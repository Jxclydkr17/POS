# app/ai/classifier.py
"""
FASE 2 — Clasificador inteligente por capas.
Reemplaza el monstruo de regex con un sistema limpio de 3 capas:

  Capa 1 — DOMINIO: ¿De qué área habla? (ventas, caja, inventario, etc.)
  Capa 2 — INTENCIÓN: ¿Qué quiere hacer? (consultar, navegar, buscar, etc.)
  Capa 3 — ENTIDADES: ¿Qué datos menciona? (periodo, cliente, producto, etc.)

Usa fuzzy matching para tolerar errores de escritura.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.ai.fuzzy import (
    normalize_text,
    fix_typos,
    any_keyword_in_text,
    keyword_in_text,
)
from app.ai.date_parser import parse_period, extract_period_or_default


# ═════════════════════════════════════════════════════
# Resultado de la clasificación
# ═════════════════════════════════════════════════════

@dataclass
class ClassificationResult:
    """Resultado del clasificador de 3 capas."""

    # Capa 1: Dominio
    domain: str = "unknown"
    # ventas | gastos | caja | inventario | clientes | compras |
    # financiero | carrito | navegacion | sistema | credito | unknown

    # Capa 2: Intención
    intent: str = "unknown"
    # consultar | navegar | buscar | agregar | eliminar |
    # confirmar | cancelar | saludar | ayuda | unknown

    # Capa 3: Entidades extraídas
    entities: dict = field(default_factory=dict)
    # Puede contener:
    #   period: str          — "today", "week", "month", etc.
    #   customer_name: str   — nombre del cliente
    #   product_name: str    — nombre/búsqueda de producto
    #   quantity: int        — cantidad
    #   payment_method: str  — "sinpe", "cash", "card"
    #   module: str          — módulo de destino para navegación
    #   raw_text: str        — texto original normalizado
    #   search_term: str     — término de búsqueda

    # Confidence score (0.0 - 1.0)
    confidence: float = 0.0

    # Texto después de fix_typos
    corrected_text: str = ""

    @property
    def is_data_query(self) -> bool:
        """True si la intención es consultar datos."""
        return self.intent == "consultar" and self.domain not in ("unknown", "sistema", "carrito")

    @property
    def is_navigation(self) -> bool:
        return self.intent == "navegar"

    @property
    def is_cart_operation(self) -> bool:
        return self.domain == "carrito"

    @property
    def is_greeting(self) -> bool:
        return self.domain == "sistema" and self.intent == "saludar"


# ═════════════════════════════════════════════════════
# Capa 1: Clasificación de DOMINIO
# ═════════════════════════════════════════════════════

# Keywords por dominio (con variantes comunes)
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "ventas": [
        "venta", "ventas", "vendí", "vendido", "vender", "vendimos",
        "facturación", "facturacion", "transacciones", "ticket",
    ],
    "gastos": [
        "gasto", "gastos", "gasté", "gastamos", "gastado",
    ],
    "caja": [
        "caja", "arqueo", "cierre de caja", "apertura",
        "efectivo en caja", "saldo de caja",
    ],
    "inventario": [
        "inventario", "stock", "existencias", "bodega",
        "agotado", "agotados", "sin stock",
    ],
    "clientes": [
        "cliente", "clientes",
    ],
    "credito": [
        "crédito", "credito", "deuda", "deudas", "debe", "deben",
        "deudor", "deudores", "saldo pendiente", "fiado", "moroso",
    ],
    "compras": [
        "compra", "compras", "proveedor", "proveedores",
        "factura proveedor", "orden de compra",
    ],
    "financiero": [
        "ganancia", "ganancias", "utilidad", "rentabilidad",
        "margen", "financiero", "estado de resultados",
        "ventas vs gastos",
    ],
    "carrito": [
        "carrito", "cart",
    ],
    "productos": [
        "producto", "productos", "artículo", "articulo",
    ],
    "navegacion": [],   # se detecta por intención, no por keywords
    "sistema": [],      # saludos, ayuda
}

# Verbos/frases que implican intención de ventas-acciones (carrito)
_SELL_VERBS = [
    "vende", "vendé", "vender", "cobrar", "cobrá",
]

# Productos como dominio: si buscan producto específico
_PRODUCT_SEARCH_VERBS = [
    "busca", "buscar", "buscame", "búscame", "encuentra",
]


def _detect_domain(text: str, text_fixed: str) -> tuple[str, float]:
    """
    Capa 1: Detecta el dominio principal.
    Retorna (domain, confidence).
    """
    t = text_fixed  # usar texto con typos corregidos

    # ── Reglas de alta confianza (patrones muy específicos) ──

    # Compras: "quién vende X" / "proveedores de X" / "dónde compro X"
    if re.search(
        r"("
        r"quien\s+(?:me\s+)?vende"
        r"|a\s+quien\s+le\s+compro"
        r"|donde\s+(?:puedo\s+)?compr[oa]"
        r"|proveedore?s?\s+(?:de|del|para|que\s+vend)"
        r"|quien\s+(?:me\s+)?(?:tiene|ofrece|maneja|distribuye|trae)"
        r"|que\s+proveedor(?:es)?\s+(?:tiene|vende|ofrece|maneja)"
        r"|a\s+quien\s+(?:le\s+)?(?:puedo\s+)?(?:comprar|pedir|encargar)"
        r"|comparar?\s+precio.*proveedor"
        r"|precio.*(?:por\s+)?proveedor"
        r")",
        t,
    ):
        return "compras", 0.95

    # Sistema: saludos
    if re.search(r"\b(hola|hey|buenas|buenos?\s+d[ií]as?|que\s+tal|saludos)\b", t):
        return "sistema", 0.95

    # Sistema: ayuda
    if re.search(r"\b(ayuda|help|que\s+puedo\s+hacer|como\s+funciona)\b", t):
        return "sistema", 0.90

    # Carrito: verbos de venta directa con producto implícito
    if re.search(r"\b(vende|vend[eé]|vender)\s+\d", t):
        return "carrito", 0.92

    # Carrito: agregar/quitar
    if re.search(r"\b(agrega|agreg[aá]|agregar|quita|quit[aá]|meter|met[eé])\b", t):
        # Solo si NO es "agregar stock" (inventario) ni "agregar gasto"
        if not re.search(r"\b(stock|inventario|gasto)\b", t):
            return "carrito", 0.85

    # Carrito: confirmar/cobrar/finalizar
    if re.search(r"\b(confirmar|confirm[aá]|cobrar|cobr[aá]|finalizar|finaliz[aá]|checkout)\b", t):
        return "carrito", 0.90

    # Carrito: deshacer
    if re.search(r"\b(deshacer|undo|deshac[eé])\b", t):
        return "carrito", 0.88

    # ── Scoring por keywords con fuzzy matching ──
    scores: dict[str, float] = {}

    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if not keywords:
            continue
        score = 0.0
        for kw in keywords:
            if keyword_in_text(kw, t, threshold=0.80):
                # Peso por longitud del keyword (más largo = más específico)
                weight = min(1.0, len(kw) / 8.0) * 0.3
                score += 0.5 + weight
        if score > 0:
            scores[domain] = min(score, 1.0)

    if not scores:
        return "unknown", 0.0

    # El dominio con mejor score
    best = max(scores, key=scores.get)

    # ── Desambiguación de dominios cercanos ──

    # "crédito" + "cliente" -> crédito (no clientes genérico)
    if "credito" in scores and "clientes" in scores:
        if scores["credito"] >= scores["clientes"]:
            return "credito", scores["credito"]

    # "inventario" y "productos" son muy cercanos
    if "inventario" in scores and "productos" in scores:
        # Si pregunta "cuántos productos" -> inventario
        if re.search(r"\bcu[aá]ntos?\b", t):
            return "inventario", max(scores["inventario"], scores["productos"])

    return best, scores[best]


# ═════════════════════════════════════════════════════
# Capa 2: Clasificación de INTENCIÓN
# ═════════════════════════════════════════════════════

# Verbos/frases por intención
_INTENT_PATTERNS: dict[str, list[str]] = {
    "consultar": [
        # Preguntas de datos
        "cuanto", "cuantos", "cuantas", "cuales",
        "total", "cifras", "cifra",
        "como esta", "como estan", "como va", "como van",
        "dame", "dime", "decime", "cuentame",
        "muestrame", "resumen", "reporte",
        "estado de", "situacion",
    ],
    "navegar": [
        "abrir", "abre", "abrime", "abríme",
        "ver", "mostrar", "mostrá", "enseñame",
        "ir a", "llévame", "llevame",
        "abre el", "abre la", "abre los",
    ],
    "buscar": [
        "busca", "buscar", "buscame", "búscame",
        "encuentra", "encontrá",
    ],
    "agregar": [
        "agrega", "agregá", "agregar",
        "meter", "meté", "añadir", "añade",
        "pon", "poné",
    ],
    "eliminar": [
        "quita", "quitá", "elimina", "eliminá",
        "saca", "sacá", "remueve", "remové",
        "borra", "borrá",
    ],
    "confirmar": [
        "confirmar", "confirmá", "sí", "si", "dale",
        "ok", "okay", "adelante", "listo",
    ],
    "cancelar": [
        "cancelar", "cancelá", "no", "anular",
        "abortar", "salir",
    ],
    "vender": [
        "vende", "vendé", "vender",
    ],
    "saludar": [
        "hola", "hey", "buenas", "buenos días",
        "qué tal", "saludos",
    ],
    "ayuda": [
        "ayuda", "help", "qué puedo hacer",
        "cómo funciona",
    ],
}

# Patrones de pregunta (implican "consultar")
_QUESTION_STARTERS = re.compile(
    r"^[¿\s]*(cu[aá]nto|cu[aá]ntos|cu[aá]ntas|cu[aá]les?|qu[eé]|qui[eé]n|c[oó]mo|d[oó]nde)\b",
    re.I,
)


def _detect_intent(text: str, text_fixed: str, domain: str) -> tuple[str, float]:
    """
    Capa 2: Detecta la intención dentro del dominio.
    Retorna (intent, confidence).
    """
    t = text_fixed

    # ── Reglas de alta confianza ──

    # Pregunta directa = consultar
    if _QUESTION_STARTERS.match(t.strip()):
        # Excepciones: "¿cuál quieres?" en contexto de carrito no es consulta
        if domain not in ("carrito",):
            return "consultar", 0.90

    # ── Scoring por keywords ──
    scores: dict[str, float] = {}

    for intent, keywords in _INTENT_PATTERNS.items():
        score = 0.0
        for kw in keywords:
            if keyword_in_text(kw, t, threshold=0.80):
                score += 0.6
        if score > 0:
            scores[intent] = min(score, 1.0)

    if not scores:
        # Default por dominio
        if domain in ("ventas", "gastos", "caja", "inventario", "clientes",
                       "credito", "compras", "financiero"):
            # Si menciona un dominio de datos sin verbo claro, asumir consulta
            return "consultar", 0.50
        return "unknown", 0.0

    best = max(scores, key=scores.get)

    # ── Desambiguación ──

    # "dame" + dominio de datos = consultar (no navegar)
    if best == "navegar" and "consultar" in scores:
        if re.search(r"\b(dame|dime|decime|cuanto|cuantos|total|cifras|resumen|reporte)\b", t):
            return "consultar", scores["consultar"]

    # "confirmar" solo aplica en contexto de carrito
    if best == "confirmar" and domain != "carrito":
        # Reinterpretar
        if "consultar" in scores:
            return "consultar", scores["consultar"]

    return best, scores[best]


# ═════════════════════════════════════════════════════
# Capa 3: Extracción de ENTIDADES
# ═════════════════════════════════════════════════════

def _extract_entities(text_raw: str, text_fixed: str, domain: str, intent: str) -> dict:
    """
    Capa 3: Extrae entidades relevantes del texto.
    """
    entities: dict[str, Any] = {}
    t = text_fixed
    t_raw = text_raw

    # ── Periodo temporal ──
    period = extract_period_or_default(text_raw, default="today")
    entities["period"] = period

    # ── Cantidad ──
    qty_m = re.search(r"\b(\d+)\b", t)
    if qty_m:
        try:
            q = int(qty_m.group(1))
            if 1 <= q <= 999:
                entities["quantity"] = q
        except ValueError:
            pass

    # ── Método de pago (fuzzy) ──
    pm = _extract_payment_method_fuzzy(t)
    if pm:
        entities["payment_method"] = pm

    # ── Cliente ──
    customer = _extract_customer_name(t_raw)
    if customer:
        entities["customer_name"] = customer

    # ── Producto / término de búsqueda ──
    if intent == "buscar" or domain == "carrito":
        search_term = _extract_search_or_product(t_raw)
        if search_term:
            entities["search_term"] = search_term

    # ── Producto para búsqueda de proveedores ──
    if domain == "compras":
        pq = _extract_product_query_for_suppliers(t)
        if pq:
            entities["product_query"] = pq
            entities["sub_intent"] = "buscar_proveedor_producto"

    # ── Módulo de navegación ──
    if intent == "navegar":
        module = _extract_nav_module(t)
        if module:
            entities["module"] = module

    return entities


def _extract_payment_method_fuzzy(text: str) -> Optional[str]:
    """Extrae método de pago con tolerancia a typos."""
    # Sinpe
    if any_keyword_in_text(["sinpe", "sinpee", "simpe", "snipe"], text, threshold=0.75):
        return "sinpe"
    # Efectivo
    if any_keyword_in_text(["efectivo", "efetivo", "cash", "plata", "en efectivo"], text, threshold=0.75):
        return "cash"
    # Tarjeta
    if any_keyword_in_text(["tarjeta", "datáfono", "datafono", "card", "tarjea", "tajeta"], text, threshold=0.75):
        return "card"
    # Crédito (método de pago)
    if re.search(r"\bpor\s+cr[eé]dito\b", text):
        return "credito"
    return None


def _extract_customer_name(text_raw: str) -> Optional[str]:
    """Extrae nombre del cliente."""
    t = text_raw

    # "cliente X" / "a nombre de X"
    m = re.search(
        r"\b(?:cliente|a\s+nombre\s+de)\s+(.+?)(?:\s+por\b|\s+con\b|\s+y\s+|\s*$)",
        t, re.I,
    )
    if m:
        name = m.group(1).strip()
        # Limpiar métodos de pago del nombre
        name = re.sub(
            r"\b(sinpe|efectivo|tarjeta|datáfono|card|cash|crédito|credito)\b.*$",
            "", name, flags=re.I,
        ).strip()
        return name or None

    # "a <nombre>" (antes de "por")
    m = re.search(r"\ba\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)\b", t)
    if m:
        name = m.group(1).strip()
        if name.lower() not in ("nombre", "credito", "crédito", "sinpe", "efectivo", "tarjeta"):
            return name

    return None


def _extract_search_or_product(text_raw: str) -> Optional[str]:
    """Extrae el término de búsqueda o nombre de producto."""
    t = text_raw

    # "busca X"
    m = re.search(r"\b(?:busca|buscar|buscame|búscame)\s+(.+?)$", t, re.I)
    if m:
        term = m.group(1).strip()
        term = re.sub(r"[\?\!\.]$", "", term).strip()
        # Quitar "el/la/los/las/un/una"
        term = re.sub(r"^(el|la|los|las|un|una)\s+", "", term, flags=re.I)
        return term or None

    # "vende N X"
    m = re.search(
        r"\b(?:vende|vendé|vender|agrega|agregá)\s+(?:\d+\s+(?:de\s+)?)?(.+?)(?:\s+(?:al?|para|por|cliente)\b|\s*$)",
        t, re.I,
    )
    if m:
        name = m.group(1).strip()
        name = re.sub(
            r"\b(sinpe|efectivo|tarjeta|datáfono|card|cash)\b.*$",
            "", name, flags=re.I,
        ).strip()
        return name or None

    return None


def _extract_product_query_for_suppliers(text: str) -> Optional[str]:
    """
    Extrae el nombre/término de producto de frases tipo:
      "quién vende cemento", "proveedores de varilla",
      "dónde compro tornillos", "a quién le compro tubo PVC"
    Opera sobre texto ya normalizado (sin acentos, minúsculas).
    """
    # Patrones ordenados de más específico a más general
    patterns = [
        # "proveedores de/del/para X"
        r"proveedore?s?\s+(?:de|del|para)\s+(.+?)$",
        # "quien (me) vende X"
        r"quien\s+(?:me\s+)?vende\s+(.+?)$",
        # "quien (me) tiene/ofrece/maneja/distribuye/trae X"
        r"quien\s+(?:me\s+)?(?:tiene|ofrece|maneja|distribuye|trae)\s+(.+?)$",
        # "a quien le compro X" / "a quien le puedo comprar X"
        r"a\s+quien\s+(?:le\s+)?(?:puedo\s+)?(?:compro|comprar?|pedir|encargar)\s+(.+?)$",
        # "donde (puedo) compro/comprar X"
        r"donde\s+(?:puedo\s+)?compr[oa]r?\s+(.+?)$",
        # "que proveedor(es) tiene(n)/vende(n) X"
        r"que\s+proveedor(?:es)?\s+(?:tienen?|venden?|ofrecen?|manejan?)\s+(.+?)$",
        # "comparar precio(s) de X" / "precio(s) de X por proveedor"
        r"comparar?\s+precios?\s+(?:de|del|para)\s+(.+?)$",
        r"precios?\s+(?:de|del|para)\s+(.+?)(?:\s+por\s+proveedor)?$",
    ]

    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            term = m.group(1).strip()
            # Limpiar artículos al inicio
            term = re.sub(r"^(el|la|los|las|un|una|unos|unas)\s+", "", term, flags=re.I)
            # Limpiar signos al final
            term = re.sub(r"[\?\!\.\,;]+$", "", term).strip()
            # Limpiar sufijos comunes que no son producto
            term = re.sub(
                r"\s+(por\s+favor|pls|please|porfa)$",
                "", term, flags=re.I,
            ).strip()
            return term or None

    return None


def _extract_nav_module(text: str) -> Optional[str]:
    """Extrae el módulo de destino para navegación."""
    # Mapeo de keywords a módulos
    _MODULE_MAP = {
        "ventas": "sales",
        "venta": "sales",
        "historial de ventas": "sales_history",
        "gastos": "expenses",
        "gasto": "expenses",
        "caja": "cash",
        "inventario": "products",
        "productos": "products",
        "producto": "products",
        "clientes": "customers",
        "cliente": "customers",
        "compras": "purchases",
        "proveedores": "suppliers",
        "proveedor": "suppliers",
        "créditos": "credits",
        "creditos": "credits",
        "crédito": "credits",
        "dashboard": "dashboard",
        "panel": "dashboard",
        "tablero": "dashboard",
        "configuración": "settings",
        "config": "settings",
        "ajustes": "settings",
        "analíticas": "analytics",
        "analytics": "analytics",
        "reportes": "reports",
        "reporte": "reports",
        "financiero": "financial_reports",
        "categorías": "categories",
        "categorias": "categories",
    }
    t = normalize_text(text)
    for keyword, module in _MODULE_MAP.items():
        kw_norm = normalize_text(keyword)
        if keyword_in_text(kw_norm, t, threshold=0.80):
            return module
    return None


# ═════════════════════════════════════════════════════
# Función principal: classify()
# ═════════════════════════════════════════════════════

def classify(text_raw: str) -> ClassificationResult:
    """
    Clasifica un mensaje del usuario en 3 capas:
    dominio → intención → entidades.

    Proceso:
    1. Normaliza y corrige typos
    2. Detecta dominio (¿de qué habla?)
    3. Detecta intención (¿qué quiere hacer?)
    4. Extrae entidades (¿con qué datos?)
    """
    if not text_raw or not text_raw.strip():
        return ClassificationResult()

    # ── Normalizar y corregir ──
    text_norm = normalize_text(text_raw)
    text_fixed = fix_typos(text_norm)

    # ── Capa 1: Dominio ──
    domain, d_conf = _detect_domain(text_norm, text_fixed)

    # ── Capa 2: Intención ──
    intent, i_conf = _detect_intent(text_norm, text_fixed, domain)

    # ── Capa 3: Entidades ──
    entities = _extract_entities(text_raw, text_fixed, domain, intent)
    entities["raw_text"] = text_norm

    # ── Confidence combinada ──
    confidence = (d_conf * 0.6 + i_conf * 0.4)

    return ClassificationResult(
        domain=domain,
        intent=intent,
        entities=entities,
        confidence=confidence,
        corrected_text=text_fixed,
    )


# ═════════════════════════════════════════════════════
# Helpers públicos para retrocompatibilidad
# ═════════════════════════════════════════════════════

def is_data_query_intent(text_raw: str) -> bool:
    """Quick check: ¿es una consulta de datos?"""
    result = classify(text_raw)
    return result.is_data_query


def get_domain(text_raw: str) -> str:
    """Quick check: ¿de qué dominio habla?"""
    result = classify(text_raw)
    return result.domain