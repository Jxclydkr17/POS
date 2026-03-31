# ui/dialogs/common_product_dialog.py
"""
Diálogo para agregar un "Producto Común" al carrito.
No toca inventario — solo pide descripción, cantidad y precio.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QMessageBox, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator


class CommonProductDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📦 Producto Común")
        self.setModal(True)
        self.setMinimumWidth(400)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #e2e8f0;
            }
            QLabel {
                color: #cbd5e1;
                font-size: 13px;
            }
            QLabel#title_label {
                color: #f1f5f9;
                font-size: 16px;
                font-weight: bold;
            }
            QLineEdit, QSpinBox {
                background-color: #1e293b;
                color: #f1f5f9;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 14px;
            }
            QLineEdit:focus, QSpinBox:focus {
                border-color: #3b82f6;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #334155;
                border: none;
                width: 20px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #475569;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # ─── Título ───
        title = QLabel("PRODUCTO COMÚN")
        title.setObjectName("title_label")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Producto sin inventario — no descuenta stock")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #64748b; font-size: 11px; margin-bottom: 6px;")
        layout.addWidget(subtitle)

        # ─── Separador ───
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #1e293b;")
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # ─── Descripción ───
        layout.addWidget(QLabel("Descripción del Producto:"))
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Ej: Servicio de corte, Artículo especial...")
        self.desc_input.setMaxLength(200)
        layout.addWidget(self.desc_input)

        # ─── Cantidad y Precio (horizontal) ───
        row_layout = QHBoxLayout()
        row_layout.setSpacing(12)

        # Cantidad
        qty_col = QVBoxLayout()
        qty_col.addWidget(QLabel("Cantidad:"))
        self.qty_input = QSpinBox()
        self.qty_input.setRange(1, 9999)
        self.qty_input.setValue(1)
        self.qty_input.setFixedHeight(36)
        qty_col.addWidget(self.qty_input)
        row_layout.addLayout(qty_col, 1)

        # Precio
        price_col = QVBoxLayout()
        price_col.addWidget(QLabel("Precio unitario:"))
        self.price_input = QLineEdit()
        self.price_input.setPlaceholderText("0.00")
        self.price_input.setValidator(QDoubleValidator(0.01, 999999999.99, 2))
        self.price_input.setFixedHeight(36)
        price_col.addWidget(self.price_input)
        row_layout.addLayout(price_col, 2)

        layout.addLayout(row_layout)

        # ─── Botones ───
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("✕  Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #374151;
                color: #e2e8f0;
                border: 1px solid #4b5563;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        btn_cancel.clicked.connect(self.reject)

        btn_accept = QPushButton("✔  Aceptar")
        btn_accept.setCursor(Qt.PointingHandCursor)
        btn_accept.setFixedHeight(36)
        btn_accept.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        btn_accept.clicked.connect(self.validate_and_accept)

        btn_layout.addWidget(btn_cancel, 1)
        btn_layout.addWidget(btn_accept, 1)
        layout.addLayout(btn_layout)

        # Focus inicial en descripción
        self.desc_input.setFocus()

    def validate_and_accept(self):
        desc = self.desc_input.text().strip()
        if not desc:
            QMessageBox.warning(self, "Campo requerido", "Debes ingresar una descripción.")
            self.desc_input.setFocus()
            return

        price_text = self.price_input.text().strip().replace(",", ".")
        if not price_text:
            QMessageBox.warning(self, "Campo requerido", "Debes ingresar el precio.")
            self.price_input.setFocus()
            return

        try:
            price = float(price_text)
            if price <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Precio inválido", "El precio debe ser mayor a 0.")
            self.price_input.setFocus()
            return

        self.accept()

    def get_data(self) -> dict:
        """Retorna los datos del producto común."""
        price_text = self.price_input.text().strip().replace(",", ".")
        return {
            "description": self.desc_input.text().strip(),
            "quantity": self.qty_input.value(),
            "price": float(price_text),
        }