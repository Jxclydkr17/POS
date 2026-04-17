"""
product_movements_dialog.py
Historial de movimientos de inventario por producto.
Muestra: entradas, salidas, ajustes, última venta y última compra.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QAbstractItemView, QComboBox, QWidget, QSizePolicy
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont
from ui.session_manager import session
from ui.utils.http_worker import api_call
from ui.api import BASE_URL

API_BASE = f"{BASE_URL}/products"

# ── Colores por tipo de movimiento ──────────────────────────
MOVEMENT_STYLES = {
    "entrada":    {"icon": "📥", "label": "Entrada",    "bg": "#1E3A2F", "fg": "#4ADE80"},
    "venta":      {"icon": "💸", "label": "Venta",      "bg": "#3A1E1E", "fg": "#F87171"},
    "ajuste":     {"icon": "🔧", "label": "Ajuste",     "bg": "#2A2A1A", "fg": "#FACC15"},
    "devolucion": {"icon": "↩️", "label": "Devolución", "bg": "#1E2A3A", "fg": "#60A5FA"},
}

COL_DATE  = 0
COL_TYPE  = 1
COL_QTY   = 2
COL_BEFORE = 3
COL_AFTER  = 4
COL_REF   = 5
COL_NOTES = 6


class StatCard(QFrame):
    """Tarjeta pequeña de estadística para el resumen superior."""

    def __init__(self, icon: str, title: str, value: str = "—", color: str = "#5B9BD5"):
        super().__init__()
        self.setMinimumHeight(80)
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #2C2F33;
                border: 1px solid #3A3D42;
                border-radius: 8px;
                padding: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(5)
        lbl_icon = QLabel(icon)
        lbl_icon.setStyleSheet("font-size: 15px; border: none;")
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #9CA3AF; font-size: 11px; border: none;")
        lbl_title.setWordWrap(True)
        top.addWidget(lbl_icon)
        top.addWidget(lbl_title, 1)
        layout.addLayout(top)

        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"color: {color}; font-size: 15px; font-weight: bold; border: none;")
        self.value_label.setWordWrap(True)
        layout.addWidget(self.value_label)

    def set_value(self, value: str):
        self.value_label.setText(value)


class ProductMovementsDialog(QDialog):
    """
    Muestra el historial de movimientos de inventario de un producto.
    Se abre desde el menú contextual de la vista de productos.
    """

    def __init__(self, product_id: int, product_name: str, parent=None):
        super().__init__(parent)
        self.product_id = product_id
        self.product_name = product_name
        self._all_movements = []
        self._active_filter = "todos"

        self.setWindowTitle(f"📋 Historial de movimientos — {product_name}")
        self.setMinimumSize(900, 580)
        self.resize(1020, 640)
        self.setStyleSheet("""
            QDialog { background-color: #1E2124; color: #FFFFFF; }
            QLabel  { color: #FFFFFF; }
            QPushButton {
                background-color: #2C2F33; color: #FFFFFF;
                border: 1px solid #444; border-radius: 6px;
                padding: 5px 14px; font-size: 12px;
            }
            QPushButton:hover  { background-color: #3A3D42; }
            QPushButton:checked { background-color: #5B9BD5; border-color: #5B9BD5; }
            QComboBox {
                background-color: #2C2F33; color: #FFFFFF;
                border: 1px solid #444; border-radius: 6px; padding: 4px 10px;
            }
            QTableWidget {
                background-color: #1E2124; color: #FFFFFF;
                gridline-color: #2C2F33; border: none;
            }
            QTableWidget::item { padding: 4px 8px; }
            QTableWidget::item:selected { background-color: #3A4A5A; }
            QHeaderView::section {
                background-color: #2C2F33; color: #9CA3AF;
                border: none; border-bottom: 1px solid #3A3D42;
                padding: 6px 8px; font-size: 11px;
            }
            QScrollBar:vertical { background: #2C2F33; width: 8px; }
            QScrollBar::handle:vertical { background: #555; border-radius: 4px; }
        """)

        self._build_ui()
        self._load_movements()

    # ── Construcción de la UI ─────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # Título
        title = QLabel(f"<b>{self.product_name}</b>")
        title.setStyleSheet("font-size: 15px; color: #FFFFFF;")
        root.addWidget(title)

        # ── Tarjetas de resumen ──────────────────────────────
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)

        self.card_total_in    = StatCard("📥", "Total entradas",  color="#4ADE80")
        self.card_total_out   = StatCard("💸", "Total salidas",   color="#F87171")
        self.card_total_adj   = StatCard("🔧", "Total ajustes",   color="#FACC15")
        self.card_last_sale   = StatCard("🛒", "Última venta",    color="#60A5FA")
        self.card_last_buy    = StatCard("📦", "Última compra",   color="#C084FC")

        for c in [self.card_total_in, self.card_total_out,
                  self.card_total_adj, self.card_last_sale, self.card_last_buy]:
            cards_row.addWidget(c)

        root.addLayout(cards_row)

        # ── Filtros por tipo ─────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)

        self.btn_all      = self._filter_btn("📊 Todos",     "todos")
        self.btn_in       = self._filter_btn("📥 Entradas",  "entrada")
        self.btn_out      = self._filter_btn("💸 Ventas",    "venta")
        self.btn_adj      = self._filter_btn("🔧 Ajustes",   "ajuste")
        self.btn_dev      = self._filter_btn("↩️ Dev.",      "devolucion")

        for btn in [self.btn_all, self.btn_in, self.btn_out, self.btn_adj, self.btn_dev]:
            filter_row.addWidget(btn)

        filter_row.addStretch()

        self.lbl_count = QLabel("0 registros")
        self.lbl_count.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        filter_row.addWidget(self.lbl_count)

        root.addLayout(filter_row)

        # ── Tabla ────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Fecha", "Tipo", "Cantidad", "Stock antes", "Stock después", "Referencia", "Notas"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setShowGrid(False)

        root.addWidget(self.table)

        # ── Botón cerrar ─────────────────────────────────────
        btn_close = QPushButton("Cerrar")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)

        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(btn_close)
        root.addLayout(bottom)

    def _filter_btn(self, text: str, filter_key: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setChecked(filter_key == "todos")
        btn.clicked.connect(lambda _, k=filter_key: self._apply_filter(k))
        return btn

    # ── Carga de datos ────────────────────────────────────────

    def _load_movements(self):
        headers = {"Authorization": f"Bearer {session.token}"}
        api_call(
            "get", f"{API_BASE}/{self.product_id}/movements?limit=500",
            headers=headers,
            on_success=self._on_movements_loaded,
            on_error=self._on_movements_error,
        )

    def _on_movements_loaded(self, body):
        self._all_movements = body.get("data", []) if isinstance(body, dict) else []
        self._compute_stats()
        self._apply_filter("todos")

    def _on_movements_error(self, msg):
        self._all_movements = []
        self._compute_stats()
        self._apply_filter("todos")

    def _compute_stats(self):
        total_in  = 0
        total_out = 0
        total_adj = 0
        last_sale = None
        last_buy  = None

        for m in self._all_movements:
            t = m.get("tipo", "")
            try:
                q = abs(float(m.get("cantidad", 0)))
            except (TypeError, ValueError):
                q = 0
            fecha = m.get("fecha", "")

            if t == "entrada":
                total_in += q
                # "última compra" = la entrada más reciente
                if last_buy is None:
                    last_buy = fecha
            elif t == "venta":
                total_out += q
                if last_sale is None:
                    last_sale = fecha
            elif t == "ajuste":
                total_adj += q

        self.card_total_in.set_value(str(total_in) if total_in else "—")
        self.card_total_out.set_value(str(total_out) if total_out else "—")
        self.card_total_adj.set_value(str(total_adj) if total_adj else "—")
        self.card_last_sale.set_value(
            last_sale[:10] if last_sale else "Sin ventas"
        )
        self.card_last_buy.set_value(
            last_buy[:10] if last_buy else "Sin entradas"
        )

    # ── Filtrado y render de tabla ────────────────────────────

    def _apply_filter(self, key: str):
        self._active_filter = key

        # Sincronizar estado de botones
        for btn, k in [
            (self.btn_all, "todos"), (self.btn_in, "entrada"),
            (self.btn_out, "venta"), (self.btn_adj, "ajuste"),
            (self.btn_dev, "devolucion"),
        ]:
            btn.setChecked(k == key)

        filtered = (
            self._all_movements if key == "todos"
            else [m for m in self._all_movements if m.get("tipo") == key]
        )

        self._render_table(filtered)

    def _render_table(self, movements: list):
        self.table.setRowCount(0)

        for row_idx, m in enumerate(movements):
            tipo   = m.get("tipo", "")
            style  = MOVEMENT_STYLES.get(tipo, {"icon": "❓", "label": tipo, "bg": "#2C2F33", "fg": "#FFFFFF"})
            try:
                qty = float(m.get("cantidad", 0))
            except (TypeError, ValueError):
                qty = 0

            # Ventas restan del inventario → mostrar como negativo
            if tipo == "venta":
                qty = -abs(qty)

            self.table.insertRow(row_idx)

            # Fecha
            self._cell(row_idx, COL_DATE,   m.get("fecha", "")[:16])
            # Tipo — badge de color
            self._badge_cell(row_idx, COL_TYPE, f"{style['icon']} {style['label']}", style["bg"], style["fg"])
            # Cantidad (positivo verde / negativo rojo)
            qty_color = "#4ADE80" if qty >= 0 else "#F87171"
            self._colored_cell(row_idx, COL_QTY, f"{'+' if qty > 0 else ''}{qty}", qty_color)
            # Stock antes / después
            self._cell(row_idx, COL_BEFORE, str(m.get("stock_antes", "")))
            self._cell(row_idx, COL_AFTER,  str(m.get("stock_despues", "")))
            # Referencia
            self._cell(row_idx, COL_REF,    m.get("referencia", "—"))
            # Notas
            self._cell(row_idx, COL_NOTES,  m.get("notas", "—"))

            # Altura de fila uniforme
            self.table.setRowHeight(row_idx, 36)

        self.lbl_count.setText(f"{len(movements)} registro{'s' if len(movements) != 1 else ''}")

    # ── Helpers de celdas ────────────────────────────────────

    def _cell(self, row: int, col: int, text: str, align=Qt.AlignVCenter):
        item = QTableWidgetItem(text)
        item.setTextAlignment(align | Qt.AlignLeft)
        item.setForeground(QColor("#D1D5DB"))
        self.table.setItem(row, col, item)

    def _colored_cell(self, row: int, col: int, text: str, color: str):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        item.setForeground(QColor(color))
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        self.table.setItem(row, col, item)

    def _badge_cell(self, row: int, col: int, text: str, bg: str, fg: str):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        item.setBackground(QColor(bg))
        item.setForeground(QColor(fg))
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        self.table.setItem(row, col, item)