from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QMessageBox, QAbstractItemView, QHeaderView, QMenu,
    QComboBox, QFrame
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QPixmap, QIcon, QPainter, QPen, QBrush, QPainterPath
from ui.utils.http_worker import api_call, api_request
import os
from ui.session_manager import session
from decimal import Decimal, ROUND_HALF_UP
from ui.dialogs.add_product_dialog import IVA_RATES
from ui.dialogs.product_movements_dialog import ProductMovementsDialog
from PySide6.QtWidgets import QCompleter
from ui.api import BASE_URL


API_URL = f"{BASE_URL}/products"

# ─────────────────────────────────────────────────────────────
# COLUMNAS — índices centralizados
# ─────────────────────────────────────────────────────────────
COL_ID        = 0   # oculta
COL_IMG       = 1   # miniatura
COL_CODE      = 2
COL_NAME      = 3
COL_PRICE     = 4
COL_COST      = 5
COL_STOCK     = 6
COL_MIN       = 7
COL_STATUS    = 8
COL_CATEGORY  = 9
COL_SUPPLIER  = 10
COL_BARCODE   = 11  # oculta
COL_PROFIT    = 12  # oculta
COL_MARGIN    = 13  # oculta
COL_CABYS     = 14  # oculta
COL_IVA       = 15  # oculta

TOTAL_COLUMNS = 16

# Paleta de colores suaves para badges de categoría
BADGE_COLORS = [
    ("#D1ECF1", "#0C5460"),
    ("#D4EDDA", "#155724"),
    ("#FFF3CD", "#856404"),
    ("#F8D7DA", "#721C24"),
    ("#E2D9F3", "#4A148C"),
    ("#FFE5D0", "#7A3B00"),
    ("#D0E4FF", "#003380"),
    ("#F5E1FF", "#5A007A"),
]

SUPPLIER_COLORS = [
    ("#E8F5E9", "#1B5E20"),
    ("#EDE7F6", "#4527A0"),
    ("#FFF8E1", "#E65100"),
    ("#E3F2FD", "#0D47A1"),
    ("#FCE4EC", "#880E4F"),
    ("#F1F8E9", "#33691E"),
    ("#E8EAF6", "#283593"),
    ("#FFF3E0", "#BF360C"),
]

# Sin coloreo de filas — solo badges en columnas Estado/Categoría/Proveedor
ROW_BG_CRITICAL = None
ROW_BG_WARNING  = None
ROW_BG_LOW      = None
ROW_BG_OK       = None


def _clean_stock(value, default=0):
    """Convierte un valor de stock a float limpio.
    '5.000' → 5.0, '2.500' → 2.5, None → default
    """
    try:
        return float(value) if value is not None else float(default)
    except (ValueError, TypeError):
        return float(default)


def _format_stock(value, default=0):
    """Formatea un valor de stock para display.
    5.0 → '5', 2.5 → '2.5', 0.0 → '0'
    """
    num = _clean_stock(value, default)
    if num == int(num):
        return str(int(num))
    return str(round(num, 3)).rstrip('0').rstrip('.')


# ─────────────────────────────────────────────────────────────
# Items con ordenamiento personalizado
# ─────────────────────────────────────────────────────────────

class NumericTableItem(QTableWidgetItem):
    def __init__(self, display_text: str, sort_value: float):
        super().__init__(display_text)
        self._sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, NumericTableItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


class StockTableItem(QTableWidgetItem):
    def __init__(self, display_text: str, stock_val: int, min_stock_val: int):
        super().__init__(display_text)
        self._stock_val = stock_val
        self.setData(Qt.UserRole,     min_stock_val)
        self.setData(Qt.UserRole + 1, stock_val)

    def __lt__(self, other):
        if isinstance(other, StockTableItem):
            return self._stock_val < other._stock_val
        return super().__lt__(other)


class StatusTableItem(QTableWidgetItem):
    _ORDER = {"🔴": 0, "🟠": 1, "🟡": 2, "🟢": 3}

    def __init__(self, display_text: str, stock_val: int, min_stock_val: int):
        super().__init__(display_text)
        self.setData(Qt.UserRole,     min_stock_val)
        self.setData(Qt.UserRole + 1, stock_val)
        emoji = display_text[:2].strip() if display_text else ""
        self._priority = self._ORDER.get(emoji, 99)

    def __lt__(self, other):
        if isinstance(other, StatusTableItem):
            return self._priority < other._priority
        return super().__lt__(other)


def _badge_color(name: str, palette: list) -> tuple:
    if not name or name == "-":
        return ("#3A3F47", "#AAAAAA")
    idx = hash(name) % len(palette)
    return palette[idx]


