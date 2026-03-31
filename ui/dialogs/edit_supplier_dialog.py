import requests
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt

from ui.session_manager import session
from ui.api import BASE_URL

API_SUPPLIERS = f"{BASE_URL}/suppliers"


class EditSupplierDialog(QDialog):
    def __init__(self, parent, supplier_data):
        super().__init__(parent)
        self.supplier = supplier_data  # dict con los datos del proveedor
        self.setWindowTitle(f"Editar proveedor — {self.supplier['name']}")
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
        title = QLabel("✏️ Editar proveedor")
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold; margin-bottom: 10px; color: #E0E0E0;"
        )
        layout.addWidget(title)

        # Nombre
        layout.addWidget(QLabel("Nombre:"))
        self.name_input = QLineEdit(self.supplier.get("name", ""))
        layout.addWidget(self.name_input)

        # Teléfono
        layout.addWidget(QLabel("Teléfono:"))
        self.phone_input = QLineEdit(self.supplier.get("phone", "") or "")
        layout.addWidget(self.phone_input)

        # Email
        layout.addWidget(QLabel("Email:"))
        self.email_input = QLineEdit(self.supplier.get("email", "") or "")
        layout.addWidget(self.email_input)

        # Contacto
        layout.addWidget(QLabel("Contacto (nombre):"))
        self.contact_name_input = QLineEdit(self.supplier.get("contact_name", "") or "")
        layout.addWidget(self.contact_name_input)

        layout.addWidget(QLabel("Contacto (teléfono):"))
        self.contact_phone_input = QLineEdit(self.supplier.get("contact_phone", "") or "")
        layout.addWidget(self.contact_phone_input)

        layout.addWidget(QLabel("Contacto (puesto):"))
        self.contact_position_input = QLineEdit(self.supplier.get("contact_position", "") or "")
        layout.addWidget(self.contact_position_input)

        # Dirección
        layout.addWidget(QLabel("Dirección:"))
        self.address_input = QTextEdit()
        self.address_input.setPlainText(self.supplier.get("address", "") or "")
        layout.addWidget(self.address_input)

        # Notas
        layout.addWidget(QLabel("Notas:"))
        self.notes_input = QTextEdit()
        self.notes_input.setPlainText(self.supplier.get("notes", "") or "")
        layout.addWidget(self.notes_input)

        # Botones
        btn_layout = QHBoxLayout()

        btn_save = QPushButton("Guardar")
        btn_save.clicked.connect(self.update_supplier)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.clicked.connect(self.reject)

        for btn in (btn_save, btn_cancel):
            btn.setStyleSheet("padding: 6px; font-size: 13px;")

        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    # --------------------------------------------------------
    # 💾 Actualizar proveedor (PUT)
    # --------------------------------------------------------
    def update_supplier(self):
        name = self.name_input.text().strip()
        phone = self.phone_input.text().strip()
        email = self.email_input.text().strip()
        address = self.address_input.toPlainText().strip()
        notes = self.notes_input.toPlainText().strip()
        contact_name = self.contact_name_input.text().strip()
        contact_phone = self.contact_phone_input.text().strip()
        contact_position = self.contact_position_input.text().strip()

        if not name:
            QMessageBox.warning(self, "Error", "El nombre del proveedor es obligatorio.")
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
            url = f"{API_SUPPLIERS}/{self.supplier['id']}"
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}

            resp = requests.put(url, json=data, headers=headers)

            if resp.status_code not in (200, 201):

                QMessageBox.warning(self, "Error", f"No se pudo actualizar el proveedor.\n{resp.text}")
                return

            QMessageBox.information(self, "Éxito", "Proveedor actualizado correctamente.")
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al actualizar proveedor:\n{e}")