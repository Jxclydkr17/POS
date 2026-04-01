from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QFont, QPen, QBrush
import requests
import sys
import logging

# 🧩 Importar gestor de sesión global
from ui.session_manager import session
from app.core.security import decode_token

from ui.api import BASE_URL

API_URL = f"{BASE_URL}/users/login"

# ── Paleta de colores ────────────────────────────────────────────────
VIOLET_DARK   = "#1a0a2e"   # fondo izquierdo (más oscuro)
VIOLET_MID    = "#2d1b4e"   # fondo izquierdo (medio)
VIOLET_LIGHT  = "#6c3db5"   # acento
VIOLET_ACCENT = "#8b5cf6"   # botón / glow
PANEL_BG      = "#12091f"   # fondo derecho
INPUT_BG      = "#1e1133"   # fondo inputs
INPUT_BORDER  = "#3b2170"   # borde sutil
TEXT_PRIMARY  = "#f0e8ff"   # texto principal
TEXT_MUTED    = "#8b7aaa"   # placeholder / texto secundario
GLOW_COLOR    = "rgba(139, 92, 246, 0.45)"   # sombra botón


# ── Panel izquierdo con degradado ───────────────────────────────────
class BrandPanel(QWidget):
    """Mitad izquierda: degradado violeta + logo + tagline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(340)
        self._setup_content()

    def _setup_content(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)
        layout.setContentsMargins(30, 40, 30, 40)

        # Logo SVG-like usando texto + emoji
        logo_icon = QLabel("💜")
        logo_icon.setAlignment(Qt.AlignCenter)
        logo_icon.setStyleSheet("font-size: 52px; background: transparent;")
        layout.addWidget(logo_icon)

        brand_name = QLabel("Violette POS")
        brand_name.setAlignment(Qt.AlignCenter)
        brand_name.setStyleSheet(
            "font-size: 26px; font-weight: 800; color: #f0e8ff;"
            "letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(brand_name)

        separator = QLabel("━━━━━━━━━")
        separator.setAlignment(Qt.AlignCenter)
        separator.setStyleSheet(
            "color: rgba(139,92,246,0.5); font-size: 10px; background: transparent;"
        )
        layout.addWidget(separator)

        tagline = QLabel("Control total de tu negocion\nen una sola pantalla\nVende más y gestiona mejor")
        tagline.setAlignment(Qt.AlignCenter)
        tagline.setWordWrap(True)
        tagline.setStyleSheet(
            "font-size: 13px; color: rgba(208,188,255,0.7);"
            "line-height: 1.6; background: transparent;"
        )
        layout.addWidget(tagline)

        # Decoración inferior
        layout.addStretch()
        deco = QLabel("v1.0  ·  © 2026 Violette")
        deco.setAlignment(Qt.AlignCenter)
        deco.setStyleSheet(
            "font-size: 10px; color: rgba(139,92,246,0.45); background: transparent;"
        )
        layout.addWidget(deco)

    def paintEvent(self, event):
        """Dibuja el degradado de fondo violeta."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0.0, QColor("#0f0520"))
        grad.setColorAt(0.4, QColor("#1e0a3c"))
        grad.setColorAt(1.0, QColor("#2d1060"))

        painter.fillRect(self.rect(), QBrush(grad))

        # Círculos decorativos difuminados
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("rgba(109,60,210,0.18)"))
        painter.drawEllipse(-60, -60, 260, 260)

        painter.setBrush(QColor("rgba(139,92,246,0.12)"))
        painter.drawEllipse(self.width() - 140, self.height() - 140, 220, 220)


