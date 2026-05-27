# ui/views/customer_credit_view.py
"""
FASE 1 — Fix 1.1 / 1.2: Carga asíncrona + timeout en acciones.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QTableWidget, QTableWidgetItem, QInputDialog,
    QComboBox, QDialog, QFormLayout, QLineEdit, QCheckBox,
    QProgressBar, QFrame, QDateEdit, QGroupBox, QGridLayout,
    QFileDialog, QSizePolicy
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor
import subprocess
import sys
import os
from datetime import datetime, date
from ui.session_manager import session
from ui.api import BASE_URL
from ui.utils.http_worker import api_call, run_async
from app.core.config import get_pdf_dir

API_URL = BASE_URL


class PaymentDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar Abono")
        self.resize(420, 190)
        layout = QFormLayout()
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("Ingrese el monto")
        layout.addRow("Monto del abono:", self.amount_input)
        self.payment_method_combo = QComboBox()
        self.payment_method_combo.addItems(["Efectivo", "Tarjeta", "Transferencia", "SINPE"])
        layout.addRow("Método de pago:", self.payment_method_combo)
        self.chk_rep = QCheckBox("Generar REP automáticamente (FIFO real)")
        self.chk_rep.setChecked(True)
        layout.addRow("", self.chk_rep)
        btn_layout = QHBoxLayout()
        self.btn_accept = QPushButton("Aceptar")
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_accept.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_accept)
        btn_layout.addWidget(self.btn_cancel)
        layout.addRow(btn_layout)
        self.setLayout(layout)

    def get_values(self):
        try:
            amount = float(self.amount_input.text() or 0)
            return amount, self.payment_method_combo.currentText(), self.chk_rep.isChecked()
        except ValueError:
            return None, None, False


_TABLE_STYLE = """
    QTableWidget { background-color: #2d2d2d; color: #E8E8E8; gridline-color: #3d3d3d; selection-background-color: #dc2626; selection-color: white; outline: 0; font-size: 13px; }
    QTableWidget::item { border: none; padding: 4px; }
    QTableWidget::item:selected { background-color: #dc2626; color: white; }
    QHeaderView::section { background-color: #3d3d3d; color: #E8E8E8; padding: 5px; font-weight: bold; border: none; }
"""
_CHECKBOX_STYLE = """
    QTableWidget::indicator { width: 18px; height: 18px; border: 2px solid #888; border-radius: 3px; background-color: #1e1e1e; }
    QTableWidget::indicator:checked { background-color: #22c55e; border-color: #16a34a; image: none; }
    QTableWidget::indicator:unchecked { background-color: #1e1e1e; border-color: #888; }
"""


class CustomerCreditView(QDialog):
    def __init__(self, customer_id, customer_name, parent=None):
        super().__init__(parent)
        self.customer_id = customer_id
        self.customer_name = customer_name
        self.credit_id = None
        self._last_data = None
        self._mov_page = 0
        self._mov_page_size = 20

        self.setWindowTitle(f"💳 Crédito de {customer_name}")
        self.resize(920, 700)
        self.setModal(True)

        self.setup_ui()
        self.load_credit_info()

    def _auth(self):
        return {"Authorization": f"Bearer {session.token}"}

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel(f"💳 Crédito del cliente: {self.customer_name}")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #E8E8E8; margin-bottom: 6px;")
        layout.addWidget(title)

        # Summary frame
        summary_frame = QFrame()
        summary_frame.setStyleSheet("QFrame { background-color: #1e1e1e; border-radius: 8px; padding: 8px; }")
        summary_layout = QGridLayout(summary_frame)
        summary_layout.setSpacing(8)

        self.lbl_balance = QLabel("Saldo: ₡0.00")
        self.lbl_balance.setStyleSheet("font-size: 18px; font-weight: bold; color: #ef4444;")
        summary_layout.addWidget(self.lbl_balance, 0, 0, 1, 2)

        self.lbl_limit = QLabel("Límite: Ilimitado")
        self.lbl_limit.setStyleSheet("font-size: 13px; color: #ccc;")
        summary_layout.addWidget(self.lbl_limit, 0, 2, 1, 1)

        self.lbl_paid_month = QLabel("Abonado este mes: ₡0.00")
        self.lbl_paid_month.setStyleSheet("font-size: 13px; color: #22c55e;")
        summary_layout.addWidget(self.lbl_paid_month, 0, 3, 1, 1)

        self.progress_limit = QProgressBar()
        self.progress_limit.setRange(0, 100); self.progress_limit.setValue(0)
        self.progress_limit.setTextVisible(True); self.progress_limit.setFormat("Uso: %p%")
        self.progress_limit.setFixedHeight(20)
        self.progress_limit.setStyleSheet("QProgressBar{background-color:#333;border-radius:4px;text-align:center;color:white;font-size:11px;}QProgressBar::chunk{background-color:#3b82f6;border-radius:4px;}")
        summary_layout.addWidget(QLabel("Uso del límite:"), 1, 0)
        summary_layout.addWidget(self.progress_limit, 1, 1, 1, 3)

        aging_lbl = QLabel("Antigüedad de deuda:")
        aging_lbl.setStyleSheet("font-size: 12px; color: #aaa; margin-top: 4px;")
        summary_layout.addWidget(aging_lbl, 2, 0, 1, 4)

        self.lbl_aging_0_30 = self._aging_box("0-30 días", "#3b82f6")
        self.lbl_aging_31_60 = self._aging_box("31-60 días", "#f59e0b")
        self.lbl_aging_61_90 = self._aging_box("61-90 días", "#f97316")
        self.lbl_aging_90_plus = self._aging_box("+90 días", "#ef4444")
        summary_layout.addWidget(self.lbl_aging_0_30, 3, 0)
        summary_layout.addWidget(self.lbl_aging_31_60, 3, 1)
        summary_layout.addWidget(self.lbl_aging_61_90, 3, 2)
        summary_layout.addWidget(self.lbl_aging_90_plus, 3, 3)
        layout.addWidget(summary_frame)

        # Action buttons
        btn_layout = QHBoxLayout()
        self.btn_view_sale = QPushButton("🧾 Ver ticket")
        self.btn_add_payment = QPushButton("💵 Registrar abono")
        self.btn_export_pdf = QPushButton("📄 Exportar PDF")
        self.btn_refresh = QPushButton("🔄 Actualizar")
        for btn, color in [(self.btn_view_sale, "#6b7280"), (self.btn_add_payment, "#28A745"), (self.btn_export_pdf, "#8b5cf6"), (self.btn_refresh, "#17A2B8")]:
            btn.setStyleSheet(f"QPushButton{{background-color:{color};color:white;font-weight:bold;padding:7px;border-radius:6px;min-width:130px;}}QPushButton:hover{{opacity:0.9;}}")
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)

        # Date filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Desde:"))
        self.date_from = QDateEdit(); self.date_from.setCalendarPopup(True); self.date_from.setDisplayFormat("dd/MM/yyyy"); self.date_from.setDate(QDate.currentDate().addMonths(-3))
        filter_layout.addWidget(self.date_from)
        filter_layout.addWidget(QLabel("Hasta:"))
        self.date_to = QDateEdit(); self.date_to.setCalendarPopup(True); self.date_to.setDisplayFormat("dd/MM/yyyy"); self.date_to.setDate(QDate.currentDate())
        filter_layout.addWidget(self.date_to)
        self.btn_filter = QPushButton("Filtrar"); self.btn_filter.clicked.connect(self._apply_date_filter); self.btn_filter.setStyleSheet("background-color:#555;color:white;padding:5px 12px;border-radius:4px;")
        filter_layout.addWidget(self.btn_filter)
        self.btn_clear_filter = QPushButton("Limpiar"); self.btn_clear_filter.clicked.connect(self._clear_date_filter); self.btn_clear_filter.setStyleSheet("background-color:#444;color:#ccc;padding:5px 12px;border-radius:4px;")
        filter_layout.addWidget(self.btn_clear_filter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Movements table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "Tipo", "Método", "Monto", "Fecha"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setColumnWidth(0, 50); self.table.setColumnWidth(1, 120); self.table.setColumnWidth(2, 120); self.table.setColumnWidth(3, 130)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setStyleSheet(_TABLE_STYLE)
        layout.addWidget(self.table)

        # Movements pagination
        pag_layout = QHBoxLayout()
        self.btn_mov_prev = QPushButton("◀"); self.btn_mov_prev.clicked.connect(self._mov_prev); self.btn_mov_prev.setStyleSheet("background-color:#444;color:white;padding:4px 10px;border-radius:4px;")
        self.lbl_mov_page = QLabel("—"); self.lbl_mov_page.setAlignment(Qt.AlignCenter); self.lbl_mov_page.setStyleSheet("color:#ccc;font-size:12px;min-width:120px;")
        self.btn_mov_next = QPushButton("▶"); self.btn_mov_next.clicked.connect(self._mov_next); self.btn_mov_next.setStyleSheet("background-color:#444;color:white;padding:4px 10px;border-radius:4px;")
        pag_layout.addStretch(); pag_layout.addWidget(self.btn_mov_prev); pag_layout.addWidget(self.lbl_mov_page); pag_layout.addWidget(self.btn_mov_next); pag_layout.addStretch()
        layout.addLayout(pag_layout)

        # Pending REP table
        layout.addWidget(QLabel("📌 Comprobantes pendientes (para REP)"))
        self.pending_table = QTableWidget()
        self.pending_table.setColumnCount(7)
        self.pending_table.setHorizontalHeaderLabels(["Sel", "N° Venta", "N° Factura", "Fecha", "Total", "Pagado", "Pendiente"])
        self.pending_table.setSelectionBehavior(QTableWidget.SelectRows); self.pending_table.setSelectionMode(QTableWidget.MultiSelection)
        self.pending_table.setStyleSheet(_TABLE_STYLE + _CHECKBOX_STYLE)
        layout.addWidget(self.pending_table)

        btn_refresh_pending = QPushButton("🔄 Refrescar pendientes"); btn_refresh_pending.clicked.connect(self.load_pending_docs)
        btn_refresh_pending.setStyleSheet("background-color:#444;color:#ccc;padding:5px;border-radius:4px;")
        layout.addWidget(btn_refresh_pending)

        self.setLayout(layout)

        self.btn_add_payment.clicked.connect(self.register_payment)
        self.btn_refresh.clicked.connect(self._full_refresh)
        self.btn_view_sale.clicked.connect(self.open_sale_pdf)
        self.btn_export_pdf.clicked.connect(self.export_pdf)
        self.table.itemSelectionChanged.connect(self.on_row_selected)

    def _aging_box(self, label, color):
        lbl = QLabel(f"{label}\n₡0.00"); lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"background-color:#2a2a2a;border:1px solid {color};border-radius:6px;padding:6px;color:{color};font-size:12px;font-weight:bold;min-width:100px;")
        return lbl

    def _update_aging_box(self, lbl, label, value, color):
        lbl.setText(f"{label}\n₡{value:,.2f}")
        lbl.setStyleSheet(f"background-color:#2a2a2a;border:1px solid {color};border-radius:6px;padding:6px;color:{color};font-size:12px;font-weight:bold;min-width:100px;")

    def _apply_date_filter(self): self._mov_page = 0; self.load_credit_info()
    def _clear_date_filter(self):
        self.date_from.setDate(QDate.currentDate().addMonths(-3)); self.date_to.setDate(QDate.currentDate())
        self._mov_page = 0; self.load_credit_info()
    def _mov_prev(self):
        if self._mov_page > 0: self._mov_page -= 1; self.load_credit_info()
    def _mov_next(self): self._mov_page += 1; self.load_credit_info()
    def _full_refresh(self): self._mov_page = 0; self.load_credit_info()

    # ─────────────────────────────────────────────────────
    # FASE 1 — Fix 1.1: Carga asíncrona de datos de crédito
    # ─────────────────────────────────────────────────────
    def load_credit_info(self):
        params = {
            "mov_skip": self._mov_page * self._mov_page_size,
            "mov_limit": self._mov_page_size,
            "date_from": self.date_from.date().toString("yyyy-MM-dd"),
            "date_to": self.date_to.date().toString("yyyy-MM-dd"),
        }
        api_call(
            "get", f"{API_URL}/credits/{self.customer_id}",
            headers=self._auth(), params=params,
            on_success=self._on_credit_loaded,
            on_error=self._on_credit_error,
        )

    def _on_credit_loaded(self, response):
        data = response.get("data", {}) if isinstance(response, dict) else {}
        self._last_data = data

        customer_data = data.get("customer", {})
        balance = float(customer_data.get("credit_balance", 0.0))
        color = "#ef4444" if balance > 0 else "#22c55e"
        self.lbl_balance.setText(f"Saldo actual: ₡{balance:,.2f}")
        self.lbl_balance.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {color};")

        has_limit = customer_data.get("has_credit_limit", False)
        credit_limit = float(customer_data.get("credit_limit", 0.0))
        if has_limit and credit_limit > 0:
            self.lbl_limit.setText(f"Límite: ₡{credit_limit:,.2f}")
            pct = min(int((balance / credit_limit) * 100), 100) if credit_limit > 0 else 0
            bar_color = "#22c55e" if pct < 70 else ("#f59e0b" if pct < 90 else "#ef4444")
            self.progress_limit.setValue(pct)
            self.progress_limit.setStyleSheet(f"QProgressBar{{background-color:#333;border-radius:4px;text-align:center;color:white;font-size:11px;}}QProgressBar::chunk{{background-color:{bar_color};border-radius:4px;}}")
            self.progress_limit.setVisible(True)
        else:
            self.lbl_limit.setText("Límite: Ilimitado"); self.progress_limit.setVisible(False)

        paid_month = float(data.get("paid_this_month", 0.0))
        self.lbl_paid_month.setText(f"Abonado este mes: ₡{paid_month:,.2f}")

        aging = data.get("aging", {})
        self._update_aging_box(self.lbl_aging_0_30, "0-30 días", aging.get("0_30", 0), "#3b82f6")
        self._update_aging_box(self.lbl_aging_31_60, "31-60 días", aging.get("31_60", 0), "#f59e0b")
        self._update_aging_box(self.lbl_aging_61_90, "61-90 días", aging.get("61_90", 0), "#f97316")
        self._update_aging_box(self.lbl_aging_90_plus, "+90 días", aging.get("90_plus", 0), "#ef4444")

        mov_data = data.get("movements", {})
        movements = mov_data.get("items", [])
        mov_has_more = mov_data.get("has_more", False)

        self.table.setRowCount(len(movements))
        for row, m in enumerate(movements):
            is_sale = m.get("type") == "sale"
            tipo = "🧾 Venta POS" if is_sale else "💵 Abono"
            metodo = m.get("payment_method") or "N/A"
            id_item = QTableWidgetItem(str(m.get("id", "")))
            if is_sale:
                sale_id = m.get("sale_id")
                if sale_id is not None: id_item.setData(Qt.UserRole, int(sale_id))
            self.table.setItem(row, 0, id_item)
            self.table.setItem(row, 1, QTableWidgetItem(tipo))
            self.table.setItem(row, 2, QTableWidgetItem(metodo))
            amount = float(m.get("amount", 0.0))
            sign = "+" if is_sale else "-"
            amount_item = QTableWidgetItem(f"{sign}₡{amount:,.2f}")
            amount_item.setForeground(QColor("#ef4444") if is_sale else QColor("#22c55e"))
            self.table.setItem(row, 3, amount_item)
            self.table.setItem(row, 4, QTableWidgetItem(m.get("created_at", "")))

        self.btn_mov_prev.setEnabled(self._mov_page > 0)
        self.btn_mov_next.setEnabled(mov_has_more)
        start = self._mov_page * self._mov_page_size + 1 if movements else 0
        end = start + len(movements) - 1 if movements else 0
        self.lbl_mov_page.setText(f"{start}–{end}")

        self.load_pending_docs()

    def _on_credit_error(self, msg):
        QMessageBox.critical(self, "Error", f"Fallo al cargar datos:\n{msg}")

    # ─────────────────────────────────────────────────────
    # FASE 1 — Fix 1.1: Pendientes REP asíncrono
    # ─────────────────────────────────────────────────────
    def load_pending_docs(self):
        api_call(
            "get", f"{API_URL}/ereps/pending-by-customer/{self.customer_id}",
            headers=self._auth(),
            on_success=self._on_pending_loaded,
            on_error=lambda msg: QMessageBox.warning(self, "REP", f"No se pudo cargar pendientes:\n{msg}"),
        )

    def _on_pending_loaded(self, response):
        data = response.get("data", {}) if isinstance(response, dict) else {}
        items = data.get("items", [])
        self.pending_table.setRowCount(len(items))
        for row, it in enumerate(items):
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked)
            self.pending_table.setItem(row, 0, chk_item)
            self.pending_table.setItem(row, 1, QTableWidgetItem(str(it.get("sale_id"))))
            self.pending_table.setItem(row, 2, QTableWidgetItem(str(it.get("electronic_invoice_id"))))
            self.pending_table.setItem(row, 3, QTableWidgetItem(it.get("sale_date") or ""))
            self.pending_table.setItem(row, 4, QTableWidgetItem(f"{it.get('total', 0):.2f}"))
            self.pending_table.setItem(row, 5, QTableWidgetItem(f"{it.get('applied', 0):.2f}"))
            self.pending_table.setItem(row, 6, QTableWidgetItem(f"{it.get('pending', 0):.2f}"))
        self.pending_table.resizeColumnsToContents()

    def _selected_pending_einvoice_ids(self):
        ids = []
        for row in range(self.pending_table.rowCount()):
            chk = self.pending_table.item(row, 0)
            if chk and chk.checkState() == Qt.Checked:
                try: ids.append(int(self.pending_table.item(row, 2).text()))
                except Exception: continue
        return ids

    # ─────────────────────────────────────────────────────
    # FASE 2 — Fix 2.1: Cadena de pagos asíncrona
    # ─────────────────────────────────────────────────────
    def register_payment(self):
        if not self.customer_id:
            QMessageBox.warning(self, "Sin cliente", "No hay cliente seleccionado."); return

        dialog = PaymentDialog(self)
        if dialog.exec() == QDialog.Accepted:
            amount, payment_method, gen_rep = dialog.get_values()
            if amount is None or amount <= 0:
                QMessageBox.warning(self, "Error", "Ingrese un monto válido."); return

            # Paso 1: Registrar abono
            def _on_payment_ok(payload):
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                payment_id = data.get("payment_id")
                if not payment_id:
                    QMessageBox.warning(self, "REP", "No se pudo obtener payment_id del servidor."); return

                msg = f"Abono de ₡{amount:,.2f} registrado correctamente"
                if payment_method == "Efectivo": msg += "\n✅ Registrado en caja"

                if not gen_rep:
                    QMessageBox.information(self, "Éxito", msg); self.load_credit_info(); return

                einv_ids = self._selected_pending_einvoice_ids()
                if not einv_ids:
                    QMessageBox.warning(self, "REP", "No hay comprobantes seleccionados para aplicar FIFO.")
                    self.load_credit_info(); return

                # Paso 2: Sugerir asignaciones FIFO
                def _on_suggest_ok(s_payload):
                    sdata = s_payload.get("data", {}) if isinstance(s_payload, dict) else {}
                    items = sdata.get("items", [])
                    if not items:
                        QMessageBox.information(self, "REP", "No hay saldo pendiente aplicable."); self.load_credit_info(); return

                    resumen = "\n".join([f"- Factura {it['electronic_invoice_id']}: ₡{it['amount_applied']:.2f}" for it in items])
                    confirm = QMessageBox.question(self, "Confirmar REP",
                        f"{msg}\n\nSe aplicará FIFO así:\n\n{resumen}\n\n¿Generar REP ahora?", QMessageBox.Yes | QMessageBox.No)
                    if confirm != QMessageBox.Yes:
                        self.load_credit_info(); return

                    # Paso 3: Crear REP
                    refs = [{"electronic_invoice_id": it["electronic_invoice_id"], "amount_applied": it["amount_applied"]} for it in items]
                    api_call(
                        "post", f"{API_URL}/ereps/from-payment/{payment_id}",
                        json={"references": refs}, headers=self._auth(),
                        on_success=lambda _: (
                            QMessageBox.information(self, "Éxito", "✅ REP generado correctamente."),
                            self.load_credit_info(),
                        ),
                        on_error=lambda m: (
                            QMessageBox.warning(self, "REP", f"Error creando REP:\n{m}"),
                            self.load_credit_info(),
                        ),
                    )

                api_call(
                    "post", f"{API_URL}/ereps/suggest-allocations/{self.customer_id}",
                    json={"amount": amount, "electronic_invoice_ids": einv_ids}, headers=self._auth(),
                    on_success=_on_suggest_ok,
                    on_error=lambda m: (
                        QMessageBox.warning(self, "REP", f"Error sugiriendo FIFO:\n{m}"),
                        self.load_credit_info(),
                    ),
                )

            api_call(
                "post", f"{API_URL}/credits/{self.customer_id}/payments",
                json={"amount": amount, "payment_method": payment_method}, headers=self._auth(),
                on_success=_on_payment_ok,
                on_error=lambda m: QMessageBox.warning(self, "Error", f"Error al registrar abono:\n{m}"),
            )

    def export_pdf(self):
        if not self._last_data:
            QMessageBox.warning(self, "Sin datos", "Carga los datos primero."); return

        path, _ = QFileDialog.getSaveFileName(self, "Guardar estado de cuenta",
            f"estado_cuenta_{self.customer_name.replace(' ', '_')}.pdf", "PDF (*.pdf)")
        if not path: return

        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas as pdf_canvas
            from reportlab.lib import colors
            from reportlab.platypus import Table, TableStyle

            c = pdf_canvas.Canvas(path, pagesize=letter)
            w, h = letter
            y = h - 50

            c.setFont("Helvetica-Bold", 16); c.drawString(50, y, "Estado de Cuenta"); y -= 25
            cust = self._last_data.get("customer", {})
            c.setFont("Helvetica", 11)
            c.drawString(50, y, f"Cliente: {cust.get('name', '')}"); y -= 16
            c.drawString(50, y, f"ID: {cust.get('id_type', '')} - {cust.get('id_number', '')}"); y -= 16
            c.drawString(50, y, f"Correo: {cust.get('email', '') or 'N/A'}  |  Tel: {cust.get('phone', '') or 'N/A'}"); y -= 16
            c.drawString(50, y, f"Fecha: {date.today().strftime('%d/%m/%Y')}"); y -= 24

            balance = float(cust.get("credit_balance", 0))
            has_limit = cust.get("has_credit_limit", False)
            limit_val = float(cust.get("credit_limit", 0))
            c.setFont("Helvetica-Bold", 12)
            c.drawString(50, y, f"Saldo actual: ₡{balance:,.2f}"); y -= 16
            limit_txt = f"₡{limit_val:,.2f}" if has_limit else "Ilimitado"
            c.drawString(50, y, f"Límite: {limit_txt}"); y -= 16
            paid_month = self._last_data.get("paid_this_month", 0)
            c.drawString(50, y, f"Abonado este mes: ₡{paid_month:,.2f}"); y -= 22

            aging = self._last_data.get("aging", {})
            c.setFont("Helvetica", 10)
            c.drawString(50, y, f"Antigüedad:  0-30d: ₡{aging.get('0_30', 0):,.2f}  |  31-60d: ₡{aging.get('31_60', 0):,.2f}  |  61-90d: ₡{aging.get('61_90', 0):,.2f}  |  +90d: ₡{aging.get('90_plus', 0):,.2f}")
            y -= 28

            c.setFont("Helvetica-Bold", 11); c.drawString(50, y, "Movimientos"); y -= 16
            movements = self._last_data.get("movements", {}).get("items", [])
            if movements:
                table_data = [["ID", "Tipo", "Método", "Monto", "Fecha"]]
                for m in movements:
                    sign = "+" if m["type"] == "sale" else "-"
                    table_data.append([str(m["id"]), "Venta" if m["type"] == "sale" else "Abono", m.get("payment_method", "N/A"), f"{sign}₡{m['amount']:,.2f}", m.get("created_at", "")])
                t = Table(table_data, colWidths=[40, 60, 80, 100, 120])
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e88e5")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f0f0")]),
                ]))
                tw, th = t.wrap(0, 0)
                if y - th < 50: c.showPage(); y = h - 50
                t.drawOn(c, 50, y - th); y -= th + 10
            c.save()
            self._open_file(path)
            QMessageBox.information(self, "Éxito", "PDF exportado correctamente.")
        except ImportError:
            QMessageBox.critical(self, "Error", "La librería reportlab no está instalada.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error generando PDF:\n{e}")

    def open_sale_pdf(self):
        row = self.table.currentRow()
        if row == -1:
            QMessageBox.warning(self, "Atención", "Selecciona una venta."); return
        tipo = self.table.item(row, 1).text()
        if "Venta" not in tipo:
            QMessageBox.information(self, "No es una venta", "El movimiento seleccionado no corresponde a una venta."); return
        item = self.table.item(row, 0)
        sale_id = item.data(Qt.UserRole)
        if sale_id is None:
            QMessageBox.warning(self, "Error", "No se pudo determinar el ticket de esta venta."); return
        try:
            pdf_path = str(get_pdf_dir() / f"venta_{sale_id}.pdf")
            if not os.path.exists(pdf_path):
                reply = QMessageBox.question(self, "PDF no encontrado", "No existe el PDF para esta venta.\n¿Desea regenerarlo?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if reply != QMessageBox.Yes: return

                def _do_regen():
                    import requests as _req
                    resp = _req.post(f"{API_URL}/sales/{sale_id}/regenerate-pdf", headers=self._auth(), timeout=(5, 20))
                    resp.raise_for_status()
                    return pdf_path

                def _on_regen_ok(_result):
                    if os.path.exists(pdf_path):
                        self._open_file(pdf_path)
                    else:
                        QMessageBox.warning(self, "Error", "El PDF fue generado pero no se encontró en la ruta esperada.")

                run_async(
                    _do_regen,
                    on_success=_on_regen_ok,
                    on_error=lambda msg: QMessageBox.critical(self, "Error", f"No se pudo regenerar el PDF:\n{msg}"),
                )
                return
            self._open_file(pdf_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    @staticmethod
    def _open_file(path):
        if sys.platform == "win32": os.startfile(path)
        elif sys.platform == "darwin": subprocess.Popen(["open", path])
        else: subprocess.Popen(["xdg-open", path])

    def on_row_selected(self):
        row = self.table.currentRow()
        if row == -1: self.btn_view_sale.setEnabled(False); return
        tipo = self.table.item(row, 1).text()
        self.btn_view_sale.setEnabled("Venta" in tipo)