# ui/dialogs/create_proforma_dialog.py
"""
Diálogo para crear o editar una proforma/cotización.
Permite buscar productos, armar un carrito, seleccionar cliente,
agregar notas y definir días de vigencia.
No requiere caja abierta, método de pago ni tipo de documento.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QSpinBox, QTextEdit,
    QMessageBox, QCompleter, QFrame, QWidget, QInputDialog,
)
from PySide6.QtCore import Qt, QTimer, QStringListModel
from PySide6.QtGui import QDoubleValidator
import logging

from ui.api import BASE_URL
from ui.session_manager import session
from ui.components.toast_notifier import show_toast
from ui.utils.http_worker import api_call

logger = logging.getLogger(__name__)

API_PRODUCTS = f"{BASE_URL}/products/"
API_CUSTOMERS = f"{BASE_URL}/customers/"
API_PROFORMAS = f"{BASE_URL}/proformas"
CABYS_SEARCH_URL = f"{BASE_URL}/cabys/search"


class CreateProformaDialog(QDialog):
    """
    Diálogo para crear o editar proformas.
    Si proforma_id se pasa, carga los datos y entra en modo edición.
    """

    def __init__(self, parent=None, proforma_id=None):
        super().__init__(parent)
        self.proforma_id = proforma_id
        self.is_edit = proforma_id is not None

        self.setWindowTitle("✏️ Editar proforma" if self.is_edit else "📋 Nueva proforma")
        self.setMinimumSize(860, 640)
        self.resize(900, 680)

        self.cart = {}            # {product_id: {product, quantity, unit_price, discount_percent, ...}}
        self._common_seq = 0      # IDs negativos para productos comunes
        self.customers = []
        self.customer_name_to_id = {}
        self.selected_customer_id = None

        self._build_ui()
        self._load_customers()

        if self.is_edit:
            self._load_proforma_data()

        # debounce para búsqueda de productos
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._search_products)
        self.txt_product_search.textChanged.connect(lambda: self._search_timer.start(350))

    def _auth_headers(self):
        return {"Authorization": f"Bearer {session.token}"}

    # ══════════════════════════════════════════════════
    # UI
    # ══════════════════════════════════════════════════
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── Título ──
        title = QLabel("✏️ Editar proforma" if self.is_edit else "📋 Nueva proforma")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        # ── Cliente ──
        client_row = QHBoxLayout()
        client_row.addWidget(QLabel("Cliente:"))
        self.txt_customer = QLineEdit()
        self.txt_customer.setPlaceholderText("Buscar cliente por nombre…")
        self.txt_customer.setStyleSheet(
            "QLineEdit{background:#111827;color:#e5e7eb;border:1px solid #374151;"
            "border-radius:6px;padding:6px;}"
        )
        self._customer_completer = QCompleter()
        self._customer_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._customer_completer.setFilterMode(Qt.MatchContains)
        self.txt_customer.setCompleter(self._customer_completer)
        self.txt_customer.textChanged.connect(self._on_customer_text_changed)
        client_row.addWidget(self.txt_customer, 1)

        client_row.addWidget(QLabel("Vigencia (días):"))
        self.spn_validity = QSpinBox()
        self.spn_validity.setRange(1, 365)
        self.spn_validity.setValue(15)
        self.spn_validity.setFixedWidth(80)
        client_row.addWidget(self.spn_validity)

        root.addLayout(client_row)

        # ── Búsqueda de productos ──
        search_row = QHBoxLayout()
        self.txt_product_search = QLineEdit()
        self.txt_product_search.setPlaceholderText("🔎 Buscar producto por nombre o código…")
        self.txt_product_search.setStyleSheet(
            "QLineEdit{background:#111827;color:#e5e7eb;border:1px solid #374151;"
            "border-radius:6px;padding:6px;}"
        )
        search_row.addWidget(self.txt_product_search, 1)

        btn_add_common = QPushButton("📦 Producto común")
        btn_add_common.setToolTip("Agregar línea libre sin inventario")
        btn_add_common.setStyleSheet(
            "QPushButton{background:#334155;color:white;padding:6px 12px;"
            "border-radius:6px;} QPushButton:hover{background:#475569;}"
        )
        btn_add_common.clicked.connect(self._add_common_product)
        search_row.addWidget(btn_add_common)

        root.addLayout(search_row)

        # ── Resultados de búsqueda ──
        self.search_results = QTableWidget()
        self.search_results.setColumnCount(5)
        self.search_results.setHorizontalHeaderLabels(["Código", "Producto", "Precio", "Stock", ""])
        self.search_results.setMaximumHeight(150)
        self.search_results.setStyleSheet(
            "QTableWidget{background:#0f172a;color:#e5e7eb;border:1px solid #1f2937;"
            "border-radius:6px;}"
            "QHeaderView::section{background:#1e293b;color:#94a3b8;border:none;padding:4px;}"
        )
        self.search_results.verticalHeader().setVisible(False)
        self.search_results.setEditTriggers(QTableWidget.NoEditTriggers)
        hdr = self.search_results.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.Fixed)
        self.search_results.setColumnWidth(4, 80)
        self.search_results.hide()
        root.addWidget(self.search_results)

        # ── Separador ──
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #1f2937;")
        root.addWidget(line)

        # ── Carrito ──
        lbl_cart = QLabel("🛒 Productos en la proforma:")
        lbl_cart.setStyleSheet("font-weight: 600; margin-top: 4px;")
        root.addWidget(lbl_cart)

        self.cart_table = QTableWidget()
        self.cart_table.setColumnCount(6)
        self.cart_table.setHorizontalHeaderLabels([
            "Producto", "Cant.", "P. Unit.", "Desc. %", "Subtotal", "",
        ])
        self.cart_table.setStyleSheet(
            "QTableWidget{background:#0b1220;color:#e5e7eb;border:1px solid #1f2937;"
            "border-radius:8px;}"
            "QHeaderView::section{background:#111827;color:#e5e7eb;border:none;padding:4px;font-weight:bold;}"
            "QTableWidget::item{padding:4px;}"
        )
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.setEditTriggers(QTableWidget.NoEditTriggers)
        cart_hdr = self.cart_table.horizontalHeader()
        cart_hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        cart_hdr.setSectionResizeMode(5, QHeaderView.Fixed)
        self.cart_table.setColumnWidth(5, 50)
        root.addWidget(self.cart_table, 1)

        # ── Totales ──
        totals_row = QHBoxLayout()
        self.lbl_total = QLabel("Total: ₡0,00")
        self.lbl_total.setStyleSheet("font-size: 16px; font-weight: bold; color: #16a34a;")
        totals_row.addStretch()
        totals_row.addWidget(self.lbl_total)
        root.addLayout(totals_row)

        # ── Notas ──
        root.addWidget(QLabel("📝 Notas (opcional):"))
        self.txt_notes = QTextEdit()
        self.txt_notes.setMaximumHeight(60)
        self.txt_notes.setPlaceholderText("Notas para el cliente o internas…")
        self.txt_notes.setStyleSheet(
            "QTextEdit{background:#111827;color:#e5e7eb;border:1px solid #374151;"
            "border-radius:6px;padding:6px;}"
        )
        root.addWidget(self.txt_notes)

        # ── Botones ──
        btns = QHBoxLayout()
        btns.setSpacing(10)

        btn_cancel = QPushButton("❌ Cancelar")
        btn_cancel.setStyleSheet(
            "QPushButton{background:#334155;color:white;padding:8px 16px;border-radius:8px;}"
            "QPushButton:hover{background:#475569;}"
        )
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_cancel)

        btns.addStretch()

        btn_save = QPushButton("💾 Guardar proforma" if self.is_edit else "✅ Crear proforma")
        btn_save.setStyleSheet(
            "QPushButton{background:#16a34a;color:white;padding:8px 16px;"
            "font-weight:700;border-radius:8px;}"
            "QPushButton:hover{background:#15803d;}"
        )
        btn_save.clicked.connect(self._save)
        btns.addWidget(btn_save)

        root.addLayout(btns)

        self.setStyleSheet("QDialog { background-color: #080d1a; }")

    # ══════════════════════════════════════════════════
    # CLIENTES
    # ══════════════════════════════════════════════════
    def _load_customers(self):
        api_call(
            "get", API_CUSTOMERS, headers=self._auth_headers(),
            on_success=self._on_customers_loaded,
            on_error=lambda msg: logger.error(f"Error cargando clientes: {msg}"),
        )

    def _on_customers_loaded(self, data):
        customers = data if isinstance(data, list) else data.get("data", [])
        self.customers = customers
        self.customer_name_to_id = {}
        names = []
        for c in customers:
            name = c.get("name", "")
            cid = c.get("id")
            if name and cid:
                self.customer_name_to_id[name] = cid
                names.append(name)
        model = QStringListModel(names)
        self._customer_completer.setModel(model)

    def _on_customer_text_changed(self):
        text = self.txt_customer.text().strip()
        self.selected_customer_id = self.customer_name_to_id.get(text)

    # ══════════════════════════════════════════════════
    # BÚSQUEDA DE PRODUCTOS
    # ══════════════════════════════════════════════════
    def _search_products(self):
        term = self.txt_product_search.text().strip()
        if len(term) < 2:
            self.search_results.hide()
            return
        api_call(
            "get", API_PRODUCTS,
            headers=self._auth_headers(),
            params={"search": term, "page_size": 10},
            on_success=self._on_products_searched,
            on_error=lambda msg: logger.error(f"Error buscando productos: {msg}"),
        )

    def _on_products_searched(self, data):
        products = data if isinstance(data, list) else data.get("data", data.get("products", []))

        self.search_results.setRowCount(len(products))
        for row, p in enumerate(products):
            self.search_results.setItem(row, 0, QTableWidgetItem(p.get("code", "")))
            self.search_results.setItem(row, 1, QTableWidgetItem(p.get("name", "")))
            self.search_results.setItem(row, 2, QTableWidgetItem(f"₡{float(p.get('price', 0)):,.2f}"))
            self.search_results.setItem(row, 3, QTableWidgetItem(str(p.get("stock", 0))))

            btn = QPushButton("➕")
            btn.setFixedSize(40, 26)
            btn.setStyleSheet("QPushButton{background:#16a34a;color:white;border-radius:4px;}"
                              "QPushButton:hover{background:#15803d;}")
            btn.clicked.connect(lambda _, product=p: self._add_product_to_cart(product))
            self.search_results.setCellWidget(row, 4, btn)

        self.search_results.setVisible(len(products) > 0)

    def _add_product_to_cart(self, product):
        pid = product.get("id")
        if pid in self.cart:
            self.cart[pid]["quantity"] += 1
        else:
            self.cart[pid] = {
                "product": product,
                "quantity": 1,
                "unit_price": float(product.get("price", 0)),
                "discount_percent": 0.0,
                "is_common": False,
            }
        self._refresh_cart()
        self.txt_product_search.clear()
        self.search_results.hide()

    def _add_common_product(self):
        """Agrega una línea de producto común (sin inventario)."""
        self._common_seq -= 1
        pid = self._common_seq
        self.cart[pid] = {
            "product": {"name": "Producto común"},
            "quantity": 1,
            "unit_price": 0.0,
            "discount_percent": 0.0,
            "is_common": True,
            "common_description": "",
            # ── CABYS por línea (Hacienda) ──
            # Cada producto común puede llevar su propio CABYS. Si la
            # proforma se convierte luego en venta, este código viaja al
            # SaleDetail y de ahí al XML de Hacienda. NULL → fallback
            # genérico "8399000000000" en xml_builder_v44.py.
            "common_cabys_code": None,
            "common_cabys_name": None,
            "tax_rate": 0.0,   # IVA del CABYS elegido (0/1/2/4/13)
        }
        self._refresh_cart()

    # ══════════════════════════════════════════════════
    # CARRITO
    # ══════════════════════════════════════════════════
    def _refresh_cart(self):
        self.cart_table.setRowCount(len(self.cart))
        total = 0.0

        for row, (pid, item) in enumerate(self.cart.items()):
            is_common = item.get("is_common", False)

            # Col 0: Nombre (editable si es común)
            if is_common:
                # Container con: [descripción editable] + [botón CABYS].
                # Reemplaza el QLineEdit suelto por un widget compuesto
                # para que el usuario pueda asignar el CABYS de Hacienda
                # sin salir de la fila ni abrir un modal pesado.
                container = QWidget()
                h = QHBoxLayout(container)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(4)

                txt = QLineEdit(item.get("common_description", ""))
                txt.setPlaceholderText("Descripción del producto…")
                txt.setStyleSheet(
                    "QLineEdit{background:#1e293b;color:#e5e7eb;border:none;padding:4px;}"
                )
                txt.textChanged.connect(
                    lambda text, p=pid: self._update_common_desc(p, text)
                )
                h.addWidget(txt, 1)

                # Botón CABYS: cambia de label y color según si hay
                # código asignado. Click → abre el flujo búsqueda+selector.
                cabys_code = item.get("common_cabys_code")
                btn_cabys = QPushButton()
                btn_cabys.setFixedHeight(26)
                btn_cabys.setCursor(Qt.PointingHandCursor)
                if cabys_code:
                    iva_pct = item.get("tax_rate") or 0
                    btn_cabys.setText(f"✓ {cabys_code}")
                    btn_cabys.setToolTip(
                        f"CABYS: {cabys_code}\n"
                        f"{item.get('common_cabys_name') or ''}\n"
                        f"IVA: {iva_pct}%\n"
                        f"(Clic para cambiar)"
                    )
                    btn_cabys.setStyleSheet(
                        "QPushButton{background:#15803d;color:white;"
                        "border-radius:4px;padding:0 8px;font-size:11px;}"
                        "QPushButton:hover{background:#166534;}"
                    )
                else:
                    btn_cabys.setText("CABYS")
                    btn_cabys.setToolTip(
                        "Asignar código CABYS de Hacienda.\n"
                        "Si no se asigna, se usará el genérico "
                        "8399000000000 (Otros servicios n.c.p.)."
                    )
                    btn_cabys.setStyleSheet(
                        "QPushButton{background:#1e3a8a;color:white;"
                        "border-radius:4px;padding:0 8px;font-size:11px;}"
                        "QPushButton:hover{background:#1d4ed8;}"
                    )
                btn_cabys.clicked.connect(
                    lambda _, p=pid: self._pick_cabys_for_common(p)
                )
                h.addWidget(btn_cabys)

                self.cart_table.setCellWidget(row, 0, container)
            else:
                name = item["product"].get("name", "")
                self.cart_table.setItem(row, 0, QTableWidgetItem(name))

            # Col 1: Cantidad
            spn = QSpinBox()
            spn.setRange(1, 99999)
            spn.setValue(item["quantity"])
            spn.setStyleSheet("QSpinBox{background:#1e293b;color:#e5e7eb;border:none;padding:2px;}")
            spn.valueChanged.connect(lambda val, p=pid: self._update_qty(p, val))
            self.cart_table.setCellWidget(row, 1, spn)

            # Col 2: Precio unitario
            txt_price = QLineEdit(f"{item['unit_price']:.2f}")
            txt_price.setValidator(QDoubleValidator(0, 999999999, 2))
            txt_price.setStyleSheet("QLineEdit{background:#1e293b;color:#e5e7eb;border:none;padding:4px;}")
            txt_price.editingFinished.connect(
                lambda p=pid, w=txt_price: self._update_price(p, w.text())
            )
            self.cart_table.setCellWidget(row, 2, txt_price)

            # Col 3: Descuento %
            txt_disc = QLineEdit(f"{item['discount_percent']:.1f}")
            txt_disc.setValidator(QDoubleValidator(0, 100, 2))
            txt_disc.setFixedWidth(60)
            txt_disc.setStyleSheet("QLineEdit{background:#1e293b;color:#e5e7eb;border:none;padding:4px;}")
            txt_disc.editingFinished.connect(
                lambda p=pid, w=txt_disc: self._update_discount(p, w.text())
            )
            self.cart_table.setCellWidget(row, 3, txt_disc)

            # Col 4: Subtotal
            qty = item["quantity"]
            price = item["unit_price"]
            disc = item["discount_percent"]
            subtotal = price * qty * (1 - disc / 100)
            total += subtotal
            sub_item = QTableWidgetItem(f"₡{subtotal:,.2f}")
            sub_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.cart_table.setItem(row, 4, sub_item)

            # Col 5: Quitar
            btn_rm = QPushButton("✕")
            btn_rm.setFixedSize(30, 26)
            btn_rm.setStyleSheet("QPushButton{background:#dc2626;color:white;border-radius:4px;}"
                                 "QPushButton:hover{background:#b91c1c;}")
            btn_rm.clicked.connect(lambda _, p=pid: self._remove_from_cart(p))
            self.cart_table.setCellWidget(row, 5, btn_rm)

        self.lbl_total.setText(f"Total: ₡{total:,.2f}")

    def _update_qty(self, pid, val):
        if pid in self.cart:
            self.cart[pid]["quantity"] = val
            self._refresh_cart()

    def _update_price(self, pid, text):
        try:
            val = float(text.replace(",", ""))
            if pid in self.cart:
                self.cart[pid]["unit_price"] = val
                self._refresh_cart()
        except ValueError:
            pass

    def _update_discount(self, pid, text):
        try:
            val = float(text.replace(",", "."))
            if pid in self.cart and 0 <= val <= 100:
                self.cart[pid]["discount_percent"] = val
                self._refresh_cart()
        except ValueError:
            pass

    def _update_common_desc(self, pid, text):
        if pid in self.cart:
            self.cart[pid]["common_description"] = text

    def _pick_cabys_for_common(self, pid):
        """Flujo de selección de CABYS para una línea común de la proforma.

        Misma mecánica que `CommonProductDialog.search_cabys` en ventas:
        pide al usuario un término, llama a /cabys/search y abre el
        `CabysSelectorDialog` para que escoja. El IVA del CABYS elegido
        se persiste como `tax_rate` de la línea — coherente con la
        propagación que hace `proforma_crud.convert_to_sale`.
        """
        if pid not in self.cart:
            return

        # Pre-cargamos el campo de búsqueda con la descripción ya escrita
        # (si la hay), para ahorrarle al usuario re-tipear "tornillos"
        # cuando ya lo puso en la descripción.
        prefill = (self.cart[pid].get("common_description") or "").strip()

        keyword, ok = QInputDialog.getText(
            self,
            "Buscar CABYS",
            "Escriba el nombre o código del bien/servicio:",
            QLineEdit.Normal,
            prefill,
        )
        if not ok:
            return
        keyword = (keyword or "").strip()
        if not keyword:
            QMessageBox.warning(
                self, "CABYS",
                "Escriba el nombre o el código CABYS para buscar."
            )
            return

        def _on_results(payload):
            data = payload.get("data", []) if isinstance(payload, dict) else []
            if not data:
                QMessageBox.information(
                    self, "CABYS", "No se encontraron coincidencias."
                )
                return

            from ui.dialogs.cabys_selector_dialog import CabysSelectorDialog
            dialog = CabysSelectorDialog(data)
            if dialog.exec() == QDialog.Accepted and dialog.selected:
                cabys = dialog.selected
                if pid not in self.cart:
                    # La línea fue removida entre el clic y la selección
                    return

                # Persistir en el cart
                try:
                    iva_int = int(cabys.get("iva") or 0)
                except (TypeError, ValueError):
                    iva_int = 13   # default razonable si llega raro

                self.cart[pid]["common_cabys_code"] = cabys.get("code") or None
                self.cart[pid]["common_cabys_name"] = cabys.get("description") or None
                self.cart[pid]["tax_rate"] = float(iva_int)

                # Refrescar para que el botón cambie a estado verde
                self._refresh_cart()

        api_call(
            "get", CABYS_SEARCH_URL,
            headers=self._auth_headers(),
            params={"q": keyword},
            on_success=_on_results,
            on_error=lambda msg: QMessageBox.critical(
                self, "Error CABYS", msg
            ),
            owner=self,
        )

    def _remove_from_cart(self, pid):
        if pid in self.cart:
            del self.cart[pid]
            self._refresh_cart()

    # ══════════════════════════════════════════════════
    # CARGAR DATOS (modo edición)
    # ══════════════════════════════════════════════════
    def _load_proforma_data(self):
        api_call(
            "get", f"{API_PROFORMAS}/{self.proforma_id}",
            headers=self._auth_headers(),
            on_success=self._on_proforma_loaded,
            on_error=lambda msg: QMessageBox.warning(self, "Error", f"No se pudo cargar la proforma: {msg}"),
        )

    def _on_proforma_loaded(self, data):
        try:

            # Cliente
            cname = data.get("customer_name", "")
            if cname and cname != "Cliente General":
                self.txt_customer.setText(cname)
                self.selected_customer_id = data.get("customer_id")

            # Vigencia
            self.spn_validity.setValue(data.get("validity_days", 15))

            # Notas
            self.txt_notes.setPlainText(data.get("notes", "") or "")

            # Cargar líneas al carrito
            for d in data.get("details", []):
                if d.get("is_common"):
                    self._common_seq -= 1
                    pid = self._common_seq
                    self.cart[pid] = {
                        "product": {"name": "Producto común"},
                        "quantity": d["quantity"],
                        "unit_price": float(d["unit_price"]),
                        "discount_percent": float(d.get("discount_percent", 0)),
                        "is_common": True,
                        "common_description": d.get("common_description", ""),
                        # Restaurar CABYS guardado previamente. El backend
                        # devuelve `common_cabys_code` en cada detail (ver
                        # proforma_crud._enriched_detail). `common_cabys_name`
                        # no se persiste, así que queda None — el botón
                        # aún muestra el código y el % de IVA.
                        "common_cabys_code": d.get("common_cabys_code"),
                        "common_cabys_name": None,
                        "tax_rate": float(d.get("tax_rate") or 0),
                    }
                else:
                    pid = d.get("product_id")
                    self.cart[pid] = {
                        "product": {"id": pid, "name": d.get("product_name", f"Producto #{pid}")},
                        "quantity": d["quantity"],
                        "unit_price": float(d["unit_price"]),
                        "discount_percent": float(d.get("discount_percent", 0)),
                        "is_common": False,
                    }

            self._refresh_cart()

        except Exception as e:
            logger.error(f"Error cargando proforma: {e}")
            QMessageBox.warning(self, "Error", f"Error cargando datos: {e}")

    # ══════════════════════════════════════════════════
    # GUARDAR
    # ══════════════════════════════════════════════════
    def _save(self):
        if not self.cart:
            QMessageBox.warning(self, "Sin productos", "Agregue al menos un producto.")
            return

        # Validar productos comunes
        for pid, item in self.cart.items():
            if item.get("is_common"):
                desc = (item.get("common_description") or "").strip()
                if not desc:
                    QMessageBox.warning(self, "Producto común", "Complete la descripción de todos los productos comunes.")
                    return
                if item["unit_price"] <= 0:
                    QMessageBox.warning(self, "Precio inválido", f"El producto '{desc}' debe tener precio mayor a 0.")
                    return

        # Construir payload
        details = []
        for pid, item in self.cart.items():
            entry = {
                "quantity": item["quantity"],
                "unit_price": item["unit_price"],
                "discount_percent": item["discount_percent"],
                "is_common": item.get("is_common", False),
            }
            if item.get("is_common"):
                entry["product_id"] = None
                entry["common_description"] = item.get("common_description", "Producto común")
                # ── CABYS y tax_rate por línea ──
                # Se envían solo si el usuario los asignó. Si no, el
                # backend persiste NULL/0 y, al convertir esta proforma
                # a venta, xml_builder_v44.py usará el CABYS genérico.
                cc = item.get("common_cabys_code")
                if cc:
                    entry["common_cabys_code"] = cc
                tr = float(item.get("tax_rate") or 0)
                if tr > 0:
                    entry["tax_rate"] = tr
            else:
                entry["product_id"] = pid
            details.append(entry)

        payload = {
            "customer_id": self.selected_customer_id,
            "details": details,
            "notes": self.txt_notes.toPlainText().strip() or None,
            "validity_days": self.spn_validity.value(),
        }

        method = "put" if self.is_edit else "post"
        url = f"{API_PROFORMAS}/{self.proforma_id}" if self.is_edit else f"{API_PROFORMAS}/"
        api_call(
            method, url, json=payload, headers=self._auth_headers(),
            on_success=self._on_proforma_saved,
            on_error=lambda msg: QMessageBox.warning(self, "Error", msg),
        )

    def _on_proforma_saved(self, resp):
        msg = resp.get("message", "Proforma guardada") if isinstance(resp, dict) else "Proforma guardada"
        show_toast(f"✅ {msg}", success=True, parent=self.parent())
        self.accept()