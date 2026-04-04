# app/core/crypto.py
"""
Utilidades de encriptación para datos sensibles (API keys, etc.).
Usa Fernet (AES-128-CBC) derivando la clave del SECRET_KEY de la app.

NUNCA almacenar API keys en texto plano en la BD.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _derive_fernet_key(secret_key: str) -> bytes:
    """
    Deriva una clave Fernet válida (32 bytes base64) a partir del SECRET_KEY.
    Usa SHA-256 para obtener exactamente 32 bytes, luego los codifica en base64
    como requiere Fernet.
    """
    # SHA-256 produce 32 bytes exactos
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
    # Fernet necesita 32 bytes codificados en base64url
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    """Obtiene una instancia de Fernet usando el SECRET_KEY de la app."""
    from app.core.config import settings
    if not settings.secret_key:
        raise RuntimeError(
            "SECRET_KEY no está configurado. "
            "No se puede encriptar/desencriptar datos sensibles."
        )
    key = _derive_fernet_key(settings.secret_key)
    return Fernet(key)


def encrypt_value(plain_text: str) -> str:
    """
    Encripta un valor sensible (ej: API key).
    Retorna el texto cifrado como string base64.
    """
    if not plain_text:
        return ""
    f = _get_fernet()
    encrypted = f.encrypt(plain_text.encode("utf-8"))
    return encrypted.decode("utf-8")


def decrypt_value(encrypted_text: str) -> Optional[str]:
    """
    Desencripta un valor previamente encriptado.
    Retorna None si la desencriptación falla (key cambió, dato corrupto, etc.).
    """
    if not encrypted_text:
        return None
    try:
        f = _get_fernet()
        decrypted = f.decrypt(encrypted_text.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        logger.error(
            "No se pudo desencriptar el valor. "
            "¿Cambió el SECRET_KEY desde que se guardó?"
        )
        return None
    except Exception as e:
        logger.error(f"Error al desencriptar: {e}")
        return None


def mask_api_key(api_key: str) -> str:
    """
    Enmascara una API key mostrando solo los últimos 4 caracteres.
    Ej: "sk-ant-abc123xyz789" → "sk-...9789"
    """
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****" + api_key[-2:] if len(api_key) > 2 else "****"

    # Mostrar prefijo (primeras 3 letras) + ... + últimos 4
    prefix = api_key[:3]
    suffix = api_key[-4:]
    return f"{prefix}...{suffix}"