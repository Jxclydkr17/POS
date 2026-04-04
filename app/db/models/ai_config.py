# app/db/models/ai_config.py
"""
Modelo de configuración de IA para el POS.
Tabla separada de Settings para:
  - Encriptación especial de API keys
  - Auditoría independiente
  - No inflar el modelo Settings
"""
from sqlalchemy import Column, Integer, String, Boolean, Float, Text, DateTime
from app.db.database import Base
from app.utils.dt import utcnow


class AIConfig(Base):
    __tablename__ = "ai_config"

    id = Column(Integer, primary_key=True, default=1)

    # Proveedor activo: "anthropic" | "openai" | "google" | "none"
    provider = Column(String(50), nullable=False, default="none")

    # API key encriptada con Fernet (NUNCA en texto plano)
    api_key_encrypted = Column(Text, nullable=True)

    # Modelo seleccionado: "claude-sonnet-4-20250514" | "gpt-4o" | etc.
    model = Column(String(100), nullable=True)

    # Habilitado: permite deshabilitar sin borrar la key
    is_enabled = Column(Boolean, nullable=False, default=False)

    # Parámetros del LLM
    max_tokens = Column(Integer, nullable=False, default=1024)
    temperature = Column(Float, nullable=False, default=0.3)

    # Prompt adicional del usuario (se concatena al system prompt)
    custom_prompt = Column(Text, nullable=True)

    # Auditoría
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)