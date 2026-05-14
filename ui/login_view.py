from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox, QFrame, QSizePolicy,
    QDialog, QDialogButtonBox
)
from PySide6.QtCore import Qt, QSize, QThread, QTimer, Signal, QObject
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QFont, QPen, QBrush, QPixmap
import requests
import sys
import logging

# 🧩 Importar gestor de sesión global
from ui.session_manager import session
from app.core.security import decode_token
from app.core.config import APP_VERSION
from ui.utils.http_worker import api_call, configure_thread_pool
from ui.utils.exception_hooks import install_global_exception_hooks

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

        # Logo: imagen de Violette
        import os
        logo_icon = QLabel()
        logo_icon.setAlignment(Qt.AlignCenter)
        logo_icon.setStyleSheet("background: transparent;")
        _img_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "violette_assistant_icon.png")
        _pixmap = QPixmap(_img_path)
        if not _pixmap.isNull():
            logo_icon.setPixmap(_pixmap.scaled(90, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            logo_icon.setText("💜")
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

        tagline = QLabel("Control total de tu negocio\nen una sola pantalla\nVende más y gestiona mejor")
        tagline.setAlignment(Qt.AlignCenter)
        tagline.setWordWrap(True)
        tagline.setStyleSheet(
            "font-size: 13px; color: rgba(208,188,255,0.7);"
            "line-height: 1.6; background: transparent;"
        )
        layout.addWidget(tagline)

        # Decoración inferior
        layout.addStretch()
        deco = QLabel(f"v{APP_VERSION}  ·  © 2026 Violette")
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


# ── Fix 4.3: Worker para login asíncrono ─────────────────────────────
class _LoginWorker(QObject):
    """Ejecuta el POST de login en un hilo separado para no congelar la UI."""
    success = Signal(dict)   # emite la respuesta JSON completa
    failed = Signal(str)     # emite el mensaje de error

    def __init__(self, url, username, password):
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
        except Exception as e:
            self.failed.emit(f"No se pudo conectar con el servidor:\n{e}")


# ── Ventana principal ────────────────────────────────────────────────
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Violette POS - Inicio de sesión")
        self.setFixedSize(800, 500)
        self.setStyleSheet(f"background-color: {PANEL_BG};")
        self._setup_ui()
        # ── FASE 3 — Fix 3.4: Verificar si necesita setup inicial ──
        self._check_needs_setup()

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

    # ── FASE 3 — Fix 3.4 + Fix 4.3: Setup inicial (asíncrono) ──────
    def _check_needs_setup(self):
        """Consulta al backend si la BD tiene cero usuarios (sin bloquear UI)."""
        import threading

        def _check():
            try:
                resp = requests.get(f"{BASE_URL}/users/needs-setup", timeout=5)
                if resp.status_code == 200 and resp.json().get("needs_setup"):
                    # Volver al hilo principal de Qt para mostrar el diálogo
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, self._show_setup_dialog)
            except Exception:
                pass  # Si el backend no responde, mostrar login normal

        threading.Thread(target=_check, daemon=True).start()

    def _show_setup_dialog(self):
        """Diálogo para crear el primer administrador cuando la BD está vacía."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Configuración inicial — Violette POS")
        dlg.setFixedSize(420, 340)
        dlg.setStyleSheet(f"""
            QDialog {{
                background-color: {PANEL_BG};
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
            }}
            QLineEdit {{
                background-color: {INPUT_BG};
                border: 1.5px solid {INPUT_BORDER};
                border-radius: 8px;
                padding: 8px 12px;
                color: {TEXT_PRIMARY};
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: {VIOLET_ACCENT};
            }}
            QPushButton {{
                background-color: {VIOLET_ACCENT};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {VIOLET_LIGHT};
            }}
        """)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(30, 25, 30, 25)

        # Título
        title = QLabel("🔐  Primera ejecución")
        title.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        info = QLabel(
            "No se encontraron usuarios en la base de datos.\n"
            "Cree el administrador inicial para comenzar."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"font-size: 12px; color: {TEXT_MUTED}; margin-bottom: 4px;")
        layout.addWidget(info)

        # Campos
        lbl_user = QLabel("Usuario")
        lbl_user.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(lbl_user)
        setup_user = QLineEdit()
        setup_user.setPlaceholderText("admin")
        setup_user.setText("admin")
        layout.addWidget(setup_user)

        lbl_pass = QLabel("Contraseña (mínimo 8 caracteres)")
        lbl_pass.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(lbl_pass)
        setup_pass = QLineEdit()
        setup_pass.setEchoMode(QLineEdit.Password)
        setup_pass.setPlaceholderText("••••••••")
        layout.addWidget(setup_pass)

        lbl_confirm = QLabel("Confirmar contraseña")
        lbl_confirm.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(lbl_confirm)
        setup_confirm = QLineEdit()
        setup_confirm.setEchoMode(QLineEdit.Password)
        setup_confirm.setPlaceholderText("••••••••")
        layout.addWidget(setup_confirm)

        # Botón
        btn_create = QPushButton("Crear administrador")
        layout.addWidget(btn_create)

        def _do_setup():
            username = setup_user.text().strip()
            password = setup_pass.text()
            confirm = setup_confirm.text()

            if not username or len(username) < 3:
                QMessageBox.warning(dlg, "Error", "El usuario debe tener al menos 3 caracteres.")
                return
            if len(password) < 8:
                QMessageBox.warning(dlg, "Error", "La contraseña debe tener al menos 8 caracteres.")
                return
            if password != confirm:
                QMessageBox.warning(dlg, "Error", "Las contraseñas no coinciden.")
                return

            btn_create.setEnabled(False)
            btn_create.setText("⏳ Creando...")

            def _on_ok(data):
                QMessageBox.information(
                    dlg, "Listo",
                    f"Administrador '{username}' creado exitosamente.\n"
                    "Ahora puede iniciar sesión."
                )
                dlg.accept()

            def _on_err(msg):
                btn_create.setEnabled(True)
                btn_create.setText("Crear administrador")
                QMessageBox.critical(dlg, "Error", f"No se pudo crear el usuario:\n{msg}")

            api_call(
                "post", f"{BASE_URL}/users/setup",
                json={"username": username, "password": password},
                timeout=(5, 10),
                on_success=_on_ok,
                on_error=_on_err,
            )

        btn_create.clicked.connect(_do_setup)
        setup_pass.returnPressed.connect(_do_setup)
        setup_confirm.returnPressed.connect(_do_setup)

        dlg.exec()

    # ── FASE 6 — Fix 6.1: Diálogo de cambio de contraseña obligatorio ──
    def _show_change_password_dialog(self, current_password):
        """Muestra diálogo para cambiar la contraseña. Retorna True si se cambió."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Cambio de contraseña obligatorio")
        dlg.setFixedSize(420, 280)
        dlg.setStyleSheet(f"""
            QDialog {{ background-color: {PANEL_BG}; }}
            QLabel {{ color: {TEXT_PRIMARY}; }}
            QLineEdit {{
                background-color: {INPUT_BG}; border: 1.5px solid {INPUT_BORDER};
                border-radius: 8px; padding: 8px 12px; color: {TEXT_PRIMARY}; font-size: 14px;
            }}
            QLineEdit:focus {{ border-color: {VIOLET_ACCENT}; }}
            QPushButton {{
                background-color: {VIOLET_ACCENT}; color: white; border: none;
                border-radius: 8px; padding: 10px; font-size: 14px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {VIOLET_LIGHT}; }}
        """)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(30, 25, 30, 25)

        title = QLabel("🔒  Debe cambiar su contraseña")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(title)

        info = QLabel("Por seguridad, debe establecer una contraseña personalizada antes de continuar.")
        info.setWordWrap(True)
        info.setStyleSheet(f"font-size: 12px; color: {TEXT_MUTED}; margin-bottom: 4px;")
        layout.addWidget(info)

        lbl_new = QLabel("Nueva contraseña (mínimo 8 caracteres)")
        lbl_new.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(lbl_new)
        new_pass = QLineEdit()
        new_pass.setEchoMode(QLineEdit.Password)
        new_pass.setPlaceholderText("••••••••")
        layout.addWidget(new_pass)

        lbl_confirm = QLabel("Confirmar nueva contraseña")
        lbl_confirm.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(lbl_confirm)
        confirm_pass = QLineEdit()
        confirm_pass.setEchoMode(QLineEdit.Password)
        confirm_pass.setPlaceholderText("••••••••")
        layout.addWidget(confirm_pass)

        btn_save = QPushButton("Guardar nueva contraseña")
        layout.addWidget(btn_save)

        result = {"changed": False}

        def _do_change():
            pwd = new_pass.text()
            conf = confirm_pass.text()
            if len(pwd) < 8:
                QMessageBox.warning(dlg, "Error", "La contraseña debe tener al menos 8 caracteres.")
                return
            if pwd != conf:
                QMessageBox.warning(dlg, "Error", "Las contraseñas no coinciden.")
                return
            if pwd == current_password:
                QMessageBox.warning(dlg, "Error", "La nueva contraseña debe ser diferente a la actual.")
                return

            btn_save.setEnabled(False)
            btn_save.setText("⏳ Guardando...")

            def _on_ok(new_data):
                new_token = new_data.get("access_token")
                if new_token:
                    session.token = new_token
                    session.save_session()
                result["changed"] = True
                QMessageBox.information(dlg, "Listo", "Contraseña actualizada exitosamente.")
                dlg.accept()

            def _on_err(msg):
                btn_save.setEnabled(True)
                btn_save.setText("Guardar nueva contraseña")
                QMessageBox.critical(dlg, "Error", f"No se pudo cambiar la contraseña:\n{msg}")

            api_call(
                "post", f"{BASE_URL}/users/me/change-password",
                json={"current_password": current_password, "new_password": pwd},
                headers={"Authorization": f"Bearer {session.token}"},
                timeout=(5, 15),
                on_success=_on_ok,
                on_error=_on_err,
            )

        btn_save.clicked.connect(_do_change)
        confirm_pass.returnPressed.connect(_do_change)
        dlg.exec()
        return result["changed"]

    # ── Lógica de login (Fix 4.3: asíncrono con spinner) ────────
    def _set_login_loading(self, loading: bool):
        """Alterna el estado de carga del botón de login."""
        self.login_button.setEnabled(not loading)
        self.login_button.setText("  ⏳ Verificando...  " if loading else "  Ingresar  →")

    def _handle_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        if not username or not password:
            QMessageBox.warning(self, "Campos vacíos", "Por favor ingrese usuario y contraseña.")
            return

        # Guardar password para posible cambio de contraseña obligatorio
        self._pending_password = password

        self._set_login_loading(True)

        worker = _LoginWorker(API_URL, username, password)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._on_login_success)
        worker.success.connect(thread.quit)
        worker.failed.connect(self._on_login_failed)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

        # Mantener referencia para evitar GC prematuro
        self._login_thread = thread
        self._login_worker = worker

    def _on_login_success(self, data: dict):
        """Callback en hilo principal tras login exitoso."""
        self._set_login_loading(False)

        username = self.username_input.text().strip()
        token = data.get("access_token")

        payload = decode_token(token)
        role = payload.get("role")

        # ── FASE 4 — Fix 4.1: Forzar cambio de contraseña ANTES de persistir sesión ──
        # Antes: start_session() guardaba el token a disco con admin123 vigente,
        # y si el usuario cerraba la ventana de cambio, la sesión quedaba
        # persistida con la contraseña insegura. Ahora solo guardamos la sesión
        # en memoria temporalmente para que el dialog pueda usar el token,
        # pero NO la persistimos a disco hasta que el cambio se complete.
        if data.get("must_change_password"):
            # Sesión temporal solo en memoria (para que el dialog use session.token)
            session.token = token
            session.username = username
            session.role = role
            # NO llamar save_session() aquí

            changed = self._show_change_password_dialog(self._pending_password)
            if not changed:
                # Usuario cerró el dialog sin cambiar → limpiar todo
                session.token = None
                session.username = None
                session.role = None
                return

            # El dialog ya actualizó session.token con el nuevo token
            # y llamó save_session(). No sobreescribir con el token viejo.
            # Solo asegurar que username/role estén persistidos.
            session.save_session()
        else:
            # No requería cambio de contraseña → persistir normalmente
            session.start_session(username, role, token)

        logging.debug(f"🔐 Sesión iniciada - Usuario: {username}, Rol: {role}")

        # ──────────────────────────────────────────────────────────────
        # FIX: diferir la apertura de MainWindow al siguiente tick del
        # event loop. Razón: estamos dentro de un slot conectado al
        # signal `success` del _LoginWorker. El worker thread aún no se
        # completó (su `thread.quit()` está en cola detrás de nosotros).
        # Crear MainWindow + close() de LoginWindow DENTRO del mismo
        # slot, con el worker thread aún vivo y signals pendientes
        # apuntando a `self`, es un patrón conocido por causar access
        # violations en PySide6.
        #
        # Diferir con singleShot(0) garantiza que el worker termine
        # ANTES de tocar las ventanas.
        # ──────────────────────────────────────────────────────────────
        QTimer.singleShot(0, lambda u=username: self._open_main_window(u))

    def _open_main_window(self, username: str):
        """
        Crea y muestra MainWindow. Llamado vía QTimer.singleShot desde
        _on_login_success para que el worker de login termine antes.
        Tiene checkpoints de log para diagnosticar dónde crashea, si
        es que sigue crasheando.
        """
        _log = logging.getLogger(__name__)
        try:
            _log.debug("CHECKPOINT 1/6: limpiando referencias al worker de login")
            # Liberar refs al worker — su C++ ya fue/será eliminado vía
            # deleteLater y mantener punteros vivos a un objeto destruido
            # es la causa típica de access violations al construir la
            # ventana siguiente.
            if hasattr(self, "_login_worker"):
                self._login_worker = None
            if hasattr(self, "_login_thread"):
                self._login_thread = None

            _log.debug("CHECKPOINT 2/6: mostrando MessageBox 'Bienvenido'")
            QMessageBox.information(
                self, "Bienvenido", f"Acceso concedido, {username}."
            )

            _log.debug("CHECKPOINT 3/6: importando MainWindow")
            from ui.main_ui import MainWindow

            _log.debug("CHECKPOINT 4/6: construyendo MainWindow")
            self.main_window = MainWindow(username)

            _log.debug("CHECKPOINT 5/6: llamando main_window.show()")
            self.main_window.show()

            _log.debug("CHECKPOINT 6/6: cerrando LoginWindow")
            self.close()

            _log.debug("✅ Apertura de MainWindow completada sin excepciones.")

        except Exception as e:
            _log.error(
                f"❌ Excepción en _open_main_window: {type(e).__name__}: {e}",
                exc_info=True,
            )
            # Re-raise: el sys.excepthook global lo capturará y mostrará
            # un QMessageBox en lugar de cerrar la app silenciosamente.
            raise

    def _on_login_failed(self, error_msg: str):
        """Callback en hilo principal tras login fallido."""
        self._set_login_loading(False)
        QMessageBox.critical(self, "Error", error_msg)


# ── Entrypoint ───────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)

    # ── FIX CRÍTICO: instalar manejadores globales de excepciones ──
    # Sin esto, cualquier excepción no manejada dentro de un slot de Qt
    # (clicked.connect, on_success del HttpWorker, timers, etc.) cierra
    # la app silenciosamente en PySide6 6.6+. Esto debe llamarse JUSTO
    # DESPUÉS de crear QApplication y ANTES de cualquier otro código UI.
    install_global_exception_hooks()

    # ── Configurar el QThreadPool con el límite definido en http_worker.py.
    # Sin esta llamada, QThreadPool usa el default del SO (que en Windows
    # puede ser 8+ hilos), permitiendo concurrencia que actualmente
    # estamos diagnosticando como causa de crashes binarios.
    configure_thread_pool()

    if session.is_logged_in():
        logging.debug(f"🔁 Sesión restaurada - Usuario: {session.username}, Rol: {session.role}")
        from ui.main_ui import MainWindow
        main_window = MainWindow(session.username)
        main_window.show()
    else:
        window = LoginWindow()
        window.show()

    sys.exit(app.exec())