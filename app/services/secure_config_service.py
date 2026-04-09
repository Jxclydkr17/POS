# app/services/secure_config_service.py
"""
Servicio para leer/escribir configuraciones sensibles encriptadas.
Patrón: DB primero, .env como fallback.
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from app.db.models.secure_config import SecureConfig
from app.core.crypto import encrypt_value, decrypt_value

logger = logging.getLogger(__name__)

# Mapeo de keys de secure_config → atributos de settings (.env)
_ENV_FALLBACK = {
    "hacienda_user": "hacienda_user",
    "hacienda_password": "hacienda_password",
    "hacienda_cert_path": "hacienda_cert_path",
    "hacienda_cert_pass": "hacienda_cert_pass",
    "hacienda_env": "hacienda_env",
    "hacienda_api": "hacienda_api",
    "email_user": "email_user",
    "email_pass": "email_pass",
}


def set_secure(db: Session, key: str, value: str) -> None:
    """Guarda un valor encriptado en la DB."""
    encrypted = encrypt_value(value)
    row = db.query(SecureConfig).filter(SecureConfig.key == key).first()
    if row:
        row.value_encrypted = encrypted
    else:
        row = SecureConfig(key=key, value_encrypted=encrypted)
        db.add(row)
    db.commit()


def get_secure(db: Session, key: str) -> Optional[str]:
    """
    Lee un valor sensible. Prioridad:
      1. secure_config en DB (encriptado)
      2. .env como fallback
    """
    row = db.query(SecureConfig).filter(SecureConfig.key == key).first()
    if row and row.value_encrypted:
        decrypted = decrypt_value(row.value_encrypted)
        if decrypted is not None:
            return decrypted

    # Fallback al .env
    env_attr = _ENV_FALLBACK.get(key)
    if env_attr:
        from app.core.config import settings
        val = getattr(settings, env_attr, None)
        if val:
            return val

    return None


def delete_secure(db: Session, key: str) -> None:
    """Elimina un valor de la DB."""
    db.query(SecureConfig).filter(SecureConfig.key == key).delete()
    db.commit()


def get_all_keys(db: Session) -> list[str]:
    """Lista todas las keys configuradas."""
    rows = db.query(SecureConfig.key).all()
    return [r[0] for r in rows]