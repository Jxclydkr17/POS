# ui/services/users_service.py
"""
Servicio HTTP para gestión de usuarios/cajeros.
Fase 3: CRUD + permisos granulares.
"""

import requests
import logging
from ui.session_manager import session
from ui.api import BASE_URL

logger = logging.getLogger(__name__)

API_URL_USERS = f"{BASE_URL}/users"


def _headers():
    if not session.token:
        raise ValueError("No hay sesión activa. Token no encontrado.")
    return {"Authorization": f"Bearer {session.token}"}


def _json_headers():
    h = _headers()
    h["Content-Type"] = "application/json"
    return h


# ─────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────

def fetch_users() -> list[dict]:
    """Lista todos los usuarios."""
    r = requests.get(f"{API_URL_USERS}/", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def fetch_user(user_id: int) -> dict:
    """Obtiene un usuario por ID."""
    r = requests.get(f"{API_URL_USERS}/{user_id}", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def create_user(payload: dict) -> dict:
    """Crea un nuevo usuario."""
    r = requests.post(
        f"{API_URL_USERS}/register",
        headers=_json_headers(),
        json=payload,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def update_user(user_id: int, payload: dict) -> dict:
    """Actualiza un usuario existente."""
    r = requests.put(
        f"{API_URL_USERS}/{user_id}",
        headers=_json_headers(),
        json=payload,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def delete_user(user_id: int) -> dict:
    """Elimina un usuario."""
    r = requests.delete(
        f"{API_URL_USERS}/{user_id}",
        headers=_headers(),
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


# ─────────────────────────────────────────────────────────
# Permisos
# ─────────────────────────────────────────────────────────

def fetch_available_permissions() -> dict:
    """Retorna permisos disponibles y defaults por rol."""
    r = requests.get(
        f"{API_URL_USERS}/permissions/available",
        headers=_headers(),
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def update_permissions(user_id: int, permissions: list[str]) -> dict:
    """Actualiza los permisos de un usuario."""
    r = requests.put(
        f"{API_URL_USERS}/{user_id}/permissions",
        headers=_json_headers(),
        json={"permissions": permissions},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def reset_permissions(user_id: int) -> dict:
    """Restaura permisos al default del rol."""
    r = requests.post(
        f"{API_URL_USERS}/{user_id}/permissions/reset",
        headers=_headers(),
        timeout=10,
    )
    r.raise_for_status()
    return r.json()