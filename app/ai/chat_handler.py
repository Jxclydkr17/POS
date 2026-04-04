# app/ai/chat.py
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.database import get_db

# FASE 1: Consultas de datos reales
from app.ai.data_query_intent import try_data_query

# FASE 2: Clasificador inteligente + fuzzy matching
from app.ai.classifier import classify, ClassificationResult
from app.ai.fuzzy import (
    normalize_text as fuzzy_normalize,
    fix_typos,
    combined_similarity,
    fuzzy_match_best,
    keyword_in_text,
    any_keyword_in_text,
)
from app.ai.date_parser import extract_period_or_default

# FASE 3: Acciones ampliadas
from app.ai.action_intent import try_action_command

# FASE 5: Contexto y memoria
from app.ai.ui_context import UIContext, build_context_prompt, generate_contextual_suggestions

# FASE 6: LLM real con function calling
from app.ai.hybrid_router import route as hybrid_route, RouteDecision
from app.ai.llm_engine import call_llm, is_llm_available

# FASE 6b: Capa inteligente de interpretación
from app.ai.llm_interpreter import interpret, execute_interpreted_intent

# FASE 7: Alertas proactivas
from app.ai.proactive_alerts import get_proactive_alerts, format_alerts_as_message

router = APIRouter(prefix="/ai", tags=["ai"])

# -------------------------------------------------
# ✅ Imports reales (runtime) + TYPE_CHECKING para tipado
# -------------------------------------------------

if TYPE_CHECKING:
    from app.db.models.product import Product
    
logger = logging.getLogger(__name__)


# -----------------------------
# Short memory (por proceso)
# -----------------------------
# Estructura: { session_id: {"data": {...}, "ts": <epoch>} }
_MEMORY: Dict[str, Dict[str, Any]] = {}

# Sesión expira tras 30 minutos de inactividad
_SESSION_TTL_SECONDS: int = 30 * 60


def _purge_expired() -> None:
    """Elimina sesiones que no fueron usadas en los últimos TTL segundos.

    Se llama una vez por request, así que no hace falta ni un cron ni un
    background-task separado. El costo es un solo recorrido lineal del dict,
    que en un POS con decenas de sesiones es despreciable.
    """
    now = time.monotonic()
    expired = [
        sid for sid, entry in _MEMORY.items()
        if now - entry.get("ts", 0) > _SESSION_TTL_SECONDS
    ]
    for sid in expired:
        del _MEMORY[sid]


class MemoryMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str = ""
    pending_action: Optional[str] = None


class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    session_id: Optional[str] = None
    memory: Optional[List[MemoryMessage]] = None  # opcional desde UI
    context: Optional[Dict[str, Any]] = None       # FASE 5: contexto UI


class ChatResponse(BaseModel):
    reply_text: str
    cards: List[Dict[str, Any]] = Field(default_factory=list)
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)  # FASE 4: chips sugeridos
    session_id: str
    memory: List[MemoryMessage] = Field(default_factory=list)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _parse_qty(text: str) -> Optional[int]:
    m = re.search(r"\b(agrega|agregá|agregar)\s+(\d+)\b", text, flags=re.I)
    if not m:
        return None
    try:
        return max(1, min(999, int(m.group(2))))
    except Exception:
        return None


def _extract_search_term(text: str) -> Optional[str]:
    """FASE 2: Extrae término de búsqueda con tolerancia a typos en el verbo."""
    # Intentar regex clásico primero
    m = re.search(r"\b(busca|buscar|buscame|búscame|encuentra|encontrá)\s+(.+)$", text, flags=re.I)
    if m:
        term = m.group(2).strip()
        term = re.sub(r"[\?\!\.]$", "", term).strip()
        return term or None

    # FASE 2: Fuzzy - detectar variantes de "busca" con typos
    words = text.lower().split()
    for i, w in enumerate(words):
        if keyword_in_text("buscar", w, threshold=0.72) or keyword_in_text("busca", w, threshold=0.72):
            rest = " ".join(words[i + 1:]).strip()
            rest = re.sub(r"[\?\!\.]$", "", rest).strip()
            return rest or None

    return None


def _is_open_intent(text: str) -> bool:
    """FASE 2: Detecta intención de abrir con tolerancia a typos."""
    if re.search(r"\b(abr(i|í)r|abre|abrime|abríme|ver|mostra|mostrar)\b", text, flags=re.I):
        return True
    # Fuzzy fallback
    return any_keyword_in_text(["abrir", "abre", "mostrar"], text, threshold=0.75)


def _is_add_intent(text: str) -> bool:
    """FASE 2: Detecta intención de agregar con tolerancia a typos."""
    if re.search(r"\b(agrega|agregá|agregar|met(e|é)r|meter|añad(i|í)r|añade)\b", text, flags=re.I):
        return True
    # Fuzzy fallback
    return any_keyword_in_text(["agregar", "agrega", "meter", "añadir"], text, threshold=0.75)


def _search_customer_intent_action(text_norm: str) -> dict | None:
    """
    Clientes SOLO si:
      - el texto menciona 'cliente(s)' explícitamente, o
      - el comando es 'busca a <nombre>' / 'buscar a <nombre>'
    Así, 'busca carbolina' queda libre para productos.
    """

    # Caso 1: menciona cliente(s)
    if re.search(r"\bclientes?\b", text_norm, re.I):
        m = re.search(
            r"\b(busca|buscar)\s+(?:a\s+)?(?:al\s+)?(?:el\s+)?(?:cliente|clientes)\s+(.+?)\s*$",
            text_norm,
            re.I,
        )
        if not m:
            return None
        q = (m.group(2) or "").strip()
        return {"type": "navigate", "module": "customers", "query": q} if q else None

    # Caso 2: "busca a <nombre>" (sin decir cliente)
    m = re.search(r"\b(busca|buscar)\s+a\s+(.+?)\s*$", text_norm, re.I)
    if not m:
        return None

    q = (m.group(2) or "").strip()
    return {"type": "navigate", "module": "customers", "query": q} if q else None


def _is_credit_question(text_norm: str) -> bool:
    """Preguntas de 'debe algo / tiene crédito / saldo pendiente'."""
    return bool(re.search(
        r"\b("
        r"debe|deuda|deudas|deb(e|és)|pendiente|pendientes|saldo|"
        r"fiado|fiados|cr[eé]dito|tiene cr[eé]dito"
        r")\b",
        text_norm,
        re.I
    ))


def _wants_open_credit_view(text_norm: str) -> bool:
    """Solo navegar si lo piden explícito."""
    return bool(re.search(r"\b(abr(i|í)r|abre|ver|mostra|mostrar|enseñ(a|á)me)\b", text_norm, re.I))


def _extract_customer_for_credit_question(text_raw: str) -> Optional[str]:
    """
    Soporta:
      - "¿este cliente debe algo?"
      - "¿el cliente Randall debe algo?"
      - "debe algo Randall?"
      - "crédito de Randall"
      - "saldo (de) Randall" / "deuda (de) Randall" / "pendiente(s) de Randall"
      - "Randall debe algo" (nombre antes del verbo)
    """
    t = (text_raw or "").strip()

    def _clean(s: str) -> Optional[str]:
        s = re.sub(r"[¿\?\.!]+$", "", (s or "").strip()).strip()
        return s or None

    # "este cliente"
    if re.search(r"\b(este|esta)\s+cliente\b", t, re.I):
        return "__CURRENT__"

    # "cliente X" — para antes de "debe" u otro verbo
    m = re.search(r"\bcliente\s+(.+?)(?:\s+debe|\?|$)", t, re.I)
    if m:
        return _clean(m.group(1))

    # "crédito de X"
    m = re.search(r"\bcr[eé]dito\s+de\s+(.+?)(?:\?|$)", t, re.I)
    if m:
        return _clean(m.group(1))

    # NUEVO A) "saldo (de) X" / "deuda (de) X" / "pendiente(s) (de) X"
    m = re.search(
        r"\b(saldo|deuda|pendientes?)\s+(?:de\s+)?(.+?)(?:\?|$)",
        t, re.I
    )
    if m:
        return _clean(m.group(2))

    # "debe algo" SOLO (sin nombre) → cliente actual
    if re.fullmatch(r"(¿\s*)?debe\s+algo\s*(\?)?", t.strip(), re.I):
        return "__CURRENT__"

    # NUEVO B) "X debe (algo/plata/dinero)?" — nombre ANTES del verbo
    m = re.match(
        r"^[¿\s]*(.+?)\s+debe(?:\s+(?:algo|plata|dinero))?\s*[\.!\?]*\s*$",
        t, re.I
    )
    if m:
        return _clean(m.group(1))

    # "debe X" o "debe algo X"
    m = re.search(r"\bdebe(?:\s+algo)?\s+(.+?)(?:\?|$)", t, re.I)
    if m:
        return _clean(m.group(1))


def _find_customer_best_match(db: Session, query: str):
    """
    FASE 2: Búsqueda de clientes con fuzzy matching.
    1) ILIKE normal
    2) Si no encuentra, fuzzy contra clientes activos
    Devuelve (customer_obj, match_count)
    """
    from app.db.models.customer import Customer

    q = (query or "").strip()
    if not q:
        return None, 0

    # 1) ILIKE normal
    rows = (
        db.query(Customer)
        .filter(Customer.name.ilike(f"%{q}%"))
        .order_by(Customer.name.asc())
        .limit(10)
        .all()
    )

    if rows:
        # exact match normalizado primero
        qn = _normalize(q)
        for c in rows:
            if _normalize(getattr(c, "name", "")) == qn:
                return c, len(rows)
        return rows[0], len(rows)

    # 2) FASE 2: Fuzzy matching
    # Corregir typos y reintentar ILIKE
    q_fixed = fix_typos(q.lower())
    if q_fixed != q.lower():
        rows = (
            db.query(Customer)
            .filter(Customer.name.ilike(f"%{q_fixed}%"))
            .order_by(Customer.name.asc())
            .limit(10)
            .all()
        )
        if rows:
            return rows[0], len(rows)

    # 3) Fuzzy contra todos los clientes activos
    all_customers = (
        db.query(Customer)
        .filter(Customer.is_active == True)
        .limit(200)
        .all()
    )

    if not all_customers:
        return None, 0

    best_customer = None
    best_score = 0.0

    for c in all_customers:
        name = getattr(c, "name", "") or ""
        score = combined_similarity(q, name)
        if score > best_score:
            best_score = score
            best_customer = c

    # Solo retornar si el score es razonable
    if best_customer and best_score >= 0.50:
        return best_customer, 1

    return None, 0


def _get_last_sale_for_customer(db: Session, customer_id: int):
    """Obtiene la última venta de un cliente."""
    from app.db.models.sale import Sale
    return (
        db.query(Sale)
        .filter(Sale.customer_id == customer_id)
        .order_by(Sale.created_at.desc())
        .first()
    )



def _product_to_card(p: Any, *, suggested: bool = False) -> Dict[str, Any]:
    return {
        "id": getattr(p, "id", None),
        "code": getattr(p, "code", "") or "",
        "title": getattr(p, "name", "") or "",
        "price": getattr(p, "price", None),
        "stock": getattr(p, "stock", None),
        "suggested": bool(suggested),
    }


