# ui/session_manager.py
"""
FASE 1 — Fix 1.3: Token JWT encriptado en disco.

Problema:
  El token JWT se guardaba en texto plano en session.json. Cualquier
  persona con acceso al disco podía copiar el archivo y autenticarse
  como el usuario sin necesidad de contraseña.

Solución:
  Se encripta el token con Fernet (AES-128-CBC) usando el SECRET_KEY
  de la aplicación antes de guardarlo en disco. Al cargar, se descifra.
  Si el descifrado falla (por cambio de SECRET_KEY), la sesión se invalida
  y el usuario debe iniciar sesión nuevamente.

  Además se restringe los permisos del archivo (solo lectura/escritura
  para el usuario actual en Windows).
"""

import json
import os
import stat
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.core.security import decode_token
from app.core.config import APP_DIR

# ── FASE B — Fix B.1: Session en directorio protegido del usuario ──
# Antes: session.json quedaba junto al .exe, accesible a cualquiera.
# Ahora: %APPDATA%/ViolettePOS/ (Windows) o data/ (fallback).
_OLD_SESSION_FILE = str(APP_DIR / "session.json")


def _get_session_dir() -> Path:
    """Retorna un directorio protegido del usuario para guardar la sesión."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            d = Path(appdata) / "ViolettePOS"
            try:
                d.mkdir(parents=True, exist_ok=True)
                return d
            except OSError:
                pass

    # Fallback (Linux/Mac o si %APPDATA% falla): data/ dentro del proyecto
    fallback = APP_DIR / "data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


SESSION_FILE = str(_get_session_dir() / "session.json")

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Helpers de encriptación (degradación elegante)
# ═══════════════════════════════════════════════════════════════

def _encrypt_token(token: str) -> str:
    """Encripta el token. Si falla, retorna el token original con warning."""
    try:
        from app.core.crypto import encrypt_value
        return encrypt_value(token)
    except Exception as e:
        logger.warning(f"No se pudo encriptar el token de sesión: {e}")
        return token


def _decrypt_token(stored_value: str) -> str | None:
    """
    Descifra el token almacenado.
    Retorna None si el descifrado falla (SECRET_KEY cambió, dato corrupto).
    """
    if not stored_value:
        return None

    # Si el valor parece un JWT sin encriptar (legado), retornarlo directamente
    if stored_value.startswith("eyJ"):
        return stored_value

    try:
        from app.core.crypto import decrypt_value
        result = decrypt_value(stored_value)
        if result is None:
            logger.warning(
                "Token de sesión no se pudo descifrar (SECRET_KEY cambió). "
                "Se requiere iniciar sesión nuevamente."
            )
        return result
    except Exception as e:
        logger.warning(f"Error al descifrar token de sesión: {e}")
        return None


def _secure_file_permissions(filepath: str):
    """
    Restringe permisos del archivo de sesión.
    En Windows: quita el bit de lectura para 'others'.
    En Linux/Mac: chmod 600 (solo owner).
    """
    try:
        if os.name == "nt":
            # Windows: quitar herencia y restringir acceso
            # stat no controla ACLs en Windows, pero al menos removemos
            # el bit de lectura para 'others' y 'group'
            os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR)
        else:
            os.chmod(filepath, 0o600)
    except Exception:
        # No fallar si no se pueden cambiar permisos
        pass


# ═══════════════════════════════════════════════════════════════
# SessionManager
# ═══════════════════════════════════════════════════════════════

class SessionManager:
    """
    Administra la sesión del usuario logueado.
    Guarda y carga automáticamente desde un archivo JSON local,
    con el token encriptado.
    """

    def __init__(self):
        self.token: str | None = None
        # FASE 2 — Fix 2.4: persistir refresh_token para sesión más larga (24h)
        # que pueda sobrevivir al expirado del access_token (2h).
        self.refresh_token: str | None = None
        self.username: str | None = None
        self.role: str | None = None
        # ── FASE 6 — Fix 6.X: Auto-refresh client-side ──
        # Lock para serializar intentos concurrentes de refresh. Si 3 requests
        # reciben 401 al mismo tiempo, solo una pega a /users/refresh y las
        # otras esperan y reutilizan el access_token renovado.
        self._refresh_lock = threading.Lock()
        self.load_session()

    # ──────────────────────────────────────
    # Manejo de sesión
    # ──────────────────────────────────────

    def start_session(self, username: str, role: str, token: str, refresh_token: str | None = None):
        """Inicia sesión y guarda los datos encriptados en session.json.

        FASE 2 — Fix 2.4: refresh_token es opcional para mantener compatibilidad
        con callers que aún no lo provean; cuando se provee se persiste también.
        """
        self.username = username
        self.role = role
        self.token = token
        self.refresh_token = refresh_token
        self.save_session()

    def end_session(self):
        """Cierra sesión y elimina el archivo de sesión."""
        self.username = None
        self.role = None
        self.token = None
        self.refresh_token = None  # FASE 2 — Fix 2.4
        try:
            if os.path.exists(SESSION_FILE):
                os.remove(SESSION_FILE)
        except OSError as e:
            logger.warning(f"No se pudo eliminar {SESSION_FILE}: {e}")

    def is_logged_in(self) -> bool:
        """Verifica si hay una sesión válida (token presente y no expirado)."""
        if not self.token:
            return False

        try:
            payload = decode_token(self.token)
            if not payload:
                self.end_session()
                return False

            exp_timestamp = payload.get("exp")
            if not exp_timestamp:
                self.end_session()
                return False

            exp_time = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
            if exp_time < datetime.now(timezone.utc):
                logger.info("Token expirado. Se requiere iniciar sesión nuevamente.")
                self.end_session()
                return False

            return True

        except Exception:
            logger.warning("Error al validar el token. Cerrando sesión.")
            self.end_session()
            return False

    # ──────────────────────────────────────
    # FASE 6 — Fix 6.X: Auto-refresh client-side
    # ──────────────────────────────────────

    def try_refresh_access_token(self, expired_token: str | None = None) -> bool:
        """
        Intenta renovar el access_token usando el refresh_token persistido.

        Retorna True si al final hay un access_token válido (ya sea porque
        este thread lo renovó, o porque otro thread ya lo hizo mientras
        esperábamos el lock). Retorna False si no hay refresh_token, si
        /users/refresh respondió error, o si la red falló.

        Single-flight:
          Múltiples requests concurrentes pueden recibir 401 con el mismo
          token expirado. Solo el primero en tomar el lock dispara el POST
          a /users/refresh; los demás, al entrar al lock, detectan que
          session.token ya cambió y retornan True sin hacer nada.

        Args:
          expired_token: el access_token que recibió 401. Se usa para
              detectar si otro thread ya renovó mientras esperábamos.
              Si es None, siempre se intenta el refresh (caso "expirado
              detectado proactivamente, no por respuesta 401").
        """
        if not self.refresh_token:
            return False

        with self._refresh_lock:
            # Otro thread ya renovó mientras esperábamos. Nuestro retry con
            # el token actual debería funcionar.
            if expired_token is not None and self.token != expired_token:
                return True

            # Recheck por si end_session() ocurrió mientras esperábamos.
            if not self.refresh_token:
                return False

            try:
                # Import local para evitar ciclo con ui.api → ui.session_manager.
                import requests as _requests  # noqa: WPS433
                from ui.api import BASE_URL    # noqa: WPS433
            except Exception as e:
                logger.warning(f"No se pudo importar dependencias para refresh: {e}")
                return False

            try:
                resp = _requests.post(
                    f"{BASE_URL}/users/refresh",
                    json={"refresh_token": self.refresh_token},
                    timeout=(5, 10),
                )
            except _requests.exceptions.RequestException as e:
                # Sin red: no podemos renovar. El caller verá AUTH_EXPIRED
                # y mostrará el diálogo de re-login.
                logger.info(f"Refresh falló por red ({e.__class__.__name__}); "
                            f"se requerirá re-login.")
                return False
            except Exception as e:
                logger.warning(f"Error inesperado refrescando token: {e}")
                return False

            if resp.status_code != 200:
                # 401: refresh expirado/revocado. 403: usuario desactivado.
                # En cualquier caso, el refresh_token actual ya no sirve →
                # limpiarlo para no reintentar en cada 401 subsecuente.
                logger.info(
                    f"/users/refresh respondió {resp.status_code}; "
                    f"invalidando refresh_token local."
                )
                self.refresh_token = None
                self.save_session()
                return False

            try:
                data = resp.json()
            except Exception as e:
                logger.warning(f"Respuesta de /users/refresh no es JSON válido: {e}")
                return False

            new_access = data.get("access_token")
            if not new_access:
                logger.warning("Respuesta de /users/refresh sin access_token.")
                return False

            # El backend actual no rota el refresh_token, pero si algún día
            # lo hace, lo aceptamos sin cambios adicionales.
            new_refresh = data.get("refresh_token")

            self.token = new_access
            if new_refresh:
                self.refresh_token = new_refresh
            self.save_session()
            logger.info("Access token renovado silenciosamente vía /users/refresh.")
            return True

    # ──────────────────────────────────────
    # Guardado y carga (con encriptación)
    # ──────────────────────────────────────

    def save_session(self):
        """Guarda la sesión en un archivo JSON con el token encriptado."""
        encrypted_token = _encrypt_token(self.token) if self.token else None
        # FASE 2 — Fix 2.4: persistir también el refresh_token (encriptado)
        encrypted_refresh = _encrypt_token(self.refresh_token) if self.refresh_token else None

        data = {
            "username": self.username,
            "role": self.role,
            "token": encrypted_token,
            "refresh_token": encrypted_refresh,  # FASE 2 — Fix 2.4
            # Marcador para saber que está encriptado
            "encrypted": True,
        }

        try:
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
            _secure_file_permissions(SESSION_FILE)
        except OSError as e:
            logger.warning(f"No se pudo guardar sesión en {SESSION_FILE}: {e}")

    def load_session(self):
        """Carga la sesión guardada, descifrando el token."""
        # ── FASE B — Fix B.1: Migrar sesión de ubicación vieja si existe ──
        if not os.path.exists(SESSION_FILE) and os.path.exists(_OLD_SESSION_FILE):
            try:
                import shutil
                os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
                shutil.move(_OLD_SESSION_FILE, SESSION_FILE)
                _secure_file_permissions(SESSION_FILE)
                logger.info(f"Sesión migrada de ubicación vieja a {SESSION_FILE}")
            except OSError as e:
                logger.warning(f"No se pudo migrar sesión vieja: {e}")

        if not os.path.exists(SESSION_FILE):
            return

        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.username = data.get("username")
            self.role = data.get("role")

            stored_token = data.get("token")
            if not stored_token:
                return

            # FASE 2 — Fix 2.4: refresh_token puede no estar (sesión guardada
            # antes del fix 2.4 o login externo que no lo provee).
            stored_refresh = data.get("refresh_token")

            # Descifrar si está marcado como encriptado
            if data.get("encrypted", False):
                decrypted = _decrypt_token(stored_token)
                if decrypted is None:
                    # No se pudo descifrar → forzar re-login
                    logger.info("Sesión invalidada: token no descifrable.")
                    self.end_session()
                    return
                self.token = decrypted
                if stored_refresh:
                    decrypted_refresh = _decrypt_token(stored_refresh)
                    # Si el refresh no se descifra (raro), no anulamos toda
                    # la sesión: el access aún sirve hasta que expire.
                    self.refresh_token = decrypted_refresh
            else:
                # Archivo legacy sin encriptación → usar directo
                # y re-guardar encriptado para la próxima vez
                self.token = stored_token
                if stored_refresh:
                    self.refresh_token = stored_refresh
                self.save_session()  # re-guardar encriptado

        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Archivo de sesión corrupto. Eliminando.")
            self.end_session()
        except Exception as e:
            logger.warning(f"Error cargando sesión: {e}")
            self.end_session()


# ═══════════════════════════════════════════════════════════════
# Instancia global (compartida por toda la app)
# ═══════════════════════════════════════════════════════════════
session = SessionManager()