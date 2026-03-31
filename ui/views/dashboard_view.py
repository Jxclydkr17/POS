from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QHBoxLayout, QScrollArea
)
from PySide6.QtCore import Qt, QTimer, Signal
import traceback
import logging

from ui.session_manager import session
from ui.components.ai_insights_panel import AIInsightsPanel
from ui.components.kpi_card import KPICard
from ui.components.toast_notifier import show_toast
from ui.components.performance_chart_card import PerformanceChartCard
from ui.components.quick_actions_panel import QuickActionsPanel
from ui.components.top_list_card import TopListCard
from ui.services.dashboard_metrics_service import (
    fetch_ai_insights_today,
    fetch_dashboard_summary,
    fetch_dashboard_7d_performance,
    fetch_dashboard_top_lists,
)


# ------------------------------------
# Utils
# ------------------------------------
def _crc(amount: float) -> str:
    try:
        return f"₡{float(amount):,.2f}"
    except Exception:
        return "₡0,00"


# ------------------------------------
# Dashboard View
# ------------------------------------
class DashboardView(QWidget):
    # El MainWindow puede conectar esto para navegar
    alert_clicked = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 🎨 Fondo general (dark)
        self.setStyleSheet("""
            QWidget {
                background-color: #111827;
                color: #e5e7eb;
            }
            QLabel {
                color: #e5e7eb;
            }
        """)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll container
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("""
QScrollArea {
    border: none;
}
QScrollBar:vertical {
    background: #111827;
    width: 8px;
    margin: 4px;
}
QScrollBar::handle:vertical {
    background: #374151;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #4b5563;
}
""")

        self.main_layout.addWidget(self.scroll)

        # Contenedor interno
        self.container = QWidget()
        self.scroll.setWidget(self.container)

        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setContentsMargins(16, 16, 16, 16)
        self.content_layout.setSpacing(14)

        # --------------------------------
        # Título
        # --------------------------------
        title = QLabel("Dashboard")
        title.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
        """)
        self.content_layout.addWidget(title)

        # --------------------------------
        # KPIs
        # --------------------------------
        kpi_row_1 = QHBoxLayout()
        kpi_row_1.setSpacing(12)
        kpi_row_1.setContentsMargins(0, 0, 0, 0)

        kpi_row_2 = QHBoxLayout()
        kpi_row_2.setSpacing(12)
        kpi_row_2.setContentsMargins(0, 0, 0, 0)

        self.kpi_sales = KPICard("Ventas de hoy", "—", "Total del día")
        self.kpi_profit = KPICard("Utilidad estimada", "—", "Ventas - gastos")
        self.kpi_low_stock = KPICard("Productos críticos", "—", "Stock <= mínimo")

        self.kpi_credits = KPICard("Créditos por cobrar", "—", "Saldo pendiente")
        self.kpi_cash = KPICard("Caja actual", "—", "Esperado en caja")
        self.kpi_purchases = KPICard("Compras pendientes", "—", "Pendiente + recibido + vencido")

        kpi_row_1.addWidget(self.kpi_sales, 1)
        kpi_row_1.addWidget(self.kpi_profit, 1)
        kpi_row_1.addWidget(self.kpi_low_stock, 1)

        kpi_row_2.addWidget(self.kpi_credits, 1)
        kpi_row_2.addWidget(self.kpi_cash, 1)
        kpi_row_2.addWidget(self.kpi_purchases, 1)

        self.content_layout.addLayout(kpi_row_1)
        self.content_layout.addLayout(kpi_row_2)

        # --------------------------------
        # Gráfica + Acciones rápidas
        # --------------------------------
        chart_actions_row = QHBoxLayout()
        chart_actions_row.setSpacing(12)

        self.performance_chart = PerformanceChartCard()

        self.quick_actions = QuickActionsPanel()
        self.quick_actions.setFixedWidth(240)
        self.quick_actions.action_clicked.connect(self._handle_quick_action)

        chart_actions_row.addWidget(self.performance_chart, 3)
        chart_actions_row.addWidget(self.quick_actions, 1)

        self.content_layout.addLayout(chart_actions_row)

        # --------------------------------
        # Panel IA (dark card)
        # --------------------------------
        ai_frame = QFrame()
        ai_frame.setStyleSheet("""
            QFrame {
                background-color: #1f2933;
                border-radius: 16px;
                padding: 12px;
            }
        """)

        ai_layout = QVBoxLayout(ai_frame)
        ai_layout.setContentsMargins(10, 10, 10, 10)
        ai_layout.setSpacing(8)

        self.ai_panel = AIInsightsPanel()
        self.ai_panel.alert_clicked.connect(self._on_alert_clicked)

        ai_layout.addWidget(self.ai_panel)
        self.content_layout.addWidget(ai_frame)

        # --------------------------------
        # Top 5 útiles
        # --------------------------------
        top_row_1 = QHBoxLayout()
        top_row_1.setSpacing(12)

        top_row_2 = QHBoxLayout()
        top_row_2.setSpacing(12)

        self.top_sold_card = TopListCard("Top 5 más vendidos hoy", "Productos con mayor salida")
        self.top_risk_card = TopListCard("Top 5 en mayor riesgo", "Stock crítico / faltante")

        self.top_customers_card = TopListCard("Top 5 clientes con mayor saldo", "Mayor saldo pendiente")
        self.top_suppliers_card = TopListCard("Top 5 proveedores críticos", "Más productos en riesgo")

        top_row_1.addWidget(self.top_sold_card, 1)
        top_row_1.addWidget(self.top_risk_card, 1)

        top_row_2.addWidget(self.top_customers_card, 1)
        top_row_2.addWidget(self.top_suppliers_card, 1)

        self.content_layout.addLayout(top_row_1)
        self.content_layout.addLayout(top_row_2)

        self.content_layout.addStretch()

        # --------------------------------
        # Auto refresh (5 min)
        # --------------------------------
        self.timer = QTimer(self)
        self.timer.setInterval(5 * 60 * 1000)
        self.timer.timeout.connect(self.refresh_all)
        self.timer.start()

        # Primera carga
        self.refresh_all()

    # --------------------------------
    # Señal de navegación
    # --------------------------------
    def _on_alert_clicked(self, alert: dict):
        self.alert_clicked.emit(alert)

    # --------------------------------
    # Handler acciones rápidas
    # --------------------------------
    def _handle_quick_action(self, action: str):
        if action == "new_sale":
            self.alert_clicked.emit({"action": "go_sales"})
        elif action == "new_purchase":
            self.alert_clicked.emit({"action": "go_purchases"})
        elif action == "critical_stock":
            self.alert_clicked.emit({"action": "go_low_stock"})
        elif action == "credits":
            self.alert_clicked.emit({"action": "go_credits"})
        elif action == "close_cash":
            self.alert_clicked.emit({"action": "close_cash"})
        elif action == "refresh":
            self.refresh_all()

    # --------------------------------
    # Refresh completo
    # --------------------------------
    def refresh_all(self):
        logging.debug("\n" + "="*60)
        logging.debug("🔄 Iniciando refresh_all()...")
        logging.debug("="*60)
        
        # 1️⃣ Panel IA
        try:
            logging.debug("📊 Cargando panel de IA...")
            self.ai_panel.reload()
            logging.debug("✅ Panel IA cargado correctamente")
        except Exception as e:
            logging.error(f"❌ ERROR en Panel IA:")
            logging.error(f"   Tipo: {type(e).__name__}")
            logging.error(f"   Mensaje: {str(e)}")
            logging.debug("\n📋 Stack trace completo:")
            traceback.print_exc()
            logging.debug("="*60)
            
            show_toast(
                "No se pudieron cargar los insights de IA",
                success=False,
                parent=self
            )

        # 2️⃣ KPIs
        try:
            logging.debug("\n📈 Cargando KPIs...")
            summary = fetch_dashboard_summary()

            trends = summary.get("trends", {}) or {}

            sales_trend = trends.get("sales_today", {}) or {}
            profit_trend = trends.get("estimated_profit_today", {}) or {}
            critical_trend = trends.get("critical_products", {}) or {}
            credits_trend = trends.get("credits_receivable", {}) or {}
            cash_trend = trends.get("cash_current", {}) or {}
            purchases_trend = trends.get("pending_purchases", {}) or {}

            sales_today = float(summary.get("sales_today", 0) or 0)
            estimated_profit = float(summary.get("estimated_profit_today", 0) or 0)
            critical_products = int(summary.get("critical_products", 0) or 0)
            credits_receivable = float(summary.get("credits_receivable", 0) or 0)
            cash_current = float(summary.get("cash_current", 0) or 0)
            cash_difference = float(summary.get("cash_difference", 0) or 0)
            pending_purchases = float(summary.get("pending_purchases", 0) or 0)

            logging.debug(f"   ✓ Ventas de hoy: ₡{sales_today:,.2f}")
            logging.debug(f"   ✓ Utilidad estimada: ₡{estimated_profit:,.2f}")
            logging.debug(f"   ✓ Productos críticos: {critical_products}")
            logging.debug(f"   ✓ Créditos por cobrar: ₡{credits_receivable:,.2f}")
            logging.debug(f"   ✓ Caja actual: ₡{cash_current:,.2f}")
            logging.debug(f"   ✓ Diferencia caja: ₡{cash_difference:,.2f}")
            logging.debug(f"   ✓ Compras pendientes: ₡{pending_purchases:,.2f}")

            self.kpi_sales.set_value(
                _crc(sales_today),
                "Total del día",
                trend_text=sales_trend.get("text", ""),
                trend_type=sales_trend.get("type", "neutral")
            )
            self.kpi_profit.set_value(
                _crc(estimated_profit),
                "Ventas - gastos",
                trend_text=profit_trend.get("text", ""),
                trend_type=profit_trend.get("type", "neutral")
            )
            self.kpi_low_stock.set_value(
                str(critical_products),
                "Stock <= mínimo",
                trend_text=critical_trend.get("text", ""),
                trend_type=critical_trend.get("type", "neutral")
            )
            self.kpi_credits.set_value(
                _crc(credits_receivable),
                "Saldo pendiente",
                trend_text=credits_trend.get("text", ""),
                trend_type=credits_trend.get("type", "neutral")
            )
            self.kpi_cash.set_value(
                _crc(cash_current),
                f"Diferencia: {_crc(cash_difference)}",
                trend_text=cash_trend.get("text", ""),
                trend_type=cash_trend.get("type", "neutral")
            )
            self.kpi_purchases.set_value(
                _crc(pending_purchases),
                "Pendiente + recibido + vencido",
                trend_text=purchases_trend.get("text", ""),
                trend_type=purchases_trend.get("type", "neutral")
            )

            logging.debug("✅ KPIs actualizados correctamente")

        except Exception as e:
            logging.error(f"❌ ERROR en KPIs:")
            logging.error(f"   Tipo: {type(e).__name__}")
            logging.error(f"   Mensaje: {str(e)}")
            logging.debug("\n📋 Stack trace completo:")
            traceback.print_exc()
            logging.debug("="*60)
            
            # No romper dashboard
            self.kpi_sales.set_value("—", "Sin datos")
            self.kpi_profit.set_value("—", "Sin datos")
            self.kpi_low_stock.set_value("—", "Sin datos")
            self.kpi_credits.set_value("—", "Sin datos")
            self.kpi_cash.set_value("—", "Sin datos")
            self.kpi_purchases.set_value("—", "Sin datos")

            show_toast(
                "No se pudieron actualizar los KPIs",
                success=False,
                parent=self
            )

        # 3️⃣ Gráfica últimos 7 días
        try:
            logging.debug("\n📉 Cargando gráfica de rendimiento 7 días...")
            performance_data = fetch_dashboard_7d_performance()
            chart_data = performance_data.get("chart_data", []) if isinstance(performance_data, dict) else []
            self.performance_chart.set_chart_data(chart_data)
            logging.debug("✅ Gráfica cargada correctamente")
        except Exception as e:
            logging.error("❌ ERROR en gráfica 7 días:")
            logging.error(f"   Tipo: {type(e).__name__}")
            logging.error(f"   Mensaje: {str(e)}")
            traceback.print_exc()
            self.performance_chart.chart_label.setText("No se pudo cargar la gráfica.")

        # 4️⃣ Top lists
        try:
            logging.debug("\n🏆 Cargando top lists...")
            top_data = fetch_dashboard_top_lists()

            sold_items = [
                {
                    "name": item.get("name", "—"),
                    "value": item.get("severity", f"{int(float(item.get('quantity', 0) or 0))} uds"),
                    "detail": f"Venta: {_crc(float(item.get('amount', 0) or 0))}"
                }
                for item in top_data.get("top_sold_products_today", [])
            ]

            risk_items = [
                {
                    "name": item.get("name", "—"),
                    "value": item.get("severity", "Riesgo"),
                    "detail": f"Stock: {int(float(item.get('stock', 0) or 0))} / Mín: {int(float(item.get('min_stock', 0) or 0))}"
                }
                for item in top_data.get("top_risk_products", [])
            ]

            customer_items = [
                {
                    "name": item.get("name", "—"),
                    "value": _crc(float(item.get("credit_balance", 0) or 0)),
                    "detail": f"Límite: {_crc(float(item.get('credit_limit', 0) or 0))}"
                }
                for item in top_data.get("top_customers_with_balance", [])
            ]

            supplier_items = [
                {
                    "name": item.get("name", "—"),
                    "value": f"{int(item.get('critical_products', 0) or 0)} críticos",
                    "detail": "Proveedor con productos en stock crítico"
                }
                for item in top_data.get("top_suppliers_with_critical_products", [])
            ]

            self.top_sold_card.set_items(sold_items, empty_text="No hay ventas hoy.")
            self.top_risk_card.set_items(risk_items, empty_text="No hay productos en riesgo.")
            self.top_customers_card.set_items(customer_items, empty_text="No hay saldos pendientes.")
            self.top_suppliers_card.set_items(supplier_items, empty_text="No hay proveedores críticos.")

            logging.debug("✅ Top lists cargadas correctamente")

        except Exception as e:
            logging.error("❌ ERROR en top lists:")
            logging.error(f"   Tipo: {type(e).__name__}")
            logging.error(f"   Mensaje: {str(e)}")
            traceback.print_exc()

            self.top_sold_card.set_items([], empty_text="No se pudo cargar.")
            self.top_risk_card.set_items([], empty_text="No se pudo cargar.")
            self.top_customers_card.set_items([], empty_text="No se pudo cargar.")
            self.top_suppliers_card.set_items([], empty_text="No se pudo cargar.")
        
        logging.debug("\n" + "="*60)
        logging.debug("✅ refresh_all() completado")
        logging.debug("="*60 + "\n")