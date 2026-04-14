# ui/views/customer_profile_view.py
"""
customer_profile_view.py
Perfil completo del cliente: datos, estadísticas, historial, crédito, notas.

FASE 1 — Fix 1.1 / 1.2: Carga asíncrona.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFrame, QGridLayout,
    QMessageBox, QTextEdit, QHeaderView, QScrollArea, QWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from ui.session_manager import session
from ui.api import BASE_URL
from ui.utils.http_worker import api_call

API_URL = f"{BASE_URL}/customers"


class CustomerProfileView(QDialog):
    def __init__(self, customer_id, parent=None):
        super().__init__(parent)
        self.customer_id = customer_id
        self.setWindowTitle("Perfil del Cliente")
        self.resize(900, 680)
        self.setModal(True)
        self.setStyleSheet("background-color: #1a1a1a; color: #E8E8E8;")

        self.setup_ui()
        self.load_profile()

    def _auth(self):
        return {"Authorization": f"Bearer {session.token}"}

    def setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # ── Título ──
        self.lbl_title = QLabel("Perfil del Cliente")
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #E8E8E8;")
        main_layout.addWidget(self.lbl_title)

        # ── Scroll area ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(10)

        # ── Panel de datos de contacto ──
        contact_frame = self._card("📋 Datos de Contacto")
        contact_grid = QGridLayout()
        self.lbl_name = QLabel("-")
        self.lbl_id = QLabel("-")
        self.lbl_email = QLabel("-")
        self.lbl_phone = QLabel("-")
        self.lbl_phone2 = QLabel("-")
        self.lbl_type = QLabel("-")
        self.lbl_location = QLabel("-")
        self.lbl_created = QLabel("-")
        self.lbl_active = QLabel("-")
        self.lbl_birth = QLabel("-")

        fields = [
            ("Nombre:", self.lbl_name, "Tipo:", self.lbl_type),
            ("Identificación:", self.lbl_id, "Estado:", self.lbl_active),
            ("Correo:", self.lbl_email, "Ubicación:", self.lbl_location),
            ("Teléfono:", self.lbl_phone, "Registrado:", self.lbl_created),
            ("Tel. Sec.:", self.lbl_phone2, "Nacimiento:", self.lbl_birth),
        ]
        for i, (l1, w1, l2, w2) in enumerate(fields):
            lbl1 = QLabel(l1); lbl1.setStyleSheet("color: #888; font-size: 12px;")
            lbl2 = QLabel(l2); lbl2.setStyleSheet("color: #888; font-size: 12px;")
            w1.setStyleSheet("font-size: 13px;")
            w2.setStyleSheet("font-size: 13px;")
            contact_grid.addWidget(lbl1, i, 0); contact_grid.addWidget(w1, i, 1)
            contact_grid.addWidget(lbl2, i, 2); contact_grid.addWidget(w2, i, 3)

        contact_frame.layout().addLayout(contact_grid)
        layout.addWidget(contact_frame)

        # ── Panel de estadísticas ──
        stats_frame = self._card("📊 Estadísticas de Compra")
        stats_grid = QGridLayout()
        self.lbl_total_sales = QLabel("-")
        self.lbl_total_amount = QLabel("-")
        self.lbl_avg_ticket = QLabel("-")
        self.lbl_frequency = QLabel("-")
        self.lbl_first_sale = QLabel("-")
        self.lbl_last_sale = QLabel("-")

        stat_fields = [
            ("Total compras:", self.lbl_total_sales, "Monto total:", self.lbl_total_amount),
            ("Ticket promedio:", self.lbl_avg_ticket, "Frecuencia/mes:", self.lbl_frequency),
            ("Primera compra:", self.lbl_first_sale, "Última compra:", self.lbl_last_sale),
        ]
        for i, (l1, w1, l2, w2) in enumerate(stat_fields):
            lbl1 = QLabel(l1); lbl1.setStyleSheet("color: #888; font-size: 12px;")
            lbl2 = QLabel(l2); lbl2.setStyleSheet("color: #888; font-size: 12px;")
            w1.setStyleSheet("font-size: 14px; font-weight: bold;")
            w2.setStyleSheet("font-size: 14px; font-weight: bold;")
            stats_grid.addWidget(lbl1, i, 0); stats_grid.addWidget(w1, i, 1)
            stats_grid.addWidget(lbl2, i, 2); stats_grid.addWidget(w2, i, 3)

        stats_frame.layout().addLayout(stats_grid)
        layout.addWidget(stats_frame)

        # ── Panel de crédito ──
        credit_frame = self._card("💳 Crédito")
        credit_grid = QGridLayout()
        self.lbl_balance = QLabel("-")
        self.lbl_limit = QLabel("-")
        self.lbl_last_pay = QLabel("-")
        self.lbl_last_pay_amt = QLabel("-")

        cr_fields = [
            ("Saldo:", self.lbl_balance, "Límite:", self.lbl_limit),
            ("Último abono:", self.lbl_last_pay, "Monto abono:", self.lbl_last_pay_amt),
        ]
        for i, (l1, w1, l2, w2) in enumerate(cr_fields):
            lbl1 = QLabel(l1); lbl1.setStyleSheet("color: #888; font-size: 12px;")
            lbl2 = QLabel(l2); lbl2.setStyleSheet("color: #888; font-size: 12px;")
            w1.setStyleSheet("font-size: 14px; font-weight: bold;")
            w2.setStyleSheet("font-size: 14px; font-weight: bold;")
            credit_grid.addWidget(lbl1, i, 0); credit_grid.addWidget(w1, i, 1)
            credit_grid.addWidget(lbl2, i, 2); credit_grid.addWidget(w2, i, 3)

        credit_frame.layout().addLayout(credit_grid)
        layout.addWidget(credit_frame)

        # ── Notas internas ──
        notes_frame = self._card("📝 Notas Internas")
        self.txt_notes = QTextEdit()
        self.txt_notes.setReadOnly(True)
        self.txt_notes.setMaximumHeight(80)
        self.txt_notes.setStyleSheet("background-color: #2a2a2a; border: 1px solid #444; border-radius: 4px; padding: 4px;")
        notes_frame.layout().addWidget(self.txt_notes)
        layout.addWidget(notes_frame)

        # ── Últimas compras ──
        sales_frame = self._card("🛒 Últimas Compras")
        self.sales_table = QTableWidget()
        self.sales_table.setColumnCount(4)
        self.sales_table.setHorizontalHeaderLabels(["ID", "Total", "Método", "Fecha"])
        self.sales_table.horizontalHeader().setStretchLastSection(True)
        self.sales_table.setStyleSheet("""
            QTableWidget { background-color: #2a2a2a; color: #E8E8E8; gridline-color: #3d3d3d; font-size: 12px; }
            QHeaderView::section { background-color: #333; color: #E8E8E8; padding: 4px; font-weight: bold; border: none; }
        """)
        self.sales_table.setMaximumHeight(200)
        sales_frame.layout().addWidget(self.sales_table)
        layout.addWidget(sales_frame)

        layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # ── Botones ──
        btn_layout = QHBoxLayout()
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.close)
        btn_close.setStyleSheet("background-color: #444; color: white; padding: 8px 20px; border-radius: 6px;")
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)

    def _card(self, title):
        frame = QFrame()
        frame.setStyleSheet("QFrame { background-color: #222; border-radius: 8px; padding: 10px; }")
        vl = QVBoxLayout(frame)
        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #60a5fa; margin-bottom: 4px;")
        vl.addWidget(lbl)
        return frame

    # ─────────────────────────────────────────────────────
    # FASE 1 — Fix 1.1: Carga asíncrona del perfil
    # ─────────────────────────────────────────────────────
    def load_profile(self):
        """Lanza la carga del perfil en background."""
        api_call(
            "get", f"{API_URL}/{self.customer_id}/profile",
            headers=self._auth(),
            on_success=self._on_profile_loaded,
            on_error=self._on_profile_error,
        )

    def _on_profile_loaded(self, response):
        """Callback: perfil recibido — poblar todos los paneles."""
        data = response.get("data", {}) if isinstance(response, dict) else {}
        cust = data.get("customer", {})
        stats = data.get("stats", {})
        credit = data.get("credit", {})
        sales = data.get("recent_sales", [])

        self.lbl_title.setText(f"Perfil: {cust.get('name', '')}")
        self.lbl_name.setText(cust.get("name", "-"))
        self.lbl_id.setText(f"{cust.get('id_type', '')} - {cust.get('id_number', '')}")
        self.lbl_email.setText(cust.get("email") or "N/A")
        self.lbl_phone.setText(cust.get("phone") or "N/A")
        self.lbl_phone2.setText(cust.get("secondary_phone") or "N/A")
        self.lbl_type.setText(cust.get("customer_type") or "Normal")
        loc = f"{cust.get('province_name', '')} - {cust.get('canton_name', '')}"
        self.lbl_location.setText(loc if cust.get("province_name") else "N/A")
        self.lbl_created.setText(cust.get("created_at") or "N/A")
        self.lbl_active.setText("✅ Activo" if cust.get("is_active") else "❌ Inactivo")
        self.lbl_birth.setText(cust.get("birth_date") or "N/A")
        self.txt_notes.setPlainText(cust.get("notes") or "(Sin notas)")

        self.lbl_total_sales.setText(str(stats.get("total_sales", 0)))
        self.lbl_total_amount.setText(f"₡{stats.get('total_amount', 0):,.2f}")
        self.lbl_avg_ticket.setText(f"₡{stats.get('avg_ticket', 0):,.2f}")
        self.lbl_frequency.setText(str(stats.get("frequency_per_month", 0)))
        self.lbl_first_sale.setText(stats.get("first_sale_date") or "N/A")
        self.lbl_last_sale.setText(stats.get("last_sale_date") or "N/A")

        bal = credit.get("balance", 0)
        self.lbl_balance.setText(f"₡{bal:,.2f}")
        self.lbl_balance.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {'#ef4444' if bal > 0 else '#22c55e'};")
        if credit.get("has_limit"):
            self.lbl_limit.setText(f"₡{credit.get('limit', 0):,.2f}")
        else:
            self.lbl_limit.setText("Ilimitado")
        self.lbl_last_pay.setText(credit.get("last_payment_date") or "N/A")
        if credit.get("last_payment_amount"):
            self.lbl_last_pay_amt.setText(f"₡{credit['last_payment_amount']:,.2f}")
        else:
            self.lbl_last_pay_amt.setText("N/A")

        self.sales_table.setRowCount(len(sales))
        for i, s in enumerate(sales):
            self.sales_table.setItem(i, 0, QTableWidgetItem(str(s["id"])))
            self.sales_table.setItem(i, 1, QTableWidgetItem(f"₡{s['total']:,.2f}"))
            self.sales_table.setItem(i, 2, QTableWidgetItem(s["payment_method"]))
            self.sales_table.setItem(i, 3, QTableWidgetItem(s["date"]))

    def _on_profile_error(self, msg):
        """Callback: error al cargar perfil."""
        QMessageBox.critical(self, "Error", f"Error cargando perfil:\n{msg}")