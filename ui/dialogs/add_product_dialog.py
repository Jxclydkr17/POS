from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QComboBox
)
from PySide6.QtCore import Qt, QEvent, QTimer
import requests
from decimal import Decimal
from ui.session_manager import session
from ui.api import BASE_URL


API_URL = f"{BASE_URL}/products"
CATEGORIES_URL = f"{BASE_URL}/categories"
SUPPLIERS_URL = f"{BASE_URL}/suppliers"
CABYS_SEARCH_URL = f"{BASE_URL}/cabys/search"


IVA_TYPES = [
    "Impuesto de valor agregado",
    "Impuesto selectivo de consumo",
    "Impuesto único a los combustibles",
    "Impuesto específico de bebidas alcohólicas",
    "Impuesto específico sobre bebidas envasadas sin alcohol y jabones",
    "Impuestos a productos de tabaco",
    "IVA (cálculo especial)",
    "IVA régimen de bienes usados (factor)",
    "Impuesto específico al cemento",
    "Otros"
]

IVA_RATES = {
    "Tarifa general 13%": 0.13,
    "Tarifa reducida 1%": 0.01,
    "Tarifa reducida 2%": 0.02,
    "Tarifa reducida 4%": 0.04,
    "Tarifa reducida 0.5%": 0.005,
    "Tarifa 0% (Artículo 32, num 1, RLIVA)": 0.00,
    "Tarifa Exenta": None,
    "Tarifa 0% sin derecho a crédito": 0.00,
}


