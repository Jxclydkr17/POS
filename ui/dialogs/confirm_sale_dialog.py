# ui/dialogs/confirm_sale_dialog.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame
)
from PySide6.QtCore import QTimer


class ConfirmSaleDialog(QDialog):
    """
    Diálogo de confirmación de venta:
    - Muestra resumen (cliente, pago, items, totales)
    - Permite:
        ✅ Confirmar e imprimir ticket
        ✅ Confirmar sin imprimir
        ❌ Cancelar
    """
    def __init__(self, parent=None, *, customer_name: str, payment_method: str, items: list, totals: dict, auto_action: str | None = None):
        """
        items: list[dict] con llaves: name, qty, unit_price, subtotal
        totals: dict con llaves: subtotal, discount, iva, total, received, change (las que tengas)
        """
        super().__init__(parent)
        self.setWindowTitle("Confirmar venta")
        self.setModal(True)
        self.setMinimumWidth(720)

        self.print_ticket = False
        # auto_action: None | 'cancel' | 'no_print' | 'print'
        self._auto_action = (auto_action or '').strip().lower() or None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Header
        header = QLabel("🧾 Confirmación de venta")
        header.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(header)

        meta = QLabel(f"<b>Cliente:</b> {customer_name} &nbsp;&nbsp; | &nbsp;&nbsp; <b>Pago:</b> {payment_method}")
        meta.setStyleSheet("color: #cbd5e1;")
        root.addWidget(meta)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #1f2937;")
        root.addWidget(line)

        # Tabla items
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Producto", "Cant.", "Precio", "Desc.", "Subtotal"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        table.setStyleSheet("""
            QTableWidget { background-color: #0b1220; border: 1px solid #1f2937; border-radius: 10px; }
            QHeaderView::section { background-color: #111827; color: #e5e7eb; padding: 6px; border: 0; }
            QTableWidget::item { padding: 6px; }
        """)

        table.setRowCount(len(items))
        for r, it in enumerate(items):
            table.setItem(r, 0, QTableWidgetItem(str(it.get("name", ""))))
            table.setItem(r, 1, QTableWidgetItem(str(it.get("qty", 0))))
            table.setItem(r, 2, QTableWidgetItem(f"{float(it.get('unit_price', 0)):.2f}"))
            table.setItem(r, 3, QTableWidgetItem(str(it.get("discount_percent", 0)) + "%"))
            table.setItem(r, 4, QTableWidgetItem(f"{float(it.get('subtotal', 0)):.2f}"))

        root.addWidget(table)

        # Totales (simple)
        def money(v):
            try:
                return f"₡{float(v):,.2f}"
            except Exception:
                return "₡0.00"

        totals_box = QFrame()
        totals_box.setStyleSheet("""
            QFrame { background-color: #0b1220; border: 1px solid #1f2937; border-radius: 10px; padding: 10px; }
            QLabel { color: #e5e7eb; }
        """)
        tb = QVBoxLayout(totals_box)
        tb.setSpacing(6)

        tb.addWidget(QLabel(f"Subtotal: <b>{money(totals.get('subtotal', 0))}</b>"))
        tb.addWidget(QLabel(f"Descuento: <b>{money(totals.get('discount', 0))}</b>"))
        tb.addWidget(QLabel(f"IVA: <b>{money(totals.get('iva', 0))}</b>"))
        tb.addWidget(QLabel(f"Total: <b>{money(totals.get('total', 0))}</b>"))

        # Opcional: si querés mostrar recibido/cambio cuando es efectivo
        if totals.get("received") is not None:
            tb.addWidget(QLabel(f"Recibido: <b>{money(totals.get('received', 0))}</b>"))
        if totals.get("change") is not None:
            tb.addWidget(QLabel(f"Cambio: <b>{money(totals.get('change', 0))}</b>"))

        root.addWidget(totals_box)

        # Botones
        btns = QHBoxLayout()
        btns.setSpacing(10)

        self.btn_cancel = QPushButton("❌ Cancelar")
        self.btn_confirm_no_print = QPushButton("✅ Confirmar (sin imprimir)")
        self.btn_confirm_print = QPushButton("🖨 Confirmar e imprimir")

        # Object names (útil para automatización / tests)
        self.btn_cancel.setObjectName('btn_cancel')
        self.btn_confirm_no_print.setObjectName('btn_confirm_no_print')
        self.btn_confirm_print.setObjectName('btn_confirm_print')

        self.btn_confirm_print.setStyleSheet(
            "QPushButton { background-color: #16a34a; color: white; padding: 8px 14px; font-weight: 700; border-radius: 8px; }"
            "QPushButton:hover { background-color: #15803d; }"
        )
        self.btn_confirm_no_print.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; padding: 8px 14px; font-weight: 700; border-radius: 8px; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.btn_cancel.setStyleSheet(
            "QPushButton { background-color: #334155; color: white; padding: 8px 14px; border-radius: 8px; }"
            "QPushButton:hover { background-color: #475569; }"
        )

        btns.addWidget(self.btn_cancel)
        btns.addStretch()
        btns.addWidget(self.btn_confirm_no_print)
        btns.addWidget(self.btn_confirm_print)

        root.addLayout(btns)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_confirm_no_print.clicked.connect(self._confirm_no_print)
        self.btn_confirm_print.clicked.connect(self._confirm_print)

        # Si se pidió auto_action, disparamos el botón al abrir (funciona incluso con exec()).
        if self._auto_action in {'cancel', 'no_print', 'print'}:
            QTimer.singleShot(0, lambda: self.trigger_action(self._auto_action))

        # fondo general
        self.setStyleSheet("""
            QDialog { background-color: #080d1a; }
        """)

    def trigger_action(self, action: str) -> None:
        """Dispara una acción del diálogo de forma programática.

        action: 'cancel' | 'no_print' | 'print'
        """
        a = (action or '').strip().lower()
        if a == 'cancel':
            self.btn_cancel.click()
        elif a == 'no_print':
            self.btn_confirm_no_print.click()
        elif a == 'print':
            self.btn_confirm_print.click()

    def confirm_no_print(self) -> None:
        self.trigger_action('no_print')

    def confirm_print(self) -> None:
        self.trigger_action('print')

    def cancel(self) -> None:
        self.trigger_action('cancel')

    def _confirm_no_print(self):
        self.print_ticket = False
        self.accept()

    def _confirm_print(self):
        self.print_ticket = True
        self.accept()