# app/ai/providers/__init__.py
"""
Capa de abstracción de proveedores LLM.
Permite usar diferentes APIs (Anthropic, OpenAI, Google) con una interfaz unificada.
"""

from app.ai.providers.base import BaseLLMProvider, ToolCall
from app.ai.providers.provider_registry import get_active_provider, is_any_provider_available

__all__ = [
    "BaseLLMProvider",
    "ToolCall",
    "get_active_provider",
    "is_any_provider_available",
]