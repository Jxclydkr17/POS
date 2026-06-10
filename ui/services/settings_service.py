# ui/services/settings_service.py
"""
Servicio HTTP para la vista de configuración.
Fase 6: backup, restore, system-info, export/import config.

FASE 6 — Fix 6.X: Auto-refresh ante 401.
  `from ui.api import http as requests`. El wrapper es drop-in:
  acepta `files=`, `stream=True`, `params=`, etc. tal cual los pasa
  al `requests` real. La única diferencia es el reintento transparente
  cuando un 401 puede resolverse con /users/refresh.

  Nota sobre uploads y stream:
    - Files (upload_logo, restore_backup, import_config) — el wrapper
      pasa `files=` tal cual; el body se cierra y se reenvía si hay
      retry. Como los uploads se hacen dentro de `with open(...)` y el
      retry solo dispara al primer 401 (antes de tocar el body de
      respuesta), el caso normal funciona sin tocar nada.
    - Stream (create_backup) — el primer 401 lo cerramos antes del
      retry (resp.close()), así que el iter_content corre solo sobre
      el response del retry exitoso.
"""

import logging
import os
from ui.session_manager import session
from ui.api import BASE_URL, http as requests

logger = logging.getLogger(__name__)

API_URL_SETTINGS = f"{BASE_URL}/settings"
API_URL_CABYS = f"{BASE_URL}/settings/update-cabys"
API_URL_SUPPLIERS = f"{BASE_URL}/suppliers"
API_URL_ISSUER = f"{BASE_URL}/settings/issuer-profile"
API_URL_UPLOAD_LOGO = f"{BASE_URL}/settings/upload-logo"
API_URL_UPLOAD_CERT = f"{BASE_URL}/settings/hacienda-cert"
API_URL_HACIENDA_CONFIG = f"{BASE_URL}/settings/hacienda-config"
API_URL_ENV_STATUS = f"{BASE_URL}/settings/env-status"
API_URL_BACKUP = f"{BASE_URL}/settings/backup"
API_URL_RESTORE = f"{BASE_URL}/settings/restore"
API_URL_SYSTEM_INFO = f"{BASE_URL}/settings/system-info"
API_URL_EXPORT_CONFIG = f"{BASE_URL}/settings/export-config"
API_URL_IMPORT_CONFIG = f"{BASE_URL}/settings/import-config"
API_URL_AUDIT_LOG = f"{BASE_URL}/settings/audit-log"
# Fix 2.5 (cerrado): prueba de impresión ESC/POS desde la UI.
API_URL_PRINTER_TEST = f"{BASE_URL}/settings/printer-test"
# Autodetección: lista impresoras del sistema + dispositivos USB.
API_URL_PRINTER_DISCOVERY = f"{BASE_URL}/settings/printer-discovery"


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
# Certificado Hacienda (.p12)
# ─────────────────────────────────────────────────────────

def upload_hacienda_cert(filepath: str, password: str = "") -> dict:
    """
    Sube el archivo .p12 de Hacienda al backend junto con su contraseña.
    El backend lo guarda en DATA_DIR/certs/firma.p12 y persiste el path
    y la contraseña encriptados en la DB.
    """
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        files = {"file": (filename, f, "application/x-pkcs12")}
        # El backend espera 'cert_password' como campo Form del multipart.
        # Siempre lo enviamos (aunque sea vacío) para que el endpoint lo
        # reciba como Form y no como query param.
        data = {"cert_password": password or ""}
        r = requests.post(
            API_URL_UPLOAD_CERT,
            headers=_headers(),
            files=files,
            data=data,
            timeout=30,
        )
    r.raise_for_status()
    return r.json()


# ─────────────────────────────────────────────────────────
# Hacienda config (credenciales + ambiente)
# ─────────────────────────────────────────────────────────

def fetch_hacienda_config() -> dict:
    """Obtiene la configuración actual de Hacienda (valores enmascarados)."""
    r = requests.get(API_URL_HACIENDA_CONFIG, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})


def save_hacienda_config(payload: dict) -> dict:
    """
    Actualiza las credenciales de Hacienda.
    El payload puede incluir: hacienda_env, hacienda_api,
    hacienda_user, hacienda_password (todos opcionales excepto env).
    """
    headers = _headers()
    headers["Content-Type"] = "application/json"
    r = requests.put(API_URL_HACIENDA_CONFIG, headers=headers, json=payload, timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})


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


# ─────────────────────────────────────────────────────────
# Fix 2.5 (cerrado): Prueba de impresión ESC/POS
# ─────────────────────────────────────────────────────────

def test_printer() -> dict:
    """
    Pide al backend imprimir una página de prueba ESC/POS con la
    configuración actual (printer_type / IP / USB / perfil / ancho).
    Retorna el dict de la respuesta del backend.
    """
    # Timeout amplio: una térmica USB puede tardar varios segundos en
    # responder si está dormida o si el SO inicializa el driver USB.
    r = requests.post(API_URL_PRINTER_TEST, headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def discover_printers() -> dict:
    """
    Pide al backend la detección de impresoras (modo "system" + USB).

    Retorna el dict `data` con:
        {
          "platform": str | None,
          "backends": {"win32print": bool, "pyusb": bool},
          "system": [ {name, port, driver, is_default}, ... ],
          "usb":    [ {vendor_id, product_id, description, ...}, ... ],
          "notes":  [ str, ... ],
        }

    La detección corre en la máquina donde está el backend (la misma del
    usuario en este POS de escritorio). Timeout moderado: enumerar el
    spooler y escanear USB es rápido, pero damos margen.
    """
    r = requests.get(API_URL_PRINTER_DISCOVERY, headers=_headers(), timeout=20)
    r.raise_for_status()
    return r.json().get("data", {}) or {}


# ─────────────────────────────────────────────────────────
# FASE 5 AI: Configuración del asistente IA
# ─────────────────────────────────────────────────────────

API_URL_AI_CONFIG = f"{BASE_URL}/settings/ai-config"
API_URL_AI_PROVIDERS = f"{BASE_URL}/settings/ai-providers"
API_URL_AI_TEST = f"{BASE_URL}/settings/ai-config/test"


def fetch_ai_config() -> dict:
    """Obtiene la config actual de IA (sin API key completa)."""
    r = requests.get(API_URL_AI_CONFIG, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})


def save_ai_config(payload: dict) -> dict:
    """Actualiza la config de IA."""
    headers = _headers()
    headers["Content-Type"] = "application/json"
    r = requests.put(API_URL_AI_CONFIG, headers=headers, json=payload, timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})


def test_ai_connection(payload: dict) -> dict:
    """Prueba la conexión con un proveedor y API key."""
    headers = _headers()
    headers["Content-Type"] = "application/json"
    r = requests.post(API_URL_AI_TEST, headers=headers, json=payload, timeout=20)
    r.raise_for_status()
    return r.json().get("data", {})


def fetch_ai_providers() -> list:
    """Lista los proveedores de IA disponibles con sus modelos."""
    r = requests.get(API_URL_AI_PROVIDERS, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("data", [])