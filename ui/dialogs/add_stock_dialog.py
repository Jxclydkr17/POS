from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QSpinBox, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ui.session_manager import session
from ui.utils.http_worker import api_call

from ui.api import BASE_URL

API_URL = f"{BASE_URL}/products"


# ──────────────────────────────────────────────────────────────
# Helper de casteo defensivo
# ──────────────────────────────────────────────────────────────
# Los campos numéricos del producto (stock, min_stock, reorder_suggestion)
# se declaran como Decimal en ProductOut y Pydantic v2 los serializa a JSON
# **como string**. Si los usamos crudo en comparaciones (`<=`, `>`, `==`)
# o aritmética, explota con TypeError. Castear a float aquí da una sola
# fuente de verdad para todo el diálogo.
def _to_float(value, default: float = 0.0) -> float:
    """Convierte str / int / float / Decimal / None a float, devolviendo
    `default` si la conversión falla. Pensado para valores que vienen
    del backend ya sea como número nativo o como string serializado."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ──────────────────────────────────────────────────────────────
# Panel de sugerencia de reposición — FASE 4: con datos de rotación
# ──────────────────────────────────────────────────────────────
class ReorderSuggestionPanel(QFrame):
    """
    Panel visual que muestra la sugerencia de reposición calculada.
    Fase 4: ahora muestra datos de rotación real (venta diaria,
    días hasta agotamiento, urgencia).
    Se oculta si no hay sugerencia (stock ya está bien surtido).
    """

    URGENCY_COLORS = {
        "critico": "#DC3545",
        "alto": "#E67E22",
        "medio": "#F7C331",
        "bajo": "#28A745",
    }
    URGENCY_LABELS = {
        "critico": "🔴 CRÍTICO",
        "alto": "🟠 ALTO",
        "medio": "🟡 MEDIO",
        "bajo": "🟢 BAJO",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("reorderPanel")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame#reorderPanel {
                background-color: #2D2A1E;
                border: 1px solid #F9A825;
                border-radius: 6px;
                padding: 4px;
            }
            QLabel { background: transparent; border: none; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        title = QLabel("📦 Sugerencia de reposición")
        title_font = QFont()
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #FFD54F; background: transparent; border: none;")
        layout.addWidget(title)

        self.detail_label = QLabel()
        self.detail_label.setStyleSheet("color: #FFFFFF; background: transparent; border: none;")
        layout.addWidget(self.detail_label)

        self.formula_label = QLabel()
        self.formula_label.setStyleSheet("color: #FFE082; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.formula_label)

        # ── Fase 4: línea de rotación ──
        self.rotation_label = QLabel()
        self.rotation_label.setStyleSheet("color: #B0BEC5; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.rotation_label)
        self.rotation_label.hide()

        # ── Fase 4: línea de urgencia ──
        self.urgency_label = QLabel()
        self.urgency_label.setStyleSheet("font-size: 11px; font-weight: bold; background: transparent; border: none;")
        layout.addWidget(self.urgency_label)
        self.urgency_label.hide()

        self.hide()

    def update_suggestion(self, stock: float, min_stock: float, suggestion: float,
                          rotation: dict = None):
        """
        Actualiza el panel con los datos de sugerencia.
        rotation (Fase 4): dict con daily_avg, days_until_stockout,
                           smart_reorder, reorder_urgency, etc.
        """
        if suggestion <= 0:
            self.hide()
            return

        target = 2 * min_stock
        self.detail_label.setText(
            f"  Stock actual: <b>{stock:g}</b> &nbsp;|&nbsp; "
            f"Mínimo: <b>{min_stock:g}</b> &nbsp;|&nbsp; "
            f"Recomendado a comprar: <b>{suggestion:g}</b>"
        )
        self.detail_label.setTextFormat(Qt.RichText)

        # ── Fase 4: mostrar info de rotación si hay datos ──
        if rotation and rotation.get("total_sold", 0) > 0:
            daily = rotation.get("daily_avg", 0)
            stockout = rotation.get("days_until_stockout")
            monthly = rotation.get("monthly_avg", 0)

            formula_parts = [f"Venta diaria: {daily:.1f} uds"]
            if monthly > 0:
                formula_parts.append(f"mensual: ~{monthly:.0f} uds")

            self.formula_label.setText(f"  📊 {' | '.join(formula_parts)}")

            if stockout is not None:
                stockout_text = (
                    f"  ⏳ Se agota en ~<b>{stockout:.0f} días</b> al ritmo actual"
                )
            else:
                stockout_text = "  ⏳ Sin datos suficientes para estimar agotamiento"

            self.rotation_label.setText(stockout_text)
            self.rotation_label.setTextFormat(Qt.RichText)
            self.rotation_label.show()

            urgency = rotation.get("reorder_urgency", "bajo")
            urgency_color = self.URGENCY_COLORS.get(urgency, "#28A745")
            urgency_text = self.URGENCY_LABELS.get(urgency, "🟢 BAJO")
            self.urgency_label.setText(f"  Urgencia: {urgency_text}")
            self.urgency_label.setStyleSheet(
                f"font-size: 11px; font-weight: bold; color: {urgency_color}; "
                f"background: transparent; border: none;"
            )
            self.urgency_label.show()

            # Cambiar borde del panel según urgencia
            border_color = urgency_color if urgency in ("critico", "alto") else "#F9A825"
            self.setStyleSheet(f"""
                QFrame#reorderPanel {{
                    background-color: #2D2A1E;
                    border: 2px solid {border_color};
                    border-radius: 6px;
                    padding: 4px;
                }}
                QLabel {{ background: transparent; border: none; }}
            """)
        else:
            # Sin datos de rotación: mostrar fórmula clásica
            self.formula_label.setText(
                f"  (objetivo: 2 × {min_stock:g} = {target:g} unidades)"
            )
            self.rotation_label.hide()
            self.urgency_label.hide()
            self.setStyleSheet("""
                QFrame#reorderPanel {
                    background-color: #2D2A1E;
                    border: 1px solid #F9A825;
                    border-radius: 6px;
                    padding: 4px;
                }
                QLabel { background: transparent; border: none; }
            """)

        self.show()

    def clear(self):
        self.hide()


# ──────────────────────────────────────────────────────────────
# Diálogo principal
# ──────────────────────────────────────────────────────────────
class AddStockDialog(QDialog):
    def __init__(self, product_data: dict | None = None):
        super().__init__()
        self.product_id = None
        self.product_data = product_data or {}
        self._reorder_suggestion = 0

        self.setWindowTitle("➕ Agregar Stock")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("Escanear o ingresar código de barras")
        layout.addWidget(self.barcode_input)

        self.info_label = QLabel("Producto: —")
        layout.addWidget(self.info_label)

        self.stock_label = QLabel("Stock actual: —")
        layout.addWidget(self.stock_label)

        self.suggestion_panel = ReorderSuggestionPanel()
        layout.addWidget(self.suggestion_panel)

        qty_layout = QHBoxLayout()

        self.qty_input = QSpinBox()
        self.qty_input.setRange(1, 100_000)
        self.qty_input.setMinimumHeight(34)
        qty_layout.addWidget(self.qty_input, stretch=1)

        self.apply_suggestion_btn = QPushButton("⚡ Aplicar sugerencia")
        self.apply_suggestion_btn.setToolTip(
            "Establece la cantidad recomendada basada en rotación real de ventas"
        )
        self.apply_suggestion_btn.setEnabled(False)
        self.apply_suggestion_btn.clicked.connect(self._apply_suggestion)
        qty_layout.addWidget(self.apply_suggestion_btn)

        layout.addLayout(qty_layout)

        btn = QPushButton("Confirmar")
        btn.clicked.connect(self.confirm)
        btn.setDefault(False)
        btn.setAutoDefault(False)
        layout.addWidget(btn)

        self.barcode_input.returnPressed.connect(self.search_product)

        if self.product_data:
            self.fill_product_data()

    def _apply_suggestion(self):
        if self._reorder_suggestion > 0:
            # qty_input es QSpinBox (int-only). Si la sugerencia es
            # fraccionaria (productos por kg/L/m), redondeamos al entero
            # más cercano para no perder valores como 3.5 → 4.
            self.qty_input.setValue(int(round(self._reorder_suggestion)))

    def _update_suggestion_ui(self, product: dict):
        # ── Bugfix: estos campos vienen como string desde el backend ──
        # ProductOut los tipa como Decimal y Pydantic v2 los serializa
        # a JSON como string ("11.5", "3", "0"). Sin castear, las
        # comparaciones `<=`, `>`, `==` revientan con TypeError.
        stock = _to_float(product.get("stock"))
        min_stock = _to_float(product.get("min_stock"))
        suggestion = _to_float(product.get("reorder_suggestion"))

        # Fase 4: datos de rotación del backend
        rotation = product.get("rotation", None)

        # Si hay smart_reorder en rotation, usarlo
        if rotation and _to_float(rotation.get("smart_reorder")) > 0:
            suggestion = _to_float(rotation["smart_reorder"])

        # Calcular localmente si el backend no lo incluyó
        if suggestion == 0 and min_stock > 0:
            suggestion = max(0.0, 2 * min_stock - stock)

        self._reorder_suggestion = suggestion
        self.suggestion_panel.update_suggestion(stock, min_stock, suggestion, rotation)
        self.apply_suggestion_btn.setEnabled(suggestion > 0)

    def fill_product_data(self):
        product_id = self.product_data.get("id")
        product_name = self.product_data.get("name", "—")
        product_stock = self.product_data.get("stock", "—")
        product_barcode = self.product_data.get("barcode", "") or ""

        self.product_id = product_id
        self.info_label.setText(f"Producto: {product_name}")
        self.stock_label.setText(f"Stock actual: {product_stock}")

        if product_barcode:
            self.barcode_input.setText(product_barcode)

        self.barcode_input.setReadOnly(True)
        self.barcode_input.setPlaceholderText("Producto precargado")
        self._update_suggestion_ui(self.product_data)

    def search_product(self):
        barcode = self.barcode_input.text().strip()
        if not barcode:
            QMessageBox.warning(self, "Atención", "Ingresa o escanea un código de barras.")
            return

        headers = {"Authorization": f"Bearer {session.token}"}
        api_call(
            "get", f"{API_URL}/barcode/{barcode}", headers=headers,
            on_success=self._on_product_found,
            on_error=self._on_product_search_error,
        )

    def _on_product_found(self, payload):
        product = payload.get("data", payload) if isinstance(payload, dict) else payload
        self.product_id = product.get("id")
        self.info_label.setText(f"Producto: {product.get('name', '—')}")
        self.stock_label.setText(f"Stock actual: {product.get('stock', '—')}")
        self._update_suggestion_ui(product)

    def _on_product_search_error(self, msg):
        QMessageBox.warning(self, "No encontrado", "Producto no encontrado")
        self.suggestion_panel.clear()
        self.apply_suggestion_btn.setEnabled(False)

    def confirm(self):
        if not self.product_id:
            QMessageBox.warning(self, "Error", "Busca un producto primero")
            return

        qty = self.qty_input.value()
        headers = {"Authorization": f"Bearer {session.token}"}
        api_call(
            "post", f"{API_URL}/{self.product_id}/add-stock",
            params={"quantity": qty}, headers=headers,
            on_success=lambda data: (QMessageBox.information(self, "OK", "Stock agregado correctamente"), self.accept()),
            on_error=lambda msg: QMessageBox.critical(self, "Error", msg),
        )