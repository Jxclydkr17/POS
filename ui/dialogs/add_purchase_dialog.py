from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QDateEdit, QComboBox, QMessageBox,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QSpinBox, QDoubleSpinBox,
)
from PySide6.QtCore import Qt, QDate
import requests
from ui.session_manager import session
from ui.api import BASE_URL

API_URL_PURCHASES = f"{BASE_URL}/purchases"
API_URL_SUPPLIERS = f"{BASE_URL}/suppliers"
API_URL_PRODUCTS = f"{BASE_URL}/products"


class AddPurchaseDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("➕ Agregar Factura / Compra")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)
        self.pdf_file_path = None
        self.products_list = []  # cache de productos
        self.detail_rows = []    # líneas de detalle actuales

        self.setup_ui()
        self.load_suppliers()
        self.load_products()

    # ----------------------------------------------------
    # 🧠 INTERFAZ
    # ----------------------------------------------------
    def setup_ui(self):
        layout = QVBoxLayout()

        title = QLabel("Registrar Nueva Factura")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # --------------------------
        # Campos del encabezado
        # --------------------------
        self.supplier_combo = QComboBox()
        layout.addWidget(self._label("Proveedor"))
        layout.addWidget(self.supplier_combo)

        self.invoice_input = QLineEdit()
        layout.addWidget(self._label("Número de factura"))
        layout.addWidget(self.invoice_input)

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

        # Fila para agregar línea
        add_line_layout = QHBoxLayout()

        self.product_combo = QComboBox()
        self.product_combo.setMinimumWidth(200)
        add_line_layout.addWidget(QLabel("Producto:"))
        add_line_layout.addWidget(self.product_combo)

        self.qty_spin = QSpinBox()
        self.qty_spin.setMinimum(1)
        self.qty_spin.setMaximum(99999)
        self.qty_spin.setValue(1)
        add_line_layout.addWidget(QLabel("Cant:"))
        add_line_layout.addWidget(self.qty_spin)

        self.cost_spin = QDoubleSpinBox()
        self.cost_spin.setMinimum(0.0)
        self.cost_spin.setMaximum(99999999.99)
        self.cost_spin.setDecimals(2)
        self.cost_spin.setPrefix("₡ ")
        add_line_layout.addWidget(QLabel("Costo unit:"))
        add_line_layout.addWidget(self.cost_spin)

        btn_add_line = QPushButton("➕ Agregar línea")
        btn_add_line.setStyleSheet("background-color: #28A745; color: white; font-weight: bold; padding: 4px 12px; border-radius: 4px;")
        btn_add_line.clicked.connect(self.add_detail_line)
        add_line_layout.addWidget(btn_add_line)

        layout.addLayout(add_line_layout)

        # Tabla de líneas
        self.items_table = QTableWidget()
        self.items_table.setColumnCount(5)
        self.items_table.setHorizontalHeaderLabels([
            "Producto", "Cantidad", "Costo Unit.", "Subtotal", ""
        ])
        self.items_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.items_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.items_table.setColumnWidth(4, 60)
        self.items_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items_table.setMaximumHeight(180)
        layout.addWidget(self.items_table)

        # Total calculado
        self.total_label = QLabel("Total líneas: ₡ 0.00")
        self.total_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #28A745;")
        layout.addWidget(self.total_label)

        # --------------------------
        # Monto manual (fallback si no se usan líneas)
        # --------------------------
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("₡ (se autocalcula si hay líneas)")
        layout.addWidget(self._label("Monto total (manual si no hay detalle)"))
        layout.addWidget(self.amount_input)

        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Notas / Observaciones (opcional)")
        self.notes_input.setMaximumHeight(60)
        layout.addWidget(self._label("Notas"))
        layout.addWidget(self.notes_input)

        # --------------------------
        # Botón subir PDF
        # --------------------------
        self.btn_pdf = QPushButton("📄 Adjuntar PDF (opcional)")
        self.btn_pdf.clicked.connect(self.select_pdf)
        layout.addWidget(self.btn_pdf)

        # --------------------------
        # Botones inferiores
        # --------------------------
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("💾 Guardar")
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

    # ----------------------------------------------------
    # 📦 Cargar proveedores
    # ----------------------------------------------------
    def load_suppliers(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            res = requests.get(API_URL_SUPPLIERS, headers=headers)
            payload = res.json()

            if isinstance(payload, dict):
                suppliers = payload.get("items", payload.get("data", []))
            else:
                suppliers = payload

            self.supplier_combo.clear()
            for s in suppliers:
                self.supplier_combo.addItem(s["name"], s["id"])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudieron cargar proveedores:\n{e}")

    # ----------------------------------------------------
    # 📦 Cargar productos
    # ----------------------------------------------------
    def load_products(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            res = requests.get(API_URL_PRODUCTS, headers=headers)
            payload = res.json()

            if isinstance(payload, dict):
                self.products_list = payload.get("data", [])
                # Si data es un dict con "items", extraer items
                if isinstance(self.products_list, dict):
                    self.products_list = self.products_list.get("items", [])
            else:
                self.products_list = payload

            self.product_combo.clear()
            for p in self.products_list:
                display = f"{p['name']} (Stock: {p.get('stock', 0)})"
                self.product_combo.addItem(display, p["id"])

                # Pre-llenar costo si existe
            self.product_combo.currentIndexChanged.connect(self._on_product_changed)
            if self.products_list:
                self._on_product_changed(0)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudieron cargar productos:\n{e}")

    def _on_product_changed(self, index):
        if 0 <= index < len(self.products_list):
            product = self.products_list[index]
            cost = product.get("cost") or 0.0
            self.cost_spin.setValue(float(cost))

    # ----------------------------------------------------
    # ➕ Agregar línea de detalle
    # ----------------------------------------------------
    def add_detail_line(self):
        product_id = self.product_combo.currentData()
        if product_id is None:
            QMessageBox.warning(self, "Atención", "Selecciona un producto.")
            return

        product_name = self.product_combo.currentText()
        qty = self.qty_spin.value()
        unit_cost = self.cost_spin.value()
        subtotal = round(qty * unit_cost, 2)

        self.detail_rows.append({
            "product_id": product_id,
            "product_name": product_name,
            "quantity": qty,
            "unit_cost": unit_cost,
            "subtotal": subtotal,
        })

        self._refresh_items_table()

    def _refresh_items_table(self):
        self.items_table.setRowCount(len(self.detail_rows))
        total = 0.0

        for row, item in enumerate(self.detail_rows):
            self.items_table.setItem(row, 0, QTableWidgetItem(item["product_name"]))
            self.items_table.setItem(row, 1, QTableWidgetItem(str(item["quantity"])))
            self.items_table.setItem(row, 2, QTableWidgetItem(f"₡ {item['unit_cost']:.2f}"))
            self.items_table.setItem(row, 3, QTableWidgetItem(f"₡ {item['subtotal']:.2f}"))

            btn_del = QPushButton("🗑️")
            btn_del.setFixedWidth(50)
            btn_del.clicked.connect(lambda checked, r=row: self._remove_line(r))
            self.items_table.setCellWidget(row, 4, btn_del)

            total += item["subtotal"]

        self.total_label.setText(f"Total líneas: ₡ {total:,.2f}")

        # Auto-llenar monto si hay líneas
        if self.detail_rows:
            self.amount_input.setText(f"{total:.2f}")

    def _remove_line(self, row):
        if 0 <= row < len(self.detail_rows):
            self.detail_rows.pop(row)
            self._refresh_items_table()

    # ----------------------------------------------------
    # 📄 Seleccionar PDF
    # ----------------------------------------------------
    def select_pdf(self):
        file, _ = QFileDialog.getOpenFileName(self, "Seleccionar PDF", "", "PDF Files (*.pdf)")
        if file:
            self.pdf_file_path = file
            self.btn_pdf.setText("📄 PDF seleccionado ✔")

    # ----------------------------------------------------
    # 💾 GUARDAR FACTURA
    # ----------------------------------------------------
    def save(self):
        try:
            invoice = self.invoice_input.text().strip()
            amount_text = self.amount_input.text().strip()

            if not invoice:
                QMessageBox.warning(self, "Atención", "El número de factura es obligatorio.")
                return

            if not self.detail_rows and not amount_text:
                QMessageBox.warning(self, "Atención", "Agregue líneas de detalle o ingrese un monto manual.")
                return

            amount = float(amount_text) if amount_text else 0.0

            data = {
                "invoice_number": invoice,
                "supplier_id": self.supplier_combo.currentData(),
                "entry_date": self.entry_date.date().toString("yyyy-MM-dd"),
                "due_date": self.due_date.date().toString("yyyy-MM-dd"),
                "amount": amount,
                "notes": self.notes_input.toPlainText(),
            }

            # Agregar items si existen
            if self.detail_rows:
                data["items"] = [
                    {
                        "product_id": item["product_id"],
                        "quantity": item["quantity"],
                        "unit_cost": item["unit_cost"],
                    }
                    for item in self.detail_rows
                ]

            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}

            # 1. Crear factura
            res = requests.post(API_URL_PURCHASES, json=data, headers=headers)

            if res.status_code != 200:
                raise Exception(res.text)

            response_data = res.json()

            if isinstance(response_data, dict) and "data" in response_data:
                purchase_id = response_data["data"]["id"]
            else:
                purchase_id = response_data["id"]

            # 2. Subir PDF si corresponde
            if self.pdf_file_path:
                with open(self.pdf_file_path, "rb") as f:
                    files = {"file": f}
                    requests.post(
                        f"{API_URL_PURCHASES}/{purchase_id}/upload-pdf",
                        files=files,
                        headers=headers
                    )

            QMessageBox.information(self, "Éxito", "Factura registrada correctamente.")
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo guardar la factura:\n{e}")