def _format_choice_line(i: int, c: dict, suggested: bool = False) -> str:
    """Formatea una línea de opción con etiquetas de stock y sugerencia."""
    name = c.get("name", "—")
    price_val = c.get("price")
    stock_val = c.get("stock")

    price = f"₡{price_val:.2f}" if isinstance(price_val, (int, float)) else "—"
    stock = stock_val if stock_val is not None else "—"

    # etiquetas
    tags = []
    if isinstance(stock_val, (int, float)) and stock_val <= 0:
        tags.append("❌ SIN STOCK")
    if suggested:
        tags.append("⭐ sugerido")

    tag_txt = f"  {'  '.join(tags)}" if tags else ""
    return f"{i}) {name} — {price} — stock {stock}{tag_txt}"


def _format_price_crc(v: Any) -> str:
    try:
        return f"₡{float(v):.2f}"
    except Exception:
        return "—"


def _make_recommendation_text(choice: dict) -> str:
    name = choice.get("name", "—")
    price_txt = _format_price_crc(choice.get("price"))
    stock = choice.get("stock")
    stock_txt = str(stock) if stock is not None else "—"
    return f"Te recomiendo **{name}** ({price_txt}, stock {stock_txt}). ¿Lo agrego? (sí / no)"


def _clear_pendings(memory: List[MemoryMessage], *actions: str) -> List[MemoryMessage]:
    for a in actions:
        memory = _clear_pending(memory, a)
    return memory


def _best_in_stock_index(choices: list[dict]) -> int | None:
    """Devuelve el índice (0-based) de la primera opción con stock > 0."""
    for idx, c in enumerate(choices):
        s = c.get("stock")
        if isinstance(s, (int, float)) and s > 0:
            return idx
    return None


def _alt_query_from_name(name: str) -> str:
    """
    Normaliza un nombre de producto para buscar alternativas.
    Quita medidas tipo 1/16, 3/16, 1/8, números sueltos, etc.
    """
    t = (name or "").lower()

    # quitar fracciones tipo 1/16, 3/16, 1/8, etc.
    t = re.sub(r"\b\d+\s*/\s*\d+\b", " ", t)

    # quitar números sueltos (ej: 50, 12v)
    t = re.sub(r"\b\d+\b", " ", t)

    # quitar palabras muy comunes
    t = re.sub(r"\b(de|del|la|el|para|por|con|al|a)\b", " ", t)

    # normalizar espacios
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _make_choice_dicts(products) -> list[dict]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "code": getattr(p, "code", None),
            "price": float(p.price) if getattr(p, "price", None) is not None else None,
            "stock": getattr(p, "stock", None),
        }
        for p in products
    ]


def _extract_period(text: str) -> str | None:
    """Extrae periodo de tiempo mencionado en el texto."""
    t = (text or "").lower()
    if re.search(r"\b(hoy|día|diario)\b", t):
        return "day"
    if re.search(r"\b(semana|semanal)\b", t):
        return "week"
    if re.search(r"\b(mes|mensual)\b", t):
        return "month"
    return None


def _smart_alerts_intent(text_raw: str) -> dict | None:
    """
    Retorna:
      {
        "reply": str,
        "actions": list[dict]
      }
    o None si no aplica.
    """
    t = (text_raw or "").strip().lower()
    if not t:
        return None

    # -----------------------------
    # A) STOCK BAJO / POR AGOTARSE
    # -----------------------------
    # Si habla de ventas, NO es stock bajo (evitar confusión con "se vendió poco")
    is_sales_context = bool(re.search(r"\b(vend|ventas?)\b", t))
    
    # Patrones directos de stock bajo
    direct_stock_patterns = r"\b(stock\s*bajo|poco\s*stock|sin\s*stock|inventario\s*bajo|agotad)\b"
    
    # Indicadores de escasez (requieren contexto de productos)
    scarcity_indicators = r"(hay\s*(poco|poca)s?|quedan?\s*(poco|poca)s?|se\s*(est[aá]n?\s*)?(acab|agot)|por\s*agotarse)"
    product_context = r"\b(productos?|inventario|stock|art[ií]culos?)\b"
    
    # Detectar stock bajo si:
    # 1) NO habla de ventas Y tiene patrón directo de stock, O
    # 2) Tiene indicador de escasez Y menciona productos/inventario
    has_direct_stock = re.search(direct_stock_patterns, t)
    has_scarcity_with_products = (
        re.search(scarcity_indicators, t) and re.search(product_context, t)
    )
    
    if not is_sales_context and (has_direct_stock or has_scarcity_with_products):
        return {
            "reply": "📦 Veo que querés revisar inventario crítico. Te abro **Productos** filtrado a **stock bajo (≤3)**.",
            "actions": [
                {"type": "navigate", "module": "products", "filter": "low_stock"}
            ]
        }

    # -----------------------------
    # B) DASHBOARD / ESTADO GENERAL / RESUMEN
    # -----------------------------

    # ⚡ Si pide "resumen" con periodo específico (mes, semana, año, ayer),
    #    NO es dashboard → dejar que fluya a data_queries para respuesta con datos reales.
    _resumen_with_period = r"\b(resumen|reporte|como\s*(va|fue|estuvo|anduvo)(\s+el|\s+la)?)\s+(del?\s*)?(mes|semana|la\s*semana|este\s*mes|esta\s*semana|año|este\s*año|ayer|la\s*semana\s*pasada|el\s*mes\s*pasado|mensual|semanal)\b"
    if re.search(_resumen_with_period, t, re.I):
        return None  # → será manejado por try_data_query con datos reales

    # Familia 1: alertas y crítico
    _dashboard_critical = r"\b(algo\s*cr[ií]tico|qu[eé]\s*hay\s*cr[ií]tico|alertas?|qu[eé]\s*debo\s*revisar|qu[eé]\s*deberia\s*revisar|algo\s*urgente|qu[eé]\s*hay\s*pendiente|qu[eé]\s*tengo\s*que\s*revisar)|algo\s*por\s*revisar\b"
    # Familia 2: estado / cómo vamos
    _dashboard_status   = r"\b(estado\s*(?:actual|general|del?\s*d[ií]a|hoy)?|c[oó]mo\s*(est[aá]\s*(todo|el\s*neg[o0]cio)|vamos|andamos?)|qu[eé]\s*tal\s*todo)\b"
    # Familia 3: resumen / overview / panorama — solo "resumen del día" o "resumen" solo (sin periodo)
    _dashboard_overview = r"\b(resumen\s+del?\s*d[ií]a|overview|panorama|situaci[oó]n(\s*actual)?|dame\s*un\s*resumen\s+del?\s*d[ií]a)\b"
    # Familia 3b: "resumen" solo (sin nada detrás) → dashboard
    _dashboard_resumen_solo = r"\bresumen\s*$"
    # Familia 4: ir al dashboard explícito
    _dashboard_explicit = r"\b(dashboard|panel(\s*principal)?|tablero)\b"

    if re.search(
        f"({_dashboard_critical}|{_dashboard_status}|{_dashboard_overview}|{_dashboard_resumen_solo}|{_dashboard_explicit})",
        t,
        re.I
    ):
        return {
            "reply": "🚨 Te abro el **Dashboard** para ver el estado general (stock, créditos, caja, ventas) en un vistazo.",
            "actions": [
                {"type": "navigate", "module": "dashboard"}
            ]
        }

    # -----------------------------
    # C) "SE VENDIÓ POCO" (low-sellers)
    # -----------------------------
    if re.search(r"\b(se\s*vend(i|ió|io)\s*poco|poco\s*vendido|bajas?\s*ventas|ventas?\s*bajas?)\b", t):
        period = _extract_period(t) or "week"

        # Para semana/mes: abrir analytics
        if period in ("week", "month"):
            return {
                "reply": f"📉 Te abro **Analíticas** para revisar lo más flojo de este **{'mes' if period=='month' else 'semana'}**.",
                "actions": [
                    {"type": "navigate", "module": "analytics", "period": period}
                ]
            }

        # Hoy: reporte del día
        return {
            "reply": "📉 Para ver ventas bajas de hoy, te abro el **Reporte del día**.",
            "actions": [
                {"type": "navigate", "module": "daily_report"}
            ]
        }

    return None


