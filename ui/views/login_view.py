from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt
import requests
import sys
import logging

# 🧩 Importar gestor de sesión global
from ui.session_manager import session
from app.core.security import decode_token  # 👈 Para leer el rol desde el token

from ui.api import BASE_URL

API_URL = f"{BASE_URL}/users/login"


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Violette POS - Inicio de sesión")
        self.setFixedSize(350, 300)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)

        # 🏷️ Título
        title = QLabel("🔐 Iniciar sesión")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold; margin-bottom: 15px;")
        layout.addWidget(title)

        # 👤 Usuario
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Usuario")
        layout.addWidget(self.username_input)

        # 🔑 Contraseña
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Contraseña")
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)

        # 🚀 Botón de inicio de sesión
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
            response = requests.post(
                API_URL,
                data={"username": username, "password": password}
            )

            if response.status_code == 200:
                data = response.json()
                token = data.get("access_token")

                # 🔐 Guardar sesión local
                payload = decode_token(token)
                role = payload.get("role")
                session.start_session(username, role, token)

                logging.debug(f"🔐 Sesión iniciada - Usuario: {username}, Rol: {role}")
                logging.debug(f"TOKEN: {token}")

                QMessageBox.information(self, "Bienvenido", f"Acceso concedido, {username}.")

                # 👉 Abrir ventana principal
                from ui.main_ui import MainWindow
                self.main_window = MainWindow(username)
                self.main_window.show()
                self.close()

            else:
                QMessageBox.critical(self, "Error", "Credenciales inválidas.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo conectar con el servidor:\n{e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 🔁 Si hay una sesión activa, saltar el login
    if session.is_logged_in():
        logging.debug(f"🔁 Sesión restaurada - Usuario: {session.username}, Rol: {session.role}")
        from ui.main_ui import MainWindow

        main_window = MainWindow(session.username)
        main_window.show()
    else:
        window = LoginWindow()
        window.show()

    sys.exit(app.exec())