def _make_placeholder_pixmap(size: int = 44) -> QPixmap:
    """Placeholder con ícono de cámara para la columna de imagen en la tabla."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)

    # Fondo redondeado
    path = QPainterPath()
    path.addRoundedRect(1, 1, size - 2, size - 2, 6, 6)
    painter.fillPath(path, QColor("#2A2E35"))
    pen = QPen(QColor("#4A5568"))
    pen.setWidth(1)
    painter.setPen(pen)
    painter.drawPath(path)

    # Cuerpo cámara
    cw, ch = size * 0.46, size * 0.30
    cx, cy = (size - cw) / 2, (size - ch) / 2 + size * 0.03
    painter.setBrush(QBrush(QColor("#4A5568")))
    pen.setColor(QColor("#6B7280"))
    painter.setPen(pen)
    painter.drawRoundedRect(int(cx), int(cy), int(cw), int(ch), 3, 3)

    # Visor
    vw, vh = cw * 0.28, ch * 0.28
    vx, vy = cx + cw * 0.32, cy - vh + 1
    painter.setBrush(QBrush(QColor("#4A5568")))
    painter.drawRoundedRect(int(vx), int(vy), int(vw), int(vh), 2, 2)

    # Lente
    lx, ly = size / 2, cy + ch / 2
    lr = size * 0.11
    painter.setBrush(QBrush(QColor("#1E2128")))
    pen.setColor(QColor("#9CA3AF"))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawEllipse(int(lx - lr), int(ly - lr), int(lr * 2), int(lr * 2))

    # Reflejo
    painter.setBrush(QBrush(QColor("#9CA3AF")))
    painter.setPen(Qt.NoPen)
    rl = lr * 0.36
    painter.drawEllipse(int(lx - lr * 0.48), int(ly - lr * 0.52), int(rl), int(rl))

    painter.end()
    return pm


def _load_thumbnail(image_path, size: int = 44) -> QPixmap:
    if not image_path:
        return _make_placeholder_pixmap(size)
    try:
        if not os.path.isabs(image_path):
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            image_path = os.path.join(base, image_path)
        if os.path.exists(image_path):
            pm = QPixmap(image_path)
            if not pm.isNull():
                return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        pass
    return _make_placeholder_pixmap(size)


class ProductsView(QWidget):
    def __init__(self, supplier_id=None, supplier_name=None, auto_low_stock: bool = False):
        super().__init__()
        self.supplier_id_filter = supplier_id
        self.supplier_name_filter = supplier_name
        self.auto_low_stock = auto_low_stock
        self.status_filter = True
        self.categories = set()
        self.btn_toggle_active = None
        self._clearing_filters = False

        self.current_page = 1
        self.page_size = 50
        self.total_products = 0
        self._categories_map: dict = {}
        self._suppliers_map: dict = {}

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._on_search_timeout)

        self.setup_ui()
        self._load_filter_options()
        self.load_products()

    COMBO_STYLE = """
        QComboBox {
            background-color: #3A3F47;
            color: #FFFFFF;
            border: 1px solid #555;
            border-radius: 6px;
            padding: 4px 8px;
            min-width: 130px;
            font-size: 12px;
        }
        QComboBox:hover { border-color: #5B9BD5; }
        QComboBox::drop-down { border: none; width: 20px; }
        QComboBox QAbstractItemView {
            background-color: #2C2F33;
            color: #FFFFFF;
            selection-background-color: #5B9BD5;
            border: 1px solid #555;
        }
    """

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)

        title = QLabel("📦 Lista de Productos")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px; color: #D9D9D9;")
        layout.addWidget(title)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Buscar por nombre, código, barras, CABYS, proveedor, categoría o descripción...")
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        filters_frame = QFrame()
        filters_frame.setStyleSheet("""
            QFrame {
                background-color: #23272B;
                border: 1px solid #3A3F47;
                border-radius: 8px;
                padding: 2px;
            }
        """)
        filters_row = QHBoxLayout(filters_frame)
        filters_row.setContentsMargins(8, 4, 8, 4)
        filters_row.setSpacing(10)

        lbl_filtros = QLabel("🔎 Filtros:")
        lbl_filtros.setStyleSheet("color: #AAAAAA; font-size: 12px; font-weight: bold;")
        filters_row.addWidget(lbl_filtros)

        self.combo_category = QComboBox()
        self.combo_category.setStyleSheet(self.COMBO_STYLE)
        self.combo_category.addItem("📁 Categoría")
        self.combo_category.currentIndexChanged.connect(self._on_combo_backend_filter_changed)
        filters_row.addWidget(self.combo_category)

        self.combo_supplier = QComboBox()
        self.combo_supplier.setStyleSheet(self.COMBO_STYLE)
        self.combo_supplier.addItem("🏭 Proveedor")
        self.combo_supplier.currentIndexChanged.connect(self._on_combo_backend_filter_changed)
        filters_row.addWidget(self.combo_supplier)

        self.combo_stock = QComboBox()
        self.combo_stock.setStyleSheet(self.COMBO_STYLE)
        self.combo_stock.addItems([
            "📦 Stock: Todos",
            "🟢 En stock",
            "🟡 Bajo",
            "🟠 Crítico",
            "🔴 Agotado",
            "⚠️ Stock bajo (≤ mín.)",
        ])
        self.combo_stock.currentIndexChanged.connect(self._on_combo_stock_changed)
        filters_row.addWidget(self.combo_stock)

        self.combo_status = QComboBox()
        self.combo_status.setStyleSheet(self.COMBO_STYLE)
        self.combo_status.addItems(["✅ Activos", "🚫 Inactivos", "📋 Todos"])
        self.combo_status.currentIndexChanged.connect(self._on_combo_status_changed)
        filters_row.addWidget(self.combo_status)

        filters_row.addStretch()

        btn_clear = QPushButton("✖ Limpiar")
        btn_clear.setStyleSheet("""
            QPushButton { background-color: #555; color: #DDD; border-radius: 6px; padding: 4px 10px; font-size: 11px; }
            QPushButton:hover { background-color: #DC3545; color: white; }
        """)
        btn_clear.clicked.connect(self.clear_filters)
        filters_row.addWidget(btn_clear)

        self.btn_filters = QPushButton("📂 Más filtros")
        self.btn_filters.setStyleSheet("""
            QPushButton { background-color: #3A3F47; color: #CCC; border: 1px solid #555; border-radius: 6px; padding: 4px 10px; font-size: 11px; }
            QPushButton:hover { background-color: #5B9BD5; color: white; }
        """)
        self.btn_filters.clicked.connect(self.show_filters_menu)
        filters_row.addWidget(self.btn_filters)

        layout.addWidget(filters_frame)

        # ── TABLA ──
        self.table = QTableWidget()
        self.table.setColumnCount(TOTAL_COLUMNS)
        self.table.setHorizontalHeaderLabels([
            "ID", "Imagen", "Código", "Nombre", "Precio", "Costo",
            "Stock", "Mín.", "Estado", "Categoría", "Proveedor",
            "Barras", "Ganancia", "Margen %", "CABYS", "IVA",
        ])

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)

        # Ocultar columnas auxiliares
        for col in (COL_ID, COL_BARCODE, COL_PROFIT, COL_MARGIN, COL_CABYS, COL_IVA):
            self.table.setColumnHidden(col, True)

        # Columna imagen fija; el resto estira
        self.table.horizontalHeader().setSectionResizeMode(COL_IMG, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_IMG, 60)
        for col in (COL_CODE, COL_NAME, COL_PRICE, COL_COST, COL_STOCK,
                    COL_MIN, COL_STATUS, COL_CATEGORY, COL_SUPPLIER):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Stretch)
        self.table.horizontalHeader().setStretchLastSection(False)

        self.table.verticalHeader().setDefaultSectionSize(58)
        self.table.verticalHeader().setVisible(False)

        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder

        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #2C2F33;
                alternate-background-color: #32383E;
                color: #FFFFFF;
                gridline-color: #3D4349;
                selection-background-color: #4A78A8;
                selection-color: #FFFFFF;
            }
            QHeaderView::section {
                background-color: #1E2126;
                color: #A8C4E0;
                font-weight: bold;
                font-size: 12px;
                padding: 6px 4px;
                border: none;
                border-bottom: 2px solid #5B9BD5;
            }
            QHeaderView::section:hover { background-color: #2A3040; }
            QHeaderView::section:pressed { background-color: #3A72A0; }
            QHeaderView::down-arrow { image: none; width: 0px; }
            QHeaderView::up-arrow   { image: none; width: 0px; }
            QTableWidget::item { padding: 4px 6px; }
        """)
        layout.addWidget(self.table)

        # ── PAGINACIÓN ──
        pagination_frame = QFrame()
        pagination_frame.setStyleSheet("QFrame { background-color: #23272B; border: 1px solid #3A3F47; border-radius: 8px; }")
        pagination_layout = QHBoxLayout(pagination_frame)
        pagination_layout.setContentsMargins(10, 4, 10, 4)
        pagination_layout.setSpacing(8)

        lbl_per_page = QLabel("Por página:")
        lbl_per_page.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        pagination_layout.addWidget(lbl_per_page)

        self.combo_page_size = QComboBox()
        self.combo_page_size.setStyleSheet(self.COMBO_STYLE)
        self.combo_page_size.setFixedWidth(75)
        for size in [25, 50, 100, 200]:
            self.combo_page_size.addItem(str(size))
        self.combo_page_size.setCurrentIndex(1)
        self.combo_page_size.currentIndexChanged.connect(self._on_page_size_changed)
        pagination_layout.addWidget(self.combo_page_size)

        pagination_layout.addStretch()

        _btn_style = """
            QPushButton { background-color: #3A3F47; color: #DDD; border: 1px solid #555; border-radius: 6px; padding: 4px 8px; font-size: 12px; }
            QPushButton:hover:enabled { background-color: #5B9BD5; color: white; }
            QPushButton:disabled { color: #555; border-color: #333; }
        """
        self.btn_prev_page = QPushButton("◀ Anterior")
        self.btn_prev_page.setFixedWidth(100)
        self.btn_prev_page.setStyleSheet(_btn_style)
        self.btn_prev_page.clicked.connect(self._prev_page)
        pagination_layout.addWidget(self.btn_prev_page)

        self.lbl_page_info = QLabel("Página 1 de 1  ·  0 productos")
        self.lbl_page_info.setStyleSheet("color: #CCCCCC; font-size: 12px; min-width: 220px;")
        self.lbl_page_info.setAlignment(Qt.AlignCenter)
        pagination_layout.addWidget(self.lbl_page_info)

        self.btn_next_page = QPushButton("Siguiente ▶")
        self.btn_next_page.setFixedWidth(100)
        self.btn_next_page.setStyleSheet(_btn_style)
        self.btn_next_page.clicked.connect(self._next_page)
        pagination_layout.addWidget(self.btn_next_page)

        pagination_layout.addStretch()
        layout.addWidget(pagination_frame)

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.doubleClicked.connect(self.edit_product)

        button_layout = QHBoxLayout()
        static_actions = [
            ("🔄 Actualizar",  self.load_products,    "#17A2B8"),
            ("➕ Agregar stock", self.add_stock_dialog, "#6F42C1"),
            ("➕ Agregar",      self.add_product,       "#28A745"),
            ("✏️ Editar",       self.edit_product,      "#FFC107"),
        ]
        for text, func, color in static_actions:
            btn = QPushButton(text)
            btn.clicked.connect(func)
            btn.setStyleSheet(f"""
                QPushButton {{ background-color: {color}; color: white; font-weight: bold; padding: 8px; border-radius: 8px; min-width: 120px; }}
                QPushButton:hover {{ background-color: #4B4B4B; }}
            """)
            button_layout.addWidget(btn)

        self.btn_toggle_active = QPushButton()
        self.btn_toggle_active.setMinimumWidth(140)
        button_layout.addWidget(self.btn_toggle_active)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        self.update_toggle_button_state()
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.returnPressed.connect(self._on_search_timeout)

    # ── Filtros ──────────────────────────────────────────────
    def _load_filter_options(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            resp_cat = api_request("get", f"{BASE_URL}/categories", headers=headers)
            if resp_cat.status_code == 200:
                cats = resp_cat.json().get("data", [])
                self._categories_map = {c["name"]: c["id"] for c in cats if c.get("is_active", True)}

            resp_sup = api_request("get", f"{BASE_URL}/suppliers", headers=headers)
            if resp_sup.status_code == 200:
                sups = resp_sup.json() if isinstance(resp_sup.json(), list) else resp_sup.json().get("items", resp_sup.json().get("data", []))
                self._suppliers_map = {s["name"]: s["id"] for s in sups if s.get("is_active", True)}

            self._populate_filter_combos()
        except Exception:
            pass

    def _update_pagination_controls(self):
        total_pages = max(1, -(-self.total_products // self.page_size))
        self.lbl_page_info.setText(f"Página {self.current_page} de {total_pages}  ·  {self.total_products:,} productos")
        self.btn_prev_page.setEnabled(self.current_page > 1)
        self.btn_next_page.setEnabled(self.current_page < total_pages)

    def _prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load_products()

    def _next_page(self):
        total_pages = max(1, -(-self.total_products // self.page_size))
        if self.current_page < total_pages:
            self.current_page += 1
            self.load_products()

    def _on_page_size_changed(self, _index):
        self.page_size = int(self.combo_page_size.currentText())
        self.current_page = 1
        self.load_products()

    def _on_search_changed(self, _text):
        self._search_timer.start(400)

    def _on_search_timeout(self):
        self.current_page = 1
        self.load_products()

    def _on_combo_backend_filter_changed(self, _index):
        self.current_page = 1
        self.load_products()

    def _on_combo_stock_changed(self, _index):
        self._apply_stock_filter()

    def _apply_stock_filter(self):
        stock_filter = self.combo_stock.currentText()
        use_stock = not stock_filter.startswith("📦 Stock: Todos")

        for row in range(self.table.rowCount()):
            if not use_stock:
                self.table.setRowHidden(row, False)
                continue

            stock_item  = self.table.item(row, COL_STOCK)
            status_item = self.table.item(row, COL_STATUS)

            if not stock_item:
                self.table.setRowHidden(row, True)
                continue

            stock_val     = stock_item.data(Qt.UserRole + 1)
            min_stock_val = stock_item.data(Qt.UserRole)

            stock_val = _clean_stock(stock_val)
            min_stock_val = _clean_stock(min_stock_val)

            status_text = status_item.text() if status_item else ""

            if "⚠️ Stock bajo" in stock_filter:
                visible = stock_val <= min_stock_val
            elif "🟢 En stock" in stock_filter:
                visible = "🟢" in status_text
            elif "🟡 Bajo" in stock_filter:
                visible = "🟡" in status_text
            elif "🟠 Crítico" in stock_filter:
                visible = "🟠" in status_text
            elif "🔴 Agotado" in stock_filter:
                visible = "🔴" in status_text
            else:
                visible = True

            self.table.setRowHidden(row, not visible)

    # ── Ordenamiento ─────────────────────────────────────────
    _SORTABLE_COLUMNS = {
        COL_CODE: "Código", COL_NAME: "Nombre", COL_PRICE: "Precio",
        COL_COST: "Costo",  COL_STOCK: "Stock", COL_MIN: "Mín.",
        COL_STATUS: "Estado", COL_CATEGORY: "Categoría", COL_SUPPLIER: "Proveedor",
    }

    def _on_header_clicked(self, logical_index: int):
        if logical_index not in self._SORTABLE_COLUMNS:
            self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
            self._sort_column = -1
            return

        if self._sort_column == logical_index:
            self._sort_order = Qt.DescendingOrder if self._sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self._sort_column = logical_index
            self._sort_order = Qt.AscendingOrder

        self.table.sortItems(logical_index, self._sort_order)
        self.table.horizontalHeader().setSortIndicator(logical_index, self._sort_order)

    def _update_sortable_header_labels(self):
        labels = [
            "ID", "Imagen", "Código ↕", "Nombre ↕", "Precio ↕", "Costo ↕",
            "Stock ↕", "Mín. ↕", "Estado ↕", "Categoría ↕", "Proveedor ↕",
            "Barras", "Ganancia", "Margen %", "CABYS", "IVA",
        ]
        for col, label in enumerate(labels):
            item = self.table.horizontalHeaderItem(col)
            if item:
                item.setText(label)

    def update_toggle_button_state(self):
        if not self.btn_toggle_active:
            return
        if self.btn_toggle_active.receivers("clicked()") > 0:
            self.btn_toggle_active.clicked.disconnect()

        if self.status_filter is False:
            text, color, handler = "✅ Reactivar", "#28A745", self.reactivate_selected_product
        else:
            text, color, handler = "🚫 Desactivar", "#DC3545", self.deactivate_selected_product

        self.btn_toggle_active.setText(text)
        self.btn_toggle_active.clicked.connect(handler)
        self.btn_toggle_active.setStyleSheet(f"""
            QPushButton {{ background-color: {color}; color: white; font-weight: bold; padding: 8px; border-radius: 8px; min-width: 120px; }}
            QPushButton:hover {{ background-color: #4B4B4B; }}
        """)

    def get_stock_status(self, stock, min_stock):
        stock = _clean_stock(stock)
        min_stock = _clean_stock(min_stock)

        low_margin = max(2, min_stock * 0.5)

        if stock == 0:
            return "🔴 Agotado",  QColor("#5C1A1A"), QColor("#FF8080"), ROW_BG_CRITICAL
        elif stock <= min_stock:
            return "🟠 Crítico",  QColor("#5C3500"), QColor("#FFA040"), ROW_BG_WARNING
        elif stock <= (min_stock + low_margin):
            return "🟡 Bajo",     QColor("#4A3800"), QColor("#FFD966"), ROW_BG_LOW
        else:
            return "🟢 En stock", QColor("#1A3A1A"), QColor("#66CC66"), ROW_BG_OK

    # ── Carga de datos ────────────────────────────────────────
    def load_products(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}

            skip = (self.current_page - 1) * self.page_size
            params = {"skip": skip, "limit": self.page_size}

            if self.status_filter is True:
                params["is_active"] = "true"
            elif self.status_filter is False:
                params["is_active"] = "false"

            if getattr(self, "supplier_id_filter", None):
                params["supplier_id"] = self.supplier_id_filter

            search_text = self.search_input.text().strip()
            if search_text:
                params["search"] = search_text

            if not getattr(self, "_clearing_filters", False):
                cat_name = self.combo_category.currentText()
                if not cat_name.startswith("📁") and cat_name in self._categories_map:
                    params["category_id"] = self._categories_map[cat_name]

                if not params.get("supplier_id"):
                    sup_name = self.combo_supplier.currentText()
                    if not sup_name.startswith("🏭") and sup_name in self._suppliers_map:
                        params["supplier_id"] = self._suppliers_map[sup_name]

            response = api_request("get", API_URL, headers=headers, params=params)

            if response.status_code == 200:
                from ui.dialogs.add_product_dialog import IVA_RATES

                payload  = response.json()
                products = payload.get("data", [])
                if not isinstance(products, list):
                    raise ValueError("El campo 'data' no es una lista.")
                self.total_products = payload.get("total") or len(products)

                self.categories = {p.get("category_name", "-") for p in products if p.get("category_name")}
                self.table.setRowCount(len(products))
                self.table.setSortingEnabled(False)

                for _r in range(len(products)):
                    self.table.setRowHidden(_r, False)

                PRECISION_COMPARE = Decimal('0.0001')

                def iva_label(value):
                    if value is None:
                        return "Tarifa Exenta"
                    try:
                        d = Decimal(str(value)).quantize(PRECISION_COMPARE)
                    except Exception:
                        return "Tarifa Desconocida"
                    if d == Decimal("0.0000"):
                        return "Tarifa 0% (Artículo 32, num 1, RLIVA)"
                    for label, rate in IVA_RATES.items():
                        if rate is None:
                            continue
                        if d == Decimal(str(rate)).quantize(PRECISION_COMPARE):
                            return label
                    return "Tarifa Desconocida"

                def colored_item(text, bg_hex, fg_hex, align=Qt.AlignCenter):
                    it = QTableWidgetItem(text)
                    it.setBackground(QColor(bg_hex))
                    it.setForeground(QColor(fg_hex))
                    it.setTextAlignment(align)
                    f = it.font(); f.setBold(True); it.setFont(f)
                    return it

                for row, product in enumerate(products):
                    stock_val     = _clean_stock(product.get("stock", 0))
                    min_stock_val = _clean_stock(product.get("min_stock", 3))
                    status_text, status_bg, status_fg, row_bg = self.get_stock_status(stock_val, min_stock_val)

                    # Col 0 — ID (oculto)
                    id_item = QTableWidgetItem(str(product.get("id", "")))
                    id_item.setData(Qt.UserRole,     product.get("is_active",       True))
                    id_item.setData(Qt.UserRole + 1, product.get("is_pos_favorite", False))
                    self.table.setItem(row, COL_ID, id_item)

                    # Col 1 — Imagen
                    img_lbl = QLabel()
                    img_lbl.setAlignment(Qt.AlignCenter)
                    img_lbl.setPixmap(_load_thumbnail(product.get("image_path"), size=48))
                    img_lbl.setFixedSize(58, 58)
                    img_lbl.setStyleSheet("background: transparent; padding: 2px;")
                    self.table.setCellWidget(row, COL_IMG, img_lbl)

                    # Col 2 — Código
                    self.table.setItem(row, COL_CODE, QTableWidgetItem(product.get("code", "-")))

                    # Col 3 — Nombre (bold + tooltip)
                    name_item = QTableWidgetItem(product.get("name", "-"))
                    desc = product.get("description") or ""
                    if desc:
                        name_item.setToolTip(desc)
                    f = name_item.font(); f.setBold(True); name_item.setFont(f)
                    self.table.setItem(row, COL_NAME, name_item)

                    # Col 4 — Precio
                    try:
                        price_value = float(product.get("price") or 0)
                    except Exception:
                        price_value = 0
                    p_item = NumericTableItem(f"₡{price_value:,.2f}", price_value)
                    p_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.table.setItem(row, COL_PRICE, p_item)

                    # Col 5 — Costo
                    try:
                        cost_value = float(product.get("cost") or 0)
                    except Exception:
                        cost_value = 0
                    c_item = NumericTableItem(f"₡{cost_value:,.2f}", cost_value)
                    c_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    c_item.setForeground(QColor("#AAAAAA"))
                    self.table.setItem(row, COL_COST, c_item)

                    # Col 6 — Stock
                    st_item = StockTableItem(_format_stock(stock_val), stock_val, min_stock_val)
                    st_item.setTextAlignment(Qt.AlignCenter)
                    st_item.setToolTip(f"Stock actual: {_format_stock(stock_val)}  |  Mínimo: {_format_stock(min_stock_val)}")
                    self.table.setItem(row, COL_STOCK, st_item)

                    # Col 7 — Mínimo
                    mn_item = NumericTableItem(_format_stock(min_stock_val), min_stock_val)
                    mn_item.setTextAlignment(Qt.AlignCenter)
                    mn_item.setForeground(QColor("#888888"))
                    self.table.setItem(row, COL_MIN, mn_item)

                    # Col 8 — Estado
                    status_item = StatusTableItem(status_text, stock_val, min_stock_val)
                    status_item.setTextAlignment(Qt.AlignCenter)
                    status_item.setToolTip(f"Stock: {stock_val}  |  Mín: {min_stock_val}")
                    self.table.setItem(row, COL_STATUS, status_item)

                    # Col 9 — Categoría
                    cat_name = product.get("category_name") or "-"
                    self.table.setItem(row, COL_CATEGORY, QTableWidgetItem(cat_name))

                    # Col 10 — Proveedor
                    sup_name = product.get("supplier_name") or "-"
                    self.table.setItem(row, COL_SUPPLIER, QTableWidgetItem(sup_name))

                    # Cols ocultas
                    self.table.setItem(row, COL_BARCODE, QTableWidgetItem(product.get("barcode", "-")))
                    profit = price_value - cost_value
                    margin = (profit / cost_value * 100) if cost_value > 0 else 0
                    self.table.setItem(row, COL_PROFIT, NumericTableItem(f"₡{profit:,.2f}", profit))
                    self.table.setItem(row, COL_MARGIN,  NumericTableItem(f"{margin:.1f}%", margin))
                    self.table.setItem(row, COL_CABYS,   QTableWidgetItem(product.get("cabys_code", "-")))
                    self.table.setItem(row, COL_IVA,     QTableWidgetItem(iva_label(product.get("tax_rate"))))



            else:
                raise Exception(f"Error {response.status_code}: {response.text}")

            self.setup_autocomplete()
            self.update_toggle_button_state()
            self.table.setSortingEnabled(True)
            self._update_sortable_header_labels()
            self._update_pagination_controls()
            self._apply_stock_filter()

            if getattr(self, "auto_low_stock", False):
                self.combo_stock.blockSignals(True)
                self.combo_stock.setCurrentIndex(5)
                self.combo_stock.blockSignals(False)
                self._apply_stock_filter()
                self.auto_low_stock = False

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudieron cargar los productos:\n{e}")

    # ── Combos ───────────────────────────────────────────────
    def _populate_filter_combos(self):
        self.combo_category.blockSignals(True)
        self.combo_supplier.blockSignals(True)

        clearing = getattr(self, "_clearing_filters", False)
        current_cat = self.combo_category.currentText() if not clearing else None
        current_sup = self.combo_supplier.currentText() if not clearing else None

        self.combo_category.clear()
        self.combo_category.addItem("📁 Categoría")
        for name in sorted(self._categories_map.keys()):
            self.combo_category.addItem(name)

        self.combo_supplier.clear()
        self.combo_supplier.addItem("🏭 Proveedor")
        for name in sorted(self._suppliers_map.keys()):
            self.combo_supplier.addItem(name)

        if current_cat:
            idx = self.combo_category.findText(current_cat)
            if idx >= 0:
                self.combo_category.setCurrentIndex(idx)

        if current_sup:
            idx = self.combo_supplier.findText(current_sup)
            if idx >= 0:
                self.combo_supplier.setCurrentIndex(idx)

        self.combo_category.blockSignals(False)
        self.combo_supplier.blockSignals(False)

    def _on_combo_status_changed(self, _index):
        text = self.combo_status.currentText()
        if "Inactivos" in text:
            self.status_filter = False
        elif "Todos" in text:
            self.status_filter = None
        else:
            self.status_filter = True
        self.current_page = 1
        self.update_toggle_button_state()
        self.load_products()

    def _on_combo_filter_changed(self, _index):
        pass

    # ── Menú contextual ──────────────────────────────────────
    def show_context_menu(self, pos):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return

        id_item = self.table.item(selected_row, COL_ID)
        if not id_item:
            return

        is_active      = id_item.data(Qt.UserRole)
        is_pos_favorite = id_item.data(Qt.UserRole + 1)

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #2C2F33; color: #FFFFFF; border: 1px solid #444; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background-color: #5B9BD5; }
            QMenu::item:disabled { color: #666; }
            QMenu::separator { height: 1px; background: #444; margin: 4px 8px; }
        """)

        action_edit      = menu.addAction("✏️ Editar")
        action_stock     = menu.addAction("➕ Agregar stock")
        action_duplicate = menu.addAction("🧬 Duplicar producto")
        menu.addSeparator()
        action_toggle = menu.addAction("🚫 Desactivar" if is_active else "✅ Reactivar")
        menu.addSeparator()
        action_favorite = menu.addAction("⭐ Quitar de favoritos POS" if is_pos_favorite else "⭐ Marcar como favorito POS")
        menu.addSeparator()
        action_history = menu.addAction("📋 Historial de movimientos")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))

        if action == action_edit:
            self.edit_product()
        elif action == action_stock:
            self.adjust_stock_from_context()
        elif action == action_duplicate:
            self.duplicate_product()
        elif action == action_toggle:
            self.deactivate_selected_product() if is_active else self.reactivate_selected_product()
        elif action == action_favorite:
            self.toggle_pos_favorite()
        elif action == action_history:
            self.show_product_movements()

    # ── Historial de movimientos ──────────────────────────────
    def show_product_movements(self):
        """Abre el diálogo de historial de movimientos del producto seleccionado."""
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return

        id_item   = self.table.item(selected_row, COL_ID)
        name_item = self.table.item(selected_row, COL_NAME)
        if not id_item or not name_item:
            return

        product_id   = int(id_item.text())
        product_name = name_item.text()

        dlg = ProductMovementsDialog(product_id, product_name, parent=self)
        dlg.exec()

    # ── CRUD ─────────────────────────────────────────────────
    def search_product(self):
        self._on_search_timeout()

    def clear_filters(self):
        self.status_filter = True
        self.current_page = 1
        self._clearing_filters = True
        self.search_input.clear()
        self._search_timer.stop()

        for combo, idx in [
            (self.combo_category, 0), (self.combo_supplier, 0),
            (self.combo_stock, 0),    (self.combo_status, 0),
        ]:
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, False)

        self.load_products()
        self._clearing_filters = False

    def add_product(self):
        from ui.dialogs.add_product_dialog import AddProductDialog
        dialog = AddProductDialog()
        if dialog.exec():
            self.load_products()

    def edit_product(self):
        from ui.dialogs.edit_product_dialog import EditProductDialog
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona un producto para editar.")
            return
        try:
            product_id = int(self.table.item(selected_row, COL_ID).text())
            headers = {"Authorization": f"Bearer {session.token}"}
            resp = api_request("get", f"{API_URL}/{product_id}", headers=headers)
            if resp.status_code != 200:
                QMessageBox.critical(self, "Error", "No se pudo obtener información completa del producto.")
                return
            dialog = EditProductDialog(resp.json()["data"])
            if dialog.exec():
                self.load_products()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo editar el producto:\n{e}")

    def deactivate_selected_product(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona un producto.")
            return
        try:
            product_id = int(self.table.item(selected_row, COL_ID).text())
            confirm = QMessageBox(self)
            confirm.setWindowTitle("Confirmar desactivación")
            confirm.setText("¿Deseas desactivar el producto seleccionado?")
            confirm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            confirm.button(QMessageBox.Yes).setText("🚫 Desactivar")
            confirm.button(QMessageBox.No).setText("❌ Cancelar")
            confirm.button(QMessageBox.Yes).setStyleSheet("background-color: #DC3545; color: white;")
            confirm.button(QMessageBox.No).setStyleSheet("background-color: #6C757D; color: white;")
            if confirm.exec() != QMessageBox.Yes:
                return
            headers = {"Authorization": f"Bearer {session.token}"}
            resp = api_request("patch", f"{API_URL}/{product_id}/deactivate", headers=headers)
            if resp.status_code == 200:
                QMessageBox.information(self, "OK", "Producto desactivado correctamente.")
                self.load_products()
            else:
                QMessageBox.critical(self, "Error", resp.text)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo desactivar el producto:\n{e}")

    def reactivate_selected_product(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona un producto.")
            return
        try:
            product_id = int(self.table.item(selected_row, COL_ID).text())
            confirm = QMessageBox(self)
            confirm.setWindowTitle("Confirmar reactivación")
            confirm.setText("¿Deseas reactivar el producto seleccionado?")
            confirm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            confirm.button(QMessageBox.Yes).setText("✅ Reactivar")
            confirm.button(QMessageBox.No).setText("❌ Cancelar")
            confirm.button(QMessageBox.Yes).setStyleSheet("background-color: #28A745; color: white;")
            confirm.button(QMessageBox.No).setStyleSheet("background-color: #6C757D; color: white;")
            if confirm.exec() != QMessageBox.Yes:
                return
            headers = {"Authorization": f"Bearer {session.token}"}
            resp = api_request("patch", f"{API_URL}/{product_id}/reactivate", headers=headers)
            if resp.status_code == 200:
                QMessageBox.information(self, "OK", "Producto reactivado correctamente.")
                self.load_products()
            else:
                QMessageBox.critical(self, "Error", resp.text)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo reactivar el producto:\n{e}")

    def delete_product(self):
        if self.status_filter is False:
            self.reactivate_selected_product()
        else:
            self.deactivate_selected_product()

    def adjust_stock_from_context(self):
        from ui.dialogs.add_stock_dialog import AddStockDialog
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona un producto.")
            return
        try:
            product_id = int(self.table.item(selected_row, COL_ID).text())
            headers = {"Authorization": f"Bearer {session.token}"}
            resp = api_request("get", f"{API_URL}/{product_id}", headers=headers)
            if resp.status_code != 200:
                QMessageBox.critical(self, "Error", "No se pudo obtener el producto.")
                return
            dialog = AddStockDialog(product_data=resp.json()["data"])
            if dialog.exec():
                self.load_products()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir el diálogo de stock:\n{e}")

    def toggle_pos_favorite(self):
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona un producto.")
            return
        try:
            id_item = self.table.item(selected_row, COL_ID)
            product_id = int(id_item.text())
            new_value  = not id_item.data(Qt.UserRole + 1)
            headers = {"Authorization": f"Bearer {session.token}"}
            resp = api_request("patch",
                f"{API_URL}/{product_id}/favorite",
                headers=headers,
                params={"is_pos_favorite": str(new_value).lower()}
            )
            if resp.status_code == 200:
                label = "marcado como favorito POS" if new_value else "removido de favoritos POS"
                QMessageBox.information(self, "OK", f"Producto {label}.")
                self.load_products()
            else:
                QMessageBox.critical(self, "Error", resp.text)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo actualizar favorito POS:\n{e}")

    def setup_autocomplete(self):
        seen = set()
        suggestions = []
        AUTOCOMPLETE_COLUMNS = [COL_CODE, COL_NAME, COL_CATEGORY, COL_SUPPLIER, COL_CABYS, COL_BARCODE]
        for row in range(self.table.rowCount()):
            for col in AUTOCOMPLETE_COLUMNS:
                item = self.table.item(row, col)
                if item:
                    text = item.text().strip()
                    if text and text != "-" and text not in seen:
                        seen.add(text)
                        suggestions.append(text)
        completer = QCompleter(sorted(suggestions))
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.search_input.setCompleter(completer)

    def show_filters_menu(self):
        menu = QMenu(self)
        menu.addAction("Mostrar todo", self.clear_filters)
        menu.addSeparator()
        menu.addAction("⚠️ Stock bajo (<= mínimo)", self.apply_filter_low_stock)
        menu.addSeparator()
        status_menu = menu.addMenu("Estado")
        status_menu.addAction("✅ Activos",   lambda: self.apply_status_filter(True))
        status_menu.addAction("🚫 Inactivos", lambda: self.apply_status_filter(False))
        status_menu.addAction("📦 Todos",     lambda: self.apply_status_filter(None))
        menu.addSeparator()
        category_menu = menu.addMenu("Categorías")
        if self.categories:
            for cat in sorted(self.categories):
                category_menu.addAction(cat, lambda c=cat: self.apply_filter_category(c))
        else:
            category_menu.addAction("Sin categorías")
        supplier_menu = menu.addMenu("Proveedores")
        suppliers = self.get_suppliers_list()
        if suppliers:
            for sp in sorted(suppliers):
                supplier_menu.addAction(sp, lambda s=sp: self.apply_filter_supplier(s))
        else:
            supplier_menu.addAction("Sin proveedores")
        menu.exec(self.btn_filters.mapToGlobal(self.btn_filters.rect().bottomLeft()))

    def get_suppliers_list(self):
        suppliers = set()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_SUPPLIER)
            if item:
                suppliers.add(item.text())
        return suppliers

    def apply_filter_category(self, category):
        for row in range(self.table.rowCount()):
            cat_item = self.table.item(row, COL_CATEGORY)
            visible = cat_item and category.lower() in cat_item.text().lower()
            self.table.setRowHidden(row, not visible)

    def apply_filter_supplier(self, supplier):
        for row in range(self.table.rowCount()):
            sup_item = self.table.item(row, COL_SUPPLIER)
            visible = sup_item and supplier.lower() in sup_item.text().lower()
            self.table.setRowHidden(row, not visible)

    def apply_filter_low_stock(self):
        for row in range(self.table.rowCount()):
            stock_item = self.table.item(row, COL_STOCK)
            if not stock_item:
                self.table.setRowHidden(row, True)
                continue
            try:
                stock     = _clean_stock(stock_item.data(Qt.UserRole + 1))
                min_stock = _clean_stock(stock_item.data(Qt.UserRole), 3)
            except Exception:
                stock, min_stock = 0, 3
            self.table.setRowHidden(row, stock > min_stock)

    def apply_status_filter(self, value):
        self.status_filter = value
        self.update_toggle_button_state()
        self.combo_status.blockSignals(True)
        if value is False:
            self.combo_status.setCurrentIndex(1)
        elif value is None:
            self.combo_status.setCurrentIndex(2)
        else:
            self.combo_status.setCurrentIndex(0)
        self.combo_status.blockSignals(False)
        self.load_products()

    def add_stock_dialog(self):
        from ui.dialogs.add_stock_dialog import AddStockDialog
        dialog = AddStockDialog()
        if dialog.exec():
            self.load_products()

    def duplicate_product(self):
        from ui.dialogs.add_product_dialog import AddProductDialog
        selected_row = self.table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona un producto para duplicar.")
            return
        try:
            product_id = int(self.table.item(selected_row, COL_ID).text())
            headers = {"Authorization": f"Bearer {session.token}"}
            resp = api_request("get", f"{API_URL}/{product_id}", headers=headers)
            if resp.status_code != 200:
                QMessageBox.critical(self, "Error", "No se pudo obtener el producto para duplicar.")
                return
            dialog = AddProductDialog(initial_data=resp.json()["data"], duplicate_mode=True)
            if dialog.exec():
                self.load_products()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo duplicar el producto:\n{e}")