"""
app/services/updater.py — Mecanismo de actualización de Violette POS

Consulta la API pública de GitHub Releases para saber si hay una versión
más reciente, descarga el instalador (.exe) y —cuando el usuario lo
decide— lanza el instalador en modo silencioso para que reemplace la app.

El flujo es conservador (NO interrumpe ventas):
  1. check_update()      → ¿hay una versión más nueva publicada?
  2. download_update()   → descarga el .exe a la carpeta `updates/` y
                           verifica su integridad (SHA-256 si está disponible)
  3. spawn_installer()   → lanza el .exe en modo /VERYSILENT, desacoplado
                           del proceso actual. El llamador (la UI) cierra la
                           app justo después para que Windows libere el .exe.
  4. Al reabrir la app ya actualizada, launcher._auto_migrate() aplica las
     migraciones de Alembic pendientes (con backup) automáticamente.

──────────────────────────────────────────────────────────────────────────
CONTRATO CON GITHUB RELEASES
──────────────────────────────────────────────────────────────────────────
El repositorio debe ser PÚBLICO (así la API responde sin token; embeber un
PAT en el .exe sería un riesgo: cualquiera lo extraería del binario).

owner/repo se configuran en el .env (GITHUB_OWNER / GITHUB_REPO) y la URL la
arma app.core.config.get_github_releases_api_url(). Endpoint consultado:

    GET https://api.github.com/repos/<owner>/<repo>/releases/latest

De la respuesta JSON se usan:
  - tag_name   → versión (ej. "v1.1.0"; se le quita la "v" para comparar)
  - body       → changelog mostrado al usuario. Además puede contener:
                   · el SHA-256 del instalador (línea "SHA256: <hash>")
                   · un marcador "[required]" para updates obligatorios
  - assets[]   → se busca el asset .exe (el instalador Inno) y, opcionalmente,
                 un asset "<instalador>.exe.sha256" con el hash.

Nota: `/releases/latest` EXCLUYE drafts y prereleases. Si el repo aún no
tiene ningún release, GitHub responde 404 → lo tratamos como "no hay
actualización" (no es un error que deba alarmar al usuario).

──────────────────────────────────────────────────────────────────────────
MODELO DE SEGURIDAD
──────────────────────────────────────────────────────────────────────────
  1. HTTPS obligatorio: la API de GitHub y la descarga de assets son siempre
     https. download_update() rechaza cualquier URL de descarga que no
     empiece con "https://".

  2. SHA-256 (verificar-si-está, advertir-si-falta):
     - Si el release publica el hash (en el body o como asset .sha256), tras
       descargar se recalcula localmente y se compara. Mismatch → se borra el
       archivo y se aborta (posible descarga corrupta o manipulada).
     - Si el release NO publica hash, la descarga continúa pero se DEJA UN
       AVISO claro en el resultado y en los logs.

     ¿Por qué no se rechaza cuando falta el hash (a diferencia de la versión
     anterior, que apuntaba a un servidor propio)? Con GitHub, tanto el
     manifiesto (la respuesta de la API) como el .exe y el .sha256 viajan por
     TLS desde la MISMA infraestructura de GitHub. El SHA-256 aquí protege
     sobre todo contra descargas truncadas/corruptas, no añade garantía de
     autoría por encima del propio TLS de GitHub. Además, el instalador Inno
     valida internamente (CRC) sus bloques comprimidos y aborta si el .exe
     llegó corrupto, lo que actúa como red de seguridad adicional. Bloquear
     el update por un .sha256 olvidado sería un footgun (dejaría a toda la
     flota sin poder actualizar). Por eso: integridad cuando esté, sin frenar
     el update cuando no esté. Recomendado: publicar siempre el hash (el
     workflow de release lo genera por vos).

  3. Firma asimétrica (Ed25519) — NO implementada, deliberadamente.
     Para una ferretería, con repo público + HTTPS de GitHub + verificación
     de integridad, el modelo es razonable. Una firma offline solo aportaría
     frente a un compromiso de la cuenta de GitHub, escenario fuera del
     alcance realista aquí. Si algún día se requiere, el punto de enganche
     natural es _verify_sha256()/download_update() (verificar una firma del
     asset contra una pubkey embebida en el .exe).
"""

