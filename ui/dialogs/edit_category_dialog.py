from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QHBoxLayout, QTextEdit,
)
from ui.session_manager import session
from ui.utils.http_worker import api_call
from ui.dialogs.icon_picker_dialog import IconPickerDialog
from ui.api import BASE_URL

API_URL = f"{BASE_URL}/categories"


class EditCategoryDialog(QDialog):
    def __init__(self, cat_id, name, icon="📦", description="", parent=None):
        super().__init__(parent)
        self.cat_id = cat_id
        self.selected_icon = icon or "📦"
        self.setWindowTitle("Editar Categoría")
        self.setup_ui(name, description)

    def setup_ui(self, name, description):
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Nuevo nombre:"))
        self.input_name = QLineEdit(name)
        layout.addWidget(self.input_name)

        # Descripción (#11)
        layout.addWidget(QLabel("Descripción (opcional):"))
        self.input_description = QTextEdit()
        self.input_description.setPlaceholderText("Breve descripción de la categoría…")
        self.input_description.setMaximumHeight(70)
        if description:
            self.input_description.setPlainText(description)
        layout.addWidget(self.input_description)

        # Ícono
        icon_layout = QHBoxLayout()
        self.icon_label = QLabel(self.selected_icon)
        self.icon_label.setStyleSheet("font-size: 28px;")
        icon_layout.addWidget(self.icon_label)

        btn_icon = QPushButton("Cambiar ícono")
        btn_icon.clicked.connect(self.choose_icon)
        icon_layout.addWidget(btn_icon)

        layout.addLayout(icon_layout)

        btn = QPushButton("Guardar cambios")
        btn.clicked.connect(self.save)
        layout.addWidget(btn)

        self.setLayout(layout)

    def choose_icon(self):
        dialog = IconPickerDialog(self)
        if dialog.exec():
            if dialog.selected_icon:
                self.selected_icon = dialog.selected_icon
                self.icon_label.setText(self.selected_icon)

    def save(self):
        name = self.input_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Atención", "El nombre no puede estar vacío.")
            return

        payload = {
            "name": name,
            "icon": self.selected_icon,
        }

        desc = self.input_description.toPlainText().strip()
        # Enviar description siempre (puede ser vacío para borrar)
        payload["description"] = desc if desc else None

        headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
        api_call(
            "put", f"{API_URL}/{self.cat_id}", json=payload, headers=headers,
            on_success=lambda data: self.accept(),
            on_error=lambda msg: QMessageBox.critical(self, "Error", msg),
        )