from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QHBoxLayout, QTextEdit,
)
import requests
from ui.session_manager import session
from ui.dialogs.icon_picker_dialog import IconPickerDialog
from ui.api import BASE_URL

API_URL = f"{BASE_URL}/categories"


class AddCategoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agregar Categoría")
        self.selected_icon = "📦"
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Nombre de la categoría:"))
        self.input_name = QLineEdit()
        layout.addWidget(self.input_name)

        # Descripción (#11)
        layout.addWidget(QLabel("Descripción (opcional):"))
        self.input_description = QTextEdit()
        self.input_description.setPlaceholderText("Breve descripción de la categoría…")
        self.input_description.setMaximumHeight(70)
        layout.addWidget(self.input_description)

        # Ícono
        icon_layout = QHBoxLayout()
        self.icon_label = QLabel(self.selected_icon)
        self.icon_label.setStyleSheet("font-size: 28px;")
        icon_layout.addWidget(self.icon_label)

        btn_icon = QPushButton("Elegir ícono")
        btn_icon.clicked.connect(self.choose_icon)
        icon_layout.addWidget(btn_icon)

        layout.addLayout(icon_layout)

        btn = QPushButton("Guardar")
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
            "is_active": True,
        }

        desc = self.input_description.toPlainText().strip()
        if desc:
            payload["description"] = desc

        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            r = requests.post(API_URL, json=payload, headers=headers)

            if r.status_code != 200:
                msg = r.json().get("message", "Error desconocido")
                QMessageBox.critical(self, "Error", msg)
                return

            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))