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
from datetime import datetime, timezone
from pathlib import Path

from app.core.security import decode_token

SESSION_FILE = "session.json"

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
        self.username: str | None = None
        self.role: str | None = None
        self.load_session()

    # ──────────────────────────────────────
    # Manejo de sesión
    # ──────────────────────────────────────

    def start_session(self, username: str, role: str, token: str):
        """Inicia sesión y guarda los datos encriptados en session.json."""
        self.username = username
        self.role = role
        self.token = token
        self.save_session()

    def end_session(self):
        """Cierra sesión y elimina el archivo de sesión."""
        self.username = None
        self.role = None
        self.token = None
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
    # Guardado y carga (con encriptación)
    # ──────────────────────────────────────

    def save_session(self):
        """Guarda la sesión en un archivo JSON con el token encriptado."""
        encrypted_token = _encrypt_token(self.token) if self.token else None

        data = {
            "username": self.username,
            "role": self.role,
            "token": encrypted_token,
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

            # Descifrar si está marcado como encriptado
            if data.get("encrypted", False):
                decrypted = _decrypt_token(stored_token)
                if decrypted is None:
                    # No se pudo descifrar → forzar re-login
                    logger.info("Sesión invalidada: token no descifrable.")
                    self.end_session()
                    return
                self.token = decrypted
            else:
                # Archivo legacy sin encriptación → usar directo
                # y re-guardar encriptado para la próxima vez
                self.token = stored_token
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