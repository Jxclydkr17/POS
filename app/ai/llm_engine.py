# app/ai/llm_engine.py
"""
Motor LLM con function calling — Refactorizado con capa de abstracción.
Usa el provider registry para seleccionar el proveedor activo (Anthropic, OpenAI, etc.)
en lugar de hablar directo con una API específica.

FASE 2: Lee max_tokens, custom_prompt y model desde la config de BD.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.llm_tools import TOOL_DEFINITIONS, execute_tool
from app.ai.ui_context import UIContext, build_context_prompt
from app.ai.providers.provider_registry import (
    get_active_provider,
    is_any_provider_available,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────────────

_DEFAULT_MAX_TOKENS = 1024
_MAX_TOOL_ROUNDS = 3  # máx ciclos tool_use → result → tool_use

# System prompt base para el LLM (compartido por todos los proveedores)
_SYSTEM_PROMPT = """Eres Violette, el asistente inteligente de un sistema POS (punto de venta) para una ferretería en Costa Rica.

REGLAS ESTRICTAS:
- Respondé SIEMPRE en español costarricense (vos, tuanis, mae, pura vida).
- Sé conciso: máximo 3-4 líneas en respuestas normales. Esto es un chat pequeño, no un ensayo.
- Usá emojis con moderación (1-2 por respuesta).
- La moneda es colones costarricenses (₡). Formateá montos con separador de miles.
- Usá **negrita** para datos importantes.
- Si el usuario pide datos, USÁ las herramientas disponibles. No inventés números.
- Si el usuario pide una acción (cambiar precio, agregar stock, etc.), ejecutá la herramienta correspondiente.
- Si no sabés algo o no tenés herramienta para eso, decilo honestamente.
- NUNCA inventés datos de ventas, inventario o clientes. Si necesitás el dato, usá una herramienta.
- Si el usuario saluda, respondé brevemente y ofrecé ayuda.

