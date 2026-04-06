# ui/dialogs/user_dialog.py
"""
Diálogo para crear y editar usuarios/cajeros.
Fase 3: CRUD + permisos granulares.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QMessageBox, QFormLayout,
    QGroupBox, QGridLayout, QScrollArea, QWidget,
)
from PySide6.QtCore import Qt
import logging

logger = logging.getLogger(__name__)

# Etiquetas legibles para cada permiso
PERMISSION_LABELS = {
    "ver_dashboard": "Ver Dashboard",
    "ver_ventas": "Ver Ventas",
    "hacer_ventas": "Realizar Ventas",
    "ver_productos": "Ver Productos",
    "editar_productos": "Editar Productos",
    "ver_clientes": "Ver Clientes",
    "editar_clientes": "Editar Clientes",
    "ver_proveedores": "Ver Proveedores",
    "editar_proveedores": "Editar Proveedores",
    "ver_categorias": "Ver Categorías",
    "editar_categorias": "Editar Categorías",
    "ver_compras": "Ver Compras",
    "editar_compras": "Editar Compras",
    "ver_proformas": "Ver Proformas",
    "editar_proformas": "Editar Proformas",
    "ver_reportes": "Ver Reportes",
    "ver_gastos": "Ver Gastos",
    "editar_gastos": "Editar Gastos",
    "ver_financiero": "Ver Financiero",
    "facturacion_electronica": "Facturación Electrónica",
    "acceder_configuracion": "Acceder a Configuración",
    "gestionar_usuarios": "Gestionar Usuarios",
}

DIALOG_STYLE = """
    QDialog {
        background-color: #111827;
        color: #e5e7eb;
    }
    QLabel {
        color: #e5e7eb;
    }
    QLineEdit, QComboBox {
        background-color: #1f2937;
        color: #e5e7eb;
        border: 1px solid #374151;
        border-radius: 6px;
        padding: 6px 8px;
        min-height: 28px;
    }
    QCheckBox {
        color: #e5e7eb;
        spacing: 6px;
    }
    QCheckBox::indicator {
        width: 16px; height: 16px;
        border: 1px solid #555;
        border-radius: 3px;
        background-color: #1f2937;
    }
    QCheckBox::indicator:checked {
        background-color: #3a86ff;
        border-color: #3a86ff;
    }
    QGroupBox {
        color: #a5b4fc;
        border: 1px solid #374151;
        border-radius: 8px;
        margin-top: 12px;
        padding-top: 18px;
        font-weight: bold;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }
    QPushButton {
        border: none;
        border-radius: 8px;
        padding: 8px 20px;
        font-weight: 600;
        font-size: 13px;
    }
