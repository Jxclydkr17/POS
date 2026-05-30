# ui/views/expenses_view.py
"""
Vista de Gastos Operativos — Rediseño visual (FASE UI).

Mantiene 100 % la lógica y la API pública de la versión anterior
(load_expenses, add_expense, edit_expense, delete_expense, export_pdf,
export_excel, paginación, callbacks _on_expenses_*), pero con una
interfaz profesional, limpia y amigable, alineada con el design
system de Violette POS:

    Fondo app .......... #111827
    Tarjetas/paneles ... #1f2933
    Paneles oscuros .... #161e2a
    Acento indigo ...... #4f46e5 / #6366f1
    Acento azul ........ #2563eb
    Texto principal .... #e5e7eb
    Texto secundario ... #9ca3af / #6b7280
    Bordes ............. #374151
    Verde .............. #22c55e   Rojo .... #ef4444   Ámbar ... #f59e0b

FASE 1 — Fix 1.1 / 1.2: Carga asíncrona + timeout en acciones (intacto).
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem, QMessageBox,
    QDateEdit, QDialog, QFormLayout, QDialogButtonBox, QFileDialog,
    QHeaderView, QFrame, QSizePolicy, QAbstractItemView, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor
import logging

from ui.session_manager import session
from ui.api import BASE_URL
from ui.utils.calendar_fix import fix_calendar_colors
from ui.utils.http_worker import api_call, api_request
from app.utils.export_utils import export_expenses_pdf
from app.constants.expense_categories import EXPENSE_CATEGORIES, EXPENSE_CATEGORIES_FILTER
from app.constants.payment_methods import ALL_PAYMENT_METHODS

try:
    from ui.components.toast_notifier import show_toast
except Exception:  # pragma: no cover - fallback si no está disponible
    show_toast = None

logger = logging.getLogger(__name__)

API_URL = BASE_URL
API_URL_EXPENSES = f"{BASE_URL}/expenses"

PAGE_SIZE = 50


# ======================================================================
# Paleta y colores semánticos
# ======================================================================
COLOR_BG          = "#111827"
COLOR_CARD        = "#1f2933"
COLOR_CARD_DARK   = "#161e2a"
COLOR_INPUT       = "#161e2a"
COLOR_BORDER      = "#2b3647"
COLOR_BORDER_SOFT = "#374151"
COLOR_TEXT        = "#e5e7eb"
COLOR_TEXT_SOFT   = "#9ca3af"
COLOR_TEXT_MUTED  = "#6b7280"
COLOR_INDIGO      = "#4f46e5"
COLOR_INDIGO_Hi   = "#6366f1"
COLOR_BLUE        = "#2563eb"
COLOR_GREEN       = "#22c55e"
COLOR_RED         = "#ef4444"
COLOR_RED_Hi      = "#f87171"
COLOR_AMBER       = "#f59e0b"

# Color por categoría (badge en la tabla)
_CATEGORY_COLORS = {
    "Servicios":             "#38bdf8",  # cyan
    "Gastos de caja":        "#f59e0b",  # ámbar
    "Sueldos":               "#a78bfa",  # violeta
    "Mantenimiento":         "#34d399",  # esmeralda
    "Compras / Proveedores": "#fb7185",  # rosa
    "Otros":                 "#94a3b8",  # gris azulado
}

# Color por método de pago (badge en la tabla)
_PAYMENT_COLORS = {
    "Efectivo":      "#22c55e",
    "Tarjeta":       "#3b82f6",
    "Transferencia": "#06b6d4",
    "SINPE":         "#8b5cf6",
    "Crédito":       "#f59e0b",
    "Otro":          "#94a3b8",
}


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


# ======================================================================
# Widgets auxiliares de presentación
# ======================================================================
class _Card(QFrame):
    """Panel con esquinas redondeadas, borde sutil y sombra suave."""

    def __init__(self, parent=None, radius: int = 16, padding=(18, 16, 18, 16)):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(f"""
            QFrame#card {{
                background-color: {COLOR_CARD};
                border: 1px solid {COLOR_BORDER};
                border-radius: {radius}px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setXOffset(0)
        shadow.setYOffset(6)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(shadow)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(*padding)
        self._layout.setSpacing(10)

    def layout(self):
        return self._layout


