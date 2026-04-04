# app/ai/providers/google_provider.py
"""
Proveedor LLM para Google Gemini.
Implementa la interfaz BaseLLMProvider adaptando las diferencias clave:

  - System prompt: campo separado `system_instruction` con `parts`
  - Mensajes: `contents` con `parts`, roles "user" / "model" (no "assistant")
  - Alternancia estricta: user → model → user → model (fusiona consecutivos)
  - Tools: `function_declarations` con schema propio (sin "input_schema")
  - Tool use: `functionCall` dentro de `parts`
  - Tool result: `functionResponse` dentro de `parts`, con rol "user"
  - Auth: header `x-goog-api-key` (no Bearer)
  - Endpoint: modelo va en la URL, no en el body
  - Safety settings: configurables para evitar falsos positivos en POS
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import requests

from app.ai.providers.base import BaseLLMProvider, ToolCall

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# Configuración específica de Google Gemini
# ─────────────────────────────────────────────────────

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_MODEL = "gemini-2.0-flash"
_REQUEST_TIMEOUT = 30

# Safety settings relajados para POS (evitar falsos positivos con
# nombres de productos como "cuchillo", "machete", "veneno para ratas", etc.)
_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
]


class GoogleProvider(BaseLLMProvider):
    """Proveedor LLM usando la API de Google Gemini."""

    name = "google"
    display_name = "Gemini (Google)"
    requires_api_key = True
    supported_models = [
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ]
    default_model = _DEFAULT_MODEL

    # ── Validación de API key ──

    def validate_api_key(self, api_key: str) -> bool:
        """
        Valida la API key de Google Gemini.
        Hace una llamada mínima para confirmar autenticación.
        """
        if not api_key or not isinstance(api_key, str):
            return False

        api_key = api_key.strip()
        if len(api_key) < 10:
            return False

        url = f"{_API_BASE}/models/{self.default_model}:generateContent"

        try:
            resp = requests.post(
                url,
                headers={
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 5},
                },
                timeout=15,
            )
            # 401/403 = key inválida o sin permisos
            return resp.status_code not in (401, 403)
        except Exception as e:
            logger.warning(f"Error validando API key de Google: {e}")
            return False

    # ── Formateo del system prompt ──

    def format_system_prompt(self, base_prompt: str) -> Dict:
        """
        Gemini usa `system_instruction` como campo separado en el payload.
        """
        return {"parts": [{"text": base_prompt}]}

    # ── Formateo de mensajes ──

    def format_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        Convierte mensajes al formato Gemini:
        - role "assistant" → "model"
        - content string → parts: [{text: ...}]
        - Fusiona mensajes consecutivos del mismo rol (Gemini es estricto)
        - Garantiza alternancia user → model → user
        """
        if not messages:
            return []

        # Paso 1: Convertir al formato Gemini básico
        gemini_msgs = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if not role or not content:
                continue

            # Mapear roles
            if role == "assistant":
                gemini_role = "model"
            elif role == "user":
                gemini_role = "user"
            else:
                continue

            # Convertir content
            if isinstance(content, str):
                parts = [{"text": content}]
            elif isinstance(content, list):
                # Ya viene como parts (tool results, etc.)
                parts = content
            else:
                parts = [{"text": str(content)}]

            gemini_msgs.append({"role": gemini_role, "parts": parts})

        if not gemini_msgs:
            return []

        # Paso 2: Fusionar mensajes consecutivos del mismo rol
        merged = [gemini_msgs[0]]
        for msg in gemini_msgs[1:]:
            if msg["role"] == merged[-1]["role"]:
                # Fusionar parts
                merged[-1]["parts"].extend(msg["parts"])
            else:
                merged.append(msg)

        # Paso 3: Garantizar que empieza con "user"
        if merged and merged[0]["role"] != "user":
            merged = merged[1:]

        return merged

    # ── Formateo de herramientas ──

    def format_tools(self, tool_definitions: List[Dict]) -> List[Dict]:
        """
        Convierte las definiciones de tools del formato Anthropic al formato Gemini.

        Anthropic:
            {"name": "...", "description": "...", "input_schema": {
                "type": "object", "properties": {...}, "required": [...]
            }}

        Gemini:
            {"function_declarations": [
                {"name": "...", "description": "...", "parameters": {
                    "type": "OBJECT", "properties": {...}, "required": [...]
                }}
            ]}
        """
        declarations = []
        for tool in tool_definitions:
            schema = tool.get("input_schema", {})
            params = self._convert_schema_to_gemini(schema)

            decl = {
                "name": tool["name"],
                "description": tool.get("description", ""),
            }

            # Solo agregar parameters si hay propiedades
            if params.get("properties"):
                decl["parameters"] = params

            declarations.append(decl)

        return [{"function_declarations": declarations}]

    @staticmethod
    def _convert_schema_to_gemini(schema: dict) -> dict:
        """
        Convierte JSON Schema estándar al formato de Gemini.
        Gemini usa tipos en MAYÚSCULAS y tiene algunas diferencias.
        """
        if not schema:
            return {}

        type_map = {
            "object": "OBJECT",
            "string": "STRING",
            "integer": "INTEGER",
            "number": "NUMBER",
            "boolean": "BOOLEAN",
            "array": "ARRAY",
        }

        result = {}

        # Tipo
        schema_type = schema.get("type", "object")
        result["type"] = type_map.get(schema_type, "OBJECT")

        # Propiedades
        props = schema.get("properties", {})
        if props:
            gemini_props = {}
            for name, prop_schema in props.items():
                gemini_prop = {}
                prop_type = prop_schema.get("type", "string")
                gemini_prop["type"] = type_map.get(prop_type, "STRING")

                if "description" in prop_schema:
                    gemini_prop["description"] = prop_schema["description"]
                if "enum" in prop_schema:
                    gemini_prop["enum"] = prop_schema["enum"]

                gemini_props[name] = gemini_prop

            result["properties"] = gemini_props

        # Required
        required = schema.get("required", [])
        if required:
            result["required"] = required

        return result

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
        Ejecuta la llamada a la API de Gemini.
        El modelo va en la URL, no en el body.
        """
        model_name = model or self.default_model

        # Modelo en la URL
        url = f"{_API_BASE}/models/{model_name}:generateContent"

        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

        payload: Dict[str, Any] = {
            "contents": messages,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
            },
            "safetySettings": _SAFETY_SETTINGS,
        }

        # System instruction
        if system:
            payload["system_instruction"] = system

        # Tools (solo si hay declaraciones)
        if tools:
            payload["tools"] = tools

        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=_REQUEST_TIMEOUT,
            )

            if resp.status_code in (401, 403):
                return {
                    "success": False,
                    "raw_response": None,
                    "error_type": "auth",
                    "error_message": "API key de Google inválida o sin permisos.",
                }

            if resp.status_code == 429:
                return {
                    "success": False,
                    "raw_response": None,
                    "error_type": "rate_limit",
                    "error_message": "Demasiadas consultas. Esperá un momento.",
                }

            if resp.status_code != 200:
                error_detail = ""
                try:
                    err_data = resp.json()
                    error_detail = err_data.get("error", {}).get("message", "")
                except Exception:
                    error_detail = resp.text[:200]
                logger.warning(f"Gemini API error {resp.status_code}: {error_detail}")
                return {
                    "success": False,
                    "raw_response": None,
                    "error_type": "server_error",
                    "error_message": "Error al consultar el asistente.",
                }

            data = resp.json()

            # Verificar bloqueo por safety filters
            if self._is_blocked(data):
                logger.warning("Gemini response blocked by safety filters")
                return {
                    "success": False,
                    "raw_response": None,
                    "error_type": "server_error",
                    "error_message": "La respuesta fue bloqueada por filtros de seguridad. Intentá reformular.",
                }

            return {
                "success": True,
                "raw_response": data,
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
            logger.error(f"Gemini request error: {e}")
            return {
                "success": False,
                "raw_response": None,
                "error_type": "server_error",
                "error_message": "Error de conexión con el asistente.",
            }

    @staticmethod
    def _is_blocked(data: dict) -> bool:
        """Verifica si la respuesta fue bloqueada por safety filters."""
        # Chequear promptFeedback
        feedback = data.get("promptFeedback", {})
        if feedback.get("blockReason"):
            return True

        # Chequear candidates vacíos o con finishReason SAFETY
        candidates = data.get("candidates", [])
        if not candidates:
            return True

        finish_reason = candidates[0].get("finishReason", "")
        if finish_reason == "SAFETY":
            return True

        return False

    # ── Extracción de texto ──

    def extract_text(self, raw_response: Dict) -> str:
        """
        Extrae texto de la respuesta de Gemini.
        Estructura: candidates[0].content.parts[*].text
        """
        if not raw_response:
            return ""

        candidates = raw_response.get("candidates", [])
        if not candidates:
            return ""

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        text_parts = [
            part["text"]
            for part in parts
            if "text" in part
        ]
        return "\n".join(text_parts)

    # ── Extracción de tool calls ──

    def extract_tool_calls(self, raw_response: Dict) -> List[ToolCall]:
        """
        Extrae functionCall parts de la respuesta de Gemini.
        Estructura: candidates[0].content.parts[*].functionCall
        """
        if not raw_response:
            return []

        candidates = raw_response.get("candidates", [])
        if not candidates:
            return []

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        result = []
        for i, part in enumerate(parts):
            fc = part.get("functionCall")
            if not fc:
                continue

            result.append(ToolCall(
                # Gemini no genera IDs explícitos para function calls,
                # usamos el nombre + índice como identificador
                id=f"gemini_{fc.get('name', 'unknown')}_{i}",
                name=fc.get("name", ""),
                input=fc.get("args", {}),
            ))

        return result

    # ── Formateo de resultado de herramienta ──

    def format_tool_result(self, tool_call_id: str, result_content: str) -> Dict:
        """
        Gemini: functionResponse dentro de un part.
        El tool_call_id contiene el nombre de la función (gemini_{name}_{i}).
        """
        # Extraer el nombre de la función del ID
        parts = tool_call_id.split("_")
        # gemini_query_sales_0 → query_sales
        func_name = "_".join(parts[1:-1]) if len(parts) > 2 else tool_call_id

        # Gemini espera la response como un dict, no como string
        try:
            response_data = json.loads(result_content) if result_content.strip().startswith("{") else {"result": result_content}
        except (json.JSONDecodeError, TypeError):
            response_data = {"result": result_content}

        return {
            "functionResponse": {
                "name": func_name,
                "response": response_data,
            }
        }

    # ── Detección de tool_use ──

    def is_tool_use_response(self, raw_response: Dict) -> bool:
        """
        Gemini indica tool use cuando hay functionCall parts en la respuesta.
        No hay un "stop_reason" específico como en otros proveedores.
        """
        if not raw_response:
            return False

        candidates = raw_response.get("candidates", [])
        if not candidates:
            return False

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        return any("functionCall" in part for part in parts)

    # ── Construcción de mensaje assistant ──

    def build_assistant_message(self, raw_response: Dict) -> Dict:
        """
        Construye el mensaje del model para agregar al historial.
        Gemini usa role "model" con parts completos.
        """
        candidates = raw_response.get("candidates", [])
        if not candidates:
            return {"role": "model", "parts": [{"text": ""}]}

        content = candidates[0].get("content", {})
        return {
            "role": content.get("role", "model"),
            "parts": content.get("parts", []),
        }

    # ── Construcción de mensajes de tool results ──

    def build_tool_results_messages(self, tool_results: List[Dict]) -> List[Dict]:
        """
        Gemini: los functionResponse van como parts dentro de UN mensaje user.
        Esto cierra el ciclo: model (functionCall) → user (functionResponse).
        """
        return [{"role": "user", "parts": tool_results}]