def _keywords_from_name(name: str) -> list[str]:
    """
    Convierte un nombre a keywords útiles para ranking.
    - quita fracciones/números
    - quita conectores comunes
    - devuelve tokens únicos (>=3 chars)
    """
    t = (name or "").lower()
    t = re.sub(r"\b\d+\s*/\s*\d+\b", " ", t)      # 1/16
    t = re.sub(r"\b\d+\b", " ", t)               # 50
    t = re.sub(r"[^\w\s]", " ", t)               # signos
    t = re.sub(r"\b(de|del|la|el|para|por|con|al|a)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    tokens = [x for x in t.split() if len(x) >= 3]
    # únicos conservando orden
    seen = set()
    out = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _alt_score(candidate_name: str, keywords: list[str]) -> int:
    """
    Score simple:
    +3 si keyword aparece como palabra completa
    +1 si aparece como substring
    """
    text = (candidate_name or "").lower()
    words = set(re.findall(r"\w+", text))
    score = 0
    for kw in keywords:
        if kw in words:
            score += 3
        elif kw in text:
            score += 1
    return score


def _rank_alternatives(alt_products, original_name: str):
    """
    Ordena alternativas por similitud y luego por stock desc.
    """
    kws = _keywords_from_name(original_name)

    def key_fn(p):
        s = getattr(p, "stock", 0) or 0
        score = _alt_score(getattr(p, "name", ""), kws)
        # orden descendente (score, stock)
        return (score, s)

    return sorted(alt_products, key=key_fn, reverse=True)


def search_products(db: "Session", query: str, limit: int = 8) -> List[Any]:
    """
    Busca productos por:
    1) código/barcode exacto
    2) LIKE en nombre/código/barcode

    Nota: este endpoint asume que SQLAlchemy y modelos están disponibles en runtime.
    Si no lo están, get_db() levantará RuntimeError.
    """
    q = (query or "").strip()
    if not q:
        return []

    # imports runtime (para no depender de variables "None" del bloque TYPE_CHECKING)
    from sqlalchemy import or_ as sa_or_, func as sa_func
    from app.db.models.product import Product as ProductModel

    # 1) exact by code/barcode
    exact = (
        db.query(ProductModel)
        .filter(sa_or_(ProductModel.code == q, ProductModel.barcode == q))
        .order_by(ProductModel.id.desc())
        .limit(limit)
        .all()
    )
    if exact:
        return exact

    # 2) LIKE on name/code/barcode (case-insensitive)
    like = f"%{q}%"
    return (
        db.query(ProductModel)
        .filter(
            sa_or_(
                sa_func.lower(ProductModel.name).like(sa_func.lower(like)),
                sa_func.lower(ProductModel.code).like(sa_func.lower(like)),
                sa_func.lower(ProductModel.barcode).like(sa_func.lower(like)),
            )
        )
        .order_by(ProductModel.id.desc())
        .limit(limit)
        .all()
    )


def search_products_fuzzy(db: "Session", query: str, limit: int = 8) -> List[Any]:
    """
    FASE 2: Búsqueda de productos con fuzzy matching.
    1) Intenta búsqueda exacta/LIKE (rápida)
    2) Si no encuentra, corrige typos y reintenta
    3) Si aún no encuentra, fuzzy match contra productos activos
    """
    # 1) Búsqueda normal primero
    results = search_products(db, query, limit=limit)
    if results:
        return results

    # 2) Corregir typos y reintentar
    query_fixed = fix_typos(query.lower())
    if query_fixed != query.lower():
        results = search_products(db, query_fixed, limit=limit)
        if results:
            return results

    # 3) Fuzzy: buscar contra todos los productos activos
    # (limitado a 500 para no matar performance)
    from app.db.models.product import Product as ProductModel

    all_products = (
        db.query(ProductModel)
        .filter(ProductModel.is_active == True)
        .limit(500)
        .all()
    )

    if not all_products:
        return []

    # Calcular similitud y ordenar
    scored = []
    for p in all_products:
        name = getattr(p, "name", "") or ""
        score = combined_similarity(query, name)
        # También comparar contra código
        code = getattr(p, "code", "") or ""
        if code:
            code_score = combined_similarity(query, code)
            score = max(score, code_score)
        if score >= 0.40:  # threshold mínimo
            scored.append((p, score))

    scored.sort(key=lambda x: -x[1])
    return [p for p, _ in scored[:limit]]


# ------------------------------------------------------------------
# Helpers de memoria por-sesión (con TTL)
# ------------------------------------------------------------------
def _remember(session_id: str, key: str, value: Any) -> None:
    entry = _MEMORY.setdefault(session_id, {"data": {}, "ts": time.monotonic()})
    entry["data"][key] = value
    entry["ts"] = time.monotonic()   # refreshear timestamp cada vez que se escribe


def _recall(session_id: str, key: str, default: Any = None) -> Any:
    entry = _MEMORY.get(session_id)
    if entry is None:
        return default
    entry["ts"] = time.monotonic()   # refreshear al leer también
    return entry["data"].get(key, default)


def _push_turn(memory: List[MemoryMessage], role: str, content: str, max_turns: int = 8) -> List[MemoryMessage]:
    memory = list(memory or [])
    memory.append(MemoryMessage(role=role, content=content))
    if len(memory) > max_turns:
        memory = memory[-max_turns:]
    return memory


def _get_sale_state(session_id: str) -> Dict[str, Any]:
    state = _recall(session_id, "sale_state")
    if state is None:
        state = {
            "items": [],
            "customer_name": None,
            "payment_method": None,
        }
        _remember(session_id, "sale_state", state)
    return state


def _save_sale_state(session_id: str, state: Dict[str, Any]) -> None:
    _remember(session_id, "sale_state", state)



def _reset_sale_state(session_id: str):
    """Resetea el sale_state a valores iniciales después de confirmar o cancelar una venta."""
    sale_state = _get_sale_state(session_id)
    sale_state["items"] = []
    sale_state["customer_name"] = None
    sale_state["payment_method"] = None
    _save_sale_state(session_id, sale_state)


def _extract_customer(text: str) -> Optional[str]:
    """
    Extrae nombre del cliente, limpiando métodos de pago.
    Soporta cualquier orden: "cliente X por Y" o "por Y al cliente X"
    FASE 2: limpia variantes con typos de métodos de pago.
    """
    m = re.search(
        r"\b(cliente|a nombre de)\s+(.+?)(?:\s+por\b|\s+con\b|\s+y\s+paga|\s*$)",
        text,
        re.I
    )
    if not m:
        return None
    
    # Capturar todo después de "cliente"
    customer = m.group(2).strip()
    
    # Limpiar palabras de método de pago del nombre (con variantes typos)
    _pay_re = r"\b(sinpe|sinpee|simpe|snipe|efectivo|efetivo|cash|tarjeta|tarjea|tajeta|datáfono|datafono|card|cr[eé]dito|credito)\b.*$"
    customer = re.sub(_pay_re, "", customer, flags=re.I).strip()
    
    return customer if customer else None


def _extract_customer_loose(text: str) -> Optional[str]:
    """
    Extrae cliente en frases tipo:
      - "... al cliente randall"
      - "... a randall por sinpe"
    Usa _extract_customer primero (más seguro). Si no, intenta con "a <nombre>".
    FASE 2: limpia variantes con typos de métodos de pago.
    """
    c = _extract_customer(text)
    if c:
        return c

    # " a randall por sinpe"
    m = re.search(r"\b a\s+(.+?)(?:\s+por\b|\s+con\b|\s*$)", text, re.I)
    if not m:
        return None

    name = (m.group(1) or "").strip()
    # limpiar posibles métodos de pago colados (con variantes typos)
    _pay_re = r"\b(sinpe|sinpee|simpe|snipe|efectivo|efetivo|cash|tarjeta|tarjea|tajeta|datáfono|datafono|card|cr[eé]dito|credito)\b.*$"
    name = re.sub(_pay_re, "", name, flags=re.I).strip()
    return name or None


def _strip_tail_customer_payment(text: str) -> str:
    """
    Quita cola tipo:
      ' a randall por sinpe'
      ' por sinpe'
      ' cliente randall por efectivo'
    para dejar solo la parte de items.
    FASE 2: incluye variantes con typos de métodos de pago.
    """
    t = text

    # quitar "por <pago>" al final (con variantes de typos)
    _pay_variants = r"(sinpe|sinpee|simpe|snipe|efectivo|efetivo|cash|tarjeta|tarjea|tajeta|datáfono|datafono|card|cr[eé]dito|credito)"
    t = re.sub(rf"\s+por\s+{_pay_variants}\b.*$", "", t, flags=re.I)

    # quitar "cliente <x>" al final
    t = re.sub(r"\s+\b(?:a|al)?\s*(?:cliente|a nombre de)\s+.+$", "", t, flags=re.I)

    # quitar " a <cliente>" al final
    t = re.sub(r"\s+\b(a|al)\s+[^,]+$", "", t, flags=re.I)

    return t.strip()


def _extract_multi_sell_items(text_raw: str) -> list[dict]:
    """
    Parseo simple:
      'vende 2 pegamento pvc y 1 cinta aislante ...'
    Devuelve: [{"qty":2,"name":"pegamento pvc"}, ...]
    
    IMPORTANTE: Esta función solo parsea los ítems, NO extrae cliente/pago.
    El cliente/pago se extraen por separado en el flujo principal.
    """
    # tomar desde "vende"
    m = re.search(r"\b(vende|vendé|vender)\b\s+(.+)$", text_raw, re.I)
    if not m:
        return []

    tail = (m.group(2) or "").strip()
    
    # IMPORTANTE: limpiar cliente/pago DESPUÉS de tomar el texto completo
    # para que no interfiera con la extracción de cliente que se hace por separado
    tail = _strip_tail_customer_payment(tail)

    # Normalizar conectores: coma -> ' y '
    tail = tail.replace(",", " y ")

    # Patrón: <qty> <nombre> (hasta antes de " y <qty> " o fin)
    pattern = re.compile(r"\b(\d+)\s+(.+?)(?=(?:\s+y\s+\d+\s+)|$)", re.I)
    items = []
    for mm in pattern.finditer(tail):
        qty_s = mm.group(1)
        name = (mm.group(2) or "").strip()
        # limpiar "de" inicial
        name = re.sub(r"^\bde\b\s+", "", name, flags=re.I).strip()
        try:
            qty = max(1, min(999, int(qty_s)))
        except Exception:
            qty = 1
        if name:
            items.append({"qty": qty, "name": name})

    return items


def _extract_payment_method(text: str) -> Optional[str]:
    """FASE 2: Extrae método de pago con tolerancia a typos."""
    t = (text or "").lower()
    # Sinpe (con variantes)
    if any_keyword_in_text(["sinpe", "sinpee", "simpe", "snipe"], t, threshold=0.75):
        return "sinpe"
    # Efectivo
    if any_keyword_in_text(["efectivo", "efetivo", "cash"], t, threshold=0.75):
        return "cash"
    # Tarjeta / datáfono
    if any_keyword_in_text(["tarjeta", "datáfono", "datafono", "card", "tajeta", "tarjea"], t, threshold=0.75):
        return "card"
    # Crédito como método de pago
    if re.search(r"\bpor\s+cr[eé]dito\b", t, re.I):
        return "credito"
    return None


def _extract_qty_generic(text: str) -> Optional[int]:
    m = re.search(r"\b(\d+)\b", text)
    if not m:
        return None
    try:
        return max(1, min(999, int(m.group(1))))
    except Exception:
        return None


def _extract_qty_sell(text: str) -> Optional[int]:
    """
    Extrae qty SOLO si viene justo después de 'vende/vendé/vender'.
    Evita agarrar números de medidas tipo 1/8.
    """
    m = re.search(r"\b(vende|vendé|vender)\s+(\d+)\b", text, re.I)
    if not m:
        return None
    try:
        return max(1, min(999, int(m.group(2))))
    except Exception:
        return None


def _extract_confirm_intent(text: str) -> Optional[str]:
    """
    Devuelve:
      - "print" si el user pide imprimir
      - "no_print" si pide confirmar sin imprimir
      - None si no pidió confirmar en el mismo mensaje
    """
    t = text.lower()

    # intenciones de confirmar
    wants_confirm = bool(re.search(r"\b(confirmar|confirmá|confirmar ya|dale|ok|listo)\b", t, re.I))
    if not wants_confirm:
        return None

    # imprimir / no imprimir
    if re.search(r"\b(imprim(i|í)|imprime|ticket|factura)\b", t, re.I):
        return "print"
    if re.search(r"\b(sin imprimir|no imprimas|no imprimir)\b", t, re.I):
        return "no_print"

    # default seguro: confirmar sin imprimir
    return "no_print"


def _extract_product_name(text: str) -> Optional[str]:
    """
    Extrae producto desde frases tipo:
    - vende 2 de cemento
    - vende 2 cemento
    - vende resistol 1/8
    """
    m = re.search(
        r"\b(vende|vendé|vender|agrega|agregá)\s+(?:(\d+)\s+(?:de\s+)?)?(.+?)(?:\s+al\b|\s+para\b|\s+por\b|\s*$)",
        text,
        re.I
    )
    if not m:
        return None

    # grupo 3 = producto
    product = (m.group(3) or "").strip()
    return product or None



def _extract_remove_name(text: str) -> Optional[str]:
    t = (text or "").strip()

    # quita/elimina/saca/remueve X (opcional "del carrito")
    m = re.search(
        r"\b(quita|quitá|elimina|eliminá|saca|sacá|remueve|remové|remove|delete)\b\s+(.*)$",
        t,
        re.I
    )
    if not m:
        return None

    rest = (m.group(2) or "").strip()

    # si es "el último" -> eso es undo, no remove-by-name
    if re.search(r"\b(último|ultimo)\b", rest, re.I):
        return None

    # limpiar colas comunes
    rest = re.sub(r"\b(del|de|del\s+carrito|del\s+carro|del\s+cart|del\s+carrito\.)\b", "", rest, flags=re.I).strip()
    rest = re.sub(r"\s+", " ", rest).strip(" .,")

    return rest or None



def _extract_decrement_name_qty(text: str):
    """
    Match:
      - 'quita 2 emicina 50'
      - 'elimina 3 pegamento pvc'
      - 'saca 1 resistol'
    Retorna (name, qty) o (None, None)
    """
    t = (text or "").strip()

    m = re.search(
        r"\b(quita|quitá|elimina|eliminá|saca|sacá|remueve|remové|remove|delete)\b\s+(\d+)\s+(.+)$",
        t,
        re.I
    )
    if not m:
        return (None, None)

    qty = int(m.group(2))
    name = (m.group(3) or "").strip()
    name = re.sub(r"\b(del\s+carrito|del\s+carro|del\s+cart)\b", "", name, flags=re.I).strip(" .,")

    if not name:
        return (None, None)

    return (name, qty)


# ------------------------------------------------------------------
# 🧠 Funciones auxiliares para manejar estados pendientes
# ------------------------------------------------------------------
def _has_pending(memory: List[MemoryMessage], action: str) -> bool:
    """Verifica si hay una acción pendiente en la memoria."""
    return any(
        m.role == "system" and m.pending_action == action 
        for m in memory
    )


def _clear_pending(memory: List[MemoryMessage], action: str) -> List[MemoryMessage]:
    """Elimina el estado pendiente de la memoria."""
    return [
        m for m in memory 
        if not (m.role == "system" and m.pending_action == action)
    ]
    

def _get_missing_sale_fields(state: dict) -> list[str]:
    missing = []
    if not state["items"]:
        missing.append("items")
    if not state["payment_method"]:
        missing.append("payment_method")
    return missing



def _sales_reports_intent_action(text_norm: str) -> dict | None:
    """
    Devuelve acción navigate para:
      - ventas hoy   -> reporte diario
      - ventas semana -> registro ventas lunes..hoy
      - ventas mes    -> registro ventas 1..hoy
    """
    # match flexible: "ventas hoy", "ventas de hoy", etc.
    m = re.search(r"\bventas(?:\s+de)?\s+(hoy|semana|mes)\b", text_norm, re.I)
    if not m:
        return None

    kind = (m.group(1) or "").lower()
    today = date.today()

    if kind == "hoy":
        return {"type": "navigate", "module": "daily_report"}

    if kind == "semana":
        start = today - timedelta(days=today.weekday())  # lunes
        return {
            "type": "navigate",
            "module": "sales_reports",
            "start_date": start.isoformat(),
            "end_date": today.isoformat(),
            "period": "week",
        }

    if kind == "mes":
        start = today.replace(day=1)
        return {
            "type": "navigate",
            "module": "sales_reports",
            "start_date": start.isoformat(),
            "end_date": today.isoformat(),
            "period": "month",
        }

    return None

def _low_stock_intent_action(text_norm: str) -> dict | None:
    # Excluir contexto de ventas para no pisar "ventas bajas" / "se vendió poco"
    if re.search(r"\b(vend[ií]|ventas?)\b", text_norm, re.I):
        return None

    # Familia 1: frases directas de inventario crítico
    _direct = (
        r"\b("
        r"stock\s*bajo|lista\s*stock\s*bajo|productos?\s*stock\s*bajo|"
        r"inventario\s*bajo|productos?\s*cr[ií]ticos?|inventario\s*cr[ií]tico|"
        r"productos?\s*por\s*agotarse|por\s*acabarse|sin\s*stock|"
        r"poco\s*stock|agotad[oa]s?"
        r")\b"
    )

    # Familia 2: frases de reposición
    _replenish = (
        r"\b("
        r"qu[eé]\s*(deber[ií]a|deber[ií]amos|tengo\s*que|hay\s*que|falta)\s*comprar|"
        r"qu[eé]\s*(tengo\s*que|hay\s*que)\s*reponer|"
        r"qu[eé]\s*falta\s*(en\s*)?(?:inventario|stock|productos?)?|"
        r"qu[eé]\s*falta|"
        r"qu[eé]\s*hace\s*falta"
        r")\b"
    )

    # Familia 3: preguntas naturales tipo dueño de negocio
    _natural = (
        r"\b("
        r"qu[eé]\s*productos?\s*(est[aá]n?\s*)?(por\s*agotarse|por\s*acabarse|escasos?|cr[ií]ticos?)|"
        r"qu[eé]\s*se\s*est[aá]\s*acabando|"
        r"qu[eé]\s*est[aá]\s*(escaso|cr[ií]tico|por\s*agotarse|por\s*acabarse)|"
        r"qu[eé]\s*debo\s*revisar\s*(en\s*)?(inventario|stock)|"
        r"qu[eé]\s*deberia\s*revisar\s*(en\s*)?(inventario|stock)|"
        r"qu[eé]\s*productos?\s*faltan|"
        r"qu[eé]\s*productos?\s*hacen\s*falta"
        r")\b"
    )

    if re.search(f"({_direct}|{_replenish}|{_natural})", text_norm, re.I):
        return {
            "type": "navigate",
            "module": "products",
            "filter": "low_stock",
            "threshold": 3,
        }
    return None


# ------------------------------------------------------------------
# FASE 5: Handler de preguntas sobre contexto actual
# ------------------------------------------------------------------
def _handle_context_questions(text_norm: str, ctx: UIContext) -> Optional[str]:
    """
    Responde preguntas sobre el contexto actual:
    - ¿En qué pantalla estoy?
    - ¿Qué tengo en el carrito?
    - ¿Quién es el cliente actual?
    """
    # ¿En qué pantalla estoy?
    if re.search(r"\b(qu[eé]\s+pantalla|d[oó]nde\s+estoy|en\s+qu[eé]\s+estoy|qu[eé]\s+secci[oó]n)\b", text_norm):
        screen = ctx.screen_label()
        return f"📍 Estás en **{screen}**."

    # ¿Qué tengo en el carrito?
    if re.search(r"\b(qu[eé]\s+tengo\s+en\s+(?:el\s+)?carrito|carrito\s+actual|mi\s+carrito|qu[eé]\s+llevo|qu[eé]\s+hay\s+en\s+(?:el\s+)?carrito)\b", text_norm):
        if not ctx.has_cart():
            return "🛒 Tu carrito está vacío. Decí *busca X* o *vende X* para agregar productos."

        lines = [f"🛒 **Carrito actual** ({ctx.cart_count} producto{'s' if ctx.cart_count != 1 else ''}):"]
        for item in ctx.cart_items:
            disc = ""
            if item.discount_percent > 0:
                disc = f" (-{item.discount_percent:.0f}%)"
            lines.append(f"  • {item.quantity}× {item.product_name} — ₡{item.unit_price:,.0f}{disc}")

        lines.append(f"  💰 **Total: ₡{ctx.cart_total:,.2f}**")
        if ctx.selected_customer_name:
            lines.append(f"  👤 Cliente: {ctx.selected_customer_name}")
        if ctx.selected_payment_method:
            lines.append(f"  💳 Pago: {ctx.selected_payment_method}")
        return "\n".join(lines)

    # ¿Quién es el cliente actual / seleccionado?
    if re.search(r"\b(qu[ié][eé]n\s+es\s+(?:el\s+)?cliente|cliente\s+(?:actual|seleccionado))\b", text_norm):
        if ctx.selected_customer_name:
            return f"👤 El cliente seleccionado es **{ctx.selected_customer_name}**."
        return "👤 No hay ningún cliente seleccionado en el punto de venta."

    # ¿Está la caja abierta?
    if re.search(r"\b(la\s+caja\s+est[aá]\s+abierta|caja\s+abierta|est[aá]\s+abierta\s+la\s+caja)\b", text_norm):
        if ctx.cash_session_open is True:
            return "🟢 Sí, la caja está **abierta**."
        elif ctx.cash_session_open is False:
            return "🔴 No, la caja está **cerrada**."
        return "🤔 No tengo info del estado de la caja ahora mismo. Decí *¿cómo está la caja?* para consultar."

    return None


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: "Session" = Depends(get_db)) -> ChatResponse:
    # Limpiar sesiones expiradas al inicio de cada request
    _purge_expired()

    session_id = req.session_id or str(uuid.uuid4())
    ui_memory = req.memory or []

    text_raw = req.text.strip()
    # FASE 2: Corregir typos comunes antes de normalizar
    text_corrected = fix_typos(text_raw)
    text = _normalize(text_corrected)

    actions: List[Dict[str, Any]] = []
    cards: List[Dict[str, Any]] = []
    reply = ""

    # -----------------------------------------
    # FASE 5: Parsear contexto UI
    # -----------------------------------------
    ui_ctx = UIContext()
    if req.context:
        try:
            ui_ctx = UIContext(**req.context)
        except Exception:
            pass  # Si el contexto viene mal, seguir sin él

    # Guardar contexto en memoria de sesión para referencia futura
    _remember(session_id, "ui_context", {
        "screen": ui_ctx.current_screen,
        "cart_count": ui_ctx.cart_count,
        "cart_total": ui_ctx.cart_total,
        "customer": ui_ctx.selected_customer_name,
        "payment": ui_ctx.selected_payment_method,
    })

    # -----------------------------------------
    # FASE 5: Preguntas sobre contexto actual
    # -----------------------------------------
    ctx_reply = _handle_context_questions(text, ui_ctx)
    if ctx_reply:
        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", ctx_reply)
        return ChatResponse(
            reply_text=ctx_reply, cards=[], actions=[],
            suggestions=generate_contextual_suggestions(ui_ctx),
            session_id=session_id, memory=out_mem,
        )

    # -----------------------------------------
    # FASE 6b: Capa inteligente de interpretación
    # Si hay LLM configurado y NO hay estados pendientes,
    # intentar interpretar la intención con el LLM ANTES
    # del regex/fuzzy. Si falla → cae al flujo legacy intacto.
    # -----------------------------------------
    _has_pending_state = any(
        _has_pending(ui_memory, a)
        for a in ("confirm_sale", "choose_product", "confirm_recommended", "await_payment")
    )

    if not _has_pending_state and is_llm_available():
        try:
            _intent = interpret(text_raw, db, ui_ctx)
            if _intent and _intent.is_actionable:
                _exec = execute_interpreted_intent(_intent, db, ui_ctx)
                if _exec:
                    logger.info(
                        f"LLM interpreter: intent={_intent.intent} "
                        f"conf={_intent.confidence:.2f} params={_intent.params}"
                    )
                    out_mem = _push_turn(ui_memory, "user", text_raw)
                    out_mem = _push_turn(out_mem, "assistant", _exec["reply_text"])
                    return ChatResponse(
                        reply_text=_exec["reply_text"],
                        cards=_exec.get("cards", []),
                        actions=_exec.get("actions", []),
                        suggestions=generate_contextual_suggestions(ui_ctx),
                        session_id=session_id,
                        memory=out_mem,
                    )
        except Exception as e:
            logger.debug(f"LLM interpreter fallthrough: {e}")
            # Silencioso — caer al flujo legacy

    # -----------------------------------------
    # 0) Navegación a stock bajo
    # -----------------------------------------
    nav = _low_stock_intent_action(text)
    if nav:
        actions.append(nav)
        reply = "Listo 👌 te abro Productos y te muestro los de stock bajo (<=3)."
        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(reply_text=reply, cards=[], actions=actions, session_id=session_id, memory=out_mem)

    # -----------------------------------------
    # 0b) Navegación a búsqueda de clientes
    # -----------------------------------------
    nav = _search_customer_intent_action(text)
    if nav:
        actions.append(nav)
        reply = f"Listo 👌 te abro Clientes y busco: {nav['query']}"
        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(reply_text=reply, cards=[], actions=actions, session_id=session_id, memory=out_mem)

    # -----------------------------------------
    # 🔄 Pago pendiente (DEBE IR ANTES QUE confirm_sale)
    # -----------------------------------------
    if _has_pending(ui_memory, "await_payment"):
        payment = _extract_payment_method(text_raw)

        if payment:
            actions.append({"type": "set_payment_method", "method": payment})

            sale_state = _get_sale_state(session_id)
            sale_state["payment_method"] = payment
            _save_sale_state(session_id, sale_state)

            ui_memory = _clear_pending(ui_memory, "await_payment")

            reply = f"Perfecto 👍 pago por **{payment.upper()}**.\n¿Confirmamos la venta?"
            ui_memory.append(
                MemoryMessage(role="system", pending_action="confirm_sale")
            )
        else:
            reply = "¿Cómo va a pagar el cliente? (sinpe, efectivo o tarjeta)"
            # mantenemos await_payment activo (no se limpia)

        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)

        return ChatResponse(
            reply_text=reply,
            cards=[],
            actions=actions,
            session_id=session_id,
            memory=out_mem
        )

    # -----------------------------------------
    # 🔄 Selección pendiente de producto (cuando hay múltiples matches)
    # -----------------------------------------
    if _has_pending(ui_memory, "choose_product"):
        sale_state = _get_sale_state(session_id)
        pending = sale_state.get("pending_sell") or {}

        choices = pending.get("choices") or []   # lista de dicts con info
        qty = int(pending.get("qty") or 1)
        customer = pending.get("customer_name")
        payment = pending.get("payment_method")

        # si por alguna razón no hay choices, limpiamos y pedimos de nuevo
        if not choices:
            ui_memory = _clear_pending(ui_memory, "choose_product")
            ui_memory = _clear_pending(ui_memory, "confirm_recommended")
            sale_state.pop("pending_sell", None)
            _save_sale_state(session_id, sale_state)

            reply = "No tengo una selección pendiente. Decime de nuevo qué querés vender 🙏"
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

        # -----------------------------------------
        # ✅ Si hay recomendación pendiente, permitir "sí/no" para agregar la ⭐ sugerida
        # -----------------------------------------
        if _has_pending(ui_memory, "confirm_recommended"):
            best_idx = _best_in_stock_index(choices)

            # Si el user dice "sí": agregar sugerido
            if re.search(r"\b(sí|si|dale|ok|okay|de una|agregá|agrega)\b", text):
                if best_idx is None:
                    ui_memory = _clear_pending(ui_memory, "confirm_recommended")
                    reply = "No tengo una recomendación con stock ahorita. Elegí una opción por número 🙏"
                    out_mem = _push_turn(ui_memory, "user", text_raw)
                    out_mem = _push_turn(out_mem, "assistant", reply)
                    return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

                chosen = choices[best_idx]

                # 🔒 Validación de stock robusta
                stock_val = chosen.get("stock")
                try:
                    s_val = float(stock_val) if stock_val is not None else 0
                except Exception:
                    s_val = 0

                if s_val <= 0:
                    ui_memory = _clear_pending(ui_memory, "confirm_recommended")
                    reply = (
                        f"⚠️ **{chosen.get('name','Ese producto')}** está **sin stock**.\n"
                        f"Elegí otra opción por número 🙏"
                    )
                    out_mem = _push_turn(ui_memory, "user", text_raw)
                    out_mem = _push_turn(out_mem, "assistant", reply)
                    return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

                # 🛒 Agregar al carrito con qty pendiente
                actions.append({"type": "add_to_cart", "product_id": chosen["id"], "qty": qty})
                sale_state["items"].append({"product_id": chosen["id"], "qty": qty})

                # 👤 Cliente
                if customer:
                    sale_state["customer_name"] = customer
                    actions.append({"type": "set_customer", "name": customer})

                # 💳 Pago
                if payment:
                    sale_state["payment_method"] = payment
                    actions.append({"type": "set_payment_method", "method": payment})

                # ✅ limpiar estados (los 2)
                ui_memory = _clear_pendings(ui_memory, "confirm_recommended", "choose_product")
                sale_state.pop("pending_sell", None)
                _save_sale_state(session_id, sale_state)

                # ✅ Mensaje "perfecto" con qty/cliente/pago
                reply_parts = [f"✅ Listo, agregué {qty} × **{chosen.get('name','')}**"]
                if customer:
                    reply_parts.append(f"a nombre de **{customer}**")
                if payment:
                    reply_parts.append(f"por **{payment.upper()}**")
                reply = " ".join(reply_parts) + "."

                missing = _get_missing_sale_fields(sale_state)
                if "payment_method" in missing:
                    reply += "\n¿Cómo va a pagar el cliente? (sinpe, efectivo o tarjeta)"
                    ui_memory.append(MemoryMessage(role="system", pending_action="await_payment"))
                else:
                    reply += "\n¿Confirmamos la venta?"
                    ui_memory.append(MemoryMessage(role="system", pending_action="confirm_sale"))

                out_mem = _push_turn(ui_memory, "user", text_raw)
                out_mem = _push_turn(out_mem, "assistant", reply)

                cards = [{
                    "id": chosen["id"],
                    "code": chosen.get("code", ""),
                    "title": chosen.get("name", ""),
                    "price": chosen.get("price"),
                    "stock": chosen.get("stock"),
                }]

                return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)

            # Si el user dice "no": quitar recomendación y seguir con selección por número
            if re.search(r"\b(no|nel|nop|mejor no|otra|ver opciones)\b", text):
                ui_memory = _clear_pending(ui_memory, "confirm_recommended")
                reply = "Dale 🙌 Elegí una opción por número."
                out_mem = _push_turn(ui_memory, "user", text_raw)
                out_mem = _push_turn(out_mem, "assistant", reply)
                return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

        # cancelar selección
        if re.search(r"\b(cancelar|cancelá|no|salir)\b", text):
            ui_memory = _clear_pendings(ui_memory, "choose_product", "confirm_recommended")
            sale_state.pop("pending_sell", None)
            _save_sale_state(session_id, sale_state)

            reply = "Listo, cancelé la selección de producto."
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

        # elegir por número
        if re.fullmatch(r"\d+", text.strip()):
            idx = int(text.strip()) - 1
            if idx < 0 or idx >= len(choices):
                reply = f"Elegí un número entre 1 y {len(choices)} (o escribí 'cancelar')."
                out_mem = _push_turn(ui_memory, "user", text_raw)
                out_mem = _push_turn(out_mem, "assistant", reply)
                return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

            chosen = choices[idx]
            product_id = chosen["id"]

            # ⚠️ Validar stock
            stock_val = chosen.get("stock")
            if isinstance(stock_val, (int, float)) and stock_val <= 0:
                reply = (
                    f"⚠️ **{chosen.get('name','Ese producto')}** está **sin stock**.\n"
                    f"Elegí otro número entre 1 y {len(choices)} (o escribí 'cancelar')."
                )
                out_mem = _push_turn(ui_memory, "user", text_raw)
                out_mem = _push_turn(out_mem, "assistant", reply)
                return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)


            # 🛒 Agregar al carrito
            actions.append({"type": "add_to_cart", "product_id": product_id, "qty": qty})
            sale_state["items"].append({"product_id": product_id, "qty": qty})

            # 👤 Cliente
            if customer:
                sale_state["customer_name"] = customer
                actions.append({"type": "set_customer", "name": customer})

            # 💳 Pago
            if payment:
                sale_state["payment_method"] = payment
                actions.append({"type": "set_payment_method", "method": payment})

            # limpiar pending
            ui_memory = _clear_pendings(ui_memory, "choose_product", "confirm_recommended")
            sale_state.pop("pending_sell", None)
            _save_sale_state(session_id, sale_state)

            # respuesta
            reply_parts = [f"✅ Agregué {qty} × **{chosen['name']}**"]
            if customer:
                reply_parts.append(f"a nombre de **{customer}**")
            if payment:
                reply_parts.append(f"por **{payment.upper()}**")
            reply = " ".join(reply_parts) + "."

            missing = _get_missing_sale_fields(sale_state)
            if "payment_method" in missing:
                reply += "\n¿Cómo va a pagar el cliente? (sinpe, efectivo o tarjeta)"
                ui_memory.append(MemoryMessage(role="system", pending_action="await_payment"))
            else:
                reply += "\n¿Confirmamos la venta?"
                ui_memory.append(MemoryMessage(role="system", pending_action="confirm_sale"))

            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)

            # cards con la opción elegida
            cards = [{
                "id": chosen["id"],
                "code": chosen.get("code", ""),
                "title": chosen.get("name", ""),
                "price": chosen.get("price"),
                "stock": chosen.get("stock"),
            }]

            return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)

        # si no es número, interpretamos como refinamiento de búsqueda (FASE 2: fuzzy)
        refined = text_raw.strip()
        results = search_products_fuzzy(db, refined, limit=5)

        if not results:
            reply = f"No encontré opciones con '{refined}'. Probá con otro nombre o escribí 'cancelar'."
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

        # actualizar choices
        choices = [{
            "id": p.id,
            "name": p.name,
            "code": p.code,
            "price": float(p.price) if p.price is not None else None,
            "stock": p.stock,
        } for p in results]

        sale_state["pending_sell"]["choices"] = choices
        _save_sale_state(session_id, sale_state)

        best_idx = _best_in_stock_index(choices)

        lines = []
        if best_idx is not None:
            rec = choices[best_idx]
            lines.append(_make_recommendation_text(rec))
            lines.append(f"Si querés otra opción, elegí 1–{len(choices)}:")
            ui_memory.append(MemoryMessage(role="system", pending_action="confirm_recommended"))
        else:
            lines.append(f"Encontré estas opciones para **{refined}**. Elegí 1–{len(choices)}:")

        for i, c in enumerate(choices, 1):
            lines.append(_format_choice_line(i, c, suggested=(best_idx == i - 1)))

        if best_idx is None:
            lines.append("\n⚠️ Ojo: todas estas opciones están sin stock.")

        reply = "\n".join(lines)

        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)

        # Marcar la card sugerida
        best_id = None
        if best_idx is not None and best_idx < len(choices):
            best_id = choices[best_idx].get("id")

        cards = []
        for p in results:
            pid = getattr(p, "id", None)
            cards.append(_product_to_card(p, suggested=(best_id is not None and pid == best_id)))

        return ChatResponse(reply_text=reply, cards=cards, actions=[], session_id=session_id, memory=out_mem)

    # -----------------------------------------
    # 🔄 Confirmación pendiente (DEBE IR PRIMERO)
    # -----------------------------------------
    if _has_pending(ui_memory, "confirm_sale"):
        
        # -----------------------------------------
        # 🔘 Manejo de botones UI (evita errores humanos)
        # -----------------------------------------
        if text_raw == "__CONFIRM__":
            actions.append({"type": "confirm_sale"})
            reply = "✅ Venta confirmada. Que Dios bendiga tu negocio 🙏"
            ui_memory = _clear_pendings(
                ui_memory,
                "confirm_sale",
                "await_payment",
                "choose_product",
                "confirm_recommended",
            )
            _reset_sale_state(session_id)
            out_mem = _push_turn(ui_memory, "user", "[Confirmado]")
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)
        
        if text_raw == "__CANCEL__":
            reply = "❌ Confirmación cancelada. La venta no fue procesada."
            ui_memory = _clear_pendings(
                ui_memory,
                "confirm_sale",
                "await_payment",
                "choose_product",
                "confirm_recommended",
            )
            _reset_sale_state(session_id)
            out_mem = _push_turn(ui_memory, "user", "[Cancelado]")
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)
        
        # -----------------------------------------
        # 💳 Permitir consultas de crédito durante confirmación
        # -----------------------------------------
        text_norm = _normalize(text_raw)
        if _is_credit_question(text_norm):
            sale_state = _get_sale_state(session_id)

            # target: si no viene nombre, usar el cliente del carrito
            target = _extract_customer_for_credit_question(text_raw)
            if target == "__CURRENT__" or (not target and sale_state.get("customer_name")):
                target = sale_state.get("customer_name")

            if not target:
                reply = (
                    "¿De cuál cliente querés revisar el saldo? "
                    "(ej: \"¿Randall debe algo?\")\n\n"
                    "¿Confirmamos la venta? (sí / no)"
                )
                out_mem = _push_turn(ui_memory, "user", text_raw)
                out_mem = _push_turn(out_mem, "assistant", reply)
                return ChatResponse(reply_text=reply, cards=[], actions=actions, session_id=session_id, memory=out_mem)

            customer, count_ = _find_customer_best_match(db, target)
            if not customer:
                reply = f"No encontré al cliente **{target}**.\n\n¿Confirmamos la venta? (sí / no)"
                out_mem = _push_turn(ui_memory, "user", text_raw)
                out_mem = _push_turn(out_mem, "assistant", reply)
                return ChatResponse(reply_text=reply, cards=[], actions=actions, session_id=session_id, memory=out_mem)

            balance = float(getattr(customer, "credit_balance", 0.0) or 0.0)

            last_sale = _get_last_sale_for_customer(db, int(customer.id))
            last_txt = ""
            if last_sale and getattr(last_sale, "created_at", None):
                try:
                    dt = last_sale.created_at.strftime("%Y-%m-%d %H:%M")
                    last_txt = f"\n🧾 Última compra: {dt} — {_format_price_crc(getattr(last_sale, 'total', 0) or 0)}"
                except Exception:
                    pass

            if balance > 0:
                reply = f"⚠️ **{customer.name}** tiene **{_format_price_crc(balance)}** pendientes.{last_txt}"
            else:
                reply = f"✅ **{customer.name}** está al día (saldo pendiente: {_format_price_crc(0)}).{last_txt}"

            # 🔁 IMPORTANTÍSIMO: no limpiamos confirm_sale; solo re-preguntamos
            reply += "\n\n¿Confirmamos la venta? (sí / no)"

            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=[], actions=actions, session_id=session_id, memory=out_mem)
        
        # -----------------------------------------
        # 🔢 Decrementar cantidad por nombre mientras estás en confirmación
        # -----------------------------------------
        name, qty = _extract_decrement_name_qty(text_raw)
        if name and qty:
            actions.append({"type": "decrement_from_cart_by_name", "name": name, "qty": qty})
            reply = f"Listo ✅ Quito {qty} de **{name}**. ¿Confirmamos la venta? (sí / no)"
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)

        # -----------------------------------------
        # 🗑️ Quitar por nombre mientras estás en confirmación
        # -----------------------------------------
        remove_name = _extract_remove_name(text_raw)
        if remove_name:
            actions.append({"type": "remove_from_cart_by_name", "name": remove_name})
            reply = f"Listo ✅ Quité **{remove_name}** del carrito. ¿Confirmamos la venta? (sí / no)"
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)

        # -----------------------------------------
        # 🔙 Deshacer mientras estás en confirmación
        # -----------------------------------------
        # ✅ MEJORA: Regex más específico que NO matchea "descuento"
        undo_pattern = r"""\b(
            deshacer|deshac[eé]|
            quit[áa]r?\s+(el\s+)?último|
            quit[áa]r?\s+(el\s+)?ultimo|
            undo|
            remov(e|er)\s+(el\s+)?último|
            elimin[áa]r?\s+(el\s+)?último
        )\b"""
        
        # ❌ Excluir explícitamente si contiene "descuento" o símbolos de porcentaje
        has_discount_words = re.search(r"\b(descuento|desc|porcentaje|%)\b", text, re.I)
        
        if re.search(undo_pattern, text, re.I | re.X) and not has_discount_words:
            actions.append({"type": "undo_last"})
            reply = "Listo ✅ Quité el último ítem del carrito. ¿Confirmamos la venta? (sí / no)"
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)

        if re.search(r"\b(sí|si|dale|ok|okay|adelante|confirmar|confirmá)\b", text):
            actions.append({"type": "confirm_sale"})
            reply = "✅ Venta confirmada. Que Dios bendiga tu negocio 🙏"
            ui_memory = _clear_pendings(
                ui_memory,
                "confirm_sale",
                "await_payment",
                "choose_product",
                "confirm_recommended",
            )
            _reset_sale_state(session_id)

        elif re.search(r"\b(no|cancelar|cancelá|anular|abortá|abortar)\b", text):
            reply = "❌ Confirmación cancelada. La venta no fue procesada."
            ui_memory = _clear_pendings(
                ui_memory,
                "confirm_sale",
                "await_payment",
                "choose_product",
                "confirm_recommended",
            )
            _reset_sale_state(session_id)

        else:
            reply = (
                "Estoy esperando confirmación 🙏\n"
                "👉 Escribí **sí** para confirmar\n"
                "👉 **no** para cancelar\n"
                "👉 o podés decir: *quita X*, *quita 2 X*, *deshacer*"
            )

        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)

        return ChatResponse(
            reply_text=reply,
            cards=cards,
            actions=actions,
            session_id=session_id,
            memory=out_mem
        )



    # -----------------------------------------
    # 🔢 Decrementar cantidad por nombre - FUERA de confirmación
    # -----------------------------------------
    name, qty = _extract_decrement_name_qty(text_raw)
    if name and qty:
        actions.append({"type": "decrement_from_cart_by_name", "name": name, "qty": qty})
        reply = f"Listo ✅ Quito {qty} de **{name}**."
        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)

    # -----------------------------------------
    # 🗑️ Quitar por nombre - FUERA de confirmación
    # -----------------------------------------
    remove_name = _extract_remove_name(text_raw)
    if remove_name:
        actions.append({"type": "remove_from_cart_by_name", "name": remove_name})
        reply = f"Listo ✅ Quité **{remove_name}** del carrito (si estaba)."
        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)

    # -----------------------------------------
    # 🔙 Deshacer último (rápido) - FUERA de confirmación
    # -----------------------------------------
    # ✅ MEJORA: Misma regex mejorada + exclusión de palabras de descuento
    undo_pattern = r"""\b(
        deshacer|deshac[eé]|
        quit[áa]r?\s+(el\s+)?último|
        quit[áa]r?\s+(el\s+)?ultimo|
        undo|
        remov(e|er)\s+(el\s+)?último|
        elimin[áa]r?\s+(el\s+)?último
    )\b"""
    
    # ❌ Excluir si hay palabras relacionadas a descuento
    has_discount_words = re.search(r"\b(descuento|desc|porcentaje|%)\b", text, re.I)
    
    if re.search(undo_pattern, text, re.I | re.X) and not has_discount_words:
        actions.append({"type": "undo_last"})
        reply = "Listo ✅ Quité el último ítem del carrito."
        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)


    # -----------------------------------------
    # 📊 FASE 1: Consultas de datos reales
    # Intercepta preguntas de datos ANTES de navegación
    # para devolver números reales en vez de abrir pantallas
    # -----------------------------------------
    data_result = try_data_query(text_raw, db)
    if data_result:
        reply = data_result["reply_text"]
        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(
            reply_text=reply,
            cards=[],
            actions=[],
            session_id=session_id,
            memory=out_mem,
        )

    # -----------------------------------------
    # 🎯 FASE 3: Acciones ampliadas
    # Actualizar precios, agregar stock, registrar gastos,
    # crear clientes, y navegar a cualquier sección.
    # -----------------------------------------
    action_result = try_action_command(text_raw, db)
    if action_result:
        reply = action_result["reply_text"]
        action_actions = action_result.get("actions", [])
        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(
            reply_text=reply,
            cards=[],
            actions=action_actions,
            session_id=session_id,
            memory=out_mem,
        )

    # -----------------------------------------
    # Navegación a reportes de ventas
    # -----------------------------------------
    sales_nav = _sales_reports_intent_action(text)
    if sales_nav:
        actions.append(sales_nav)

        if sales_nav["module"] == "daily_report":
            reply = "Listo ✅ abriendo el reporte del día."
        else:
            reply = "Listo ✅ abriendo el registro de ventas con el rango correspondiente."

        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(reply_text=reply, cards=[], actions=actions, session_id=session_id, memory=out_mem)

    # -----------------------------------------
    # 🔔 Alertas inteligentes en lenguaje natural
    # -----------------------------------------
    alert = _smart_alerts_intent(text_raw)
    if alert:
        reply = alert["reply"]
        actions.extend(alert.get("actions", []))

        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)

        return ChatResponse(
            reply_text=reply,
            cards=[],
            actions=actions,
            session_id=session_id,
            memory=out_mem
        )

    # -----------------------------------------
    # A) Saludos y respuestas simples
    # -----------------------------------------
    if re.search(r"\b(hola|hey|buenas|qué tal)\b", text):
        # FASE 5: Saludo contextual
        if ui_ctx.current_screen:
            reply = f"¡Hola! 👋 Estás en **{ui_ctx.screen_label()}**. ¿En qué te ayudo?"
        else:
            reply = "¡Hola! 👋 ¿En qué te puedo ayudar?"
        if ui_ctx.has_cart():
            reply += f"\n🛒 Tenés {ui_ctx.cart_count} producto{'s' if ui_ctx.cart_count != 1 else ''} en el carrito (₡{ui_ctx.cart_total:,.0f})."
        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(
            reply_text=reply, cards=[], actions=[],
            suggestions=generate_contextual_suggestions(ui_ctx),
            session_id=session_id, memory=out_mem,
        )

    # -----------------------------------------
    # B-PRO) Comando: cotiza / proforma desde chat
    # "cotiza 5 cemento para Juan"
    # Se maneja vía action_intent → action_commands
    # (ya cubierto por try_action_command arriba)
    # Solo agregamos detección directa para frases sueltas
    # que no captura action_intent
    # -----------------------------------------
    if re.search(r"\b(cotiz[aá]r?|cotiza|cotizaci[oó]n|proforma)\b", text) and not re.search(r"\b(vende|vendé|vender)\b", text):
        # Delegar a action_intent que ya maneja proformas
        from app.ai.action_intent import _try_create_proforma
        proforma_result = _try_create_proforma(text_raw.lower(), db)
        if proforma_result:
            reply = proforma_result["reply_text"]
            pro_actions = proforma_result.get("actions", [])
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(
                reply_text=reply,
                cards=[],
                actions=pro_actions,
                session_id=session_id,
                memory=out_mem,
            )

    # -----------------------------------------
    # B) Comando compuesto: vender X producto
    # -----------------------------------------
    if re.search(r"\b(vende|vendé|vender)\b", text):
        qty = _extract_qty_sell(text_raw) or 1
        product_name = _extract_product_name(text_raw)
        customer = _extract_customer_loose(text_raw)
        payment = _extract_payment_method(text_raw)
        confirm_mode = _extract_confirm_intent(text_raw)

        # -----------------------------------------
        # ✅ Multi-producto (máx 3 ítems, modo limitado)
        # Ej: "vende 2 pegamento pvc y 1 cinta aislante a randall por sinpe"
        # Reglas:
        # - máx 3 ítems
        # - cada ítem debe resolver a 1 match y stock > 0
        # - si no, decir "mejor manual"
        # -----------------------------------------
        multi_items = _extract_multi_sell_items(text_raw)

        if len(multi_items) >= 2:
            if len(multi_items) > 3:
                reply = "⚠️ Son muchos ítems para una sola frase. Mejor hacelo manual 🙏 (máximo 3)."
                out_mem = _push_turn(ui_memory, "user", text_raw)
                out_mem = _push_turn(out_mem, "assistant", reply)
                return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

            resolved = []
            problems = []

            for it in multi_items:
                q = it["qty"]
                name = it["name"]

                results = search_products_fuzzy(db, name, limit=5)

                if not results:
                    problems.append(f"• No encontré **{name}**")
                    continue

                if len(results) > 1:
                    problems.append(f"• **{name}** tiene varias coincidencias (mejor manual)")
                    continue

                p = results[0]
                stock = getattr(p, "stock", None)
                if isinstance(stock, (int, float)) and stock <= 0:
                    problems.append(f"• **{p.name}** está sin stock (mejor manual)")
                    continue

                resolved.append((p, q))

            if problems:
                reply = "⚠️ No puedo procesar esa venta multi-producto automáticamente:\n" + "\n".join(problems) + "\n\nMejor hacelo manual 🙏"
                out_mem = _push_turn(ui_memory, "user", text_raw)
                out_mem = _push_turn(out_mem, "assistant", reply)
                return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

            # ✅ aplicar acciones
            sale_state = _get_sale_state(session_id)

            for p, q in resolved:
                actions.append({"type": "add_to_cart", "product_id": p.id, "qty": q})
                sale_state["items"].append({"product_id": p.id, "qty": q})
                cards.append(_product_to_card(p))

            # cliente / pago (una sola vez)
            if customer:
                sale_state["customer_name"] = customer
                actions.append({"type": "set_customer", "name": customer})

            if payment:
                sale_state["payment_method"] = payment
                actions.append({"type": "set_payment_method", "method": payment})

            _save_sale_state(session_id, sale_state)

            # respuesta
            summary = ", ".join([f"{q}× {p.name}" for p, q in resolved])
            reply = f"✅ Listo: agregué {summary}."
            if customer:
                reply += f" Cliente: **{customer}**."
            if payment:
                reply += f" Pago: **{payment.upper()}**."

            missing = _get_missing_sale_fields(sale_state)
            if "payment_method" in missing:
                reply += "\n¿Cómo va a pagar el cliente? (sinpe, efectivo o tarjeta)"
                ui_memory.append(MemoryMessage(role="system", pending_action="await_payment"))
            else:
                if confirm_mode in ("print", "no_print"):
                    actions.append({"type": "preview_confirm_sale"})
                    actions.append({"type": "confirm_sale_print" if confirm_mode == "print" else "confirm_sale_no_print"})
                    reply += "\n✅ Listo. Confirmando la venta."
                else:
                    reply += "\n¿Confirmamos la venta?"
                    ui_memory.append(MemoryMessage(role="system", pending_action="confirm_sale"))

            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)

            return ChatResponse(
                reply_text=reply,
                cards=cards,
                actions=actions,
                session_id=session_id,
                memory=out_mem
            )

        # Continuar con flujo de 1 producto si no es multi-item
        if not product_name:
            reply = "Decime qué producto querés vender 🙏"
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

        # 🔍 Buscar producto automáticamente (FASE 2: con fuzzy)
        results = search_products_fuzzy(db, product_name, limit=5)

        if not results:
            reply = f"No encontré el producto '{product_name}'. Probá con otro nombre."
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

        # 👇 Si hay varias coincidencias: guardamos opciones y pedimos selección
        if len(results) > 1:
            sale_state = _get_sale_state(session_id)

            sale_state["pending_sell"] = {
                "qty": qty,
                "product_query": product_name,
                "customer_name": customer,
                "payment_method": payment,
                "choices": [{
                    "id": p.id,
                    "name": p.name,
                    "code": p.code,
                    "price": float(p.price) if p.price is not None else None,
                    "stock": p.stock,
                } for p in results],
            }
            _save_sale_state(session_id, sale_state)

            ui_memory.append(MemoryMessage(role="system", pending_action="choose_product"))

            choices = sale_state["pending_sell"]["choices"]
            best_idx = _best_in_stock_index(choices)

            lines = []
            if best_idx is not None:
                rec = choices[best_idx]
                lines.append(_make_recommendation_text(rec))
                lines.append(f"Si querés otra opción, elegí 1–{len(choices)}:")
                ui_memory.append(MemoryMessage(role="system", pending_action="confirm_recommended"))
            else:
                lines.append(f"Encontré varias coincidencias para **{product_name}**. Elegí 1–{len(choices)}:")

            for i, c in enumerate(choices, 1):
                lines.append(_format_choice_line(i, c, suggested=(best_idx == i - 1)))

            if best_idx is None:
                lines.append("\n⚠️ Ojo: todas estas opciones están sin stock.")

            reply = "\n".join(lines)

            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)

            # Marcar la card sugerida
            best_id = None
            if best_idx is not None and best_idx < len(choices):
                best_id = choices[best_idx].get("id")

            cards = []
            for p in results:
                pid = getattr(p, "id", None)
                cards.append(_product_to_card(p, suggested=(best_id is not None and pid == best_id)))

            return ChatResponse(reply_text=reply, cards=cards, actions=[], session_id=session_id, memory=out_mem)

        # ✅ Solo 1 match: seguimos normal
        product = results[0]
        
        # 🚫 Si el único match está sin stock: buscar alternativas automáticamente
        if product.stock is not None and product.stock <= 0:
            base_query = _alt_query_from_name(product.name) or product.name

            alt_results = search_products(db, base_query, limit=10)

            # fallback: si no encuentra nada, usar keyword principal
            if not alt_results:
                keywords = _keywords_from_name(product.name)
                if keywords:
                    alt_results = search_products(db, keywords[0], limit=10)

            # filtrar stock y excluir producto original
            alt_results = [
                p for p in alt_results
                if p.id != product.id
                and isinstance(getattr(p, "stock", None), (int, float))
                and p.stock > 0
            ]


            # ✅ priorizar más parecidos al producto original + stock
            alt_results = _rank_alternatives(alt_results, original_name=product.name)[:5]

            # Si no hay alternativas, solo informamos
            if not alt_results:
                reply = (
                    f"⚠️ **{product.name}** está **sin stock**.\n"
                    "No encontré alternativas con stock. ¿Querés buscar otro producto?"
                )
                out_mem = _push_turn(ui_memory, "user", text_raw)
                out_mem = _push_turn(out_mem, "assistant", reply)
                return ChatResponse(
                    reply_text=reply,
                    cards=[_product_to_card(product)],
                    actions=[],
                    session_id=session_id,
                    memory=out_mem
                )

            # ✅ Hay alternativas: activar selector automáticamente
            sale_state = _get_sale_state(session_id)
            sale_state["pending_sell"] = {
                "qty": qty,
                "product_query": base_query,
                "customer_name": customer,
                "payment_method": payment,
                "choices": _make_choice_dicts(alt_results),
            }
            _save_sale_state(session_id, sale_state)

            ui_memory.append(MemoryMessage(role="system", pending_action="choose_product"))

            choices = sale_state["pending_sell"]["choices"]
            best_idx = _best_in_stock_index(choices)

            lines = [f"⚠️ **{product.name}** está **sin stock**."]

            if best_idx is not None:
                rec = choices[best_idx]
                lines.append(_make_recommendation_text(rec))
                lines.append(f"Si querés otra opción, elegí 1–{len(choices)}:")
                ui_memory.append(MemoryMessage(role="system", pending_action="confirm_recommended"))
            else:
                lines.append(f"Te encontré opciones para **{base_query}**. Elegí 1–{len(choices)}:")

            for i, c in enumerate(choices, 1):
                lines.append(_format_choice_line(i, c, suggested=(best_idx == i - 1)))

            if best_idx is not None:
                lines.append(f"\n⭐ Sugerido: #{best_idx + 1}")

            reply = "\n".join(lines)

            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)

            # Marcar la card sugerida en las alternativas
            best_id = None
            if best_idx is not None and best_idx < len(choices):
                best_id = choices[best_idx].get("id")

            cards = []
            for p in alt_results:
                pid = getattr(p, "id", None)
                cards.append(_product_to_card(p, suggested=(best_id is not None and pid == best_id)))

            return ChatResponse(
                reply_text=reply,
                cards=cards,
                actions=[],
                session_id=session_id,
                memory=out_mem
            )

        # 🛒 Agregar al carrito
        actions.append({
            "type": "add_to_cart",
            "product_id": product.id,
            "qty": qty
        })

        # 🧠 Guardar en la venta activa
        sale_state = _get_sale_state(session_id)
        sale_state["items"].append({
            "product_id": product.id,
            "qty": qty
        })

        # Cliente
        if customer:
            sale_state["customer_name"] = customer
            actions.append({
                "type": "set_customer",
                "name": customer
            })

        # Pago
        if payment:
            sale_state["payment_method"] = payment
            actions.append({
                "type": "set_payment_method",
                "method": payment
            })

        _save_sale_state(session_id, sale_state)

        # 📝 Mensaje de respuesta
        reply = f"✅ Listo, agregué {qty} × **{product.name}**."
        if customer:
            reply += f" Cliente: **{customer}**."
        if payment:
            reply += f" Pago: **{payment.upper()}**."

        # 🔍 validar campos faltantes antes de confirmar
        missing = _get_missing_sale_fields(sale_state)

        if "payment_method" in missing:
            reply += "\n¿Cómo va a pagar el cliente? (sinpe, efectivo o tarjeta)"
            ui_memory.append(
                MemoryMessage(role="system", pending_action="await_payment")
            )
        else:
            # ✅ Si el user ya pidió confirmar en la MISMA frase, ejecutamos confirmación
            if confirm_mode in ("print", "no_print"):
                actions.append({"type": "preview_confirm_sale"})
                actions.append({"type": "confirm_sale_print" if confirm_mode == "print" else "confirm_sale_no_print"})
                reply += "\n✅ Listo. Confirmando la venta."
            else:
                reply += "\n¿Confirmamos la venta?"
                ui_memory.append(
                    MemoryMessage(role="system", pending_action="confirm_sale")
                )


        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)

        return ChatResponse(
            reply_text=reply,
            cards=[_product_to_card(product)],
            actions=actions,
            session_id=session_id,
            memory=out_mem
        )

    # -----------------------------------------
    # C) Tool: buscar productos (FASE 2: con fuzzy)
    # -----------------------------------------
    term = _extract_search_term(text_raw)
    if term:
        try:
            results = search_products_fuzzy(db, term, limit=8)
        except Exception as e:
            reply = f"Hubo un problema buscando productos: {type(e).__name__}: {e}"
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

        if not results:
            reply = f"No encontré productos con '{term}'. Probá con otro nombre o con el código."
        else:
            cards = [_product_to_card(p) for p in results]

            # memoria corta para follow-ups
            ids = [c["id"] for c in cards if c.get("id") is not None]
            if ids:
                _remember(session_id, "last_results", ids)
                _remember(session_id, "last_product_id", ids[0])

            # ✅ IMPORTANTE: NO mandamos acciones aquí.
            # Solo mostramos resultados y esperamos a que el usuario diga "abre" o "agrega X".
            if len(cards) == 1:
                reply = f"Encontré **{cards[0]['title']}**. Decime: 'abre' o 'agrega 2'."
            else:
                reply = (
                    f"Encontré {len(cards)} productos. "
                    f"Decime cuál (por ID/código) o decime: 'abre' / 'agrega 2' (usa el último)."
                )

        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)

    # -----------------------------------------
    # 👤 Cliente inteligente: deuda/crédito (contextual + explícito)
    # -----------------------------------------
    text_norm = _normalize(text_raw)

    if _is_credit_question(text_norm):
        sale_state = _get_sale_state(session_id)
        target = _extract_customer_for_credit_question(text_raw)

        # 1) Contextual al carrito: si dicen "este cliente" o no dicen nombre
        # FASE 5: Primero revisar contexto real de la UI, luego sale_state
        if target == "__CURRENT__" or (not target and sale_state.get("customer_name")):
            target = sale_state.get("customer_name")
        if target == "__CURRENT__" or (not target and ui_ctx.selected_customer_name):
            target = ui_ctx.selected_customer_name

        if not target:
            reply = "¿De qué cliente querés revisar el saldo? (ej: '¿Randall debe algo?')"
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

        customer, count_ = _find_customer_best_match(db, target)

        if not customer:
            reply = f"No encontré al cliente **{target}**. Probá con otro nombre o buscá en clientes."
            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)
            return ChatResponse(reply_text=reply, cards=[], actions=[], session_id=session_id, memory=out_mem)

        balance = float(getattr(customer, "credit_balance", 0.0) or 0.0)

        last_sale = _get_last_sale_for_customer(db, int(customer.id))
        last_txt = ""
        if last_sale and getattr(last_sale, "created_at", None):
            try:
                dt = last_sale.created_at.strftime("%Y-%m-%d %H:%M")
                last_txt = f"\n🧾 Última compra: {dt} — {_format_price_crc(getattr(last_sale, 'total', 0) or 0)}"
            except Exception:
                pass

        if balance > 0:
            reply = f"⚠️ **{customer.name}** tiene **{_format_price_crc(balance)}** pendientes.{last_txt}"
        else:
            reply = f"✅ **{customer.name}** está al día (saldo pendiente: {_format_price_crc(0)}).{last_txt}"

        # Solo navegar si lo piden explícito ("abrí / mostrámelo")
        if _wants_open_credit_view(text_norm):
            actions.append({"type": "navigate", "module": "credits", "customer_id": int(customer.id)})

        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(reply_text=reply, cards=[], actions=actions, session_id=session_id, memory=out_mem)

    # -----------------------------------------
    # D) Cliente y método de pago
    # -----------------------------------------
    customer = _extract_customer(text_raw)
    payment = _extract_payment_method(text_raw)

    if customer or payment:
        sale_state = _get_sale_state(session_id)

        if customer:
            sale_state["customer_name"] = customer
            actions.append({
                "type": "set_customer",
                "name": customer
            })

        if payment:
            sale_state["payment_method"] = payment
            actions.append({
                "type": "set_payment_method",
                "method": payment
            })

        _save_sale_state(session_id, sale_state)

        parts = []
        if customer:
            parts.append(f"cliente **{customer}**")
        if payment:
            parts.append(f"pago por **{payment.upper()}**")

        reply = "Perfecto 👍 Asigno " + " y ".join(parts) + "."

        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)

        return ChatResponse(
            reply_text=reply,
            cards=[],
            actions=actions,
            session_id=session_id,
            memory=out_mem
        )

    # -----------------------------------------
    # E) Abre / Agrega usando memoria corta
    # -----------------------------------------
    qty = _parse_qty(text_raw)
    last_pid = _recall(session_id, "last_product_id")

    if _is_open_intent(text_raw) and last_pid:
        actions.append({"type": "open_product", "product_id": last_pid})
        reply = "Listo ✅ lo abro."
        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)
        return ChatResponse(reply_text=reply, cards=cards, actions=actions, session_id=session_id, memory=out_mem)
    
    if _is_add_intent(text_raw) and last_pid:
        qty_final = qty or 1


        sale_state = _get_sale_state(session_id)
        sale_state["items"].append({
            "product_id": last_pid,
            "qty": qty_final
        })
        _save_sale_state(session_id, sale_state)

        actions.append({
            "type": "add_to_cart",
            "product_id": last_pid,
            "qty": qty_final
        })

        reply = f"Listo ✅ agrego {qty_final} al carrito."
        
        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)

        return ChatResponse(
            reply_text=reply,
            cards=cards,
            actions=actions,
            session_id=session_id,
            memory=out_mem
        )

    
    # -----------------------------------------
    # F) Confirmar venta (resumen previo) 🧾
    # -----------------------------------------
    confirm_intent_re = r"\b(confirmar|confirmá|finalizar|finalizá|cobrar|cobrá|cerrar venta|pagar|checkout)\b"

    if re.search(confirm_intent_re, text):

        sale_state = _get_sale_state(session_id)

        if not sale_state["items"]:
            reply = "⚠️ No hay productos en la venta. Agregá al menos uno antes de confirmar."

            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)

            return ChatResponse(
                reply_text=reply,
                cards=cards,
                actions=[],
                session_id=session_id,
                memory=out_mem
            )

        # 🧠 Evitar doble confirmación
        if _has_pending(ui_memory, "confirm_sale"):
            reply = "La venta ya está pendiente de confirmación 🙏 ¿Deseás confirmarla o cancelarla?"
        else:
            actions.append({"type": "preview_confirm_sale"})

            reply = (
                "🧾 <b>Resumen de la venta:</b><br>"
                "Revisá los datos en pantalla.<br><br>"
                "¿Confirmamos la venta? (sí / cancelar)"
            )

            ui_memory.append(
                MemoryMessage(
                    role="system",
                    content="",
                    pending_action="confirm_sale"
                )
            )

        missing = _get_missing_sale_fields(sale_state)

        if "payment_method" in missing:
            reply = "Antes de confirmar necesito saber cómo va a pagar el cliente 🙏"
            ui_memory.append(
                MemoryMessage(role="system", pending_action="await_payment")
            )

            out_mem = _push_turn(ui_memory, "user", text_raw)
            out_mem = _push_turn(out_mem, "assistant", reply)

            return ChatResponse(
                reply_text=reply,
                cards=[],
                actions=[],
                session_id=session_id,
                memory=out_mem
            )

        out_mem = _push_turn(ui_memory, "user", text_raw)
        out_mem = _push_turn(out_mem, "assistant", reply)

        return ChatResponse(
            reply_text=reply,
            cards=cards,
            actions=actions,
            session_id=session_id,
            memory=out_mem
        )

    # -----------------------------------------
    # FASE 6: LLM Fallback — consultas complejas
    # Si el clasificador no resolvió, intentar con el LLM
    # -----------------------------------------
    has_pending = any(
        _has_pending(ui_memory, a)
        for a in ("confirm_sale", "choose_product", "confirm_recommended", "await_payment")
    )
    route_decision = hybrid_route(text_raw, has_pending_state=has_pending)

    if route_decision.is_llm:
        try:
            llm_result = call_llm(
                user_text=text_raw,
                db=db,
                memory=[{"role": m.role, "content": m.content} for m in ui_memory if m.content],
                ui_ctx=ui_ctx,
            )

            reply = llm_result.get("reply_text", "")
            llm_actions = llm_result.get("actions", [])
            llm_cards = llm_result.get("cards", [])

            if reply:
                out_mem = _push_turn(ui_memory, "user", text_raw)
                out_mem = _push_turn(out_mem, "assistant", reply)
                return ChatResponse(
                    reply_text=reply,
                    cards=llm_cards,
                    actions=llm_actions,
                    suggestions=generate_contextual_suggestions(ui_ctx),
                    session_id=session_id,
                    memory=out_mem,
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"LLM fallback error: {e}")
            # Caer al fallback estático si el LLM falla

    # -----------------------------------------
    # Fallback estático (cuando no hay LLM o falló)
    # -----------------------------------------
    reply = (
        "Te puedo ayudar con cosas como:\n"
        "📊 **Consultas:** `¿cuánto vendí hoy?` · `¿cómo está la caja?` · `¿quién me debe?`\n"
        "🔍 **Buscar:** `busca soldadura` · `busca a Randall`\n"
        "🛒 **Vender:** `vende 2 pegamento a Juan por sinpe` · `confirmar venta`\n"
        "✏️ **Acciones:** `precio de cemento a 5000` · `agrega 50 al stock de clavos`\n"
        "📤 **Gastos:** `registra gasto de 15000 en servicios`\n"
        "👤 **Clientes:** `crea cliente María López tel 88881234`\n"
        "🧭 **Navegar:** `abre gastos` · `abre proveedores` · `ir a configuración`\n"
        "🛒 **Carrito:** `¿qué tengo en el carrito?` · `¿en qué pantalla estoy?`"
    )
    out_mem = _push_turn(ui_memory, "user", text_raw)
    out_mem = _push_turn(out_mem, "assistant", reply)
    return ChatResponse(
        reply_text=reply, cards=cards, actions=actions,
        suggestions=generate_contextual_suggestions(ui_ctx),
        session_id=session_id, memory=out_mem,
    )


