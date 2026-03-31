import os
import requests
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QMessageBox, QAbstractItemView,
    QLineEdit, QFrame, QScrollArea
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject
from PySide6.QtGui import QColor

from ui.session_manager import session
from ui.dialogs.add_supplier_dialog import AddSupplierDialog
from ui.dialogs.edit_supplier_dialog import EditSupplierDialog
from ui.api import BASE_URL

# Ruta al stylesheet compartido
_STYLES_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "styles.qss")

API_SUPPLIERS = f"{BASE_URL}/suppliers"


# ----------------------------------------------------------
# #11  Worker hilo para fetch_recent_purchases (no bloquea UI)
# ----------------------------------------------------------
class _RecentPurchasesWorker(QObject):
    finished = Signal(list)

    def __init__(self, supplier_id: int, limit: int = 5):
        super().__init__()
        self.supplier_id = supplier_id
        self.limit = limit

    def run(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            resp = requests.get(
                f"{BASE_URL}/purchases/recent",
                params={"supplier_id": self.supplier_id, "limit": self.limit},
                headers=headers,
                timeout=6,
            )
            if resp.status_code != 200:
                self.finished.emit([])
                return

            payload = resp.json()
            data = payload.get("data", payload) if isinstance(payload, dict) else payload
            self.finished.emit(data if isinstance(data, list) else [])
        except Exception:
            self.finished.emit([])


class SuppliersView(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.suppliers = []
        self.all_suppliers = []
        self.filtered_suppliers = []
        self._purchase_thread = None
        self._purchase_worker = None

        self.setup_ui()
        self.load_suppliers()

    # --------------------------------------------------------
    # 🧠 INTERFAZ PRINCIPAL
    # --------------------------------------------------------
    def setup_ui(self):
        # Cargar stylesheet compartido (#12)
        try:
            with open(_STYLES_PATH, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        except FileNotFoundError:
            pass

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)

        # Título
        title = QLabel("📦 Lista de Proveedores")
        title.setObjectName("suppliersTitle")
        layout.addWidget(title)

        # 🔎 Buscador
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar por nombre, email, teléfono, contacto, dirección...")
        self.search_input.textChanged.connect(self.apply_filter)
        self.search_input.setObjectName("suppliersSearch")
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # --------------------------------------------------------
        # 🧾 Tabla
        # --------------------------------------------------------
        self.table = QTableWidget()
        self.table.setColumnCount(15)
        self.table.setHorizontalHeaderLabels([
            "ID", "Nombre", "Teléfono", "Email", "Dirección", "Notas",
            "Productos", "Críticos", "Compras", "Total comprado", "Última compra",
            "⏳ Días sin comprar", "Estado", "Score", "Dependencia"
        ])
        # Ocultar columna ID (solo uso interno)
        self.table.setColumnHidden(0, True)

        score_header = self.table.horizontalHeaderItem(13)
        if score_header:
            score_header.setToolTip(
                "Score 0–100 basado en:\n"
                "• Frecuencia de compras (40%)\n"
                "• Rotación de productos (40%)\n"
                "• Cumplimiento de stock (20%)\n\n"
                "🟢 80-100 excelente\n"
                "🟡 60-79 bueno\n"
                "🔴 <60 revisar"
            )
        dep_header = self.table.horizontalHeaderItem(14)
        if dep_header:
            dep_header.setToolTip(
                "📌 % de productos del catálogo que pertenecen a este proveedor.\n"
                "⚠ Valores > 40% indican dependencia alta."
            )

        self.table.horizontalHeader().setStretchLastSection(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, header.ResizeMode.ResizeToContents)  # ID
        header.setSectionResizeMode(1, header.ResizeMode.Stretch)           # Nombre
        header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)  # Teléfono
        header.setSectionResizeMode(3, header.ResizeMode.Stretch)           # Email
        header.setSectionResizeMode(4, header.ResizeMode.Stretch)           # Dirección
        header.setSectionResizeMode(5, header.ResizeMode.Stretch)           # Notas
        header.setSectionResizeMode(6, header.ResizeMode.ResizeToContents)  # Productos
        header.setSectionResizeMode(7, header.ResizeMode.ResizeToContents)  # Críticos
        header.setSectionResizeMode(8, header.ResizeMode.ResizeToContents)  # Compras
        header.setSectionResizeMode(9, header.ResizeMode.ResizeToContents)  # Total comprado
        header.setSectionResizeMode(10, header.ResizeMode.ResizeToContents) # Última compra
        header.setSectionResizeMode(11, header.ResizeMode.ResizeToContents) # Días sin comprar
        header.setSectionResizeMode(12, header.ResizeMode.ResizeToContents) # Estado
        header.setSectionResizeMode(13, header.ResizeMode.ResizeToContents) # Score
        header.setSectionResizeMode(14, header.ResizeMode.ResizeToContents) # Dependencia

        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setObjectName("suppliersTable")
        self.table.doubleClicked.connect(self.open_products_view)

        # --------------------------------------------------------
        # 🎛 Barra de acciones inferior (estilo ProductsView)
        # --------------------------------------------------------
        actions_layout = QHBoxLayout()

        def _action_btn(text, color, slot, min_w=120, hover="#4B4B4B"):
            """Crea un QPushButton — estilos base en styles.qss, solo bg-color inline."""
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            btn.setObjectName("actionBtn")
            btn.setMinimumWidth(min_w)
            btn.setStyleSheet(f"""
                QPushButton#actionBtn {{
                    background-color: {color};
                    color: white;
                    font-weight: bold;
                    padding: 8px;
                    border-radius: 8px;
                }}
                QPushButton#actionBtn:hover {{
                    background-color: {hover};
                }}
            """)
            return btn

        btn_refresh   = _action_btn("🔄 Actualizar",        "#2D9CDB", self.load_suppliers)
        btn_add       = _action_btn("➕ Agregar",            "#27AE60", self.open_add_dialog)
        btn_edit      = _action_btn("✏️ Editar",             "#F2C94C", self.open_edit_dialog)
        btn_delete    = _action_btn("🗑 Eliminar",           "#EB5757", self.delete_supplier)
        btn_view_prod = _action_btn("👁 Productos",          "#9B51E0", self.open_products_view)
        btn_restock   = _action_btn("📦 Reabastecer",        "#1ABC9C", self.open_restock_view, min_w=140)
        btn_purchases = _action_btn("🧾 Compras",            "#E67E22", self.open_purchases_view)
        btn_toggle    = _action_btn("✅ Activar/Desactivar", "#4B4B4B", self.toggle_supplier_status, min_w=160, hover="#6B6B6B")

        actions_layout.addWidget(btn_refresh)
        actions_layout.addWidget(btn_add)
        actions_layout.addWidget(btn_edit)
        actions_layout.addWidget(btn_delete)
        actions_layout.addWidget(btn_view_prod)
        actions_layout.addWidget(btn_restock)
        actions_layout.addWidget(btn_purchases)
        actions_layout.addWidget(btn_toggle)

        # --------------------------------------------------------
        # 🗂 Layout de 2 columnas: tabla+acciones | panel lateral
        # --------------------------------------------------------
        content_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()
        content_layout.addLayout(left_layout, 3)
        content_layout.addLayout(right_layout, 1)

        left_layout.addWidget(self.table)
        left_layout.addLayout(actions_layout)

        layout.addLayout(content_layout)

        # --------------------------------------------------------
        # 📌 Panel lateral de detalles
        # --------------------------------------------------------
        self.details_panel = QFrame()
        self.details_panel.setObjectName("SupplierDetailsPanel")
        self.details_panel.setMinimumWidth(260)

        panel_layout = QVBoxLayout(self.details_panel)
        panel_layout.setAlignment(Qt.AlignTop)

        panel_title = QLabel("📌 Detalles del proveedor")
        panel_title.setObjectName("panelTitle")
        panel_layout.addWidget(panel_title)

        self.lbl_name = QLabel("—")
        self.lbl_name.setObjectName("supplierName")
        panel_layout.addWidget(self.lbl_name)

        self.lbl_products = QLabel("📦 Total productos: —")
        self.lbl_critical = QLabel("📉 Críticos: —")
        self.lbl_last_purchase = QLabel("📅 Última compra: —")
        self.lbl_total_purchased = QLabel("💰 Total comprado: —")

        for lbl in (self.lbl_products, self.lbl_critical, self.lbl_last_purchase, self.lbl_total_purchased):
            lbl.setObjectName("metricLabel")
            panel_layout.addWidget(lbl)

        self.lbl_score = QLabel("⭐ Score: —")
        self.lbl_score.setObjectName("supplierScore")
        panel_layout.addWidget(self.lbl_score)

        self.lbl_avg_purchase_gap = QLabel("📈 Promedio compra: —")
        self.lbl_avg_purchase_gap.setObjectName("avgPurchaseGap")
        panel_layout.addWidget(self.lbl_avg_purchase_gap)

        # --------------------------------------------------------
        # 📦 Últimas compras (panel lateral)
        # --------------------------------------------------------
        recent_title = QLabel("📦 Últimas compras")
        recent_title.setObjectName("sectionTitle")
        panel_layout.addWidget(recent_title)

        self.recent_purchase_labels = []
        for _ in range(5):
            lbl = QLabel("—")
            lbl.setObjectName("recentPurchaseLabel")
            panel_layout.addWidget(lbl)
            self.recent_purchase_labels.append(lbl)

        # Separador contacto
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("panelSeparator")
        panel_layout.addWidget(sep)

        contact_title = QLabel("🤝 Contacto")
        contact_title.setObjectName("contactTitle")
        panel_layout.addWidget(contact_title)

        self.lbl_contact_name = QLabel("👤 —")
        self.lbl_contact_phone = QLabel("☎️ —")
        self.lbl_contact_position = QLabel("🧾 —")

        for lbl in (self.lbl_contact_name, self.lbl_contact_phone, self.lbl_contact_position):
            lbl.setObjectName("contactLabel")
            panel_layout.addWidget(lbl)

        # --------------------------------------------------------
        # ⚠ Alertas inteligentes (panel lateral)
        # --------------------------------------------------------
        alerts_title = QLabel("⚠ Alertas")
        alerts_title.setObjectName("sectionTitle")
        panel_layout.addWidget(alerts_title)

        self.alert_labels = []
        for _ in range(3):  # hasta 3 alertas visibles
            lbl = QLabel("—")
            lbl.setWordWrap(True)
            lbl.setObjectName("alertLabel")
            panel_layout.addWidget(lbl)
            self.alert_labels.append(lbl)

        panel_layout.addStretch(1)

        # ✅ Scroll para el panel derecho (para que no se corten textos)
        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QFrame.NoFrame)
        self.details_scroll.setWidget(self.details_panel)

        right_layout.addWidget(self.details_scroll)

        # Conectar selección de tabla → actualizar panel
        self.table.itemSelectionChanged.connect(self.on_supplier_selection_changed)

        self.setLayout(layout)

    # --------------------------------------------------------
    # 🔄 Cargar proveedores desde API
    # --------------------------------------------------------
    def load_suppliers(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            resp = requests.get(API_SUPPLIERS, headers=headers, params={"limit": 500})

            if resp.status_code != 200:
                QMessageBox.warning(self, "Error", f"No se pudieron cargar los proveedores.\n{resp.text}")
                return

            payload = resp.json()
            # Soporta respuesta paginada {"items": [...]} y legacy lista directa
            if isinstance(payload, dict) and "items" in payload:
                data = payload["items"]
            elif isinstance(payload, dict) and "data" in payload:
                data = payload["data"]
            elif isinstance(payload, list):
                data = payload
            else:
                QMessageBox.warning(self, "Error", "Formato inválido de proveedores")
                return
            if not isinstance(data, list):
                QMessageBox.warning(self, "Error", "Formato inválido de proveedores")
                return
            self.all_suppliers = data
            self.apply_filter()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al cargar proveedores:\n{e}")

    # --------------------------------------------------------
    # 📦 Obtener últimas compras del proveedor (async, #11)
    # --------------------------------------------------------
    def fetch_recent_purchases_async(self, supplier_id: int, limit: int = 5):
        """Lanza un hilo para obtener compras recientes sin bloquear UI."""
        # Cancelar hilo previo si existe
        if self._purchase_thread and self._purchase_thread.isRunning():
            self._purchase_thread.quit()
            self._purchase_thread.wait(500)

        self._purchase_worker = _RecentPurchasesWorker(supplier_id, limit)
        self._purchase_thread = QThread()
        self._purchase_worker.moveToThread(self._purchase_thread)

        self._purchase_thread.started.connect(self._purchase_worker.run)
        self._purchase_worker.finished.connect(self._on_recent_purchases_loaded)
        self._purchase_worker.finished.connect(self._purchase_thread.quit)

        # Mostrar indicador de carga
        if getattr(self, "recent_purchase_labels", None):
            self.recent_purchase_labels[0].setText("Cargando...")
            for lbl in self.recent_purchase_labels[1:]:
                lbl.setText("")

        self._purchase_thread.start()

    def _on_recent_purchases_loaded(self, recent: list):
        """Callback cuando el hilo termina de cargar compras."""
        if not recent:
            if getattr(self, "recent_purchase_labels", None):
                self.recent_purchase_labels[0].setText("Sin compras registradas")
                for lbl in self.recent_purchase_labels[1:]:
                    lbl.setText("—")
        else:
            for i, lbl in enumerate(self.recent_purchase_labels):
                if i >= len(recent):
                    lbl.setText("—")
                    continue

                entry_date = str(recent[i].get("entry_date") or "")
                amount = float(recent[i].get("amount") or 0)

                try:
                    y, m, d = entry_date.split("-")
                    entry_date = f"{d}-{m}-{y}"
                except Exception:
                    pass

                lbl.setText(f"{entry_date}   ₡{amount:,.2f}")

    # --------------------------------------------------------
    # 🔎 Filtrar proveedores
    # --------------------------------------------------------
    def apply_filter(self):
        text = (self.search_input.text() if hasattr(self, "search_input") else "").strip().lower()

        if not text:
            self.filtered_suppliers = list(self.all_suppliers)
        else:
            self.filtered_suppliers = [
                s for s in self.all_suppliers
                if text in (s.get("name", "") or "").lower()
                or text in (s.get("email", "") or "").lower()
                or text in (s.get("phone", "") or "").lower()
                or text in (s.get("contact_name", "") or "").lower()
                or text in (s.get("contact_phone", "") or "").lower()
                or text in (s.get("address", "") or "").lower()
            ]

        self.populate_table()

    # --------------------------------------------------------
    # 📝 Cargar datos en la tabla
    # --------------------------------------------------------
    def populate_table(self):
        data = self.filtered_suppliers
        self.table.setRowCount(len(data))

        for row, s in enumerate(data):
            self.table.setItem(row, 0, QTableWidgetItem(str(s["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(s["name"]))
            self.table.setItem(row, 2, QTableWidgetItem(s.get("phone", "") or ""))

            email_item = QTableWidgetItem(s.get("email", "") or "")
            email_item.setToolTip(email_item.text())
            self.table.setItem(row, 3, email_item)

            self.table.setItem(row, 4, QTableWidgetItem(s.get("address", "") or ""))

            notes_item = QTableWidgetItem(s.get("notes", "") or "")
            notes_item.setToolTip(notes_item.text())
            self.table.setItem(row, 5, notes_item)

            prod = int(s.get("products_count", 0) or 0)
            prod_item = QTableWidgetItem(str(prod))
            prod_item.setTextAlignment(Qt.AlignCenter)
            f = prod_item.font(); f.setBold(True); prod_item.setFont(f)
            prod_item.setForeground(Qt.gray if prod == 0 else Qt.green)
            self.table.setItem(row, 6, prod_item)

            # --- Críticos ---
            critical_count = int(s.get("critical_products_count", 0) or 0)

            critical_item = QTableWidgetItem(str(critical_count))
            critical_item.setTextAlignment(Qt.AlignCenter)

            font = critical_item.font()
            font.setBold(True)
            critical_item.setFont(font)

            if critical_count == 0:
                critical_item.setForeground(Qt.gray)
            elif critical_count < 5:
                critical_item.setForeground(Qt.yellow)
            else:
                critical_item.setForeground(Qt.red)

            critical_item.setToolTip("⚠ Productos en stock crítico" if critical_count > 0 else "Sin productos críticos")
            self.table.setItem(row, 7, critical_item)

            purch = int(s.get("purchases_count", 0) or 0)
            purch_item = QTableWidgetItem(str(purch))
            purch_item.setTextAlignment(Qt.AlignCenter)
            f = purch_item.font(); f.setBold(True); purch_item.setFont(f)
            purch_item.setForeground(Qt.gray if purch == 0 else Qt.green)
            self.table.setItem(row, 8, purch_item)

            total = s.get("total_purchased", 0) or 0
            total_item = QTableWidgetItem(f"₡{float(total):,.2f}")
            total_item.setToolTip(total_item.text())
            self.table.setItem(row, 9, total_item)

            last = s.get("last_purchase_date")
            last_txt = str(last) if last else ""
            last_item = QTableWidgetItem(last_txt)

            days_since_purchase = None
            if last:
                try:
                    from datetime import date as _date, datetime as _datetime
                    last_d = last if isinstance(last, _date) else _datetime.strptime(str(last), "%Y-%m-%d").date()
                    days_since_purchase = (_date.today() - last_d).days
                except Exception:
                    pass

            if days_since_purchase is not None and days_since_purchase >= 90:
                last_item.setForeground(QColor("#f97316"))
                last_item.setToolTip(f"📅 Hace {days_since_purchase} días sin compras a este proveedor")
            elif not last:
                last_item.setForeground(Qt.gray)
                last_item.setToolTip("Sin compras registradas")
            else:
                last_item.setToolTip(last_txt)

            self.table.setItem(row, 10, last_item)

            # --- Días sin comprar ---
            days = s.get("days_since_last_purchase")
            days_text = str(days) if days is not None else "—"

            days_item = QTableWidgetItem(days_text)
            days_item.setTextAlignment(Qt.AlignCenter)
            f2 = days_item.font(); f2.setBold(True); days_item.setFont(f2)

            if days is None:
                days_item.setForeground(Qt.gray)
                days_item.setToolTip("Sin compras registradas")
            elif days >= 60:
                days_item.setForeground(QColor("#FF6B6B"))
                days_item.setToolTip(f"🔴 Hace {days} días sin compras — requiere atención")
            elif days >= 30:
                days_item.setForeground(QColor("#FFD43B"))
                days_item.setToolTip(f"⚠ Hace {days} días sin compras")
            else:
                days_item.setForeground(Qt.green)
                days_item.setToolTip(f"✅ Hace {days} días")

            self.table.setItem(row, 11, days_item)

            # Tooltip del nombre con resumen
            name_item = self.table.item(row, 1)
            if name_item:
                tooltip_parts = []
                if critical_count > 0:
                    tooltip_parts.append(f"⚠ {critical_count} producto(s) en stock crítico")
                if days_since_purchase is not None and days_since_purchase >= 90:
                    tooltip_parts.append(f"📅 Última compra hace {days_since_purchase} días")
                elif not last:
                    tooltip_parts.append("📅 Sin compras registradas")
                if tooltip_parts:
                    name_item.setToolTip("\n".join(tooltip_parts))

            is_active = bool(s.get("is_active", True))

            status_item = QTableWidgetItem("🟢 Activo" if is_active else "🔴 Inactivo")
            status_item.setTextAlignment(Qt.AlignCenter)
            f = status_item.font(); f.setBold(True); status_item.setFont(f)
            status_item.setForeground(Qt.green if is_active else Qt.gray)
            status_item.setToolTip("Proveedor habilitado" if is_active else "Proveedor deshabilitado")
            self.table.setItem(row, 12, status_item)

            # -----------------------------
            # ✅ SCORE (sin emoji, solo número + color)
            # -----------------------------
            score = int(s.get("supplier_score", 0) or 0)
            if score >= 80:
                color = Qt.green
                label = "Excelente"
            elif score >= 60:
                color = QColor("#F2C94C")
                label = "Bueno"
            else:
                color = Qt.red
                label = "Revisar"

            score_item = QTableWidgetItem(str(score))
            score_item.setTextAlignment(Qt.AlignCenter)
            font = score_item.font()
            font.setBold(True)
            score_item.setFont(font)
            score_item.setForeground(color)

            purch = int(s.get("purchases_count", 0) or 0)
            rotation = int(s.get("rotation_units", 0) or 0)
            prod = int(s.get("products_count", 0) or 0)
            crit = int(s.get("critical_products_count", 0) or 0)

            stock_ok_pct = 0.0
            if prod > 0:
                stock_ok_pct = max(0.0, min(1.0, 1.0 - (crit / prod))) * 100

            score_item.setToolTip(
                f"⭐ Score: {score} ({label})\n\n"
                "Basado en:\n"
                f"• Frecuencia compras: {purch}\n"
                f"• Rotación (uds): {rotation}\n"
                f"• Cumplimiento stock: {stock_ok_pct:.0f}% (críticos: {crit}/{prod})\n\n"
                "80-100 excelente | 60-79 bueno | <60 revisar"
            )
            self.table.setItem(row, 13, score_item)

            # --- Dependencia ---
            dep = float(s.get("dependency_pct", 0) or 0)
            dep_item = QTableWidgetItem(f"{dep:.1f}%")
            dep_item.setTextAlignment(Qt.AlignCenter)
            font_dep = dep_item.font()
            font_dep.setBold(True)
            dep_item.setFont(font_dep)

            prod_sup = int(s.get("products_count", 0) or 0)
            total_all = int(s.get("total_products_all", 0) or 0)
            if total_all > 0:
                dep_tooltip = (
                    "📌 Dependencia de proveedor\n"
                    f"{prod_sup} / {total_all} = {dep:.1f}%\n\n"
                    "⚠ Si es muy alta, hay riesgo de depender de un solo proveedor."
                )
            else:
                dep_tooltip = (
                    "📌 Dependencia de proveedor\n"
                    f"Productos de este proveedor: {prod_sup}\n"
                    f"Dependencia: {dep:.1f}%\n\n"
                    "⚠ Si es muy alta, hay riesgo de depender de un solo proveedor."
                )
            dep_item.setToolTip(dep_tooltip)

            if dep > 40:
                dep_item.setForeground(Qt.red)
                dep_item.setToolTip(dep_item.toolTip() + "\n\n🚨 Riesgo: proveedor único (dependencia > 40%)")
            elif dep > 20:
                dep_item.setForeground(QColor("#F2C94C"))
            elif dep > 0:
                dep_item.setForeground(Qt.green)
            else:
                dep_item.setForeground(Qt.gray)

            self.table.setItem(row, 14, dep_item)

        if self.table.rowCount() > 0:
            self.table.selectRow(0)
        else:
            self.update_side_panel(None)

    # --------------------------------------------------------
    # ➕ Agregar proveedor
    # --------------------------------------------------------
    def open_add_dialog(self):
        dialog = AddSupplierDialog(self)
        if dialog.exec():
            self.load_suppliers()

    # --------------------------------------------------------
    # ✏️ Editar proveedor
    # --------------------------------------------------------
    def open_edit_dialog(self):
        supplier = self.get_selected_supplier()
        if not supplier:
            QMessageBox.warning(self, "Editar proveedor", "Seleccione un proveedor primero.")
            return

        dialog = EditSupplierDialog(self, supplier)
        if dialog.exec():
            self.load_suppliers()

    # --------------------------------------------------------
    # 🗑 Eliminar proveedor
    # --------------------------------------------------------
    def delete_supplier(self):
        supplier = self.get_selected_supplier()
        if not supplier:
            QMessageBox.warning(self, "Eliminar proveedor", "Seleccione un proveedor.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirmar eliminación",
            f"¿Seguro que desea eliminar al proveedor '{supplier['name']}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.No:
            return

        try:
            url = f"{API_SUPPLIERS}/{supplier['id']}"
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            resp = requests.delete(url, headers=headers)

            payload = resp.json()

            if not payload.get("success"):
                QMessageBox.warning(self, "Error", payload.get("message", "No se pudo eliminar"))
                return

            QMessageBox.information(self, "Proveedor eliminado", "Proveedor eliminado correctamente.")
            self.load_suppliers()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al eliminar proveedor:\n{e}")

    # --------------------------------------------------------
    # 👁 Ver productos del proveedor
    # --------------------------------------------------------
    def open_products_view(self):
        supplier = self.get_selected_supplier()
        if not supplier:
            QMessageBox.warning(self, "Ver productos", "Seleccione un proveedor primero.")
            return

        try:
            from ui.views.products_view import ProductsView
            supplier_id = int(supplier.get("id"))
            supplier_name = (supplier.get("name") or "").strip()

            products_view = ProductsView(supplier_id=supplier_id, supplier_name=supplier_name)
            self.main_window.set_view(products_view)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir Productos:\n{e}")

    # --------------------------------------------------------
    # 📦 Reabastecer: abrir productos del proveedor en modo stock bajo
    # --------------------------------------------------------
    def open_restock_view(self):
        supplier = self.get_selected_supplier()
        if not supplier:
            QMessageBox.warning(self, "Reabastecer", "Seleccione un proveedor primero.")
            return

        try:
            from ui.views.products_view import ProductsView
            supplier_id = int(supplier.get("id"))
            supplier_name = (supplier.get("name") or "").strip()

            products_view = ProductsView(
                supplier_id=supplier_id,
                supplier_name=supplier_name,
                auto_low_stock=True
            )
            self.main_window.set_view(products_view)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir Reabastecer:\n{e}")

    # --------------------------------------------------------
    # 🧾 Ver compras del proveedor
    # --------------------------------------------------------
    def open_purchases_view(self):
        supplier = self.get_selected_supplier()
        if not supplier:
            QMessageBox.warning(self, "Compras", "Seleccione un proveedor primero.")
            return

        try:
            from ui.views.purchases_view import PurchasesView
            supplier_id = int(supplier.get("id"))
            supplier_name = (supplier.get("name") or "").strip()

            view = PurchasesView(supplier_id=supplier_id, supplier_name=supplier_name)
            self.main_window.set_view(view)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir Compras:\n{e}")

    # --------------------------------------------------------
    # ✅ Activar / Desactivar proveedor
    # --------------------------------------------------------
    def toggle_supplier_status(self):
        supplier = self.get_selected_supplier()
        if not supplier:
            QMessageBox.warning(self, "Estado del proveedor", "Seleccione un proveedor.")
            return

        try:
            url = f"{API_SUPPLIERS}/{supplier['id']}/toggle"
            headers = {"Authorization": f"Bearer {session.token}"} if session.token else {}
            resp = requests.patch(url, headers=headers)

            if resp.status_code not in (200, 201):
                QMessageBox.warning(self, "Error", f"No se pudo cambiar el estado.\n{resp.text}")
                return

            self.load_suppliers()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al cambiar estado:\n{e}")

    # --------------------------------------------------------
    # 📌 Panel lateral: selección y actualización
    # --------------------------------------------------------
    def on_supplier_selection_changed(self):
        supplier = self.get_selected_supplier()
        self.update_side_panel(supplier)

    def update_side_panel(self, s: dict | None):
        if not s:
            self.lbl_name.setText("—")
            self.lbl_products.setText("📦 Total productos: —")
            self.lbl_critical.setText("📉 Críticos: —")
            self.lbl_last_purchase.setText("📅 Última compra: —")
            self.lbl_total_purchased.setText("💰 Total comprado: —")
            self.lbl_score.setText("⭐ Score: —")
            self.lbl_score.setStyleSheet("")  # reset al estilo base del QSS
            self.lbl_avg_purchase_gap.setText("📈 Promedio compra: —")
            self.lbl_contact_name.setText("👤 —")
            self.lbl_contact_phone.setText("☎️ —")
            self.lbl_contact_position.setText("🧾 —")
            for lbl in getattr(self, "recent_purchase_labels", []):
                lbl.setText("—")
            for lbl in getattr(self, "alert_labels", []):
                lbl.setText("—")
                lbl.hide()
            return

        name = (s.get("name") or "—")
        products = int(s.get("products_count", 0) or 0)
        critical = int(s.get("critical_products_count", 0) or 0)
        last = s.get("last_purchase_date") or None
        total = float(s.get("total_purchased", 0) or 0)

        self.lbl_name.setText(name)
        self.lbl_products.setText(f"📦 Total productos: {products}")
        self.lbl_critical.setText(f"📉 Críticos: {critical}")
        self.lbl_last_purchase.setText(f"📅 Última compra: {last if last else '—'}")
        self.lbl_total_purchased.setText(f"💰 Total comprado: ₡{total:,.2f}")

        score = int(s.get("supplier_score", 0) or 0)
        if score >= 80:
            self.lbl_score.setStyleSheet("color: #27AE60;")
        elif score >= 60:
            self.lbl_score.setStyleSheet("color: #F2C94C;")
        else:
            self.lbl_score.setStyleSheet("color: #EB5757;")
        self.lbl_score.setText(f"⭐ Score: {score}/100")

        avg_gap = s.get("avg_days_between_purchases", None)
        if avg_gap is None:
            self.lbl_avg_purchase_gap.setText("📈 Promedio compra: —")
        else:
            self.lbl_avg_purchase_gap.setText(f"📈 Promedio compra: {int(avg_gap)} días")

        contact_name = s.get("contact_name") or "—"
        contact_phone = s.get("contact_phone") or "—"
        contact_position = s.get("contact_position") or "—"
        self.lbl_contact_name.setText(f"👤 {contact_name}")
        self.lbl_contact_phone.setText(f"☎️ {contact_phone}")
        self.lbl_contact_position.setText(f"🧾 {contact_position}")

        if critical == 0:
            self.lbl_critical.setStyleSheet("color: #AAAAAA;")
        elif critical < 5:
            self.lbl_critical.setStyleSheet("color: #F2C94C; font-weight: bold;")
        else:
            self.lbl_critical.setStyleSheet("color: #EB5757; font-weight: bold;")

        supplier_id = int(s.get("id") or 0)
        self.fetch_recent_purchases_async(supplier_id, limit=5)

        alerts = []

        critical = int(s.get("critical_products_count", 0) or 0)
        days_since = s.get("days_since_last_purchase")
        dep_pct = float(s.get("dependency_pct", 0) or 0)

        if critical > 0:
            alerts.append(f"⚠ Este proveedor tiene {critical} productos críticos")

        if days_since is not None:
            try:
                days_i = int(days_since)
                if days_i >= 45:
                    alerts.append(f"⚠ Hace {days_i} días que no compras")
            except Exception:
                pass

        if dep_pct >= 35:
            alerts.append(f"⚠ Representa el {dep_pct:.1f}% de tu inventario")

        for i, lbl in enumerate(getattr(self, "alert_labels", [])):
            if i < len(alerts):
                lbl.setText(alerts[i])
                lbl.show()
            else:
                lbl.setText("—")
                lbl.hide()

    # --------------------------------------------------------
    # 🔍 Obtener proveedor seleccionado
    # --------------------------------------------------------
    def get_selected_supplier(self):
        row = self.table.currentRow()
        if row == -1:
            return None
        if row >= len(self.filtered_suppliers):
            return None
        return self.filtered_suppliers[row]