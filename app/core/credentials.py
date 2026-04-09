# app/core/credentials.py
"""
Lectura centralizada de credenciales sensibles.
Prioridad: secure_config (DB) → .env (fallback).

Uso:
    from app.core.credentials import get_credential
    user = get_credential("hacienda_user")
"""
import logging
from typing import Optional
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)


def get_credential(key: str) -> Optional[str]:
    """
    Lee una credencial sensible.
    1. Intenta leer de secure_config (DB, encriptado).
    2. Si no hay, cae al .env vía settings.
    """
    # 1. Intentar DB
    try:
        db = SessionLocal()
        try:
            from app.services.secure_config_service import get_secure
            val = get_secure(db, key)
            if val:
                return val
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"No se pudo leer '{key}' de secure_config: {e}")

    # 2. Fallback .env
    from app.core.config import settings
    return getattr(settings, key, None) or None


# ── Shortcuts para los más usados ──

def hacienda_user() -> Optional[str]:
    return get_credential("hacienda_user")

def hacienda_password() -> Optional[str]:
    return get_credential("hacienda_password")

def hacienda_env() -> str:
    return get_credential("hacienda_env") or "sandbox"

def hacienda_api() -> Optional[str]:
    return get_credential("hacienda_api")

def hacienda_cert_path() -> Optional[str]:
    return get_credential("hacienda_cert_path")

def hacienda_cert_pass() -> Optional[str]:
    return get_credential("hacienda_cert_pass")

def email_user() -> Optional[str]:
    return get_credential("email_user")

def email_pass() -> Optional[str]:
    return get_credential("email_pass")