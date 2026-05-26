# ui/dialogs/common_product_dialog.py
"""
Diálogo para agregar un "Producto Común" al carrito.
No toca inventario — pide descripción, CABYS, cantidad y precio.

CABYS:
    Cada producto común puede llevar su propio código CABYS. Hacienda
    exige que toda línea facturada reporte el CABYS del bien o servicio.
    Si el usuario no selecciona uno, la línea sale al XML con el default
    "8399000000000" (Otros servicios n.c.p.) — fallback genérico aceptado
    como tolerancia, pero no recomendado para uso recurrente.

    El IVA del CABYS seleccionado se propaga como tax_rate de la línea,
    igual que sucede con los productos del inventario.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QMessageBox, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator

from ui.api import BASE_URL
from ui.session_manager import session
from ui.utils.http_worker import api_call


CABYS_SEARCH_URL = f"{BASE_URL}/cabys/search"


class CommonProductDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📦 Producto Común")
        self.setModal(True)
        self.setMinimumWidth(440)

        # Estado del CABYS seleccionado (None = no seleccionado todavía)
        self._cabys_code = None
        self._cabys_name = None
        self._cabys_iva = None  # int: 0, 1, 2, 4 o 13

        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #e2e8f0;
            }
            QLabel {
                color: #cbd5e1;
                font-size: 13px;
            }
            QLabel#title_label {
                color: #f1f5f9;
                font-size: 16px;
                font-weight: bold;
            }
            QLabel#cabys_display {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px 10px;
                color: #94a3b8;
                font-size: 12px;
            }
            QLabel#cabys_display[selected="true"] {
                color: #f1f5f9;
                border-color: #22c55e;
            }
            QLineEdit, QSpinBox {
                background-color: #1e293b;
                color: #f1f5f9;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 14px;
            }
            QLineEdit:focus, QSpinBox:focus {
                border-color: #3b82f6;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #334155;
                border: none;
                width: 20px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #475569;
            }
            QPushButton#cabys_search_btn {
                background-color: #1e3a8a;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: bold;
            }
            QPushButton#cabys_search_btn:hover {
                background-color: #1d4ed8;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # ─── Título ───
        title = QLabel("PRODUCTO COMÚN")
        title.setObjectName("title_label")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Producto sin inventario — no descuenta stock")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #64748b; font-size: 11px; margin-bottom: 6px;")
        layout.addWidget(subtitle)

        # ─── Separador ───
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #1e293b;")
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # ─── Descripción ───
        layout.addWidget(QLabel("Descripción del Producto:"))
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Ej: Tornillos sueltos, servicio de corte...")
        self.desc_input.setMaxLength(200)
        layout.addWidget(self.desc_input)

        # ─── CABYS (buscador + display) ───
        layout.addWidget(QLabel("CABYS (Hacienda):"))

        cabys_row = QHBoxLayout()
        cabys_row.setSpacing(8)

        self.cabys_search_input = QLineEdit()
        self.cabys_search_input.setPlaceholderText("Escriba nombre o código y pulse Buscar…")
        # Permite Enter en el campo de búsqueda → dispara la búsqueda
        # sin cerrar el diálogo (returnPressed no llama a accept porque
        # ningún botón es default).
        self.cabys_search_input.returnPressed.connect(self.search_cabys)
        cabys_row.addWidget(self.cabys_search_input, 3)

        self.btn_search_cabys = QPushButton("🔍 Buscar")
        self.btn_search_cabys.setObjectName("cabys_search_btn")
        self.btn_search_cabys.setCursor(Qt.PointingHandCursor)
        self.btn_search_cabys.setAutoDefault(False)
        self.btn_search_cabys.setDefault(False)
        self.btn_search_cabys.clicked.connect(self.search_cabys)
        cabys_row.addWidget(self.btn_search_cabys, 1)

        layout.addLayout(cabys_row)

        # Display del CABYS seleccionado (read-only, estilo "chip")
        self.cabys_display = QLabel("Sin CABYS seleccionado — se usará el genérico de Hacienda")
        self.cabys_display.setObjectName("cabys_display")
        self.cabys_display.setProperty("selected", "false")
        self.cabys_display.setWordWrap(True)
        layout.addWidget(self.cabys_display)

        # ─── Cantidad y Precio (horizontal) ───
        row_layout = QHBoxLayout()
        row_layout.setSpacing(12)

        # Cantidad
        qty_col = QVBoxLayout()
        qty_col.addWidget(QLabel("Cantidad:"))
        self.qty_input = QSpinBox()
        self.qty_input.setRange(1, 9999)
        self.qty_input.setValue(1)
        self.qty_input.setFixedHeight(36)
        qty_col.addWidget(self.qty_input)
        row_layout.addLayout(qty_col, 1)

        # Precio
        price_col = QVBoxLayout()
        price_col.addWidget(QLabel("Precio unitario:"))
        self.price_input = QLineEdit()
        self.price_input.setPlaceholderText("0.00")
        self.price_input.setValidator(QDoubleValidator(0.01, 999999999.99, 2))
        self.price_input.setFixedHeight(36)
        price_col.addWidget(self.price_input)
        row_layout.addLayout(price_col, 2)

        layout.addLayout(row_layout)

        # ─── Botones ───
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("✕  Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #374151;
                color: #e2e8f0;
                border: 1px solid #4b5563;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        btn_cancel.clicked.connect(self.reject)

        btn_accept = QPushButton("✔  Aceptar")
        btn_accept.setCursor(Qt.PointingHandCursor)
        # NO marcar como default: queremos que Enter en el campo de
        # búsqueda CABYS dispare la búsqueda, no que cierre el diálogo.
        btn_accept.setAutoDefault(False)
        btn_accept.setDefault(False)
        btn_accept.setFixedHeight(36)
        btn_accept.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        btn_accept.clicked.connect(self.validate_and_accept)

        btn_layout.addWidget(btn_cancel, 1)
        btn_layout.addWidget(btn_accept, 1)
        layout.addLayout(btn_layout)

        # Focus inicial en descripción
        self.desc_input.setFocus()

    # ─────────────────────────────────────────────────────────────
    # CABYS — búsqueda y selección
    # ─────────────────────────────────────────────────────────────
    def search_cabys(self):
        """Busca CABYS por nombre o código y abre el selector.

        Misma mecánica que add_product_dialog.search_cabys: usa
        api_call + CabysSelectorDialog, así el comportamiento es
        idéntico al de productos del inventario.
        """
        keyword = self.cabys_search_input.text().strip()
        if not keyword:
            QMessageBox.warning(
                self, "CABYS",
                "Escriba el nombre o el código CABYS para buscar."
            )
            self.cabys_search_input.setFocus()
            return

        headers = {"Authorization": f"Bearer {session.token}"}
        params = {"q": keyword}

        def _on_results(payload):
            data = payload.get("data", []) if isinstance(payload, dict) else []
            if not data:
                QMessageBox.information(
                    self, "CABYS", "No se encontraron coincidencias."
                )
                return

            # Import diferido para no cargar el selector si nunca se usa
            from ui.dialogs.cabys_selector_dialog import CabysSelectorDialog
            dialog = CabysSelectorDialog(data)
            if dialog.exec() == QDialog.Accepted and dialog.selected:
                self._apply_cabys_selection(dialog.selected)

        api_call(
            "get", CABYS_SEARCH_URL,
            headers=headers, params=params,
            on_success=_on_results,
            on_error=lambda msg: QMessageBox.critical(
                self, "Error CABYS", msg
            ),
            owner=self,
        )

    def _apply_cabys_selection(self, cabys: dict):
        """Guarda el CABYS seleccionado y actualiza el display.

        `cabys` viene del CabysSelectorDialog con shape:
            {"code": str, "description": str, "iva": str}
        El IVA llega como string ("0", "1", "13", etc.) porque el
        selector lo lee desde QTableWidgetItem.text(). Convertimos a int.
        """
        self._cabys_code = cabys.get("code") or None
        self._cabys_name = cabys.get("description") or None
        try:
            self._cabys_iva = int(cabys.get("iva") or 0)
        except (TypeError, ValueError):
            # Si por alguna razón viene un valor raro, default a 13%
            # (tarifa general — el caso más común en ferreterías).
            self._cabys_iva = 13

        # Actualizar display visual
        if self._cabys_code:
            label = (
                f"✓ {self._cabys_code} — {self._cabys_name}\n"
                f"IVA: {self._cabys_iva}%"
            )
            self.cabys_display.setText(label)
            self.cabys_display.setProperty("selected", "true")
            # Forzar refresco del stylesheet para que aplique el borde verde
            self.cabys_display.style().unpolish(self.cabys_display)
            self.cabys_display.style().polish(self.cabys_display)

    # ─────────────────────────────────────────────────────────────
    # Validación y salida
    # ─────────────────────────────────────────────────────────────
    def validate_and_accept(self):
        desc = self.desc_input.text().strip()
        if not desc:
            QMessageBox.warning(self, "Campo requerido", "Debes ingresar una descripción.")
            self.desc_input.setFocus()
            return

        price_text = self.price_input.text().strip().replace(",", ".")
        if not price_text:
            QMessageBox.warning(self, "Campo requerido", "Debes ingresar el precio.")
            self.price_input.setFocus()
            return

        try:
            price = float(price_text)
            if price <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Precio inválido", "El precio debe ser mayor a 0.")
            self.price_input.setFocus()
            return

        # Si no eligieron CABYS, confirmar (no bloquear: la línea sale
        # con el default "8399000000000", que Hacienda acepta como
        # fallback genérico). Avisamos por si fue olvido.
        if not self._cabys_code:
            reply = QMessageBox.question(
                self,
                "CABYS no seleccionado",
                "No seleccionaste un CABYS específico para este producto.\n\n"
                "La línea se enviará a Hacienda con el código genérico "
                "8399000000000 (Otros servicios n.c.p.).\n\n"
                "¿Deseas continuar igual?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.cabys_search_input.setFocus()
                return

        self.accept()

    def get_data(self) -> dict:
        """Retorna los datos del producto común.

        Campos:
            description: descripción libre (obligatoria)
            quantity:    entero ≥ 1
            price:       precio unitario CON IVA incluido
            cabys_code:  código CABYS (None si no se seleccionó)
            cabys_name:  descripción del CABYS (informativo, no se persiste)
            tax_rate:    IVA en % entero (0, 1, 2, 4 o 13). 0 si no hay CABYS.
        """
        price_text = self.price_input.text().strip().replace(",", ".")
        return {
            "description": self.desc_input.text().strip(),
            "quantity": self.qty_input.value(),
            "price": float(price_text),
            "cabys_code": self._cabys_code,
            "cabys_name": self._cabys_name,
            "tax_rate": float(self._cabys_iva) if self._cabys_iva is not None else 0.0,
        }