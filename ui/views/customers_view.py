from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QLineEdit, QMessageBox,
    QAbstractItemView, QSizePolicy, QHeaderView, QComboBox,
    QFileDialog
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
import requests
from datetime import date, datetime
from ui.session_manager import session

from ui.dialogs.add_customer_dialog import AddCustomerDialog
from ui.dialogs.edit_customer_dialog import EditCustomerDialog
from ui.api import BASE_URL

API_URL = f"{BASE_URL}/customers"

# Mapa columna-tabla → campo backend para ordenamiento
SORT_COLUMN_MAP = {
    0: "id",
    1: "name",
    2: "customer_type",
    3: "email",
    4: "phone",
    5: None,          # Ubicación (compuesta, no sorteable)
    6: None,          # Identificación (compuesta)
    7: "credit_balance",
    8: None,           # Límite (no sorteable directo)
    9: "last_purchase_date",
}


class CustomersView(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clientes")
        self.resize(850, 550)

        self.customers_by_id = {}

        # Estado de paginación
        self._page = 0
        self._page_size = 25
        self._total = 0

        # Estado de ordenamiento
        self._sort_by = "id"
        self._sort_dir = "desc"

        # Debounce timer
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(350)
        self._debounce_timer.timeout.connect(self._do_search)

        self.setup_ui()
        self.load_customers()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Título
        title = QLabel("👥 Lista de Clientes")
        title.setStyleSheet("""
            font-size: 22px;
            font-weight: bold;
            color: #E8E8E8;
            margin-bottom: 4px;
        """)
        layout.addWidget(title)

        # ── Búsqueda ──
        search_layout = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar por nombre, correo, teléfono o identificación...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet("""
            padding: 7px 10px;
            border-radius: 6px;
            border: 1px solid #555;
            background-color: #F8F9FA;
            color: #000;
            font-size: 14px;
        """)
        self.search_input.textChanged.connect(self._on_search_changed)

        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # ── TABLA ──
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "ID", "Nombre", "Tipo", "Correo", "Teléfono",
            "Ubicación", "Identificación",
            "Saldo crédito", "Límite", "Última compra"
        ])

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setAlternatingRowColors(True)

        # Doble clic en fila → editar
        self.table.doubleClicked.connect(self._on_double_click)

        # Sort por header
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._on_header_clicked)

        # Anchos iniciales sugeridos
        self.table.setColumnWidth(0, 50)   # ID
        self.table.setColumnWidth(1, 150)  # Nombre
        self.table.setColumnWidth(2, 80)   # Tipo
        self.table.setColumnWidth(3, 150)  # Correo
        self.table.setColumnWidth(4, 100)  # Teléfono
        self.table.setColumnWidth(5, 130)  # Ubicación
        self.table.setColumnWidth(6, 140)  # Identificación
        self.table.setColumnWidth(7, 110)  # Saldo
        self.table.setColumnWidth(8, 100)  # Límite

        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #2b2b2b;
                alternate-background-color: #32383E;
                color: #fff;
                gridline-color: #444;
                font-size: 13px;
            }
            QHeaderView::section {
                background-color: #1e88e5;
                padding: 5px;
                border: none;
                color: white;
                font-weight: bold;
                font-size: 12px;
            }
        """)

        layout.addWidget(self.table, stretch=1)

        # ── Paginación ──
        pag_layout = QHBoxLayout()

        self.btn_prev = QPushButton("◀ Anterior")
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_prev.setStyleSheet(self._pag_btn_style())

        self.lbl_page_info = QLabel("Página 1 de 1")
        self.lbl_page_info.setAlignment(Qt.AlignCenter)
        self.lbl_page_info.setStyleSheet("color: #ccc; font-size: 13px; min-width: 180px;")

        self.btn_next = QPushButton("Siguiente ▶")
        self.btn_next.clicked.connect(self._next_page)
        self.btn_next.setStyleSheet(self._pag_btn_style())

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100"])
        self.page_size_combo.setCurrentText("25")
        self.page_size_combo.currentTextChanged.connect(self._on_page_size_changed)
        self.page_size_combo.setStyleSheet("""
            QComboBox {
                background-color: #333;
                color: white;
                padding: 4px 8px;
                border-radius: 4px;
                min-width: 60px;
            }
        """)

        pag_layout.addStretch()
        pag_layout.addWidget(self.btn_prev)
        pag_layout.addWidget(self.lbl_page_info)
        pag_layout.addWidget(self.btn_next)
        pag_layout.addWidget(QLabel("  por página:"))
        pag_layout.addWidget(self.page_size_combo)
        pag_layout.addStretch()
        layout.addLayout(pag_layout)

        # ── Barra de acciones ──
        buttons_layout = QHBoxLayout()

        self.btn_add = QPushButton("➕ Agregar")
        self.btn_edit = QPushButton("✏️ Editar")
        self.btn_delete = QPushButton("🗑️ Eliminar")
        self.btn_credit = QPushButton("💳 Créditos")

        buttons = [
            (self.btn_add, "#27AE60"),
            (self.btn_edit, "#F2C94C"),
            (self.btn_delete, "#EB5757"),
            (self.btn_credit, "#2D9CDB")
        ]

        for btn, color in buttons:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color};
                    color: white;
                    font-weight: bold;
                    padding: 8px;
                    border-radius: 8px;
                    min-width: 120px;
                }}
                QPushButton:hover {{
                    background-color: #4B4B4B;
                }}
            """)
            buttons_layout.addWidget(btn)

        layout.addLayout(buttons_layout)

        # ── Barra secundaria: Exportar / Importar / Aging / Reactivar ──
        sec_btn_style = """
            QPushButton {
                background-color: #333; color: #ccc; font-weight: bold;
                padding: 6px 12px; border-radius: 6px; min-width: 100px;
                border: 1px solid #555;
            }
            QPushButton:hover { background-color: #444; color: white; }
        """
        sec_layout = QHBoxLayout()

        self.btn_export = QPushButton("📥 Exportar CSV")
        self.btn_export.setStyleSheet(sec_btn_style)
        self.btn_export.clicked.connect(self.export_csv)

        self.btn_import = QPushButton("📤 Importar CSV")
        self.btn_import.setStyleSheet(sec_btn_style)
        self.btn_import.clicked.connect(self.import_csv)

        self.btn_aging = QPushButton("📊 Aging Crédito")
        self.btn_aging.setStyleSheet(sec_btn_style)
        self.btn_aging.clicked.connect(self.open_aging_report)

        self.btn_reactivate = QPushButton("♻️ Reactivar")
        self.btn_reactivate.setStyleSheet(sec_btn_style)
        self.btn_reactivate.clicked.connect(self.reactivate_customer)

        sec_layout.addWidget(self.btn_export)
        sec_layout.addWidget(self.btn_import)
        sec_layout.addWidget(self.btn_aging)
        sec_layout.addStretch()
        sec_layout.addWidget(self.btn_reactivate)
        layout.addLayout(sec_layout)

        # Eventos
        self.btn_add.clicked.connect(self.add_customer)
        self.btn_edit.clicked.connect(self.edit_customer)
        self.btn_delete.clicked.connect(self.delete_customer)
        self.btn_credit.clicked.connect(self.manage_credit)

        if session.role != "admin":
            self.btn_delete.setEnabled(False)

        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Estilo reutilizable para botones de paginación
    # ------------------------------------------------------------------
    @staticmethod
    def _pag_btn_style():
        return """
            QPushButton {
                background-color: #444;
                color: white;
                font-weight: bold;
                padding: 5px 14px;
                border-radius: 5px;
                min-width: 90px;
            }
            QPushButton:hover { background-color: #555; }
            QPushButton:disabled { background-color: #2a2a2a; color: #666; }
        """

    # ==================================================================
    # DEBOUNCE — búsqueda mientras escribe
    # ==================================================================
    def _on_search_changed(self, _text):
        self._debounce_timer.start()

    def _do_search(self):
        self._page = 0
        self.load_customers()

    # ==================================================================
    # PAGINACIÓN
    # ==================================================================
    def _prev_page(self):
        if self._page > 0:
            self._page -= 1
            self.load_customers()

    def _next_page(self):
        max_page = max(0, (self._total - 1) // self._page_size)
        if self._page < max_page:
            self._page += 1
            self.load_customers()

    def _on_page_size_changed(self, text):
        try:
            self._page_size = int(text)
        except ValueError:
            self._page_size = 25
        self._page = 0
        self.load_customers()

    def _update_pag_controls(self):
        max_page = max(0, (self._total - 1) // self._page_size) if self._total > 0 else 0
        self.btn_prev.setEnabled(self._page > 0)
        self.btn_next.setEnabled(self._page < max_page)

        start = self._page * self._page_size + 1 if self._total > 0 else 0
        end = min(start + self._page_size - 1, self._total)
        self.lbl_page_info.setText(
            f"{start}–{end} de {self._total}  (pág {self._page + 1}/{max_page + 1})"
        )

    # ==================================================================
    # ORDENAMIENTO por header
    # ==================================================================
    def _on_header_clicked(self, logical_index):
        field = SORT_COLUMN_MAP.get(logical_index)
        if not field:
            return  # columna no sorteable

        if self._sort_by == field:
            self._sort_dir = "asc" if self._sort_dir == "desc" else "desc"
        else:
            self._sort_by = field
            self._sort_dir = "asc"

        order = Qt.AscendingOrder if self._sort_dir == "asc" else Qt.DescendingOrder
        self.table.horizontalHeader().setSortIndicator(logical_index, order)

        self._page = 0
        self.load_customers()

    # ==================================================================
    # DOBLE CLIC → Abrir perfil del cliente
    # ==================================================================
    def _on_double_click(self, index):
        self.open_profile()

    # ------------------------------------------------------------------
    # Cargar clientes
    # ------------------------------------------------------------------
    def load_customers(self):
        try:
            headers = {"Authorization": f"Bearer {session.token}"}

            search = self.search_input.text().strip()

            params = {
                "skip": self._page * self._page_size,
                "limit": self._page_size,
                "sort_by": self._sort_by,
                "sort_dir": self._sort_dir,
            }
            if search:
                params["search"] = search

            response = requests.get(API_URL, headers=headers, params=params)

            if response.status_code != 200:
                QMessageBox.warning(self, "Error", "No se pudieron cargar los clientes.")
                return

            payload = response.json()
            customers = payload.get("data", [])
            self._total = payload.get("total", len(customers))

            self.customers_by_id = {c["id"]: c for c in customers}

            self.table.setSortingEnabled(False)
            self.table.setRowCount(len(customers))

            for row, c in enumerate(customers):
                self.table.setItem(row, 0, QTableWidgetItem(str(c["id"])))

                # ── Nombre con indicadores visuales ──
                name = c["name"]
                badges = []
                balance = float(c.get("credit_balance", 0.0))
                has_limit = c.get("has_credit_limit", False)
                limit_val = float(c.get("credit_limit", 0.0))
                ctype = (c.get("customer_type") or "Normal")

                # 🔴 Sobre su límite
                if has_limit and limit_val > 0 and balance > limit_val:
                    badges.append("🔴")

                # ⚠️ Deuda > 60 días sin compra (proxy: last_purchase_date)
                lp_raw = c.get("last_purchase_date")
                days_inactive = None
                if lp_raw:
                    try:
                        lp_date = datetime.fromisoformat(str(lp_raw).replace("Z", "")).date()
                        days_inactive = (date.today() - lp_date).days
                    except Exception:
                        pass

                if balance > 0 and days_inactive is not None and days_inactive > 60:
                    badges.append("⚠️")

                # 💤 Inactivo > 90 días (sin compras)
                if days_inactive is not None and days_inactive > 90:
                    badges.append("💤")

                # ⭐ VIP
                if ctype == "VIP":
                    badges.append("⭐")

                prefix = " ".join(badges) + " " if badges else ""
                name_item = QTableWidgetItem(f"{prefix}{name}")

                # Color de fondo sutil para alertas críticas
                if has_limit and limit_val > 0 and balance > limit_val:
                    name_item.setForeground(QColor("#ef4444"))

                self.table.setItem(row, 1, name_item)

                self.table.setItem(row, 2, QTableWidgetItem(ctype))
                self.table.setItem(row, 3, QTableWidgetItem(c.get("email") or ""))
                self.table.setItem(row, 4, QTableWidgetItem(c.get("phone") or ""))

                # Ubicación (Provincia - Cantón)
                prov = c.get("province_name") or ""
                cant = c.get("canton_name") or ""
                ubicacion = f"{prov} - {cant}" if prov else ""
                self.table.setItem(row, 5, QTableWidgetItem(ubicacion))

                # Identificación
                id_full = f"{c.get('id_type') or ''} - {c.get('id_number') or ''}"
                self.table.setItem(row, 6, QTableWidgetItem(id_full))

                # Saldo crédito (con color) — variables ya declaradas arriba
                balance_item = QTableWidgetItem(f"₡{balance:,.2f}")

                if balance <= 0:
                    balance_item.setForeground(QColor("#22c55e"))  # verde
                elif has_limit and limit_val > 0 and balance > limit_val:
                    balance_item.setForeground(QColor("#ef4444"))  # rojo - excede límite
                elif balance > 0:
                    balance_item.setForeground(QColor("#f59e0b"))  # amarillo - tiene saldo
                self.table.setItem(row, 7, balance_item)

                # Límite de crédito
                if has_limit:
                    limit_text = f"₡{limit_val:,.2f}"
                else:
                    limit_text = "Ilimitado"
                self.table.setItem(row, 8, QTableWidgetItem(limit_text))

                # Última compra
                lp = c.get("last_purchase_date") or ""
                if lp and "T" in str(lp):
                    lp = str(lp).split("T")[0]
                self.table.setItem(row, 9, QTableWidgetItem(str(lp)))

            self._update_pag_controls()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo conectar con el servidor:\n{e}")

    # ------------------------------------------------------------------
    # Crear cliente
    # ------------------------------------------------------------------
    def add_customer(self):
        dialog = AddCustomerDialog()
        if dialog.exec():
            self.load_customers()

    # ------------------------------------------------------------------
    # Obtener detalle completo del cliente
    # ------------------------------------------------------------------
    def fetch_customer_detail(self, customer_id: int):
        headers = {"Authorization": f"Bearer {session.token}"}
        r = requests.get(f"{API_URL}/{customer_id}", headers=headers)

        if r.status_code != 200:
            return None

        data = r.json()
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            return data["data"]
        return data

    # ------------------------------------------------------------------
    # Editar cliente
    # ------------------------------------------------------------------
    def edit_customer(self):
        selected = self.table.currentRow()
        if selected < 0:
            QMessageBox.warning(self, "Atención", "Selecciona un cliente para editar.")
            return

        customer_id = int(self.table.item(selected, 0).text())

        customer_data = None
        try:
            headers = session.get_auth_headers()
            r = requests.get(f"{API_URL}/{customer_id}", headers=headers, timeout=10)
            if r.status_code == 200:
                customer_data = r.json()
                if isinstance(customer_data, dict) and "data" in customer_data and isinstance(customer_data["data"], dict):
                    customer_data = customer_data["data"]
                self.customers_by_id[customer_id] = customer_data
            else:
                customer_data = self.customers_by_id.get(customer_id)
        except Exception:
            customer_data = self.customers_by_id.get(customer_id)

        if not customer_data:
            QMessageBox.critical(self, "Error", "No pude cargar los datos del cliente.")
            return

        dialog = EditCustomerDialog(customer_data)
        if dialog.exec():
            self.load_customers()

    # ------------------------------------------------------------------
    # Eliminar cliente
    # ------------------------------------------------------------------
    def delete_customer(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona un cliente para eliminar.")
            return

        customer_id = int(self.table.item(row, 0).text())
        name = self.table.item(row, 1).text()

        confirm = QMessageBox.question(
            self,
            "Confirmar eliminación",
            f"¿Seguro que deseas eliminar a '{name}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            return

        headers = {"Authorization": f"Bearer {session.token}"}
        response = requests.delete(f"{API_URL}/{customer_id}", headers=headers)

        if response.status_code == 200:
            QMessageBox.information(self, "Éxito", "Cliente eliminado.")
            self.load_customers()
        else:
            QMessageBox.warning(self, "Error", f"No se pudo eliminar:\n{response.text}")

    # ------------------------------------------------------------------
    # Créditos
    # ------------------------------------------------------------------
    def manage_credit(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona un cliente para ver sus créditos.")
            return

        customer_id = int(self.table.item(row, 0).text())
        customer_name = self.table.item(row, 1).text()

        from ui.views.customer_credit_view import CustomerCreditView
        dlg = CustomerCreditView(customer_id, customer_name, parent=self)
        dlg.exec()
        self.load_customers()

    # ------------------------------------------------------------------
    # Perfil completo del cliente
    # ------------------------------------------------------------------
    def open_profile(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona un cliente.")
            return

        customer_id = int(self.table.item(row, 0).text())

        from ui.views.customer_profile_view import CustomerProfileView
        dlg = CustomerProfileView(customer_id, parent=self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Exportar CSV
    # ------------------------------------------------------------------
    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar clientes", "clientes.csv", "CSV (*.csv)"
        )
        if not path:
            return

        try:
            headers = {"Authorization": f"Bearer {session.token}"}
            r = requests.get(f"{API_URL}/export/csv", headers=headers, timeout=30)
            if r.status_code == 200:
                with open(path, "w", encoding="utf-8-sig") as f:
                    f.write(r.text)
                QMessageBox.information(self, "Éxito", f"Clientes exportados a:\n{path}")
            else:
                QMessageBox.warning(self, "Error", f"Error exportando:\n{r.text}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ------------------------------------------------------------------
    # Importar CSV
    # ------------------------------------------------------------------
    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar clientes", "", "CSV (*.csv);;Todos (*)"
        )
        if not path:
            return

        try:
            headers = {"Authorization": f"Bearer {session.token}"}
            with open(path, "rb") as f:
                files = {"file": (path.split("/")[-1].split("\\")[-1], f, "text/csv")}
                r = requests.post(
                    f"{API_URL}/import/csv",
                    headers=headers,
                    files=files,
                    timeout=60,
                )

            if r.status_code == 200:
                data = r.json().get("data", {})
                created = data.get("created", 0)
                errors = data.get("errors", [])
                msg = f"✅ {created} clientes importados."
                if errors:
                    error_lines = "\n".join([f"Fila {e['row']}: {e['error']}" for e in errors[:10]])
                    msg += f"\n\n⚠️ Errores ({len(errors)}):\n{error_lines}"
                QMessageBox.information(self, "Importación", msg)
                self.load_customers()
            else:
                QMessageBox.warning(self, "Error", f"Error importando:\n{r.text}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ------------------------------------------------------------------
    # Reporte de Aging global
    # ------------------------------------------------------------------
    def open_aging_report(self):
        from ui.views.aging_report_view import AgingReportView
        dlg = AgingReportView(parent=self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Reactivar cliente desactivado
    # ------------------------------------------------------------------
    def reactivate_customer(self):
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Reactivar Cliente",
            "Ingrese el ID del cliente a reactivar:"
        )
        if not ok or not text.strip():
            return

        try:
            customer_id = int(text.strip())
        except ValueError:
            QMessageBox.warning(self, "Error", "Ingrese un ID numérico válido.")
            return

        confirm = QMessageBox.question(
            self, "Confirmar",
            f"¿Reactivar el cliente con ID {customer_id}?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            headers = {"Authorization": f"Bearer {session.token}"}
            r = requests.post(
                f"{API_URL}/{customer_id}/reactivate",
                headers=headers,
                timeout=10,
            )
            if r.status_code == 200:
                QMessageBox.information(self, "Éxito", "Cliente reactivado correctamente.")
                self.load_customers()
            else:
                detail = r.json().get("detail", r.text)
                QMessageBox.warning(self, "Error", f"No se pudo reactivar:\n{detail}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))