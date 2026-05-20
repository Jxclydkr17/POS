# app/ai/providers/provider_registry.py
"""
Registry de proveedores LLM.
Gestiona qué proveedor está activo y cachea instancias.

FASE 2: Lee la configuración desde la BD (tabla ai_config).
Fallback a variables de entorno si no hay config en BD.
"""
from __future__ import annotations

import os
import logging
from typing import Dict, Optional, Tuple

from app.ai.providers.base import BaseLLMProvider
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.openai_provider import OpenAIProvider
from app.ai.providers.google_provider import GoogleProvider

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# Registro de proveedores disponibles
# ─────────────────────────────────────────────────────

# Mapa de proveedores conocidos: name → clase
_PROVIDER_CLASSES: Dict[str, type] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "google": GoogleProvider,
}

# Cache de instancias (singleton por proveedor)
_provider_instances: Dict[str, BaseLLMProvider] = {}


def _get_provider_instance(provider_name: str) -> BaseLLMProvider:
    """Obtiene (o crea y cachea) una instancia del proveedor."""
    if provider_name not in _provider_instances:
        cls = _PROVIDER_CLASSES.get(provider_name)
        if not cls:
            raise ValueError(f"Proveedor LLM desconocido: {provider_name}")
        _provider_instances[provider_name] = cls()
    return _provider_instances[provider_name]


# ─────────────────────────────────────────────────────
# Resolución de API key desde env vars (fallback)
# ─────────────────────────────────────────────────────

def _resolve_api_key_from_env(provider_name: str) -> Optional[str]:
    """
    Busca la API key del proveedor.
    Prioridad:
      1) Settings de pydantic (consolida .env + env vars)
      2) Variables de entorno directas (fallback legacy)
    """
    # ── FASE 5 — Fix 5.1: Leer desde settings (soporta los 3 providers) ──
    try:
        from app.core.config import settings as _settings
        settings_attr_map = {
            "anthropic": "anthropic_api_key",
            "openai": "openai_api_key",
            "google": "google_api_key",
        }
        attr = settings_attr_map.get(provider_name)
        if attr:
            val = getattr(_settings, attr, None)
            if val and val.strip():
                return val.strip()
    except Exception as e:
        logger.debug("Could not read API key from app settings for '%s': %s", provider_name, e)

    env_var_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
    }

    env_var = env_var_map.get(provider_name)
    if not env_var:
        return None

    # Variable de entorno directa (fallback)
    key = os.environ.get(env_var, "").strip()
    if key:
        return key

    return None


def _maybe_migrate_deprecated_model(
    provider_name: str,
    current_model: str,
) -> Optional[str]:
    """
    FASE 1.2 — Fix 1.2: Auto-migrar modelos deprecados a la versión vigente.

    Si el modelo guardado en `ai_config.model` es uno que el proveedor
    marca como deprecado, se reemplaza por su `default_model`. La
    persistencia en BD se hace en `_resolve_from_db` con `safe_session`
    para no afectar la transacción del request en curso.

    Args:
        provider_name: nombre del proveedor (ej. "anthropic").
        current_model: modelo guardado actualmente en BD.

    Returns:
        Nuevo modelo si hay que migrar, None si no hace falta.
    """
    if not current_model:
        return None

    cls = _PROVIDER_CLASSES.get(provider_name)
    if not cls:
        return None

    deprecated = getattr(cls, "deprecated_models", frozenset())
    if current_model not in deprecated:
        return None

    new_model = getattr(cls, "default_model", "") or ""
    if not new_model:
        return None

    logger.warning(
        "Modelo %s '%s' está deprecado. Auto-migrando a '%s' en ai_config.",
        provider_name, current_model, new_model,
    )
    return new_model


def _persist_model_migration(new_model: str) -> None:
    """
    Persiste el nuevo modelo en `ai_config` usando una sesión separada
    (safe_session) para evitar contaminar la transacción del request.

    Cualquier fallo se loguea pero no propaga, porque la migración es
    un nice-to-have (el `_safe_model` del provider sigue siendo la
    red de seguridad real en runtime).
    """
    try:
        from app.db.database import safe_session
        from app.db.models.ai_config import AIConfig
        with safe_session() as s:
            cfg = s.query(AIConfig).filter(AIConfig.id == 1).first()
            if cfg and cfg.model != new_model:
                cfg.model = new_model
                s.commit()
                logger.info("ai_config.model actualizado a '%s'", new_model)
    except Exception as e:
        logger.warning("No se pudo persistir migración de modelo: %s", e)


# ─────────────────────────────────────────────────────
# Resolución desde BD (FASE 2)
# ─────────────────────────────────────────────────────

