import requests
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt

from ui.session_manager import session
from ui.api import BASE_URL

API_SUPPLIERS = f"{BASE_URL}/suppliers"


class AddSupplierDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agregar proveedor")
        self.setModal(True)
        self.setFixedWidth(400)

        self.setup_ui()

    # --------------------------------------------------------
    # 🧠 INTERFAZ
    # --------------------------------------------------------
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)

        # Título
        title = QLabel("➕ Agregar proveedor")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px; color: #E0E0E0;")
        layout.addWidget(title)

        # Input: Nombre
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Nombre del proveedor")
        layout.addWidget(QLabel("Nombre:"))
        layout.addWidget(self.name_input)

        # Input: Teléfono
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Número de teléfono")
        layout.addWidget(QLabel("Teléfono:"))
        layout.addWidget(self.phone_input)

        # Input: Email
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Correo electrónico")
        layout.addWidget(QLabel("Email:"))
        layout.addWidget(self.email_input)

        # Input: Persona de contacto
        self.contact_name_input = QLineEdit()
        self.contact_name_input.setPlaceholderText("Nombre del contacto")
        layout.addWidget(QLabel("Contacto (nombre):"))
        layout.addWidget(self.contact_name_input)

        self.contact_phone_input = QLineEdit()
        self.contact_phone_input.setPlaceholderText("Teléfono del contacto")
        layout.addWidget(QLabel("Contacto (teléfono):"))
        layout.addWidget(self.contact_phone_input)

        self.contact_position_input = QLineEdit()
        self.contact_position_input.setPlaceholderText("Puesto / cargo")
        layout.addWidget(QLabel("Contacto (puesto):"))
        layout.addWidget(self.contact_position_input)

        # Input: Dirección
        self.address_input = QTextEdit()
        self.address_input.setPlaceholderText("Dirección")
        layout.addWidget(QLabel("Dirección:"))
        layout.addWidget(self.address_input)

        # Input: Notas
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Notas")
        layout.addWidget(QLabel("Notas:"))
        layout.addWidget(self.notes_input)

        # --------------------------------------------------------
        # Botones
        # --------------------------------------------------------
        btn_layout = QHBoxLayout()

        btn_save = QPushButton("Guardar")
        btn_save.clicked.connect(self.save_supplier)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)

        for btn in (btn_save, btn_cancel):
            btn.setStyleSheet("padding: 6px; font-size: 13px;")

        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

        self.setLayout(layout)

    # --------------------------------------------------------
    # 💾 Guardar proveedor (POST)
    # --------------------------------------------------------
    def save_supplier(self):
        name = self.name_input.text().strip()
        phone = self.phone_input.text().strip()
        email = self.email_input.text().strip()
        address = self.address_input.toPlainText().strip()
        notes = self.notes_input.toPlainText().strip()
        contact_name = self.contact_name_input.text().strip()
        contact_phone = self.contact_phone_input.text().strip()
        contact_position = self.contact_position_input.text().strip()

        # Validación mínima
        if not name:
            QMessageBox.warning(self, "Campos incompletos", "El nombre del proveedor es obligatorio.")
            return

        data = {
            "name": name,
            "phone": phone or None,
            "email": email or None,
            "address": address or None,
            "notes": notes or None,
            "contact_name": contact_name or None,
            "contact_phone": contact_phone or None,
            "contact_position": contact_position or None,
        }

        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            resp = requests.post(API_SUPPLIERS, json=data, headers=headers)

            if resp.status_code not in (200, 201):

                QMessageBox.warning(self, "Error", f"No se pudo crear el proveedor.\n{resp.text}")
                return

            QMessageBox.information(self, "Éxito", "Proveedor creado correctamente.")
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al crear proveedor:\n{e}")