# app/core/crypto.py
"""
Utilidades de encriptación para datos sensibles (API keys, etc.).
Usa Fernet (AES-128-CBC) derivando la clave del SECRET_KEY de la app.

NUNCA almacenar API keys en texto plano en la BD.

── FASE 2 — Fix 2.4 ──
Además de la verificación en startup (check_encrypted_keys_on_startup),
se almacena un "fingerprint" del SECRET_KEY en disco. Si la clave cambia
(por regeneración automática, edición manual del .env, etc.), se detecta
al arrancar ANTES de que las operaciones de descifrado fallen, y se alerta
al administrador con un mensaje claro.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  Derivación de clave
# ═══════════════════════════════════════════════════════════════

def _derive_fernet_key(secret_key: str) -> bytes:
    """
    Deriva una clave Fernet válida (32 bytes base64) a partir del SECRET_KEY.
    Usa SHA-256 para obtener exactamente 32 bytes, luego los codifica en base64
    como requiere Fernet.
    """
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
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


# ═══════════════════════════════════════════════════════════════
#  Encrypt / Decrypt
# ═══════════════════════════════════════════════════════════════

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

    prefix = api_key[:3]
    suffix = api_key[-4:]
    return f"{prefix}...{suffix}"


# ═══════════════════════════════════════════════════════════════
#  Fingerprint del SECRET_KEY  (Fix 2.4)
#
#  Guarda un hash corto (SHA-256[:16]) del SECRET_KEY en un archivo
#  dentro de DATA_DIR. Al arrancar, compara el fingerprint actual con
#  el guardado. Si difieren, alerta inmediatamente.
# ═══════════════════════════════════════════════════════════════

def _fingerprint_path() -> Path:
    from app.core.config import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / ".secret_key_fingerprint"


def _compute_fingerprint(secret_key: str) -> str:
    """Fingerprint corto del SECRET_KEY (no reversible)."""
    return hashlib.sha256(
        f"vp-fingerprint:{secret_key}".encode("utf-8")
    ).hexdigest()[:16]


def save_key_fingerprint() -> None:
    """Guarda el fingerprint del SECRET_KEY actual en disco."""
    from app.core.config import settings
    if not settings.secret_key:
        return
    fp = _compute_fingerprint(settings.secret_key)
    try:
        _fingerprint_path().write_text(
            json.dumps({"fingerprint": fp}), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"No se pudo guardar fingerprint de SECRET_KEY: {e}")


def check_key_fingerprint() -> dict:
    """
    Compara el fingerprint guardado con el SECRET_KEY actual.

    Retorna:
      {"status": "ok"}                  – la clave no cambió
      {"status": "first_run"}           – no hay fingerprint previo (se crea)
      {"status": "changed", "warning":} – la clave cambió, datos en riesgo
    """
    from app.core.config import settings
    if not settings.secret_key:
        return {"status": "error", "warning": "SECRET_KEY no configurado"}

    current_fp = _compute_fingerprint(settings.secret_key)
    path = _fingerprint_path()

    if not path.exists():
        # Primera ejecución: guardar y continuar
        save_key_fingerprint()
        return {"status": "first_run"}

    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored_fp = stored.get("fingerprint", "")
    except Exception:
        # Archivo corrupto: recrear
        save_key_fingerprint()
        return {"status": "first_run"}

    if current_fp == stored_fp:
        return {"status": "ok"}

    # ¡Cambió!
    warning = (
        "⚠️  SECRET_KEY CAMBIÓ desde la última ejecución. "
        "Todas las API keys de IA encriptadas con la clave anterior "
        "son IRRECUPERABLES. Deberá reconfigurarlas desde Ajustes > IA. "
        "Si el cambio fue intencional, este aviso se puede ignorar."
    )
    logger.error(warning)

    # Actualizar fingerprint para no repetir el aviso en cada reinicio
    save_key_fingerprint()

    return {"status": "changed", "warning": warning}


# ═══════════════════════════════════════════════════════════════
#  Verificaciones de salud (startup)
# ═══════════════════════════════════════════════════════════════

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
    También verifica el fingerprint del SECRET_KEY.
    Retorna la cantidad de claves irrecuperables.

    Uso: llamar en lifespan/startup para alertar al administrador.
    """
    # 1. Verificar fingerprint primero (detección rápida de cambio de clave)
    fp_result = check_key_fingerprint()
    if fp_result["status"] == "changed":
        logger.error(fp_result["warning"])

    # 2. Verificar claves individuales
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