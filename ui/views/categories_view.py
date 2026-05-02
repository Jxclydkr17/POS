# ui/views/categories_view.py
"""
FASE 1 — Fix 1.1 / 1.2: Carga asíncrona + timeout en acciones.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView,
    QLineEdit, QAbstractItemView,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from ui.dialogs.add_category_dialog import AddCategoryDialog
from ui.dialogs.edit_category_dialog import EditCategoryDialog
from ui.session_manager import session
from ui.api import BASE_URL
from ui.utils.http_worker import api_call

API_URL = f"{BASE_URL}/categories"

# Roles personalizados para guardar datos limpios en cada celda
ROLE_NAME = Qt.UserRole
ROLE_ICON = Qt.UserRole + 1
ROLE_DESC = Qt.UserRole + 2


class CategoriesView(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
        self.load_categories()

    # -----------------------------------------------------
    # UI
    # -----------------------------------------------------
    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)

        title = QLabel("📂 Lista de Categorías")
        title.setStyleSheet(
            "font-size: 20px; font-weight: bold; margin-bottom: 10px; color: #D9D9D9;"
        )
        layout.addWidget(title)

        # --- Buscador ---
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Buscar categoría por nombre…")
        self.search_input.setStyleSheet(
            """
            QLineEdit {
                padding: 6px 10px;
                border: 1px solid #555;
                border-radius: 8px;
                background-color: #2C2C2C;
                color: #D9D9D9;
                font-size: 13px;
            }
            QLineEdit:focus { border: 1px solid #2E86C1; }
            """
        )
        layout.addWidget(self.search_input)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_filter)
        self.search_input.textChanged.connect(lambda: self._search_timer.start(300))

        # --- Tabla ---
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Categoría", "Productos", "Estado"])
        self.table.setColumnHidden(0, True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #2b2b2b;
                alternate-background-color: #32383E;
                color: #fff;
                gridline-color: #444;
                font-size: 13px;
            }
            QTableWidget::item:selected {
                background-color: #1e88e5;
                color: #ffffff;
            }
            QTableWidget::item:selected:!active {
                background-color: #1565c0;
                color: #ffffff;
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

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        self.table.setColumnWidth(1, 400)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 150)
        layout.addWidget(self.table)

        # --- Botones ---
        btn_layout = QHBoxLayout()

        self.btn_refresh = QPushButton("🔄 Actualizar")
        self.btn_refresh.clicked.connect(self.load_categories)

        self.btn_add = QPushButton("➕ Agregar")
        self.btn_add.clicked.connect(self.open_add_dialog)

        self.btn_edit = QPushButton("✏️ Editar")
        self.btn_edit.clicked.connect(self.open_edit_dialog)

        self.btn_toggle = QPushButton("✅ Activar/Desactivar")
        self.btn_toggle.clicked.connect(self.toggle_category)

        self.btn_delete = QPushButton("🗑️ Eliminar")
        self.btn_delete.clicked.connect(self.delete_category)

        for b in [self.btn_refresh, self.btn_add, self.btn_edit, self.btn_toggle, self.btn_delete]:
            b.setStyleSheet(
                """
                QPushButton {
                    background-color: #2E86C1;
                    color: white;
                    padding: 8px;
                    border-radius: 8px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #1B4F72; }
                """
            )
            btn_layout.addWidget(b)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    # -----------------------------------------------------
    # Filtro client-side
    # -----------------------------------------------------
    def _apply_filter(self):
        query = self.search_input.text().strip().lower()
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 1)
            if not name_item:
                continue
            name = (name_item.data(ROLE_NAME) or "").lower()
            self.table.setRowHidden(row, query not in name)

    # -----------------------------------------------------
    # Headers de autenticación
    # -----------------------------------------------------
    def _auth_headers(self):
        return {"Authorization": f"Bearer {session.token}"} if session.token else {}

    # ─────────────────────────────────────────────────────
    # FASE 1 — Fix 1.1: Carga asíncrona de categorías
    # ─────────────────────────────────────────────────────
    def load_categories(self):
        """Carga las categorías en background sin congelar la UI."""
        api_call(
            "get", API_URL,
            headers=self._auth_headers(),
            on_success=self._on_categories_loaded,
            on_error=self._on_load_error,
        )

    def _on_categories_loaded(self, payload):
        """Callback: categorías recibidas del servidor."""
        cats = payload.get("data", []) if isinstance(payload, dict) else []

        self.table.setRowCount(len(cats))

        for row, c in enumerate(cats):
            self.table.setItem(row, 0, QTableWidgetItem(str(c["id"])))

            name = c.get("name", "")
            icon = c.get("icon") or "📦"
            desc = c.get("description") or ""

            name_item = QTableWidgetItem(f"{icon}  {name}")
            name_item.setTextAlignment(Qt.AlignCenter)
            name_item.setData(ROLE_NAME, name)
            name_item.setData(ROLE_ICON, icon)
            name_item.setData(ROLE_DESC, desc)
            self.table.setItem(row, 1, name_item)

            total = int(c.get("total_products", 0) or 0)
            item_total = QTableWidgetItem(str(total))
            item_total.setTextAlignment(Qt.AlignCenter)
            font = item_total.font()
            font.setBold(True)
            item_total.setFont(font)

            if total == 0:
                item_total.setForeground(Qt.gray)
            elif total < 5:
                item_total.setForeground(Qt.yellow)
            else:
                item_total.setForeground(Qt.green)

            self.table.setItem(row, 2, item_total)

            is_active = bool(c.get("is_active", True))
            estado_text = "🟢 Activa" if is_active else "🔴 Inactiva"
            item_estado = QTableWidgetItem(estado_text)
            item_estado.setTextAlignment(Qt.AlignCenter)

            if not is_active:
                item_estado.setForeground(Qt.gray)
                name_item.setForeground(Qt.gray)

            self.table.setItem(row, 3, item_estado)

        # Reaplicar filtro activo
        self._apply_filter()

    def _on_load_error(self, msg):
        """Callback: error al cargar categorías."""
        QMessageBox.critical(self, "Error", f"No se pudieron cargar las categorías.\n{msg}")

    # -----------------------------------------------------
    # Crear categoría
    # -----------------------------------------------------
    def open_add_dialog(self):
        dialog = AddCategoryDialog(self)
        if dialog.exec():
            self.load_categories()

    # -----------------------------------------------------
    # Editar — lee datos limpios, sin parsear texto
    # -----------------------------------------------------
    def open_edit_dialog(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona una categoría primero.")
            return

        cat_id = int(self.table.item(row, 0).text())
        name_item = self.table.item(row, 1)
        name = name_item.data(ROLE_NAME) or ""
        icon = name_item.data(ROLE_ICON) or "📦"
        desc = name_item.data(ROLE_DESC) or ""

        dialog = EditCategoryDialog(cat_id, name, icon, desc, self)
        if dialog.exec():
            self.load_categories()

    # ─────────────────────────────────────────────────────
    # FASE 1 — Fix 1.2: Acciones con timeout
    # ─────────────────────────────────────────────────────

    def toggle_category(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona una categoría primero.")
            return

        cat_id = int(self.table.item(row, 0).text())
        estado_text = self.table.item(row, 3).text() if self.table.item(row, 3) else ""
        is_active = "🟢" in estado_text

        action = "desactivar" if is_active else "activar"
        confirm = QMessageBox.question(
            self,
            "Confirmar",
            f"¿Deseas {action} esta categoría?",
        )

        if confirm != QMessageBox.Yes:
            return

        api_call(
            "patch", f"{API_URL}/{cat_id}/toggle",
            headers=self._auth_headers(),
            on_success=lambda _: self.load_categories(),
            on_error=lambda msg: QMessageBox.critical(self, "Error", f"No se pudo actualizar el estado.\n{msg}"),
        )

    def delete_category(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Selecciona una categoría a eliminar.")
            return

        cat_id = int(self.table.item(row, 0).text())

        confirm = QMessageBox.question(
            self,
            "Confirmar",
            "¿Eliminar la categoría? Esta acción no se puede deshacer.",
        )

        if confirm != QMessageBox.Yes:
            return

        api_call(
            "delete", f"{API_URL}/{cat_id}",
            headers=self._auth_headers(),
            on_success=lambda _: self.load_categories(),
            on_error=lambda msg: QMessageBox.critical(self, "Error", f"No se pudo eliminar.\n{msg}"),
        )