from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDateEdit,
    QPushButton, QMessageBox, QFrame, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
)
from PySide6.QtCore import Qt, QDate, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor
import requests
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from ui.session_manager import session
from ui.api import BASE_URL
from ui.utils.calendar_fix import fix_calendar_colors
import logging
import os
import tempfile
from datetime import datetime

API_URL = BASE_URL

# ─────────────────────────────────────────────────────────────
# Paleta de colores (misma que daily_report_view)
# ─────────────────────────────────────────────────────────────
THEME = {
    "bg_app":       "#121212",
    "bg_header":    "#1a1a1a",
    "bg_card":      "#1c1c1c",
    "bg_input":     "#2A2A2A",
    "bg_table":     "#202020",
    "bg_table_alt": "#252525",
    "bg_table_hdr": "#333333",
    "bg_summary":   "#1e1e1e",
    "border_sep":   "#404040",
    "text_primary": "#FFFFFF",
    "text_muted":   "#aaaaaa",
    "text_dim":     "#888888",
    "accent_blue":  "#3a86ff",
    "accent_green": "#06d6a0",
    "accent_purple":"#8338ec",
    "accent_pink":  "#ff006e",
    "accent_yellow":"#ffd60a",
    "accent_orange":"#ff8800",
    "error":        "#ff6b6b",
    "disabled_bg":  "#444444",
    "disabled_text":"#888888",
}

METHOD_COLORS = {
    "Efectivo":      THEME["accent_green"],
    "SINPE":         THEME["accent_blue"],
    "Tarjeta":       THEME["accent_purple"],
    "Crédito":       THEME["accent_pink"],
    "Transferencia": THEME["accent_yellow"],
}

STATUS_COLORS = {
    "pendiente": THEME["accent_yellow"],
    "parcial":   THEME["accent_orange"],
    "vencido":   THEME["error"],
    "pagado":    THEME["accent_green"],
    "recibido":  THEME["accent_blue"],
}


