# app/ai/llm_interpreter.py
"""
FASE 6 — Capa inteligente de interpretación.
Usa el LLM como PRIMERA capa para entender el lenguaje natural del usuario
antes de ejecutar acciones. NO responde al usuario directamente;
retorna una intención estructurada en JSON que el sistema ejecuta.

Flujo:
  Mensaje → LLM Interpreter (entiende intención) → Ejecutor (actions/cards/reply)
            ↓ si falla o no hay LLM
            Regex/Fuzzy (código legacy, intacto)
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.ai.ui_context import UIContext, build_context_prompt
from app.ai.providers.provider_registry import get_active_provider

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────────────

_INTERPRETER_MAX_TOKENS = 300
_CONFIDENCE_THRESHOLD = 0.7

# ─────────────────────────────────────────────────────
# System prompt del intérprete (NO es Violette, es un parser)
# ─────────────────────────────────────────────────────

_INTERPRETER_PROMPT = """Sos un intérprete de intenciones para un sistema POS de ferretería en Costa Rica.
Tu trabajo NO es responder al usuario. Tu trabajo es ENTENDER qué quiere hacer y retornar JSON.

IMPORTANTE — Vocabulario tico:
- "rojos/rojo" = miles de colones (ej: "5 rojos" = ₡5000, "50 rojos" = ₡50000)
- "mae/compa/muchacho" = cliente o persona
- "poneme/metele/echale" = agregar al carrito
- "cobrále/pasale la factura" = confirmar venta
- "harina/plata" = dinero
- "sinpe/transferencia" = método de pago SINPE Móvil
- "tarjeta" = método de pago tarjeta
- "efectivo/cash/en harina" = método de pago efectivo
- "teja/tejo" = billete de ₡10,000

Retorná SOLO un JSON con esta estructura (sin markdown, sin backticks, sin texto extra):
{
  "intent": "<tipo_de_intencion>",
  "confidence": <0.0 a 1.0>,
  "params": { ... },
  "reply": "<respuesta corta SOLO si intent es greeting o general_question>"
}

INTENCIONES posibles:

1. "search_product" — buscar producto en inventario
   params: {"query": "nombre o descripción del producto"}

2. "search_customer" — buscar un cliente
   params: {"query": "nombre del cliente"}

3. "navigate" — ir a una pantalla del sistema
   params: {"module": "dashboard|ventas|productos|clientes|gastos|proveedores|compras|configuracion|categorias|reporte_diario|analytics|proformas"}

4. "query_data" — consultar datos (ventas, gastos, inventario, caja, deudores, etc.)
   params: {"type": "sales|expenses|cash|inventory|low_stock|top_products|debtors|customers|profit", "period": "today|yesterday|week|month|last_month|year"}

5. "set_customer" — asignar cliente a la venta actual
   params: {"name": "nombre del cliente"}

6. "set_payment" — asignar método de pago
   params: {"method": "efectivo|sinpe|tarjeta|transferencia"}

7. "add_to_cart" — agregar producto al carrito (cuando el usuario dice qué quiere vender)
   params: {"query": "nombre del producto", "qty": 1}

8. "confirm_sale" — confirmar/cobrar la venta actual
   params: {}

9. "cancel" — cancelar operación actual
   params: {}

10. "register_expense" — registrar un gasto
    params: {"amount": 5000, "category": "categoría", "description": "detalle"}

11. "greeting" — saludo casual
    params: {}
    reply: "respuesta breve y amigable en tico"

12. "general_question" — pregunta abierta, consultoría, o cualquier cosa que NO encaje arriba
    params: {"question": "la pregunta reformulada"}
    reply: "" (dejar vacío, lo maneja otro módulo)

13. "unknown" — no entendiste la intención
    params: {}

