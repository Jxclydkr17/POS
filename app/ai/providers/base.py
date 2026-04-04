# app/ai/providers/base.py
"""
Clase abstracta que define la interfaz de cualquier proveedor LLM.
Todos los proveedores (Anthropic, OpenAI, Google, etc.) implementan esta interfaz.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────
# Modelo unificado para tool calls
# ─────────────────────────────────────────────────────

@dataclass
class ToolCall:
    """Representación unificada de una llamada a herramienta, agnóstica al proveedor."""
    id: str                        # ID único del tool call (lo genera el LLM)
    name: str                      # Nombre de la herramienta (ej: "query_sales")
    input: Dict[str, Any] = field(default_factory=dict)  # Parámetros de entrada


# ─────────────────────────────────────────────────────
# Clase abstracta base
# ─────────────────────────────────────────────────────

class BaseLLMProvider(ABC):
    """
    Interfaz que todo proveedor de LLM debe implementar.

    Cada proveedor encapsula:
      - Cómo se valida su API key
      - Cómo se formatea el system prompt, messages, tools
      - Cómo se hace la llamada HTTP
      - Cómo se extraen texto y tool_calls de la respuesta
      - Cómo se formatean los resultados de tools para enviarlos de vuelta
    """

    # ── Metadata del proveedor ──
    name: str = ""                          # "anthropic" | "openai" | "google"
    display_name: str = ""                  # "Claude (Anthropic)" | "ChatGPT (OpenAI)"
    requires_api_key: bool = True
    supported_models: List[str] = []        # ["claude-sonnet-4-20250514", ...]
    default_model: str = ""                 # Modelo por defecto

    @abstractmethod
    def validate_api_key(self, api_key: str) -> bool:
        """
        Valida que una API key sea funcional (formato correcto + llamada de prueba opcional).
        Retorna True si la key es válida.
        """
        ...

    @abstractmethod
    def format_system_prompt(self, base_prompt: str) -> Any:
        """
        Formatea el system prompt según lo requiera la API del proveedor.
        Anthropic: string directo en campo "system"
        OpenAI: {"role": "system", "content": "..."} dentro de messages
        """
        ...

    @abstractmethod
    def format_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        Convierte la lista de mensajes al formato del proveedor.
        La entrada es el formato interno: [{"role": "user"|"assistant", "content": "..."}]
        """
        ...

    @abstractmethod
    def format_tools(self, tool_definitions: List[Dict]) -> Any:
        """
        Convierte las definiciones de herramientas al formato del proveedor.
        La entrada es nuestro formato interno (compatible con Anthropic).
        """
        ...

    @abstractmethod
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
        Ejecuta la llamada al API del LLM.

        Retorna un dict normalizado:
        {
            "success": True/False,
            "raw_response": <respuesta original del proveedor>,
            "error_type": None | "auth" | "rate_limit" | "timeout" | "server_error",
            "error_message": str | None,
        }
        """
        ...

    @abstractmethod
    def extract_text(self, raw_response: Dict) -> str:
        """
        Extrae el texto de respuesta del LLM de la respuesta cruda.
        Retorna string vacío si no hay texto.
        """
        ...

    @abstractmethod
    def extract_tool_calls(self, raw_response: Dict) -> List[ToolCall]:
        """
        Extrae las llamadas a herramientas de la respuesta cruda.
        Retorna lista vacía si no hay tool calls.
        """
        ...

    @abstractmethod
    def format_tool_result(self, tool_call_id: str, result_content: str) -> Dict:
        """
        Formatea el resultado de una herramienta para enviarlo de vuelta al LLM.
        Cada proveedor tiene su propio formato de tool_result.
        """
        ...

    @abstractmethod
    def is_tool_use_response(self, raw_response: Dict) -> bool:
        """
        Determina si la respuesta del LLM contiene tool_use y espera resultados.
        """
        ...

    @abstractmethod
    def build_assistant_message(self, raw_response: Dict) -> Dict:
        """
        Construye el mensaje del assistant para agregar al historial,
        incluyendo content blocks con text y tool_use.
        """
        ...

    @abstractmethod
    def build_tool_results_messages(self, tool_results: List[Dict]) -> List[Dict]:
        """
        Construye los mensajes de resultados de herramientas para agregar al historial.

        Cada proveedor tiene su propio formato:
          - Anthropic: UN mensaje user con content = [tool_result1, tool_result2, ...]
          - OpenAI: N mensajes separados, cada uno con role="tool"
        
        Retorna lista de dicts listos para extender messages.
        """
        ...