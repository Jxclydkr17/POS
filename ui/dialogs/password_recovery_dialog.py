"""
ui/dialogs/password_recovery_dialog.py — Recuperación de contraseña (estilo Google).

Diálogo multi-paso, EXCLUSIVO para el administrador, que se abre desde el
link "¿Olvidó su contraseña?" en la ventana de login. Replica el flujo de
recuperación de Google en tres pantallas encadenadas (QStackedWidget):

    Paso 1 — Identidad : cédula + correo. El backend valida que coincidan
                          con los del admin. Si no, muestra el error
                          amigable "Mmm, esos no son…".
    Paso 2 — Código    : el admin recibe un código de 6 dígitos en su correo
                          y lo introduce aquí. El backend lo verifica y
                          devuelve un reset_token de un solo uso.
    Paso 3 — Nueva clave: el admin escribe y confirma su nueva contraseña.
                          El backend la actualiza con el reset_token.

Diseño:
  - 100% sobre el backend vía `api_call` (igual que login_view): la UI nunca
    toca la BD ni envía correos directamente.
  - Paleta violeta/oscura coherente con login_view.py y setup_wizard.py
    (se redeclara localmente, como ya hace setup_wizard.py, para que el
    archivo sea auto-contenido y no genere imports circulares con login_view).
"""
from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog, QWidget, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox,
)

from ui.api import BASE_URL
from ui.utils.http_worker import api_call

# ── Paleta — coherente con ui/login_view.py ──────────────────────────
VIOLET_LIGHT  = "#6c3db5"
VIOLET_ACCENT = "#8b5cf6"
PANEL_BG      = "#12091f"
INPUT_BG      = "#1e1133"
INPUT_BORDER  = "#3b2170"
TEXT_PRIMARY  = "#f0e8ff"
TEXT_MUTED    = "#8b7aaa"


