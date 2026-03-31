# ui/services/settings_service.py
"""
Servicio HTTP para la vista de configuración.
Fase 6: backup, restore, system-info, export/import config.
"""

import requests
import logging
import os
from ui.session_manager import session
from ui.api import BASE_URL

logger = logging.getLogger(__name__)

API_URL_SETTINGS = f"{BASE_URL}/settings"
API_URL_CABYS = f"{BASE_URL}/settings/update-cabys"
API_URL_SUPPLIERS = f"{BASE_URL}/suppliers"
API_URL_ISSUER = f"{BASE_URL}/settings/issuer-profile"
API_URL_UPLOAD_LOGO = f"{BASE_URL}/settings/upload-logo"
API_URL_ENV_STATUS = f"{BASE_URL}/settings/env-status"
API_URL_BACKUP = f"{BASE_URL}/settings/backup"
API_URL_RESTORE = f"{BASE_URL}/settings/restore"
API_URL_SYSTEM_INFO = f"{BASE_URL}/settings/system-info"
API_URL_EXPORT_CONFIG = f"{BASE_URL}/settings/export-config"
API_URL_IMPORT_CONFIG = f"{BASE_URL}/settings/import-config"
API_URL_AUDIT_LOG = f"{BASE_URL}/settings/audit-log"


def _headers():
    if not session.token:
        raise ValueError("No hay sesión activa. Token no encontrado.")
    return {"Authorization": f"Bearer {session.token}"}


# ─────────────────────────────────────────────────────────
# Settings generales
# ─────────────────────────────────────────────────────────

def fetch_settings() -> dict:
    r = requests.get(API_URL_SETTINGS, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})


def save_settings(payload: dict) -> dict:
    headers = _headers()
    headers["Content-Type"] = "application/json"
    r = requests.put(API_URL_SETTINGS, headers=headers, json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def update_cabys() -> dict:
    r = requests.post(API_URL_CABYS, headers=_headers(), timeout=300)
    r.raise_for_status()
    return r.json()


def fetch_suppliers() -> list:
    r = requests.get(API_URL_SUPPLIERS, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("items", [])


# ─────────────────────────────────────────────────────────
# Issuer Profile
# ─────────────────────────────────────────────────────────

def fetch_issuer_profile() -> dict:
    r = requests.get(API_URL_ISSUER, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})


def save_issuer_profile(payload: dict) -> dict:
    headers = _headers()
    headers["Content-Type"] = "application/json"
    r = requests.put(API_URL_ISSUER, headers=headers, json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


# ─────────────────────────────────────────────────────────
# Logo
# ─────────────────────────────────────────────────────────

def upload_logo(filepath: str) -> dict:
    filename = os.path.basename(filepath)
    ext = os.path.splitext(filename)[1].lower()
    content_types = {".png": "image/png", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg", ".webp": "image/webp"}
    ct = content_types.get(ext, "image/png")

    with open(filepath, "rb") as f:
        files = {"file": (filename, f, ct)}
        r = requests.post(API_URL_UPLOAD_LOGO, headers=_headers(), files=files, timeout=30)
    r.raise_for_status()
    return r.json()


# ─────────────────────────────────────────────────────────
# Env status
# ─────────────────────────────────────────────────────────

def fetch_env_status() -> dict:
    r = requests.get(API_URL_ENV_STATUS, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})


# ─────────────────────────────────────────────────────────
# 6.1: Backup y restauración
# ─────────────────────────────────────────────────────────

def create_backup(save_to: str) -> str:
    """Descarga el backup .sql y lo guarda en save_to. Retorna el path."""
    r = requests.post(API_URL_BACKUP, headers=_headers(), timeout=180, stream=True)
    r.raise_for_status()
    with open(save_to, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return save_to


def restore_backup(filepath: str) -> dict:
    """Sube un archivo .sql para restaurar la DB."""
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        files = {"file": (filename, f, "application/sql")}
        r = requests.post(API_URL_RESTORE, headers=_headers(), files=files, timeout=600)
    r.raise_for_status()
    return r.json()


# ─────────────────────────────────────────────────────────
# 6.5: System info
# ─────────────────────────────────────────────────────────

def fetch_system_info() -> dict:
    r = requests.get(API_URL_SYSTEM_INFO, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})


# ─────────────────────────────────────────────────────────
# 6.6: Export / Import config
# ─────────────────────────────────────────────────────────

def export_config(save_to: str) -> str:
    """Descarga config JSON y lo guarda en save_to."""
    r = requests.get(API_URL_EXPORT_CONFIG, headers=_headers(), timeout=15)
    r.raise_for_status()
    with open(save_to, "w", encoding="utf-8") as f:
        import json
        json.dump(r.json(), f, indent=2, ensure_ascii=False)
    return save_to


def import_config(filepath: str) -> dict:
    """Sube un archivo JSON de configuración."""
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        files = {"file": (filename, f, "application/json")}
        r = requests.post(API_URL_IMPORT_CONFIG, headers=_headers(), files=files, timeout=30)
    r.raise_for_status()
    return r.json()


# ─────────────────────────────────────────────────────────
# 6.4: Audit log
# ─────────────────────────────────────────────────────────

def fetch_audit_log(limit: int = 50) -> list:
    r = requests.get(API_URL_AUDIT_LOG, headers=_headers(), params={"limit": limit}, timeout=10)
    r.raise_for_status()
    return r.json().get("data", [])