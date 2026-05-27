# ui/views/sales_history_view.py
"""
Vista de Registro de Ventas — rediseñada.

Cambios respecto a la versión anterior:
  - Tema oscuro consistente con el resto de la app (Dashboard).
  - Columna "Estado Hacienda" con badges de color.
  - Columna "Pago" con icono.
  - Panel de detalle con banner de estado, cédula del cliente,
    desglose de Subtotal/IVA/Total y botonera de acciones.
  - Botón "🔄 Consultar Hacienda" cableado a
    `POST /einvoices/{einvoice_id}/check-status`.
  - Botón "Anular / Nota de Crédito" cableado a
    `POST /sales/{id}/cancel` (genera NC si la FE fue aceptada) o
    `DELETE /sales/{id}` (anulación simple para no-aceptadas).

Métodos públicos preservados (los usa main_ui.py):
  - load_sales()
  - apply_date_range(start_date, end_date)
  - apply_period_filter(period, start_iso=None, end_iso=None)
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QDateEdit, QMessageBox,
    QFrame, QHeaderView, QAbstractItemView, QSizePolicy, QGridLayout,
)
from PySide6.QtCore import Qt, QDate, QSize
from PySide6.QtGui import QColor, QBrush
import os
import logging

from ui.api import BASE_URL
from ui.session_manager import session
from ui.utils.calendar_fix import fix_calendar_colors
from ui.utils.http_worker import api_call, api_request
from ui.components.toast_notifier import show_toast
from app.core.config import get_pdf_dir

API_URL = BASE_URL
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Paleta de colores (mismo lenguaje que dashboard_view.py)
# ═══════════════════════════════════════════════════════════
COLOR_BG = "#111827"
COLOR_CARD = "#1f2933"
COLOR_CARD_SOFT = "#273340"
COLOR_BORDER = "#374151"
COLOR_TEXT = "#e5e7eb"
COLOR_TEXT_SOFT = "#9ca3af"
COLOR_TEXT_MUTE = "#6b7280"
COLOR_ACCENT = "#2563eb"

COLOR_GREEN = "#22c55e"
COLOR_YELLOW = "#f59e0b"
COLOR_RED = "#ef4444"
COLOR_GRAY = "#6b7280"
COLOR_INDIGO = "#6366f1"


# ═══════════════════════════════════════════════════════════
# Helpers de presentación
# ═══════════════════════════════════════════════════════════
def _money(amount) -> str:
    try:
        return f"₡{float(amount):,.2f}"
    except (TypeError, ValueError):
        return "₡0.00"


def _classify_hacienda_status(sale_status: str, hacienda_status, einvoice_id) -> tuple:
    """
    Devuelve (label, icon, color_fg, color_bg) según el estado.

    Prioridad:
      1. Si la venta está ANULADA → 'ANULADA' (rojo oscuro)
      2. hacienda_status = ACEPTADO → verde
      3. hacienda_status = RECHAZADO → rojo
      4. Hay einvoice pero sin respuesta final → PENDIENTE (amarillo)
      5. No hay einvoice asociada → SIN ENVIAR (gris)
    """
    if (sale_status or "").upper() == "ANULADA":
        return ("ANULADA", "🛑", "#fca5a5", "rgba(239, 68, 68, 0.18)")

    hs = (hacienda_status or "").upper().strip()

    if hs == "ACEPTADO":
        return ("ACEPTADO", "✅", "#86efac", "rgba(34, 197, 94, 0.18)")

    if hs == "RECHAZADO":
        return ("RECHAZADO", "❌", "#fca5a5", "rgba(239, 68, 68, 0.18)")

    if hs in ("PROCESANDO", "RECIBIDO"):
        return (hs, "⏳", "#fcd34d", "rgba(245, 158, 11, 0.18)")

    if einvoice_id:
        # Hay registro electrónico pero todavía no llegó respuesta de Hacienda
        return ("PENDIENTE", "⏳", "#fcd34d", "rgba(245, 158, 11, 0.18)")

    # Sin facturación electrónica asociada
    return ("SIN ENVIAR", "—", "#cbd5e1", "rgba(107, 114, 128, 0.20)")


def _payment_icon(method: str) -> str:
    m = (method or "").lower()
    if "efectiv" in m:
        return "💵"
    if "tarjet" in m or "card" in m:
        return "💳"
    if "sinpe" in m:
        return "📱"
    if "credit" in m or "crédit" in m:
        return "🏷️"
    return "💰"


def _payment_label(method: str) -> str:
    if not method:
        return "—"
    return method.strip().capitalize()


# ═══════════════════════════════════════════════════════════
# Widget: Badge de estado (usado en celdas y banner)
# ═══════════════════════════════════════════════════════════
class StatusBadge(QLabel):
    """Etiqueta con esquinas redondeadas y color según estado."""

    def __init__(self, label: str, icon: str, fg: str, bg: str,
                 *, big: bool = False, parent=None):
        text = f" {icon}  {label} " if icon else f" {label} "
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)

        font_size = 15 if big else 12
        padding = "10px 18px" if big else "4px 12px"

        self.setStyleSheet(f"""
            QLabel {{
                color: {fg};
                background-color: {bg};
                border-radius: 14px;
                padding: {padding};
                font-size: {font_size}px;
                font-weight: 700;
                letter-spacing: 0.3px;
            }}
        """)


# ═══════════════════════════════════════════════════════════
# Helper para crear celdas (centrado vertical + padding visual)
# ═══════════════════════════════════════════════════════════
def _cell_label(text: str, *, align=Qt.AlignVCenter | Qt.AlignLeft,
                color: str = COLOR_TEXT, weight: int = 400,
                size: int = 13) -> QWidget:
    """Devuelve un widget contenedor con un QLabel dentro (para padding)."""
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    h = QHBoxLayout(wrap)
    h.setContentsMargins(12, 4, 12, 4)
    lbl = QLabel(text)
    lbl.setAlignment(align)
    lbl.setStyleSheet(f"""
        color: {color};
        font-size: {size}px;
        font-weight: {weight};
        background: transparent;
    """)
    h.addWidget(lbl)
    h.addStretch()
    return wrap


def _cell_money(text: str) -> QWidget:
    """Celda de dinero alineada a la derecha."""
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    h = QHBoxLayout(wrap)
    h.setContentsMargins(12, 4, 16, 4)
    h.addStretch()
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
    lbl.setStyleSheet(f"""
        color: {COLOR_TEXT};
        font-size: 13px;
        font-weight: 600;
        background: transparent;
    """)
    h.addWidget(lbl)
    return wrap


def _cell_payment(method: str) -> QWidget:
    """Celda de método de pago: icono + texto."""
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    h = QHBoxLayout(wrap)
    h.setContentsMargins(12, 4, 12, 4)

    icon = QLabel(_payment_icon(method))
    icon.setStyleSheet("font-size: 16px; background: transparent;")
    h.addWidget(icon)

    lbl = QLabel(_payment_label(method))
    lbl.setStyleSheet(f"""
        color: {COLOR_TEXT};
        font-size: 13px;
        font-weight: 500;
        background: transparent;
        padding-left: 4px;
    """)
    h.addWidget(lbl)
    h.addStretch()
    return wrap


def _cell_status_badge(sale_status, hacienda_status, einvoice_id) -> QWidget:
    """Celda con el badge de estado de Hacienda."""
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    h = QHBoxLayout(wrap)
    h.setContentsMargins(10, 4, 10, 4)

    label, icon, fg, bg = _classify_hacienda_status(
        sale_status, hacienda_status, einvoice_id
    )
    badge = StatusBadge(label, icon, fg, bg)
    h.addWidget(badge)
    h.addStretch()
    return wrap


# ═══════════════════════════════════════════════════════════
# Botón de acción con estilo
# ═══════════════════════════════════════════════════════════
def _action_button(text: str, color_bg: str, color_fg: str = "white",
                   *, icon: str = "", min_h: int = 56) -> QPushButton:
    """Botón con estilo de acción para el panel de detalle."""
    btn = QPushButton(f"{icon}  {text}" if icon else text)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(min_h)
    # Calcular colores hover/pressed (versiones ligeramente más claras/oscuras)
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {color_bg};
            color: {color_fg};
            border: none;
            border-radius: 12px;
            font-size: 13px;
            font-weight: 600;
            padding: 8px 14px;
        }}
        QPushButton:hover {{
            background-color: {color_bg};
            border: 2px solid rgba(255, 255, 255, 0.25);
            padding: 6px 12px;
        }}
        QPushButton:pressed {{
            background-color: {color_bg};
            border: 2px solid rgba(255, 255, 255, 0.4);
            padding: 6px 12px;
        }}
        QPushButton:disabled {{
            background-color: #374151;
            color: #6b7280;
        }}
    """)
    return btn


