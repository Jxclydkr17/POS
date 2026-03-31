from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame,
    QPushButton, QHBoxLayout, QGridLayout, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
import traceback

from ui.services.dashboard_metrics_service import fetch_ai_insights_today
from ui.components.toast_notifier import show_toast
import logging


LEVEL_STYLES = {
    "info": "#2d8cf0",
    "warning": "#f0ad4e",
    "critical": "#d9534f"
}

SECTION_TITLES = {
    "sales":    "📈 Ventas",
    "stock":    "📦 Stock",
    "credit":   "💳 Créditos",
    "supplier": "🏭 Proveedores",
    "kpi":      "📊 KPIs / Ranking",
    "cash":     "💰 Caja",
    "other":    "📋 Otras",
}

SECTION_ORDER = ["stock", "credit", "cash", "supplier", "sales", "kpi", "other"]


class ClickableFrame(QFrame):
    clicked = Signal(dict)

    def __init__(self, alert: dict, parent=None):
        super().__init__(parent)
        self._alert = alert
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        self.clicked.emit(self._alert)
        super().mousePressEvent(event)


class AIInsightsPanel(QWidget):
    alert_clicked = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(10)
        self.setMinimumHeight(420)
        self.setMaximumHeight(520)

        # -----------------------------
        # Header
        # -----------------------------
        header = QHBoxLayout()

        self.title = QLabel("🧠 Inteligencia del Día")
        self.title.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #e5e7eb;
        """)
        header.addWidget(self.title)

        header.addStretch()

        self.btn_refresh = QPushButton("Refrescar")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
                border-radius: 8px;
                background-color: #374151;
                color: #e5e7eb;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
        """)
        self.btn_refresh.clicked.connect(self.reload)
        header.addWidget(self.btn_refresh)

        self.layout().addLayout(header)

        # -----------------------------
        # Summary
        # -----------------------------
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("""
            color: #9ca3af;
            margin-bottom: 6px;
        """)
        self.layout().addWidget(self.summary_label)

        self.toggle_btn = QPushButton("Ver todas")
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
                border-radius: 8px;
                background-color: #1f2937;
                color: #d1d5db;
                border: 1px solid #374151;
            }
            QPushButton:hover {
                background-color: #374151;
                color: #ffffff;
            }
        """)
        self.toggle_btn.clicked.connect(self._toggle_show_all)
        self.toggle_btn.hide()
        self.layout().addWidget(self.toggle_btn)

        # -----------------------------
        # Alerts container con scroll interno
        # -----------------------------
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: #111827;
                width: 8px;
                margin: 4px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #374151;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4b5563;
            }
        """)

        self.container = QWidget()
        self.container.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)

        self.container.setLayout(QVBoxLayout())
        self.container.layout().setSpacing(8)
        self.container.layout().setContentsMargins(2, 2, 2, 2)

        self.scroll_area.setWidget(self.container)
        self.layout().addWidget(self.scroll_area, 1)

        self.show_all_alerts = False
        self.priority_limit = 5
        self._all_alerts = []

        self.reload()

    # ─────────────────────────────────────────
    # PASO 1 — Clasificar alerta en sección
    # ─────────────────────────────────────────
    def _get_section_key(self, alert: dict) -> str:
        alert_type = alert.get("type")
        return alert_type if alert_type in SECTION_TITLES else "other"

    # ─────────────────────────────────────────
    # PASO 4 — Toggle ver todas / ver menos
    # ─────────────────────────────────────────
    def _toggle_show_all(self):
        self.show_all_alerts = not self.show_all_alerts
        self._render_alerts(self._all_alerts)

    # ─────────────────────────────────────────
    # PASO 5 — Render con prioridad + expansión
    # ─────────────────────────────────────────
    def _render_alerts(self, alerts: list[dict]):
        self._clear_alerts()

        if not alerts:
            empty = QLabel("✅ Todo se ve estable hoy.\nNo hay alertas importantes.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("""
                color: #9ca3af;
                font-size: 14px;
                padding: 24px;
            """)
            self.container.layout().addStretch()
            self.container.layout().addWidget(empty)
            self.container.layout().addStretch()
            self.toggle_btn.hide()
            return

        priority_alerts = alerts[:self.priority_limit]
        secondary_alerts = alerts[self.priority_limit:]

        # Botón ver todas / ver menos
        if secondary_alerts:
            self.toggle_btn.show()
            self.toggle_btn.setText("Ver menos" if self.show_all_alerts else f"Ver todas ({len(alerts)})")
        else:
            self.toggle_btn.hide()

        # 1) Bloque principal: alertas prioritarias
        priority_block = self._create_section_block(
            f"🔥 Prioritarias ({len(priority_alerts)})",
            priority_alerts
        )
        self.container.layout().addWidget(priority_block)

        # 2) Bloques secundarios
        if self.show_all_alerts and secondary_alerts:
            grouped: dict[str, list[dict]] = {key: [] for key in SECTION_ORDER}

            for alert in secondary_alerts:
                key = self._get_section_key(alert)
                grouped.setdefault(key, []).append(alert)

            for section_key in SECTION_ORDER:
                section_alerts = grouped.get(section_key, [])
                if not section_alerts:
                    continue

                title = SECTION_TITLES.get(section_key, section_key)
                section_block = self._create_section_block(title, section_alerts)
                self.container.layout().addWidget(section_block)

        self.container.layout().addStretch()

    # ─────────────────────────────────────────
    # PASO 5 — Decidir label del CTA según alerta
    # ─────────────────────────────────────────
    def _get_primary_action_label(self, alert: dict) -> str:
        alert_type = alert.get("type")
        meta = alert.get("meta", {}) or {}

        if alert_type == "stock":
            return "Ver stock bajo"

        if alert_type == "credit":
            return "Ver créditos"

        if alert_type == "cash":
            return "Ver caja"

        if alert_type == "sales":
            return "Ver ventas"

        if alert_type == "supplier":
            action = meta.get("action", "")
            if action == "open_supplier_products":
                return "Reabastecer"
            if action == "open_supplier_purchases":
                return "Ver compras"
            return "Ir a proveedor"

        if alert_type == "kpi":
            action = meta.get("action", "")
            if action == "open_credit_ranking":
                return "Ver créditos"
            return "Ver KPI"

        return "Ver detalle"

    # ─────────────────────────────────────────
    # PASO 3 — Renderer de líneas compactas
    # ─────────────────────────────────────────
    def _build_compact_lines(self, alert: dict) -> list[str]:
        """Devuelve líneas cortas de detalle según tipo de alerta."""
        alert_type = alert.get("type")
        meta = alert.get("meta", {}) or {}
        lines = []

        if alert_type == "stock":
            if meta.get("coverage_days") is not None:
                lines.append(f"Cobertura: {meta['coverage_days']} días")
            elif meta.get("current_stock") is not None:
                lines.append(f"Stock actual: {meta['current_stock']}")

            if meta.get("lost_revenue") is not None:
                lines.append(f"Impacto estimado: ₡{meta['lost_revenue']:,.0f}")

            if meta.get("suggested_qty") is not None and meta.get("suggested_qty") > 0:
                lines.append(f"Sugerencia: comprar {meta['suggested_qty']} uds")

        elif alert_type == "sales":
            if meta.get("predicted_today") is not None and meta.get("today_sales") is not None:
                lines.append(f"Esperado hoy: ₡{meta['predicted_today']:,.0f}")
                lines.append(f"Actual: ₡{meta['today_sales']:,.0f}")

            if meta.get("drop_pct_vs_pred") is not None:
                lines.append(f"Desviación: -{meta['drop_pct_vs_pred']}%")
            elif meta.get("drop_pct_vs_avg") is not None:
                lines.append(f"Desviación: -{meta['drop_pct_vs_avg']}%")

            if meta.get("forecast_avg") is not None:
                lines.append(f"Promedio esperado: ₡{meta['forecast_avg']:,.0f}")

            if meta.get("trend_pct") is not None:
                trend = meta["trend_pct"]
                sign = "+" if trend > 0 else ""
                lines.append(f"Tendencia: {sign}{trend}%")

        elif alert_type == "credit":
            if meta.get("credit_balance") is not None:
                lines.append(f"Saldo pendiente: ₡{meta['credit_balance']:,.0f}")

            if meta.get("usage_percent") is not None:
                lines.append(f"Uso del crédito: {meta['usage_percent']:.1f}%")

            if meta.get("credit_limit") is not None:
                lines.append(f"Límite: ₡{meta['credit_limit']:,.0f}")

        elif alert_type == "supplier":
            if meta.get("critical_count") is not None:
                lines.append(f"Productos críticos: {meta['critical_count']}")

            if meta.get("days") is not None:
                lines.append(f"Días sin comprar: {meta['days']}")

            if meta.get("last_purchase_date"):
                lines.append(f"Última compra: {meta['last_purchase_date']}")

        elif alert_type == "cash":
            if meta.get("balance") is not None:
                lines.append(f"Diferencia: ₡{abs(meta['balance']):,.0f}")

        limit = 4 if alert.get("level") == "critical" else 3
        return lines[:limit]

    # ─────────────────────────────────────────
    # Utils
    # ─────────────────────────────────────────
    def _clear_alerts(self):
        lay = self.container.layout()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    # ─────────────────────────────────────────
    # PASO 2 — Agrupar + PASO 3 — Secciones
    # ─────────────────────────────────────────
    def reload(self):
        logging.debug("\n" + "─"*50)
        logging.debug("🧠 AIInsightsPanel.reload() iniciado...")
        logging.debug("─"*50)

        self.btn_refresh.setEnabled(False)
        self._clear_alerts()

        try:
            logging.debug("📡 Llamando a fetch_ai_insights_today()...")
            data = fetch_ai_insights_today()
            logging.debug(f"✅ Respuesta recibida: {type(data)}")

            if not isinstance(data, dict):
                logging.error(f"❌ ERROR: Respuesta no es dict, es {type(data)}")
                raise ValueError("Respuesta inválida de insights")

            summary = data.get("summary") or "Sin resumen disponible"
            alerts = data.get("alerts") or []

            logging.debug(f"📊 Summary: {summary}")
            logging.debug(f"📊 Alertas: {len(alerts)}")

            self.summary_label.setText(summary)

            if not alerts:
                logging.debug("ℹ️  No hay alertas, mostrando mensaje vacío")

            self._all_alerts = alerts
            logging.debug("🎨 Renderizando panel con prioridad + expansión...")
            self._render_alerts(alerts)
            logging.debug("✅ Panel renderizado")

        except Exception as e:
            logging.error(f"❌ ERROR en reload():")
            logging.error(f"   Tipo: {type(e).__name__}")
            logging.error(f"   Mensaje: {str(e)}")
            logging.debug("\n📋 Stack trace completo:")
            traceback.print_exc()
            logging.debug("─"*50)

            self._clear_alerts()
            self.summary_label.setText("Sin información de IA disponible por ahora.")

            show_toast(
                f"Error: {str(e)}",
                success=False,
                parent=self
            )

        finally:
            self.btn_refresh.setEnabled(True)
            logging.debug("─"*50)
            logging.debug("🏁 AIInsightsPanel.reload() finalizado\n")

    # ─────────────────────────────────────────
    # PASO 3 — Widget de sección reutilizable
    # ─────────────────────────────────────────
    def _create_section_block(self, title: str, alerts: list[dict]) -> QFrame:
        block = QFrame()
        block.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        block.setStyleSheet("""
            QFrame {
                background-color: #161d2b;
                border: 1px solid #1f2937;
                border-radius: 14px;
            }
        """)

        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(10, 10, 10, 10)
        block_layout.setSpacing(6)

        # Encabezado de sección con contador
        header_row = QHBoxLayout()

        section_title = QLabel(f"{title}")
        section_title.setStyleSheet("""
            font-size: 12px;
            font-weight: bold;
            color: #9ca3af;
            letter-spacing: 0.5px;
        """)
        header_row.addWidget(section_title)

        header_row.addStretch()

        count_label = QLabel(f"{len(alerts)}")
        count_label.setStyleSheet("""
            font-size: 11px;
            color: #6b7280;
            background-color: #1f2937;
            border-radius: 8px;
            padding: 1px 7px;
        """)
        header_row.addWidget(count_label)

        block_layout.addLayout(header_row)

        # Cards dentro de la sección
        for alert in alerts:
            if alert.get("type") == "kpi":
                card = self._create_kpi_card(alert)
            else:
                card = self._create_alert_card(alert)
            block_layout.addWidget(card)

        return block

    # ─────────────────────────────────────────
    # PASO 4 + 6 + 7 + 8 — Alert card mejorada
    # ─────────────────────────────────────────
    def _create_alert_card(self, alert: dict) -> QFrame:
        # PASO 7: QFrame normal (no ClickableFrame como principal)
        frame = QFrame()
        frame.setMinimumHeight(96)
        color = LEVEL_STYLES.get(alert.get("level"), "#6b7280")

        frame.setStyleSheet(f"""
            QFrame {{
                border-left: 4px solid {color};
                background-color: #111827;
                border-radius: 10px;
            }}
            QFrame:hover {{
                background-color: #1a2236;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        # PASO 4: Zona principal — mensaje
        msg = QLabel(alert.get("message", ""))
        msg.setWordWrap(True)
        msg.setStyleSheet("""
            font-size: 13px;
            font-weight: 600;
            color: #f3f4f6;
        """)
        layout.addWidget(msg)

        # PASO 4: Líneas de detalle apiladas
        detail_lines = self._build_compact_lines(alert)
        if detail_lines:
            details_wrap = QVBoxLayout()
            details_wrap.setContentsMargins(0, 2, 0, 0)
            details_wrap.setSpacing(2)

            for line in detail_lines:
                line_label = QLabel(line)
                line_label.setWordWrap(True)
                line_label.setStyleSheet("""
                    font-size: 11px;
                    color: #9ca3af;
                """)
                details_wrap.addWidget(line_label)

            layout.addLayout(details_wrap)

        # PASO 4 + 6: Barra inferior de acciones
        action_label = self._get_primary_action_label(alert)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 6, 0, 0)
        actions_row.addStretch()

        btn = QPushButton(action_label)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                padding: 4px 12px;
                border-radius: 6px;
                background-color: #1f2937;
                color: {color};
                font-size: 12px;
                border: 1px solid {color};
            }}
            QPushButton:hover {{
                background-color: {color};
                color: #111827;
            }}
        """)
        # PASO 6: botón emite la misma señal que el flujo existente
        btn.clicked.connect(lambda _, a=alert: self.alert_clicked.emit(a))
        actions_row.addWidget(btn)

        layout.addLayout(actions_row)

        return frame

    # ─────────────────────────────────────────
    # PASO 6 — Resumen compacto para KPI cards
    # ─────────────────────────────────────────
    def _build_kpi_summary_lines(self, kpi: dict) -> list[str]:
        meta = kpi.get("meta", {}) or {}
        items = meta.get("items", []) or []

        if not items:
            return []

        usages = [float(i.get("usage_percent", 0) or 0) for i in items]
        max_usage = max(usages) if usages else 0
        avg_usage = sum(usages) / len(usages) if usages else 0

        return [
            f"Clientes evaluados: {len(items)}",
            f"Máximo uso: {max_usage:.1f}%",
            f"Promedio top {len(items)}: {avg_usage:.1f}%",
        ]

    # ─────────────────────────────────────────
    # PASO 9 — KPI card con acción
    # ─────────────────────────────────────────
    def _create_kpi_card(self, kpi: dict) -> QFrame:
        """Renderiza un KPI con tabla/grid y botón de acción."""
        frame = QFrame()
        frame.setMinimumHeight(140)
        frame.setStyleSheet("""
            QFrame {
                border-left: 4px solid #10b981;
                background-color: #1a1f2e;
                border-radius: 10px;
            }
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Título del KPI
        title = QLabel(f"📊 {kpi.get('message', 'KPI')}")
        title.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: #10b981;
        """)
        layout.addWidget(title)

        # PASO 6: Resumen compacto con métricas clave
        summary_lines = self._build_kpi_summary_lines(kpi)
        if summary_lines:
            summary_wrap = QVBoxLayout()
            summary_wrap.setSpacing(2)
            summary_wrap.setContentsMargins(0, 0, 0, 4)

            for line in summary_lines:
                lbl = QLabel(line)
                lbl.setStyleSheet("""
                    color: #9ca3af;
                    font-size: 11px;
                """)
                summary_wrap.addWidget(lbl)

            layout.addLayout(summary_wrap)

        # Descripción (si existe en meta)
        meta = kpi.get("meta", {}) or {}
        description = meta.get("description", "")

        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("""
                color: #9ca3af;
                font-size: 12px;
                margin-bottom: 4px;
            """)
            layout.addWidget(desc_label)

        # Items — tabla de datos
        items = meta.get("items", [])

        if items:
            grid = QGridLayout()
            grid.setSpacing(8)
            grid.setContentsMargins(0, 8, 0, 0)

            headers = ["#", "Cliente", "Uso", "Saldo", "Límite"]
            for col, header in enumerate(headers):
                label = QLabel(header)
                label.setStyleSheet("""
                    font-weight: bold;
                    color: #6b7280;
                    font-size: 11px;
                """)
                grid.addWidget(label, 0, col)

            for row, item in enumerate(items, start=1):
                num = QLabel(str(row))
                num.setStyleSheet("color: #9ca3af; font-size: 12px;")
                grid.addWidget(num, row, 0)

                customer_name = QLabel(item.get("customer_name", "N/A"))
                customer_name.setStyleSheet("color: #e5e7eb; font-size: 12px;")
                customer_name.setWordWrap(True)
                grid.addWidget(customer_name, row, 1)

                usage = item.get("usage_percent", 0)
                usage_label = QLabel(f"{usage:.1f}%")
                if usage >= 90:
                    u_color = "#ef4444"
                elif usage >= 70:
                    u_color = "#f59e0b"
                else:
                    u_color = "#10b981"
                usage_label.setStyleSheet(f"color: {u_color}; font-weight: bold; font-size: 12px;")
                grid.addWidget(usage_label, row, 2)

                balance = item.get("credit_balance", 0)
                balance_label = QLabel(f"₡{balance:,.0f}")
                balance_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
                grid.addWidget(balance_label, row, 3)

                limit = item.get("credit_limit", 0)
                limit_label = QLabel(f"₡{limit:,.0f}")
                limit_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
                grid.addWidget(limit_label, row, 4)

            grid.setColumnStretch(1, 2)
            layout.addLayout(grid)
        else:
            no_data = QLabel("Sin datos disponibles")
            no_data.setStyleSheet("color: #6b7280; font-style: italic; font-size: 12px;")
            layout.addWidget(no_data)

        # PASO 9: botón de acción contextual para KPIs
        action_label = self._get_primary_action_label(kpi)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 4, 0, 0)
        actions_row.addStretch()

        btn = QPushButton(action_label)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                padding: 4px 12px;
                border-radius: 6px;
                background-color: #1f2937;
                color: #10b981;
                font-size: 12px;
                border: 1px solid #10b981;
            }
            QPushButton:hover {
                background-color: #10b981;
                color: #111827;
            }
        """)
        btn.clicked.connect(lambda _, a=kpi: self.alert_clicked.emit(a))
        actions_row.addWidget(btn)

        layout.addLayout(actions_row)

        return frame