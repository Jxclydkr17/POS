# ui/views/no_rotation_view.py
"""
Vista: Productos sin Rotación (Inventario Muerto)
Detecta productos activos con stock > 0 que no han tenido ventas
en los últimos 30, 60 o 90 días.
"""

import requests
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame, QMessageBox, QSizePolicy
)

from ui.session_manager import session
from ui.api import BASE_URL

API_BASE = BASE_URL

# ─────────────────────────────────────────────────────────────
# Paleta dark — texto y fondo por antigüedad
# ─────────────────────────────────────────────────────────────
COLOR_NEVER = QColor("#C4B5FD")   # Nunca vendido  → lavanda claro
COLOR_90    = QColor("#FCA5A5")   # >90 días       → rojo claro
COLOR_60    = QColor("#FDBA74")   # 60-89 días     → naranja claro
COLOR_30    = QColor("#FDE68A")   # 30-59 días     → amarillo claro

BG_NEVER = QColor("#2D1B69")     # morado oscuro
BG_90    = QColor("#450A0A")     # rojo oscuro
BG_60    = QColor("#431407")     # naranja oscuro
BG_30    = QColor("#422006")     # ámbar oscuro

# ─────────────────────────────────────────────────────────────
# Worker para llamada HTTP asíncrona
# ─────────────────────────────────────────────────────────────
class FetchWorker(QThread):
    finished = Signal(dict)
    error    = Signal(str)

    def __init__(self, days: int):
        super().__init__()
        self.days = days

    def run(self):
        try:
            # FIX: session.token (no existe get_token())
            token = session.token
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            r = requests.get(
                f"{API_BASE}/analytics/no-rotation",
                params={"days": self.days},
                headers=headers,
                timeout=15,
            )
            r.raise_for_status()
            self.finished.emit(r.json())
        except Exception as exc:
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────
# Tabla con orden numérico en columna "Días sin venta"
# ─────────────────────────────────────────────────────────────
class NumericItem(QTableWidgetItem):
    def __init__(self, display: str, sort_val: float):
        super().__init__(display)
        self._val = sort_val

    def __lt__(self, other):
        if isinstance(other, NumericItem):
            return self._val < other._val
        return super().__lt__(other)