REGLAS:
- Si el usuario dice algo ambiguo, usá el contexto (pantalla, carrito) para desambiguar.
- "confidence" debe reflejar qué tan seguro estás de la intención. Usá 0.9+ para intenciones claras.
- Si la frase puede ser tanto un query_data como un navigate, preferí query_data.
- Para "add_to_cart", extraé la cantidad si la mencionan, sino qty=1.
- Para montos en "rojos": multiplicá por 1000 (5 rojos = 5000).
- NO inventés productos ni clientes, solo extraé lo que el usuario dijo.
- El campo "reply" SOLO se llena para greeting y general_question.
"""


# ─────────────────────────────────────────────────────
# Resultado del intérprete
# ─────────────────────────────────────────────────────

@dataclass
class InterpretedIntent:
    """Resultado estructurado de la interpretación del LLM."""
    intent: str = "unknown"          # Tipo de intención
    confidence: float = 0.0          # 0.0 a 1.0
    params: Dict[str, Any] = field(default_factory=dict)
    reply: str = ""                  # Solo para greeting/general_question
    raw_json: Dict = field(default_factory=dict)  # JSON crudo del LLM

    @property
    def is_actionable(self) -> bool:
        """True si la intención es clara y confiable."""
        return (
            self.intent not in ("unknown", "general_question")
            and self.confidence >= _CONFIDENCE_THRESHOLD
        )


# ─────────────────────────────────────────────────────
# Función principal de interpretación
# ─────────────────────────────────────────────────────

def interpret(
    user_text: str,
    db: Session,
    ui_ctx: Optional[UIContext] = None,
) -> Optional[InterpretedIntent]:
    """
    Usa el LLM para interpretar la intención del usuario.

    Retorna InterpretedIntent si la interpretación fue exitosa,
    o None si no hay LLM disponible o hubo error.

    NO lanza excepciones — siempre retorna None en caso de fallo
    para que el flujo caiga al regex/fuzzy.
    """
    try:
        provider, api_key, extras = get_active_provider(db)
    except RuntimeError:
        return None

    # Construir el mensaje con contexto
    context_prefix = ""
    if ui_ctx:
        ctx_text = build_context_prompt(ui_ctx)
        if ctx_text:
            context_prefix = f"CONTEXTO ACTUAL: {ctx_text}\n\n"

    user_message = f"{context_prefix}MENSAJE DEL USUARIO: \"{user_text}\""

    # Preparar la llamada (sin tools, solo queremos JSON)
    system = provider.format_system_prompt(_INTERPRETER_PROMPT)
    messages = provider.format_messages([
        {"role": "user", "content": user_message},
    ])

    model_override = extras.get("model", "")

    result = provider.call_completion(
        api_key=api_key,
        messages=messages,
        tools=[],       # Sin tools — el intérprete solo retorna JSON
        system=system,
        model=model_override or None,
        max_tokens=_INTERPRETER_MAX_TOKENS,
    )

    if not result["success"]:
        logger.debug("Interpreter LLM call failed: %s", result.get('error_message'))
        return None

    # Extraer texto y parsear JSON
    raw_text = provider.extract_text(result["raw_response"])
    if not raw_text:
        return None

    parsed = _parse_intent_json(raw_text)
    if not parsed:
        return None

    return InterpretedIntent(
        intent=parsed.get("intent", "unknown"),
        confidence=min(1.0, max(0.0, float(parsed.get("confidence", 0.0)))),
        params=parsed.get("params", {}),
        reply=parsed.get("reply", ""),
        raw_json=parsed,
    )


# ─────────────────────────────────────────────────────
# Parser de JSON robusto
# ─────────────────────────────────────────────────────

def _parse_intent_json(text: str) -> Optional[dict]:
    """
    Parsea el JSON de intención del LLM.
    Maneja casos comunes: backticks de markdown, texto extra, etc.
    """
    text = text.strip()

    # Quitar backticks de markdown si los hay
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Intentar parsear directamente
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "intent" in data:
            return data
    except json.JSONDecodeError:
        pass

    # Buscar JSON embebido en texto
    match = re.search(r"\{[^{}]*\"intent\"[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict) and "intent" in data:
                return data
        except json.JSONDecodeError:
            pass

    # Buscar JSON con objetos anidados (params)
    match = re.search(r"\{.*\"intent\".*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict) and "intent" in data:
                return data
        except json.JSONDecodeError:
            pass

    logger.debug("Could not parse intent JSON from: %s", text[:200])
    return None


# ─────────────────────────────────────────────────────
# Ejecutor de intenciones interpretadas
# ─────────────────────────────────────────────────────

def execute_interpreted_intent(
    intent: InterpretedIntent,
    db: Session,
    ui_ctx: Optional[UIContext] = None,
) -> Optional[Dict]:
    """
    Convierte una intención interpretada en acciones/cards/reply
    usando el formato que chat_handler espera.

    Retorna dict con {reply_text, actions, cards} o None si no puede ejecutar.
    """
    params = intent.params
    intent_type = intent.intent

    # ── Greeting ──
    if intent_type == "greeting":
        return {
            "reply_text": intent.reply or "¡Pura vida! 👋 ¿En qué te ayudo?",
            "actions": [],
            "cards": [],
        }

    # ── Search product ──
    if intent_type == "search_product":
        query = params.get("query", "")
        if not query:
            return None
        return {
            "reply_text": f"🔍 Buscando **{query}**...",
            "actions": [{"type": "search_product", "query": query}],
            "cards": [],
        }

    # ── Search customer ──
    if intent_type == "search_customer":
        query = params.get("query", "")
        if not query:
            return None
        return {
            "reply_text": f"🔍 Buscando cliente **{query}**...",
            "actions": [{"type": "navigate", "module": "customers", "query": query}],
            "cards": [],
        }

    # ── Navigate ──
    if intent_type == "navigate":
        module = params.get("module", "")
        # Mapear sinónimos a módulos válidos
        module_map = {
            "configuracion": "configuración",
            "compras": "compras/facturas",
            "facturas": "compras/facturas",
            "reporte_diario": "daily_report",
            "reporte": "daily_report",
            "analytics": "analytics",
            "proformas": "proformas",
        }
        module = module_map.get(module, module)
        if not module:
            return None

        labels = {
            "dashboard": "Dashboard", "ventas": "Punto de venta",
            "productos": "Productos", "clientes": "Clientes",
            "gastos": "Gastos", "proveedores": "Proveedores",
            "compras/facturas": "Compras", "configuración": "Configuración",
            "daily_report": "Reporte diario", "analytics": "Analíticas",
            "categorias": "Categorías", "proformas": "Proformas",
        }
        label = labels.get(module, module)
        return {
            "reply_text": f"Listo 👌 te abro **{label}**.",
            "actions": [{"type": "navigate", "module": module}],
            "cards": [],
        }

    # ── Query data → se delega al LLM con tools (no ejecutar aquí) ──
    if intent_type == "query_data":
        return None  # Dejar que el LLM fallback con tools lo maneje

    # ── Set customer ──
    if intent_type == "set_customer":
        name = params.get("name", "")
        if not name:
            return None
        return {
            "reply_text": f"✅ Cliente asignado: **{name}**",
            "actions": [{"type": "set_customer", "name": name}],
            "cards": [],
        }

    # ── Set payment ──
    if intent_type == "set_payment":
        method = params.get("method", "")
        if not method:
            return None
        return {
            "reply_text": f"✅ Método de pago: **{method}**",
            "actions": [{"type": "set_payment_method", "method": method}],
            "cards": [],
        }

    # ── Add to cart ──
    if intent_type == "add_to_cart":
        query = params.get("query", "")
        qty = params.get("qty", 1)
        if not query:
            return None
        return {
            "reply_text": f"🔍 Buscando **{query}** para agregar {qty} al carrito...",
            "actions": [{"type": "search_product", "query": query, "auto_add_qty": qty}],
            "cards": [],
        }

    # ── Confirm sale ──
    if intent_type == "confirm_sale":
        return {
            "reply_text": "🧾 Preparando la confirmación de venta...",
            "actions": [{"type": "preview_confirm_sale"}],
            "cards": [],
        }

    # ── Cancel ──
    if intent_type == "cancel":
        return {
            "reply_text": "❌ Operación cancelada.",
            "actions": [{"type": "cancel_operation"}],
            "cards": [],
        }

    # ── Register expense ──
    if intent_type == "register_expense":
        amount = params.get("amount", 0)
        category = params.get("category", "general")
        description = params.get("description", "")
        if not amount:
            return None
        return {
            "reply_text": f"📤 Registrando gasto de **₡{amount:,.0f}** en {category}.",
            "actions": [{
                "type": "register_expense",
                "amount": amount,
                "category": category,
                "description": description,
            }],
            "cards": [],
        }

    # ── General question → se delega al LLM con tools ──
    if intent_type == "general_question":
        return None  # El LLM fallback con tools lo maneja

    # ── Unknown / no mapeado ──
    return None