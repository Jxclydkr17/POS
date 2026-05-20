# app/ai/providers/anthropic_provider.py
"""
Proveedor LLM para Anthropic (Claude).
Migración del código existente en llm_engine.py a la interfaz BaseLLMProvider.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from app.ai.providers.base import BaseLLMProvider, ToolCall

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# Configuración específica de Anthropic
# ─────────────────────────────────────────────────────

_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

# ── FASE 1.2 — Fix 1.2: Modelos vigentes en la API de Anthropic ──
# Default: Sonnet 4.6 — mantiene continuidad con el Sonnet 4 anterior
# (mismo tier, mismo precio $3/$15 por millón de tokens), pero con
# mejor calidad. Recomendado para uso general en un POS.
# Para reducir costos, el usuario puede cambiar a Haiku 4.5 desde
# Configuración > Asistente IA (es ~3x más barato y suficiente para
# la mayoría de consultas del POS).
_DEFAULT_MODEL = "claude-sonnet-4-6"

# ── FASE 1.2 — Fix 1.2: Modelos deprecados ──
# Anthropic anunció el 14-abr-2026 la deprecación de claude-sonnet-4
# y claude-opus-4 (originales de mayo 2025), con retiro en la API el
# 15-jun-2026. Después de esa fecha, las llamadas devuelven error.
#
# Si una instalación existente tiene uno de estos modelos guardado en
# `ai_config.model`, el flujo de auto-migración en provider_registry
# lo reemplaza por el default actual la primera vez que se invoca el
# asistente. Esta lista es la red de seguridad para evitar 100% que
# se llame a un modelo retirado.
_DEPRECATED_MODELS: frozenset[str] = frozenset({
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
})

_REQUEST_TIMEOUT = 30


class AnthropicProvider(BaseLLMProvider):
    """Proveedor LLM usando la API de Anthropic (Claude)."""

    name = "anthropic"
    display_name = "Claude (Anthropic)"
    requires_api_key = True

    # Lista de modelos seleccionables desde la UI.
    # Orden = orden en que aparecen en el dropdown (default primero).
    # Mantener sincronizado con https://platform.claude.com/docs/en/about-claude/models
    supported_models = [
        "claude-sonnet-4-6",          # Default — mejor balance precio/calidad
        "claude-opus-4-7",            # Flagship — máxima capacidad
        "claude-haiku-4-5-20251001",  # Más rápido y barato ($1/$5)
        "claude-sonnet-4-5-20250929", # Sonnet generación anterior
        "claude-opus-4-1-20250805",   # Opus generación anterior
    ]
    default_model = _DEFAULT_MODEL

    # Atributo de clase — usado por provider_registry para auto-migrar
    # `ai_config.model` cuando una instalación existente tiene un
    # modelo deprecado guardado.
    deprecated_models = _DEPRECATED_MODELS

    # ── FASE 1.2: Helper para sanear modelo en tiempo de ejecución ──

    def _safe_model(self, requested: Optional[str]) -> str:
        """
        Devuelve un model_id seguro para enviar a la API.

        Si `requested` está vacío o es uno de los modelos deprecados,
        cae al `default_model` actual. Esto previene 100% que una
        configuración vieja en BD o un .env con un modelo retirado
        rompa el chat del POS.
        """
        if not requested or not requested.strip():
            return self.default_model
        if requested in _DEPRECATED_MODELS:
            logger.warning(
                "Modelo Claude '%s' está deprecado (retira 15-jun-2026). "
                "Usando '%s' en su lugar. Actualice ai_config.model.",
                requested, self.default_model,
            )
            return self.default_model
        return requested

    # ── Validación de API key ──

    def validate_api_key(self, api_key: str) -> bool:
        """
        Valida la API key de Anthropic.
        Verifica formato básico y hace una llamada mínima para confirmar autenticación.
        """
        if not api_key or not isinstance(api_key, str):
            return False

        api_key = api_key.strip()

        # Validación de formato: las keys de Anthropic empiezan con "sk-ant-"
        if not api_key.startswith("sk-ant-"):
            return False

        # Llamada mínima para verificar autenticación
        try:
            resp = requests.post(
                _API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": _ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self.default_model,
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=15,
            )
            # 200 = key válida, 401 = key inválida
            # Cualquier otro status (400, 429, etc.) significa que la key es válida
            # pero hubo otro problema
            return resp.status_code != 401
        except Exception as e:
            logger.warning(f"Error validando API key de Anthropic: {e}")
            return False

    # ── Formateo del system prompt ──

    def format_system_prompt(self, base_prompt: str) -> str:
        """Anthropic usa el system prompt como string directo en el campo 'system'."""
        return base_prompt

    # ── Formateo de mensajes ──

    def format_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        Anthropic requiere:
        - Primer mensaje sea 'user'
        - Roles alternados (user/assistant)
        - Sin duplicados consecutivos del mismo rol
        """
        if not messages:
            return messages

        # Asegurar alternancia correcta
        cleaned = []
        last_role = None
        for msg in messages:
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue
            if role == last_role:
                continue  # skip duplicados consecutivos
            cleaned.append(msg)
            last_role = role

        # Primer mensaje debe ser "user"
        if cleaned and cleaned[0]["role"] != "user":
            cleaned = cleaned[1:]

        return cleaned

    # ── Formateo de herramientas ──

    def format_tools(self, tool_definitions: List[Dict]) -> List[Dict]:
        """
        Anthropic usa el formato nativo de tool definitions.
        Nuestro formato interno ya es compatible con Anthropic, así que
        se retorna tal cual.
        """
        return tool_definitions

    # ── Llamada al API ──

    def call_completion(
        self,
        *,
        api_key: str,
        messages: List[Dict],
        tools: Any,
        system: Any,
        model: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> Dict:
        """
        Ejecuta la llamada a la API de Anthropic.
        Retorna respuesta normalizada.
        """
        headers = {
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        # FASE 1.2: sanitizar el modelo — si está deprecated o vacío,
        # cae al default vigente. Evita errores 4xx por modelo retirado.
        effective_model = self._safe_model(model)

        payload = {
            "model": effective_model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
        }

        try:
            resp = requests.post(
                _API_URL,
                headers=headers,
                json=payload,
                timeout=_REQUEST_TIMEOUT,
            )

            if resp.status_code == 401:
                return {
                    "success": False,
                    "raw_response": None,
                    "error_type": "auth",
                    "error_message": "API key de Anthropic inválida.",
                }

            if resp.status_code == 429:
                return {
                    "success": False,
                    "raw_response": None,
                    "error_type": "rate_limit",
                    "error_message": "Demasiadas consultas. Esperá un momento.",
                }

            if resp.status_code != 200:
                logger.warning(f"Anthropic API error {resp.status_code}: {resp.text[:200]}")
                return {
                    "success": False,
                    "raw_response": None,
                    "error_type": "server_error",
                    "error_message": "Error al consultar el asistente.",
                }

            return {
                "success": True,
                "raw_response": resp.json(),
                "error_type": None,
                "error_message": None,
            }

        except requests.Timeout:
            return {
                "success": False,
                "raw_response": None,
                "error_type": "timeout",
                "error_message": "El asistente tardó mucho. Intentá de nuevo.",
            }
        except Exception as e:
            logger.error(f"Anthropic request error: {e}")
            return {
                "success": False,
                "raw_response": None,
                "error_type": "server_error",
                "error_message": "Error de conexión con el asistente.",
            }

    # ── Extracción de texto ──

    def extract_text(self, raw_response: Dict) -> str:
        """Extrae bloques de texto de la respuesta de Anthropic."""
        if not raw_response:
            return ""

        content_blocks = raw_response.get("content", [])
        text_parts = [
            block["text"]
            for block in content_blocks
            if block.get("type") == "text" and block.get("text")
        ]
        return "\n".join(text_parts)

    # ── Extracción de tool calls ──

    def extract_tool_calls(self, raw_response: Dict) -> List[ToolCall]:
        """Extrae tool_use blocks de la respuesta de Anthropic."""
        if not raw_response:
            return []

        content_blocks = raw_response.get("content", [])
        return [
            ToolCall(
                id=block.get("id", ""),
                name=block.get("name", ""),
                input=block.get("input", {}),
            )
            for block in content_blocks
            if block.get("type") == "tool_use"
        ]

    # ── Formateo de resultado de herramienta ──

    def format_tool_result(self, tool_call_id: str, result_content: str) -> Dict:
        """Formatea un tool_result para Anthropic."""
        return {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": result_content,
        }

    # ── Detección de tool_use ──

    def is_tool_use_response(self, raw_response: Dict) -> bool:
        """Verifica si la respuesta de Anthropic requiere ejecución de tools."""
        if not raw_response:
            return False

        stop_reason = raw_response.get("stop_reason", "")
        if stop_reason != "tool_use":
            return False

        # Verificar que efectivamente hay bloques tool_use
        content_blocks = raw_response.get("content", [])
        return any(block.get("type") == "tool_use" for block in content_blocks)

    # ── Construcción de mensaje assistant ──

    def build_assistant_message(self, raw_response: Dict) -> Dict:
        """
        Construye el mensaje del assistant para agregar al historial.
        Anthropic necesita los content blocks completos (text + tool_use).
        """
        content_blocks = raw_response.get("content", [])
        return {"role": "assistant", "content": content_blocks}

    # ── Construcción de mensajes de tool results ──

    def build_tool_results_messages(self, tool_results: List[Dict]) -> List[Dict]:
        """
        Anthropic: todos los tool results van en UN solo mensaje user.
        """
        return [{"role": "user", "content": tool_results}]