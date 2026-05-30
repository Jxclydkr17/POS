import re
from datetime import date, timedelta
import requests

from PySide6.QtCore import Qt, QDate, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDateEdit, QGroupBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QHeaderView, QAbstractItemView, QMessageBox
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from app.utils.export_utils import export_sales_analytics_pdf
import logging
from ui.session_manager import session
from ui.api import BASE_URL
from ui.utils.calendar_fix import fix_calendar_colors

API_URL = BASE_URL


def _strip_emoji(text: str) -> str:
    """Elimina emojis de un texto para compatibilidad con Matplotlib."""
    return re.sub(r'[\U00010000-\U0010ffff\u2600-\u27BF\u2B50\uFE0F]', '', text).strip()

# ─────────────────────────────────────────────────────────────
# Paleta dark para Matplotlib
# ─────────────────────────────────────────────────────────────
_MPL_BG      = "#1c1c1c"
_MPL_TEXT    = "#e5e7eb"
_MPL_GRID    = "#3a3a3a"
_MPL_ACCENT  = "#3a86ff"
_MPL_PALETTE = [
    "#3a86ff", "#22c55e", "#f59e0b", "#ef4444",
    "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16",
]


# ─────────────────────────────────────────────────────────────
# Worker genérico HTTP
# ─────────────────────────────────────────────────────────────
class AnalyticsWorker(QThread):
    finished = Signal(str, dict)
    error = Signal(str, str)

    def __init__(self, tag: str, url: str, params: dict):
        super().__init__()
        self.tag = tag
        self.url = url
        self.params = params

    def run(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            res = requests.get(self.url, params=self.params, headers=headers, timeout=15)
            res.raise_for_status()
            self.finished.emit(self.tag, res.json())
        except Exception as exc:
            self.error.emit(self.tag, str(exc))


# ─────────────────────────────────────────────────────────────
# ChartWidget con tema dark
# ─────────────────────────────────────────────────────────────
class ChartWidget(QWidget):
    def __init__(self, parent=None, title: str = ""):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.figure = Figure(figsize=(4, 3))
        self.figure.set_facecolor(_MPL_BG)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        if title:
            self.setWindowTitle(title)

    @staticmethod
    def style_ax(ax):
        ax.set_facecolor(_MPL_BG)
        ax.title.set_color(_MPL_TEXT)
        ax.xaxis.label.set_color(_MPL_TEXT)
        ax.yaxis.label.set_color(_MPL_TEXT)
        ax.tick_params(colors=_MPL_TEXT, which="both")
        for spine in ax.spines.values():
            spine.set_color(_MPL_GRID)


# ─────────────────────────────────────────────────────────────
# NumericItem para tablas
# ─────────────────────────────────────────────────────────────
class _NumericItem(QTableWidgetItem):
    def __init__(self, display: str, sort_val: float):
        super().__init__(display)
        self._val = sort_val

    def __lt__(self, other):
        if isinstance(other, _NumericItem):
            return self._val < other._val
        return super().__lt__(other)


# ─────────────────────────────────────────────────────────────
# Vista principal
# ─────────────────────────────────────────────────────────────
class SalesAnalyticsView(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("SalesAnalyticsView")
        self.setWindowTitle("Analítica de Ventas")
        self.resize(1100, 700)

        self._workers: dict[str, AnalyticsWorker] = {}
        self._pending_tags: set[str] = set()

        # Cache de datos para exportación
        self._last_kpis: dict | None = None
        self._last_top: list | None = None
        self._last_categories: list | None = None
        self._last_daily: list | None = None
        self._last_payments: list | None = None
        self._last_compare: dict | None = None

        self._build_ui()
        self.refresh_all()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # ---------- TÍTULO ----------
        title = QLabel("📊 Reportes y Analítica de Ventas")
        title.setObjectName("analyticsTitle")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        # ---------- FILTROS + EXPORTACIÓN ----------
        filter_box = QGroupBox("Filtros")
        filter_box.setObjectName("analyticsFilterBox")
        filter_layout = QHBoxLayout(filter_box)
        filter_layout.setContentsMargins(10, 8, 10, 8)

        filter_layout.addWidget(QLabel("Desde:"))
        self.dt_from = QDateEdit(calendarPopup=True)
        self.dt_from.setDate(QDate.currentDate().addDays(-7))
        self.dt_from.setDisplayFormat("yyyy-MM-dd")
        fix_calendar_colors(self.dt_from)
        filter_layout.addWidget(self.dt_from)

        filter_layout.addWidget(QLabel("Hasta:"))
        self.dt_to = QDateEdit(calendarPopup=True)
        self.dt_to.setDate(QDate.currentDate())
        self.dt_to.setDisplayFormat("yyyy-MM-dd")
        fix_calendar_colors(self.dt_to)
        filter_layout.addWidget(self.dt_to)

        self.btn_refresh = QPushButton("🔄 Actualizar")
        self.btn_refresh.setObjectName("analyticsRefreshBtn")
        self.btn_refresh.clicked.connect(self.refresh_all)
        filter_layout.addWidget(self.btn_refresh)

        filter_layout.addStretch()

        # Botones de exportación
        self.btn_export_excel = QPushButton("📥 Excel")
        self.btn_export_excel.setObjectName("analyticsExportBtn")
        self.btn_export_excel.clicked.connect(self._export_excel)
        filter_layout.addWidget(self.btn_export_excel)

        self.btn_export_pdf = QPushButton("📄 PDF")
        self.btn_export_pdf.setObjectName("analyticsExportBtn")
        self.btn_export_pdf.clicked.connect(self._export_pdf)
        filter_layout.addWidget(self.btn_export_pdf)

        main_layout.addWidget(filter_box)

        # ---------- ESTADO ----------
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("analyticsStatus")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.lbl_status)

        # ---------- KPIs ----------
        kpi_box = QGroupBox("Indicadores clave")
        kpi_box.setObjectName("analyticsKpiBox")
        kpi_layout = QHBoxLayout(kpi_box)
        kpi_layout.setContentsMargins(10, 8, 10, 8)

        self.lbl_total_sales = self._create_kpi_label("Ventas totales", "0")
        self.lbl_total_amount = self._create_kpi_label("Monto total", "₡0.00")
        self.lbl_avg_ticket = self._create_kpi_label("Ticket promedio", "₡0.00")

        kpi_layout.addWidget(self.lbl_total_sales)
        kpi_layout.addWidget(self.lbl_total_amount)
        kpi_layout.addWidget(self.lbl_avg_ticket)

        main_layout.addWidget(kpi_box)

        # ---------- GRÁFICOS (TABS) ----------
        charts_tabs = QTabWidget()
        charts_tabs.setObjectName("analyticsChartTabs")

        tab_daily = QWidget()
        tab_daily_layout = QVBoxLayout(tab_daily)
        self.chart_daily = ChartWidget(self, "Ventas Diarias")
        tab_daily_layout.addWidget(self.chart_daily)
        charts_tabs.addTab(tab_daily, "📈 Ventas diarias")

        tab_payments = QWidget()
        tab_payments_layout = QVBoxLayout(tab_payments)
        self.chart_payments = ChartWidget(self, "Métodos de pago")
        tab_payments_layout.addWidget(self.chart_payments)
        charts_tabs.addTab(tab_payments, "💳 Métodos de pago")

        tab_categories = QWidget()
        tab_categories_layout = QVBoxLayout(tab_categories)
        self.chart_categories = ChartWidget(self, "Ventas por categoría")
        tab_categories_layout.addWidget(self.chart_categories)
        charts_tabs.addTab(tab_categories, "🏷️ Por categoría")

        main_layout.addWidget(charts_tabs, stretch=2)

        # ---------- TOP PRODUCTOS ----------
        top_box = QGroupBox("🧾 Top productos")
        top_box.setObjectName("analyticsTopBox")
        top_layout = QVBoxLayout(top_box)
        top_layout.setContentsMargins(10, 8, 10, 8)

        self.table_top = QTableWidget()
        self.table_top.setObjectName("analyticsTopTable")
        self.table_top.setColumnCount(5)
        self.table_top.setHorizontalHeaderLabels([
            "#", "Producto", "Cantidad", "Total (₡)", "% del Total"
        ])
        self.table_top.verticalHeader().setVisible(False)
        self.table_top.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_top.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_top.setSortingEnabled(True)
        self.table_top.setShowGrid(False)
        self.table_top.setAlternatingRowColors(True)

        hh = self.table_top.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        top_layout.addWidget(self.table_top)
        main_layout.addWidget(top_box, stretch=1)

    def _create_kpi_label(self, title: str, value: str) -> QLabel:
        lbl = QLabel(f"{title}<br><b>{value}</b>")
        lbl.setObjectName("analyticsKpiLabel")
        lbl.setTextFormat(Qt.RichText)
        lbl.setAlignment(Qt.AlignCenter)
        return lbl

    # ------------------------------------------------------------------
    # Helpers de periodo anterior
    # ------------------------------------------------------------------
    def _previous_period_params(self) -> dict:
        """Calcula el periodo anterior simétrico al seleccionado."""
        qd_from = self.dt_from.date()
        qd_to = self.dt_to.date()
        d_from = date(qd_from.year(), qd_from.month(), qd_from.day())
        d_to = date(qd_to.year(), qd_to.month(), qd_to.day())
        span = (d_to - d_from).days + 1
        prev_end = d_from - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)
        return {
            "current_start": d_from.isoformat(),
            "current_end": d_to.isoformat(),
            "previous_start": prev_start.isoformat(),
            "previous_end": prev_end.isoformat(),
        }

    # ------------------------------------------------------------------
    # WORKERS
    # ------------------------------------------------------------------
    def _date_params(self) -> dict:
        return {
            "start_date": self.dt_from.date().toString("yyyy-MM-dd"),
            "end_date": self.dt_to.date().toString("yyyy-MM-dd"),
        }

    def _launch_worker(self, tag: str, endpoint: str, extra_params: dict | None = None):
        if tag in self._workers and self._workers[tag].isRunning():
            return
        params = self._date_params()
        if extra_params:
            params.update(extra_params)
        worker = AnalyticsWorker(tag, f"{API_URL}{endpoint}", params)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)
        self._workers[tag] = worker
        self._pending_tags.add(tag)
        worker.start()

    def _launch_compare_worker(self):
        """Lanza el worker de /compare con parámetros de periodo anterior."""
        tag = "compare"
        if tag in self._workers and self._workers[tag].isRunning():
            return
        params = self._previous_period_params()
        worker = AnalyticsWorker(tag, f"{API_URL}/analytics/compare", params)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)
        self._workers[tag] = worker
        self._pending_tags.add(tag)
        worker.start()

    def _on_worker_finished(self, tag: str, response: dict):
        self._pending_tags.discard(tag)
        self._update_status()
        payload = response.get("data") if isinstance(response, dict) else response
        handler = {
            "kpis": self._render_kpis,
            "compare": self._render_compare,
            "daily": self._render_daily_sales,
            "payments": self._render_payment_methods,
            "categories": self._render_by_category,
            "top": self._render_top_products,
        }.get(tag)
        if handler and payload is not None:
            handler(payload)

    def _on_worker_error(self, tag: str, msg: str):
        self._pending_tags.discard(tag)
        self._update_status()
        logging.error(f"Error cargando {tag}: {msg}")

    def _update_status(self):
        if self._pending_tags:
            pending = len(self._pending_tags)
            self.lbl_status.setText(
                f"⏳ Cargando datos… ({pending} pendiente{'s' if pending > 1 else ''})"
            )
            self.btn_refresh.setEnabled(False)
            self.btn_refresh.setText("⏳ Cargando…")
        else:
            self.lbl_status.setText("✅ Datos actualizados")
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("🔄 Actualizar")

    # ------------------------------------------------------------------
    # REFRESH
    # ------------------------------------------------------------------
    def refresh_all(self):
        if self._pending_tags:
            return
        self.lbl_status.setText("⏳ Cargando datos…")
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("⏳ Cargando…")

        self._launch_worker("kpis",       "/analytics/kpis")
        self._launch_worker("daily",      "/analytics/daily-sales")
        self._launch_worker("payments",   "/analytics/payment-methods")
        self._launch_worker("categories", "/analytics/by-category")
        self._launch_worker("top",        "/analytics/top-products", {"limit": 10})
        self._launch_compare_worker()

    # ------------------------------------------------------------------
    # RENDERERS
    # ------------------------------------------------------------------
    def _render_kpis(self, data: dict):
        self._last_kpis = data
        total_sales = data.get("total_sales", 0)
        total_amount = data.get("total_amount", 0.0)
        avg_ticket = data.get("avg_ticket", 0.0)

        self.lbl_total_sales.setText(f"Ventas totales<br><b>{total_sales}</b>")
        self.lbl_total_amount.setText(f"Monto total<br><b>₡{total_amount:,.2f}</b>")
        self.lbl_avg_ticket.setText(f"Ticket promedio<br><b>₡{avg_ticket:,.2f}</b>")

    def _render_compare(self, data: dict):
        """Muestra indicadores de variación porcentual vs periodo anterior."""
        self._last_compare = data
        current = data.get("current", {})
        previous = data.get("previous", {})

        def trend_html(cur_val: float, prev_val: float) -> str:
            if not prev_val:
                return ""
            pct = ((cur_val - prev_val) / prev_val) * 100
            if pct > 0:
                return f"<br><span style='color:#22c55e;font-size:11px;'>▲ {pct:.1f}% vs anterior</span>"
            elif pct < 0:
                return f"<br><span style='color:#ef4444;font-size:11px;'>▼ {abs(pct):.1f}% vs anterior</span>"
            else:
                return "<br><span style='color:#9ca3af;font-size:11px;'>= sin cambio</span>"

        cur_sales = current.get("count", 0)
        cur_amount = current.get("total_amount", 0.0)
        cur_ticket = current.get("avg_ticket", 0.0)
        prev_sales = previous.get("count", 0)
        prev_amount = previous.get("total_amount", 0.0)
        prev_ticket = previous.get("avg_ticket", 0.0)

        self.lbl_total_sales.setText(
            f"Ventas totales<br><b>{cur_sales}</b>{trend_html(cur_sales, prev_sales)}"
        )
        self.lbl_total_amount.setText(
            f"Monto total<br><b>₡{cur_amount:,.2f}</b>{trend_html(cur_amount, prev_amount)}"
        )
        self.lbl_avg_ticket.setText(
            f"Ticket promedio<br><b>₡{cur_ticket:,.2f}</b>{trend_html(cur_ticket, prev_ticket)}"
        )

    def _render_daily_sales(self, data: list):
        self._last_daily = data
        dates = [row["date"] for row in data]
        totals = [row["total"] for row in data]

        self.chart_daily.figure.clear()
        ax = self.chart_daily.figure.add_subplot(111)
        ChartWidget.style_ax(ax)

        if dates:
            ax.plot(dates, totals, marker="o", color=_MPL_ACCENT, linewidth=2, markersize=5)
            ax.fill_between(range(len(dates)), totals, alpha=0.15, color=_MPL_ACCENT)
            ax.set_xticks(range(len(dates)))
            ax.set_xticklabels(dates, rotation=45, ha="right", fontsize=8)

        ax.set_title("Ventas diarias", fontsize=13, fontweight="bold")
        ax.set_ylabel("Monto (₡)")
        ax.grid(True, alpha=0.2, color=_MPL_GRID)
        self.chart_daily.figure.tight_layout()
        self.chart_daily.canvas.draw_idle()

    def _render_payment_methods(self, data: list):
        self._last_payments = data
        labels = [row["method"] for row in data]
        values = [row["total"] for row in data]

        self.chart_payments.figure.clear()
        ax = self.chart_payments.figure.add_subplot(111)
        ChartWidget.style_ax(ax)

        if values:
            colors = _MPL_PALETTE[:len(values)]
            wedges, texts, autotexts = ax.pie(
                values, labels=labels, autopct="%1.1f%%",
                colors=colors, textprops={"color": _MPL_TEXT, "fontsize": 10},
            )
            for t in autotexts:
                t.set_fontsize(9)
                t.set_color("#ffffff")

        ax.set_title("Métodos de pago", fontsize=13, fontweight="bold")
        self.chart_payments.figure.tight_layout()
        self.chart_payments.canvas.draw_idle()

    def _render_by_category(self, data: list):
        self._last_categories = data
        labels = [_strip_emoji(row["category"]) for row in data]
        values = [row["total"] for row in data]

        self.chart_categories.figure.clear()
        ax = self.chart_categories.figure.add_subplot(111)
        ChartWidget.style_ax(ax)

        if labels:
            colors = (_MPL_PALETTE * ((len(labels) // len(_MPL_PALETTE)) + 1))[:len(labels)]
            ax.bar(labels, values, color=colors, edgecolor="none", width=0.65)
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)

        ax.set_title("Ventas por categoría", fontsize=13, fontweight="bold")
        ax.set_ylabel("Monto (₡)")
        ax.grid(True, axis="y", alpha=0.2, color=_MPL_GRID)
        self.chart_categories.figure.tight_layout()
        self.chart_categories.canvas.draw_idle()

    def _render_top_products(self, data: list):
        self._last_top = data
        grand_total = sum(p.get("total", 0.0) for p in data) or 1.0

        self.table_top.setSortingEnabled(False)
        self.table_top.setRowCount(len(data))

        for row, p in enumerate(data):
            name = p.get("name", "")
            qty = p.get("quantity", 0)
            total = p.get("total", 0.0)
            pct = (total / grand_total) * 100

            rank_item = _NumericItem(str(row + 1), row + 1)
            rank_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            name_item = QTableWidgetItem(name)
            name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            qty_item = _NumericItem(f"{qty:,}", qty)
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            total_item = _NumericItem(f"₡{total:,.2f}", total)
            total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            pct_item = _NumericItem(f"{pct:.1f}%", pct)
            pct_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            self.table_top.setItem(row, 0, rank_item)
            self.table_top.setItem(row, 1, name_item)
            self.table_top.setItem(row, 2, qty_item)
            self.table_top.setItem(row, 3, total_item)
            self.table_top.setItem(row, 4, pct_item)

        self.table_top.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # EXPORTACIÓN (#11)
    # ------------------------------------------------------------------
    def _gather_export_data(self) -> dict:
        """Reúne los datos cacheados para exportar."""
        return {
            "start_date": self.dt_from.date().toString("yyyy-MM-dd"),
            "end_date": self.dt_to.date().toString("yyyy-MM-dd"),
            "kpis": self._last_kpis,
            "compare": self._last_compare,
            "top_products": self._last_top,
            "categories": self._last_categories,
            "daily": self._last_daily,
            "payments": self._last_payments,
        }

    def _export_excel(self):
        try:
            data = self._gather_export_data()
            if not data["kpis"]:
                QMessageBox.warning(self, "Atención", "No hay datos para exportar. Presione Actualizar primero.")
                return

            from app.utils.export_utils import export_sales_analytics_excel
            filename = export_sales_analytics_excel(data)
            QMessageBox.information(self, "Éxito", f"Archivo Excel generado:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar el Excel:\n{e}")

    def _export_pdf(self):
        try:
            data = self._gather_export_data()
            if not data["kpis"]:
                QMessageBox.warning(self, "Atención", "No hay datos para exportar. Presione Actualizar primero.")
                return
            filename = export_sales_analytics_pdf(data)
            QMessageBox.information(self, "Éxito", f"Reporte PDF generado:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar el PDF:\n{e}")