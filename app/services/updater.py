"""
app/services/updater.py — Mecanismo de actualización de Violette POS

Verifica si hay una versión más reciente disponible en un servidor
de actualizaciones y permite descargar el paquete.

El flujo es conservador:
  1. Verifica versión disponible vs versión actual
  2. Si hay update, descarga el .zip a una carpeta temporal
  3. El usuario decide cuándo aplicar (reiniciar manualmente)
  4. NO aplica automáticamente para evitar interrumpir operaciones

CONFIGURACIÓN:
  - UPDATE_URL en .env (default: endpoint de versión)
  - El servidor de updates debe retornar JSON con:
    {"version": "1.1.0", "url": "https://...", "changelog": "...", "required": false}

USO:
    from app.services.updater import check_update, download_update

    info = check_update()      # {"available": True, "latest": "1.1.0", ...}
    result = download_update()  # Descarga el paquete si hay update
"""

from __future__ import annotations

import os
import sys
import logging
import hashlib
from pathlib import Path
from typing import Optional

import requests

from app.core.config import APP_VERSION

logger = logging.getLogger(__name__)

# ── FASE 5 — Fix 5.4: Versión centralizada desde config.py ──
CURRENT_VERSION = APP_VERSION

# ── URL del servidor de actualizaciones ──
# El usuario puede override esto en .env con UPDATE_URL=...
DEFAULT_UPDATE_URL = os.environ.get(
    "UPDATE_URL",
    "https://updates.violettepos.com/api/version"
)

# Directorio para descargas
if getattr(sys, 'frozen', False):
    _APP_DIR = Path(sys.executable).parent
else:
    _APP_DIR = Path(__file__).resolve().parents[2]

UPDATE_DIR = _APP_DIR / "updates"
UPDATE_DIR.mkdir(parents=True, exist_ok=True)

# Timeout para requests
_TIMEOUT = 10


def _parse_version(v: str) -> tuple[int, ...]:
    """Convierte "1.2.3" en (1, 2, 3) para comparación."""
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def check_update(url: str = DEFAULT_UPDATE_URL) -> dict:
    """
    Verifica si hay una versión más reciente disponible.

    Returns:
        dict con:
            - available: bool
            - current_version: str
            - latest_version: str (si available)
            - changelog: str (si available)
            - download_url: str (si available)
            - required: bool (si es update obligatorio)
            - error: str (si hubo error)
    """
    result = {
        "available": False,
        "current_version": CURRENT_VERSION,
        "latest_version": None,
        "changelog": None,
        "download_url": None,
        "required": False,
        "sha256": None,
        "error": None,
    }

    try:
        resp = requests.get(url, timeout=_TIMEOUT)

        if resp.status_code != 200:
            result["error"] = f"Servidor de updates retornó HTTP {resp.status_code}"
            return result

        data = resp.json()
        latest = data.get("version", "")
        result["latest_version"] = latest

        if not latest:
            result["error"] = "Respuesta del servidor sin campo 'version'"
            return result

        # Comparar versiones
        current_tuple = _parse_version(CURRENT_VERSION)
        latest_tuple = _parse_version(latest)

        if latest_tuple > current_tuple:
            result["available"] = True
            result["changelog"] = data.get("changelog", "")
            result["download_url"] = data.get("url", "")
            result["required"] = data.get("required", False)
            # ── FASE 3 — Fix 3.1: Capturar hash para verificación post-descarga ──
            result["sha256"] = data.get("sha256", "")

            logger.info(
                f"Actualización disponible: {CURRENT_VERSION} → {latest}"
            )
        else:
            logger.debug(f"Sin actualizaciones. Versión actual: {CURRENT_VERSION}")

    except requests.ConnectionError:
        result["error"] = "Sin conexión al servidor de actualizaciones"
    except requests.Timeout:
        result["error"] = "Timeout conectando al servidor de actualizaciones"
    except Exception as e:
        result["error"] = f"Error verificando actualizaciones: {e}"
        logger.warning(f"Error en check_update: {e}")

    return result


