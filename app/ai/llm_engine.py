# app/ai/llm_engine.py
"""
FASE 6 — Motor LLM con function calling.
Llama a la API de Anthropic cuando el clasificador local no resuelve la consulta.
Soporta tool_use (function calling) para ejecutar acciones contra la BD.
"""
from __future__ import annotations

import json
import os
import logging
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy.orm import Session

from app.ai.llm_tools import TOOL_DEFINITIONS, execute_tool
from app.ai.ui_context import UIContext, build_context_prompt

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────────────

_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-sonnet-4-20250514"
_MAX_TOKENS = 1024
_MAX_TOOL_ROUNDS = 3  # máx ciclos tool_use → result → tool_use

# System prompt para el LLM
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


def _get_api_key() -> Optional[str]:
    """Obtiene la API key de Anthropic."""
    # 1) Variable de entorno
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key

    # 2) Archivo .env en raíz del proyecto
    for env_path in [".env", "../.env", "../../.env"]:
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ANTHROPIC_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
        except (FileNotFoundError, PermissionError):
            continue

    return None


def is_llm_available() -> bool:
    """Verifica si hay una API key configurada."""
    return bool(_get_api_key())


# ─────────────────────────────────────────────────────
# Conversión de memoria al formato Anthropic
# ─────────────────────────────────────────────────────

def _build_messages(
    user_text: str,
    memory: list[dict],
    ui_ctx: Optional[UIContext] = None,
) -> list[dict]:
    """
    Construye la lista de messages para la API de Anthropic.
    Incluye historial de conversación + contexto UI.
    """
    messages = []

    # Historial (últimos turnos)
    for m in (memory or [])[-6:]:
        role = m.get("role", "")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Asegurar alternancia correcta (Anthropic requiere user/assistant alternados)
    cleaned = []
    last_role = None
    for msg in messages:
        if msg["role"] == last_role:
            continue  # skip duplicados consecutivos
        cleaned.append(msg)
        last_role = msg["role"]

    # Agregar contexto UI como prefijo al mensaje actual
    context_prefix = ""
    if ui_ctx:
        ctx_text = build_context_prompt(ui_ctx)
        if ctx_text:
            context_prefix = f"{ctx_text}\n\n"

    # Mensaje actual del usuario
    cleaned.append({
        "role": "user",
        "content": f"{context_prefix}{user_text}" if context_prefix else user_text,
    })

    # Anthropic requiere que el primer mensaje sea "user"
    if cleaned and cleaned[0]["role"] != "user":
        cleaned = cleaned[1:]

    return cleaned


# ─────────────────────────────────────────────────────
# Llamada al LLM con tool use loop
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

    Retorna:
        {
            "reply_text": str,
            "actions": list[dict],
            "cards": list[dict],
            "used_llm": True,
        }
    """
    api_key = _get_api_key()
    if not api_key:
        return {
            "reply_text": "⚠️ No hay API key de Anthropic configurada. Configurá la variable ANTHROPIC_API_KEY para habilitar respuestas inteligentes.",
            "actions": [],
            "cards": [],
            "used_llm": False,
        }

    messages = _build_messages(user_text, memory, ui_ctx)
    all_actions: list[dict] = []
    all_cards: list[dict] = []
    final_text = ""

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    for _round in range(_MAX_TOOL_ROUNDS + 1):
        payload = {
            "model": _MODEL,
            "max_tokens": _MAX_TOKENS,
            "system": _SYSTEM_PROMPT,
            "messages": messages,
            "tools": TOOL_DEFINITIONS,
        }

        try:
            resp = requests.post(
                _API_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if resp.status_code == 401:
                return {
                    "reply_text": "⚠️ API key de Anthropic inválida. Revisá la configuración.",
                    "actions": [], "cards": [], "used_llm": False,
                }

            if resp.status_code == 429:
                return {
                    "reply_text": "⏳ Demasiadas consultas al asistente. Esperá un momento e intentá de nuevo.",
                    "actions": [], "cards": [], "used_llm": True,
                }

            if resp.status_code != 200:
                logger.warning(f"LLM API error {resp.status_code}: {resp.text[:200]}")
                return {
                    "reply_text": "⚠️ Error al consultar el asistente. Intentá de nuevo.",
                    "actions": [], "cards": [], "used_llm": False,
                }

            data = resp.json()

        except requests.Timeout:
            return {
                "reply_text": "⏳ El asistente tardó mucho. Intentá de nuevo o usá un comando directo.",
                "actions": [], "cards": [], "used_llm": True,
            }
        except Exception as e:
            logger.error(f"LLM request error: {e}")
            return {
                "reply_text": "⚠️ Error de conexión con el asistente.",
                "actions": [], "cards": [], "used_llm": False,
            }

        # ── Procesar la respuesta ──
        stop_reason = data.get("stop_reason", "")
        content_blocks = data.get("content", [])

        # Extraer texto
        text_parts = []
        tool_uses = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_uses.append(block)

        if text_parts:
            final_text = "\n".join(text_parts)

        # ── Si no hay tool_use, terminamos ──
        if stop_reason != "tool_use" or not tool_uses:
            break

        # ── Ejecutar herramientas ──
        # Agregar el response del assistant a messages
        messages.append({"role": "assistant", "content": content_blocks})

        tool_results = []
        for tool_block in tool_uses:
            tool_name = tool_block.get("name", "")
            tool_id = tool_block.get("id", "")
            tool_input = tool_block.get("input", {})

            logger.info(f"LLM tool_use: {tool_name}({tool_input})")

            # Ejecutar herramienta
            result = execute_tool(tool_name, tool_input, db)

            # Recoger acciones y cards del resultado
            if result.get("actions"):
                all_actions.extend(result["actions"])
            if result.get("cards"):
                all_cards.extend(result["cards"])

            # Preparar resultado para el LLM
            result_text = result.get("reply_text", "")
            result_data = result.get("data", {})

            tool_result_content = result_text
            if result_data:
                tool_result_content += f"\n\nDatos: {json.dumps(result_data, ensure_ascii=False, default=str)}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": tool_result_content,
            })

        # Agregar resultados de herramientas
        messages.append({"role": "user", "content": tool_results})

    return {
        "reply_text": final_text or "No pude generar una respuesta. Intentá reformular tu pregunta.",
        "actions": all_actions,
        "cards": all_cards,
        "used_llm": True,
    }