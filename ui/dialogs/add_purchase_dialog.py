from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QDateEdit, QComboBox, QMessageBox,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QSpinBox, QDoubleSpinBox, QListWidget,
    QListWidgetItem, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, QDate, QTimer
from ui.session_manager import session
from ui.utils.http_worker import api_call, run_async
from ui.api import BASE_URL

API_URL_PURCHASES = f"{BASE_URL}/purchases"
API_URL_SUPPLIERS = f"{BASE_URL}/suppliers"
API_URL_PRODUCTS  = f"{BASE_URL}/products"

# Tarifas de IVA disponibles en Costa Rica
IVA_RATES = [0, 1, 2, 4, 8, 13]


class AddPurchaseDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("➕ Agregar Factura / Compra")
        self.setMinimumWidth(780)
        self.setMinimumHeight(640)
        self.pdf_file_path = None
        self.products_list = []      # cache de productos
        self.detail_rows = []        # líneas de detalle actuales
        self.selected_product = None # producto seleccionado en el buscador

        self.setup_ui()
        self.load_suppliers()
        self.load_products()

    # -------------------------------------------------------
    # 🧠 INTERFAZ
    # -------------------------------------------------------
    def setup_ui(self):
        layout = QVBoxLayout()

        title = QLabel("Registrar Nueva Factura")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Proveedor
        self.supplier_combo = QComboBox()
        layout.addWidget(self._label("Proveedor"))
        layout.addWidget(self.supplier_combo)

        # Número de factura
        self.invoice_input = QLineEdit()
        layout.addWidget(self._label("Número de factura"))
        layout.addWidget(self.invoice_input)

        # Fechas
        dates_layout = QHBoxLayout()
        self.entry_date = QDateEdit()
        self.entry_date.setCalendarPopup(True)
        self.entry_date.setDate(QDate.currentDate())
        dates_layout.addWidget(self._label("F. Entrada"))
        dates_layout.addWidget(self.entry_date)

        self.due_date = QDateEdit()
        self.due_date.setCalendarPopup(True)
        self.due_date.setDate(QDate.currentDate())
        dates_layout.addWidget(self._label("F. Vencimiento"))
        dates_layout.addWidget(self.due_date)
        layout.addLayout(dates_layout)

        # --------------------------
        # Líneas de detalle
        # --------------------------
        layout.addWidget(self._label("📦 Detalle de productos (opcional)"))

        # Fila de entrada: Producto | Cant | Costo unit | %IVA | [Agregar]
        add_line_layout = QHBoxLayout()

        # -- Buscador de producto --
        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText("🔍 Buscar por nombre o código de barras...")
        self.product_search.setMinimumWidth(200)
        self.product_search.textChanged.connect(self._on_search_changed)
        self.product_search.installEventFilter(self)
        add_line_layout.addWidget(QLabel("Producto:"))
        add_line_layout.addWidget(self.product_search)

        # Popup de búsqueda
        self._search_popup = QListWidget(self)
        self._search_popup.setWindowFlags(Qt.Popup)
        self._search_popup.setFocusPolicy(Qt.NoFocus)
        self._search_popup.setMaximumHeight(180)
        self._search_popup.setStyleSheet("""
            QListWidget {
                border: 1px solid #555;
                background-color: #2b2b2b;
                color: #f0f0f0;
                font-size: 13px;
            }
            QListWidget::item:hover { background-color: #3c6e9e; }
            QListWidget::item:selected { background-color: #1a5276; }
        """)
        self._search_popup.itemClicked.connect(self._on_product_selected)
        self._search_popup.hide()

        # -- Cantidad --
        self.qty_spin = QSpinBox()
        self.qty_spin.setMinimum(1)
        self.qty_spin.setMaximum(99999)
        self.qty_spin.setValue(1)
        add_line_layout.addWidget(QLabel("Cant:"))
        add_line_layout.addWidget(self.qty_spin)

        # -- Costo unitario --
        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setMinimum(0.0)
        self.cost_spin.setMaximum(99999999.99)
        self.cost_spin.setDecimals(2)
        self.cost_spin.setPrefix("₡ ")
        add_line_layout.addWidget(QLabel("Costo unit:"))
        add_line_layout.addWidget(self.cost_spin)

        # -- % IVA --
        self.iva_combo = QComboBox()
        self.iva_combo.setFixedWidth(72)
        for rate in IVA_RATES:
            self.iva_combo.addItem(f"{rate}%", rate)
        # Dejar por defecto el 13% (índice 5)
        self.iva_combo.setCurrentIndex(IVA_RATES.index(13))
        add_line_layout.addWidget(QLabel("IVA:"))
        add_line_layout.addWidget(self.iva_combo)

        # -- Botón agregar --
        btn_add_line = QPushButton("➕ Agregar línea")
        btn_add_line.setStyleSheet(
            "background-color: #28A745; color: white; font-weight: bold;"
            " padding: 4px 12px; border-radius: 4px;"
        )
        btn_add_line.clicked.connect(self.add_detail_line)
        add_line_layout.addWidget(btn_add_line)

        layout.addLayout(add_line_layout)

        # Tabla de líneas  (7 cols: Producto | Cant | Costo Unit. | Subtotal | %IVA | IVA ₡ | Total | 🗑)
        self.items_table = QTableWidget()
        self.items_table.setColumnCount(8)
        self.items_table.setHorizontalHeaderLabels([
            "Producto", "Cant.", "Costo Unit.", "Subtotal", "%IVA", "IVA ₡", "Total", ""
        ])
        hh = self.items_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        hh.setSectionResizeMode(7, QHeaderView.Fixed)
        self.items_table.setColumnWidth(1, 50)
        self.items_table.setColumnWidth(4, 55)
        self.items_table.setColumnWidth(7, 50)
        self.items_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.setMaximumHeight(200)
        layout.addWidget(self.items_table)

        # --- Resumen de totales (subtotal / IVA / total) ---
        totals_frame = QFrame()
        totals_frame.setStyleSheet(
            "QFrame { background-color: #1e1e2e; border-radius: 6px; padding: 4px; }"
        )
        totals_layout = QHBoxLayout(totals_frame)
        totals_layout.setContentsMargins(12, 6, 12, 6)

        self.lbl_subtotal = QLabel("Subtotal: ₡ 0.00")
        self.lbl_subtotal.setStyleSheet("font-size: 13px; color: #aaaaaa;")

        self.lbl_iva_total = QLabel("IVA: ₡ 0.00")
        self.lbl_iva_total.setStyleSheet("font-size: 13px; color: #f0ad4e;")

        self.lbl_total = QLabel("TOTAL: ₡ 0.00")
        self.lbl_total.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #28A745;"
        )

        totals_layout.addWidget(self.lbl_subtotal)
        totals_layout.addStretch()
        totals_layout.addWidget(self.lbl_iva_total)
        totals_layout.addStretch()
        totals_layout.addWidget(self.lbl_total)
        layout.addWidget(totals_frame)

        # Monto manual (fallback)
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("₡ (se autocalcula si hay líneas)")
        layout.addWidget(self._label("Monto total (manual si no hay detalle)"))
        layout.addWidget(self.amount_input)

        # Notas
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Notas / Observaciones (opcional)")
        self.notes_input.setMaximumHeight(60)
        layout.addWidget(self._label("Notas"))
        layout.addWidget(self.notes_input)

        # Botón PDF
        self.btn_pdf = QPushButton("📄 Adjuntar PDF (opcional)")
        self.btn_pdf.clicked.connect(self.select_pdf)
        layout.addWidget(self.btn_pdf)

        # Botones inferiores
        btn_layout = QHBoxLayout()
        btn_save   = QPushButton("💾 Guardar")
        btn_cancel = QPushButton("❌ Cancelar")
        btn_save.clicked.connect(self.save)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: bold; margin-top: 8px;")
        return lbl

    # -------------------------------------------------------
    # 📦 Cargar proveedores
    # -------------------------------------------------------
    def load_suppliers(self):
        headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
        api_call(
            "get", API_URL_SUPPLIERS, headers=headers,
            on_success=self._on_suppliers_loaded,
            on_error=lambda msg: QMessageBox.critical(
                self, "Error", f"No se pudieron cargar proveedores:\n{msg}"
            ),
        )

    def _on_suppliers_loaded(self, payload):
        suppliers = (
            payload.get("items", payload.get("data", []))
            if isinstance(payload, dict)
            else payload
        )
        self.supplier_combo.clear()
        for s in suppliers:
            self.supplier_combo.addItem(s["name"], s["id"])

    # -------------------------------------------------------
    # 📦 Cargar productos
    # -------------------------------------------------------
    def load_products(self):
        headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
        api_call(
            "get", API_URL_PRODUCTS, headers=headers,
            on_success=self._on_products_loaded,
            on_error=lambda msg: QMessageBox.critical(
                self, "Error", f"No se pudieron cargar productos:\n{msg}"
            ),
        )

    def _on_products_loaded(self, payload):
        if isinstance(payload, dict):
            self.products_list = payload.get("data", [])
            if isinstance(self.products_list, dict):
                self.products_list = self.products_list.get("items", [])
        else:
            self.products_list = payload

    # -------------------------------------------------------
    # 🔍 Buscador de productos
    # -------------------------------------------------------
    def _on_search_changed(self, text):
        text = text.strip().lower()
        self._search_popup.clear()

        if not text:
            self._search_popup.hide()
            return

        results = [
            p for p in self.products_list
            if text in p.get("name", "").lower()
            or text in str(p.get("barcode", "")).lower()
            or text in str(p.get("code", "")).lower()
        ]

        if not results:
            self._search_popup.hide()
            return

        for p in results[:20]:
            barcode = p.get("barcode") or p.get("code") or ""
            label = p["name"]
            if barcode:
                label += f"  [{barcode}]"
            label += f"  —  Stock: {p.get('stock', 0)}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, p)
            self._search_popup.addItem(item)

        pos = self.product_search.mapToGlobal(self.product_search.rect().bottomLeft())
        self._search_popup.move(pos)
        self._search_popup.setFixedWidth(self.product_search.width())
        self._search_popup.show()

    def _on_product_selected(self, item):
        product = item.data(Qt.UserRole)
        self.selected_product = product
        self.product_search.blockSignals(True)
        self.product_search.setText(product["name"])
        self.product_search.blockSignals(False)
        self.cost_spin.setValue(float(product.get("cost") or 0.0))
        # Pre-seleccionar IVA del producto si está guardado, si no 13 %
        product_iva = product.get("tax_rate") or product.get("iva") or 13
        idx = self.iva_combo.findData(int(product_iva))
        if idx >= 0:
            self.iva_combo.setCurrentIndex(idx)
        self._search_popup.hide()

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj == self.product_search and event.type() == QEvent.FocusOut:
            QTimer.singleShot(150, self._search_popup.hide)
        return super().eventFilter(obj, event)

    # -------------------------------------------------------
    # ➕ Agregar línea de detalle
    # -------------------------------------------------------
    def add_detail_line(self):
        if self.selected_product is None:
            QMessageBox.warning(self, "Atención", "Selecciona un producto desde el buscador.")
            return

        product_id   = self.selected_product["id"]
        product_name = self.selected_product["name"]
        qty          = self.qty_spin.value()
        unit_cost    = self.cost_spin.value()
        iva_pct      = self.iva_combo.currentData()   # entero: 0, 1, 2, 4, 8 ó 13

        # ── Validar consistencia del IVA con el producto registrado ──
        registered_iva = self.selected_product.get("tax_rate")
        if registered_iva is not None:
            if int(iva_pct) != int(registered_iva):
                QMessageBox.warning(
                    self,
                    "⚠️ IVA Inconsistente",
                    f"El producto «{product_name}» tiene registrado un IVA del "
                    f"{int(registered_iva)}%, pero seleccionaste {iva_pct}%.\n\n"
                    f"Corregí el IVA antes de agregar la línea."
                )
                return

        subtotal     = round(qty * unit_cost, 2)
        iva_amount   = round(subtotal * iva_pct / 100, 2)
        total_line   = round(subtotal + iva_amount, 2)

        self.detail_rows.append({
            "product_id":   product_id,
            "product_name": product_name,
            "quantity":     qty,
            "unit_cost":    unit_cost,
            "subtotal":     subtotal,
            "iva_pct":      iva_pct,
            "iva_amount":   iva_amount,
            "total_line":   total_line,
        })

        # Limpiar campos para la próxima línea
        self.selected_product = None
        self.product_search.blockSignals(True)
        self.product_search.clear()
        self.product_search.blockSignals(False)
        self.cost_spin.setValue(0.0)
        self.qty_spin.setValue(1)
        self.iva_combo.setCurrentIndex(IVA_RATES.index(13))

        self._refresh_items_table()

    # -------------------------------------------------------
    # 🔄 Actualizar tabla y totales
    # -------------------------------------------------------
    def _refresh_items_table(self):
        self.items_table.setRowCount(len(self.detail_rows))

        grand_subtotal = 0.0
        grand_iva      = 0.0
        grand_total    = 0.0

        for row, item in enumerate(self.detail_rows):
            self.items_table.setItem(row, 0, QTableWidgetItem(item["product_name"]))
            self.items_table.setItem(row, 1, QTableWidgetItem(str(item["quantity"])))
            self.items_table.setItem(row, 2, QTableWidgetItem(f"₡ {item['unit_cost']:,.2f}"))
            self.items_table.setItem(row, 3, QTableWidgetItem(f"₡ {item['subtotal']:,.2f}"))

            iva_cell = QTableWidgetItem(f"{item['iva_pct']}%")
            iva_cell.setTextAlignment(Qt.AlignCenter)
            self.items_table.setItem(row, 4, iva_cell)

            self.items_table.setItem(row, 5, QTableWidgetItem(f"₡ {item['iva_amount']:,.2f}"))
            self.items_table.setItem(row, 6, QTableWidgetItem(f"₡ {item['total_line']:,.2f}"))

            btn_del = QPushButton("🗑️")
            btn_del.setFixedWidth(40)
            btn_del.clicked.connect(lambda checked, r=row: self._remove_line(r))
            self.items_table.setCellWidget(row, 7, btn_del)

            grand_subtotal += item["subtotal"]
            grand_iva      += item["iva_amount"]
            grand_total    += item["total_line"]

        # Actualizar etiquetas de resumen
        self.lbl_subtotal.setText(f"Subtotal: ₡ {grand_subtotal:,.2f}")
        self.lbl_iva_total.setText(f"IVA: ₡ {grand_iva:,.2f}")
        self.lbl_total.setText(f"TOTAL: ₡ {grand_total:,.2f}")

        # Llenar campo de monto manual con el total con IVA
        if self.detail_rows:
            self.amount_input.setText(f"{grand_total:.2f}")

    def _remove_line(self, row):
        if 0 <= row < len(self.detail_rows):
            self.detail_rows.pop(row)
            self._refresh_items_table()

    # -------------------------------------------------------
    # 📄 Seleccionar PDF
    # -------------------------------------------------------
    def select_pdf(self):
        file, _ = QFileDialog.getOpenFileName(self, "Seleccionar PDF", "", "PDF Files (*.pdf)")
        if file:
            self.pdf_file_path = file
            self.btn_pdf.setText("📄 PDF seleccionado ✔")

    # -------------------------------------------------------
    # 💾 GUARDAR FACTURA
    # -------------------------------------------------------
    def save(self):
        try:
            invoice     = self.invoice_input.text().strip()
            amount_text = self.amount_input.text().strip()

            if not invoice:
                QMessageBox.warning(self, "Atención", "El número de factura es obligatorio.")
                return

            if not self.detail_rows and not amount_text:
                QMessageBox.warning(
                    self, "Atención",
                    "Agregue líneas de detalle o ingrese un monto manual."
                )
                return

            amount = float(amount_text) if amount_text else 0.0

            data = {
                "invoice_number": invoice,
                "supplier_id":    self.supplier_combo.currentData(),
                "entry_date":     self.entry_date.date().toString("yyyy-MM-dd"),
                "due_date":       self.due_date.date().toString("yyyy-MM-dd"),
                "amount":         amount,
                "notes":          self.notes_input.toPlainText(),
            }

            if self.detail_rows:
                data["items"] = [
                    {
                        "product_id": item["product_id"],
                        "quantity":   item["quantity"],
                        "unit_cost":  item["unit_cost"],
                        "iva_pct":    item["iva_pct"],
                        "iva_amount": item["iva_amount"],
                        "total_line": item["total_line"],
                    }
                    for item in self.detail_rows
                ]

            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}

            api_call(
                "post", API_URL_PURCHASES, json=data, headers=headers,
                on_success=lambda resp: self._on_purchase_saved(resp, headers),
                on_error=lambda msg: QMessageBox.critical(
                    self, "Error", f"No se pudo guardar la factura:\n{msg}"
                ),
            )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo guardar la factura:\n{e}")

    def _on_purchase_saved(self, response_data, headers):
        if isinstance(response_data, dict) and "data" in response_data:
            purchase_id = response_data["data"]["id"]
        else:
            purchase_id = response_data.get("id") if isinstance(response_data, dict) else None

        if self.pdf_file_path and purchase_id:
            pdf_path = self.pdf_file_path

            def _do_upload():
                import requests as _req
                with open(pdf_path, "rb") as f:
                    _req.post(
                        f"{API_URL_PURCHASES}/{purchase_id}/upload-pdf",
                        files={"file": f}, headers=headers,
                        timeout=(5, 15),
                    )

            run_async(_do_upload)

        QMessageBox.information(self, "Éxito", "Factura registrada correctamente.")
        self.accept()