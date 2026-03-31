from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QDateEdit,
    QScrollArea, QTabWidget, QFileDialog, QMessageBox, QGraphicsOpacityEffect
)
from PySide6.QtCore import Qt, QDate, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont
import requests
from ui.session_manager import session
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage,
    KeepTogether, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from datetime import datetime
from ui.api import BASE_URL
import os
import tempfile
import logging


API_URL = f"{BASE_URL}/cash/report/{{date}}"

# ─────────────────────────────────────────────────────────────
# FIX #22: Paleta de colores centralizada
# ─────────────────────────────────────────────────────────────
THEME = {
    "bg_app":       "#121212",    # Fondo principal de la app
    "bg_header":    "#1a1a1a",    # Fondo del encabezado
    "bg_card":      "#1c1c1c",    # Fondo de tarjetas / gráficos
    "bg_input":     "#2A2A2A",    # Fondo de inputs / boxes
    "bg_table":     "#202020",    # Fondo de tablas
    "bg_table_alt": "#252525",    # Fila alterna de tabla
    "bg_table_hdr": "#333333",    # Header de tabla
    "bg_summary":   "#1e1e1e",    # Fondo de resumen / badge
    "border_sep":   "#404040",    # Separadores
    "text_primary": "#FFFFFF",    # Texto principal
    "text_muted":   "#aaaaaa",    # Texto secundario
    "text_dim":     "#888888",    # Texto apagado
    "accent_blue":  "#3a86ff",    # Azul primario
    "accent_green": "#06d6a0",    # Verde
    "accent_purple":"#8338ec",    # Morado
    "accent_pink":  "#ff006e",    # Rosa / rojo
    "accent_yellow":"#ffd60a",    # Amarillo
    "accent_orange":"#ff8800",    # Naranja
    "error":        "#ff6b6b",    # Error
    "disabled_bg":  "#444444",    # Botón deshabilitado
    "disabled_text":"#888888",    # Texto deshabilitado
}

# Colores por método de pago
METHOD_COLORS = {
    "Efectivo": THEME["accent_green"],
    "SINPE":    THEME["accent_blue"],
    "Tarjeta":  THEME["accent_purple"],
    "Crédito":  THEME["accent_pink"],
    "Transferencia": THEME["accent_yellow"],
}




# ─────────────────────────────────────────────────────────────
# Worker para llamada HTTP asíncrona (FIX #1 + FIX #9)
# Un solo worker porque ahora el endpoint devuelve todo
# ─────────────────────────────────────────────────────────────
class ReportWorker(QThread):
    """Carga el reporte consolidado del día en segundo plano."""
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, url: str, headers: dict):
        super().__init__()
        self.url = url
        self.headers = headers

    def run(self):
        try:
            response = requests.get(self.url, headers=self.headers, timeout=15)
            if response.status_code != 200:
                self.error.emit(f"HTTP {response.status_code}: {response.text}")
                return
            self.finished.emit(response.json())
        except Exception as e:
            self.error.emit(str(e))