class _StatCard(QFrame):
    """Tarjeta resumen tipo KPI con icono, etiqueta y valor destacado."""

    def __init__(self, label: str, icon: str, accent: str, parent=None):
        super().__init__(parent)
        self.setObjectName("stat")
        self._accent = accent
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(96)
        self.setStyleSheet(f"""
            QFrame#stat {{
                background-color: {COLOR_CARD};
                border: 1px solid {COLOR_BORDER};
                border-radius: 16px;
            }}
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(QColor(0, 0, 0, 110))
        self.setGraphicsEffect(shadow)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(14)

        # Icono dentro de un chip de color
        self.icon_chip = QLabel(icon)
        self.icon_chip.setFixedSize(46, 46)
        self.icon_chip.setAlignment(Qt.AlignCenter)
        self.icon_chip.setStyleSheet(f"""
            QLabel {{
                background-color: {_hex_to_rgba(accent, 0.16)};
                border-radius: 12px;
                font-size: 20px;
            }}
        """)
        root.addWidget(self.icon_chip, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.lbl_label = QLabel(label)
        self.lbl_label.setStyleSheet(
            f"color: {COLOR_TEXT_SOFT}; font-size: 12px; font-weight: 600; "
            "letter-spacing: 0.3px;"
        )
        self.lbl_value = QLabel("—")
        self.lbl_value.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 22px; font-weight: 800;"
        )
        col.addWidget(self.lbl_label)
        col.addWidget(self.lbl_value)
        col.addStretch()
        root.addLayout(col, 1)

    def set_value(self, value: str):
        self.lbl_value.setText(value)
        # El valor del total se tiñe con el acento para resaltar
        self.lbl_value.setStyleSheet(
            f"color: {self._accent}; font-size: 22px; font-weight: 800;"
        )

    def set_value_neutral(self, value: str):
        self.lbl_value.setText(value)
        self.lbl_value.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 22px; font-weight: 800;"
        )


class _Badge(QLabel):
    """Etiqueta tipo 'pill' coloreada para categoría / método de pago."""

    def __init__(self, text: str, color: str, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"""
            QLabel {{
                color: {color};
                background-color: {_hex_to_rgba(color, 0.14)};
                border: 1px solid {_hex_to_rgba(color, 0.35)};
                border-radius: 9px;
                padding: 3px 10px;
                font-size: 12px;
                font-weight: 700;
            }}
        """)


# ======================================================================
# Hojas de estilo reutilizables
# ======================================================================
def _input_style() -> str:
    return f"""
        QLineEdit, QDateEdit, QComboBox {{
            background-color: {COLOR_INPUT};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER_SOFT};
            border-radius: 10px;
            padding: 7px 12px;
            font-size: 13px;
            selection-background-color: {COLOR_INDIGO};
        }}
        QLineEdit:focus, QDateEdit:focus, QComboBox:focus {{
            border: 1px solid {COLOR_INDIGO_Hi};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {COLOR_CARD_DARK};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER_SOFT};
            border-radius: 8px;
            selection-background-color: {COLOR_INDIGO};
            selection-color: white;
            outline: 0;
            padding: 4px;
        }}
        QDateEdit::drop-down {{
            border: none;
            background-color: {COLOR_INDIGO};
            border-top-right-radius: 9px;
            border-bottom-right-radius: 9px;
            width: 22px;
        }}
    """


def _button_style(bg: str, hover: str, fg: str = "white") -> str:
    return f"""
        QPushButton {{
            background-color: {bg};
            color: {fg};
            border: none;
            border-radius: 10px;
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 700;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:pressed {{ padding-top: 9px; }}
        QPushButton:disabled {{
            background-color: {COLOR_CARD_DARK};
            color: {COLOR_TEXT_MUTED};
        }}
    """


def _ghost_button_style(accent: str) -> str:
    """Botón fantasma (borde + texto coloreado, fondo translúcido)."""
    return f"""
        QPushButton {{
            background-color: transparent;
            color: {accent};
            border: 1px solid {_hex_to_rgba(accent, 0.45)};
            border-radius: 10px;
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 700;
        }}
        QPushButton:hover {{ background-color: {_hex_to_rgba(accent, 0.12)}; }}
        QPushButton:pressed {{ background-color: {_hex_to_rgba(accent, 0.2)}; }}
        QPushButton:disabled {{
            color: {COLOR_TEXT_MUTED};
            border: 1px solid {COLOR_BORDER};
        }}
    """


# ======================================================================
# Vista principal
# ======================================================================
class ExpensesView(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gastos Operativos")
        self.resize(1100, 720)

        self.current_page = 0
        self.page_size = PAGE_SIZE
        self.total_count = 0
        self.expenses = []          # página actual tal cual viene del backend
        self._visible = []          # filas visibles tras búsqueda local
        self.total_backend = 0

        self.setStyleSheet(f"QWidget {{ background-color: {COLOR_BG}; color: {COLOR_TEXT}; }}")

        self.setup_ui()
        self.load_expenses()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {session.token}"} if session.token else {}

    # ------------------------------------------------------------------
    # Construcción de la interfaz
    # ------------------------------------------------------------------
    def setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(16)

        outer.addLayout(self._build_header())
        outer.addLayout(self._build_stats_row())
        outer.addWidget(self._build_toolbar_card())
        outer.addWidget(self._build_table_card(), 1)
        outer.addWidget(self._build_form_card())

        # estado inicial de paginación
        self.update_pagination_controls()

    # ---- Encabezado -------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Gastos Operativos")
        title.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 24px; font-weight: 800; letter-spacing: 0.2px;"
        )
        subtitle = QLabel("Controla y registra los egresos de tu negocio")
        subtitle.setStyleSheet(f"color: {COLOR_TEXT_SOFT}; font-size: 13px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        row.addLayout(title_col)

        row.addStretch()

        self.btn_excel = QPushButton("📊  Exportar Excel")
        self.btn_excel.setStyleSheet(_ghost_button_style(COLOR_GREEN))
        self.btn_excel.setCursor(Qt.PointingHandCursor)
        self.btn_excel.clicked.connect(self.export_excel)

        self.btn_pdf = QPushButton("📄  Exportar PDF")
        self.btn_pdf.setStyleSheet(_ghost_button_style(COLOR_RED_Hi))
        self.btn_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_pdf.clicked.connect(self.export_pdf)

        row.addWidget(self.btn_excel)
        row.addWidget(self.btn_pdf)
        return row

    # ---- Fila de tarjetas resumen (KPIs) ----------------------------
    def _build_stats_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        self.stat_total = _StatCard("TOTAL DE GASTOS", "💸", COLOR_RED_Hi)
        self.stat_count = _StatCard("REGISTROS", "🧾", COLOR_BLUE)
        self.stat_avg = _StatCard("PROMEDIO POR GASTO", "📊", COLOR_AMBER)

        row.addWidget(self.stat_total)
        row.addWidget(self.stat_count)
        row.addWidget(self.stat_avg)
        return row

    # ---- Toolbar de filtros -----------------------------------------
    def _build_toolbar_card(self) -> QWidget:
        card = _Card(padding=(16, 12, 16, 12))
        lay = card.layout()

        row = QHBoxLayout()
        row.setSpacing(12)

        def _field_label(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {COLOR_TEXT_SOFT}; font-size: 12px; font-weight: 600;"
            )
            return lbl

        # Desde / Hasta
        self.dt_from = QDateEdit(calendarPopup=True)
        self.dt_from.setDisplayFormat("dd/MM/yyyy")
        self.dt_from.setDate(QDate.currentDate().addDays(-7))
        self.dt_from.setStyleSheet(_input_style())
        self.dt_from.setFixedWidth(128)
        fix_calendar_colors(self.dt_from)

        self.dt_to = QDateEdit(calendarPopup=True)
        self.dt_to.setDisplayFormat("dd/MM/yyyy")
        self.dt_to.setDate(QDate.currentDate())
        self.dt_to.setStyleSheet(_input_style())
        self.dt_to.setFixedWidth(128)
        fix_calendar_colors(self.dt_to)

        self.cmb_category = QComboBox()
        self.cmb_category.addItems(EXPENSE_CATEGORIES_FILTER)
        self.cmb_category.setStyleSheet(_input_style())
        self.cmb_category.setMinimumWidth(160)
        self.cmb_category.setCursor(Qt.PointingHandCursor)

        # Búsqueda (filtra localmente la página cargada)
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍  Buscar descripción, usuario...")
        self.txt_search.setStyleSheet(_input_style())
        self.txt_search.setMinimumWidth(220)
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self._apply_local_search)

        btn_filter = QPushButton("⚙  Filtrar")
        btn_filter.setStyleSheet(_button_style(COLOR_INDIGO, COLOR_INDIGO_Hi))
        btn_filter.setCursor(Qt.PointingHandCursor)
        btn_filter.clicked.connect(self.filter_from_first_page)

        # composición: grupos etiqueta+campo + búsqueda + botón
        def _group(label_text, widget, stretch=0):
            g = QVBoxLayout()
            g.setSpacing(3)
            g.addWidget(_field_label(label_text))
            g.addWidget(widget)
            return g

        row.addLayout(_group("Desde", self.dt_from))
        row.addLayout(_group("Hasta", self.dt_to))
        row.addLayout(_group("Categoría", self.cmb_category))
        row.addLayout(_group("Buscar", self.txt_search), 1)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(3)
        spacer_lbl = QLabel("")
        spacer_lbl.setStyleSheet("font-size: 12px;")
        btn_col.addWidget(spacer_lbl)  # alinea el botón con los campos
        btn_col.addWidget(btn_filter)
        row.addLayout(btn_col)

        lay.addLayout(row)
        return card

    # ---- Tabla ------------------------------------------------------
    def _build_table_card(self) -> QWidget:
        card = _Card(padding=(8, 8, 8, 8))
        lay = card.layout()
        lay.setSpacing(0)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["#", "Fecha", "Categoría", "Descripción", "Monto ₡", "Pago", "Usuario"]
        )
        # Alinear cabeceras con el contenido de cada columna
        self.table.horizontalHeaderItem(0).setTextAlignment(Qt.AlignCenter)
        self.table.horizontalHeaderItem(4).setTextAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self.table.horizontalHeaderItem(6).setTextAlignment(Qt.AlignCenter)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)

        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: transparent;
                alternate-background-color: {_hex_to_rgba('#ffffff', 0.022)};
                color: {COLOR_TEXT};
                border: none;
                outline: 0;
                font-size: 13px;
            }}
            QTableWidget::item {{
                padding: 10px 8px;
                border: none;
                border-bottom: 1px solid {_hex_to_rgba('#ffffff', 0.05)};
            }}
            QTableWidget::item:selected {{
                background-color: {_hex_to_rgba(COLOR_INDIGO, 0.28)};
                color: {COLOR_TEXT};
            }}
            QHeaderView::section {{
                background-color: transparent;
                color: {COLOR_TEXT_SOFT};
                padding: 10px 8px;
                border: none;
                border-bottom: 2px solid {COLOR_BORDER};
                font-weight: 700;
                font-size: 12px;
            }}
            QHeaderView::section:first {{ padding-left: 14px; }}
            QTableCornerButton::section {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent; width: 10px; margin: 4px 2px 4px 0;
            }}
            QScrollBar::handle:vertical {{
                background: {COLOR_BORDER_SOFT}; border-radius: 5px; min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {COLOR_INDIGO_Hi}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)   # #
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)   # Fecha
        # Categoría y Pago llevan widgets (badges) que ResizeToContents
        # NO mide correctamente, por eso usamos ancho fijo suficiente
        # para la etiqueta más larga ("Compras / Proveedores").
        header.setSectionResizeMode(2, QHeaderView.Fixed)              # Categoría (badge)
        header.setSectionResizeMode(3, QHeaderView.Stretch)            # Descripción
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)   # Monto
        header.setSectionResizeMode(5, QHeaderView.Fixed)              # Pago (badge)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)   # Usuario
        self.table.setColumnWidth(2, 220)   # Categoría
        self.table.setColumnWidth(5, 158)   # Pago
        header.setMinimumSectionSize(64)
        header.setHighlightSections(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(48)

        lay.addWidget(self.table)

        # Estado vacío
        self.lbl_empty = QLabel("Sin gastos para los filtros seleccionados.")
        self.lbl_empty.setAlignment(Qt.AlignCenter)
        self.lbl_empty.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 14px; padding: 30px;"
        )
        self.lbl_empty.setVisible(False)
        lay.addWidget(self.lbl_empty)

        self.table.cellClicked.connect(self.on_row_selected)
        return card

    # ---- Formulario + paginación + acciones -------------------------
    def _build_form_card(self) -> QWidget:
        card = _Card(padding=(18, 16, 18, 16))
        lay = card.layout()
        lay.setSpacing(14)

        # ---- Fila: total a la izquierda + paginación a la derecha ----
        top = QHBoxLayout()
        self.lbl_total = QLabel("Total de gastos:  ₡0.00")
        self.lbl_total.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 15px; font-weight: 800;"
        )
        top.addWidget(self.lbl_total)
        top.addStretch()

        self.btn_prev = QPushButton("◀  Anterior")
        self.btn_prev.setStyleSheet(_ghost_button_style(COLOR_TEXT_SOFT))
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.clicked.connect(self.prev_page)

        self.lbl_page = QLabel("Página 1")
        self.lbl_page.setStyleSheet(
            f"color: {COLOR_TEXT_SOFT}; font-size: 12px; font-weight: 600; margin: 0 6px;"
        )

        self.btn_next = QPushButton("Siguiente  ▶")
        self.btn_next.setStyleSheet(_ghost_button_style(COLOR_TEXT_SOFT))
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self.next_page)

        top.addWidget(self.btn_prev)
        top.addWidget(self.lbl_page)
        top.addWidget(self.btn_next)
        lay.addLayout(top)

        # separador fino
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {COLOR_BORDER}; border: none;")
        lay.addWidget(sep)

        # ---- Fila: formulario de registro ----------------------------
        form_lbl = QLabel("Registrar nuevo gasto")
        form_lbl.setStyleSheet(
            f"color: {COLOR_TEXT_SOFT}; font-size: 12px; font-weight: 700; "
            "letter-spacing: 0.4px;"
        )
        lay.addWidget(form_lbl)

        form = QHBoxLayout()
        form.setSpacing(10)

        self.txt_desc = QLineEdit()
        self.txt_desc.setPlaceholderText("Descripción del gasto...")
        self.txt_desc.setStyleSheet(_input_style())

        self.cmb_new_cat = QComboBox()
        self.cmb_new_cat.addItems(EXPENSE_CATEGORIES)
        self.cmb_new_cat.setStyleSheet(_input_style())
        self.cmb_new_cat.setMinimumWidth(170)
        self.cmb_new_cat.setCursor(Qt.PointingHandCursor)

        self.txt_amount = QLineEdit()
        self.txt_amount.setPlaceholderText("Monto ₡")
        self.txt_amount.setStyleSheet(_input_style())
        self.txt_amount.setFixedWidth(130)
        self.txt_amount.returnPressed.connect(self.add_expense)

        self.cmb_method = QComboBox()
        self.cmb_method.addItems(ALL_PAYMENT_METHODS)
        self.cmb_method.setStyleSheet(_input_style())
        self.cmb_method.setMinimumWidth(150)
        self.cmb_method.setCursor(Qt.PointingHandCursor)

        btn_add = QPushButton("➕  Registrar gasto")
        btn_add.setStyleSheet(_button_style(COLOR_INDIGO, COLOR_INDIGO_Hi))
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setMinimumWidth(170)
        btn_add.clicked.connect(self.add_expense)

        form.addWidget(self.txt_desc, 1)
        form.addWidget(self.cmb_new_cat)
        form.addWidget(self.txt_amount)
        form.addWidget(self.cmb_method)
        form.addWidget(btn_add)
        lay.addLayout(form)

        # ---- Fila: acciones sobre la selección -----------------------
        actions = QHBoxLayout()
        actions.addStretch()
        btn_edit = QPushButton("✏  Editar seleccionado")
        btn_edit.setStyleSheet(_button_style(COLOR_AMBER, "#fbbf24", fg="#1f2933"))
        btn_edit.setCursor(Qt.PointingHandCursor)
        btn_edit.clicked.connect(self.edit_expense)

        btn_delete = QPushButton("🗑  Eliminar seleccionado")
        btn_delete.setStyleSheet(_button_style(COLOR_RED, COLOR_RED_Hi))
        btn_delete.setCursor(Qt.PointingHandCursor)
        btn_delete.clicked.connect(self.delete_expense)

        actions.addWidget(btn_edit)
        actions.addWidget(btn_delete)
        lay.addLayout(actions)

        return card

    # ------------------------------------------------------------------
    # Notificaciones (toast con fallback a QMessageBox)
    # ------------------------------------------------------------------
    def _notify(self, message: str, success: bool = True):
        if show_toast is not None:
            try:
                show_toast(message, success=success, parent=self.window())
                return
            except Exception:
                pass
        if success:
            QMessageBox.information(self, "Éxito", message)
        else:
            QMessageBox.critical(self, "Error", message)

    # ------------------------------------------------------------------
    # Paginación
    # ------------------------------------------------------------------
    def filter_from_first_page(self):
        self.current_page = 0
        self.load_expenses()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.load_expenses()

    def next_page(self):
        max_page = max(0, (self.total_count - 1) // self.page_size)
        if self.current_page < max_page:
            self.current_page += 1
            self.load_expenses()

    def update_pagination_controls(self):
        max_page = max(0, (self.total_count - 1) // self.page_size) if self.total_count > 0 else 0
        self.btn_prev.setEnabled(self.current_page > 0)
        self.btn_next.setEnabled(self.current_page < max_page)
        self.lbl_page.setText(
            f"Página {self.current_page + 1} de {max_page + 1}   ·   {self.total_count} registros"
        )

    def on_row_selected(self, row, column):
        pass

    # ------------------------------------------------------------------
    # FASE 1 — Fix 1.1: Carga asíncrona
    # ------------------------------------------------------------------
    def load_expenses(self):
        selected_category = self.cmb_category.currentText()
        skip = self.current_page * self.page_size
        params = {
            "start_date": self.dt_from.date().toString("yyyy-MM-dd"),
            "end_date": self.dt_to.date().toString("yyyy-MM-dd"),
            "skip": skip,
            "limit": self.page_size,
        }
        if selected_category and selected_category != "Todos":
            params["category"] = selected_category

        api_call(
            "get", API_URL_EXPENSES,
            headers=self._auth_headers(),
            params=params,
            on_success=self._on_expenses_loaded,
            on_error=self._on_expenses_error,
        )

    def _on_expenses_loaded(self, payload):
        if not isinstance(payload, dict):
            return
        if not payload.get("success", True):
            self._on_expenses_error(payload.get("message", "Error al cargar gastos"))
            return

        data = payload.get("data", {})
        self.expenses = data.get("items", [])
        self.total_backend = data.get("total_amount", 0)
        self.total_count = data.get("total_count", 0)

        self.update_table()
        self.update_pagination_controls()

    def _on_expenses_error(self, msg):
        self._notify(f"No se pudieron cargar los gastos:\n{msg}", success=False)
        logger.error(f"Error cargando gastos: {msg}")

    # ------------------------------------------------------------------
    # Búsqueda local sobre la página cargada
    # ------------------------------------------------------------------
    def _apply_local_search(self):
        self.update_table()

    def _filtered_expenses(self):
        term = (self.txt_search.text() or "").strip().lower()
        if not term:
            return list(self.expenses)
        out = []
        for e in self.expenses:
            haystack = " ".join(str(e.get(k, "") or "") for k in
                                ("description", "category", "payment_method", "created_by"))
            if term in haystack.lower():
                out.append(e)
        return out

    # ------------------------------------------------------------------
    # Render de la tabla
    # ------------------------------------------------------------------
    def _make_text_item(self, text, *, align=Qt.AlignVCenter | Qt.AlignLeft,
                        color=None, bold=False):
        item = QTableWidgetItem(text)
        item.setTextAlignment(align)
        if color:
            item.setForeground(QColor(color))
        if bold:
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        return item

    def _set_badge(self, row, col, text, color):
        badge = _Badge(text, color)
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(0)
        h.addWidget(badge)
        h.addStretch()
        wrap.setStyleSheet("background: transparent;")
        self.table.setCellWidget(row, col, wrap)

    def update_table(self):
        self._visible = self._filtered_expenses()
        search_active = bool(self.txt_search.text().strip())

        if not self._visible:
            self.table.setRowCount(0)
            self.lbl_empty.setVisible(True)
            self.table.setVisible(False)
            shown_total = 0.0 if search_active else float(self.total_backend or 0)
            self._update_totals(shown_total, 0 if search_active else self.total_count)
            return

        self.lbl_empty.setVisible(False)
        self.table.setVisible(True)
        self.table.clearContents()
        self.table.setRowCount(len(self._visible))

        page_offset = self.current_page * self.page_size
        page_total = 0.0
        for row, e in enumerate(self._visible):
            seq = page_offset + row + 1
            date_str = self._format_date(str(e.get("date", "") or ""))
            category = e.get("category", "") or ""
            description = e.get("description", "") or "—"
            amount = float(e.get("amount", 0) or 0)
            payment = e.get("payment_method", "") or "—"
            created_by = e.get("created_by", "") or "—"

            # # (índice)
            self.table.setItem(
                row, 0,
                self._make_text_item(str(seq),
                                     align=Qt.AlignVCenter | Qt.AlignHCenter,
                                     color=COLOR_TEXT_MUTED)
            )
            # Fecha
            self.table.setItem(
                row, 1,
                self._make_text_item(date_str, color=COLOR_TEXT_SOFT)
            )
            # Categoría (badge)
            cat_color = _CATEGORY_COLORS.get(category, COLOR_TEXT_SOFT)
            self.table.setItem(row, 2, QTableWidgetItem(""))  # base para selección de fila
            self._set_badge(row, 2, category if category else "—", cat_color)
            # Descripción
            self.table.setItem(
                row, 3,
                self._make_text_item(description, color=COLOR_TEXT)
            )
            # Monto (rojo, negrita, alineado a la derecha)
            self.table.setItem(
                row, 4,
                self._make_text_item(
                    f"₡{amount:,.2f}",
                    align=Qt.AlignVCenter | Qt.AlignRight,
                    color=COLOR_RED_Hi, bold=True
                )
            )
            # Pago (badge)
            pay_color = _PAYMENT_COLORS.get(payment, COLOR_TEXT_SOFT)
            self.table.setItem(row, 5, QTableWidgetItem(""))
            self._set_badge(row, 5, payment if payment else "—", pay_color)
            # Usuario
            self.table.setItem(
                row, 6,
                self._make_text_item(created_by,
                                     align=Qt.AlignVCenter | Qt.AlignHCenter,
                                     color=COLOR_TEXT_SOFT)
            )
            page_total += amount

        # Sin búsqueda: total global del periodo (backend, suma de todas las
        # páginas). Con búsqueda: suma de lo visible.
        if search_active:
            self._update_totals(page_total, len(self._visible))
        else:
            self._update_totals(float(self.total_backend or 0), self.total_count)

        self.table.viewport().update()

    def _update_totals(self, total_amount: float, count: int):
        self.lbl_total.setText(f"Total de gastos:  ₡{total_amount:,.2f}")
        self.stat_total.set_value(f"₡{total_amount:,.2f}")
        self.stat_count.set_value_neutral(f"{count:,}")
        avg = (total_amount / count) if count else 0.0
        self.stat_avg.set_value_neutral(f"₡{avg:,.2f}")

    @staticmethod
    def _format_date(raw: str) -> str:
        """Convierte 'YYYY-MM-DD' (o ISO) a 'DD/MM/YYYY'. Tolerante a fallos."""
        if not raw:
            return "—"
        s = raw.split("T")[0].split(" ")[0]
        parts = s.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            y, m, d = parts
            return f"{d}/{m}/{y}"
        return raw

    # ------------------------------------------------------------------
    # FASE 1 — Fix 1.2: Acciones con timeout
    # ------------------------------------------------------------------
    def add_expense(self):
        try:
            desc = self.txt_desc.text().strip()
            amount_text = self.txt_amount.text().strip().replace(",", "")
            if not desc:
                self._notify("Ingrese una descripción.", success=False); return
            if not amount_text:
                self._notify("Ingrese un monto.", success=False); return
            try:
                amount = float(amount_text)
                if amount <= 0:
                    raise ValueError("El monto debe ser mayor a 0")
            except ValueError as e:
                self._notify(f"Monto inválido: {e}", success=False); return

            data = {
                "description": desc,
                "category": self.cmb_new_cat.currentText(),
                "amount": amount,
                "payment_method": self.cmb_method.currentText(),
            }
            res = api_request("post", API_URL_EXPENSES, json=data, headers=self._auth_headers())
            if res.status_code != 200:
                raise Exception(f"Error del servidor: {res.text}")
            response_data = res.json()
            if not response_data.get("success", True):
                raise Exception(response_data.get("message", "Error desconocido"))

            self.txt_desc.clear()
            self.txt_amount.clear()
            self.txt_desc.setFocus()
            self.load_expenses()
            self._notify(f"Gasto de ₡{amount:,.2f} registrado correctamente.")
        except Exception as e:
            self._notify(f"No se pudo registrar el gasto:\n{e}", success=False)

    def edit_expense(self):
        row = self.table.currentRow()
        if row < 0:
            self._notify("Seleccione un gasto para editar.", success=False); return

        # 'row' indexa la lista visible (tras búsqueda)
        source = self._visible if self._visible else self.expenses
        if row >= len(source):
            self._notify("Selección inválida.", success=False); return
        expense = source[row]

        dlg = EditExpenseDialog(expense, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updates = dlg.get_updates()
            if not updates:
                return
            try:
                res = api_request(
                    "put", f"{API_URL_EXPENSES}/{expense['id']}",
                    json=updates, headers=self._auth_headers(),
                )
                if res.status_code != 200:
                    raise Exception(res.text)
                response_data = res.json()
                if not response_data.get("success", True):
                    raise Exception(response_data.get("message", "Error desconocido"))
                self._notify("Gasto actualizado correctamente.")
                self.load_expenses()
            except Exception as e:
                self._notify(f"No se pudo actualizar el gasto:\n{e}", success=False)

    def delete_expense(self):
        row = self.table.currentRow()
        if row < 0:
            self._notify("Seleccione un gasto para eliminar.", success=False); return

        source = self._visible if self._visible else self.expenses
        if row >= len(source):
            self._notify("Selección inválida.", success=False); return
        expense_id = source[row]["id"]

        confirm = QMessageBox.question(
            self, "Confirmar eliminación",
            "¿Está seguro de eliminar el gasto seleccionado?\nEsta acción no se puede deshacer.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            res = api_request("delete", f"{API_URL_EXPENSES}/{expense_id}", headers=self._auth_headers())
            if res.status_code != 200:
                raise Exception(res.text)
            self._notify("Gasto eliminado correctamente.")
            self.load_expenses()
        except Exception as e:
            self._notify(f"No se pudo eliminar el gasto:\n{e}", success=False)

    # ------------------------------------------------------------------
    # Exportar (sin cambios funcionales — no hacen HTTP)
    # ------------------------------------------------------------------
    def _collect_export_rows(self):
        """Toma las filas visibles actuales y las normaliza para exportar."""
        rows = []
        source = self._visible if self._visible else self.expenses
        for e in source:
            rows.append({
                "date": self._format_date(str(e.get("date", "") or "")),
                "category": e.get("category", "") or "",
                "description": e.get("description", "") or "",
                "amount": float(e.get("amount", 0) or 0),
                "payment_method": e.get("payment_method", "") or "",
            })
        return rows

    def export_excel(self):
        try:
            data = self._collect_export_rows()
            if not data:
                self._notify("No hay gastos para exportar.", success=False); return
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Guardar reporte Excel", "reporte_gastos.xlsx",
                "Archivos Excel (*.xlsx)"
            )
            if not filepath:
                return
            from app.utils.export_utils import export_expenses_excel
            filename = export_expenses_excel(data, filename=filepath)
            self._notify(f"Archivo Excel generado:\n{filename}")
        except Exception as e:
            self._notify(f"No se pudo exportar el Excel:\n{e}", success=False)

    def export_pdf(self):
        try:
            data = self._collect_export_rows()
            if not data:
                self._notify("No hay gastos para exportar.", success=False); return
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Guardar reporte PDF", "reporte_gastos.pdf",
                "Archivos PDF (*.pdf)"
            )
            if not filepath:
                return
            total = sum(r["amount"] for r in data)
            start_date = self.dt_from.date().toString("yyyy-MM-dd")
            end_date = self.dt_to.date().toString("yyyy-MM-dd")
            filename = export_expenses_pdf(data, start_date, end_date, total, filename=filepath)
            self._notify(f"Reporte PDF generado:\n{filename}")
        except Exception as e:
            self._notify(f"No se pudo exportar el PDF:\n{e}", success=False)


# ======================================================================
# Diálogo de edición de gasto — rediseñado (sin cambios de lógica)
# ======================================================================
class EditExpenseDialog(QDialog):
    def __init__(self, expense: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar Gasto")
        self.setMinimumWidth(440)
        self.expense = expense

        self.setStyleSheet(f"""
            QDialog {{ background-color: {COLOR_BG}; }}
            QLabel {{ color: {COLOR_TEXT_SOFT}; font-size: 13px; font-weight: 600; }}
            {_input_style()}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        header = QLabel("✏  Editar gasto")
        header.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 18px; font-weight: 800;"
        )
        root.addWidget(header)

        card = _Card(padding=(18, 16, 18, 16))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setSpacing(12)
        form.setContentsMargins(0, 0, 0, 0)

        self.txt_desc = QLineEdit(expense.get("description", "") or "")
        form.addRow("Descripción", self.txt_desc)

        self.cmb_cat = QComboBox()
        self.cmb_cat.addItems(EXPENSE_CATEGORIES)
        idx = self.cmb_cat.findText(expense.get("category", "") or "")
        if idx >= 0:
            self.cmb_cat.setCurrentIndex(idx)
        form.addRow("Categoría", self.cmb_cat)

        self.txt_amount = QLineEdit(str(expense.get("amount", "") or ""))
        form.addRow("Monto (₡)", self.txt_amount)

        self.cmb_method = QComboBox()
        self.cmb_method.addItems(ALL_PAYMENT_METHODS)
        idx_pm = self.cmb_method.findText(expense.get("payment_method", "") or "")
        if idx_pm >= 0:
            self.cmb_method.setCurrentIndex(idx_pm)
        form.addRow("Método de pago", self.cmb_method)

        card.layout().addLayout(form)
        root.addWidget(card)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ok_btn.setText("Guardar cambios")
        cancel_btn.setText("Cancelar")
        ok_btn.setStyleSheet(_button_style(COLOR_INDIGO, COLOR_INDIGO_Hi))
        ok_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(_ghost_button_style(COLOR_TEXT_SOFT))
        cancel_btn.setCursor(Qt.PointingHandCursor)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def get_updates(self) -> dict:
        updates = {}
        new_desc = self.txt_desc.text().strip()
        if new_desc != (self.expense.get("description") or ""):
            updates["description"] = new_desc
        new_cat = self.cmb_cat.currentText()
        if new_cat != self.expense.get("category", ""):
            updates["category"] = new_cat
        try:
            new_amount = float(self.txt_amount.text().strip().replace(",", ""))
            if new_amount != self.expense.get("amount"):
                updates["amount"] = new_amount
        except ValueError:
            pass
        new_pm = self.cmb_method.currentText()
        if new_pm != self.expense.get("payment_method", ""):
            updates["payment_method"] = new_pm
        return updates