# ── Input con icono integrado ────────────────────────────────────────
class IconLineEdit(QFrame):
    """
    Campo de texto moderno: icono unicode a la izquierda + QLineEdit sin bordes.
    El Frame actúa como 'contenedor' que recibe el estilo visual completo.
    """

    STYLE_NORMAL = f"""
        QFrame {{
            background-color: {INPUT_BG};
            border: 1.5px solid {INPUT_BORDER};
            border-radius: 10px;
        }}
    """
    STYLE_FOCUSED = f"""
        QFrame {{
            background-color: {INPUT_BG};
            border: 1.5px solid {VIOLET_ACCENT};
            border-radius: 10px;
        }}
    """

    def __init__(self, icon: str, placeholder: str, echo_mode=QLineEdit.Normal, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self.setStyleSheet(self.STYLE_NORMAL)

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(10)

        # Icono
        icon_label = QLabel(icon)
        icon_label.setFixedWidth(20)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(f"font-size: 16px; color: {TEXT_MUTED}; background: transparent; border: none; border-radius: 0px;")
        h.addWidget(icon_label)

        # Input
        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText(placeholder)
        self.line_edit.setEchoMode(echo_mode)
        self.line_edit.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                color: {TEXT_PRIMARY};
                font-size: 14px;
            }}
            QLineEdit::placeholder {{
                color: {TEXT_MUTED};
            }}
        """)
        self.line_edit.focusInEvent  = self._on_focus_in
        self.line_edit.focusOutEvent = self._on_focus_out
        h.addWidget(self.line_edit)

    def _on_focus_in(self, event):
        self.setStyleSheet(self.STYLE_FOCUSED)
        QLineEdit.focusInEvent(self.line_edit, event)

    def _on_focus_out(self, event):
        self.setStyleSheet(self.STYLE_NORMAL)
        QLineEdit.focusOutEvent(self.line_edit, event)

    def text(self):
        return self.line_edit.text()


# ── Ventana principal ────────────────────────────────────────────────
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Violette POS - Inicio de sesión")
        self.setFixedSize(800, 500)
        self.setStyleSheet(f"background-color: {PANEL_BG};")
        self._setup_ui()

    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Panel izquierdo (branding) ─────────────────────────────
        brand = BrandPanel()
        root.addWidget(brand)

        # ── Panel derecho (formulario) ─────────────────────────────
        form_panel = QWidget()
        form_panel.setStyleSheet(f"background-color: {PANEL_BG};")
        form_layout = QVBoxLayout(form_panel)
        form_layout.setAlignment(Qt.AlignCenter)
        form_layout.setContentsMargins(50, 50, 50, 50)
        form_layout.setSpacing(0)

        # Título
        title = QLabel("Iniciar sesión")
        title.setAlignment(Qt.AlignLeft)
        title.setStyleSheet(
            f"font-size: 28px; font-weight: 800; color: {TEXT_PRIMARY};"
            "letter-spacing: 0.5px;"
        )
        form_layout.addWidget(title)

        subtitle = QLabel("Bienvenido de vuelta 👋")
        subtitle.setStyleSheet(f"font-size: 13px; color: {TEXT_MUTED}; margin-bottom: 28px;")
        form_layout.addWidget(subtitle)

        form_layout.addSpacing(22)

        # Campo usuario
        self.username_input = IconLineEdit("👤", "Usuario")
        form_layout.addWidget(self.username_input)

        form_layout.addSpacing(14)

        # Campo contraseña
        self.password_input = IconLineEdit("🔒", "Contraseña", QLineEdit.Password)
        form_layout.addWidget(self.password_input)

        form_layout.addSpacing(28)

        # Botón Ingresar (glow)
        self.login_button = QPushButton("  Ingresar  →")
        self.login_button.setFixedHeight(50)
        self.login_button.setCursor(Qt.PointingHandCursor)
        self.login_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {VIOLET_ACCENT};
                color: #ffffff;
                border: none;
                border-radius: 12px;
                font-size: 15px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background-color: #7c3aed;
            }}
            QPushButton:pressed {{
                background-color: #6d28d9;
            }}
        """)
        # Sombra/glow vía GraphicsEffect sería ideal, pero el stylesheet
        # box-shadow no existe en Qt; en su lugar se logra con un QGraphicsDropShadowEffect:
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(28)
        glow.setOffset(0, 4)
        glow.setColor(QColor(139, 92, 246, 160))
        self.login_button.setGraphicsEffect(glow)

        self.login_button.clicked.connect(self._handle_login)
        form_layout.addWidget(self.login_button)

        form_layout.addSpacing(18)

        # Texto de pie
        footer = QLabel("Sistema de uso interno — acceso restringido")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet(f"font-size: 11px; color: rgba(139,122,170,0.5);")
        form_layout.addWidget(footer)

        root.addWidget(form_panel)

    # ── Lógica de login (sin cambios) ──────────────────────────────
    def _handle_login(self):
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

                payload = decode_token(token)
                role = payload.get("role")
                session.start_session(username, role, token)

                logging.debug(f"🔐 Sesión iniciada - Usuario: {username}, Rol: {role}")
                logging.debug(f"TOKEN: {token}")

                QMessageBox.information(self, "Bienvenido", f"Acceso concedido, {username}.")

                from ui.main_ui import MainWindow
                self.main_window = MainWindow(username)
                self.main_window.show()
                self.close()

            else:
                QMessageBox.critical(self, "Error", "Credenciales inválidas.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo conectar con el servidor:\n{e}")


# ── Entrypoint ───────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)

    if session.is_logged_in():
        logging.debug(f"🔁 Sesión restaurada - Usuario: {session.username}, Rol: {session.role}")
        from ui.main_ui import MainWindow
        main_window = MainWindow(session.username)
        main_window.show()
    else:
        window = LoginWindow()
        window.show()

    sys.exit(app.exec())