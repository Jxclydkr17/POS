from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QHBoxLayout,
    QPushButton, QSpinBox, QDoubleSpinBox, QMessageBox
)

from app.utils.unit_helpers import is_unit_based, UNIT_LABELS


class EditCartItemDialog(QDialog):
    def __init__(self, product_name, quantity, unit_price, discount_percent, max_stock,
                 unit_type="Unid", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar producto del carrito")
        self.setModal(True)
        self.setMinimumWidth(360)

        self.unit_type = unit_type or "Unid"
        self._is_unit = is_unit_based(self.unit_type)

        layout = QVBoxLayout(self)

        title = QLabel(f"Editar: <b>{product_name}</b>")
        layout.addWidget(title)

        # 📏 Cantidad: QSpinBox para unidades, QDoubleSpinBox para granel
        if self._is_unit:
            self.max_stock = max(1, int(max_stock or 1))
            self.qty_input = QSpinBox()
            self.qty_input.setRange(1, self.max_stock)
            self.qty_input.setValue(max(1, int(quantity or 1)))
        else:
            self.max_stock = float(max_stock or 99999)
            unit_label = UNIT_LABELS.get(self.unit_type, self.unit_type)
            self.qty_input = QDoubleSpinBox()
            self.qty_input.setRange(0.001, self.max_stock)
            self.qty_input.setDecimals(3)
            self.qty_input.setSingleStep(0.5)
            self.qty_input.setSuffix(f" {unit_label}")
            self.qty_input.setValue(float(quantity or 1))

        self.price_input = QDoubleSpinBox()
        self.price_input.setRange(0.01, 999999999.99)
        self.price_input.setDecimals(2)
        self.price_input.setValue(float(unit_price or 0.01))

        # ✅ FASE 2.4: QDoubleSpinBox para soportar descuentos fraccionarios
        self.discount_input = QDoubleSpinBox()
        self.discount_input.setRange(0.0, 100.0)
        self.discount_input.setDecimals(2)
        self.discount_input.setSuffix(" %")
        self.discount_input.setValue(float(discount_percent or 0))

        unit_hint = "" if self._is_unit else f"  ({UNIT_LABELS.get(self.unit_type, self.unit_type)})"
        layout.addWidget(QLabel(f"Cantidad{unit_hint}:"))
        layout.addWidget(self.qty_input)

        layout.addWidget(QLabel("Precio unitario:"))
        layout.addWidget(self.price_input)

        layout.addWidget(QLabel("Descuento (%):"))
        layout.addWidget(self.discount_input)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancelar")
        btn_save = QPushButton("Guardar")

        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self.validate_and_accept)

        btns.addWidget(btn_cancel)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

    def validate_and_accept(self):
        if self.qty_input.value() < (1 if self._is_unit else 0.001):
            QMessageBox.warning(self, "Atención", "La cantidad debe ser mayor a 0.")
            return

        if self.price_input.value() <= 0:
            QMessageBox.warning(self, "Atención", "El precio debe ser mayor a 0.")
            return

        self.accept()

    def get_data(self):
        return {
            "quantity": self.qty_input.value(),
            "unit_price": self.price_input.value(),
            "discount_percent": self.discount_input.value(),     # ✅ FASE 2.4: float
        }