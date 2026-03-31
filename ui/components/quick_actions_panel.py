from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QPushButton, QLabel
)
from PySide6.QtCore import Signal


class QuickActionsPanel(QFrame):

    action_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setStyleSheet("""
        QFrame{
            background-color:#1f2937;
            border-radius:16px;
            padding:12px;
        }

        QPushButton{
            background-color:#374151;
            border:none;
            border-radius:8px;
            padding:10px;
            text-align:left;
            font-size:13px;
        }

        QPushButton:hover{
            background-color:#4b5563;
        }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel("⚡ Acciones rápidas")
        title.setStyleSheet("""
        font-size:14px;
        font-weight:bold;
        """)
        layout.addWidget(title)

        actions = [
            ("🧾 Nueva venta", "new_sale"),
            ("📦 Registrar compra", "new_purchase"),
            ("⚠ Ver stock crítico", "critical_stock"),
            ("💳 Abrir créditos", "credits"),
            ("💰 Cerrar caja", "close_cash"),
            ("🔄 Refrescar dashboard", "refresh")
        ]

        for text, action in actions:
            btn = QPushButton(text)
            btn.clicked.connect(lambda _, a=action: self.action_clicked.emit(a))
            layout.addWidget(btn)

        layout.addStretch()