# ═══════════════════════════════════════════════════════════
# Vista principal
# ═══════════════════════════════════════════════════════════
class SalesHistoryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle("Registro de Ventas")
        self.resize(1280, 720)

        # Cache de la última respuesta — necesario para export (las celdas
        # ahora son widgets, no QTableWidgetItem con texto plano).
        self._sales_data: list = []
        self._current_detail: dict | None = None

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLOR_BG};
                color: {COLOR_TEXT};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
        """)

        self.setup_ui()
        self.load_sales()

    # ----------------------------------------------------------------------
    def _auth_headers(self):
        return {"Authorization": f"Bearer {session.token}"}

    # ══════════════════════════════════════════════════════════════════════
    # UI
    # ══════════════════════════════════════════════════════════════════════
    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # ───────────── Header ─────────────
        title = QLabel("🧾  Registro de Ventas")
        title.setStyleSheet(f"""
            color: {COLOR_TEXT};
            font-size: 22px;
            font-weight: 700;
            background: transparent;
            padding-bottom: 2px;
        """)
        root.addWidget(title)

        # ───────────── Card de filtros ─────────────
        root.addWidget(self._build_filters_card())

        # ───────────── Panel principal: tabla + detalle ─────────────
        body = QHBoxLayout()
        body.setSpacing(14)

        body.addWidget(self._build_sales_card(), 6)
        body.addWidget(self._build_detail_card(), 5)

        root.addLayout(body, 1)

    # ──────────────────────────────────────────────────────────────────────
    def _build_filters_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("FiltersCard")
        card.setStyleSheet(f"""
            QFrame#FiltersCard {{
                background-color: {COLOR_CARD};
                border-radius: 14px;
            }}
            QLabel {{
                color: {COLOR_TEXT_SOFT};
                font-size: 12px;
                font-weight: 600;
                background: transparent;
            }}
            QDateEdit, QComboBox, QLineEdit {{
                background-color: {COLOR_BG};
                color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 13px;
                min-height: 28px;
            }}
            QDateEdit:focus, QComboBox:focus, QLineEdit:focus {{
                border: 1px solid {COLOR_ACCENT};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {COLOR_CARD};
                color: {COLOR_TEXT};
                selection-background-color: {COLOR_ACCENT};
                selection-color: white;
                border: 1px solid {COLOR_BORDER};
            }}
        """)

        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # Fecha desde
        self.dt_from = QDateEdit(calendarPopup=True)
        self.dt_from.setDate(QDate.currentDate().addDays(-7))
        self.dt_from.setDisplayFormat("d/M/yyyy")
        fix_calendar_colors(self.dt_from)

        # Fecha hasta
        self.dt_to = QDateEdit(calendarPopup=True)
        self.dt_to.setDate(QDate.currentDate())
        self.dt_to.setDisplayFormat("d/M/yyyy")
        fix_calendar_colors(self.dt_to)

        # Pago
        self.cmb_payment = QComboBox()
        self.cmb_payment.addItems(["Todos", "Efectivo", "Tarjeta", "SINPE", "Crédito"])

        # Estado (combinado: hacienda_status + sale.status)
        self.cmb_status = QComboBox()
        self.cmb_status.addItems(["Todos", "Aceptado", "Pendiente", "Rechazado", "Anulada"])

        # Búsqueda
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Buscar #venta o cliente…")
        self.txt_search.setMinimumWidth(190)
        self.txt_search.returnPressed.connect(self.load_sales)

        # Botones
        btn_apply = _action_button("Filtrar", COLOR_ACCENT, icon="🔎", min_h=36)
        btn_apply.setMinimumWidth(120)
        btn_apply.clicked.connect(self.load_sales)

        btn_pdf = _action_button("Exportar PDF", "#3b82f6", icon="📄", min_h=36)
        btn_pdf.setMinimumWidth(160)
        btn_pdf.clicked.connect(self.export_pdf)

        btn_excel = _action_button("Exportar Excel", "#10b981", icon="📊", min_h=36)
        btn_excel.setMinimumWidth(170)
        btn_excel.clicked.connect(self.export_excel)

        for lbl_txt, w in [
            ("Desde:", self.dt_from),
            ("Hasta:", self.dt_to),
            ("Pago:", self.cmb_payment),
            ("Estado:", self.cmb_status),
        ]:
            block = QVBoxLayout()
            block.setSpacing(2)
            lab = QLabel(lbl_txt)
            block.addWidget(lab)
            block.addWidget(w)
            container = QWidget()
            container.setLayout(block)
            container.setStyleSheet("background: transparent;")
            lay.addWidget(container)

        # Búsqueda (sin label arriba para ahorrar espacio)
        search_block = QVBoxLayout()
        search_block.setSpacing(2)
        search_block.addWidget(QLabel(" "))  # spacer label
        search_block.addWidget(self.txt_search)
        search_container = QWidget()
        search_container.setLayout(search_block)
        search_container.setStyleSheet("background: transparent;")
        lay.addWidget(search_container, 1)

        # Botones alineados con los inputs
        for b in (btn_apply, btn_pdf, btn_excel):
            btn_block = QVBoxLayout()
            btn_block.setSpacing(2)
            btn_block.addWidget(QLabel(" "))
            btn_block.addWidget(b)
            cont = QWidget()
            cont.setLayout(btn_block)
            cont.setStyleSheet("background: transparent;")
            lay.addWidget(cont)

        return card

    # ──────────────────────────────────────────────────────────────────────
    def _build_sales_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("SalesCard")
        card.setStyleSheet(f"""
            QFrame#SalesCard {{
                background-color: {COLOR_CARD};
                border-radius: 14px;
            }}
        """)
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Tabla principal
        self.tbl = QTableWidget()
        self.tbl.setColumnCount(6)
        self.tbl.setHorizontalHeaderLabels(
            ["# Venta", "Fecha", "Cliente", "Estado Hacienda", "Pago", "Total"]
        )

        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setShowGrid(False)
        self.tbl.setAlternatingRowColors(False)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.verticalHeader().setDefaultSectionSize(52)
        self.tbl.horizontalHeader().setHighlightSections(False)
        self.tbl.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tbl.horizontalHeader().setStretchLastSection(False)

        # Anchos de columna
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # # Venta
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Fecha
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)           # Cliente
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Estado
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Pago
        hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Total
        self.tbl.setColumnWidth(0, 92)
        self.tbl.setColumnWidth(1, 110)

        self.tbl.cellClicked.connect(self.on_row_clicked)

        self.tbl.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLOR_CARD};
                color: {COLOR_TEXT};
                border: none;
                border-radius: 14px;
                gridline-color: transparent;
                outline: 0;
            }}
            QHeaderView::section {{
                background-color: {COLOR_CARD};
                color: {COLOR_TEXT_SOFT};
                border: none;
                border-bottom: 1px solid {COLOR_BORDER};
                padding: 14px 12px;
                font-size: 12px;
                font-weight: 700;
                text-transform: none;
            }}
            QTableWidget::item {{
                border-bottom: 1px solid rgba(55, 65, 81, 0.4);
                padding: 0px;
            }}
            QTableWidget::item:selected {{
                background-color: rgba(37, 99, 235, 0.18);
                color: {COLOR_TEXT};
            }}
            QScrollBar:vertical {{
                background: {COLOR_CARD};
                width: 10px;
                margin: 4px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLOR_BORDER};
                border-radius: 5px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {COLOR_TEXT_MUTE};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        v.addWidget(self.tbl)

        # Footer pequeño con conteo
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet(f"""
            color: {COLOR_TEXT_MUTE};
            font-size: 11px;
            padding: 8px 16px;
            background: transparent;
        """)
        v.addWidget(self.lbl_count)

        return card

    # ──────────────────────────────────────────────────────────────────────
    def _build_detail_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("DetailCard")
        card.setStyleSheet(f"""
            QFrame#DetailCard {{
                background-color: {COLOR_CARD};
                border-radius: 14px;
            }}
        """)

        v = QVBoxLayout(card)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)

        # ── Encabezado del detalle ──
        self.lbl_header = QLabel("Detalle de Venta")
        self.lbl_header.setStyleSheet(f"""
            color: {COLOR_TEXT};
            font-size: 17px;
            font-weight: 700;
            background: transparent;
        """)
        v.addWidget(self.lbl_header)

        self.lbl_subheader = QLabel("Seleccione una factura de la lista")
        self.lbl_subheader.setStyleSheet(f"""
            color: {COLOR_TEXT_SOFT};
            font-size: 12px;
            background: transparent;
        """)
        v.addWidget(self.lbl_subheader)

        # ── Banner de estado (oculto hasta que haya selección) ──
        self.status_banner_wrap = QHBoxLayout()
        self.status_banner_wrap.setContentsMargins(0, 4, 0, 4)
        self._status_banner_widget: QWidget | None = None
        banner_container = QWidget()
        banner_container.setLayout(self.status_banner_wrap)
        banner_container.setStyleSheet("background: transparent;")
        v.addWidget(banner_container)

        # ── Datos del cliente ──
        self.lbl_customer = QLabel("")
        self.lbl_customer.setStyleSheet(f"""
            color: {COLOR_TEXT};
            font-size: 14px;
            font-weight: 600;
            background: transparent;
        """)
        v.addWidget(self.lbl_customer)

        self.lbl_customer_id = QLabel("")
        self.lbl_customer_id.setStyleSheet(f"""
            color: {COLOR_TEXT_SOFT};
            font-size: 12px;
            background: transparent;
        """)
        v.addWidget(self.lbl_customer_id)

        # ── Tabla de items ──
        self.tbl_items = QTableWidget()
        self.tbl_items.setColumnCount(4)
        self.tbl_items.setHorizontalHeaderLabels(
            ["Producto", "Cantidad", "Precio", "Subtotal"]
        )
        self.tbl_items.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_items.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl_items.setShowGrid(False)
        self.tbl_items.verticalHeader().setVisible(False)
        self.tbl_items.verticalHeader().setDefaultSectionSize(36)
        self.tbl_items.horizontalHeader().setHighlightSections(False)
        self.tbl_items.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tbl_items.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_items.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl_items.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_items.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)

        self.tbl_items.setStyleSheet(f"""
            QTableWidget {{
                background-color: transparent;
                color: {COLOR_TEXT};
                border: none;
                outline: 0;
            }}
            QHeaderView::section {{
                background-color: transparent;
                color: {COLOR_TEXT_SOFT};
                border: none;
                border-bottom: 1px solid {COLOR_BORDER};
                padding: 8px 6px;
                font-size: 11px;
                font-weight: 700;
            }}
            QTableWidget::item {{
                padding: 6px;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 2px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLOR_BORDER};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)
        # Garantizar que la tabla de items tenga espacio mínimo para varios
        # productos. Sin esto, en layouts apretados se reduce a 1-2 filas.
        self.tbl_items.setMinimumHeight(180)
        v.addWidget(self.tbl_items, 1)

        # ── Totales ──
        totals_frame = QFrame()
        totals_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLOR_CARD_SOFT};
                border-radius: 10px;
            }}
            QLabel {{ background: transparent; }}
        """)
        tg = QGridLayout(totals_frame)
        tg.setContentsMargins(14, 12, 14, 12)
        tg.setHorizontalSpacing(20)
        tg.setVerticalSpacing(6)

        def _tlbl(text, color=COLOR_TEXT_SOFT, size=12, weight=500, align=Qt.AlignLeft):
            l = QLabel(text)
            l.setAlignment(align | Qt.AlignVCenter)
            l.setStyleSheet(f"color: {color}; font-size: {size}px; font-weight: {weight};")
            return l

        # Subtotal
        tg.addWidget(_tlbl("Subtotal"), 0, 0)
        self.lbl_sub = _tlbl("₡0.00", color=COLOR_TEXT, weight=600, align=Qt.AlignRight)
        tg.addWidget(self.lbl_sub, 0, 1)

        # IVA / Impuestos
        tg.addWidget(_tlbl("IVA / Impuestos"), 1, 0)
        self.lbl_tax = _tlbl("₡0.00", color=COLOR_TEXT, weight=600, align=Qt.AlignRight)
        tg.addWidget(self.lbl_tax, 1, 1)

        # Total
        self.lbl_total_label = _tlbl(
            "Total a Pagar", color=COLOR_TEXT, size=14, weight=700,
        )
        tg.addWidget(self.lbl_total_label, 2, 0)
        self.lbl_total = _tlbl(
            "₡0.00", color="#86efac", size=18, weight=800, align=Qt.AlignRight,
        )
        tg.addWidget(self.lbl_total, 2, 1)

        v.addWidget(totals_frame)

        # ── Botones de acción ──
        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)

        self.btn_return = _action_button("Devolución", "#f59e0b", icon="↩")
        self.btn_return.setToolTip("Próximamente — registrar devolución de mercadería")
        self.btn_return.clicked.connect(self._on_devolucion_clicked)

        self.btn_pdf = _action_button("Ver PDF", "#3b82f6", icon="📄")
        self.btn_pdf.setToolTip("Abrir comprobante PDF")
        self.btn_pdf.clicked.connect(self.open_pdf)

        self.btn_email = _action_button("Enviar Correo", "#0ea5e9", icon="📧")
        self.btn_email.setToolTip("Enviar comprobante al correo del cliente")
        self.btn_email.clicked.connect(self._on_email_clicked)

        self.btn_cancel = _action_button(
            "Anular / Nota\nde Crédito", "#ef4444", icon="✕"
        )
        self.btn_cancel.setToolTip("Anular venta — emite Nota de Crédito si la FE fue aceptada")
        self.btn_cancel.clicked.connect(self._on_anular_clicked)

        self.btn_check = _action_button(
            "Consultar Estado en Hacienda", COLOR_INDIGO, icon="🔄", min_h=46,
        )
        self.btn_check.setToolTip(
            "Consultar directamente a Hacienda el estado actual del comprobante.\n"
            "Útil si la respuesta automática (callback) no ha llegado todavía."
        )
        self.btn_check.clicked.connect(self._on_check_hacienda_clicked)

        actions.addWidget(self.btn_return, 0, 0)
        actions.addWidget(self.btn_pdf,    0, 1)
        actions.addWidget(self.btn_email,  1, 0)
        actions.addWidget(self.btn_cancel, 1, 1)
        actions.addWidget(self.btn_check,  2, 0, 1, 2)

        v.addLayout(actions)

        # Botones deshabilitados hasta que haya selección
        self._set_actions_enabled(False)

        return card

    # ──────────────────────────────────────────────────────────────────────
    def _set_actions_enabled(self, enabled: bool):
        for b in (self.btn_return, self.btn_pdf, self.btn_email,
                  self.btn_cancel, self.btn_check):
            b.setEnabled(enabled)

    def _swap_status_banner(self, new_widget: QWidget | None):
        """Reemplaza el banner de estado del detalle."""
        if self._status_banner_widget is not None:
            self.status_banner_wrap.removeWidget(self._status_banner_widget)
            self._status_banner_widget.deleteLater()
            self._status_banner_widget = None
        if new_widget is not None:
            self.status_banner_wrap.addWidget(new_widget)
            self._status_banner_widget = new_widget

    # ══════════════════════════════════════════════════════════════════════
    # Carga de datos
    # ══════════════════════════════════════════════════════════════════════
    def load_sales(self):
        """Carga el listado de ventas (mismo nombre y semántica que antes)."""
        params = {
            "start_date": self.dt_from.date().toString("yyyy-MM-dd"),
            "end_date": self.dt_to.date().toString("yyyy-MM-dd"),
        }

        pay = self.cmb_payment.currentText().lower()
        if pay != "todos":
            params["payment"] = pay

        st = self.cmb_status.currentText().lower()
        if st != "todos":
            # El backend ya acepta 'aceptado'/'pendiente'/'rechazado'/'anulada'
            params["status"] = st

        q = self.txt_search.text().strip()
        if q:
            params["q"] = q

        api_call(
            "get", f"{API_URL}/reports/sales/history",
            params=params,
            headers=self._auth_headers(),
            on_success=self._on_sales_loaded,
            on_error=self._on_sales_error,
        )

    # ──────────────────────────────────────────────────────────────────────
    def _on_sales_loaded(self, response):
        """Callback: ventas recibidas."""
        data = response.get("sales", []) if isinstance(response, dict) else []
        self._sales_data = data

        self.tbl.clearContents()
        self.tbl.setRowCount(len(data))

        for row, s in enumerate(data):
            # Col 0: # Venta (texto plano, alineado a la izquierda)
            self.tbl.setCellWidget(
                row, 0,
                _cell_label(
                    f"#{s.get('id', '?')}",
                    color=COLOR_TEXT, weight=700, size=13,
                )
            )

            # Col 1: Fecha (puede venir como 'YYYY-MM-DD HH:MM')
            created = s.get("created_at", "") or ""
            date_part = created.split(" ")[0] if " " in created else created
            self.tbl.setCellWidget(
                row, 1,
                _cell_label(date_part, color=COLOR_TEXT, size=13)
            )

            # Col 2: Cliente
            self.tbl.setCellWidget(
                row, 2,
                _cell_label(
                    s.get("customer_name", "—"),
                    color=COLOR_TEXT, weight=500, size=13,
                )
            )

            # Col 3: Estado Hacienda (badge)
            self.tbl.setCellWidget(
                row, 3,
                _cell_status_badge(
                    s.get("status"),
                    s.get("hacienda_status"),
                    s.get("einvoice_id"),
                )
            )

            # Col 4: Pago con icono
            self.tbl.setCellWidget(
                row, 4,
                _cell_payment(s.get("payment_method", ""))
            )

            # Col 5: Total alineado a la derecha
            self.tbl.setCellWidget(
                row, 5,
                _cell_money(_money(s.get("total", 0)))
            )

            # Item invisible para que la selección de fila funcione
            for col in range(6):
                if self.tbl.item(row, col) is None:
                    item = QTableWidgetItem("")
                    item.setData(Qt.UserRole, s.get("id"))
                    self.tbl.setItem(row, col, item)

        # Footer
        if not data:
            self.lbl_count.setText("No se encontraron ventas con los filtros seleccionados.")
        elif len(data) == 1:
            self.lbl_count.setText("1 venta encontrada")
        else:
            self.lbl_count.setText(f"{len(data)} ventas encontradas")

        # Limpiar detalle si la venta seleccionada ya no está
        if self._current_detail:
            sid = self._current_detail.get("id")
            ids = {row.get("id") for row in data}
            if sid not in ids:
                self._reset_detail()

    def _on_sales_error(self, msg):
        QMessageBox.critical(self, "Error", f"No se pudo cargar el registro:\n{msg}")
        self.lbl_count.setText("Error al cargar ventas")

    # ══════════════════════════════════════════════════════════════════════
    # Detalle
    # ══════════════════════════════════════════════════════════════════════
    def on_row_clicked(self, row, col):
        """Carga el detalle de la venta seleccionada."""
        if row < 0 or row >= len(self._sales_data):
            return

        sale = self._sales_data[row]
        sale_id = sale.get("id")
        if not sale_id:
            return

        api_call(
            "get", f"{API_URL}/reports/sales/{sale_id}",
            headers=self._auth_headers(),
            on_success=self._on_detail_loaded,
            on_error=self._on_detail_error,
        )

    def _reset_detail(self):
        self._current_detail = None
        self.lbl_header.setText("Detalle de Venta")
        self.lbl_subheader.setText("Seleccione una factura de la lista")
        self._swap_status_banner(None)
        self.lbl_customer.setText("")
        self.lbl_customer_id.setText("")
        self.tbl_items.setRowCount(0)
        self.lbl_sub.setText("₡0.00")
        self.lbl_tax.setText("₡0.00")
        self.lbl_total.setText("₡0.00")
        self._set_actions_enabled(False)

    def _on_detail_loaded(self, d):
        """Callback: detalle de venta recibido."""
        if not isinstance(d, dict):
            return

        self._current_detail = d

        # Header
        self.lbl_header.setText(f"Detalle de Venta #{d['id']}")
        self.lbl_subheader.setText(f"Emitida el {d.get('created_at', '—')}")

        # Banner de estado
        label, icon, fg, bg = _classify_hacienda_status(
            d.get("status"), d.get("hacienda_status"), d.get("einvoice_id")
        )
        banner_text = {
            "ACEPTADO":   "ESTADO HACIENDA: ACEPTADO",
            "RECHAZADO":  "ESTADO HACIENDA: RECHAZADO",
            "PENDIENTE":  "ESTADO HACIENDA: PENDIENTE DE RESPUESTA",
            "PROCESANDO": "ESTADO HACIENDA: PROCESANDO",
            "RECIBIDO":   "ESTADO HACIENDA: RECIBIDO POR HACIENDA",
            "ANULADA":    "VENTA ANULADA",
            "SIN ENVIAR": "SIN FACTURACIÓN ELECTRÓNICA ASOCIADA",
        }.get(label, f"ESTADO HACIENDA: {label}")
        banner = StatusBadge(banner_text, icon, fg, bg, big=True)
        banner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._swap_status_banner(banner)

        # Cliente
        self.lbl_customer.setText(f"Cliente: {d.get('customer_name', '—')}")
        id_num = d.get("customer_id_number")
        id_type = d.get("customer_id_type") or ""
        if id_num:
            tag = "Cédula" if id_type else "ID"
            self.lbl_customer_id.setText(f"{tag}: {id_num}")
        else:
            self.lbl_customer_id.setText("Sin identificación registrada")

        # Items
        items = d.get("items", [])
        self.tbl_items.clearContents()
        self.tbl_items.setRowCount(max(len(items), 0))

        if not items:
            self.tbl_items.setRowCount(1)
            empty = QTableWidgetItem("Sin productos")
            empty.setForeground(QBrush(QColor(COLOR_TEXT_MUTE)))
            self.tbl_items.setItem(0, 0, empty)
            for c in range(1, 4):
                self.tbl_items.setItem(0, c, QTableWidgetItem("—"))
        else:
            for i, it in enumerate(items):
                name_item = QTableWidgetItem(it.get("product_name", "—"))
                if it.get("is_common", False):
                    name_item.setForeground(QBrush(QColor("#94a3b8")))
                    name_item.setToolTip("Producto común — sin inventario")
                self.tbl_items.setItem(i, 0, name_item)

                qty_item = QTableWidgetItem(f"{float(it.get('quantity', 0)):g}")
                qty_item.setTextAlignment(Qt.AlignCenter)
                self.tbl_items.setItem(i, 1, qty_item)

                price_item = QTableWidgetItem(_money(it.get("price", 0)))
                price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_items.setItem(i, 2, price_item)

                sub_item = QTableWidgetItem(_money(it.get("subtotal", 0)))
                sub_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl_items.setItem(i, 3, sub_item)

        # Totales
        self.lbl_sub.setText(_money(d.get("subtotal", 0)))
        self.lbl_tax.setText(_money(d.get("tax", 0)))
        self.lbl_total.setText(_money(d.get("total", 0)))

        # Habilitar acciones según contexto
        self._set_actions_enabled(True)

        # "Consultar Hacienda" sólo aplica si hay einvoice
        self.btn_check.setEnabled(bool(d.get("einvoice_id")))
        if not d.get("einvoice_id"):
            self.btn_check.setToolTip(
                "No hay factura electrónica asociada a esta venta."
            )
        else:
            self.btn_check.setToolTip(
                "Consultar directamente a Hacienda el estado actual del comprobante."
            )

        # Anular: deshabilitar si ya está anulada
        already_voided = (d.get("status") or "").upper() == "ANULADA"
        self.btn_cancel.setEnabled(not already_voided)
        if already_voided:
            self.btn_cancel.setToolTip("La venta ya fue anulada.")
        else:
            self.btn_cancel.setToolTip(
                "Anular venta — emite Nota de Crédito si la FE fue aceptada."
            )

    def _on_detail_error(self, msg):
        QMessageBox.critical(self, "Error", f"No se pudo cargar el detalle:\n{msg}")

    # ══════════════════════════════════════════════════════════════════════
    # Acciones del panel de detalle
    # ══════════════════════════════════════════════════════════════════════
    def _on_email_clicked(self):
        """Placeholder — el endpoint /sales/{id}/send-email todavía no existe.
        Mostramos un mensaje útil al usuario y dejamos el hook listo.
        """
        if not self._current_detail:
            return
        email = self._current_detail.get("customer_email")
        if not email:
            QMessageBox.warning(
                self, "Sin correo del cliente",
                "El cliente de esta venta no tiene correo electrónico registrado.\n\n"
                "Edite la ficha del cliente para agregar uno y vuelva a intentarlo."
            )
            return
        QMessageBox.information(
            self, "Envío de correo",
            f"Se enviará el comprobante a:\n  {email}\n\n"
            "(El endpoint backend de envío de venta por correo todavía no "
            "está implementado — esta función estará disponible próximamente.)"
        )

    def _on_devolucion_clicked(self):
        """Placeholder — el flujo de devolución requiere un módulo dedicado."""
        if not self._current_detail:
            return
        QMessageBox.information(
            self, "Devolución",
            "El flujo de devoluciones se gestiona desde el módulo de inventario.\n\n"
            "(Funcionalidad próximamente desde esta vista.)"
        )

    # ──────────────────────────────────────────────────────────────────────
    def _on_anular_clicked(self):
        """Anular la venta seleccionada.

        Si la FE fue ACEPTADA por Hacienda → POST /sales/{id}/cancel (NC).
        Si NO fue aceptada o no hay FE → DELETE /sales/{id} (soft-void).
        """
        if not self._current_detail:
            return

        sale_id = self._current_detail.get("id")
        if not sale_id:
            return

        hs = (self._current_detail.get("hacienda_status") or "").upper()
        is_accepted = hs == "ACEPTADO"

        if is_accepted:
            title = "Generar Nota de Crédito"
            msg = (
                f"Esta venta tiene factura electrónica ACEPTADA por Hacienda.\n\n"
                f"Se generará una Nota de Crédito (NC) para anularla.\n\n"
                f"¿Confirma anular la venta #{sale_id}?"
            )
        else:
            title = "Anular venta"
            msg = (
                f"Se anulará la venta #{sale_id} (no se enviará Nota de Crédito\n"
                f"porque la factura no fue aceptada por Hacienda).\n\n"
                f"¿Continuar?"
            )

        reply = QMessageBox.question(
            self, title, msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            if is_accepted:
                resp = api_request(
                    "post",
                    f"{API_URL}/sales/{sale_id}/cancel",
                    headers=self._auth_headers(),
                    json={"razon": "Anulación desde Registro de Ventas"},
                    timeout=30,
                )
            else:
                resp = api_request(
                    "delete",
                    f"{API_URL}/sales/{sale_id}",
                    headers=self._auth_headers(),
                    timeout=20,
                )
        except Exception as e:
            QMessageBox.critical(
                self, "Error",
                f"No se pudo anular la venta:\n{e}"
            )
            return

        if resp.status_code in (200, 201, 202, 204):
            show_toast(
                "Nota de Crédito generada." if is_accepted else "Venta anulada.",
                success=True, parent=self.main,
            )
            # Recargar lista y detalle
            self.load_sales()
            # Re-disparar el detalle para refrescar estado/banner
            api_call(
                "get", f"{API_URL}/reports/sales/{sale_id}",
                headers=self._auth_headers(),
                on_success=self._on_detail_loaded,
                on_error=self._on_detail_error,
            )
        else:
            detail = ""
            try:
                detail = resp.json().get("detail", "") or ""
            except Exception:
                pass
            QMessageBox.warning(
                self, "Atención",
                f"No se pudo completar la anulación.\n\n"
                f"Código: {resp.status_code}\n{detail or resp.text[:200]}"
            )

    # ──────────────────────────────────────────────────────────────────────
    def _on_check_hacienda_clicked(self):
        """Consulta directa el estado del comprobante a Hacienda."""
        if not self._current_detail:
            return
        einvoice_id = self._current_detail.get("einvoice_id")
        if not einvoice_id:
            QMessageBox.information(
                self, "Sin factura electrónica",
                "Esta venta no tiene una factura electrónica asociada."
            )
            return

        try:
            resp = api_request(
                "post",
                f"{API_URL}/einvoices/{einvoice_id}/check-status",
                headers=self._auth_headers(),
                timeout=30,
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Error",
                f"No se pudo consultar Hacienda:\n{e}"
            )
            return

        if resp.status_code == 200:
            try:
                payload = resp.json()
            except Exception:
                payload = {}
            data = payload.get("data") if isinstance(payload, dict) else {}
            data = data or payload or {}
            new_status = data.get("hacienda_status") or "Desconocido"

            show_toast(
                f"Estado Hacienda: {new_status}",
                success=(new_status.upper() == "ACEPTADO"),
                parent=self.main,
            )
            # Refrescar lista y detalle
            self.load_sales()
            sale_id = self._current_detail.get("id")
            if sale_id:
                api_call(
                    "get", f"{API_URL}/reports/sales/{sale_id}",
                    headers=self._auth_headers(),
                    on_success=self._on_detail_loaded,
                    on_error=self._on_detail_error,
                )
        else:
            detail = ""
            try:
                detail = resp.json().get("detail", "") or ""
            except Exception:
                pass
            QMessageBox.warning(
                self, "Consulta a Hacienda",
                f"No se pudo consultar el estado.\n\n"
                f"Código: {resp.status_code}\n{detail or resp.text[:200]}"
            )

    # ══════════════════════════════════════════════════════════════════════
    # Exportar
    # ══════════════════════════════════════════════════════════════════════
    def _export_data(self) -> list:
        """Adapta self._sales_data al formato esperado por export_utils."""
        out = []
        for s in self._sales_data:
            out.append({
                "id": s.get("id"),
                "created_at": s.get("created_at", ""),
                "customer_name": s.get("customer_name", ""),
                "payment_method": s.get("payment_method", ""),
                "total": float(s.get("total", 0) or 0),
            })
        return out

    def export_excel(self):
        try:
            if not self._sales_data:
                QMessageBox.warning(self, "Atención", "No hay ventas para exportar.")
                return

            from app.utils.export_utils import export_sales_history_excel
            filename = export_sales_history_excel(self._export_data())
            QMessageBox.information(self, "Éxito", f"Archivo Excel generado:\n{filename}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar el Excel:\n{e}")

    def export_pdf(self):
        try:
            if not self._sales_data:
                QMessageBox.warning(self, "Atención", "No hay ventas para exportar.")
                return

            from app.utils.export_utils import export_sales_history_pdf
            filename = export_sales_history_pdf(
                self._export_data(),
                self.dt_from.date().toString("yyyy-MM-dd"),
                self.dt_to.date().toString("yyyy-MM-dd"),
            )
            QMessageBox.information(self, "Éxito", f"Reporte PDF generado:\n{filename}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar el PDF:\n{e}")

    # ══════════════════════════════════════════════════════════════════════
    # Ver / regenerar PDF
    # ══════════════════════════════════════════════════════════════════════
    def open_pdf(self):
        try:
            if not self._current_detail:
                QMessageBox.warning(self, "Atención", "Selecciona una venta.")
                return

            sale_id = self._current_detail.get("id")
            if not sale_id:
                return

            pdf_path = str(get_pdf_dir() / f"venta_{sale_id}.pdf")

            if not os.path.exists(pdf_path):
                reply = QMessageBox.question(
                    self,
                    "PDF no encontrado",
                    "No existe el PDF para esta venta.\n¿Desea regenerarlo?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply != QMessageBox.Yes:
                    return
                try:
                    resp = api_request(
                        "post",
                        f"{API_URL}/sales/{sale_id}/regenerate-pdf",
                        headers=self._auth_headers(),
                        timeout=20,
                    )
                    resp.raise_for_status()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"No se pudo regenerar el PDF:\n{e}")
                    return
                if not os.path.exists(pdf_path):
                    QMessageBox.warning(
                        self, "Error",
                        "El PDF fue generado pero no se encontró en la ruta esperada."
                    )
                    return

            if os.name == "nt":
                os.startfile(pdf_path)
            elif os.name == "posix":
                import subprocess
                subprocess.Popen(["xdg-open", pdf_path])

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir el PDF:\n{e}")

    # ══════════════════════════════════════════════════════════════════════
    # API pública (usada por main_ui.py)
    # ══════════════════════════════════════════════════════════════════════
    def apply_period_filter(self, period: str,
                            start_iso: str | None = None,
                            end_iso: str | None = None):
        today = QDate.currentDate()

        if period == "today":
            self.dt_from.setDate(today)
            self.dt_to.setDate(today)
        elif period == "week":
            start = today.addDays(-today.dayOfWeek() + 1)
            end = start.addDays(6)
            self.dt_from.setDate(start)
            self.dt_to.setDate(end)
        elif period == "month":
            start = QDate(today.year(), today.month(), 1)
            end = start.addMonths(1).addDays(-1)
            self.dt_from.setDate(start)
            self.dt_to.setDate(end)

        if start_iso and end_iso:
            self.dt_from.setDate(QDate.fromString(start_iso, "yyyy-MM-dd"))
            self.dt_to.setDate(QDate.fromString(end_iso, "yyyy-MM-dd"))

        self.load_sales()

    def apply_date_range(self, start_date: str, end_date: str):
        try:
            y, m, d = map(int, start_date.split("-"))
            y2, m2, d2 = map(int, end_date.split("-"))

            self.dt_from.setDate(QDate(y, m, d))
            self.dt_to.setDate(QDate(y2, m2, d2))

            self.load_sales()
        except Exception as e:
            logger.error(f"apply_date_range error: {e}")