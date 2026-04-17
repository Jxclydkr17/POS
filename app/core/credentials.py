# app/core/credentials.py
"""
Lectura centralizada de credenciales sensibles.
Prioridad: secure_config (DB) → .env (fallback).

FASE 5 — Fix 5.3: Cacheo en memoria tras el primer read.
Cada llamada a get_credential() creaba un SessionLocal().
En el startup se llaman varias seguidas (hacienda_user, hacienda_password, etc.),
abriendo y cerrando ~6 conexiones innecesarias.
Ahora se cachean en un dict y solo se lee de BD una vez por key.

Uso:
    from app.core.credentials import get_credential, clear_credential_cache
    user = get_credential("hacienda_user")
    clear_credential_cache()  # forzar re-lectura (ej: tras cambio de config)
"""
import logging
from typing import Optional
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)

# Cache en memoria: {key: value}
# None como valor significa "ya se buscó y no se encontró en DB"
_CACHE_SENTINEL = object()
_cache: dict[str, Optional[str]] = {}


def get_credential(key: str) -> Optional[str]:
    """
    Lee una credencial sensible (con cache en memoria).
    1. Si ya está en cache, retorna inmediatamente.
    2. Si no, intenta leer de secure_config (DB, encriptado).
    3. Si no hay, cae al .env vía settings.
    """
    # 1. Cache hit
    if key in _cache:
        return _cache[key]

    # 2. Intentar DB
    db_value = None
    try:
        db = SessionLocal()
        try:
            from app.services.secure_config_service import get_secure
            db_value = get_secure(db, key)
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"No se pudo leer '{key}' de secure_config: {e}")

    if db_value:
        _cache[key] = db_value
        return db_value

    # 3. Fallback .env
    from app.core.config import settings
    env_value = getattr(settings, key, None) or None
    _cache[key] = env_value
    return env_value


def clear_credential_cache():
    """
    Limpia el cache de credenciales.
    Útil tras cambiar credenciales en la UI de configuración.
    """
    _cache.clear()
    logger.debug("Cache de credenciales limpiado")


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