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
        # ── FASE 2 — Fix 2.4: Mensaje claro sobre la causa más probable ──
        logger.error(
            "No se pudo desencriptar el valor. "
            "Causa probable: el SECRET_KEY cambió desde que se guardó este dato. "
            "Las API keys encriptadas con la clave anterior son irrecuperables. "
            "Deberá volver a configurarlas manualmente."
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


# ── FASE 2 — Fix 2.4: Verificación de salud de encriptación ──────────
def verify_encryption_health() -> dict:
    """
    Verifica que la encriptación funcione correctamente con el SECRET_KEY actual.
    Retorna un dict con el estado:
      {"ok": True}  o  {"ok": False, "error": "..."}

    Uso recomendado: llamar en startup para detectar cambios de clave temprano.
    """
    test_value = "encryption_health_check"
    try:
        encrypted = encrypt_value(test_value)
        decrypted = decrypt_value(encrypted)
        if decrypted != test_value:
            return {"ok": False, "error": "Round-trip de encriptación falló (valor no coincide)"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_encrypted_keys_on_startup(db) -> int:
    """
    Verifica que las API keys guardadas en ai_configs puedan desencriptarse.
    Retorna la cantidad de claves irrecuperables.

    Uso: llamar en lifespan/startup para alertar al administrador.
    """
    try:
        from app.db.models.ai_config import AIConfig
        configs = db.query(AIConfig).filter(AIConfig.api_key_encrypted.isnot(None)).all()
        broken = 0
        for cfg in configs:
            if cfg.api_key_encrypted and not decrypt_value(cfg.api_key_encrypted):
                broken += 1
                logger.error(
                    f"API key del proveedor '{cfg.provider}' no se puede desencriptar. "
                    f"Reconfigure la API key desde Ajustes > IA."
                )
        if broken:
            logger.error(
                f"{broken} API key(s) de IA son irrecuperables. "
                f"Esto ocurre cuando el SECRET_KEY cambió. "
                f"Reconfigure las claves manualmente."
            )
        return broken
    except Exception as e:
        logger.warning(f"No se pudo verificar API keys encriptadas: {e}")
        return 0