# ─────────────────────────────────────────────────────────────
# Vista principal
# ─────────────────────────────────────────────────────────────
class NoRotationView(QWidget):
    def __init__(self):
        super().__init__()
        self._current_days = 30
        self._worker = None
        self._build_ui()
        self._load_data()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        # Fondo general dark (igual que el resto de la app)
        self.setStyleSheet("QWidget { background-color: #111827; color: #e5e7eb; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Título ──────────────────────────────────────────────────
        title = QLabel("🕳️ Productos sin Rotación")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #f9fafb; margin-bottom: 4px;"
        )
        root.addWidget(title)

        subtitle = QLabel(
            "Inventario activo con stock disponible que no ha registrado ventas en el período seleccionado."
        )
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #9ca3af; font-size: 13px; margin-bottom: 8px;")
        root.addWidget(subtitle)

        # ── Filtros de días ─────────────────────────────────────────
        filter_frame = QFrame()
        filter_frame.setStyleSheet(
            "QFrame { background: #1f2937; border: 1px solid #374151;"
            " border-radius: 10px; padding: 4px; }"
        )
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(12, 8, 12, 8)
        filter_layout.setSpacing(10)

        lbl = QLabel("📅  Sin ventas en los últimos:")
        lbl.setStyleSheet("color: #9ca3af;")
        filter_layout.addWidget(lbl)

        self._day_buttons: dict[int, QPushButton] = {}
        for d in (30, 60, 90):
            btn = QPushButton(f"  {d} días  ")
            btn.setCheckable(True)
            btn.setChecked(d == self._current_days)
            btn.setFixedHeight(32)
            btn.setStyleSheet(self._btn_style(d == self._current_days))
            btn.clicked.connect(lambda checked, days=d: self._on_filter_change(days))
            self._day_buttons[d] = btn
            filter_layout.addWidget(btn)

        filter_layout.addStretch()

        self._btn_refresh = QPushButton("🔄 Actualizar")
        self._btn_refresh.setFixedHeight(32)
        self._btn_refresh.setStyleSheet(
            "QPushButton { background: #3b82f6; color: white; border-radius: 6px;"
            " padding: 0 14px; font-weight: 600; }"
            "QPushButton:hover { background: #2563eb; }"
        )
        self._btn_refresh.clicked.connect(self._load_data)
        filter_layout.addWidget(self._btn_refresh)

        root.addWidget(filter_frame)

        # ── KPI cards ───────────────────────────────────────────────
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)

        self._kpi_count = self._make_kpi_card("📦 Productos afectados", "—", "#ef4444")
        self._kpi_value = self._make_kpi_card("💰 Valor inmovilizado", "—", "#f97316")
        self._kpi_never = self._make_kpi_card("⚠️ Nunca vendidos", "—", "#8b5cf6")

        kpi_row.addWidget(self._kpi_count)
        kpi_row.addWidget(self._kpi_value)
        kpi_row.addWidget(self._kpi_never)
        root.addLayout(kpi_row)

        # ── Estado de carga ─────────────────────────────────────────
        self._lbl_status = QLabel("")
        self._lbl_status.setAlignment(Qt.AlignCenter)
        self._lbl_status.setStyleSheet("color: #9ca3af; font-size: 13px;")
        root.addWidget(self._lbl_status)

        # ── Leyenda de colores ───────────────────────────────────────
        legend_row = QHBoxLayout()
        legend_row.setSpacing(16)
        legend_row.addStretch()
        for label, bg, fg in [
            ("Nunca vendido",  "#2D1B69", "#C4B5FD"),
            ("> 90 días",      "#450A0A", "#FCA5A5"),
            ("60 – 89 días",   "#431407", "#FDBA74"),
            ("30 – 59 días",   "#422006", "#FDE68A"),
        ]:
            dot = QLabel(f"  {label}  ")
            dot.setFixedHeight(22)
            dot.setStyleSheet(
                f"background: {bg}; color: {fg}; border-radius: 4px;"
                " font-size: 11px; font-weight: 600; padding: 0 6px;"
            )
            legend_row.addWidget(dot)
        legend_row.addStretch()
        root.addLayout(legend_row)

        # ── Tabla ────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "Código", "Nombre", "Categoría", "Stock",
            "Costo unit.", "Valor inventario", "Última venta", "Días sin venta",
        ])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(False)   # colores propios por fila
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(
            "QTableWidget { background: #1f2937; border: 1px solid #374151;"
            " border-radius: 8px; color: #e5e7eb; }"
            "QHeaderView::section { background: #111827; color: #9ca3af;"
            " font-weight: 600; padding: 8px 10px; border: none;"
            " border-bottom: 2px solid #374151; }"
            "QTableWidget::item { padding: 6px 10px; }"
            "QTableWidget::item:selected { background: #1e3a5f; color: #f9fafb; }"
            "QScrollBar:vertical { background: #111827; width: 8px; margin: 4px; }"
            "QScrollBar::handle:vertical { background: #374151; border-radius: 4px; }"
            "QScrollBar::handle:vertical:hover { background: #4b5563; }"
        )

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)   # Código
        hh.setSectionResizeMode(1, QHeaderView.Stretch)             # Nombre
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)   # Categoría
        for col in range(3, 8):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        root.addWidget(self._table, 1)

    # ------------------------------------------------------------------
    # KPI card helper
    # ------------------------------------------------------------------
    def _make_kpi_card(self, title: str, value: str, accent: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: #1f2937; border: 1px solid #374151;"
            f" border-left: 4px solid {accent}; border-radius: 10px; }}"
        )
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setFixedHeight(80)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(4)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 12px; color: #9ca3af; font-weight: 600;")

        lbl_value = QLabel(value)
        lbl_value.setObjectName("kpi_value")
        lbl_value.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {accent};"
        )

        lay.addWidget(lbl_title)
        lay.addWidget(lbl_value)

        card._value_label = lbl_value
        return card

    # ------------------------------------------------------------------
    # Estilos del botón de filtro
    # ------------------------------------------------------------------
    @staticmethod
    def _btn_style(active: bool) -> str:
        if active:
            return (
                "QPushButton { background: #1e40af; color: white; border-radius: 6px;"
                " font-weight: 700; border: none; }"
                "QPushButton:hover { background: #1d4ed8; }"
            )
        return (
            "QPushButton { background: #374151; color: #d1d5db; border-radius: 6px;"
            " font-weight: 600; border: none; }"
            "QPushButton:hover { background: #4b5563; }"
        )

    # ------------------------------------------------------------------
    # Cambio de filtro
    # ------------------------------------------------------------------
    def _on_filter_change(self, days: int):
        self._current_days = days
        for d, btn in self._day_buttons.items():
            btn.setChecked(d == days)
            btn.setStyleSheet(self._btn_style(d == days))
        self._load_data()

    # ------------------------------------------------------------------
    # Carga de datos
    # ------------------------------------------------------------------
    def _load_data(self):
        if self._worker and self._worker.isRunning():
            return

        self._lbl_status.setText("⏳ Cargando datos…")
        self._btn_refresh.setEnabled(False)
        self._table.setRowCount(0)

        self._worker = FetchWorker(self._current_days)
        self._worker.finished.connect(self._on_data_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_data_loaded(self, response: dict):
        self._btn_refresh.setEnabled(True)

        if not response.get("success"):
            msg = response.get("message", "Error desconocido")
            self._lbl_status.setText(f"❌ {msg}")
            return

        payload = response.get("data", {})
        products = payload.get("products", [])
        total_products = payload.get("total_products", 0)
        total_value = payload.get("total_stock_value", 0.0)
        never_count = sum(1 for p in products if p.get("last_sale_date") is None)

        # Actualizar KPIs
        self._kpi_count._value_label.setText(str(total_products))
        self._kpi_value._value_label.setText(f"₡{total_value:,.0f}")
        self._kpi_never._value_label.setText(str(never_count))

        # Poblar tabla
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(products))

        for row, p in enumerate(products):
            days_val = p.get("days_without_sale")
            last_sale = p.get("last_sale_date") or "—"

            # Determinar colores
            if days_val is None:
                bg, fg = BG_NEVER, COLOR_NEVER
                days_display = "Nunca vendido"
                sort_days = 99999
            elif days_val >= 90:
                bg, fg = BG_90, COLOR_90
                days_display = str(days_val)
                sort_days = days_val
            elif days_val >= 60:
                bg, fg = BG_60, COLOR_60
                days_display = str(days_val)
                sort_days = days_val
            else:
                bg, fg = BG_30, COLOR_30
                days_display = str(days_val)
                sort_days = days_val

            cells = [
                QTableWidgetItem(p.get("code", "")),
                QTableWidgetItem(p.get("name", "")),
                QTableWidgetItem(p.get("category", "Sin categoría")),
                NumericItem(str(p.get("stock", 0)), p.get("stock", 0)),
                NumericItem(f"₡{p.get('cost', 0):,.2f}", p.get("cost", 0)),
                NumericItem(f"₡{p.get('stock_value', 0):,.2f}", p.get("stock_value", 0)),
                QTableWidgetItem(last_sale),
                NumericItem(days_display, sort_days),
            ]

            for col, item in enumerate(cells):
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                item.setBackground(bg)
                item.setForeground(fg)
                font = item.font()
                font.setWeight(QFont.Medium)
                item.setFont(font)
                self._table.setItem(row, col, item)

        self._table.setSortingEnabled(True)
        # Ordenar por días sin venta descendente por defecto
        self._table.sortByColumn(7, Qt.DescendingOrder)

        self._lbl_status.setText(
            f"✅  Mostrando {total_products} producto(s) sin ventas en los últimos "
            f"{self._current_days} días."
        )

    def _on_error(self, msg: str):
        self._btn_refresh.setEnabled(True)
        self._lbl_status.setText(f"❌ Error al cargar datos: {msg}")
        QMessageBox.warning(self, "Error", f"No se pudo obtener datos:\n{msg}")