# ─────────────────────────────────────────────────────────────
# Worker HTTP asíncrono
# ─────────────────────────────────────────────────────────────
class FinancialWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, url: str, headers: dict, params: dict):
        super().__init__()
        self.url = url
        self.headers = headers
        self.params = params

    def run(self):
        try:
            r = requests.get(
                self.url, headers=self.headers,
                params=self.params, timeout=15,
            )
            if r.status_code != 200:
                self.error.emit(f"HTTP {r.status_code}: {r.text}")
                return
            self.finished.emit(r.json())
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────
# Vista principal
# ─────────────────────────────────────────────────────────────
class FinancialView(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reporte Financiero Global")
        self.resize(950, 850)
        self._active_workers = []
        self._figures = []
        self._spinner_dots = 0
        self._spinner_timer = None
        self._data = None
        self._chart_path = None
        self.setup_ui()

    # ─── helpers de estilo ───────────────────────────────────
    @staticmethod
    def _section_title(text, color=THEME["accent_blue"]):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size:14px; font-weight:bold; margin-top:10px; "
            f"color:{color}; padding: 4px 0;"
        )
        return lbl

    @staticmethod
    def _detail_label(text=""):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size:13px; margin:2px 0 2px 16px; "
            f"color:{THEME['text_primary']};"
        )
        return lbl

    @staticmethod
    def _separator():
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(2)
        sep.setStyleSheet(f"background-color: {THEME['border_sep']}; border: none;")
        return sep

    def _preset_button(self, text, callback):
        btn = QPushButton(text)
        btn.setFixedHeight(32)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME["bg_input"]};
                color: {THEME["text_primary"]};
                border: 1px solid {THEME["border_sep"]};
                border-radius: 8px;
                padding: 4px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {THEME["bg_table_hdr"]};
                border-color: {THEME["accent_blue"]};
            }}
        """)
        btn.clicked.connect(callback)
        return btn

    @staticmethod
    def _style_table(table):
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {THEME["bg_table"]};
                color: white; border: none;
                border-radius: 8px; gridline-color: #333;
            }}
            QTableWidget::item {{ padding: 6px; }}
            QTableWidget::item:alternate {{ background-color: {THEME["bg_table_alt"]}; }}
            QHeaderView::section {{
                background-color: {THEME["bg_table_hdr"]};
                color: white; padding: 8px; border: none; font-weight: bold;
            }}
        """)

    # ─── UI setup ────────────────────────────────────────────
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ═══════ HEADER FIJO ═══════
        header_w = QWidget()
        header_w.setStyleSheet(f"background-color: {THEME['bg_header']}; padding: 12px;")
        header = QHBoxLayout(header_w)

        title = QLabel("📊 Reporte Financiero Global")
        title.setStyleSheet(f"font-size:22px; font-weight:bold; color:{THEME['text_primary']};")
        header.addWidget(title)
        header.addStretch()

        lbl_from = QLabel("Desde:")
        lbl_from.setStyleSheet(f"color:{THEME['text_muted']}; font-size:13px;")
        header.addWidget(lbl_from)
        self.dt_from = QDateEdit(calendarPopup=True)
        self.dt_from.setDate(QDate.currentDate().addDays(-7))
        self.dt_from.setDisplayFormat("dd/MM/yyyy")
        self._style_date_edit(self.dt_from)
        fix_calendar_colors(self.dt_from)
        header.addWidget(self.dt_from)

        lbl_to = QLabel("Hasta:")
        lbl_to.setStyleSheet(f"color:{THEME['text_muted']}; font-size:13px;")
        header.addWidget(lbl_to)
        self.dt_to = QDateEdit(calendarPopup=True)
        self.dt_to.setDate(QDate.currentDate())
        self.dt_to.setDisplayFormat("dd/MM/yyyy")
        self._style_date_edit(self.dt_to)
        fix_calendar_colors(self.dt_to)
        header.addWidget(self.dt_to)

        self.btn_refresh = QPushButton("🔍 Actualizar")
        self.btn_refresh.setFixedHeight(36)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background-color: {THEME["accent_green"]};
                color: white; border-radius: 10px;
                padding: 6px 16px; font-weight: bold; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: #05b589; }}
        """)
        self.btn_refresh.clicked.connect(self.load_data)
        header.addWidget(self.btn_refresh)

        # 4.1: Botón PDF
        self.btn_pdf = QPushButton("📄 Exportar PDF")
        self.btn_pdf.setFixedHeight(36)
        self.btn_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_pdf.setEnabled(False)
        self._apply_pdf_btn_style()
        self.btn_pdf.clicked.connect(self.export_pdf)
        header.addWidget(self.btn_pdf)

        main_layout.addWidget(header_w)

        # ═══════ PRESETS DE FECHA ═══════
        presets_w = QWidget()
        presets_w.setStyleSheet(f"background-color: {THEME['bg_header']}; padding: 0 12px 8px 12px;")
        presets = QHBoxLayout(presets_w)
        presets.setContentsMargins(0, 0, 0, 0)
        presets.setSpacing(6)
        presets.addWidget(self._preset_button("Hoy", self._preset_today))
        presets.addWidget(self._preset_button("Esta semana", self._preset_this_week))
        presets.addWidget(self._preset_button("Este mes", self._preset_this_month))
        presets.addWidget(self._preset_button("Últimos 30 días", self._preset_last_30))
        presets.addWidget(self._preset_button("Este año", self._preset_this_year))
        presets.addStretch()
        main_layout.addWidget(presets_w)

        # ═══════ SCROLL BODY ═══════
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"QScrollArea {{ border: none; background-color: {THEME['bg_app']}; }}")
        scroll_content = QWidget()
        self.body = QVBoxLayout(scroll_content)
        self.body.setSpacing(4)
        self.body.setContentsMargins(20, 16, 20, 20)

        # Spinner
        self.loading_indicator = QLabel("")
        self.loading_indicator.setAlignment(Qt.AlignCenter)
        self.loading_indicator.setStyleSheet(
            f"font-size:18px; color:{THEME['accent_blue']}; padding:30px; background-color:transparent;"
        )
        self.loading_indicator.setVisible(False)
        self.body.addWidget(self.loading_indicator)

        # Totales principales
        self.lbl_sales = QLabel()
        self.lbl_expenses = QLabel()
        self.lbl_profit = QLabel()
        for lbl in [self.lbl_sales, self.lbl_expenses, self.lbl_profit]:
            lbl.setStyleSheet(f"font-size:15px; font-weight:bold; margin:3px 0; color:{THEME['text_primary']};")
            self.body.addWidget(lbl)

        # 4.2: Comparación de período
        self.lbl_comparison = QLabel()
        self.lbl_comparison.setStyleSheet(f"font-size:12px; color:{THEME['text_muted']}; margin:4px 0 0 4px;")
        self.body.addWidget(self.lbl_comparison)
        self.comparison_container = QVBoxLayout()
        self.body.addLayout(self.comparison_container)

        self.body.addWidget(self._separator())

        # Margen bruto
        self.body.addWidget(self._section_title("📦 Margen bruto", THEME["accent_blue"]))
        self.lbl_cogs = self._detail_label()
        self.lbl_gross_profit = self._detail_label()
        self.lbl_gross_margin = self._detail_label()
        for lbl in [self.lbl_cogs, self.lbl_gross_profit, self.lbl_gross_margin]:
            self.body.addWidget(lbl)
        self.body.addWidget(self._separator())

        # IVA
        self.body.addWidget(self._section_title("🏛️ IVA recaudado en el período", THEME["accent_purple"]))
        self.lbl_tax = self._detail_label()
        self.body.addWidget(self.lbl_tax)
        self.body.addWidget(self._separator())

        # Método de pago
        self.body.addWidget(self._section_title("💳 Ventas por método de pago", THEME["accent_green"]))
        self.payment_labels_container = QVBoxLayout()
        self.body.addLayout(self.payment_labels_container)
        self.body.addWidget(self._separator())

        # Crédito vs contado
        self.body.addWidget(self._section_title("🔄 Ventas: contado vs crédito", THEME["accent_yellow"]))
        self.lbl_cash_sales = self._detail_label()
        self.lbl_credit_sales = self._detail_label()
        self.body.addWidget(self.lbl_cash_sales)
        self.body.addWidget(self.lbl_credit_sales)
        self.body.addWidget(self._separator())

        # 4.3: Desglose de gastos por categoría
        self.body.addWidget(self._section_title("🧾 Desglose de gastos en el período"))
        self.lbl_op_expenses = self._detail_label()
        self.body.addWidget(self.lbl_op_expenses)
        self.expense_cat_container = QVBoxLayout()
        self.body.addLayout(self.expense_cat_container)
        self.lbl_purchase_expenses = self._detail_label()
        self.body.addWidget(self.lbl_purchase_expenses)
        self.body.addWidget(self._separator())

        # 4.4: Tabla de compras
        self.body.addWidget(self._section_title("📦 Detalle de compras en el período", THEME["accent_orange"]))
        self.lbl_purchases_summary = self._detail_label()
        self.body.addWidget(self.lbl_purchases_summary)
        self.table_purchases = QTableWidget()
        self.table_purchases.setColumnCount(6)
        self.table_purchases.setHorizontalHeaderLabels(
            ["Factura", "Proveedor", "Monto", "Pagado", "Saldo", "Estado"]
        )
        self.table_purchases.setMinimumHeight(120)
        self.table_purchases.setMaximumHeight(250)
        self._style_table(self.table_purchases)
        self.body.addWidget(self.table_purchases)
        self.body.addWidget(self._separator())

        # Cuentas por cobrar / pagar
        self.body.addWidget(self._section_title("📋 Balance: cuentas por cobrar y por pagar", THEME["accent_orange"]))
        self.lbl_total_receivables = self._detail_label()
        self.lbl_total_payables = self._detail_label()
        self.lbl_overdue_payables = self._detail_label()
        self.lbl_net_balance = self._detail_label()
        for lbl in [self.lbl_total_receivables, self.lbl_total_payables,
                     self.lbl_overdue_payables, self.lbl_net_balance]:
            self.body.addWidget(lbl)
        self.body.addWidget(self._separator())

        # Gráfico
        self.chart_container = QFrame()
        self.chart_container.setStyleSheet(
            f"background-color: {THEME['bg_card']}; border-radius: 12px; padding: 12px;"
        )
        self.chart_layout = QVBoxLayout(self.chart_container)
        self.chart_layout.setContentsMargins(8, 8, 8, 8)
        self.body.addWidget(self.chart_container)

        self.body.addStretch()
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        self.load_data()

    # ─── estilo date edits ───────────────────────────────────
    def _style_date_edit(self, de):
        de.setFixedHeight(36)
        de.setFixedWidth(140)
        de.setStyleSheet(f"""
            QDateEdit {{
                background-color: {THEME["bg_input"]};
                color: {THEME["text_primary"]};
                border: 2px solid {THEME["accent_blue"]};
                border-radius: 10px; padding: 6px; font-size: 13px;
            }}
        """)

    def _apply_pdf_btn_style(self):
        if self.btn_pdf.isEnabled():
            self.btn_pdf.setStyleSheet(f"""
                QPushButton {{
                    background-color: {THEME["accent_blue"]};
                    color: white; border-radius: 10px;
                    padding: 6px 16px; font-weight: bold; font-size: 13px;
                }}
                QPushButton:hover {{ background-color: #2a6fd3; }}
            """)
        else:
            self.btn_pdf.setStyleSheet(f"""
                QPushButton {{
                    background-color: {THEME["disabled_bg"]};
                    color: {THEME["disabled_text"]};
                    border-radius: 10px; padding: 6px 16px; font-size: 13px;
                }}
            """)

    # ─── presets de fecha ────────────────────────────────────
    def _preset_today(self):
        today = QDate.currentDate()
        self.dt_from.setDate(today); self.dt_to.setDate(today); self.load_data()

    def _preset_this_week(self):
        today = QDate.currentDate()
        self.dt_from.setDate(today.addDays(-(today.dayOfWeek() - 1)))
        self.dt_to.setDate(today); self.load_data()

    def _preset_this_month(self):
        today = QDate.currentDate()
        self.dt_from.setDate(QDate(today.year(), today.month(), 1))
        self.dt_to.setDate(today); self.load_data()

    def _preset_last_30(self):
        today = QDate.currentDate()
        self.dt_from.setDate(today.addDays(-30)); self.dt_to.setDate(today); self.load_data()

    def _preset_this_year(self):
        today = QDate.currentDate()
        self.dt_from.setDate(QDate(today.year(), 1, 1))
        self.dt_to.setDate(today); self.load_data()

    # ─── spinner ─────────────────────────────────────────────
    def _start_spinner(self):
        self._spinner_dots = 0
        self.loading_indicator.setVisible(True)
        self.loading_indicator.setText("⏳ Cargando reporte financiero")
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._animate_spinner)
        self._spinner_timer.start(400)

    def _animate_spinner(self):
        self._spinner_dots = (self._spinner_dots + 1) % 4
        self.loading_indicator.setText(f"⏳ Cargando reporte financiero{'.' * self._spinner_dots}")

    def _stop_spinner(self):
        if self._spinner_timer:
            self._spinner_timer.stop(); self._spinner_timer = None
        self.loading_indicator.setVisible(False)

    def _set_loading_state(self, loading: bool):
        self.btn_refresh.setEnabled(not loading)
        self.btn_pdf.setEnabled(False if loading else bool(self._data))
        self._apply_pdf_btn_style()
        if loading:
            self.btn_refresh.setText("⏳ Cargando..."); self._start_spinner()
        else:
            self.btn_refresh.setText("🔍 Actualizar"); self._stop_spinner()

    # ─── worker management ──────────────────────────────────
    def _keep_worker(self, w):
        self._active_workers.append(w)
        w.finished.connect(lambda: self._cleanup_worker(w))
        if hasattr(w, "error"):
            w.error.connect(lambda: self._cleanup_worker(w))

    def _cleanup_worker(self, w):
        try: self._active_workers.remove(w)
        except ValueError: pass
        w.deleteLater()

    def _auth_headers(self):
        if not session.token:
            raise ValueError("No hay sesión activa.")
        return {"Authorization": f"Bearer {session.token}"}

    # ─── clear helpers ───────────────────────────────────────
    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()

    def _clear_chart(self):
        for fig in self._figures:
            try:
                import matplotlib.pyplot as plt
                plt.close(fig)
            except Exception:
                pass
        self._figures.clear()
        self._clear_layout(self.chart_layout)

    # ─── load data ───────────────────────────────────────────
    def load_data(self):
        try:
            start_date = self.dt_from.date().toString("yyyy-MM-dd")
            end_date = self.dt_to.date().toString("yyyy-MM-dd")
            self._set_loading_state(True)
            worker = FinancialWorker(
                url=f"{API_URL}/financial/summary",
                headers=self._auth_headers(),
                params={"start_date": start_date, "end_date": end_date},
            )
            worker.finished.connect(self._on_data_loaded)
            worker.error.connect(self._on_data_error)
            self._keep_worker(worker)
            worker.start()
        except Exception as e:
            logging.error(f"Error iniciando carga financiera: {e}")
            self._set_loading_state(False)
            QMessageBox.critical(self, "Error", f"No se pudo iniciar la carga:\n{e}")

    def _on_data_loaded(self, data: dict):
        try:
            self._data = data
            self._populate(data)
        except Exception as e:
            logging.error(f"Error poblando reporte financiero: {e}")
            QMessageBox.critical(self, "Error", f"Error procesando datos:\n{e}")
        finally:
            self._set_loading_state(False)

    def _on_data_error(self, err: str):
        logging.error(f"Error cargando reporte financiero: {err}")
        self._data = None
        self._set_loading_state(False)
        QMessageBox.critical(self, "Error", f"No se pudo obtener el reporte financiero:\n{err}")

    # ─── comparison helper (4.2) ─────────────────────────────
    @staticmethod
    def _trend_text(label, current, previous):
        if previous == 0:
            pct = "N/A"
            arrow = "➖"
        else:
            change = ((current - previous) / abs(previous)) * 100
            if change > 0:
                arrow = "🔼"
                pct = f"+{change:.1f}%"
            elif change < 0:
                arrow = "🔽"
                pct = f"{change:.1f}%"
            else:
                arrow = "➖"
                pct = "0.0%"
        delta = current - previous
        sign = "+" if delta >= 0 else ""
        return f"  {arrow} {label}: ₡{current:,.2f}  ({pct}, {sign}₡{delta:,.2f} vs anterior)"

    # ─── populate UI ─────────────────────────────────────────
    def _populate(self, data: dict):
        T = THEME

        # Totales principales
        self.lbl_sales.setText(f"💰 Ventas: ₡{data['total_sales']:,.2f}")
        self.lbl_expenses.setText(f"💸 Gastos totales: ₡{data['total_expenses']:,.2f}")
        net = data["net_profit"]
        net_c = T["accent_green"] if net >= 0 else T["error"]
        self.lbl_profit.setText(f"📈 Utilidad neta: ₡{net:,.2f}")
        self.lbl_profit.setStyleSheet(f"font-size:15px; font-weight:bold; margin:3px 0; color:{net_c};")

        # 4.2: Comparación de período
        self._clear_layout(self.comparison_container)
        prev = data.get("previous_period", {})
        if prev:
            pstart = prev.get("start_date", "")
            pend = prev.get("end_date", "")
            self.lbl_comparison.setText(f"📅 Comparación vs período anterior ({pstart} a {pend}):")
            comparisons = [
                ("Ventas", data["total_sales"], prev.get("total_sales", 0)),
                ("Gastos", data["total_expenses"], prev.get("total_expenses", 0)),
                ("Utilidad", data["net_profit"], prev.get("net_profit", 0)),
                ("Ganancia bruta", data.get("gross_profit", 0), prev.get("gross_profit", 0)),
            ]
            for label, cur, prv in comparisons:
                lbl = QLabel(self._trend_text(label, cur, prv))
                lbl.setStyleSheet(f"font-size:12px; margin:1px 0 1px 16px; color:{T['text_muted']};")
                self.comparison_container.addWidget(lbl)
        else:
            self.lbl_comparison.setText("")

        # Margen bruto
        self.lbl_cogs.setText(f"  Costo de ventas (COGS): ₡{data.get('total_cogs', 0):,.2f}")
        gp = data.get("gross_profit", 0)
        gp_c = T["accent_green"] if gp >= 0 else T["error"]
        self.lbl_gross_profit.setText(f"  Ganancia bruta: ₡{gp:,.2f}")
        self.lbl_gross_profit.setStyleSheet(f"font-size:13px; margin:2px 0 2px 16px; color:{gp_c}; font-weight:bold;")
        self.lbl_gross_margin.setText(f"  Margen bruto: {data.get('gross_margin_pct', 0):.2f}%")

        # IVA
        self.lbl_tax.setText(f"  IVA total: ₡{data.get('total_tax_collected', 0):,.2f}")

        # Métodos de pago
        self._clear_layout(self.payment_labels_container)
        breakdown = data.get("payment_breakdown", {})
        for pm, monto in sorted(breakdown.items(), key=lambda x: -x[1]):
            dot_color = METHOD_COLORS.get(pm, T["text_muted"])
            lbl = QLabel(f"  ● {pm}: ₡{monto:,.2f}")
            lbl.setStyleSheet(f"font-size:13px; margin:2px 0 2px 16px; color:{dot_color};")
            self.payment_labels_container.addWidget(lbl)

        # Crédito vs contado
        self.lbl_cash_sales.setText(
            f"  Contado: ₡{data.get('cash_sales_total', 0):,.2f}  ({data.get('cash_sales_count', 0)} ventas)")
        self.lbl_credit_sales.setText(
            f"  Crédito: ₡{data.get('credit_sales_total', 0):,.2f}  ({data.get('credit_sales_count', 0)} ventas)")

        # 4.3: Gastos por categoría
        self.lbl_op_expenses.setText(f"  Gastos operativos: ₡{data.get('operational_expenses', 0):,.2f}")
        self._clear_layout(self.expense_cat_container)
        exp_cats = data.get("expense_by_category", {})
        for cat, monto in sorted(exp_cats.items(), key=lambda x: -x[1]):
            lbl = QLabel(f"      • {cat}: ₡{monto:,.2f}")
            lbl.setStyleSheet(f"font-size:12px; margin:1px 0 1px 32px; color:{T['text_muted']};")
            self.expense_cat_container.addWidget(lbl)
        self.lbl_purchase_expenses.setText(f"  Pagos a proveedores: ₡{data.get('purchase_expenses', 0):,.2f}")

        # 4.4: Tabla de compras
        details = data.get("purchases_detail", [])
        self.lbl_purchases_summary.setText(
            f"  Compras: {data.get('purchases_count', 0)} — "
            f"Monto total: ₡{data.get('total_purchases_amount', 0):,.2f}"
        )
        self.table_purchases.setRowCount(len(details))
        if not details:
            self.table_purchases.setVisible(False)
        else:
            self.table_purchases.setVisible(True)
            for row, p in enumerate(details):
                self.table_purchases.setItem(row, 0, QTableWidgetItem(p.get("invoice_number", "")))
                self.table_purchases.setItem(row, 1, QTableWidgetItem(p.get("supplier", "")))

                amt_item = QTableWidgetItem(f"₡{p.get('amount', 0):,.2f}")
                amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table_purchases.setItem(row, 2, amt_item)

                paid_item = QTableWidgetItem(f"₡{p.get('paid_amount', 0):,.2f}")
                paid_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table_purchases.setItem(row, 3, paid_item)

                bal = p.get("balance", 0)
                bal_item = QTableWidgetItem(f"₡{bal:,.2f}")
                bal_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if bal > 0:
                    bal_item.setForeground(QColor(T["accent_orange"]))
                self.table_purchases.setItem(row, 4, bal_item)

                st = p.get("status", "")
                st_item = QTableWidgetItem(st.capitalize())
                st_color = STATUS_COLORS.get(st, T["text_muted"])
                st_item.setForeground(QColor(st_color))
                self.table_purchases.setItem(row, 5, st_item)

        # Cuentas por cobrar / pagar
        recv = data.get("total_receivables", 0)
        payb = data.get("total_payables", 0)
        ovrd = data.get("overdue_payables", 0)
        net_bal = recv - payb
        self.lbl_total_receivables.setText(f"  Cuentas por cobrar (clientes): ₡{recv:,.2f}")
        self.lbl_total_payables.setText(f"  Cuentas por pagar (proveedores): ₡{payb:,.2f}")
        ovrd_c = T["error"] if ovrd > 0 else T["text_dim"]
        self.lbl_overdue_payables.setText(f"  Vencido: ₡{ovrd:,.2f}")
        self.lbl_overdue_payables.setStyleSheet(
            f"font-size:13px; margin:2px 0 2px 16px; color:{ovrd_c}; font-weight:bold;")
        bal_c = T["accent_green"] if net_bal >= 0 else T["error"]
        self.lbl_net_balance.setText(f"  Balance neto (cobrar − pagar): ₡{net_bal:,.2f}")
        self.lbl_net_balance.setStyleSheet(
            f"font-size:13px; margin:2px 0 2px 16px; color:{bal_c}; font-weight:bold;")

        # Gráfico
        self._render_chart(data.get("chart_data", []))

    # ─── gráfico dark mode ───────────────────────────────────
    def _render_chart(self, chart_data):
        self._clear_chart()
        self._chart_path = None

        if not chart_data:
            lbl = QLabel("Sin datos para el rango seleccionado.")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(f"color:{THEME['text_muted']}; font-size:14px; padding:20px;")
            self.chart_layout.addWidget(lbl)
            return

        T = THEME
        bg = T["bg_card"]
        fechas_raw = [d["fecha"] for d in chart_data]
        ventas = [d["ventas"] for d in chart_data]
        gastos_op = [d.get("gastos_operativos", 0) for d in chart_data]
        pagos_prov = [d.get("pagos_proveedores", 0) for d in chart_data]
        utilidad = [d["utilidad"] for d in chart_data]

        n = len(fechas_raw)
        if n <= 10:
            fechas = [f[-5:].replace("-", "/") for f in fechas_raw]
            rotation = 0
        else:
            step = max(1, n // 10)
            fechas = [f[-5:].replace("-", "/") if i % step == 0 else "" for i, f in enumerate(fechas_raw)]
            rotation = 45

        x = list(range(n))
        fig = Figure(figsize=(10, 4.5), facecolor=bg)
        self._figures.append(fig)
        ax = fig.add_subplot(111)
        fig.subplots_adjust(left=0.10, right=0.96, top=0.88, bottom=0.18)

        bar_w = 0.5
        ax.bar(x, gastos_op, label="Gastos operativos", color=T["accent_yellow"], alpha=0.85, width=bar_w)
        ax.bar(x, pagos_prov, bottom=gastos_op, label="Pagos proveedores",
               color=T["accent_orange"], alpha=0.85, width=bar_w)
        ax.plot(x, ventas, marker="o", markersize=5, label="Ventas",
                color=T["accent_green"], linewidth=2)
        ax.plot(x, utilidad, marker="o", markersize=4, label="Utilidad",
                linestyle="--", color=T["accent_blue"], linewidth=1.8)

        if n <= 14:
            for xi, v in zip(x, ventas):
                if v > 0:
                    ax.text(xi, v, f"₡{v:,.0f}", ha="center", va="bottom",
                            color=T["accent_green"], fontsize=8, fontweight="bold")

        ax.set_facecolor(bg)
        ax.set_title("Ingresos, gastos y utilidad", color="white", fontsize=15, fontweight="bold", pad=12)
        ax.set_ylabel("Monto (₡)", color="white", fontsize=11)
        ax.set_xticks(x)
        ax.set_xticklabels(fechas, rotation=rotation, ha="right" if rotation else "center", fontsize=9)
        ax.tick_params(colors="white", labelsize=10)
        ax.grid(axis="y", alpha=0.15, linestyle="--", color="white")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(T["border_sep"])
        ax.spines["bottom"].set_color(T["border_sep"])
        ax.legend(fontsize=9, facecolor=T["bg_summary"], edgecolor=T["border_sep"],
                  labelcolor="white", loc="upper left")

        canvas = FigureCanvas(fig)
        canvas.setMinimumHeight(380)
        self.chart_layout.addWidget(canvas)

        # Guardar imagen temporal para PDF
        try:
            tmp = os.path.join(tempfile.gettempdir(), "violettepos_financial_chart.png")
            fig.savefig(tmp, dpi=120, facecolor=fig.get_facecolor())
            self._chart_path = tmp
        except Exception:
            pass

    # ═════════════════════════════════════════════════════════
    # 4.1: EXPORTAR PDF
    # ═════════════════════════════════════════════════════════
    def export_pdf(self):
        if not self._data:
            QMessageBox.warning(self, "Sin datos", "No hay datos para exportar.")
            return

        default_name = (
            f"Reporte_Financiero_"
            f"{self.dt_from.date().toString('yyyyMMdd')}_"
            f"{self.dt_to.date().toString('yyyyMMdd')}.pdf"
        )
        filepath, _ = QFileDialog.getSaveFileName(self, "Guardar PDF", default_name, "PDF (*.pdf)")
        if not filepath:
            return

        try:
            self._generate_pdf(filepath)
            QMessageBox.information(self, "PDF generado", f"Archivo guardado en:\n{filepath}")
        except Exception as e:
            logging.error(f"Error generando PDF: {e}")
            QMessageBox.critical(self, "Error", f"No se pudo generar el PDF:\n{e}")

    def _generate_pdf(self, filepath: str):
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors as rl_colors
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
        )
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT

        data = self._data
        start_str = self.dt_from.date().toString("dd/MM/yyyy")
        end_str = self.dt_to.date().toString("dd/MM/yyyy")

        doc = SimpleDocTemplate(filepath, pagesize=letter,
                                leftMargin=15 * mm, rightMargin=15 * mm,
                                topMargin=15 * mm, bottomMargin=15 * mm)
        page_width = letter[0] - 30 * mm
        styles = getSampleStyleSheet()

        styles.add(ParagraphStyle("PDFTitle", parent=styles["Title"], fontSize=18,
                                  textColor=rl_colors.HexColor("#333333"), spaceAfter=4 * mm))
        styles.add(ParagraphStyle("PDFSubTitle", parent=styles["Normal"], fontSize=11,
                                  textColor=rl_colors.HexColor("#666666"), alignment=TA_CENTER,
                                  spaceAfter=6 * mm))
        styles.add(ParagraphStyle("SectionTitle", parent=styles["Heading2"], fontSize=13,
                                  textColor=rl_colors.HexColor("#3a86ff"),
                                  spaceBefore=6 * mm, spaceAfter=3 * mm))
        styles.add(ParagraphStyle("CellBold", parent=styles["Normal"], fontSize=10, leading=12))
        styles.add(ParagraphStyle("CellText", parent=styles["Normal"], fontSize=9, leading=11))

        def _make_table(rows, col_widths, header_color="#3a86ff"):
            t = Table(rows, colWidths=col_widths)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor(header_color)),
                ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [rl_colors.HexColor("#f5f5f5"), rl_colors.white]),
                ("BOX", (0, 0), (-1, -1), 0.5, rl_colors.grey),
                ("GRID", (0, 0), (-1, -1), 0.25, rl_colors.HexColor("#dddddd")),
            ]))
            return t

        story = []

        # Título
        story.append(Paragraph("Reporte Financiero Global", styles["PDFTitle"]))
        story.append(Paragraph(f"Período: {start_str} — {end_str}", styles["PDFSubTitle"]))

        # Resumen principal
        story.append(Paragraph("Resumen General", styles["SectionTitle"]))
        summary_rows = [
            [Paragraph("<b>Métrica</b>", styles["CellBold"]),
             Paragraph("<b>Monto</b>", styles["CellBold"])],
            ["Ventas totales", f"₡{data['total_sales']:,.2f}"],
            ["Costo de ventas (COGS)", f"₡{data.get('total_cogs', 0):,.2f}"],
            ["Ganancia bruta", f"₡{data.get('gross_profit', 0):,.2f}"],
            ["Margen bruto", f"{data.get('gross_margin_pct', 0):.2f}%"],
            ["Gastos totales", f"₡{data['total_expenses']:,.2f}"],
            ["Utilidad neta", f"₡{data['net_profit']:,.2f}"],
            ["IVA recaudado", f"₡{data.get('total_tax_collected', 0):,.2f}"],
        ]
        story.append(_make_table(summary_rows, [page_width * 0.55, page_width * 0.45]))
        story.append(Spacer(1, 4 * mm))

        # 4.2: Comparación
        prev = data.get("previous_period", {})
        if prev and prev.get("total_sales", 0) > 0:
            story.append(Paragraph(
                f"Comparación vs período anterior ({prev.get('start_date', '')} a {prev.get('end_date', '')})",
                styles["SectionTitle"]))
            comp_rows = [
                [Paragraph("<b>Métrica</b>", styles["CellBold"]),
                 Paragraph("<b>Actual</b>", styles["CellBold"]),
                 Paragraph("<b>Anterior</b>", styles["CellBold"]),
                 Paragraph("<b>Cambio</b>", styles["CellBold"])],
            ]
            for label, key in [("Ventas", "total_sales"), ("Gastos", "total_expenses"),
                               ("Utilidad", "net_profit"), ("G. bruta", "gross_profit")]:
                cur = data.get(key, 0)
                prv = prev.get(key, 0)
                delta = cur - prv
                sign = "+" if delta >= 0 else ""
                comp_rows.append([label, f"₡{cur:,.2f}", f"₡{prv:,.2f}", f"{sign}₡{delta:,.2f}"])
            cw = page_width * 0.25
            story.append(_make_table(comp_rows, [cw, cw, cw, cw], "#8338ec"))
            story.append(Spacer(1, 4 * mm))

        # Métodos de pago
        breakdown = data.get("payment_breakdown", {})
        if breakdown:
            story.append(Paragraph("Ventas por Método de Pago", styles["SectionTitle"]))
            pm_rows = [[Paragraph("<b>Método</b>", styles["CellBold"]),
                        Paragraph("<b>Monto</b>", styles["CellBold"]),
                        Paragraph("<b>%</b>", styles["CellBold"])]]
            total_pm = sum(breakdown.values())
            for pm, amt in sorted(breakdown.items(), key=lambda x: -x[1]):
                pct = (amt / total_pm * 100) if total_pm > 0 else 0
                pm_rows.append([pm, f"₡{amt:,.2f}", f"{pct:.1f}%"])
            story.append(_make_table(pm_rows,
                                     [page_width * 0.45, page_width * 0.35, page_width * 0.20], "#06d6a0"))
            story.append(Spacer(1, 4 * mm))

        # 4.3: Gastos por categoría
        exp_cats = data.get("expense_by_category", {})
        if exp_cats:
            story.append(Paragraph("Desglose de Gastos Operativos", styles["SectionTitle"]))
            gc_rows = [[Paragraph("<b>Categoría</b>", styles["CellBold"]),
                        Paragraph("<b>Monto</b>", styles["CellBold"])]]
            for cat, amt in sorted(exp_cats.items(), key=lambda x: -x[1]):
                gc_rows.append([cat, f"₡{amt:,.2f}"])
            gc_rows.append([Paragraph("<b>Total operativos</b>", styles["CellBold"]),
                            Paragraph(f"<b>₡{data.get('operational_expenses', 0):,.2f}</b>", styles["CellBold"])])
            story.append(_make_table(gc_rows, [page_width * 0.60, page_width * 0.40], "#ff8800"))
            story.append(Spacer(1, 4 * mm))

        # 4.4: Detalle de compras
        purchases = data.get("purchases_detail", [])
        if purchases:
            story.append(Paragraph(f"Compras del Período ({len(purchases)})", styles["SectionTitle"]))
            pc_rows = [[
                Paragraph("<b>Factura</b>", styles["CellBold"]),
                Paragraph("<b>Proveedor</b>", styles["CellBold"]),
                Paragraph("<b>Monto</b>", styles["CellBold"]),
                Paragraph("<b>Saldo</b>", styles["CellBold"]),
                Paragraph("<b>Estado</b>", styles["CellBold"]),
            ]]
            for p in purchases:
                pc_rows.append([
                    p.get("invoice_number", ""),
                    Paragraph(p.get("supplier", ""), styles["CellText"]),
                    f"₡{p.get('amount', 0):,.2f}",
                    f"₡{p.get('balance', 0):,.2f}",
                    p.get("status", "").capitalize(),
                ])
            story.append(_make_table(
                pc_rows,
                [page_width * 0.18, page_width * 0.32, page_width * 0.18,
                 page_width * 0.18, page_width * 0.14],
                "#ff8800"))
            story.append(Spacer(1, 4 * mm))

        # Cuentas por cobrar / pagar
        story.append(Paragraph("Cuentas por Cobrar y Pagar", styles["SectionTitle"]))
        recv = data.get("total_receivables", 0)
        payb = data.get("total_payables", 0)
        bal_rows = [
            [Paragraph("<b>Concepto</b>", styles["CellBold"]),
             Paragraph("<b>Monto</b>", styles["CellBold"])],
            ["Cuentas por cobrar (clientes)", f"₡{recv:,.2f}"],
            ["Cuentas por pagar (proveedores)", f"₡{payb:,.2f}"],
            ["Vencido (proveedores)", f"₡{data.get('overdue_payables', 0):,.2f}"],
            [Paragraph("<b>Balance neto</b>", styles["CellBold"]),
             Paragraph(f"<b>₡{recv - payb:,.2f}</b>", styles["CellBold"])],
        ]
        story.append(_make_table(bal_rows, [page_width * 0.60, page_width * 0.40], "#ff8800"))
        story.append(Spacer(1, 4 * mm))

        # Gráfico
        if self._chart_path and os.path.exists(self._chart_path):
            story.append(Paragraph("Gráfico de Ingresos, Gastos y Utilidad", styles["SectionTitle"]))
            story.append(RLImage(self._chart_path, width=page_width, height=55 * mm))
            story.append(Spacer(1, 4 * mm))

        # Pie de página
        story.append(Spacer(1, 6 * mm))
        footer_style = ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8,
                                      textColor=rl_colors.HexColor("#999999"), alignment=TA_CENTER)
        story.append(Paragraph(
            f"Reporte generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} "
            f"— Violette POS © {datetime.now().year}",
            footer_style))

        doc.build(story)

    # ─── cleanup ─────────────────────────────────────────────
    def closeEvent(self, event):
        self._clear_chart()
        self._stop_spinner()
        for w in self._active_workers:
            w.quit(); w.wait(2000)
        if self._chart_path and os.path.exists(self._chart_path):
            try: os.remove(self._chart_path)
            except Exception: logging.debug("No se pudo eliminar chart temporal: %s", self._chart_path)
        super().closeEvent(event)