class AddProductDialog(QDialog):
    def __init__(self, initial_data: dict | None = None, duplicate_mode: bool = False):
        super().__init__()
        self.initial_data = initial_data or {}
        self.duplicate_mode = duplicate_mode

        self.setWindowTitle("Duplicar producto" if self.duplicate_mode else "Agregar nuevo producto")
        self.setFixedSize(820, 780)

        self.categories = []
        self.suppliers = []
        self.barcode_reading = False  # Flag para detectar lectura de código
        self.barcode_timer = QTimer()
        self.barcode_timer.setSingleShot(True)
        self.barcode_timer.timeout.connect(self._finish_barcode_scan)

        self.setup_ui()
        self.load_categories()
        self.load_suppliers()

        if self.initial_data:
            self.fill_initial_data()

    def setup_ui(self):
        self.layout_main = QVBoxLayout()
        self.layout_main.setAlignment(Qt.AlignTop)
        self.layout_main.setContentsMargins(20, 25, 20, 20)

        title_text = "📄 Duplicar Producto" if self.duplicate_mode else "➕ Agregar Nuevo Producto"
        title = QLabel(title_text)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #5B9BD5;")
        self.layout_main.addWidget(title)

        # Contenedor de 2 columnas
        form_layout = QHBoxLayout()
        left_col = QVBoxLayout()
        right_col = QVBoxLayout()

        # Columna izquierda
        self.code_input = self.add_input_inline("Código", left_col)
        self.barcode_input = self.add_input_inline("Código de barras", left_col)
        self.barcode_input.textChanged.connect(self._on_barcode_changed)

        self.name_input = self.add_input_inline("Nombre del producto", left_col)
        self.description_input = self.add_input_inline("Descripción", left_col)

        self.cabys_name_input = self.add_input_inline("Nombre CABYS", left_col)
        self.cabys_input = self.add_input_inline("Código CABYS", left_col)

        self.search_cabys_btn = QPushButton("🔍 Buscar CABYS")
        self.search_cabys_btn.setAutoDefault(False)
        self.search_cabys_btn.setDefault(False)
        self.search_cabys_btn.clicked.connect(self.search_cabys)
        left_col.addWidget(self.search_cabys_btn)

        self.category_combo = QComboBox()
        self.add_combo_inline("Categoría", self.category_combo, left_col)

        self.supplier_combo = QComboBox()
        self.add_combo_inline("Proveedor", self.supplier_combo, left_col)

        # Imagen
        from ui.components.product_image_widget import ProductImageWidget
        self.image_widget = ProductImageWidget()
        left_col.addWidget(self.image_widget)

        # Columna derecha
        self.tax_type_combo = QComboBox()
        self.tax_type_combo.addItems(IVA_TYPES)
        self.add_combo_inline("Tipo IVA", self.tax_type_combo, right_col)

        self.tax_rate_combo = QComboBox()
        self.tax_rate_combo.addItems(list(IVA_RATES.keys()))
        self.add_combo_inline("Tarifa IVA", self.tax_rate_combo, right_col)

        self.cost_input = self.add_input_inline("Costo", right_col)
        self.utilidad_input = self.add_input_inline("Utilidad %", right_col)
        self.price_input = self.add_input_inline("Precio", right_col)
        self.stock_input = self.add_input_inline("Stock", right_col)
        self.min_stock_input = self.add_input_inline("Stock mínimo", right_col)
        self.min_stock_input.setText("3")

        # 📏 Unidad de medida
        self.unit_type_combo = QComboBox()
        self.unit_type_combo.addItem("Unid — Unidades", "Unid")
        self.unit_type_combo.addItem("Kg — Kilogramos", "Kg")
        self.unit_type_combo.addItem("g — Gramos", "g")
        self.unit_type_combo.addItem("m — Metros", "m")
        self.unit_type_combo.addItem("cm — Centímetros", "cm")
        self.unit_type_combo.addItem("L — Litros", "L")
        self.unit_type_combo.addItem("mL — Mililitros", "mL")
        self.add_combo_inline("Unidad medida", self.unit_type_combo, right_col)

        # Añadir columnas
        form_layout.addLayout(left_col)
        form_layout.addLayout(right_col)
        self.layout_main.addLayout(form_layout)

        # Conexiones para cálculos
        self.cost_input.textChanged.connect(self.recalculate_price)
        self.utilidad_input.textChanged.connect(self.recalculate_price)
        self.tax_rate_combo.currentTextChanged.connect(self.recalculate_price)
        self.price_input.textChanged.connect(self.recalculate_utilidad_from_price)

        # Botones
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("💾 Guardar")
        self.btn_save.setDefault(False)
        self.btn_save.setAutoDefault(False)
        self.btn_save.setStyleSheet("background-color: #28A745; padding: 10px; color: white; font-weight: bold;")
        self.btn_save.clicked.connect(self.save_product)

        btn_cancel = QPushButton("❌ Cancelar")
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_cancel.setStyleSheet("background-color: #DC3545; padding: 10px; color: white; font-weight: bold;")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(btn_cancel)
        self.layout_main.addLayout(btn_layout)

        self.setLayout(self.layout_main)
        self.name_input.setFocus()

    def _format_stock_value(self, value):
        """Formatea un valor de stock quitando decimales innecesarios.
        Ej: '5.000' → '5', '2.500' → '2.5', None → '0'
        """
        try:
            num = float(value or 0)
            if num == int(num):
                return str(int(num))
            return str(round(num, 3)).rstrip('0').rstrip('.')
        except (ValueError, TypeError):
            return str(value)

    def fill_initial_data(self):
        p = self.initial_data

        self.code_input.setText("" if self.duplicate_mode else (p.get("code", "") or ""))
        self.barcode_input.setText("" if self.duplicate_mode else (p.get("barcode", "") or ""))
        self.name_input.setText(p.get("name", "") or "")
        self.description_input.setText(p.get("description", "") or "")
        self.cabys_input.setText(p.get("cabys_code", "") or "")
        self.cabys_name_input.setText(p.get("cabys_name", "") or "")
        self.image_widget.set_path(p.get("image_path", "") or "")

        self.cost_input.setText(str(p.get("cost", "") or ""))
        self.price_input.setText(str(p.get("price", "") or ""))
        self.stock_input.setText("0" if self.duplicate_mode else self._format_stock_value(p.get("stock", 0)))
        self.min_stock_input.setText(self._format_stock_value(p.get("min_stock", 3)))

        # 📏 Unidad de medida
        unit_type = p.get("unit_type", "Unid") or "Unid"
        idx = self.unit_type_combo.findData(unit_type)
        if idx >= 0:
            self.unit_type_combo.setCurrentIndex(idx)

        utilidad = p.get("utility_percentage")
        if utilidad is None:
            try:
                cost = float(p.get("cost") or 0)
                price = float(p.get("price") or 0)
                iva = p.get("tax_rate")
                iva = float(iva) if iva is not None else 0.0

                if cost > 0:
                    base = price / (1 + iva)
                    utilidad = ((base - cost) / cost) * 100
            except Exception:
                utilidad = ""

        self.utilidad_input.setText("" if utilidad in (None, "") else str(round(float(utilidad), 2)))

        cat_id = p.get("category_id")
        idx = self.category_combo.findData(cat_id)
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)

        sup_id = p.get("supplier_id")
        idx = self.supplier_combo.findData(sup_id)
        if idx >= 0:
            self.supplier_combo.setCurrentIndex(idx)

        tax_type = p.get("tax_type")
        if tax_type:
            idx = self.tax_type_combo.findText(tax_type)
            if idx >= 0:
                self.tax_type_combo.setCurrentIndex(idx)

        self.select_iva_label(p.get("tax_rate"))

        if self.duplicate_mode:
            self.name_input.setFocus()
            self.name_input.selectAll()

    def add_input_inline(self, label_text, layout):
        label = QLabel(label_text)
        label.setStyleSheet("font-weight: bold; color: #E0E0E0; margin-top: 6px;")

        field = QLineEdit()
        field.setPlaceholderText(label_text)
        field.setFixedHeight(30)

        layout.addWidget(label)
        layout.addWidget(field)
        return field

    def add_combo_inline(self, label_text, combo, layout):
        label = QLabel(label_text)
        label.setStyleSheet("font-weight: bold; color: #E0E0E0; margin-top: 6px;")
        combo.setFixedHeight(30)

        layout.addWidget(label)
        layout.addWidget(combo)

    def load_categories(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"}
            r = requests.get(CATEGORIES_URL, headers=headers)
            data = r.json()["data"]

            self.category_combo.clear()
            self.categories = data

            for c in data:
                self.category_combo.addItem(c["name"], c["id"])

        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudieron cargar categorías:\n{e}")

    def load_suppliers(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            resp = requests.get(SUPPLIERS_URL, headers=headers)

            if resp.status_code != 200:
                QMessageBox.warning(self, "Error", f"No se pudieron cargar los proveedores.\n{resp.text}")
                return

            data = resp.json()
            suppliers = data.get("items", data) if isinstance(data, dict) else data

            self.supplier_combo.clear()

            for supplier in suppliers:
                if not supplier.get("is_active", True):
                    continue

                self.supplier_combo.addItem(supplier["name"], supplier["id"])

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al cargar proveedores:\n{e}")

    def save_product(self):
        try:
            label = self.tax_rate_combo.currentText()
            tax_rate = IVA_RATES.get(label)

            unit = self.unit_type_combo.currentData() or "Unid"
            is_unit = unit == "Unid"

            try:
                min_stock_value = float(self.min_stock_input.text() or 3)
                if min_stock_value < 0:
                    QMessageBox.warning(self, "Error", "El stock mínimo no puede ser negativo.")
                    return
                if is_unit and min_stock_value != int(min_stock_value):
                    QMessageBox.warning(self, "Error", "El stock mínimo debe ser un número entero para productos vendidos por unidad.")
                    return
            except ValueError:
                QMessageBox.warning(self, "Error", "El stock mínimo debe ser un número válido.")
                return

            try:
                stock_value = float(self.stock_input.text() or 0)
                if stock_value < 0:
                    QMessageBox.warning(self, "Error", "El stock no puede ser negativo.")
                    return
                if is_unit and stock_value != int(stock_value):
                    QMessageBox.warning(self, "Error", "El stock debe ser un número entero para productos vendidos por unidad.")
                    return
            except ValueError:
                QMessageBox.warning(self, "Error", "El stock debe ser un número válido.")
                return

            data = {
                "code": self.code_input.text() or None,
                "barcode": self.barcode_input.text() or None,
                "name": self.name_input.text().strip(),
                "description": self.description_input.text() or None,
                "category_id": self.category_combo.currentData(),
                "supplier_id": self.supplier_combo.currentData(),
                "tax_type": self.tax_type_combo.currentText(),
                "tax_rate": tax_rate,
                "cabys_code": self.cabys_input.text() or None,
                "cabys_name": self.cabys_name_input.text() or None,
                "cost": float(self.cost_input.text() or 0),
                "price": float(self.price_input.text() or 0),
                "stock": stock_value,
                "min_stock": min_stock_value,
                "unit_type": unit,
                "image_path": self.image_widget.get_path() or None,
            }

            if not data["name"] or data["price"] <= 0:
                QMessageBox.warning(self, "Error", "Nombre y precio son obligatorios.")
                return

            if not data["cabys_code"]:
                QMessageBox.warning(self, "CABYS", "Debe seleccionar un código CABYS.")
                return

            headers = {"Authorization": f"Bearer {session.token}"}
            r = requests.post(API_URL, json=data, headers=headers)
            resp = r.json()

            if r.status_code == 200:
                QMessageBox.information(self, "Éxito", resp["message"])
                self.accept()
            else:
                QMessageBox.critical(self, "Error", str(resp))

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def recalculate_price(self):
        try:
            cost = float(self.cost_input.text())
            utilidad = float(self.utilidad_input.text())
            iva = self._parse_iva()

            base = cost * (1 + utilidad / 100)
            price = base * (1 + iva)

            self.price_input.blockSignals(True)
            self.price_input.setText(str(round(price, 2)))
            self.price_input.blockSignals(False)

            self.price_input.setStyleSheet("""
                QLineEdit {
                    background-color: #1E3D2B;
                    color: #7CFF9B;
                    font-weight: bold;
                }
            """)
        except:
            pass

    def recalculate_utilidad_from_price(self):
        try:
            cost = float(self.cost_input.text())
            price = float(self.price_input.text())
            iva = self._parse_iva()

            base = price / (1 + iva)
            utilidad = ((base - cost) / cost) * 100

            self.utilidad_input.blockSignals(True)
            self.utilidad_input.setText(str(round(utilidad, 2)))
            self.utilidad_input.blockSignals(False)

            self.price_input.setStyleSheet("")
        except:
            pass

    def search_cabys(self):
        keyword = self.cabys_name_input.text().strip() or self.cabys_input.text().strip()

        if not keyword:
            QMessageBox.warning(self, "CABYS", "Escriba el nombre o el código CABYS para buscar.")
            return

        headers = {"Authorization": f"Bearer {session.token}"}
        params = {"q": keyword}

        try:
            resp = requests.get(CABYS_SEARCH_URL, headers=headers, params=params)
            payload = resp.json()
            data = payload.get("data", [])

            if not data:
                QMessageBox.information(self, "CABYS", "No se encontraron coincidencias.")
                return

            from ui.dialogs.cabys_selector_dialog import CabysSelectorDialog

            dialog = CabysSelectorDialog(data)

            if dialog.exec() == QDialog.Accepted:
                cabys = dialog.selected
                self.cabys_input.setText(cabys["code"])

                iva_db = int(cabys["iva"])
                mapa_iva = {
                    0: "Tarifa 0% (Artículo 32, num 1, RLIVA)",
                    1: "Tarifa reducida 1%",
                    2: "Tarifa reducida 2%",
                    4: "Tarifa reducida 4%",
                    13: "Tarifa general 13%"
                }

                label = mapa_iva.get(iva_db, "Tarifa general 13%")
                self.tax_rate_combo.setCurrentText(label)

        except Exception as e:
            QMessageBox.critical(self, "Error CABYS", str(e))

    def _parse_iva(self):
        label = self.tax_rate_combo.currentText()
        value = IVA_RATES.get(label)
        return value if value is not None else 0.0

    def select_iva_label(self, rate_value):
        if rate_value is None:
            self.tax_rate_combo.setCurrentIndex(0)
            return

        try:
            rate_value = float(rate_value)
        except:
            self.tax_rate_combo.setCurrentIndex(0)
            return

        for label, value in IVA_RATES.items():
            if value is not None and abs(float(value) - rate_value) < 0.000001:
                idx = self.tax_rate_combo.findText(label)
                if idx >= 0:
                    self.tax_rate_combo.setCurrentIndex(idx)
                    return

        self.tax_rate_combo.setCurrentIndex(0)

    def _on_barcode_changed(self):
        """Detecta cuando empieza a escribirse en el campo de barras"""
        text = self.barcode_input.text()

        if len(text) > 0:
            # Activar modo de lectura de código
            self.barcode_reading = True
            # Reiniciar timer (500ms después de la última tecla)
            self.barcode_timer.start(500)

    def _finish_barcode_scan(self):
        """Se ejecuta cuando termina la lectura del código"""
        self.barcode_reading = False
        # Mover foco al siguiente campo
        if len(self.barcode_input.text()) >= 6:
            self.name_input.setFocus()

    def event(self, event):
        """Intercepta TODOS los eventos antes de que lleguen a los widgets"""
        if event.type() == QEvent.KeyPress:
            key = event.key()

            # Si estamos en modo lectura de código y es Enter/Return
            if self.barcode_reading and key in (Qt.Key_Return, Qt.Key_Enter):
                # Consumir el evento inmediatamente
                event.accept()
                return True

            # Si el foco está en el campo de barras y es Enter/Return/Escape
            if self.barcode_input.hasFocus() and key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
                event.accept()
                return True

        # Dejar pasar el resto de eventos normalmente
        return super().event(event)

    def keyPressEvent(self, event):
        """Protección adicional a nivel de diálogo"""
        key = event.key()

        # Si estamos leyendo código o el foco está en barras
        if self.barcode_reading or self.barcode_input.hasFocus():
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
                event.ignore()
                return

        # Comportamiento por defecto
        super().keyPressEvent(event)