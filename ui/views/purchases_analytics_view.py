# ui/views/purchases_analytics_view.py
"""
Vista: Analítica de Compras
Consume los 5 endpoints de /analytics/purchases/* que ya existen en el backend:
  - spending-by-supplier
  - monthly-evolution
  - avg-payment-days
  - top-products
  - supplier-comparison (+ multi-supplier-products)
"""


import requests

from PySide6.QtCore import Qt, QDate, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDateEdit, QGroupBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QHeaderView, QAbstractItemView, QMessageBox
)
from app.utils.export_utils import export_purchases_analytics_pdf
import logging

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from ui.session_manager import session
from ui.api import BASE_URL
from ui.utils.calendar_fix import fix_calendar_colors

API_URL = BASE_URL

# Paleta dark Matplotlib
_MPL_BG      = "#1c1c1c"
_MPL_TEXT    = "#e5e7eb"
_MPL_GRID    = "#3a3a3a"
_MPL_ACCENT  = "#3a86ff"
_MPL_PALETTE = [
    "#3a86ff", "#22c55e", "#f59e0b", "#ef4444",
    "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16",
]


# ─────────────────────────────────────────────────────────────
# Worker HTTP
# ─────────────────────────────────────────────────────────────
class _PurchaseWorker(QThread):
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
# ChartWidget local (mismo estilo que sales)
# ─────────────────────────────────────────────────────────────
class _ChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.figure = Figure(figsize=(5, 3))
        self.figure.set_facecolor(_MPL_BG)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

    @staticmethod
    def style_ax(ax):
        ax.set_facecolor(_MPL_BG)
        ax.title.set_color(_MPL_TEXT)
        ax.xaxis.label.set_color(_MPL_TEXT)
        ax.yaxis.label.set_color(_MPL_TEXT)
        ax.tick_params(colors=_MPL_TEXT, which="both")
        for spine in ax.spines.values():
            spine.set_color(_MPL_GRID)


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
class PurchasesAnalyticsView(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("PurchasesAnalyticsView")
        self.setWindowTitle("Analítica de Compras")

        self._workers: dict[str, _PurchaseWorker] = {}
        self._pending_tags: set[str] = set()

        # Cache para exportación
        self._last_suppliers: list | None = None
        self._last_evolution: list | None = None
        self._last_payment_days: dict | None = None
        self._last_top_products: list | None = None

        self._build_ui()
        self.refresh_all()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Título
        title = QLabel("📦 Analítica de Compras")
        title.setObjectName("analyticsTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        # Filtros
        filter_box = QGroupBox("Filtros")
        filter_box.setObjectName("analyticsFilterBox")
        fl = QHBoxLayout(filter_box)
        fl.setContentsMargins(10, 8, 10, 8)

        fl.addWidget(QLabel("Desde:"))
        self.dt_from = QDateEdit(calendarPopup=True)
        self.dt_from.setDate(QDate.currentDate().addMonths(-3))
        self.dt_from.setDisplayFormat("yyyy-MM-dd")
        fix_calendar_colors(self.dt_from)
        fl.addWidget(self.dt_from)

        fl.addWidget(QLabel("Hasta:"))
        self.dt_to = QDateEdit(calendarPopup=True)
        self.dt_to.setDate(QDate.currentDate())
        self.dt_to.setDisplayFormat("yyyy-MM-dd")
        fix_calendar_colors(self.dt_to)
        fl.addWidget(self.dt_to)

        self.btn_refresh = QPushButton("🔄 Actualizar")
        self.btn_refresh.setObjectName("analyticsRefreshBtn")
        self.btn_refresh.clicked.connect(self.refresh_all)
        fl.addWidget(self.btn_refresh)

        fl.addStretch()

        self.btn_export_excel = QPushButton("📥 Excel")
        self.btn_export_excel.setObjectName("analyticsExportBtn")
        self.btn_export_excel.clicked.connect(self._export_excel)
        fl.addWidget(self.btn_export_excel)

        self.btn_export_pdf = QPushButton("📄 PDF")
        self.btn_export_pdf.setObjectName("analyticsExportBtn")
        self.btn_export_pdf.clicked.connect(self._export_pdf)
        fl.addWidget(self.btn_export_pdf)

        root.addWidget(filter_box)

        # Estado
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("analyticsStatus")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        root.addWidget(self.lbl_status)

        # KPIs de compras
        kpi_box = QGroupBox("Resumen")
        kpi_box.setObjectName("analyticsKpiBox")
        kpi_lay = QHBoxLayout(kpi_box)
        kpi_lay.setContentsMargins(10, 8, 10, 8)

        self.kpi_total_spent = self._make_kpi("💰 Gasto total", "₡0")
        self.kpi_invoice_count = self._make_kpi("🧾 Facturas", "0")
        self.kpi_avg_payment = self._make_kpi("📅 Prom. días pago", "—")
        self.kpi_top_supplier = self._make_kpi("🏆 Mayor proveedor", "—")

        kpi_lay.addWidget(self.kpi_total_spent)
        kpi_lay.addWidget(self.kpi_invoice_count)
        kpi_lay.addWidget(self.kpi_avg_payment)
        kpi_lay.addWidget(self.kpi_top_supplier)
        root.addWidget(kpi_box)

        # Tabs
        tabs = QTabWidget()
        tabs.setObjectName("analyticsChartTabs")

        # Tab 1: Gasto por proveedor
        tab_suppliers = QWidget()
        tab_s_lay = QVBoxLayout(tab_suppliers)
        self.chart_suppliers = _ChartWidget(self)
        tab_s_lay.addWidget(self.chart_suppliers)
        tabs.addTab(tab_suppliers, "🏢 Por proveedor")

        # Tab 2: Evolución mensual
        tab_evolution = QWidget()
        tab_e_lay = QVBoxLayout(tab_evolution)
        self.chart_evolution = _ChartWidget(self)
        tab_e_lay.addWidget(self.chart_evolution)
        tabs.addTab(tab_evolution, "📈 Evolución mensual")

        # Tab 3: Días de pago por proveedor
        tab_days = QWidget()
        tab_d_lay = QVBoxLayout(tab_days)
        self.chart_payment_days = _ChartWidget(self)
        tab_d_lay.addWidget(self.chart_payment_days)
        tabs.addTab(tab_days, "📅 Días de pago")

        root.addWidget(tabs, stretch=2)

        # Tabla: Top productos comprados
        top_box = QGroupBox("🧾 Top productos comprados")
        top_box.setObjectName("analyticsTopBox")
        top_lay = QVBoxLayout(top_box)
        top_lay.setContentsMargins(10, 8, 10, 8)

        self.table_products = QTableWidget()
        self.table_products.setObjectName("analyticsTopTable")
        self.table_products.setColumnCount(6)
        self.table_products.setHorizontalHeaderLabels([
            "#", "Producto", "Código", "Cantidad", "Gasto (₡)", "Proveedor top"
        ])
        self.table_products.verticalHeader().setVisible(False)
        self.table_products.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_products.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_products.setSortingEnabled(True)
        self.table_products.setShowGrid(False)
        self.table_products.setAlternatingRowColors(True)

        hh = self.table_products.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)

        top_lay.addWidget(self.table_products)
        root.addWidget(top_box, stretch=1)

    def _make_kpi(self, title: str, value: str) -> QLabel:
        lbl = QLabel(f"{title}<br><b>{value}</b>")
        lbl.setObjectName("analyticsKpiLabel")
        lbl.setTextFormat(Qt.RichText)
        lbl.setAlignment(Qt.AlignCenter)
        return lbl

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------
    def _date_params(self) -> dict:
        return {
            "start_date": self.dt_from.date().toString("yyyy-MM-dd"),
            "end_date": self.dt_to.date().toString("yyyy-MM-dd"),
        }

    def _launch(self, tag: str, endpoint: str, extra: dict | None = None):
        if tag in self._workers and self._workers[tag].isRunning():
            return
        params = self._date_params()
        if extra:
            params.update(extra)
        w = _PurchaseWorker(tag, f"{API_URL}{endpoint}", params)
        w.finished.connect(self._on_finished)
        w.error.connect(self._on_error)
        self._workers[tag] = w
        self._pending_tags.add(tag)
        w.start()

    def _on_finished(self, tag: str, response: dict):
        self._pending_tags.discard(tag)
        self._update_status()
        payload = response.get("data") if isinstance(response, dict) else response
        handler = {
            "suppliers": self._render_suppliers,
            "evolution": self._render_evolution,
            "days": self._render_payment_days,
            "products": self._render_top_products,
        }.get(tag)
        if handler and payload is not None:
            handler(payload)

    def _on_error(self, tag: str, msg: str):
        self._pending_tags.discard(tag)
        self._update_status()
        logging.error(f"Error compras/{tag}: {msg}")

    def _update_status(self):
        if self._pending_tags:
            n = len(self._pending_tags)
            self.lbl_status.setText(f"⏳ Cargando… ({n} pendiente{'s' if n > 1 else ''})")
            self.btn_refresh.setEnabled(False)
            self.btn_refresh.setText("⏳ Cargando…")
        else:
            self.lbl_status.setText("✅ Datos actualizados")
            self.btn_refresh.setEnabled(True)
            self.btn_refresh.setText("🔄 Actualizar")

    def refresh_all(self):
        if self._pending_tags:
            return
        self.lbl_status.setText("⏳ Cargando…")
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("⏳ Cargando…")

        self._launch("suppliers", "/analytics/purchases/spending-by-supplier")
        self._launch("evolution", "/analytics/purchases/monthly-evolution")
        self._launch("days",      "/analytics/purchases/avg-payment-days")
        self._launch("products",  "/analytics/purchases/top-products", {"limit": 10})

    # ------------------------------------------------------------------
    # Renderers
    # ------------------------------------------------------------------
    def _render_suppliers(self, data: dict):
        items = data.get("items", [])
        grand_total = data.get("grand_total", 0)
        self._last_suppliers = items

        # KPIs
        total_invoices = sum(s.get("invoice_count", 0) for s in items)
        self.kpi_total_spent.setText(f"💰 Gasto total<br><b>₡{grand_total:,.0f}</b>")
        self.kpi_invoice_count.setText(f"🧾 Facturas<br><b>{total_invoices}</b>")
        if items:
            top = items[0]
            self.kpi_top_supplier.setText(
                f"🏆 Mayor proveedor<br><b>{top['supplier_name']}</b>"
            )

        # Gráfico de barras horizontales
        names = [s["supplier_name"][:20] for s in items]
        amounts = [s["total_spent"] for s in items]

        self.chart_suppliers.figure.clear()
        ax = self.chart_suppliers.figure.add_subplot(111)
        _ChartWidget.style_ax(ax)

        if names:
            colors = (_MPL_PALETTE * ((len(names) // len(_MPL_PALETTE)) + 1))[:len(names)]
            ax.barh(names[::-1], amounts[::-1], color=colors[::-1], height=0.6)
            ax.set_xlabel("Gasto (₡)")

        ax.set_title("Gasto por proveedor", fontsize=13, fontweight="bold")
        ax.grid(True, axis="x", alpha=0.2, color=_MPL_GRID)
        self.chart_suppliers.figure.tight_layout()
        self.chart_suppliers.canvas.draw_idle()

    def _render_evolution(self, data: list):
        self._last_evolution = data
        months = [r["month"] for r in data]
        totals = [r["total"] for r in data]

        self.chart_evolution.figure.clear()
        ax = self.chart_evolution.figure.add_subplot(111)
        _ChartWidget.style_ax(ax)

        if months:
            ax.bar(range(len(months)), totals, color=_MPL_ACCENT, width=0.6)
            ax.plot(range(len(months)), totals, color="#22c55e", marker="o", linewidth=1.5, markersize=4)
            ax.set_xticks(range(len(months)))
            ax.set_xticklabels(months, rotation=45, ha="right", fontsize=8)

        ax.set_title("Evolución mensual de compras", fontsize=13, fontweight="bold")
        ax.set_ylabel("Monto (₡)")
        ax.grid(True, axis="y", alpha=0.2, color=_MPL_GRID)
        self.chart_evolution.figure.tight_layout()
        self.chart_evolution.canvas.draw_idle()

    def _render_payment_days(self, data: dict):
        self._last_payment_days = data
        global_avg = data.get("global_avg_days")
        if global_avg is not None:
            self.kpi_avg_payment.setText(
                f"📅 Prom. días pago<br><b>{global_avg:.1f} días</b>"
            )

        by_supplier = data.get("by_supplier", [])
        names = [s["supplier_name"][:20] for s in by_supplier if s.get("avg_days") is not None]
        days = [s["avg_days"] for s in by_supplier if s.get("avg_days") is not None]

        self.chart_payment_days.figure.clear()
        ax = self.chart_payment_days.figure.add_subplot(111)
        _ChartWidget.style_ax(ax)

        if names:
            colors = ["#22c55e" if d <= 15 else "#f59e0b" if d <= 30 else "#ef4444" for d in days]
            ax.barh(names[::-1], days[::-1], color=colors[::-1], height=0.6)
            ax.set_xlabel("Días promedio de pago")
            if global_avg is not None:
                ax.axvline(x=global_avg, color="#3a86ff", linestyle="--", alpha=0.7, label=f"Promedio: {global_avg:.1f}d")
                ax.legend(loc="lower right", fontsize=9, facecolor=_MPL_BG, edgecolor=_MPL_GRID, labelcolor=_MPL_TEXT)

        ax.set_title("Días de pago por proveedor", fontsize=13, fontweight="bold")
        ax.grid(True, axis="x", alpha=0.2, color=_MPL_GRID)
        self.chart_payment_days.figure.tight_layout()
        self.chart_payment_days.canvas.draw_idle()

    def _render_top_products(self, data: list):
        self._last_top_products = data
        self.table_products.setSortingEnabled(False)
        self.table_products.setRowCount(len(data))

        for row, p in enumerate(data):
            rank = _NumericItem(str(row + 1), row + 1)
            rank.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)

            name_item = QTableWidgetItem(p.get("product_name", ""))
            name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            code_item = QTableWidgetItem(p.get("product_code", ""))
            code_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)

            qty_item = _NumericItem(f"{p.get('total_qty', 0):,}", p.get("total_qty", 0))
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            spent = p.get("total_spent", 0.0)
            spent_item = _NumericItem(f"₡{spent:,.2f}", spent)
            spent_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            supplier_item = QTableWidgetItem(p.get("top_supplier", "—") or "—")
            supplier_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            self.table_products.setItem(row, 0, rank)
            self.table_products.setItem(row, 1, name_item)
            self.table_products.setItem(row, 2, code_item)
            self.table_products.setItem(row, 3, qty_item)
            self.table_products.setItem(row, 4, spent_item)
            self.table_products.setItem(row, 5, supplier_item)

        self.table_products.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # Exportación
    # ------------------------------------------------------------------
    def _gather_export_data(self) -> dict:
        return {
            "start_date": self.dt_from.date().toString("yyyy-MM-dd"),
            "end_date": self.dt_to.date().toString("yyyy-MM-dd"),
            "suppliers": self._last_suppliers,
            "evolution": self._last_evolution,
            "payment_days": self._last_payment_days,
            "top_products": self._last_top_products,
        }

    def _export_excel(self):
        try:
            data = self._gather_export_data()
            if not data["suppliers"]:
                QMessageBox.warning(self, "Atención", "No hay datos. Presione Actualizar primero.")
                return
            from app.utils.export_utils import export_purchases_analytics_excel
            filename = export_purchases_analytics_excel(data)
            QMessageBox.information(self, "Éxito", f"Archivo Excel generado:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar:\n{e}")

    def _export_pdf(self):
        try:
            data = self._gather_export_data()
            if not data["suppliers"]:
                QMessageBox.warning(self, "Atención", "No hay datos. Presione Actualizar primero.")
                return
            filename = export_purchases_analytics_pdf(data)
            QMessageBox.information(self, "Éxito", f"Reporte PDF generado:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar:\n{e}")