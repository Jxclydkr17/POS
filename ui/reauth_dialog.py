# ui/reauth_dialog.py
"""
Diálogo de re-autenticación / cambio de usuario.

Usado por main_ui._on_switch_user() para cambiar de cajero sin
cerrar la aplicación. El caller (main_ui) se encarga de llamar
session.start_session() con el token retornado.

FASE 7 — Fix 7.2: Login asíncrono.
  Antes: requests.post() síncrono en el hilo principal de Qt,
  sin timeout. Si el backend tardaba, la ventana se congelaba.
  Ahora: QThread + señales, igual que login_view.py.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, QObject, Signal

import requests

from ui.api import BASE_URL

API_URL = f"{BASE_URL}/users/login"


# ═══════════════════════════════════════════════════════════════
# Worker: ejecuta el POST de login en un hilo separado
# ═══════════════════════════════════════════════════════════════
class _LoginWorker(QObject):
    """Ejecuta el POST de login fuera del hilo principal de Qt."""
    success = Signal(dict)   # respuesta JSON completa
    failed = Signal(str)     # mensaje de error

    def __init__(self, url: str, username: str, password: str):
        super().__init__()
        self._url = url
        self._username = username
        self._password = password

    def run(self):
        try:
            response = requests.post(
                self._url,
                data={"username": self._username, "password": self._password},
                timeout=(5, 15),
            )
            if response.status_code == 200:
                self.success.emit(response.json())
            else:
                self.failed.emit("Credenciales inválidas.")
        except requests.exceptions.ConnectTimeout:
            self.failed.emit(
                "No se pudo conectar al servidor (timeout).\n"
                "Verifique que Violette POS esté iniciado."
            )
        except requests.exceptions.ConnectionError:
            self.failed.emit(
                "No se pudo conectar al servidor.\n"
                "¿Está Violette POS iniciado correctamente?"
            )
        except Exception as e:
            self.failed.emit(f"No se pudo conectar con el servidor:\n{e}")


# ═══════════════════════════════════════════════════════════════
# Diálogo de login
# ═══════════════════════════════════════════════════════════════
class LoginDialog(QDialog):
    """
    Diálogo modal para autenticación.

    Tras login exitoso, self.token contiene el access_token JWT.
    El caller debe verificar `dlg.exec() == QDialog.Accepted` y
    usar `dlg.token` para actualizar la sesión.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Violette POS - Iniciar sesión")
        self.setFixedSize(350, 300)

        # Tema oscuro para el login
        self.setStyleSheet("""
            QDialog {
                background-color: #111827;
                color: #e5e7eb;
            }
            QLabel {
                color: #e5e7eb;
            }
            QLineEdit {
                background-color: #1f2933;
                color: #e5e7eb;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 6px 8px;
            }
            QLineEdit::placeholder {
                color: #9ca3af;
            }
            QPushButton {
                background-color: #4f46e5;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 0;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #6366f1;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #6b7280;
            }
        """)

        self.token = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("🔐 Iniciar sesión")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold; margin-bottom: 15px;")
        layout.addWidget(title)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Usuario")
        layout.addWidget(self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Contraseña")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.returnPressed.connect(self._handle_login)
        layout.addWidget(self.password_input)

        self.login_button = QPushButton("Ingresar")
        self.login_button.clicked.connect(self._handle_login)
        layout.addWidget(self.login_button)

        self.setLayout(layout)

    # ── Estado de carga ──────────────────────────────────────
    def _set_loading(self, loading: bool):
        """Alterna el estado visual de carga."""
        self.login_button.setEnabled(not loading)
        self.login_button.setText("⏳ Verificando..." if loading else "Ingresar")
        self.username_input.setEnabled(not loading)
        self.password_input.setEnabled(not loading)

    # ── Lanzar login asíncrono ───────────────────────────────
    def _handle_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        if not username or not password:
            QMessageBox.warning(self, "Campos vacíos", "Por favor ingrese usuario y contraseña.")
            return

        self._set_loading(True)

        # Crear worker y thread
        worker = _LoginWorker(API_URL, username, password)
        thread = QThread()
        worker.moveToThread(thread)

        # Conectar señales
        thread.started.connect(worker.run)
        worker.success.connect(self._on_login_success)
        worker.success.connect(thread.quit)
        worker.failed.connect(self._on_login_failed)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        thread.start()

        # Mantener referencias para evitar GC prematuro
        self._login_thread = thread
        self._login_worker = worker

    # ── Callbacks (ejecutados en el hilo principal de Qt) ────
    def _on_login_success(self, data: dict):
        self._set_loading(False)
        token = data.get("access_token") or data.get("token") or data.get("access")
        if not token:
            QMessageBox.critical(self, "Error", "Respuesta del servidor sin token.")
            return
        self.token = token
        self.accept()

    def _on_login_failed(self, error_msg: str):
        self._set_loading(False)
        QMessageBox.critical(self, "Error", error_msg)