from __future__ import annotations

import os
import sys
import re
import logging
import hashlib
import subprocess
from pathlib import Path

import requests

from app.core.config import APP_VERSION, get_github_releases_api_url

logger = logging.getLogger(__name__)

# ── Versión instalada (fuente única: archivo VERSION vía config) ──
CURRENT_VERSION = APP_VERSION

# ── Directorio base (escribible) y carpeta de descargas ──
if getattr(sys, "frozen", False):
    _APP_DIR = Path(sys.executable).parent
else:
    _APP_DIR = Path(__file__).resolve().parents[2]

UPDATE_DIR = _APP_DIR / "updates"
UPDATE_DIR.mkdir(parents=True, exist_ok=True)

# Timeouts (segundos)
_TIMEOUT_API = 10        # consultar la API (rápido, no debe demorar el login)
_TIMEOUT_DOWNLOAD = 120  # descargar el instalador (.exe puede pesar decenas de MB)
_TIMEOUT_SIDECAR = 10    # bajar el pequeño archivo .sha256

# Headers requeridos por la API de GitHub (sin User-Agent, GitHub responde 403)
_GITHUB_HEADERS = {
    "User-Agent": "ViolettePOS-Updater",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Patrón para extraer un SHA-256 (64 hex) del cuerpo del release.
# Acepta "SHA256: <hash>", "sha-256 = <hash>", etc.
_SHA256_IN_BODY = re.compile(r"(?i)sha-?256[^0-9a-f]{0,8}([0-9a-fA-F]{64})")
# SHA-256 suelto (fallback dentro de un asset .sha256, formato sha256sum o crudo)
_SHA256_TOKEN = re.compile(r"\b([0-9a-fA-F]{64})\b")
# Marcador de update obligatorio en el cuerpo del release.
_REQUIRED_MARKER = re.compile(r"(?i)\[required\]|required\s*[:=]\s*true")


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _parse_version(v: str) -> "object":
    """Convierte "v1.2.3" / "1.2.3" en un objeto comparable (packaging).

    Quita un prefijo 'v'/'V' defensivamente y delega en packaging.version.
    Ante un valor inválido devuelve la versión 0 (para que nunca se
    considere "más nueva" que la instalada).
    """
    from packaging.version import parse as _parse, InvalidVersion

    s = (v or "").strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    try:
        return _parse(s)
    except (InvalidVersion, TypeError):
        return _parse("0")


def _pick_installer_asset(assets: list[dict]) -> dict | None:
    """Elige el asset del instalador (.exe) entre los del release.

    Prioriza nombres que contengan 'setup' o 'installer'. Ignora el .sha256.
    Devuelve el dict del asset (con 'name' y 'browser_download_url') o None.
    """
    exe_assets = [
        a for a in assets
        if str(a.get("name", "")).lower().endswith(".exe")
    ]
    if not exe_assets:
        return None
    # Preferir el que parezca explícitamente el instalador.
    for a in exe_assets:
        name = str(a.get("name", "")).lower()
        if "setup" in name or "installer" in name:
            return a
    return exe_assets[0]


def _find_sha256_asset(assets: list[dict], installer_name: str) -> dict | None:
    """Busca el asset con el hash del instalador.

    Acepta "<instalador>.sha256" o "<instalador>.exe.sha256" o cualquier
    asset que termine en .sha256 si solo hay uno.
    """
    sidecars = [
        a for a in assets
        if str(a.get("name", "")).lower().endswith(".sha256")
    ]
    if not sidecars:
        return None
    # Match exacto por nombre del instalador.
    base = installer_name.lower()
    for a in sidecars:
        n = str(a.get("name", "")).lower()
        if n in (base + ".sha256", base.rsplit(".exe", 1)[0] + ".sha256"):
            return a
    # Si hay un único .sha256, asumir que es el del instalador.
    return sidecars[0] if len(sidecars) == 1 else None


def _extract_sha256(body: str, assets: list[dict], installer_name: str) -> str | None:
    """Obtiene el SHA-256 esperado del instalador.

    Estrategia (en orden, para minimizar requests):
      1. Parsear el cuerpo del release buscando "SHA256: <hash>".
      2. Si no está, buscar y descargar un asset "<instalador>.sha256".
    Devuelve el hash en minúsculas, o None si no se publicó ninguno.
    """
    # 1) En el cuerpo del release.
    if body:
        m = _SHA256_IN_BODY.search(body)
        if m:
            return m.group(1).lower()

    # 2) Asset sidecar .sha256.
    sidecar = _find_sha256_asset(assets, installer_name)
    if sidecar:
        url = sidecar.get("browser_download_url", "")
        if url.startswith("https://"):
            try:
                resp = requests.get(url, headers=_GITHUB_HEADERS, timeout=_TIMEOUT_SIDECAR)
                if resp.status_code == 200:
                    m = _SHA256_TOKEN.search(resp.text or "")
                    if m:
                        return m.group(1).lower()
            except requests.RequestException as e:
                logger.warning("No se pudo leer el asset .sha256: %s", e)

    return None


def _verify_sha256(filepath: Path, expected_hash: str) -> bool:
    """Recalcula el SHA-256 del archivo y lo compara con el esperado."""
    if not expected_hash:
        return False
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    actual = sha256.hexdigest()
    if actual.lower() != expected_hash.lower():
        logger.warning(
            "SHA-256 mismatch: esperado=%s actual=%s archivo=%s",
            expected_hash, actual, filepath,
        )
        return False
    logger.info("SHA-256 verificado correctamente para %s", filepath.name)
    return True


# ══════════════════════════════════════════════════════════════════════
# 1) Verificar si hay actualización
# ══════════════════════════════════════════════════════════════════════

def check_update(api_url: str | None = None) -> dict:
    """Verifica si hay una versión más reciente publicada en GitHub Releases.

    Args:
        api_url: override opcional de la URL de la API. Si es None, se toma
                 de la configuración (GITHUB_OWNER / GITHUB_REPO en el .env).

    Returns (dict):
        - configured       bool  → False si owner/repo no están en el .env
        - available        bool  → True si hay una versión más nueva
        - current_version  str
        - latest_version   str | None
        - changelog        str | None
        - download_url     str | None  (browser_download_url del .exe)
        - asset_name       str | None
        - sha256           str | None  (hash esperado, si el release lo publica)
        - required         bool        (update obligatorio, si está marcado)
        - error            str | None
    """
    result = {
        "configured": True,
        "available": False,
        "current_version": CURRENT_VERSION,
        "latest_version": None,
        "changelog": None,
        "download_url": None,
        "asset_name": None,
        "sha256": None,
        "required": False,
        "error": None,
    }

    url = api_url or get_github_releases_api_url()
    if not url:
        # owner/repo no configurados → updater inactivo, sin error.
        result["configured"] = False
        logger.debug("Updater inactivo: GITHUB_OWNER/GITHUB_REPO no configurados.")
        return result

    try:
        resp = requests.get(url, headers=_GITHUB_HEADERS, timeout=_TIMEOUT_API)

        # 404 = el repo todavía no tiene releases. NO es un error para el usuario.
        if resp.status_code == 404:
            logger.debug("GitHub: el repo no tiene releases publicados (404).")
            return result

        if resp.status_code == 403:
            # Límite de tasa de la API (60/h por IP sin token). Benigno.
            result["error"] = "Límite temporal de la API de GitHub. Intente más tarde."
            logger.info("GitHub API 403 (rate limit) al verificar actualizaciones.")
            return result

        if resp.status_code != 200:
            result["error"] = f"GitHub respondió HTTP {resp.status_code}"
            return result

        data = resp.json()
        tag = data.get("tag_name", "") or ""
        latest = tag.lstrip("vV").strip()
        result["latest_version"] = latest or None

        if not latest:
            result["error"] = "El release de GitHub no tiene 'tag_name'."
            return result

        # Comparar versiones (packaging).
        if _parse_version(latest) <= _parse_version(CURRENT_VERSION):
            logger.debug("Sin actualizaciones. Instalada=%s, última=%s",
                         CURRENT_VERSION, latest)
            return result

        # Hay una versión más nueva → localizar el instalador.
        assets = data.get("assets", []) or []
        installer = _pick_installer_asset(assets)
        if installer is None:
            result["error"] = (
                f"El release {tag} no incluye un instalador .exe como asset."
            )
            logger.warning(result["error"])
            return result

        body = data.get("body", "") or ""
        asset_name = installer.get("name", "")

        result["available"] = True
        result["latest_version"] = latest
        result["changelog"] = body
        result["download_url"] = installer.get("browser_download_url", "")
        result["asset_name"] = asset_name
        result["sha256"] = _extract_sha256(body, assets, asset_name)
        result["required"] = bool(_REQUIRED_MARKER.search(body))

        logger.info("Actualización disponible: %s → %s", CURRENT_VERSION, latest)

    except requests.ConnectionError:
        result["error"] = "Sin conexión a internet para verificar actualizaciones."
    except requests.Timeout:
        result["error"] = "Tiempo de espera agotado consultando GitHub."
    except ValueError:
        # JSON inválido
        result["error"] = "Respuesta inválida de la API de GitHub."
    except Exception as e:  # defensivo: nunca debe tumbar el arranque/login
        result["error"] = f"Error verificando actualizaciones: {e}"
        logger.warning("Error en check_update: %s", e)

    return result


# ══════════════════════════════════════════════════════════════════════
# 2) Descargar el instalador
# ══════════════════════════════════════════════════════════════════════

def download_update(api_url: str | None = None) -> dict:
    """Descarga el instalador (.exe) del último release, si hay update.

    Returns (dict):
        - downloaded   bool
        - path         str | None   (ruta local del .exe descargado)
        - version      str | None
        - verified     bool         (True si se verificó el SHA-256)
        - message      str
    """
    result = {
        "downloaded": False,
        "path": None,
        "version": None,
        "verified": False,
        "message": "",
    }

    check = check_update(api_url)

    if not check.get("configured", True):
        result["message"] = "Actualizaciones no configuradas (falta GITHUB_OWNER/REPO)."
        return result

    if check.get("error"):
        result["message"] = check["error"]
        return result

    if not check["available"]:
        result["message"] = f"Ya tiene la última versión ({CURRENT_VERSION})."
        return result

    download_url = check.get("download_url") or ""
    version = check["latest_version"]
    expected_hash = check.get("sha256")
    asset_name = check.get("asset_name") or f"ViolettePOS_Setup_{version}.exe"

    # ── Seguridad: exigir HTTPS ──
    if not download_url.startswith("https://"):
        result["message"] = (
            "URL de descarga insegura (no HTTPS). Descarga rechazada por seguridad."
        )
        logger.error("Descarga rechazada: URL no HTTPS: %s", download_url)
        return result

    filepath = UPDATE_DIR / _safe_filename(asset_name)

    # Si ya está descargado y su hash coincide, reusar.
    if filepath.exists():
        if expected_hash:
            if _verify_sha256(filepath, expected_hash):
                result.update(downloaded=True, path=str(filepath), version=version,
                              verified=True,
                              message=f"Actualización {version} ya descargada.")
                return result
            logger.warning("Hash inválido en archivo existente. Re-descargando.")
            filepath.unlink(missing_ok=True)
        else:
            # Sin hash para validar el existente → re-descargar para estar seguros.
            filepath.unlink(missing_ok=True)

    # ── Descargar ──
    try:
        logger.info("Descargando actualización %s desde %s ...", version, download_url)
        resp = requests.get(
            download_url, headers=_GITHUB_HEADERS,
            timeout=_TIMEOUT_DOWNLOAD, stream=True,
        )
        resp.raise_for_status()

        tmp = filepath.with_suffix(filepath.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        tmp.replace(filepath)  # rename atómico al nombre final

        size_mb = filepath.stat().st_size / (1024 * 1024)
        logger.info("Descargado: %s (%.1f MB)", filepath, size_mb)

        # ── Verificación de integridad ──
        if expected_hash:
            if not _verify_sha256(filepath, expected_hash):
                filepath.unlink(missing_ok=True)
                result["message"] = (
                    "SEGURIDAD: el SHA-256 del archivo descargado no coincide "
                    "con el publicado. El archivo fue eliminado."
                )
                logger.error("ALERTA: hash mismatch en descarga de %s", download_url)
                return result
            result["verified"] = True
            result["message"] = (
                f"Actualización {version} descargada y verificada ({size_mb:.1f} MB)."
            )
        else:
            # Sin hash publicado: continuar pero advertir claramente.
            result["verified"] = False
            result["message"] = (
                f"Actualización {version} descargada ({size_mb:.1f} MB). "
                "AVISO: el release no publicó SHA-256, no se pudo verificar la "
                "integridad (el instalador validará su propio contenido al correr)."
            )
            logger.warning(
                "Descarga sin SHA-256 publicado para %s. Integridad no verificada.",
                asset_name,
            )

        result["downloaded"] = True
        result["path"] = str(filepath)
        result["version"] = version

    except requests.ConnectionError:
        result["message"] = "Sin conexión para descargar la actualización."
    except requests.Timeout:
        result["message"] = "Tiempo de espera agotado descargando la actualización."
    except Exception as e:
        result["message"] = f"Error descargando: {e}"
        logger.error("Error en download_update: %s", e)
        # limpiar parciales
        for p in (filepath, filepath.with_suffix(filepath.suffix + ".part")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    return result


# ══════════════════════════════════════════════════════════════════════
# 3) Lanzar el instalador (el "relevo")
# ══════════════════════════════════════════════════════════════════════

def spawn_installer(installer_path: str | Path, silent: bool = True) -> bool:
    """Lanza el instalador Inno DESACOPLADO del proceso actual.

    El instalador queda corriendo de forma independiente, de modo que cuando
    el llamador cierre Violette POS (sys.exit), Windows libere el .exe y el
    instalador pueda reemplazarlo. NO cierra la app: de eso se encarga el
    llamador (la UI), que primero debe hacer el teardown ordenado de Qt.

    Args:
        installer_path: ruta al .exe descargado.
        silent: si True, usa /VERYSILENT /SUPPRESSMSGBOXES /NORESTART.

    Returns:
        True si el instalador se lanzó correctamente, False si no.
    """
    path = Path(installer_path)
    if not path.exists():
        logger.error("spawn_installer: no existe el instalador en %s", path)
        return False

    args: list[str] = [str(path)]
    if silent:
        # /VERYSILENT      → sin UI del instalador
        # /SUPPRESSMSGBOXES→ acepta los diálogos por defecto
        # /NORESTART       → no reiniciar Windows
        args += ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
        # Log del instalador para diagnóstico de soporte.
        try:
            log_dir = _APP_DIR / "data" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            args.append(f'/LOG={log_dir / "update_install.log"}')
        except OSError:
            pass  # el log es opcional; no abortar por esto

    creationflags = 0
    if sys.platform == "win32":
        # DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP → el instalador NO muere
        # cuando el proceso padre (la app) termine.
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )

    try:
        subprocess.Popen(
            args,
            close_fds=True,
            creationflags=creationflags,
            cwd=str(path.parent),
        )
        logger.info("Instalador lanzado: %s (silent=%s)", path.name, silent)
        return True
    except Exception as e:
        logger.error("No se pudo lanzar el instalador: %s", e)
        return False


def _safe_filename(name: str) -> str:
    """Sanea el nombre de un asset para usarlo como archivo local."""
    name = os.path.basename(name or "")
    name = re.sub(r"[^A-Za-z0-9_.\- ]", "_", name).strip()
    return name or "ViolettePOS_Setup.exe"


# ══════════════════════════════════════════════════════════════════════
# Info rápida para la UI (sin red)
# ══════════════════════════════════════════════════════════════════════

def get_update_info() -> dict:
    """Estado local del updater, sin conectar a internet."""
    pending = list(UPDATE_DIR.glob("*.exe"))
    return {
        "current_version": CURRENT_VERSION,
        "configured": get_github_releases_api_url() is not None,
        "pending_updates": [
            {"filename": p.name, "size_mb": round(p.stat().st_size / 1024 / 1024, 1)}
            for p in pending
        ],
        "update_dir": str(UPDATE_DIR),
    }