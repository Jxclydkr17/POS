# app/schemas/ai_config.py
"""
Schemas Pydantic para la configuración de IA.
"""
from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────────────
# Respuesta: lo que retorna GET /settings/ai-config
# ─────────────────────────────────────────────────────

class AIConfigOut(BaseModel):
    """Config actual de IA — NUNCA expone la API key completa."""
    provider: str = "none"
    api_key_hint: str = ""          # Solo "sk-...xxxx" (últimos 4 chars)
    has_api_key: bool = False       # True si hay key guardada
    model: Optional[str] = None
    is_enabled: bool = False
    max_tokens: int = 1024
    temperature: float = 0.3
    custom_prompt: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────
# Update: lo que recibe PUT /settings/ai-config
# ─────────────────────────────────────────────────────

class AIConfigUpdate(BaseModel):
    """Actualizar config de IA. Todos los campos son opcionales."""
    provider: Optional[str] = None
    api_key: Optional[str] = None       # Key en texto plano → se encripta al guardar
    model: Optional[str] = None
    is_enabled: Optional[bool] = None
    max_tokens: Optional[int] = Field(None, ge=100, le=4096)
    temperature: Optional[float] = Field(None, ge=0.0, le=1.0)
    custom_prompt: Optional[str] = None


# ─────────────────────────────────────────────────────
# Test: request/response para POST /settings/ai-config/test
# ─────────────────────────────────────────────────────

class AIConfigTestRequest(BaseModel):
    """Probar conexión con un proveedor y API key."""
    provider: str                        # "anthropic" | "openai" | "google"
    api_key: str                         # Key en texto plano para probar
    model: Optional[str] = None          # Modelo específico (usa default si None)


class AIConfigTestResponse(BaseModel):
    """Resultado del test de conexión."""
    success: bool
    message: str
    provider: str
    model_used: str = ""


# ─────────────────────────────────────────────────────
# Proveedores: respuesta de GET /settings/ai-providers
# ─────────────────────────────────────────────────────

class AIProviderInfo(BaseModel):
    """Info de un proveedor disponible."""
    name: str
    display_name: str
    models: List[str] = []
    default_model: str = ""
    has_key: bool = False
    is_active: bool = False