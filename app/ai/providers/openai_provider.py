# app/ai/providers/openai_provider.py
"""
Proveedor LLM para OpenAI (ChatGPT).
Implementa la interfaz BaseLLMProvider adaptando las diferencias clave:

  - System prompt: mensaje con role "system" dentro de messages
  - Tools: formato "function" con "parameters" (JSON Schema estándar)
  - Tool use: finish_reason "tool_calls" en choices[0]
  - Tool result: mensajes separados con role "tool"
  - Headers: Authorization Bearer
  - Endpoint: api.openai.com/v1/chat/completions
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import requests

from app.ai.providers.base import BaseLLMProvider, ToolCall

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# Configuración específica de OpenAI
# ─────────────────────────────────────────────────────

_API_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-4o-mini"
_REQUEST_TIMEOUT = 30


class OpenAIProvider(BaseLLMProvider):
    """Proveedor LLM usando la API de OpenAI (ChatGPT)."""

    name = "openai"
    display_name = "ChatGPT (OpenAI)"
    requires_api_key = True
    supported_models = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
    ]
    default_model = _DEFAULT_MODEL

    # ── Validación de API key ──

    def validate_api_key(self, api_key: str) -> bool:
        """
        Valida la API key de OpenAI.
        Hace una llamada mínima para confirmar autenticación.
        """
        if not api_key or not isinstance(api_key, str):
            return False

        api_key = api_key.strip()

        # Validación de formato: las keys de OpenAI empiezan con "sk-"
        if not api_key.startswith("sk-"):
            return False

        # Llamada mínima para verificar autenticación
        try:
            resp = requests.post(
                _API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.default_model,
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=15,
            )
            # 401 = key inválida, cualquier otro status = key reconocida
            return resp.status_code != 401
        except Exception as e:
            logger.warning(f"Error validando API key de OpenAI: {e}")
            return False

    # ── Formateo del system prompt ──

    def format_system_prompt(self, base_prompt: str) -> Dict:
        """
        OpenAI usa el system prompt como un mensaje con role "system"
        que se inserta al inicio de la lista de messages.
        Retorna el dict del mensaje para ser prepended.
        """
        return {"role": "system", "content": base_prompt}

    # ── Formateo de mensajes ──

    def format_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        OpenAI es más flexible que Anthropic con la alternancia.
        Filtra mensajes vacíos y asegura formato correcto.
        """
        if not messages:
            return messages

        cleaned = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                cleaned.append({"role": role, "content": content})

        return cleaned

    # ── Formateo de herramientas ──

    def format_tools(self, tool_definitions: List[Dict]) -> List[Dict]:
        """
        Convierte las definiciones de tools del formato Anthropic al formato OpenAI.

        Anthropic:
            {"name": "...", "description": "...", "input_schema": {...}}

        OpenAI:
            {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
        """
        openai_tools = []
        for tool in tool_definitions:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }),
                },
            }
            openai_tools.append(openai_tool)
        return openai_tools

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
        Ejecuta la llamada a la API de OpenAI.
        Nota: el system prompt se inyecta al inicio de messages.
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # OpenAI: system prompt va como primer mensaje
        full_messages = []
        if system:
            if isinstance(system, dict):
                full_messages.append(system)
            else:
                full_messages.append({"role": "system", "content": str(system)})
        full_messages.extend(messages)

        payload = {
            "model": model or self.default_model,
            "max_tokens": max_tokens,
            "messages": full_messages,
        }

        # Solo agregar tools si hay definiciones
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

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
                    "error_message": "API key de OpenAI inválida.",
                }

            if resp.status_code == 429:
                return {
                    "success": False,
                    "raw_response": None,
                    "error_type": "rate_limit",
                    "error_message": "Demasiadas consultas. Esperá un momento.",
                }

            if resp.status_code != 200:
                logger.warning(f"OpenAI API error {resp.status_code}: {resp.text[:200]}")
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
            logger.error(f"OpenAI request error: {e}")
            return {
                "success": False,
                "raw_response": None,
                "error_type": "server_error",
                "error_message": "Error de conexión con el asistente.",
            }

    # ── Extracción de texto ──

    def extract_text(self, raw_response: Dict) -> str:
        """
        Extrae el texto de la respuesta de OpenAI.
        Estructura: {"choices": [{"message": {"content": "..."}}]}
        """
        if not raw_response:
            return ""

        choices = raw_response.get("choices", [])
        if not choices:
            return ""

        message = choices[0].get("message", {})
        return message.get("content") or ""

    # ── Extracción de tool calls ──

    def extract_tool_calls(self, raw_response: Dict) -> List[ToolCall]:
        """
        Extrae tool_calls de la respuesta de OpenAI.
        Estructura: choices[0].message.tool_calls = [
            {"id": "...", "type": "function", "function": {"name": "...", "arguments": "{...}"}}
        ]
        """
        if not raw_response:
            return []

        choices = raw_response.get("choices", [])
        if not choices:
            return []

        message = choices[0].get("message", {})
        tool_calls_raw = message.get("tool_calls", [])

        result = []
        for tc in tool_calls_raw:
            if tc.get("type") != "function":
                continue

            func = tc.get("function", {})
            func_name = func.get("name", "")

            # OpenAI envía los arguments como JSON string
            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str)
            except (json.JSONDecodeError, TypeError):
                args = {}

            result.append(ToolCall(
                id=tc.get("id", ""),
                name=func_name,
                input=args,
            ))

        return result

    # ── Formateo de resultado de herramienta ──

    def format_tool_result(self, tool_call_id: str, result_content: str) -> Dict:
        """
        OpenAI: cada tool result es un mensaje separado con role "tool".
        """
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result_content,
        }

    # ── Detección de tool_use ──

    def is_tool_use_response(self, raw_response: Dict) -> bool:
        """
        OpenAI indica tool_use con finish_reason "tool_calls".
        """
        if not raw_response:
            return False

        choices = raw_response.get("choices", [])
        if not choices:
            return False

        finish_reason = choices[0].get("finish_reason", "")
        if finish_reason != "tool_calls":
            return False

        # Verificar que hay tool_calls en el mensaje
        message = choices[0].get("message", {})
        return bool(message.get("tool_calls"))

    # ── Construcción de mensaje assistant ──

    def build_assistant_message(self, raw_response: Dict) -> Dict:
        """
        Construye el mensaje del assistant para agregar al historial.
        OpenAI necesita el message completo incluyendo tool_calls.
        """
        choices = raw_response.get("choices", [])
        if not choices:
            return {"role": "assistant", "content": ""}

        message = choices[0].get("message", {})
        return message

    # ── Construcción de mensajes de tool results ──

    def build_tool_results_messages(self, tool_results: List[Dict]) -> List[Dict]:
        """
        OpenAI: cada tool result es un mensaje independiente con role "tool".
        Se agregan directamente a messages como elementos separados.
        """
        return tool_results