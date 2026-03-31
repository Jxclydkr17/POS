from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from PySide6.QtCore import Qt

import requests

from app.core.security import decode_token


from ui.api import BASE_URL

API_URL = f"{BASE_URL}/users/login"


class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Violette POS - Iniciar sesión")
        self.setFixedSize(350, 300)

        # 🎨 Tema oscuro para el login
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
        """)


        
        self.setup_ui()
        self.token = None


    def setup_ui(self):
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
        layout.addWidget(self.password_input)

        self.login_button = QPushButton("Ingresar")
        self.login_button.clicked.connect(self.handle_login)
        layout.addWidget(self.login_button)

        self.setLayout(layout)

    def handle_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        if not username or not password:
            QMessageBox.warning(self, "Campos vacíos", "Por favor ingrese usuario y contraseña.")
            return

        try:
            response = requests.post(API_URL, data={"username": username, "password": password})
            if response.status_code == 200:
                data = response.json()
                token = data.get("token") or data.get("access") or data.get("access_token")
                self.token = token
                self.accept()  # ☑️ Cierra el diálogo exitosamente
            else:
                QMessageBox.critical(self, "Error", "Credenciales inválidas.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo conectar con el servidor:\n{e}")