def _verify_sha256(filepath: Path, expected_hash: str) -> bool:
    """
    Verifica el SHA-256 de un archivo contra el hash esperado.
    FASE 3 — Fix 3.1: hashlib se importa pero nunca se usaba.
    """
    if not expected_hash:
        return False
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    actual = sha256.hexdigest()
    if actual.lower() != expected_hash.lower():
        logger.warning(
            f"SHA-256 mismatch: esperado={expected_hash}, "
            f"actual={actual}, archivo={filepath}"
        )
        return False
    logger.info(f"SHA-256 verificado correctamente para {filepath.name}")
    return True


def download_update(url: str = DEFAULT_UPDATE_URL) -> dict:
    """
    Descarga el paquete de actualización si hay uno disponible.

    Returns:
        dict con:
            - downloaded: bool
            - path: str (ruta del archivo descargado)
            - version: str
            - message: str
    """
    result = {
        "downloaded": False,
        "path": None,
        "version": None,
        "message": "",
    }

    # Primero verificar si hay update
    check = check_update(url)

    if check.get("error"):
        result["message"] = check["error"]
        return result

    if not check["available"]:
        result["message"] = f"Ya tiene la última versión ({CURRENT_VERSION})"
        return result

    download_url = check.get("download_url")
    if not download_url:
        result["message"] = "No hay URL de descarga disponible"
        return result

    version = check["latest_version"]
    expected_hash = check.get("sha256", "")
    filename = f"ViolettePOS_update_{version}.zip"
    filepath = UPDATE_DIR / filename

    # Si ya está descargado, verificar integridad antes de aceptar
    if filepath.exists():
        if expected_hash and not _verify_sha256(filepath, expected_hash):
            logger.warning(f"Hash inválido en archivo existente {filepath}. Re-descargando.")
            filepath.unlink(missing_ok=True)
        else:
            result["downloaded"] = True
            result["path"] = str(filepath)
            result["version"] = version
            result["message"] = f"Actualización {version} ya descargada en {filepath}"
            return result

    # ── FASE 3 — Fix 3.1: Exigir SHA-256 del servidor ──
    if not expected_hash:
        result["message"] = (
            "El servidor de actualizaciones no proporcionó un hash SHA-256. "
            "Descarga rechazada por seguridad."
        )
        logger.error("Descarga rechazada: servidor no envió sha256 en el manifiesto.")
        return result

    # Descargar
    try:
        logger.info(f"Descargando actualización {version} desde {download_url}...")

        resp = requests.get(download_url, timeout=60, stream=True)
        resp.raise_for_status()

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        size_mb = filepath.stat().st_size / (1024 * 1024)
        logger.info(f"Actualización descargada: {filepath} ({size_mb:.1f} MB)")

        # ── FASE 3 — Fix 3.1: Verificar SHA-256 post-descarga ──
        if not _verify_sha256(filepath, expected_hash):
            filepath.unlink(missing_ok=True)
            result["message"] = (
                "SEGURIDAD: El hash SHA-256 del archivo descargado no coincide "
                "con el del servidor. El archivo fue eliminado. "
                "Posible manipulación en tránsito."
            )
            logger.error(
                f"ALERTA SEGURIDAD: Hash mismatch en descarga de {download_url}. "
                f"Esperado: {expected_hash}"
            )
            return result

        result["downloaded"] = True
        result["path"] = str(filepath)
        result["version"] = version
        result["message"] = (
            f"Actualización {version} descargada ({size_mb:.1f} MB). "
            f"Cierre la aplicación y ejecute el instalador desde {filepath}"
        )

    except requests.ConnectionError:
        result["message"] = "Sin conexión para descargar la actualización"
    except requests.Timeout:
        result["message"] = "Timeout descargando la actualización"
    except Exception as e:
        result["message"] = f"Error descargando: {e}"
        logger.error(f"Error en download_update: {e}")
        filepath.unlink(missing_ok=True)

    return result


def get_update_info() -> dict:
    """Información rápida para la UI (sin conectar al servidor)."""
    pending_updates = list(UPDATE_DIR.glob("ViolettePOS_update_*.zip"))

    return {
        "current_version": CURRENT_VERSION,
        "pending_updates": [
            {"filename": p.name, "size_mb": round(p.stat().st_size / 1024 / 1024, 1)}
            for p in pending_updates
        ],
        "update_dir": str(UPDATE_DIR),
    }