import json
import os
from datetime import datetime, timezone
from app.core.security import decode_token
import logging

SESSION_FILE = "session.json"

class SessionManager:
    """
    Administra la sesión del usuario logueado.
    Guarda y carga automáticamente desde un archivo JSON local.
    """

    def __init__(self):
        self.token = None
        self.username = None
        self.role = None
        self.load_session()

    # ------------------------------
    # 🧩 Manejo de sesión
    # ------------------------------
    def start_session(self, username, role, token):
        """Inicia sesión y guarda los datos en session.json"""
        self.username = username
        self.role = role
        self.token = token
        self.save_session()

    def end_session(self):
        """Cierra sesión y elimina el archivo de sesión"""
        self.username = None
        self.role = None
        self.token = None
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)

    def is_logged_in(self):
        """Verifica si hay una sesión válida (token presente y no expirado)"""
        if not self.token:
            return False

        try:
            payload = decode_token(self.token)
            exp_timestamp = payload.get("exp")
            if not exp_timestamp:
                return False

            exp_time = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
            if exp_time < datetime.now(timezone.utc):
                logging.warning("⚠️ Token expirado. Se requiere iniciar sesión nuevamente.")
                self.end_session()
                return False

            return True
        except Exception:
            logging.warning("⚠️ Error al validar el token. Cerrando sesión.")
            self.end_session()
            return False

    # ------------------------------
    # 💾 Guardado y carga local
    # ------------------------------
    def save_session(self):
        """Guarda la sesión en un archivo JSON"""
        data = {
            "username": self.username,
            "role": self.role,
            "token": self.token
        }
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def load_session(self):
        """Carga la sesión guardada (si existe)"""
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.username = data.get("username")
                    self.role = data.get("role")
                    self.token = data.get("token")
            except Exception:
                logging.warning("⚠️ No se pudo cargar la sesión guardada. Se eliminará el archivo.")
                self.end_session()


# 🔁 Instancia global (compartida por toda la app)
session = SessionManager()