# ═══════════════════════════════════════════════════════
# FASE 7: Endpoints adicionales
# ═══════════════════════════════════════════════════════

class ProactiveAlertsResponse(BaseModel):
    alerts: List[Dict[str, Any]] = Field(default_factory=list)
    message: str = ""
    suggestions: List[str] = Field(default_factory=list)


@router.get("/proactive-alerts", response_model=ProactiveAlertsResponse)
def proactive_alerts(db: "Session" = Depends(get_db)) -> ProactiveAlertsResponse:
    """FASE 7: Alertas proactivas al abrir el chat."""
    try:
        alerts = get_proactive_alerts(db)
        message = format_alerts_as_message(alerts)
        return ProactiveAlertsResponse(
            alerts=alerts,
            message=message,
            suggestions=["Ventas hoy", "Resumen del día", "¿Quién me debe?", "Stock bajo"],
        )
    except Exception:
        return ProactiveAlertsResponse(
            alerts=[],
            message="👋 ¿En qué te puedo ayudar?",
            suggestions=["Ventas hoy", "Resumen del día"],
        )


class ExportRequest(BaseModel):
    messages: List[Dict[str, str]] = Field(default_factory=list)
    format: str = "text"  # "text" | "markdown"


class ExportResponse(BaseModel):
    content: str
    filename: str


@router.post("/export-chat", response_model=ExportResponse)
def export_chat(req: ExportRequest) -> ExportResponse:
    """FASE 7: Exportar conversación del chat."""
    from datetime import datetime

    lines = []
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    if req.format == "markdown":
        lines.append(f"# Conversación Violette — {ts}\n")
        for msg in req.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"**Tú:** {content}\n")
            elif role == "assistant":
                lines.append(f"**Violette:** {content}\n")
        filename = f"chat_violette_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    else:
        lines.append(f"Conversación Violette — {ts}")
        lines.append("=" * 40)
        for msg in req.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"\nTú: {content}")
            elif role == "assistant":
                lines.append(f"\nViolette: {content}")
        filename = f"chat_violette_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    return ExportResponse(content="\n".join(lines), filename=filename)