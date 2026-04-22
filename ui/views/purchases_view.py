from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QFileDialog, QComboBox, QLineEdit, QDateEdit, QDialog,
    QTextEdit, QDoubleSpinBox, QSpinBox, QFrame, QGroupBox,
    QGridLayout, QInputDialog,
)
from PySide6.QtCore import Qt, QTimer
from datetime import date
from ui.utils.http_worker import api_call, api_request
from ui.session_manager import session
from PySide6 import QtGui
from PySide6.QtWidgets import QAbstractItemView
from ui.components.toast_notifier import show_toast
import logging

from ui.api import BASE_URL


API_URL = f"{BASE_URL}/purchases"
API_SUPPLIERS = f"{BASE_URL}/suppliers"
API_PRODUCTS = f"{BASE_URL}/products"


class PurchasesView(QWidget):
    def __init__(self, supplier_id: int | None = None, supplier_name: str | None = None):
        super().__init__()
        self.supplier_id_filter = supplier_id
        self.supplier_name_filter = supplier_name
        self.purchases = []
        self.filtered_purchases = []

        # Paginación
        self.current_page = 1
        self.page_size = 50
        self.total_items = 0
        self.total_pages = 1

        # Debounce para búsqueda
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(400)  # ms
        self._search_timer.timeout.connect(self._on_search_debounced)

        self.setup_ui()
        self.load_purchases()
        self.load_dashboard()

    # ---------------------------------------------------------
    # 🧠 UI
    # ---------------------------------------------------------
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)

        title = QLabel("🧾 Facturas / Compras")
        if getattr(self, "supplier_name_filter", None):
            title.setText(f"🧾 Facturas de {self.supplier_name_filter}")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #D9D9D9; margin-bottom: 10px;")
        layout.addWidget(title)

        # =====================================================
        # MINI-DASHBOARD (KPIs)
        # =====================================================
        self.dashboard_group = QGroupBox("📊 Resumen de compras")
        self.dashboard_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 13px; color: #D9D9D9;
                border: 1px solid #444; border-radius: 8px;
                margin-top: 6px; padding: 10px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
        """)
        dash_grid = QGridLayout()
        dash_grid.setSpacing(10)

        kpi_style = "font-size: 13px; color: #D9D9D9; padding: 4px;"
        val_style_normal = "font-size: 16px; font-weight: bold; color: #5B9BD5;"
        val_style_warn = "font-size: 16px; font-weight: bold; color: #F7C331;"
        val_style_danger = "font-size: 16px; font-weight: bold; color: #DC3545;"

        self.kpi_payable_week = QLabel("₡0.00")
        self.kpi_payable_week.setStyleSheet(val_style_normal)
        dash_grid.addWidget(QLabel("📅 Por pagar esta semana:"), 0, 0)
        dash_grid.addWidget(self.kpi_payable_week, 0, 1)

        self.kpi_urgent = QLabel("0")
        self.kpi_urgent.setStyleSheet(val_style_warn)
        dash_grid.addWidget(QLabel("⚡ Vencen en 3 días:"), 0, 2)
        dash_grid.addWidget(self.kpi_urgent, 0, 3)

        self.kpi_overdue = QLabel("₡0.00 (0)")
        self.kpi_overdue.setStyleSheet(val_style_danger)
        dash_grid.addWidget(QLabel("🔴 Vencidas:"), 1, 0)
        dash_grid.addWidget(self.kpi_overdue, 1, 1)

        self.kpi_month_total = QLabel("₡0.00")
        self.kpi_month_total.setStyleSheet(val_style_normal)
        dash_grid.addWidget(QLabel("📦 Compras del mes:"), 1, 2)
        dash_grid.addWidget(self.kpi_month_total, 1, 3)

        self.dashboard_group.setLayout(dash_grid)
        layout.addWidget(self.dashboard_group)

        # =====================================================
        # FILTROS
        # =====================================================
        filter_layout = QHBoxLayout()
        self.filter_status_combo = QComboBox()
        self.filter_status_combo.addItems([
            "Todos", "Pendiente", "Recibido", "Parcial",
            "Por vencer", "Vencido", "Pagado"
        ])
        self.filter_status_combo.setFixedWidth(180)
        self.filter_status_combo.currentTextChanged.connect(self._on_server_filter_changed)
        filter_layout.addWidget(QLabel("Estado:"))
        filter_layout.addWidget(self.filter_status_combo)

        self.filter_supplier_combo = QComboBox()
        self.filter_supplier_combo.addItem("Todos")
        self.filter_supplier_combo.setFixedWidth(180)
        self.filter_supplier_combo.currentTextChanged.connect(self._on_server_filter_changed)
        filter_layout.addWidget(QLabel("Proveedor:"))
        filter_layout.addWidget(self.filter_supplier_combo)

        self.filter_min_input = QLineEdit()
        self.filter_min_input.setPlaceholderText("Min")
        self.filter_min_input.setFixedWidth(80)
        self.filter_min_input.textChanged.connect(self.apply_combined_filters)
        filter_layout.addWidget(QLabel("₡Min:"))
        filter_layout.addWidget(self.filter_min_input)

        self.filter_max_input = QLineEdit()
        self.filter_max_input.setPlaceholderText("Max")
        self.filter_max_input.setFixedWidth(80)
        self.filter_max_input.textChanged.connect(self.apply_combined_filters)
        filter_layout.addWidget(QLabel("₡Max:"))
        filter_layout.addWidget(self.filter_max_input)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Fecha + buscador
        filter2 = QHBoxLayout()
        from PySide6.QtCore import QDate
        self.filter_date_from = QDateEdit()
        self.filter_date_from.setCalendarPopup(True)
        self.filter_date_from.setDisplayFormat("yyyy-MM-dd")
        self.filter_date_from.setFixedWidth(130)
        self.filter_date_from.setSpecialValueText("Sin filtro")
        self.filter_date_from.setMinimumDate(QDate(2000, 1, 1))
        self.filter_date_from.setDate(QDate(2000, 1, 1))
        self.filter_date_from.dateChanged.connect(self.apply_combined_filters)

        self.filter_date_to = QDateEdit()
        self.filter_date_to.setCalendarPopup(True)
        self.filter_date_to.setDisplayFormat("yyyy-MM-dd")
        self.filter_date_to.setFixedWidth(130)
        self.filter_date_to.setSpecialValueText("Sin filtro")
        self.filter_date_to.setMinimumDate(QDate(2000, 1, 1))
        self.filter_date_to.setDate(QDate(2000, 1, 1))
        self.filter_date_to.dateChanged.connect(self.apply_combined_filters)

        filter2.addWidget(QLabel("Desde:"))
        filter2.addWidget(self.filter_date_from)
        filter2.addWidget(QLabel("Hasta:"))
        filter2.addWidget(self.filter_date_to)

        self.advanced_search_input = QLineEdit()
        self.advanced_search_input.setPlaceholderText("Buscar factura... (Enter o espere)")
        self.advanced_search_input.textChanged.connect(self._on_search_text_changed)
        self.advanced_search_input.returnPressed.connect(self._on_search_debounced)
        filter2.addWidget(self.advanced_search_input)
        layout.addLayout(filter2)

        # =====================================================
        # TABLA
        # =====================================================
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setColumnCount(15)
        self.table.setHorizontalHeaderLabels([
            "ID", "Número", "Proveedor", "F.Entrada", "F.Venc.",
            "Monto", "Abonado", "Saldo", "Estado", "Líneas", "Notas",
            "PDF", "Método", "F.Recep.", "F.Pago"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #2C2F33; alternate-background-color: #32383E; color: white; selection-background-color: #5B9BD5; }
            QHeaderView::section { background-color: #5B9BD5; color: white; font-weight: bold; }
        """)
        self.table.cellDoubleClicked.connect(self.open_payment_details)
        layout.addWidget(self.table)

        # =====================================================
        # PAGINACIÓN
        # =====================================================
        pag_layout = QHBoxLayout()
        pag_layout.setContentsMargins(0, 4, 0, 4)

        self.btn_first_page = QPushButton("⏮")
        self.btn_first_page.setFixedWidth(36)
        self.btn_first_page.clicked.connect(lambda: self._go_to_page(1))
        pag_layout.addWidget(self.btn_first_page)

        self.btn_prev_page = QPushButton("◀ Anterior")
        self.btn_prev_page.setFixedWidth(100)
        self.btn_prev_page.clicked.connect(lambda: self._go_to_page(self.current_page - 1))
        pag_layout.addWidget(self.btn_prev_page)

        self.lbl_page_info = QLabel("Página 1 de 1  (0 facturas)")
        self.lbl_page_info.setAlignment(Qt.AlignCenter)
        self.lbl_page_info.setStyleSheet("color: #D9D9D9; font-size: 12px; font-weight: bold;")
        pag_layout.addWidget(self.lbl_page_info, 1)

        self.btn_next_page = QPushButton("Siguiente ▶")
        self.btn_next_page.setFixedWidth(100)
        self.btn_next_page.clicked.connect(lambda: self._go_to_page(self.current_page + 1))
        pag_layout.addWidget(self.btn_next_page)

        self.btn_last_page = QPushButton("⏭")
        self.btn_last_page.setFixedWidth(36)
        self.btn_last_page.clicked.connect(lambda: self._go_to_page(self.total_pages))
        pag_layout.addWidget(self.btn_last_page)

        pag_layout.addSpacing(16)
        pag_layout.addWidget(QLabel("Por página:"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100"])
        self.page_size_combo.setCurrentText("50")
        self.page_size_combo.setFixedWidth(65)
        self.page_size_combo.currentTextChanged.connect(self._on_page_size_changed)
        pag_layout.addWidget(self.page_size_combo)

        pag_style = """
            QPushButton { background-color: #3A3F47; color: #D9D9D9; border: 1px solid #555;
                          border-radius: 4px; padding: 4px 8px; font-weight: bold; }
            QPushButton:hover { background-color: #5B9BD5; color: white; }
            QPushButton:disabled { background-color: #2C2F33; color: #666; border-color: #444; }
        """
        for btn in [self.btn_first_page, self.btn_prev_page, self.btn_next_page, self.btn_last_page]:
            btn.setStyleSheet(pag_style)

        layout.addLayout(pag_layout)

        # =====================================================
        # BOTONES — Fila 1 (CRUD + recepción)
        # =====================================================
        btn1 = QHBoxLayout()
        for text, slot, color in [
            ("🔄 Actualizar", self.load_purchases, "#17A2B8"),
            ("➕ Agregar", self.add_purchase, "#28A745"),
            ("✏️ Editar", self.edit_purchase, "#FFC107"),
            ("🗑️ Eliminar", self.delete_purchase, "#DC3545"),
            ("📦 Recibir", self.receive_purchase, "#17A2B8"),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            b.setStyleSheet(f"QPushButton {{ background-color: {color}; color: white; font-weight: bold; padding: 7px; border-radius: 6px; min-width: 100px; }}")
            btn1.addWidget(b)
        layout.addLayout(btn1)

        # =====================================================
        # BOTONES — Fila 2 (financieros + exportación)
        # =====================================================
        btn2 = QHBoxLayout()
        for text, slot, color in [
            ("💵 Abonar", self.add_payment_dialog, "#28A745"),
            ("💰 Pagar total", self.mark_paid, "#6F42C1"),
            ("📋 Nota crédito", self.add_credit_note_dialog, "#E67E22"),
            ("📄 Subir PDF", self.upload_pdf, "#0D6EFD"),
            ("📊 Excel", self.export_excel, "#1D6F42"),
            ("📑 PDF", self.export_pdf, "#B71C1C"),
            ("📧 Alertas email", self.send_email_alert, "#7B1FA2"),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            b.setStyleSheet(f"QPushButton {{ background-color: {color}; color: white; font-weight: bold; padding: 7px; border-radius: 6px; min-width: 95px; }}")
            btn2.addWidget(b)
        layout.addLayout(btn2)

        self.setLayout(layout)

    # ---------------------------------------------------------
    # 📊 CARGAR MINI-DASHBOARD
    # ---------------------------------------------------------
    def load_dashboard(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            res = api_request("get", f"{API_URL}/dashboard", headers=headers, timeout=10)
            if res.status_code != 200:
                return

            payload = res.json()
            data = payload.get("data", {}) if isinstance(payload, dict) else {}

            self.kpi_payable_week.setText(f"₡{data.get('payable_this_week', 0):,.2f} ({data.get('count_payable_week', 0)})")
            self.kpi_urgent.setText(f"{data.get('count_urgent', 0)} factura(s)")
            self.kpi_overdue.setText(f"₡{data.get('total_overdue', 0):,.2f} ({data.get('count_overdue', 0)})")
            self.kpi_month_total.setText(f"₡{data.get('total_month', 0):,.2f}")

            # Toast urgente si hay facturas por vencer
            urgent = data.get("count_urgent", 0)
            overdue = data.get("count_overdue", 0)
            if overdue > 0:
                show_toast(f"🔴 {overdue} factura(s) VENCIDA(S)", success=False, parent=self.window(), duration=5000)
            elif urgent > 0:
                show_toast(f"⚡ {urgent} factura(s) vencen en 3 días", success=False, parent=self.window(), duration=4000)

        except Exception:
            pass  # No bloquear si el dashboard falla

    # ---------------------------------------------------------
    # 📦 CARGAR FACTURAS
    # ---------------------------------------------------------
    def load_purchases(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}

            # --- Parámetros server-side ---
            skip = (self.current_page - 1) * self.page_size
            params = {"skip": skip, "limit": self.page_size}

            # Proveedor (filtro fijo de constructor o combo)
            if getattr(self, "supplier_id_filter", None):
                params["supplier_id"] = self.supplier_id_filter
            else:
                sid = getattr(self, "filter_supplier_combo", None)
                if sid and sid.currentData() is not None:
                    params["supplier_id"] = sid.currentData()

            # Estado → enviar al server (excepto "por vencer" que es client-side)
            status_combo = getattr(self, "filter_status_combo", None)
            status_text = status_combo.currentText().lower() if status_combo else "todos"
            if status_text not in ("todos", "por vencer"):
                params["status_filter"] = status_text

            # Búsqueda por número de factura
            search_text = getattr(self, "advanced_search_input", None)
            if search_text and search_text.text().strip():
                params["search"] = search_text.text().strip()

            res = api_request("get", API_URL, headers=headers, params=params)
            if res.status_code != 200:
                raise Exception(res.text)

            payload = res.json()
            if isinstance(payload, dict):
                if not payload.get("success", True):
                    raise Exception(payload.get("message", "Error"))
                data = payload.get("data", {})
                self.purchases = data.get("items", [])
                self.total_items = data.get("total", len(self.purchases))
            else:
                self.purchases = payload
                self.total_items = len(self.purchases)

            if not isinstance(self.purchases, list):
                raise Exception("Formato inválido")

            # Calcular páginas
            self.total_pages = max(1, (self.total_items + self.page_size - 1) // self.page_size)
            if self.current_page > self.total_pages:
                self.current_page = self.total_pages

            # Cargar proveedores (solo la primera vez o si el combo está vacío)
            if not getattr(self, "suppliers_map", None) or not self.suppliers_map:
                res_sup = api_request("get", API_SUPPLIERS, headers=headers)
                suppliers_payload = res_sup.json() if res_sup.status_code == 200 else []
                if isinstance(suppliers_payload, dict):
                    suppliers_list = suppliers_payload.get("items", suppliers_payload.get("data", []))
                else:
                    suppliers_list = suppliers_payload
                self.suppliers_map = {s["id"]: s["name"] for s in suppliers_list}

                self.filter_supplier_combo.blockSignals(True)
                self.filter_supplier_combo.clear()
                self.filter_supplier_combo.addItem("Todos", None)
                for sid_key, name in self.suppliers_map.items():
                    self.filter_supplier_combo.addItem(name, sid_key)
                self.filter_supplier_combo.blockSignals(False)

            # Aplicar filtros client-side (monto, fecha, "por vencer")
            self.apply_client_filters()

            # Actualizar controles de paginación
            self._update_pagination_controls()

            # Refresh dashboard KPIs
            self.load_dashboard()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudieron cargar las compras:\n{e}")

    def update_table(self, purchase_list=None):
        if purchase_list is None:
            purchase_list = self.purchases
        self.filtered_purchases = purchase_list
        self.table.setRowCount(len(purchase_list))

        for row, p in enumerate(purchase_list):
            self.table.setItem(row, 0, QTableWidgetItem(str(p.get("id", ""))))
            self.table.setItem(row, 1, QTableWidgetItem(p.get("invoice_number", "")))
            sid = p.get("supplier_id")
            self.table.setItem(row, 2, QTableWidgetItem(self.suppliers_map.get(sid, "?")))
            self.table.setItem(row, 3, QTableWidgetItem(str(p.get("entry_date", ""))[:10]))
            self.table.setItem(row, 4, QTableWidgetItem(str(p.get("due_date", ""))[:10]))

            amount = float(p.get("amount", 0))
            paid_amount = float(p.get("paid_amount", 0))
            balance = float(p.get("balance", amount))
            self.table.setItem(row, 5, QTableWidgetItem(f"₡{amount:,.2f}"))
            self.table.setItem(row, 6, QTableWidgetItem(f"₡{paid_amount:,.2f}"))
            self.table.setItem(row, 7, QTableWidgetItem(f"₡{balance:,.2f}"))

            raw_status = (p.get("status") or "").lower()
            eff = raw_status
            try:
                due_dt = date.fromisoformat(str(p.get("due_date", ""))[:10])
                if raw_status not in ("pagado", "recibido", "parcial") and due_dt < date.today():
                    eff = "vencido"
            except Exception:
                pass

            self.table.setItem(row, 8, QTableWidgetItem(eff))
            self.table.setItem(row, 9, QTableWidgetItem(str(p.get("items_count", 0))))
            notes_item = QTableWidgetItem(p.get("notes") or "")
            notes_item.setToolTip(p.get("notes") or "")
            self.table.setItem(row, 10, notes_item)
            self.table.setItem(row, 11, QTableWidgetItem(p.get("pdf_path") or ""))
            self.table.setItem(row, 12, QTableWidgetItem(p.get("payment_method") or "-"))
            recv = p.get("received_at")
            self.table.setItem(row, 13, QTableWidgetItem(str(recv)[:10] if recv else "-"))
            pa = p.get("paid_at")
            self.table.setItem(row, 14, QTableWidgetItem(str(pa)[:10] if pa else "-"))

            color_map = {"pendiente": "#F7C331", "recibido": "#17A2B8", "parcial": "#E67E22", "pagado": "#28A745", "vencido": "#DC3545"}
            color = color_map.get(eff)
            if color:
                for c in range(self.table.columnCount()):
                    it = self.table.item(row, c)
                    if it:
                        it.setBackground(QtGui.QColor(color))

            for c in range(self.table.columnCount()):
                it = self.table.item(row, c)
                if it and it.text():
                    it.setToolTip(it.text())

    # ---------------------------------------------------------
    # CRUD
    # ---------------------------------------------------------
    def add_purchase(self):
        from ui.dialogs.add_purchase_dialog import AddPurchaseDialog
        if AddPurchaseDialog().exec():
            self.load_purchases()

    def edit_purchase(self):
        from ui.dialogs.edit_purchase_dialog import EditPurchaseDialog
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona una factura.")
            return
        purchase = self.filtered_purchases[row]
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            res = api_request("get", f"{API_URL}/{purchase['id']}", headers=headers)
            if res.status_code == 200:
                full = res.json()
                if isinstance(full, dict) and "data" in full:
                    purchase = full["data"]
        except Exception:
            pass
        if EditPurchaseDialog(purchase).exec():
            self.load_purchases()

    def delete_purchase(self):
        row = self.table.currentRow()
        if row < 0:
            return
        pid = self.table.item(row, 0).text()
        if QMessageBox.question(self, "Eliminar", f"¿Eliminar factura ID {pid}?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            api_request("delete", f"{API_URL}/{pid}", headers=headers)
            show_toast("Factura eliminada", success=True, parent=self.window())
            self.load_purchases()

    def receive_purchase(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona una factura.")
            return
        pid = self.table.item(row, 0).text()
        st = self.table.item(row, 8).text().lower()
        if st in ("recibido", "pagado"):
            show_toast("Ya fue recibida", success=True, parent=self.window())
            return
        if QMessageBox.question(self, "Recibir", f"¿Confirmar recepción factura {pid}?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
        try:
            res = api_request("put", f"{API_URL}/{pid}/receive", headers=headers)
            if res.status_code == 200:
                show_toast("📦 Mercadería recibida", success=True, parent=self.window())
                self.load_purchases()
            else:
                err = res.text
                try:
                    err = res.json().get("detail", err)
                except Exception:
                    pass
                QMessageBox.critical(self, "Error", str(err))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ---------------------------------------------------------
    # FINANCIEROS
    # ---------------------------------------------------------
    def add_payment_dialog(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona una factura.")
            return
        p = self.filtered_purchases[row]
        if p.get("status") == "pagado":
            show_toast("Ya está pagada", success=True, parent=self.window())
            return
        bal = float(p.get("balance", p.get("amount", 0)))
        dlg = AddPaymentDialog(p, bal, self)
        if dlg.exec() == QDialog.Accepted:
            self.load_purchases()

    def add_credit_note_dialog(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona una factura.")
            return
        dlg = AddCreditNoteDialog(self.filtered_purchases[row], self)
        if dlg.exec() == QDialog.Accepted:
            self.load_purchases()

    def mark_paid(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona una factura.")
            return
        pid = self.table.item(row, 0).text()
        dlg = PaymentMethodDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
        try:
            res = api_request("put", f"{API_URL}/{pid}/pay", json={"payment_method": dlg.selected_method()}, headers=headers)
            if res.status_code == 200:
                show_toast("💰 Factura pagada", success=True, parent=self.window())
                self.load_purchases()
            else:
                QMessageBox.critical(self, "Error", res.text)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def upload_pdf(self):
        row = self.table.currentRow()
        if row < 0:
            return
        pid = self.table.item(row, 0).text()
        file, _ = QFileDialog.getOpenFileName(self, "Seleccionar PDF", "", "PDF Files (*.pdf)")
        if not file:
            return
        headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
        with open(file, "rb") as f:
            res = api_request("post", f"{API_URL}/{pid}/upload-pdf", files={"file": f}, headers=headers)
        if res.status_code == 200:
            show_toast("PDF subido", success=True, parent=self.window())
            self.load_purchases()

    # ---------------------------------------------------------
    # EXPORTACIÓN
    # ---------------------------------------------------------
    def _export_params(self):
        params = {}
        st = self.filter_status_combo.currentText().lower()
        if st != "todos":
            params["status_filter"] = st
        sid = self.filter_supplier_combo.currentData()
        if sid is not None:
            params["supplier_id"] = sid
        q = self.advanced_search_input.text().strip()
        if q:
            params["search"] = q
        return params

    def export_excel(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            params = self._export_params()
            params["format"] = "excel"
            res = api_request("get", f"{API_URL}/export", headers=headers, params=params, timeout=30)
            if res.status_code == 200:
                path, _ = QFileDialog.getSaveFileName(self, "Guardar Excel", "compras.xlsx", "Excel (*.xlsx)")
                if path:
                    with open(path, "wb") as f:
                        f.write(res.content)
                    show_toast(f"Excel exportado", success=True, parent=self.window())
            else:
                QMessageBox.critical(self, "Error", "No se pudo exportar.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def export_pdf(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            params = self._export_params()
            params["format"] = "pdf"
            res = api_request("get", f"{API_URL}/export", headers=headers, params=params, timeout=30)
            if res.status_code == 200:
                path, _ = QFileDialog.getSaveFileName(self, "Guardar PDF", "compras.pdf", "PDF (*.pdf)")
                if path:
                    with open(path, "wb") as f:
                        f.write(res.content)
                    show_toast(f"PDF exportado", success=True, parent=self.window())
            else:
                QMessageBox.critical(self, "Error", "No se pudo exportar.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ---------------------------------------------------------
    # ALERTA POR CORREO
    # ---------------------------------------------------------
    def send_email_alert(self):
        email, ok = QInputDialog.getText(self, "Enviar alerta", "Correo destino:")
        if not ok or not email.strip():
            return
        headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
        try:
            res = api_request("post",
                f"{API_URL}/notify-expiring",
                headers=headers,
                params={"recipient": email.strip(), "days_ahead": 3},
            )
            if res.status_code == 200:
                data = res.json().get("data", {})
                if data.get("sent"):
                    show_toast(f"📧 Alerta enviada ({data.get('count', 0)} facturas)", success=True, parent=self.window())
                else:
                    show_toast("No hay facturas por vencer o el correo no está configurado", success=False, parent=self.window())
            else:
                QMessageBox.critical(self, "Error", res.text)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ---------------------------------------------------------
    # FILTROS
    # ---------------------------------------------------------
    def apply_state_filter(self):
        self._on_server_filter_changed()

    def apply_combined_filters(self):
        """Aplica solo los filtros client-side (monto, fecha) sobre la data ya cargada."""
        self.apply_client_filters()

    def apply_client_filters(self):
        """Filtra client-side: monto min/max, rango de fecha, y 'por vencer'."""
        filtered = self.purchases.copy()

        # Filtro especial "por vencer" (client-side)
        status_combo = getattr(self, "filter_status_combo", None)
        st = status_combo.currentText().lower() if status_combo else "todos"
        if st == "por vencer":
            from datetime import timedelta
            today = date.today()
            lim = today + timedelta(days=3)
            filtered = [
                p for p in filtered
                if p.get("status") == "pendiente" and p.get("due_date")
                and today <= date.fromisoformat(str(p["due_date"])[:10]) <= lim
            ]

        # Monto mínimo / máximo
        mn = self.filter_min_input.text().strip()
        if mn.replace(".", "", 1).isdigit():
            filtered = [p for p in filtered if float(p.get("amount", 0)) >= float(mn)]
        mx = self.filter_max_input.text().strip()
        if mx.replace(".", "", 1).isdigit():
            filtered = [p for p in filtered if float(p.get("amount", 0)) <= float(mx)]

        # Rango de fecha
        NULL = "2000-01-01"
        df = self.filter_date_from.date().toString("yyyy-MM-dd")
        dt_val = self.filter_date_to.date().toString("yyyy-MM-dd")
        if df and df != NULL:
            filtered = [p for p in filtered if str(p.get("entry_date", "")) >= df]
        if dt_val and dt_val != NULL:
            filtered = [p for p in filtered if str(p.get("entry_date", "")) <= dt_val]

        self.update_table(filtered)

    # ---------------------------------------------------------
    # PAGINACIÓN
    # ---------------------------------------------------------
    def _go_to_page(self, page: int):
        page = max(1, min(page, self.total_pages))
        if page == self.current_page:
            return
        self.current_page = page
        self.load_purchases()

    def _on_page_size_changed(self, text):
        try:
            self.page_size = int(text)
        except ValueError:
            self.page_size = 50
        self.current_page = 1
        self.load_purchases()

    def _update_pagination_controls(self):
        self.btn_first_page.setEnabled(self.current_page > 1)
        self.btn_prev_page.setEnabled(self.current_page > 1)
        self.btn_next_page.setEnabled(self.current_page < self.total_pages)
        self.btn_last_page.setEnabled(self.current_page < self.total_pages)
        self.lbl_page_info.setText(
            f"Página {self.current_page} de {self.total_pages}  ({self.total_items} facturas)"
        )

    # ---------------------------------------------------------
    # FILTROS SERVER-SIDE (resetean a página 1 y recargan)
    # ---------------------------------------------------------
    def _on_server_filter_changed(self, *_args):
        """Cuando cambia estado o proveedor → página 1 y recargar del server."""
        self.current_page = 1
        self.load_purchases()

    def _on_search_text_changed(self, _text):
        """Reinicia el debounce timer cuando el usuario escribe."""
        self._search_timer.start()

    def _on_search_debounced(self):
        """Se ejecuta tras 400ms sin tipear → búsqueda server-side."""
        self._search_timer.stop()
        self.current_page = 1
        self.load_purchases()

    def open_payment_details(self, row, column):
        if row < 0 or row >= len(self.filtered_purchases):
            return
        dlg = PaymentDetailDialog(self.filtered_purchases[row], self)
        dlg.exec()


# ============================================================
# DIÁLOGOS AUXILIARES
# ============================================================

class PaymentMethodDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Método de pago")
        self.setMinimumWidth(300)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Método de pago:"))
        self.method_combo = QComboBox()
        self.method_combo.addItems(["Efectivo", "SINPE", "Transferencia bancaria", "Tarjeta", "Otro"])
        layout.addWidget(self.method_combo)
        bl = QHBoxLayout()
        ok = QPushButton("Aceptar"); ok.clicked.connect(self.accept)
        ca = QPushButton("Cancelar"); ca.clicked.connect(self.reject)
        bl.addWidget(ok); bl.addWidget(ca)
        layout.addLayout(bl)
        self.setLayout(layout)

    def selected_method(self):
        return self.method_combo.currentText()


class AddPaymentDialog(QDialog):
    def __init__(self, purchase, balance, parent=None):
        super().__init__(parent)
        self.purchase = purchase
        self.setWindowTitle(f"💵 Abonar — #{purchase.get('invoice_number', '')}")
        self.setMinimumWidth(400)
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"Total: ₡{float(purchase.get('amount', 0)):,.2f}  |  Abonado: ₡{float(purchase.get('paid_amount', 0)):,.2f}  |  Saldo: ₡{balance:,.2f}"))
        layout.addWidget(QLabel("Monto del abono:"))
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.01, max(balance, 0.01))
        self.amount_spin.setDecimals(2)
        self.amount_spin.setPrefix("₡ ")
        self.amount_spin.setValue(balance)
        layout.addWidget(self.amount_spin)
        layout.addWidget(QLabel("Método:"))
        self.method_combo = QComboBox()
        self.method_combo.addItems(["Efectivo", "SINPE", "Transferencia bancaria", "Tarjeta", "Otro"])
        layout.addWidget(self.method_combo)
        layout.addWidget(QLabel("Notas:"))
        self.notes_input = QLineEdit()
        layout.addWidget(self.notes_input)
        bl = QHBoxLayout()
        sv = QPushButton("💾 Registrar"); sv.setStyleSheet("background-color:#28A745;color:white;font-weight:bold;padding:8px;"); sv.clicked.connect(self.save)
        ca = QPushButton("Cancelar"); ca.clicked.connect(self.reject)
        bl.addWidget(sv); bl.addWidget(ca)
        layout.addLayout(bl)
        self.setLayout(layout)

    def save(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            res = api_request("post", f"{API_URL}/{self.purchase['id']}/payments", json={
                "amount": self.amount_spin.value(), "payment_method": self.method_combo.currentText(),
                "notes": self.notes_input.text().strip() or None,
            }, headers=headers)
            if res.status_code == 200:
                show_toast("Abono registrado", success=True, parent=self.window())
                self.accept()
            else:
                err = res.text
                try: err = res.json().get("detail", err)
                except Exception: logging.debug("No se pudo parsear JSON de error en abono: %s", err)
                QMessageBox.critical(self, "Error", str(err))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


class AddCreditNoteDialog(QDialog):
    def __init__(self, purchase, parent=None):
        super().__init__(parent)
        self.purchase = purchase
        self.setWindowTitle(f"📋 Nota crédito — #{purchase.get('invoice_number', '')}")
        self.setMinimumWidth(450)
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"Monto: ₡{float(purchase.get('amount', 0)):,.2f}  |  Saldo: ₡{float(purchase.get('balance', 0)):,.2f}"))
        layout.addWidget(QLabel("Monto NC:"))
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.01, float(purchase.get("amount", 99999999)))
        self.amount_spin.setDecimals(2)
        self.amount_spin.setPrefix("₡ ")
        layout.addWidget(self.amount_spin)
        layout.addWidget(QLabel("Motivo:"))
        self.reason_input = QTextEdit()
        self.reason_input.setMaximumHeight(50)
        layout.addWidget(self.reason_input)
        layout.addWidget(QLabel("Producto a devolver (opcional):"))
        self.product_combo = QComboBox()
        self.product_combo.addItem("— Sin devolución —", None)
        self._load_products()
        layout.addWidget(self.product_combo)
        layout.addWidget(QLabel("Unidades a devolver:"))
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(0, 99999)
        layout.addWidget(self.qty_spin)
        bl = QHBoxLayout()
        sv = QPushButton("💾 Registrar"); sv.setStyleSheet("background-color:#E67E22;color:white;font-weight:bold;padding:8px;"); sv.clicked.connect(self.save)
        ca = QPushButton("Cancelar"); ca.clicked.connect(self.reject)
        bl.addWidget(sv); bl.addWidget(ca)
        layout.addLayout(bl)
        self.setLayout(layout)

    def _load_products(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            res = api_request("get", API_PRODUCTS, headers=headers)
            payload = res.json()
            products = payload.get("data", []) if isinstance(payload, dict) else payload
            if isinstance(products, dict):
                products = products.get("items", [])
            for p in products:
                self.product_combo.addItem(f"{p['name']} (Stock: {p.get('stock', 0)})", p["id"])
        except Exception:
            pass

    def save(self):
        reason = self.reason_input.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Atención", "Motivo obligatorio.")
            return
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            res = api_request("post", f"{API_URL}/{self.purchase['id']}/credit-notes", json={
                "amount": self.amount_spin.value(), "reason": reason,
                "product_id": self.product_combo.currentData(), "quantity_returned": self.qty_spin.value(),
            }, headers=headers)
            if res.status_code == 200:
                show_toast("NC registrada", success=True, parent=self.window())
                self.accept()
            else:
                err = res.text
                try: err = res.json().get("detail", err)
                except Exception: logging.debug("No se pudo parsear JSON de error en NC: %s", err)
                QMessageBox.critical(self, "Error", str(err))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


class PaymentDetailDialog(QDialog):
    def __init__(self, purchase, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"📄 Detalle — #{purchase.get('invoice_number', '')}")
        self.setMinimumWidth(550)
        self.setMinimumHeight(400)
        layout = QVBoxLayout()

        def r(l, v):
            h = QHBoxLayout(); h.addWidget(QLabel(f"<b>{l}:</b>")); h.addWidget(QLabel(str(v))); layout.addLayout(h)

        r("Factura", purchase.get("invoice_number", ""))
        r("Proveedor", str(purchase.get("supplier_name") or purchase.get("supplier_id", "")))
        r("Monto", f"₡{float(purchase.get('amount', 0)):,.2f}")
        r("Abonado", f"₡{float(purchase.get('paid_amount', 0)):,.2f}")
        r("NC", f"₡{float(purchase.get('credit_notes_total', 0)):,.2f}")
        r("Saldo", f"₡{float(purchase.get('balance', 0)):,.2f}")
        r("Estado", purchase.get("status", "-"))

        pid = purchase.get("id")
        headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}

        layout.addWidget(QLabel("<b>💵 Abonos:</b>"))
        try:
            res = api_request("get", f"{API_URL}/{pid}/payments", headers=headers)
            pays = res.json().get("data", []) if res.status_code == 200 else []
            for pp in (pays if isinstance(pays, list) else []):
                layout.addWidget(QLabel(f"  • {pp.get('date','?')} — ₡{float(pp.get('amount',0)):,.2f} ({pp.get('payment_method','')})"))
            if not pays:
                layout.addWidget(QLabel("  Sin abonos."))
        except Exception: layout.addWidget(QLabel("  Error."))

        layout.addWidget(QLabel("<b>📋 Notas crédito:</b>"))
        try:
            res = api_request("get", f"{API_URL}/{pid}/credit-notes", headers=headers)
            cns = res.json().get("data", []) if res.status_code == 200 else []
            for cn in (cns if isinstance(cns, list) else []):
                t = f"  • {cn.get('date','?')} — ₡{float(cn.get('amount',0)):,.2f} — {cn.get('reason','')}"
                if cn.get("quantity_returned"):
                    t += f" ({cn['quantity_returned']} uds)"
                layout.addWidget(QLabel(t))
            if not cns:
                layout.addWidget(QLabel("  Sin NC."))
        except Exception: layout.addWidget(QLabel("  Error."))

        btn = QPushButton("Cerrar"); btn.clicked.connect(self.accept)
        layout.addWidget(btn)
        self.setLayout(layout)