CONTEXTO DEL SISTEMA:
- Es un sistema POS para ferretería (herramientas, materiales de construcción, productos varios).
- Maneja: ventas, inventario, clientes, gastos, caja, proveedores, compras, facturación electrónica.
- El usuario es el dueño o empleado del negocio.
"""


def _build_full_system_prompt(custom_prompt: str = "") -> str:
    """Combina el system prompt base con el prompt personalizado del usuario."""
    if not custom_prompt or not custom_prompt.strip():
        return _SYSTEM_PROMPT
    return f"{_SYSTEM_PROMPT}\n\nINSTRUCCIONES ADICIONALES DEL NEGOCIO:\n{custom_prompt.strip()}"


def is_llm_available() -> bool:
    """Verifica si hay un proveedor LLM configurado con API key."""
    return is_any_provider_available()


# ─────────────────────────────────────────────────────
# Conversión de memoria al formato de mensajes
# ─────────────────────────────────────────────────────

def _build_messages(
    user_text: str,
    memory: list[dict],
    ui_ctx: Optional[UIContext] = None,
) -> list[dict]:
    """
    Construye la lista de messages en formato interno.
    El proveedor se encargará de ajustar al formato de su API.
    """
    messages = []

    # Historial (últimos turnos)
    for m in (memory or [])[-6:]:
        role = m.get("role", "")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Agregar contexto UI como prefijo al mensaje actual
    context_prefix = ""
    if ui_ctx:
        ctx_text = build_context_prompt(ui_ctx)
        if ctx_text:
            context_prefix = f"{ctx_text}\n\n"

    # Mensaje actual del usuario
    messages.append({
        "role": "user",
        "content": f"{context_prefix}{user_text}" if context_prefix else user_text,
    })

    return messages


# ─────────────────────────────────────────────────────
# Llamada al LLM con tool use loop (agnóstico al proveedor)
# ─────────────────────────────────────────────────────

def call_llm(
    user_text: str,
    db: Session,
    memory: list[dict] = None,
    ui_ctx: Optional[UIContext] = None,
) -> dict:
    """
    Llama al LLM con function calling.
    Maneja el loop de tool_use automáticamente.
    Usa el proveedor activo del registry.

    Retorna:
        {
            "reply_text": str,
            "actions": list[dict],
            "cards": list[dict],
            "used_llm": True,
        }
    """
    # ── Obtener proveedor activo, API key y config extra ──
    try:
        provider, api_key, extras = get_active_provider(db)
    except RuntimeError:
        return {
            "reply_text": (
                "⚠️ No hay API key de IA configurada. "
                "Configurá tu API key en Ajustes > Asistente IA para habilitar respuestas inteligentes."
            ),
            "actions": [],
            "cards": [],
            "used_llm": False,
        }

    # ── Leer parámetros de config ──
    max_tokens = extras.get("max_tokens", _DEFAULT_MAX_TOKENS)
    custom_prompt = extras.get("custom_prompt", "")
    model_override = extras.get("model", "")

    # ── Preparar mensajes y herramientas ──
    raw_messages = _build_messages(user_text, memory, ui_ctx)
    messages = provider.format_messages(raw_messages)
    system = provider.format_system_prompt(_build_full_system_prompt(custom_prompt))
    tools = provider.format_tools(TOOL_DEFINITIONS)

    all_actions: list[dict] = []
    all_cards: list[dict] = []
    final_text = ""

    # ── Loop de tool_use ──
    for _round in range(_MAX_TOOL_ROUNDS + 1):

        # Llamar al proveedor
        result = provider.call_completion(
            api_key=api_key,
            messages=messages,
            tools=tools,
            system=system,
            model=model_override or None,
            max_tokens=max_tokens,
        )

        # ── Manejar errores ──
        if not result["success"]:
            error_type = result["error_type"]
            error_msg = result["error_message"]

            if error_type == "auth":
                return {
                    "reply_text": f"⚠️ {error_msg} Revisá la configuración.",
                    "actions": [], "cards": [], "used_llm": False,
                }
            if error_type == "rate_limit":
                return {
                    "reply_text": f"⏳ {error_msg}",
                    "actions": [], "cards": [], "used_llm": True,
                }
            if error_type == "timeout":
                return {
                    "reply_text": f"⏳ {error_msg}",
                    "actions": [], "cards": [], "used_llm": True,
                }
            # server_error u otros
            return {
                "reply_text": f"⚠️ {error_msg}",
                "actions": [], "cards": [], "used_llm": False,
            }

        raw_response = result["raw_response"]

        # ── Extraer texto ──
        text = provider.extract_text(raw_response)
        if text:
            final_text = text

        # ── Si no hay tool_use, terminamos ──
        if not provider.is_tool_use_response(raw_response):
            break

        # ── Ejecutar herramientas ──
        tool_calls = provider.extract_tool_calls(raw_response)

        # Agregar el response del assistant a messages
        messages.append(provider.build_assistant_message(raw_response))

        # Ejecutar cada tool y recoger resultados
        tool_results = []
        for tc in tool_calls:
            logger.info(f"LLM tool_use: {tc.name}({tc.input})")

            # Ejecutar herramienta
            tool_result = execute_tool(tc.name, tc.input, db)

            # Recoger acciones y cards del resultado
            if tool_result.get("actions"):
                all_actions.extend(tool_result["actions"])
            if tool_result.get("cards"):
                all_cards.extend(tool_result["cards"])

            # Preparar resultado para el LLM
            result_text = tool_result.get("reply_text", "")
            result_data = tool_result.get("data", {})

            tool_result_content = result_text
            if result_data:
                tool_result_content += f"\n\nDatos: {json.dumps(result_data, ensure_ascii=False, default=str)}"

            tool_results.append(
                provider.format_tool_result(tc.id, tool_result_content)
            )

        # Agregar resultados de herramientas al historial (formato varía por proveedor)
        messages.extend(provider.build_tool_results_messages(tool_results))

    return {
        "reply_text": final_text or "No pude generar una respuesta. Intentá reformular tu pregunta.",
        "actions": all_actions,
        "cards": all_cards,
        "used_llm": True,
    }