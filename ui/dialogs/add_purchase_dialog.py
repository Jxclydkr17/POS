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
        self.setMinimumWidth(920)
        self.setMinimumHeight(660)
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

        # Fila de entrada: Producto | Cant | Costo unit | %Desc | %IVA | [Agregar]
        add_line_layout = QHBoxLayout()

        # -- Buscador de producto --
        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText("🔍 Buscar por nombre o código...")
        self.product_search.setMinimumWidth(180)
        self.product_search.textChanged.connect(self._on_search_changed)
        self.product_search.installEventFilter(self)
        add_line_layout.addWidget(QLabel("Producto:"))
        add_line_layout.addWidget(self.product_search)

        # Dropdown de busqueda - widget flotante sin robar foco
        self._search_popup = QListWidget(self)
        self._search_popup.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self._search_popup.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._search_popup.setFocusPolicy(Qt.NoFocus)
        self._search_popup.setFixedHeight(180)
        self._search_popup.setStyleSheet("""
            QListWidget {
                border: 2px solid #3c6e9e;
                background-color: #1e1e2e;
                color: #f0f0f0;
                font-size: 13px;
            }
            QListWidget::item { padding: 4px 8px; }
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

        # -- % Descuento (NUEVO) --
        self.discount_spin = QDoubleSpinBox()
        self.discount_spin.setMinimum(0.0)
        self.discount_spin.setMaximum(100.0)
        self.discount_spin.setDecimals(2)
        self.discount_spin.setSuffix(" %")
        self.discount_spin.setValue(0.0)
        self.discount_spin.setFixedWidth(80)
        self.discount_spin.setToolTip(
            "Porcentaje de descuento por línea.\n"
            "Se aplica sobre el Subtotal Bruto antes de calcular el IVA.\n"
            "(Ej.: 10% → base imponible = Subtotal × 0.90)"
        )
        add_line_layout.addWidget(QLabel("Desc.:"))
        add_line_layout.addWidget(self.discount_spin)

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

        # ──────────────────────────────────────────────────────────────────
        # Tabla de líneas  (10 cols):
        # Producto | Cant. | Costo Unit. | Subtotal Bruto | % Desc. | Desc. ₡ | %IVA | IVA ₡ | Total | 🗑
        # ──────────────────────────────────────────────────────────────────
        self.items_table = QTableWidget()
        self.items_table.setColumnCount(10)
        self.items_table.setHorizontalHeaderLabels([
            "Producto", "Cant.", "Costo Unit.", "Subtotal Bruto",
            "% Desc.", "Desc. ₡", "%IVA", "IVA ₡", "Total", ""
        ])
        hh = self.items_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        # Columnas de ancho fijo (no se estiran)
        for col, width in [(1, 50), (4, 58), (5, 72), (6, 55), (9, 40)]:
            hh.setSectionResizeMode(col, QHeaderView.Fixed)
            self.items_table.setColumnWidth(col, width)
        self.items_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.setMaximumHeight(200)
        layout.addWidget(self.items_table)

        # --- Resumen de totales (subtotal bruto / descuento / IVA / total) ---
        totals_frame = QFrame()
        totals_frame.setStyleSheet(
            "QFrame { background-color: #1e1e2e; border-radius: 6px; padding: 4px; }"
        )
        totals_layout = QHBoxLayout(totals_frame)
        totals_layout.setContentsMargins(12, 6, 12, 6)

        self.lbl_subtotal = QLabel("Subtotal Bruto: ₡ 0.00")
        self.lbl_subtotal.setStyleSheet("font-size: 13px; color: #aaaaaa;")

        self.lbl_discount_total = QLabel("Descuento: ₡ 0.00")
        self.lbl_discount_total.setStyleSheet("font-size: 13px; color: #e67e22; font-weight: bold;")

        self.lbl_iva_total = QLabel("IVA: ₡ 0.00")
        self.lbl_iva_total.setStyleSheet("font-size: 13px; color: #f0ad4e;")

        self.lbl_total = QLabel("TOTAL: ₡ 0.00")
        self.lbl_total.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #28A745;"
        )

        totals_layout.addWidget(self.lbl_subtotal)
        totals_layout.addStretch()
        totals_layout.addWidget(self.lbl_discount_total)
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
        self._search_popup.setFixedWidth(max(self.product_search.width(), 350))
        self._search_popup.show()
        self._search_popup.raise_()

    def _on_product_selected(self, item):
        product = item.data(Qt.UserRole)
        self.selected_product = product
        self.product_search.blockSignals(True)
        self.product_search.setText(product["name"])
        self.product_search.blockSignals(False)
        self.cost_spin.setValue(float(product.get("cost") or 0.0))
        # Pre-seleccionar IVA del producto si está guardado, si no 13%
        # tax_rate se almacena como decimal (0.13) → convertir a entero %
        raw_iva = product.get("tax_rate") or product.get("iva")
        if raw_iva is not None:
            product_iva = round(float(raw_iva) * 100) if float(raw_iva) <= 1.0 else int(float(raw_iva))
        else:
            product_iva = 13
        idx = self.iva_combo.findData(int(product_iva))
        if idx >= 0:
            self.iva_combo.setCurrentIndex(idx)
        self._search_popup.hide()

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        # Cerrar el popup si el usuario presiona Escape o Tab
        if obj == self.product_search and event.type() == QEvent.KeyPress:
            from PySide6.QtCore import Qt as _Qt
            if event.key() in (_Qt.Key_Escape, _Qt.Key_Tab):
                self._search_popup.hide()
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
        discount_pct = self.discount_spin.value()       # 0.00 – 100.00
        iva_pct      = self.iva_combo.currentData()     # entero: 0, 1, 2, 4, 8 ó 13

        # ── Validar consistencia del IVA con el producto registrado ──
        registered_iva = self.selected_product.get("tax_rate")
        if registered_iva is not None:
            # tax_rate se guarda como decimal (0.13) → convertir a entero %
            registered_iva_pct = (
                round(float(registered_iva) * 100)
                if float(registered_iva) <= 1.0
                else int(float(registered_iva))
            )
            if int(iva_pct) != registered_iva_pct:
                QMessageBox.warning(
                    self,
                    "⚠️ IVA Inconsistente",
                    f"El producto «{product_name}» tiene registrado un IVA del "
                    f"{registered_iva_pct}%, pero seleccionaste {iva_pct}%.\n\n"
                    f"Corregí el IVA antes de agregar la línea."
                )
                return

        # ── Cálculo conforme facturación electrónica Costa Rica (V4.4) ──
        # 1. Subtotal bruto (base antes de descuentos)
        subtotal_bruto  = round(qty * unit_cost, 2)

        # 2. Monto del descuento
        discount_amount = round(subtotal_bruto * (discount_pct / 100), 2)

        # 3. Base imponible (subtotal neto = base para el IVA)
        subtotal_neto   = round(subtotal_bruto - discount_amount, 2)

        # 4. IVA calculado sobre la base imponible
        iva_amount      = round(subtotal_neto * (iva_pct / 100), 2)

        # 5. Total de la línea
        total_line      = round(subtotal_neto + iva_amount, 2)

        self.detail_rows.append({
            "product_id":      product_id,
            "product_name":    product_name,
            "quantity":        qty,
            "unit_cost":       unit_cost,
            "subtotal_bruto":  subtotal_bruto,
            "discount_pct":    discount_pct,
            "discount_amount": discount_amount,
            "subtotal_neto":   subtotal_neto,
            "iva_pct":         iva_pct,
            "iva_amount":      iva_amount,
            "total_line":      total_line,
        })

        # Limpiar campos para la próxima línea
        self.selected_product = None
        self.product_search.blockSignals(True)
        self.product_search.clear()
        self.product_search.blockSignals(False)
        self.cost_spin.setValue(0.0)
        self.qty_spin.setValue(1)
        self.discount_spin.setValue(0.0)          # ← reiniciar descuento
        self.iva_combo.setCurrentIndex(IVA_RATES.index(13))

        self._refresh_items_table()

    # -------------------------------------------------------
    # 🔄 Actualizar tabla y totales
    # -------------------------------------------------------
    def _refresh_items_table(self):
        self.items_table.setRowCount(len(self.detail_rows))

        grand_subtotal_bruto  = 0.0
        grand_discount_amount = 0.0
        grand_iva             = 0.0
        grand_total           = 0.0

        for row, item in enumerate(self.detail_rows):
            # Col 0 – Producto
            self.items_table.setItem(row, 0, QTableWidgetItem(item["product_name"]))

            # Col 1 – Cantidad
            qty_cell = QTableWidgetItem(str(item["quantity"]))
            qty_cell.setTextAlignment(Qt.AlignCenter)
            self.items_table.setItem(row, 1, qty_cell)

            # Col 2 – Costo unitario
            self.items_table.setItem(row, 2, QTableWidgetItem(f"₡ {item['unit_cost']:,.2f}"))

            # Col 3 – Subtotal bruto
            self.items_table.setItem(row, 3, QTableWidgetItem(f"₡ {item['subtotal_bruto']:,.2f}"))

            # Col 4 – % Descuento
            disc_pct_cell = QTableWidgetItem(f"{item['discount_pct']:.2f}%")
            disc_pct_cell.setTextAlignment(Qt.AlignCenter)
            if item["discount_pct"] > 0:
                disc_pct_cell.setForeground(Qt.yellow)
            self.items_table.setItem(row, 4, disc_pct_cell)

            # Col 5 – Monto descuento
            disc_amt_cell = QTableWidgetItem(f"₡ {item['discount_amount']:,.2f}")
            if item["discount_amount"] > 0:
                disc_amt_cell.setForeground(Qt.yellow)
            self.items_table.setItem(row, 5, disc_amt_cell)

            # Col 6 – % IVA
            iva_pct_cell = QTableWidgetItem(f"{item['iva_pct']}%")
            iva_pct_cell.setTextAlignment(Qt.AlignCenter)
            self.items_table.setItem(row, 6, iva_pct_cell)

            # Col 7 – IVA ₡
            self.items_table.setItem(row, 7, QTableWidgetItem(f"₡ {item['iva_amount']:,.2f}"))

            # Col 8 – Total línea
            total_cell = QTableWidgetItem(f"₡ {item['total_line']:,.2f}")
            total_cell.setForeground(Qt.green)
            self.items_table.setItem(row, 8, total_cell)

            # Col 9 – Botón eliminar
            btn_del = QPushButton("🗑️")
            btn_del.setFixedWidth(38)
            btn_del.clicked.connect(lambda checked, r=row: self._remove_line(r))
            self.items_table.setCellWidget(row, 9, btn_del)

            grand_subtotal_bruto  += item["subtotal_bruto"]
            grand_discount_amount += item["discount_amount"]
            grand_iva             += item["iva_amount"]
            grand_total           += item["total_line"]

        # Actualizar etiquetas de resumen
        self.lbl_subtotal.setText(f"Subtotal Bruto: ₡ {grand_subtotal_bruto:,.2f}")
        self.lbl_discount_total.setText(
            f"Descuento: ₡ {grand_discount_amount:,.2f}"
            if grand_discount_amount > 0
            else "Descuento: ₡ 0.00"
        )
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
                        "product_id":      item["product_id"],
                        "quantity":        item["quantity"],
                        "unit_cost":       item["unit_cost"],
                        "discount_pct":    item["discount_pct"],
                        "discount_amount": item["discount_amount"],
                        "iva_pct":         item["iva_pct"],
                        "iva_amount":      item["iva_amount"],
                        "total_line":      item["total_line"],
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