"""


class UserDialog(QDialog):
    """
    Diálogo para agregar o editar un usuario.

    Args:
        user_data: dict con datos del usuario (None = modo agregar).
        all_permissions: lista de permisos disponibles del sistema.
        default_permissions: dict de permisos default por rol.
    """

    def __init__(
        self,
        user_data: dict | None = None,
        all_permissions: list[str] | None = None,
        default_permissions: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.user_data = user_data
        self.is_edit = user_data is not None
        self.all_permissions = all_permissions or []
        self.default_permissions = default_permissions or {}
        self.result_data = None

        self.setWindowTitle("Editar usuario" if self.is_edit else "Agregar usuario")
        self.setMinimumWidth(520)
        self.setMinimumHeight(500)
        self.resize(560, 620)
        self.setStyleSheet(DIALOG_STYLE)

        self._build_ui()

        if self.is_edit:
            self._populate(user_data)

    # ----------------------------------------------------------
    # Construir UI
    # ----------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # Título
        title = QLabel("✏️ Editar usuario" if self.is_edit else "➕ Agregar usuario")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 4px;")
        layout.addWidget(title)

        # -- Formulario datos básicos --
        form = QFormLayout()
        form.setSpacing(8)

        self.input_username = QLineEdit()
        self.input_username.setPlaceholderText("Mínimo 3 caracteres")
        form.addRow("Usuario:", self.input_username)

        self.input_password = QLineEdit()
        self.input_password.setEchoMode(QLineEdit.EchoMode.Password)
        if self.is_edit:
            self.input_password.setPlaceholderText("Dejar vacío para no cambiar")
        else:
            self.input_password.setPlaceholderText("Mínimo 8 caracteres")
        form.addRow("Contraseña:", self.input_password)

        self.input_full_name = QLineEdit()
        self.input_full_name.setPlaceholderText("Nombre completo")
        form.addRow("Nombre:", self.input_full_name)

        self.combo_role = QComboBox()
        self.combo_role.addItems(["vendedor", "cajero", "admin"])
        self.combo_role.currentTextChanged.connect(self._on_role_changed)
        form.addRow("Rol:", self.combo_role)

        if self.is_edit:
            self.chk_active = QCheckBox("Usuario activo")
            self.chk_active.setChecked(True)
            form.addRow("Estado:", self.chk_active)

        layout.addLayout(form)

        # -- Permisos --
        self.permissions_group = QGroupBox("🔑 Permisos")
        perms_outer = QVBoxLayout(self.permissions_group)

        # Botones rápidos
        btn_row = QHBoxLayout()
        btn_all = QPushButton("Marcar todos")
        btn_all.setStyleSheet("background-color: #374151; color: white;")
        btn_all.clicked.connect(lambda: self._set_all_perms(True))
        btn_none = QPushButton("Desmarcar todos")
        btn_none.setStyleSheet("background-color: #374151; color: white;")
        btn_none.clicked.connect(lambda: self._set_all_perms(False))
        btn_defaults = QPushButton("Defaults del rol")
        btn_defaults.setStyleSheet("background-color: #374151; color: white;")
        btn_defaults.clicked.connect(self._apply_role_defaults)
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addWidget(btn_defaults)
        btn_row.addStretch()
        perms_outer.addLayout(btn_row)

        # Scroll area con checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        grid = QGridLayout(scroll_widget)
        grid.setSpacing(6)

        self.perm_checkboxes: dict[str, QCheckBox] = {}
        for i, perm in enumerate(self.all_permissions):
            label = PERMISSION_LABELS.get(perm, perm)
            chk = QCheckBox(label)
            chk.setProperty("perm_key", perm)
            self.perm_checkboxes[perm] = chk
            row, col = divmod(i, 2)
            grid.addWidget(chk, row, col)

        scroll.setWidget(scroll_widget)
        perms_outer.addWidget(scroll)

        layout.addWidget(self.permissions_group, 1)

        # -- Botones finales --
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setStyleSheet("background-color: #374151; color: white;")
        btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(btn_cancel)

        btn_save = QPushButton("💾 Guardar")
        btn_save.setStyleSheet("background-color: #3a86ff; color: white;")
        btn_save.clicked.connect(self._on_save)
        btn_bar.addWidget(btn_save)

        layout.addLayout(btn_bar)

        # Estado inicial de permisos según rol
        self._on_role_changed(self.combo_role.currentText())

    # ----------------------------------------------------------
    # Poblar datos en modo edición
    # ----------------------------------------------------------
    def _populate(self, data: dict):
        self.input_username.setText(data.get("username", ""))
        self.input_full_name.setText(data.get("full_name", "") or "")

        role = data.get("role", "vendedor")
        idx = self.combo_role.findText(role)
        if idx >= 0:
            self.combo_role.setCurrentIndex(idx)

        if hasattr(self, "chk_active"):
            self.chk_active.setChecked(data.get("is_active", True))

        # Marcar permisos actuales del usuario
        user_perms = data.get("permissions", [])
        for perm, chk in self.perm_checkboxes.items():
            chk.setChecked(perm in user_perms)

        # Si es admin, deshabilitar permisos (siempre tiene todos)
        if role == "admin":
            self._disable_perms(True)

    # ----------------------------------------------------------
    # Callbacks
    # ----------------------------------------------------------
    def _on_role_changed(self, role: str):
        """Cuando cambia el rol, actualizar permisos visibles."""
        is_admin = role == "admin"
        self._disable_perms(is_admin)

        if is_admin:
            self._set_all_perms(True)
        elif not self.is_edit:
            # Solo aplicar defaults si estamos creando (no editar)
            self._apply_role_defaults()

    def _disable_perms(self, disabled: bool):
        """Habilita/deshabilita todos los checkboxes de permisos."""
        for chk in self.perm_checkboxes.values():
            chk.setEnabled(not disabled)

    def _set_all_perms(self, checked: bool):
        for chk in self.perm_checkboxes.values():
            chk.setChecked(checked)

    def _apply_role_defaults(self):
        role = self.combo_role.currentText()
        defaults = self.default_permissions.get(role, [])
        for perm, chk in self.perm_checkboxes.items():
            chk.setChecked(perm in defaults)

    # ----------------------------------------------------------
    # Guardar
    # ----------------------------------------------------------
    def _on_save(self):
        username = self.input_username.text().strip()
        password = self.input_password.text()
        full_name = self.input_full_name.text().strip()
        role = self.combo_role.currentText()

        # Validaciones
        if len(username) < 3:
            QMessageBox.warning(self, "Error", "El usuario debe tener al menos 3 caracteres.")
            return

        if not self.is_edit and len(password) < 8:
            QMessageBox.warning(self, "Error", "La contraseña debe tener al menos 8 caracteres.")
            return

        if self.is_edit and password and len(password) < 8:
            QMessageBox.warning(self, "Error", "La contraseña debe tener al menos 8 caracteres.")
            return

        # Recopilar permisos seleccionados
        selected_perms = [
            perm for perm, chk in self.perm_checkboxes.items() if chk.isChecked()
        ]

        self.result_data = {
            "username": username,
            "full_name": full_name or None,
            "role": role,
            "permissions": selected_perms,
        }

        if password:
            self.result_data["password"] = password

        if self.is_edit and hasattr(self, "chk_active"):
            self.result_data["is_active"] = self.chk_active.isChecked()

        self.accept()