class PasswordRecoveryDialog(QDialog):
    """Flujo de recuperación de contraseña del administrador (3 pasos)."""

    # Índices de las páginas del stack
    PAGE_IDENTITY = 0
    PAGE_CODE = 1
    PAGE_PASSWORD = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recuperar contraseña — Violette POS")
        self.setFixedSize(440, 460)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {PANEL_BG}; }}
            QLabel {{ color: {TEXT_PRIMARY}; background: transparent; }}
            QLineEdit {{
                background-color: {INPUT_BG};
                border: 1.5px solid {INPUT_BORDER};
                border-radius: 8px;
                padding: 10px 12px;
                color: {TEXT_PRIMARY};
                font-size: 14px;
            }}
            QLineEdit:focus {{ border-color: {VIOLET_ACCENT}; }}
            QPushButton#primary {{
                background-color: {VIOLET_ACCENT};
                color: white; border: none; border-radius: 8px;
                padding: 11px; font-size: 14px; font-weight: bold;
            }}
            QPushButton#primary:hover {{ background-color: {VIOLET_LIGHT}; }}
            QPushButton#primary:disabled {{ background-color: #3b2170; color: #8b7aaa; }}
            QPushButton#link {{
                background: transparent; border: none;
                color: {TEXT_MUTED}; font-size: 12px; text-align: left;
            }}
            QPushButton#link:hover {{ color: {VIOLET_ACCENT}; }}
        """)

        # Estado del flujo
        self._reset_token = None

        self._build_ui()
        self._show_step(self.PAGE_IDENTITY)

    # ══════════════════════════════════════════════════════════════
    # Construcción de la UI
    # ══════════════════════════════════════════════════════════════
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 28)
        root.setSpacing(8)

        # Encabezado
        self._icon = QLabel("🔑")
        self._icon.setStyleSheet("font-size: 34px;")
        root.addWidget(self._icon)

        self._title = QLabel("¿Olvidó su contraseña?")
        self._title.setStyleSheet(
            f"font-size: 21px; font-weight: 800; color: {TEXT_PRIMARY};"
        )
        root.addWidget(self._title)

        self._subtitle = QLabel()
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(f"font-size: 12px; color: {TEXT_MUTED};")
        root.addWidget(self._subtitle)

        root.addSpacing(10)

        # Stack de pasos
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_identity_page())
        self._stack.addWidget(self._build_code_page())
        self._stack.addWidget(self._build_password_page())
        root.addWidget(self._stack)

        root.addStretch()

        # Pie: cancelar
        self._btn_cancel = QPushButton("Cancelar")
        self._btn_cancel.setObjectName("link")
        self._btn_cancel.setCursor(Qt.PointingHandCursor)
        self._btn_cancel.clicked.connect(self.reject)
        root.addWidget(self._btn_cancel)

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 13px; font-weight: 600;")
        return lbl

    # ── Paso 1: identidad (cédula + correo) ──────────────────────
    def _build_identity_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(self._section_label("Cédula"))
        self._inp_cedula = QLineEdit()
        self._inp_cedula.setPlaceholderText("1-1234-5678")
        lay.addWidget(self._inp_cedula)

        lay.addSpacing(6)
        lay.addWidget(self._section_label("Correo electrónico"))
        self._inp_correo = QLineEdit()
        self._inp_correo.setPlaceholderText("correo@ejemplo.com")
        lay.addWidget(self._inp_correo)

        lay.addSpacing(14)
        self._btn_identity = QPushButton("Continuar")
        self._btn_identity.setObjectName("primary")
        self._btn_identity.setCursor(Qt.PointingHandCursor)
        self._btn_identity.clicked.connect(self._do_request_code)
        lay.addWidget(self._btn_identity)

        self._inp_correo.returnPressed.connect(self._do_request_code)
        return page

    # ── Paso 2: código de 6 dígitos ──────────────────────────────
    def _build_code_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(self._section_label("Código de verificación"))
        self._inp_code = QLineEdit()
        self._inp_code.setPlaceholderText("000000")
        self._inp_code.setMaxLength(6)
        self._inp_code.setAlignment(Qt.AlignCenter)
        self._inp_code.setStyleSheet(
            "font-size: 26px; font-weight: bold; letter-spacing: 12px;"
        )
        # Solo dígitos, máximo 6.
        self._inp_code.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d{0,6}"))
        )
        lay.addWidget(self._inp_code)

        lay.addSpacing(8)
        self._btn_verify = QPushButton("Verificar")
        self._btn_verify.setObjectName("primary")
        self._btn_verify.setCursor(Qt.PointingHandCursor)
        self._btn_verify.clicked.connect(self._do_verify_code)
        lay.addWidget(self._btn_verify)

        self._btn_resend = QPushButton("Reenviar código")
        self._btn_resend.setObjectName("link")
        self._btn_resend.setCursor(Qt.PointingHandCursor)
        self._btn_resend.clicked.connect(self._do_request_code)
        lay.addWidget(self._btn_resend)

        self._inp_code.returnPressed.connect(self._do_verify_code)
        return page

    # ── Paso 3: nueva contraseña ─────────────────────────────────
    def _build_password_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(self._section_label("Nueva contraseña (mínimo 8 caracteres)"))
        self._inp_new = QLineEdit()
        self._inp_new.setEchoMode(QLineEdit.Password)
        self._inp_new.setPlaceholderText("••••••••")
        lay.addWidget(self._inp_new)

        lay.addSpacing(6)
        lay.addWidget(self._section_label("Confirmar nueva contraseña"))
        self._inp_confirm = QLineEdit()
        self._inp_confirm.setEchoMode(QLineEdit.Password)
        self._inp_confirm.setPlaceholderText("••••••••")
        lay.addWidget(self._inp_confirm)

        lay.addSpacing(14)
        self._btn_save = QPushButton("Guardar nueva contraseña")
        self._btn_save.setObjectName("primary")
        self._btn_save.setCursor(Qt.PointingHandCursor)
        self._btn_save.clicked.connect(self._do_reset_password)
        lay.addWidget(self._btn_save)

        self._inp_confirm.returnPressed.connect(self._do_reset_password)
        return page

    # ══════════════════════════════════════════════════════════════
    # Navegación entre pasos
    # ══════════════════════════════════════════════════════════════
    def _show_step(self, index: int):
        self._stack.setCurrentIndex(index)
        if index == self.PAGE_IDENTITY:
            self._icon.setText("🔑")
            self._title.setText("¿Olvidó su contraseña?")
            self._subtitle.setText(
                "Ingresá la cédula y el correo del administrador para "
                "verificar tu identidad."
            )
            self._inp_cedula.setFocus()
        elif index == self.PAGE_CODE:
            self._icon.setText("📧")
            self._title.setText("Revisá tu correo")
            # El subtítulo con el correo enmascarado se fija al recibir la respuesta.
            self._inp_code.clear()
            self._inp_code.setFocus()
        elif index == self.PAGE_PASSWORD:
            self._icon.setText("🔒")
            self._title.setText("Nueva contraseña")
            self._subtitle.setText(
                "Elegí una contraseña nueva. La usarás la próxima vez que "
                "inicies sesión."
            )
            self._inp_new.setFocus()

    # ══════════════════════════════════════════════════════════════
    # Paso 1 → solicitar código
    # ══════════════════════════════════════════════════════════════
    def _do_request_code(self):
        cedula = self._inp_cedula.text().strip()
        correo = self._inp_correo.text().strip()

        if not cedula:
            QMessageBox.warning(self, "Falta la cédula", "Ingresá tu número de cédula.")
            return
        if not correo or "@" not in correo:
            QMessageBox.warning(self, "Correo inválido", "Ingresá un correo electrónico válido.")
            return

        # Si estamos reenviando desde el paso del código, deshabilitar ese botón.
        resending = self._stack.currentIndex() == self.PAGE_CODE
        btn = self._btn_resend if resending else self._btn_identity
        original_text = btn.text()
        btn.setEnabled(False)
        btn.setText("⏳ Enviando…")

        def _on_ok(data):
            btn.setEnabled(True)
            btn.setText(original_text)
            masked = (data or {}).get("correo_masked") or correo
            self._subtitle.setText(
                f"Enviamos un código de 6 dígitos a {masked}. "
                "Ingresalo abajo (vence en 10 minutos)."
            )
            if not resending:
                self._show_step(self.PAGE_CODE)
            else:
                QMessageBox.information(self, "Código reenviado",
                                        "Te enviamos un código nuevo a tu correo.")

        def _on_err(msg):
            btn.setEnabled(True)
            btn.setText(original_text)
            # El backend ya manda mensajes amigables ("Mmm, esos no son…",
            # correo no configurado, etc.). Los mostramos tal cual.
            QMessageBox.warning(self, "No pudimos continuar", msg)

        api_call(
            "post", f"{BASE_URL}/users/recover-password/request",
            json={"cedula": cedula, "correo": correo},
            timeout=(5, 20),
            on_success=_on_ok,
            on_error=_on_err,
        )

    # ══════════════════════════════════════════════════════════════
    # Paso 2 → verificar código
    # ══════════════════════════════════════════════════════════════
    def _do_verify_code(self):
        code = self._inp_code.text().strip()
        if len(code) != 6 or not code.isdigit():
            QMessageBox.warning(self, "Código incompleto",
                                "El código tiene 6 dígitos. Revisalo e intentá de nuevo.")
            return

        cedula = self._inp_cedula.text().strip()
        correo = self._inp_correo.text().strip()

        self._btn_verify.setEnabled(False)
        self._btn_verify.setText("⏳ Verificando…")

        def _on_ok(data):
            self._btn_verify.setEnabled(True)
            self._btn_verify.setText("Verificar")
            self._reset_token = (data or {}).get("reset_token")
            if not self._reset_token:
                QMessageBox.critical(self, "Error",
                                     "No recibimos el token de reseteo. Intentá de nuevo.")
                return
            self._show_step(self.PAGE_PASSWORD)

        def _on_err(msg):
            self._btn_verify.setEnabled(True)
            self._btn_verify.setText("Verificar")
            QMessageBox.warning(self, "Código incorrecto", msg)

        api_call(
            "post", f"{BASE_URL}/users/recover-password/verify",
            json={"cedula": cedula, "correo": correo, "code": code},
            timeout=(5, 15),
            on_success=_on_ok,
            on_error=_on_err,
        )

    # ══════════════════════════════════════════════════════════════
    # Paso 3 → resetear contraseña
    # ══════════════════════════════════════════════════════════════
    def _do_reset_password(self):
        pwd = self._inp_new.text()
        conf = self._inp_confirm.text()

        if len(pwd) < 8:
            QMessageBox.warning(self, "Contraseña corta",
                                "La contraseña debe tener al menos 8 caracteres.")
            return
        if pwd != conf:
            QMessageBox.warning(self, "No coinciden",
                                "Las contraseñas no coinciden.")
            return
        if not self._reset_token:
            QMessageBox.critical(self, "Sesión expirada",
                                 "La sesión de recuperación expiró. Iniciá el proceso de nuevo.")
            self._show_step(self.PAGE_IDENTITY)
            return

        self._btn_save.setEnabled(False)
        self._btn_save.setText("⏳ Guardando…")

        def _on_ok(data):
            QMessageBox.information(
                self, "¡Listo!",
                "Tu contraseña fue actualizada.\nYa podés iniciar sesión con tu nueva contraseña."
            )
            self.accept()

        def _on_err(msg):
            self._btn_save.setEnabled(True)
            self._btn_save.setText("Guardar nueva contraseña")
            QMessageBox.warning(self, "No pudimos actualizar", msg)

        api_call(
            "post", f"{BASE_URL}/users/recover-password/reset",
            json={"reset_token": self._reset_token, "new_password": pwd},
            timeout=(5, 15),
            on_success=_on_ok,
            on_error=_on_err,
        )