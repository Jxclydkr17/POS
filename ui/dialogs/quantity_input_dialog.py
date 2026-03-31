# ui/dialogs/quantity_input_dialog.py
"""
📏 Diálogo para ingresar cantidad decimal (kg, m, L).
Se abre al hacer clic en un producto a granel en el POS.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QDoubleSpinBox, QFrame
)
from PySide6.QtCore import Qt

from app.utils.unit_helpers import UNIT_LABELS


class QuantityInputDialog(QDialog):
    def __init__(self, product_name, unit_type, max_stock, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📏 Cantidad")
        self.setModal(True)
        self.setFixedWidth(380)
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
            QLabel#unit_label {
                color: #38bdf8;
                font-size: 12px;
                font-weight: bold;
            }
            QDoubleSpinBox {
                background-color: #1e293b;
                color: #f1f5f9;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 10px 12px;
                font-size: 20px;
                font-weight: bold;
            }
            QDoubleSpinBox:focus {
                border-color: #3b82f6;
            }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                background-color: #334155;
                border: none;
                width: 24px;
            }
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
                background-color: #475569;
            }
        """)

        unit_label_text = UNIT_LABELS.get(unit_type, unit_type)
        max_stock_float = float(max_stock) if max_stock else 99999.0

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        # Título
        title = QLabel(f"{product_name}")
        title.setObjectName("title_label")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        layout.addWidget(title)

        unit_info = QLabel(f"Se vende por {unit_label_text}  ·  Disponible: {max_stock_float:.3g} {unit_label_text}")
        unit_info.setObjectName("unit_label")
        unit_info.setAlignment(Qt.AlignCenter)
        layout.addWidget(unit_info)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #1e293b;")
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # Cantidad input
        layout.addWidget(QLabel("Cantidad:"))
        self.qty_input = QDoubleSpinBox()
        self.qty_input.setRange(0.001, max_stock_float)
        self.qty_input.setDecimals(3)
        self.qty_input.setValue(1.0)
        self.qty_input.setSingleStep(0.5)
        self.qty_input.setSuffix(f" {unit_label_text}")
        self.qty_input.setFixedHeight(48)
        layout.addWidget(self.qty_input)

        # Botones rápidos
        quick_layout = QHBoxLayout()
        quick_layout.setSpacing(6)

        quick_values = [0.25, 0.5, 1.0, 2.0, 5.0]
        quick_btn_style = """
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 8px 4px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #f1f5f9;
                border-color: #3b82f6;
            }
        """

        for val in quick_values:
            # Formatear: 0.25 → "¼", 0.5 → "½", 1.0 → "1", etc.
            if val == 0.25:
                label = "¼"
            elif val == 0.5:
                label = "½"
            else:
                label = str(int(val)) if val == int(val) else str(val)

            btn = QPushButton(f"{label} {unit_label_text}")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(36)
            btn.setStyleSheet(quick_btn_style)
            btn.clicked.connect(lambda checked=False, v=val: self.qty_input.setValue(v))
            quick_layout.addWidget(btn)

        layout.addLayout(quick_layout)

        # Botones OK / Cancelar
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("✕  Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setFixedHeight(38)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #374151;
                color: #e2e8f0;
                border: 1px solid #4b5563;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #4b5563; }
        """)
        btn_cancel.clicked.connect(self.reject)

        btn_accept = QPushButton("✔  Agregar al carrito")
        btn_accept.setCursor(Qt.PointingHandCursor)
        btn_accept.setFixedHeight(38)
        btn_accept.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        btn_accept.clicked.connect(self.accept)

        btn_layout.addWidget(btn_cancel, 1)
        btn_layout.addWidget(btn_accept, 2)
        layout.addLayout(btn_layout)

        # Focus en el input
        self.qty_input.setFocus()
        self.qty_input.selectAll()

    def get_quantity(self) -> float:
        return self.qty_input.value()