class DailyReportView(QWidget):
    def __init__(self):
        super().__init__()
        self.data = None
        self._active_workers = []
        self._temp_chart_files = []
        self.bar_chart_path = None
        self.pie_chart_path = None
        self._figures = []
        self._spinner_dots = 0                     # FIX #10: contador para animación
        self._spinner_timer = None                 # FIX #10: timer del spinner
        self.setup_ui()
        self.load_report()

    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # ======================
        #   ENCABEZADO FIJO
        # ======================
        header_container = QWidget()
        header_container.setStyleSheet("background-color: #1a1a1a; padding: 15px;")
        header = QHBoxLayout(header_container)

        title = QLabel("📅 Reporte del Día")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #FFFFFF;")

        # Controles de fecha
        self.date_selector = QDateEdit()
        self.date_selector.setCalendarPopup(True)
        self.date_selector.setDate(QDate.currentDate())
        self.date_selector.setDisplayFormat("dd/MM/yyyy")
        self.date_selector.setFixedHeight(40)
        self.date_selector.setFixedWidth(150)
        self.date_selector.setStyleSheet("""
            QDateEdit {
                background-color: #2A2A2A;
                color: white;
                border: 2px solid #3a86ff;
                border-radius: 10px;
                padding: 8px;
                font-size: 14px;
            }
        """)

        self.btn_load_date = QPushButton("🔍 Cargar")
        self.btn_load_date.setFixedHeight(40)
        self.btn_load_date.setFixedWidth(120)
        self.btn_load_date.setStyleSheet("""
            QPushButton {
                background-color: #06d6a0;
                color: white;
                border-radius: 10px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #05b589; }
        """)
        self.btn_load_date.clicked.connect(self.load_report)

        self.btn_today = QPushButton("📆 Hoy")
        self.btn_today.setFixedHeight(40)
        self.btn_today.setFixedWidth(100)
        self.btn_today.setStyleSheet("""
            QPushButton {
                background-color: #8338ec;
                color: white;
                border-radius: 10px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #6b2dbf; }
        """)
        self.btn_today.clicked.connect(self.load_today)

        # FIX #14: Botón PDF inicia deshabilitado
        self.btn_export_pdf = QPushButton("📄 Exportar PDF")
        self.btn_export_pdf.setFixedHeight(40)
        self.btn_export_pdf.setEnabled(False)
        self._apply_pdf_button_style()
        self.btn_export_pdf.clicked.connect(self.export_pdf)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("Seleccionar fecha:"))
        header.addWidget(self.date_selector)
        header.addWidget(self.btn_load_date)
        header.addWidget(self.btn_today)
        header.addWidget(self.btn_export_pdf)

        self.layout.addWidget(header_container)

        # ======================
        #   CONTENIDO CON SCROLL
        # ======================
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background-color: #121212; }")
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(20)
        scroll_layout.setContentsMargins(20, 20, 20, 20)

        # ─────────────────────────────────────────────────────
        # FIX #10: Indicador de carga (spinner)
        # ─────────────────────────────────────────────────────
        self.loading_indicator = QLabel("")
        self.loading_indicator.setAlignment(Qt.AlignCenter)
        self.loading_indicator.setStyleSheet("""
            font-size: 18px; color: #3a86ff; padding: 30px;
            background-color: transparent;
        """)
        self.loading_indicator.setVisible(False)
        scroll_layout.addWidget(self.loading_indicator)

        # FIX #7: Badge de estado de caja
        self.status_container = QHBoxLayout()
        scroll_layout.addLayout(self.status_container)

        # RESUMEN
        self.summary_container = QHBoxLayout()
        scroll_layout.addLayout(self.summary_container)

        # TABS
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #1c1c1c;
                border-radius: 10px;
            }
            QTabBar::tab {
                background-color: #2A2A2A;
                color: white;
                padding: 10px 20px;
                margin-right: 5px;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }
            QTabBar::tab:selected {
                background-color: #3a86ff;
            }
            QTabBar::tab:hover {
                background-color: #404040;
            }
        """)

        # TAB 1: VENTAS Y MOVIMIENTOS
        tab_transactions = QWidget()
        tab_transactions_layout = QVBoxLayout(tab_transactions)
        tab_transactions_layout.setSpacing(25)

        # ─────────────────────────────────────────────────────
        # FIX #15: Resumen de pagos en pestaña de Transacciones
        # ─────────────────────────────────────────────────────
        self.payment_summary_container = QHBoxLayout()
        tab_transactions_layout.addLayout(self.payment_summary_container)

        # Ventas
        label_sales = QLabel("🧾 Ventas del Día")
        label_sales.setStyleSheet("font-size: 20px; font-weight: bold; color: #FFFFFF; margin-top: 10px;")
        tab_transactions_layout.addWidget(label_sales)

        # FIX #11: 5 columnas (+ Hora)
        self.table_sales = QTableWidget()
        self.table_sales.setColumnCount(5)
        self.table_sales.setHorizontalHeaderLabels(["ID", "Hora", "Cliente", "Método", "Total"])
        self.table_sales.setMinimumHeight(250)
        self._style_table(self.table_sales)
        tab_transactions_layout.addWidget(self.table_sales)

        # FIX #13: Label de total de ventas
        self.label_sales_total = QLabel("")
        self.label_sales_total.setAlignment(Qt.AlignRight)
        self.label_sales_total.setStyleSheet("""
            font-size: 16px; font-weight: bold; color: #06d6a0;
            padding: 8px 15px; background-color: #1e1e1e;
            border-radius: 8px;
        """)
        tab_transactions_layout.addWidget(self.label_sales_total)

        # Movimientos
        label_mov = QLabel("💼 Movimientos de Caja")
        label_mov.setStyleSheet("font-size: 20px; font-weight: bold; color: #FFFFFF; margin-top: 10px;")
        tab_transactions_layout.addWidget(label_mov)

        # FIX #12: 5 columnas (+ Hora + Origen)
        self.table_mov = QTableWidget()
        self.table_mov.setColumnCount(5)
        self.table_mov.setHorizontalHeaderLabels(["Tipo", "Hora", "Monto", "Origen", "Descripción"])
        self.table_mov.setMinimumHeight(250)
        self._style_table(self.table_mov)
        tab_transactions_layout.addWidget(self.table_mov)

        # FIX #13: Labels de totales de movimientos
        self.label_mov_totals = QLabel("")
        self.label_mov_totals.setAlignment(Qt.AlignRight)
        self.label_mov_totals.setStyleSheet("""
            font-size: 16px; font-weight: bold; color: #3a86ff;
            padding: 8px 15px; background-color: #1e1e1e;
            border-radius: 8px;
        """)
        tab_transactions_layout.addWidget(self.label_mov_totals)

        tab_transactions_layout.addStretch()

        # TAB 2: GRÁFICOS (con scroll)
        tab_graphs = QWidget()
        tab_graphs_main_layout = QVBoxLayout(tab_graphs)
        tab_graphs_main_layout.setContentsMargins(0, 0, 0, 0)
        
        graphs_scroll = QScrollArea()
        graphs_scroll.setWidgetResizable(True)
        graphs_scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        graphs_scroll_content = QWidget()
        tab_graphs_layout = QVBoxLayout(graphs_scroll_content)
        tab_graphs_layout.setSpacing(30)
        tab_graphs_layout.setContentsMargins(20, 20, 20, 20)

        self.graph_container = QFrame()
        self.graph_container.setStyleSheet("background-color: #1c1c1c; border-radius: 12px; padding: 20px;")
        self.graph_layout = QVBoxLayout(self.graph_container)
        self.graph_layout.setSpacing(30)
        tab_graphs_layout.addWidget(self.graph_container)
        tab_graphs_layout.addStretch()
        
        graphs_scroll.setWidget(graphs_scroll_content)
        tab_graphs_main_layout.addWidget(graphs_scroll)

        # Agregar tabs
        self.tabs.addTab(tab_transactions, "📊 Transacciones")
        self.tabs.addTab(tab_graphs, "📈 Gráficos")

        scroll_layout.addWidget(self.tabs)

        scroll_area.setWidget(scroll_content)
        self.layout.addWidget(scroll_area)

    # ─────────────────────────────────────────────────────────
    # FIX #14: Estilo dinámico del botón PDF
    # ─────────────────────────────────────────────────────────
    def _apply_pdf_button_style(self):
        """Aplica estilo al botón PDF según su estado enabled/disabled."""
        if self.btn_export_pdf.isEnabled():
            self.btn_export_pdf.setStyleSheet("""
                QPushButton {
                    background-color: #3a86ff;
                    color: white;
                    border-radius: 10px;
                    padding: 8px;
                }
                QPushButton:hover { background-color: #2a6fd3; }
            """)
        else:
            self.btn_export_pdf.setStyleSheet("""
                QPushButton {
                    background-color: {THEME["disabled_bg"]};
                    color: {THEME["disabled_text"]};
                    border-radius: 10px;
                    padding: 8px;
                }
            """)

    def _style_table(self, table):
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setAlternatingRowColors(True)
        table.setStyleSheet("""
            QTableWidget {
                background-color: #202020;
                color: white;
                border: none;
                border-radius: 8px;
                gridline-color: #333;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:alternate {
                background-color: #252525;
            }
            QHeaderView::section {
                background-color: #333;
                color: white;
                padding: 10px;
                border: none;
                font-weight: bold;
            }
        """)

    def load_today(self):
        self.date_selector.setDate(QDate.currentDate())
        self.load_report()

    # ─────────────────────────────────────────────────────────
    # FIX #10: Spinner animado de carga
    # ─────────────────────────────────────────────────────────
    def _start_spinner(self):
        """Inicia la animación del indicador de carga."""
        self._spinner_dots = 0
        self.loading_indicator.setVisible(True)
        self.loading_indicator.setText("⏳ Cargando reporte")
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._animate_spinner)
        self._spinner_timer.start(400)

    def _animate_spinner(self):
        """Actualiza los puntos del spinner."""
        self._spinner_dots = (self._spinner_dots + 1) % 4
        dots = "." * self._spinner_dots
        self.loading_indicator.setText(f"⏳ Cargando reporte{dots}")

    def _stop_spinner(self):
        """Detiene y oculta el indicador de carga."""
        if self._spinner_timer:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self.loading_indicator.setVisible(False)

    def _set_loading_state(self, loading: bool):
        """Habilita/deshabilita botones mientras se cargan datos."""
        self.btn_load_date.setEnabled(not loading)
        self.btn_today.setEnabled(not loading)
        self.btn_export_pdf.setEnabled(False if loading else bool(self.data))
        self._apply_pdf_button_style()

        if loading:
            self.btn_load_date.setText("⏳ Cargando...")
            self._start_spinner()
        else:
            self.btn_load_date.setText("🔍 Cargar")
            self._stop_spinner()

    def _keep_worker(self, worker: QThread):
        """Mantiene referencia al worker y lo limpia al terminar."""
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        if hasattr(worker, 'error'):
            worker.error.connect(lambda: self._cleanup_worker(worker))

    def _cleanup_worker(self, worker: QThread):
        """Elimina la referencia al worker terminado."""
        try:
            self._active_workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    def load_report(self):
        try:
            selected_date = self.date_selector.date().toString("yyyy-MM-dd")
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            url = API_URL.format(date=selected_date)

            logging.debug(f"Cargando reporte para: {selected_date}")
            self._set_loading_state(True)

            worker = ReportWorker(url, headers)
            worker.finished.connect(lambda data: self._on_report_loaded(data, selected_date))
            worker.error.connect(lambda err: self._on_report_error(err, selected_date))
            self._keep_worker(worker)
            worker.start()

        except Exception as e:
            logging.error(f"Error iniciando carga de reporte: {e}")
            self._set_loading_state(False)
            self.show_no_data_message("Error al cargar el reporte")

    def _on_report_loaded(self, json_response: dict, selected_date: str):
        """Callback cuando el reporte consolidado termina de cargar."""
        try:
            if "data" in json_response:
                self.data = json_response["data"]
            else:
                self.data = json_response

            if not self.data:
                self.show_no_data_message(f"No hay datos para {selected_date}")
                self._set_loading_state(False)
                return

            self._update_status_badge()
            self.fill_summary()
            self._fill_sales_from_data()
            self._fill_movements_from_data()
            self._fill_payment_summary()           # FIX #15

            if "payment_breakdown" in self.data:
                try:
                    self.plot_payment_graphs(self.data["payment_breakdown"])
                except Exception as e:
                    logging.warning(f"⚠️ Error al generar gráficos: {e}")
                    error_label = QLabel("⚠️ Error al generar gráficos de pago")
                    error_label.setStyleSheet("font-size: 14px; color: #ff6b6b; padding: 20px;")
                    error_label.setAlignment(Qt.AlignCenter)
                    self.graph_layout.addWidget(error_label)

        except Exception as e:
            logging.error(f"Error procesando reporte: {e}")
            self.show_no_data_message("Error al procesar el reporte")
        finally:
            self._set_loading_state(False)

    def _on_report_error(self, error_msg: str, selected_date: str):
        """Callback cuando falla la carga del reporte."""
        logging.error(f"Error al cargar reporte: {error_msg}")
        self.data = None                           # FIX #14: asegurar sin datos
        self.show_no_data_message(f"No hay datos para {selected_date}")
        self._set_loading_state(False)

    # ─────────────────────────────────────────────────────────
    # FIX #7: Badge de estado de caja + closing_amount
    # ─────────────────────────────────────────────────────────
    def _update_status_badge(self):
        """Muestra un badge indicando si la caja está abierta o cerrada."""
        while self.status_container.count():
            item = self.status_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.data:
            return

        status = self.data.get("status", "unknown")
        report_date = self.data.get("date", "")

        status_frame = QFrame()
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(15, 10, 15, 10)
        status_layout.setSpacing(15)

        if status == "open":
            badge_text = "🟢 Caja Abierta"
            badge_color = THEME["accent_green"]
            border_color = THEME["accent_green"]
            extra_info = "Los valores se calculan en tiempo real"
        elif status == "closed":
            badge_text = "🔴 Caja Cerrada"
            badge_color = THEME["accent_pink"]
            border_color = THEME["accent_pink"]
            closing = self.data.get("closing_amount", 0)
            extra_info = f"Cierre registrado: ₡{closing:,.2f}"
        else:
            badge_text = "⚪ Estado desconocido"
            badge_color = THEME["text_dim"]
            border_color = THEME["text_dim"]
            extra_info = ""

        status_frame.setStyleSheet(f"""
            QFrame {{
                background-color: #1e1e1e;
                border: 2px solid {border_color};
                border-radius: 10px;
            }}
        """)

        badge_label = QLabel(badge_text)
        badge_label.setStyleSheet(f"""
            font-size: 16px; font-weight: bold; color: {badge_color};
            background: transparent; border: none;
        """)
        status_layout.addWidget(badge_label)

        date_label = QLabel(f"📅 {report_date}")
        date_label.setStyleSheet("""
            font-size: 14px; color: #aaa;
            background: transparent; border: none;
        """)
        status_layout.addWidget(date_label)

        if extra_info:
            info_label = QLabel(f"ℹ️ {extra_info}")
            info_label.setStyleSheet("""
                font-size: 13px; color: #888;
                background: transparent; border: none;
            """)
            status_layout.addWidget(info_label)

        status_layout.addStretch()
        self.status_container.addWidget(status_frame)

    # ─────────────────────────────────────────────────────────
    # FIX #11: Tabla de ventas con columna Hora
    # FIX #13: Total al pie de la tabla
    # ─────────────────────────────────────────────────────────
    def _fill_sales_from_data(self):
        """Llena la tabla de ventas desde self.data['sales']."""
        sales = self.data.get("sales", [])
        self.table_sales.setRowCount(len(sales))
        total = 0.0

        for row, s in enumerate(sales):
            # Extraer hora de created_at ("2026-03-20 14:30:05" -> "14:30")
            created = s.get("created_at", "")
            hora = ""
            if created and " " in created:
                time_part = created.split(" ")[1]
                hora = time_part[:5]  # "HH:MM"

            sale_total = float(s.get("total", 0))
            total += sale_total

            self.table_sales.setItem(row, 0, QTableWidgetItem(str(s.get("id", ""))))
            self.table_sales.setItem(row, 1, QTableWidgetItem(hora))
            self.table_sales.setItem(row, 2, QTableWidgetItem(s.get("customer", "")))
            self.table_sales.setItem(row, 3, QTableWidgetItem(s.get("payment_method", "").capitalize()))
            self.table_sales.setItem(row, 4, QTableWidgetItem(f"₡{sale_total:,.2f}"))

        # FIX #13: Mostrar total
        count = len(sales)
        self.label_sales_total.setText(
            f"📊 {count} venta{'s' if count != 1 else ''}  |  Total: ₡{total:,.2f}"
        )

    # ─────────────────────────────────────────────────────────
    # FIX #12: Tabla de movimientos con columnas Hora y Origen
    # FIX #13: Totales al pie de la tabla
    # ─────────────────────────────────────────────────────────

    # Mapeo legible de source
    _SOURCE_LABELS = {
        "SALE": "Venta",
        "SALE_CASH": "Venta (Efectivo)",
        "MANUAL": "Manual",
        "ADJUSTMENT": "Ajuste",
        "WITHDRAW": "Retiro",
        "EXPENSE": "Gasto",
        "manual": "Manual",
    }

    def _fill_movements_from_data(self):
        """Llena la tabla de movimientos desde self.data['movements']."""
        movs = self.data.get("movements", [])
        self.table_mov.setRowCount(len(movs))
        total_in = 0.0
        total_out = 0.0

        for row, m in enumerate(movs):
            tipo = m.get("type", "")
            amount = float(m.get("amount", 0))
            source_raw = m.get("source", "") or ""
            source_label = self._SOURCE_LABELS.get(source_raw, source_raw.capitalize())
            hora = m.get("time", "")

            if tipo == "Entrada":
                total_in += amount
            else:
                total_out += amount

            self.table_mov.setItem(row, 0, QTableWidgetItem(tipo))
            self.table_mov.setItem(row, 1, QTableWidgetItem(hora))
            self.table_mov.setItem(row, 2, QTableWidgetItem(f"₡{amount:,.2f}"))
            self.table_mov.setItem(row, 3, QTableWidgetItem(source_label))
            self.table_mov.setItem(row, 4, QTableWidgetItem(m.get("description", "")))

        # FIX #13: Mostrar totales
        self.label_mov_totals.setText(
            f"📥 Entradas: ₡{total_in:,.2f}   |   📤 Salidas: ₡{total_out:,.2f}   |   "
            f"Neto: ₡{total_in - total_out:,.2f}"
        )

    # ─────────────────────────────────────────────────────────
    # FIX #15: Resumen de ventas por método de pago en Transacciones
    # ─────────────────────────────────────────────────────────
    def _fill_payment_summary(self):
        """Muestra mini-cards con el desglose por método de pago."""
        # Limpiar anteriores
        while self.payment_summary_container.count():
            item = self.payment_summary_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        payment_data = self.data.get("payment_breakdown", {})
        if not payment_data:
            return

        # Título
        title_label = QLabel("💳 Desglose por Método de Pago")
        title_label.setStyleSheet("""
            font-size: 16px; font-weight: bold; color: #FFFFFF;
            padding: 8px 0px;
        """)

        # Contenedor vertical: título + cards
        wrapper = QFrame()
        wrapper.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
                border-radius: 10px;
                padding: 12px;
            }
        """)
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setSpacing(10)
        wrapper_layout.addWidget(title_label)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)

        method_colors = METHOD_COLORS

        total_all = sum(float(v) for v in payment_data.values())

        for method, amount in payment_data.items():
            amount = float(amount)
            pct = (amount / total_all * 100) if total_all > 0 else 0
            color = method_colors.get(method, "#aaa")

            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: #2A2A2A;
                    border-left: 3px solid {color};
                    border-radius: 8px;
                    padding: 10px;
                }}
                QLabel {{ color: white; }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(3)
            card_layout.setContentsMargins(8, 6, 8, 6)

            lbl_method = QLabel(method)
            lbl_method.setStyleSheet("font-size: 12px; color: #aaa;")

            lbl_amount = QLabel(f"₡{amount:,.2f}")
            lbl_amount.setStyleSheet("font-size: 16px; font-weight: bold;")

            lbl_pct = QLabel(f"{pct:.1f}%")
            lbl_pct.setStyleSheet(f"font-size: 12px; color: {color};")

            card_layout.addWidget(lbl_method)
            card_layout.addWidget(lbl_amount)
            card_layout.addWidget(lbl_pct)

            cards_row.addWidget(card)

        cards_row.addStretch()
        wrapper_layout.addLayout(cards_row)
        self.payment_summary_container.addWidget(wrapper)

    def show_no_data_message(self, message):
        # Limpiar badge de estado
        while self.status_container.count():
            item = self.status_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        while self.summary_container.count():
            item = self.summary_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # FIX #15: Limpiar payment summary
        while self.payment_summary_container.count():
            item = self.payment_summary_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.table_sales.setRowCount(0)
        self.table_mov.setRowCount(0)
        self.label_sales_total.setText("")
        self.label_mov_totals.setText("")
        self.clear_graph()
        
        msg_label = QLabel(message)
        msg_label.setStyleSheet("font-size: 18px; color: #ff6b6b; padding: 20px;")
        msg_label.setAlignment(Qt.AlignCenter)
        self.summary_container.addWidget(msg_label)

    def fill_summary(self):
        if not self.data:
            return

        while self.summary_container.count():
            item = self.summary_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        def box(title, value, color="#3a86ff"):
            frame = QFrame()
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: #2A2A2A;
                    border-left: 4px solid {color};
                    border-radius: 12px;
                    padding: 15px;
                }}
                QLabel {{
                    color: white;
                }}
            """)
            v = QVBoxLayout(frame)
            v.setSpacing(5)

            l1 = QLabel(title)
            l1.setStyleSheet("font-size: 14px; color: #aaa;")
            l2 = QLabel(f"₡{value:,.2f}")
            l2.setStyleSheet("font-size: 22px; font-weight: bold;")

            v.addWidget(l1)
            v.addWidget(l2)
            return frame

        def box_text(title, text, color="#3a86ff"):
            frame = QFrame()
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: #2A2A2A;
                    border-left: 4px solid {color};
                    border-radius: 12px;
                    padding: 15px;
                }}
                QLabel {{
                    color: white;
                }}
            """)
            v = QVBoxLayout(frame)
            v.setSpacing(5)

            l1 = QLabel(title)
            l1.setStyleSheet("font-size: 14px; color: #aaa;")
            l2 = QLabel(text)
            l2.setStyleSheet("font-size: 22px; font-weight: bold;")

            v.addWidget(l1)
            v.addWidget(l2)
            return frame

        status = self.data.get("status", "unknown")

        self.summary_container.addWidget(box("Apertura", self.data.get("opening_amount", 0), THEME["accent_green"]))
        self.summary_container.addWidget(box("Entradas", self.data.get("entries", 0), THEME["accent_blue"]))
        self.summary_container.addWidget(box("Salidas", self.data.get("exits", 0), THEME["accent_pink"]))
        self.summary_container.addWidget(box("Ventas", self.data.get("total_sales", 0), THEME["accent_purple"]))
        self.summary_container.addWidget(box("Esperado", self.data.get("expected", 0), THEME["accent_yellow"]))

        if status == "closed":
            self.summary_container.addWidget(
                box("Cierre", self.data.get("closing_amount", 0), THEME["accent_orange"])
            )

        if status == "open":
            self.summary_container.addWidget(
                box_text("Diferencia", "N/A (Abierta)", THEME["text_dim"])
            )
        else:
            diff = self.data.get("difference", 0)
            diff_color = THEME["accent_green"] if diff >= 0 else THEME["accent_pink"]
            self.summary_container.addWidget(box("Diferencia", diff, diff_color))

    def clear_graph(self):
        self._close_all_figures()

        for i in reversed(range(self.graph_layout.count())):
            widget = self.graph_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

    def _close_all_figures(self):
        import matplotlib.pyplot as plt
        for fig in self._figures:
            try:
                plt.close(fig)
            except Exception:
                pass
        self._figures.clear()

    def _cleanup_temp_charts(self):
        for path in self._temp_chart_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                logging.debug(f"No se pudo eliminar temporal {path}: {e}")
        self._temp_chart_files.clear()
        self.bar_chart_path = None
        self.pie_chart_path = None

    def plot_payment_graphs(self, payment_data):
        
        def normalize_payment_method(method: str) -> str:
            m = method.lower().strip()

            if "sinpe" in m:
                return "SINPE"
            if "efectivo" in m:
                return "Efectivo"
            if "tarjeta" in m:
                return "Tarjeta"
            if "credito" in m or "crédito" in m:
                return "Crédito"
            if "transferencia" in m:
                return "Transferencia"

            return method

        self.clear_graph()
        self._cleanup_temp_charts()

        if not payment_data:
            return
        
        normalized = {}

        for k, v in payment_data.items():
            key = normalize_payment_method(k)
            normalized[key] = normalized.get(key, 0) + float(v)

        labels = list(normalized.keys())
        values = list(normalized.values())

        if not values or sum(values) == 0:
            return

        title_label = QLabel("📊 Análisis de Métodos de Pago")
        title_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #FFFFFF; margin-bottom: 20px;")
        title_label.setAlignment(Qt.AlignCenter)
        self.graph_layout.addWidget(title_label)

        # Gráfico de barras
        fig_bar = Figure(figsize=(11, 5), facecolor="#1c1c1c")
        self._figures.append(fig_bar)
        canvas_bar = FigureCanvas(fig_bar)
        ax = fig_bar.add_subplot(111)
        fig_bar.subplots_adjust(left=0.08, right=0.95, top=0.88, bottom=0.12)

        x_pos = list(range(len(labels)))
        values = values
        
        bars = ax.bar(x_pos, values, color=THEME['accent_blue'], width=0.6, edgecolor='white', linewidth=1.5)
        
        for i, (bar, value) in enumerate(zip(bars, values)):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'₡{value:,.0f}',
                   ha='center', va='bottom', color='white', fontsize=11, fontweight='bold')
        
        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, rotation=0, ha='center', fontsize=12)
        ax.set_title("Ingresos por método de pago", color="white", fontsize=16, fontweight='bold', pad=20)
        ax.set_ylabel("Monto (₡)", color="white", fontsize=12)
        ax.tick_params(colors="white", labelsize=11)
        ax.set_facecolor("#1c1c1c")
        ax.grid(axis='y', alpha=0.2, linestyle='--', color='white')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('white')
        ax.spines['bottom'].set_color('white')

        self.graph_layout.addWidget(canvas_bar)
        self.bar_chart_path = self._save_temp_figure(fig_bar, "chart_bar.png")

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #404040; max-height: 2px; margin: 20px 0px;")
        self.graph_layout.addWidget(separator)

        # Gráfico de pastel
        fig_pie = Figure(figsize=(11, 5), facecolor="#1c1c1c")
        self._figures.append(fig_pie)
        canvas_pie = FigureCanvas(fig_pie)
        ax2 = fig_pie.add_subplot(111)
        fig_pie.subplots_adjust(left=0.05, right=0.75, top=0.88, bottom=0.08)

        labels_pie = []
        values_pie = []

        for label, value in zip(labels, values):
            if value > 0:
                labels_pie.append(str(label))
                values_pie.append(float(value))

        if not values_pie:
            return
        
        values_pie = values_pie
        colors_pie = [THEME['accent_blue'], THEME['accent_green'], THEME['accent_purple'], THEME['accent_pink'], THEME['accent_yellow']]
        
        wedges, texts, autotexts = ax2.pie(
            values_pie, 
            labels=labels_pie,
            autopct='%1.1f%%',
            startangle=90,
            colors=colors_pie[:len(values_pie)],
            textprops={'color': 'white', 'fontsize': 11}
        )
        
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
            autotext.set_fontsize(12)
            
        ax2.set_title("Distribución porcentual de pagos", color="white", fontsize=16, fontweight='bold', pad=20)

        self.graph_layout.addWidget(canvas_pie)
        self.pie_chart_path = self._save_temp_figure(fig_pie, "chart_pie.png")

    def export_pdf(self):
        if not self.data:
            QMessageBox.warning(self, "Sin datos", "No hay datos para exportar. Cargue un reporte primero.")
            return

        default_name = f"Reporte_Diario_{self.data.get('date', 'unknown')}.pdf"

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar Reporte PDF",
            default_name,
            "Archivos PDF (*.pdf)"
        )

        if not filepath:
            return

        try:
            self._generate_pdf(filepath)
            QMessageBox.information(
                self,
                "PDF Generado",
                f"El reporte se guardó correctamente en:\n{filepath}"
            )
        except Exception as e:
            logging.error(f"Error generando PDF: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo generar el PDF:\n{str(e)}"
            )

    def _generate_pdf(self, filepath: str):
        """
        FIX #16: PDF completo — espejo fiel de la pantalla.
        FIX #17: Posiciones dinámicas, sin solapamiento.
        FIX #18: SimpleDocTemplate con flujo Platypus y salto de página automático.
        FIX #19: Nombre del negocio desde configuración del backend.
        """
        # ── Datos base ──────────────────────────────────────
        status = self.data.get("status", "unknown")
        status_label = "Abierta" if status == "open" else "Cerrada"
        report_date = self.data.get("date", "N/A")
        empresa = self.data.get("empresa_nombre", "POS")
        current_year = datetime.now().year

        # ── Estilos ─────────────────────────────────────────
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name="PDFTitle", parent=styles["Heading1"],
            fontSize=18, leading=22, alignment=TA_CENTER, spaceAfter=4,
        ))
        styles.add(ParagraphStyle(
            name="SectionTitle", parent=styles["Heading2"],
            fontSize=13, leading=16, spaceBefore=14, spaceAfter=6,
            textColor=colors.HexColor("#333333"),
        ))
        styles.add(ParagraphStyle(
            name="CellText", parent=styles["Normal"],
            fontSize=9, leading=11,
        ))
        styles.add(ParagraphStyle(
            name="CellBold", parent=styles["Normal"],
            fontSize=9, leading=11, fontName="Helvetica-Bold",
        ))
        styles.add(ParagraphStyle(
            name="FooterStyle", parent=styles["Normal"],
            fontSize=8, leading=10, textColor=colors.grey, alignment=TA_CENTER,
        ))
        styles.add(ParagraphStyle(
            name="SubInfo", parent=styles["Normal"],
            fontSize=10, leading=13, textColor=colors.HexColor("#555555"),
        ))

        # ── Documento ───────────────────────────────────────
        doc = SimpleDocTemplate(
            filepath,
            pagesize=letter,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=15 * mm,
            bottomMargin=20 * mm,
            title=f"Reporte Diario - {report_date}",
        )

        story = []
        page_width = letter[0] - 36 * mm  # ancho útil

        # ── ENCABEZADO ──────────────────────────────────────
        story.append(Paragraph(f"Reporte Diario — {empresa}", styles["PDFTitle"]))
        story.append(Paragraph(
            f"Fecha: {report_date}  &nbsp;&nbsp;|&nbsp;&nbsp;  "
            f"Estado de caja: <b>{status_label}</b>",
            styles["SubInfo"],
        ))
        story.append(Spacer(1, 3 * mm))

        # ── RESUMEN DEL DÍA ────────────────────────────────
        story.append(Paragraph("Resumen del Día", styles["SectionTitle"]))

        resumen_rows = [
            [Paragraph("<b>Concepto</b>", styles["CellBold"]),
             Paragraph("<b>Monto</b>", styles["CellBold"])],
            ["Apertura",    f"₡{self.data.get('opening_amount', 0):,.2f}"],
            ["Entradas",    f"₡{self.data.get('entries', 0):,.2f}"],
            ["Salidas",     f"₡{self.data.get('exits', 0):,.2f}"],
            ["Total Ventas", f"₡{self.data.get('total_sales', 0):,.2f}"],
            ["Esperado",    f"₡{self.data.get('expected', 0):,.2f}"],
        ]
        if status == "closed":
            resumen_rows.append(["Cierre", f"₡{self.data.get('closing_amount', 0):,.2f}"])
            resumen_rows.append(["Diferencia", f"₡{self.data.get('difference', 0):,.2f}"])
        else:
            resumen_rows.append(["Diferencia", "N/A (Caja abierta)"])

        t_resumen = Table(resumen_rows, colWidths=[page_width * 0.5, page_width * 0.5])
        t_resumen.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3a86ff")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME",  (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",  (0, 0), (-1, -1), 10),
            ("ALIGN",     (1, 0), (1, -1), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f5f5f5")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f5f5f5"), colors.white]),
            ("BOX",  (0, 0), (-1, -1), 0.5, colors.grey),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
        ]))
        story.append(t_resumen)
        story.append(Spacer(1, 4 * mm))

        # ── MÉTODOS DE PAGO ─────────────────────────────────
        payment_breakdown = self.data.get("payment_breakdown", {})
        if payment_breakdown:
            story.append(Paragraph("Desglose por Método de Pago", styles["SectionTitle"]))
            pay_rows = [
                [Paragraph("<b>Método</b>", styles["CellBold"]),
                 Paragraph("<b>Monto</b>", styles["CellBold"]),
                 Paragraph("<b>%</b>", styles["CellBold"])],
            ]
            total_pay = sum(float(v) for v in payment_breakdown.values())
            for method, amount in payment_breakdown.items():
                amount = float(amount)
                pct = (amount / total_pay * 100) if total_pay > 0 else 0
                pay_rows.append([method, f"₡{amount:,.2f}", f"{pct:.1f}%"])

            pay_rows.append([
                Paragraph("<b>TOTAL</b>", styles["CellBold"]),
                Paragraph(f"<b>₡{total_pay:,.2f}</b>", styles["CellBold"]),
                "",
            ])

            t_pay = Table(pay_rows, colWidths=[page_width * 0.45, page_width * 0.35, page_width * 0.2])
            t_pay.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8338ec")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME",  (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",  (0, 0), (-1, -1), 10),
                ("ALIGN",     (1, 0), (-1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.HexColor("#f5f5f5"), colors.white]),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#8338ec")),
                ("BOX",  (0, 0), (-1, -1), 0.5, colors.grey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ]))
            story.append(t_pay)
            story.append(Spacer(1, 4 * mm))

        # ── GRÁFICOS ────────────────────────────────────────
        charts_added = False
        try:
            chart_items = []
            if self.bar_chart_path and os.path.exists(self.bar_chart_path):
                chart_items.append(RLImage(self.bar_chart_path, width=page_width, height=55 * mm))
            if self.pie_chart_path and os.path.exists(self.pie_chart_path):
                chart_items.append(Spacer(1, 3 * mm))
                chart_items.append(RLImage(self.pie_chart_path, width=page_width, height=55 * mm))
            if chart_items:
                story.append(Paragraph("Gráficos de Métodos de Pago", styles["SectionTitle"]))
                for item in chart_items:
                    story.append(item)
                story.append(Spacer(1, 4 * mm))
                charts_added = True
        except Exception as e:
            logging.error(f"Error insertando gráficos en PDF: {e}")

        # ── TABLA DE VENTAS ─────────────────────────────────
        sales = self.data.get("sales", [])
        if sales:
            story.append(Paragraph(f"Ventas del Día ({len(sales)})", styles["SectionTitle"]))

            sale_header = [
                Paragraph("<b>ID</b>", styles["CellBold"]),
                Paragraph("<b>Hora</b>", styles["CellBold"]),
                Paragraph("<b>Cliente</b>", styles["CellBold"]),
                Paragraph("<b>Método</b>", styles["CellBold"]),
                Paragraph("<b>Total</b>", styles["CellBold"]),
            ]
            sale_rows = [sale_header]
            total_ventas = 0.0

            for s in sales:
                created = s.get("created_at", "")
                hora = created.split(" ")[1][:5] if " " in created else ""
                t = float(s.get("total", 0))
                total_ventas += t
                sale_rows.append([
                    str(s.get("id", "")),
                    hora,
                    Paragraph(s.get("customer", ""), styles["CellText"]),
                    s.get("payment_method", "").capitalize(),
                    f"₡{t:,.2f}",
                ])

            # Fila de total
            sale_rows.append([
                "", "", "",
                Paragraph("<b>TOTAL</b>", styles["CellBold"]),
                Paragraph(f"<b>₡{total_ventas:,.2f}</b>", styles["CellBold"]),
            ])

            col_w = [page_width * 0.08, page_width * 0.10, page_width * 0.37,
                      page_width * 0.20, page_width * 0.25]
            t_sales = Table(sale_rows, colWidths=col_w, repeatRows=1)
            t_sales.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#06d6a0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME",  (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",  (0, 0), (-1, -1), 9),
                ("ALIGN",     (0, 0), (0, -1), "CENTER"),
                ("ALIGN",     (4, 0), (4, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f9f9f9")]),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#06d6a0")),
                ("BOX",  (0, 0), (-1, -1), 0.5, colors.grey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ]))
            story.append(t_sales)
            story.append(Spacer(1, 4 * mm))

        # ── TABLA DE MOVIMIENTOS ────────────────────────────
        movs = self.data.get("movements", [])
        if movs:
            story.append(Paragraph(f"Movimientos de Caja ({len(movs)})", styles["SectionTitle"]))

            source_labels = {
                "SALE": "Venta", "SALE_CASH": "Venta (Efectivo)",
                "MANUAL": "Manual", "ADJUSTMENT": "Ajuste",
                "WITHDRAW": "Retiro", "EXPENSE": "Gasto", "manual": "Manual",
            }
            mov_header = [
                Paragraph("<b>Tipo</b>", styles["CellBold"]),
                Paragraph("<b>Hora</b>", styles["CellBold"]),
                Paragraph("<b>Monto</b>", styles["CellBold"]),
                Paragraph("<b>Origen</b>", styles["CellBold"]),
                Paragraph("<b>Descripción</b>", styles["CellBold"]),
            ]
            mov_rows = [mov_header]
            total_in = 0.0
            total_out = 0.0

            for m in movs:
                tipo = m.get("type", "")
                amt = float(m.get("amount", 0))
                src_raw = m.get("source", "") or ""
                src = source_labels.get(src_raw, src_raw.capitalize())

                if tipo == "Entrada":
                    total_in += amt
                else:
                    total_out += amt

                mov_rows.append([
                    tipo,
                    m.get("time", ""),
                    f"₡{amt:,.2f}",
                    src,
                    Paragraph(m.get("description", ""), styles["CellText"]),
                ])

            # Fila de totales
            mov_rows.append([
                "", "",
                Paragraph(f"<b>Ent: ₡{total_in:,.2f}  |  Sal: ₡{total_out:,.2f}</b>", styles["CellBold"]),
                "",
                Paragraph(f"<b>Neto: ₡{total_in - total_out:,.2f}</b>", styles["CellBold"]),
            ])

            col_w_m = [page_width * 0.12, page_width * 0.10, page_width * 0.18,
                        page_width * 0.15, page_width * 0.45]
            t_movs = Table(mov_rows, colWidths=col_w_m, repeatRows=1)
            t_movs.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3a86ff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME",  (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",  (0, 0), (-1, -1), 9),
                ("ALIGN",     (2, 0), (2, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f9f9f9")]),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#3a86ff")),
                ("BOX",  (0, 0), (-1, -1), 0.5, colors.grey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ]))
            story.append(t_movs)
            story.append(Spacer(1, 4 * mm))

        # ── PIE DE PÁGINA (como flowable) ───────────────────
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(
            f"Generado por {empresa} © {current_year}",
            styles["FooterStyle"],
        ))

        # ── CONSTRUIR PDF ───────────────────────────────────
        doc.build(story)
        logging.debug(f"PDF generado: {filepath}")

    def _save_temp_figure(self, fig, filename):
        temp_dir = tempfile.gettempdir()
        path = os.path.join(temp_dir, f"violettepos_{filename}")
        fig.savefig(path, dpi=120, facecolor=fig.get_facecolor())
        self._temp_chart_files.append(path)
        return path

    def closeEvent(self, event):
        self._close_all_figures()
        self._cleanup_temp_charts()
        self._stop_spinner()
        for worker in self._active_workers:
            worker.quit()
            worker.wait(2000)
        super().closeEvent(event)