def _resolve_from_db(db) -> Optional[Tuple[str, str, dict]]:
    """
    Lee la config de IA desde la BD.
    Retorna (provider_name, api_key, extras) o None si no hay config válida.

    extras contiene: max_tokens, temperature, custom_prompt, model
    """
    if db is None:
        return None

    try:
        from app.services.ai_config_service import get_ai_config, get_decrypted_api_key

        config = get_ai_config(db)

        # Si el proveedor es "none" o está deshabilitado, no hay config en BD
        if not config or config.provider == "none" or not config.is_enabled:
            return None

        # Si no hay key guardada, no sirve
        api_key = get_decrypted_api_key(db)
        if not api_key:
            return None

        # Verificar que el proveedor es válido
        if config.provider not in _PROVIDER_CLASSES:
            logger.warning(f"Proveedor en BD no reconocido: {config.provider}")
            return None

        # ── FASE 1.2 — Fix 1.2: Auto-migrar modelo deprecado ──
        # Si la fila `ai_config` tiene un modelo deprecado guardado
        # (ej. instalación existente con claude-sonnet-4-20250514),
        # lo reemplazamos por el default vigente y lo persistimos.
        effective_model = config.model or ""
        new_model = _maybe_migrate_deprecated_model(config.provider, effective_model)
        if new_model:
            effective_model = new_model
            _persist_model_migration(new_model)

        extras = {
            "max_tokens": config.max_tokens or 1024,
            "temperature": config.temperature if config.temperature is not None else 0.3,
            "custom_prompt": config.custom_prompt or "",
            "model": effective_model,
        }

        return config.provider, api_key, extras

    except Exception as e:
        logger.debug("No se pudo leer ai_config de BD (normal en primera ejecución): %s", e)
        return None


# ─────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────

def get_active_provider(db=None) -> Tuple[BaseLLMProvider, str, dict]:
    """
    Retorna el proveedor activo, su API key y parámetros extra.

    Prioridad de resolución:
      1. Configuración en BD (tabla ai_config) — si está habilitada y tiene key
      2. Variables de entorno (ANTHROPIC_API_KEY, etc.) — fallback

    Args:
        db: Session de SQLAlchemy.

    Returns:
        Tuple de (instancia del proveedor, api_key, extras_dict).
        extras_dict contiene: max_tokens, temperature, custom_prompt, model

    Raises:
        RuntimeError: Si no hay proveedor configurado o no hay API key.
    """
    extras = {
        "max_tokens": 1024,
        "temperature": 0.3,
        "custom_prompt": "",
        "model": "",
    }

    # ── 1) Intentar BD ──
    db_result = _resolve_from_db(db)
    if db_result:
        provider_name, api_key, extras = db_result
        provider = _get_provider_instance(provider_name)
        return provider, api_key, extras

    # ── 2) Fallback a env vars (Anthropic por defecto) ──
    provider_name = "anthropic"
    api_key = _resolve_api_key_from_env(provider_name)

    if not api_key:
        raise RuntimeError(
            "No hay API key de IA configurada. "
            "Configurá tu API key en Ajustes > Asistente IA."
        )

    provider = _get_provider_instance(provider_name)
    return provider, api_key, extras


def is_any_provider_available(db=None) -> bool:
    """
    Verifica si hay al menos un proveedor LLM configurado con API key.

    Prioridad:
      1. BD (ai_config habilitada con key)
      2. Env vars
    """
    # Intentar BD
    if db is not None:
        db_result = _resolve_from_db(db)
        if db_result:
            return True

    # Fallback a env vars
    try:
        for provider_name in _PROVIDER_CLASSES:
            if _resolve_api_key_from_env(provider_name):
                return True
    except Exception as e:
        logger.debug("Error checking env var API keys: %s", e)

    return False


def get_available_providers(db=None) -> list[dict]:
    """
    Lista todos los proveedores disponibles con su estado.
    Útil para la UI de configuración.
    """
    # Leer config activa de BD si hay
    active_provider = None
    if db is not None:
        db_result = _resolve_from_db(db)
        if db_result:
            active_provider = db_result[0]

    providers = []
    for name, cls in _PROVIDER_CLASSES.items():
        instance = _get_provider_instance(name)
        has_key_env = bool(_resolve_api_key_from_env(name))

        # Determinar si está activo
        is_active = False
        has_key = has_key_env
        if active_provider:
            is_active = name == active_provider
            if is_active:
                has_key = True
        elif has_key_env:
            # Fallback: activo si tiene key en env
            is_active = name == "anthropic" and has_key_env

        providers.append({
            "name": instance.name,
            "display_name": instance.display_name,
            "has_key": has_key,
            "models": instance.supported_models,
            "default_model": instance.default_model,
            "is_active": is_active,
        })
    return providers