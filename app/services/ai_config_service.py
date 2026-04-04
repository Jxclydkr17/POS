# app/services/ai_config_service.py
"""
Servicio de configuración de IA.
Maneja CRUD de ai_config con encriptación de API keys.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models.ai_config import AIConfig
from app.core.crypto import encrypt_value, decrypt_value, mask_api_key
from app.schemas.ai_config import AIConfigOut, AIConfigUpdate

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────

def get_ai_config(db: Session) -> AIConfig:
    """Obtiene la config de IA (fila id=1). La crea si no existe."""
    config = db.query(AIConfig).filter(AIConfig.id == 1).first()
    if not config:
        config = AIConfig(id=1, provider="none", is_enabled=False)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def get_ai_config_out(db: Session) -> AIConfigOut:
    """Retorna la config como schema Pydantic (sin API key completa)."""
    config = get_ai_config(db)

    # Desencriptar para obtener el hint
    api_key_hint = ""
    has_api_key = False
    if config.api_key_encrypted:
        decrypted = decrypt_value(config.api_key_encrypted)
        if decrypted:
            api_key_hint = mask_api_key(decrypted)
            has_api_key = True

    return AIConfigOut(
        provider=config.provider or "none",
        api_key_hint=api_key_hint,
        has_api_key=has_api_key,
        model=config.model,
        is_enabled=config.is_enabled,
        max_tokens=config.max_tokens or 1024,
        temperature=config.temperature if config.temperature is not None else 0.3,
        custom_prompt=config.custom_prompt,
    )


def update_ai_config(db: Session, data: AIConfigUpdate) -> AIConfigOut:
    """Actualiza la config de IA. Encripta la API key si se envía."""
    config = get_ai_config(db)
    update_data = data.model_dump(exclude_unset=True)

    # Manejar API key por separado (encriptar)
    if "api_key" in update_data:
        raw_key = update_data.pop("api_key")
        if raw_key:
            # Encriptar y guardar
            config.api_key_encrypted = encrypt_value(raw_key.strip())
        else:
            # Key vacía = borrar
            config.api_key_encrypted = None

    # Validar proveedor
    if "provider" in update_data:
        valid_providers = {"anthropic", "openai", "google", "none"}
        if update_data["provider"] not in valid_providers:
            raise ValueError(
                f"Proveedor inválido: {update_data['provider']}. "
                f"Opciones: {', '.join(sorted(valid_providers))}"
            )

    # Aplicar los demás campos
    for key, value in update_data.items():
        if hasattr(config, key):
            setattr(config, key, value)

    db.commit()
    db.refresh(config)

    return get_ai_config_out(db)


def get_decrypted_api_key(db: Session) -> Optional[str]:
    """
    Obtiene la API key desencriptada.
    Solo para uso interno (provider_registry). NUNCA exponer en API.
    """
    config = get_ai_config(db)
    if not config.api_key_encrypted:
        return None
    return decrypt_value(config.api_key_encrypted)


def clear_api_key(db: Session) -> None:
    """Borra la API key guardada."""
    config = get_ai_config(db)
    config.api_key_encrypted = None
    db.commit()