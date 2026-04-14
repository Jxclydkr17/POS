# ui/views/expenses_view.py
"""
FASE 1 — Fix 1.1 / 1.2: Carga asíncrona + timeout en acciones.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QMessageBox, QDateEdit,
    QDialog, QFormLayout, QDialogButtonBox, QFileDialog, QHeaderView
)
from PySide6.QtCore import Qt, QDate
import logging
from ui.session_manager import session
from ui.api import BASE_URL
from ui.utils.calendar_fix import fix_calendar_colors
from ui.utils.http_worker import api_call, api_request
from app.utils.export_utils import export_expenses_pdf
from app.constants.expense_categories import EXPENSE_CATEGORIES, EXPENSE_CATEGORIES_FILTER
from app.constants.payment_methods import ALL_PAYMENT_METHODS

logger = logging.getLogger(__name__)

API_URL = BASE_URL
API_URL_EXPENSES = f"{BASE_URL}/expenses"

PAGE_SIZE = 50


class ExpensesView(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gastos Operativos")
        self.resize(1050, 700)

        self.current_page = 0
        self.page_size = PAGE_SIZE
        self.total_count = 0
        self.expenses = []
        self.total_backend = 0

        self.setup_ui()
        self.load_expenses()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {session.token}"} if session.token else {}

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        title = QLabel("💸 Registro de Gastos Operativos")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:18px; font-weight:bold; margin-bottom:10px;")
        layout.addWidget(title)

        # --- Filtros ---
        filters = QHBoxLayout()
        self.dt_from = QDateEdit(calendarPopup=True)
        self.dt_from.setDate(QDate.currentDate().addDays(-7))
        fix_calendar_colors(self.dt_from)
        self.dt_to = QDateEdit(calendarPopup=True)
        self.dt_to.setDate(QDate.currentDate())
        fix_calendar_colors(self.dt_to)

        self.cmb_category = QComboBox()
        self.cmb_category.addItems(EXPENSE_CATEGORIES_FILTER)

        btn_filter = QPushButton("🔎 Filtrar")
        btn_filter.clicked.connect(self.filter_from_first_page)
        btn_pdf = QPushButton("📄 Exportar PDF")
        btn_excel = QPushButton("📊 Exportar Excel")
        btn_pdf.clicked.connect(self.export_pdf)
        btn_excel.clicked.connect(self.export_excel)
        filters.addWidget(btn_pdf)
        filters.addWidget(btn_excel)
        filters.addWidget(QLabel("Desde:")); filters.addWidget(self.dt_from)
        filters.addWidget(QLabel("Hasta:")); filters.addWidget(self.dt_to)
        filters.addWidget(QLabel("Categoría:")); filters.addWidget(self.cmb_category)
        filters.addWidget(btn_filter)
        layout.addLayout(filters)

        # --- Tabla ---
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Fecha", "Categoría", "Descripción", "Monto (₡)", "Pago", "Usuario"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e; color: #f0f0f0;
                gridline-color: #3a3a3a; border: none; outline: 0;
            }
            QTableWidget::item:selected { background-color: #0078D7; color: white; }
            QHeaderView::section {
                background-color: #2c2c2c; color: #f0f0f0;
                padding: 6px; border: none; font-weight: bold;
            }
        """)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # --- Total + Paginación ---
        info_row = QHBoxLayout()
        self.lbl_total = QLabel("Total de gastos: ₡0.00")
        self.lbl_total.setStyleSheet("font-size:14px; font-weight:bold;")
        info_row.addWidget(self.lbl_total)
        info_row.addStretch()
        self.btn_prev = QPushButton("◀ Anterior")
        self.btn_prev.clicked.connect(self.prev_page)
        self.btn_prev.setEnabled(False)
        info_row.addWidget(self.btn_prev)
        self.lbl_page = QLabel("Página 1")
        self.lbl_page.setStyleSheet("font-size:12px; margin: 0 8px;")
        info_row.addWidget(self.lbl_page)
        self.btn_next = QPushButton("Siguiente ▶")
        self.btn_next.clicked.connect(self.next_page)
        self.btn_next.setEnabled(False)
        info_row.addWidget(self.btn_next)
        layout.addLayout(info_row)

        # --- Formulario de registro ---
        form = QHBoxLayout()
        self.txt_desc = QLineEdit(); self.txt_desc.setPlaceholderText("Descripción del gasto...")
        self.cmb_new_cat = QComboBox()
        self.cmb_new_cat.addItems(EXPENSE_CATEGORIES)
        self.txt_amount = QLineEdit(); self.txt_amount.setPlaceholderText("Monto ₡")
        self.cmb_method = QComboBox(); self.cmb_method.addItems(ALL_PAYMENT_METHODS)
        btn_add = QPushButton("➕ Registrar gasto")
        btn_add.clicked.connect(self.add_expense)
        for w in [self.txt_desc, self.cmb_new_cat, self.txt_amount, self.cmb_method, btn_add]:
            form.addWidget(w)
        layout.addLayout(form)

        # --- Botones de acción ---
        actions = QHBoxLayout()
        btn_edit = QPushButton("✏️ Editar seleccionado")
        btn_edit.clicked.connect(self.edit_expense)
        btn_delete = QPushButton("🗑️ Eliminar seleccionado")
        btn_delete.clicked.connect(self.delete_expense)
        actions.addWidget(btn_edit)
        actions.addWidget(btn_delete)
        layout.addLayout(actions)

        self.table.cellClicked.connect(self.on_row_selected)

    # ── Paginación ──
    def filter_from_first_page(self):
        self.current_page = 0
        self.load_expenses()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.load_expenses()

    def next_page(self):
        max_page = max(0, (self.total_count - 1) // self.page_size)
        if self.current_page < max_page:
            self.current_page += 1
            self.load_expenses()

    def update_pagination_controls(self):
        max_page = max(0, (self.total_count - 1) // self.page_size) if self.total_count > 0 else 0
        self.btn_prev.setEnabled(self.current_page > 0)
        self.btn_next.setEnabled(self.current_page < max_page)
        self.lbl_page.setText(
            f"Página {self.current_page + 1} de {max_page + 1}  ({self.total_count} registros)"
        )

    def on_row_selected(self, row, column):
        pass

    # ─────────────────────────────────────────────────────
    # FASE 1 — Fix 1.1: Carga asíncrona
    # ─────────────────────────────────────────────────────
    def load_expenses(self):
        selected_category = self.cmb_category.currentText()
        skip = self.current_page * self.page_size
        params = {
            "start_date": self.dt_from.date().toString("yyyy-MM-dd"),
            "end_date": self.dt_to.date().toString("yyyy-MM-dd"),
            "skip": skip,
            "limit": self.page_size,
        }
        if selected_category and selected_category != "Todos":
            params["category"] = selected_category

        api_call(
            "get", API_URL_EXPENSES,
            headers=self._auth_headers(),
            params=params,
            on_success=self._on_expenses_loaded,
            on_error=self._on_expenses_error,
        )

    def _on_expenses_loaded(self, payload):
        if not isinstance(payload, dict):
            return
        if not payload.get("success", True):
            self._on_expenses_error(payload.get("message", "Error al cargar gastos"))
            return

        data = payload.get("data", {})
        self.expenses = data.get("items", [])
        self.total_backend = data.get("total_amount", 0)
        self.total_count = data.get("total_count", 0)

        self.update_table()
        self.update_pagination_controls()

    def _on_expenses_error(self, msg):
        QMessageBox.critical(self, "Error", f"No se pudieron cargar los gastos:\n{msg}")
        logger.error(f"Error cargando gastos: {msg}")

    # ── update_table (sin cambios, ya era local) ──
    def update_table(self):
        if not self.expenses:
            self.table.setRowCount(0)
            self.lbl_total.setText("Total de gastos: ₡0.00")
            return

        self.table.setRowCount(len(self.expenses))
        total = 0
        for row, e in enumerate(self.expenses):
            date_str = str(e.get("date", ""))
            category = e.get("category", "")
            description = e.get("description", "")
            amount = float(e.get("amount", 0))
            payment = e.get("payment_method", "")
            created_by = e.get("created_by", "") or ""

            self.table.setItem(row, 0, QTableWidgetItem(date_str))
            self.table.setItem(row, 1, QTableWidgetItem(category))
            self.table.setItem(row, 2, QTableWidgetItem(description))
            self.table.setItem(row, 3, QTableWidgetItem(f'{amount:,.2f}'))
            self.table.setItem(row, 4, QTableWidgetItem(payment))
            self.table.setItem(row, 5, QTableWidgetItem(created_by))
            total += amount

        self.lbl_total.setText(f"Total de gastos: ₡{total:,.2f}")
        self.table.viewport().update()

    # ─────────────────────────────────────────────────────
    # FASE 1 — Fix 1.2: Acciones con timeout
    # ─────────────────────────────────────────────────────
    def add_expense(self):
        try:
            desc = self.txt_desc.text().strip()
            amount_text = self.txt_amount.text().strip()
            if not desc:
                QMessageBox.warning(self, "Atención", "Ingrese una descripción."); return
            if not amount_text:
                QMessageBox.warning(self, "Atención", "Ingrese un monto."); return
            try:
                amount = float(amount_text)
                if amount <= 0: raise ValueError("El monto debe ser mayor a 0")
            except ValueError as e:
                QMessageBox.warning(self, "Atención", f"Monto inválido: {e}"); return

            data = {
                "description": desc,
                "category": self.cmb_new_cat.currentText(),
                "amount": amount,
                "payment_method": self.cmb_method.currentText(),
            }
            res = api_request("post", API_URL_EXPENSES, json=data, headers=self._auth_headers())
            if res.status_code != 200:
                raise Exception(f"Error del servidor: {res.text}")
            response_data = res.json()
            if not response_data.get("success", True):
                raise Exception(response_data.get("message", "Error desconocido"))

            self.txt_desc.clear()
            self.txt_amount.clear()
            self.load_expenses()
            QMessageBox.information(self, "Éxito", f"Gasto de ₡{amount:,.2f} registrado correctamente.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo registrar el gasto:\n{e}")

    def edit_expense(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Seleccione un gasto para editar."); return

        expense = self.expenses[row]
        dlg = EditExpenseDialog(expense, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updates = dlg.get_updates()
            if not updates: return
            try:
                res = api_request(
                    "put", f"{API_URL_EXPENSES}/{expense['id']}",
                    json=updates, headers=self._auth_headers(),
                )
                if res.status_code != 200: raise Exception(res.text)
                response_data = res.json()
                if not response_data.get("success", True):
                    raise Exception(response_data.get("message", "Error desconocido"))
                QMessageBox.information(self, "Éxito", "Gasto actualizado correctamente.")
                self.load_expenses()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo actualizar el gasto:\n{e}")

    def delete_expense(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Atención", "Seleccione un gasto para eliminar."); return

        expense_id = self.expenses[row]["id"]
        confirm = QMessageBox.question(self, "Confirmar", "¿Eliminar gasto seleccionado?")
        if confirm != QMessageBox.Yes: return
        try:
            res = api_request("delete", f"{API_URL_EXPENSES}/{expense_id}", headers=self._auth_headers())
            if res.status_code != 200: raise Exception(res.text)
            QMessageBox.information(self, "Éxito", "Gasto eliminado correctamente.")
            self.load_expenses()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo eliminar el gasto:\n{e}")

    # ── Exportar (sin cambios — no hacen HTTP) ──
    def export_excel(self):
        try:
            rows = self.table.rowCount()
            if rows == 0:
                QMessageBox.warning(self, "Atención", "No hay gastos para exportar."); return
            filepath, _ = QFileDialog.getSaveFileName(self, "Guardar reporte Excel", "reporte_gastos.xlsx", "Archivos Excel (*.xlsx)")
            if not filepath: return

            data = []
            for i in range(rows):
                data.append({
                    "date": self.table.item(i, 0).text(),
                    "category": self.table.item(i, 1).text(),
                    "description": self.table.item(i, 2).text(),
                    "amount": float(self.table.item(i, 3).text().replace(",", "")),
                    "payment_method": self.table.item(i, 4).text(),
                })
            from app.utils.export_utils import export_expenses_excel
            filename = export_expenses_excel(data, filename=filepath)
            QMessageBox.information(self, "Éxito", f"Archivo Excel generado:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar el Excel:\n{e}")

    def export_pdf(self):
        try:
            rows = self.table.rowCount()
            if rows == 0:
                QMessageBox.warning(self, "Atención", "No hay gastos para exportar."); return
            filepath, _ = QFileDialog.getSaveFileName(self, "Guardar reporte PDF", "reporte_gastos.pdf", "Archivos PDF (*.pdf)")
            if not filepath: return

            data = []
            for i in range(rows):
                data.append({
                    "date": self.table.item(i, 0).text(),
                    "category": self.table.item(i, 1).text(),
                    "description": self.table.item(i, 2).text(),
                    "amount": float(self.table.item(i, 3).text().replace(",", "")),
                    "payment_method": self.table.item(i, 4).text(),
                })
            total = sum(row["amount"] for row in data)
            start_date = self.dt_from.date().toString("yyyy-MM-dd")
            end_date = self.dt_to.date().toString("yyyy-MM-dd")
            filename = export_expenses_pdf(data, start_date, end_date, total, filename=filepath)
            QMessageBox.information(self, "Éxito", f"Reporte PDF generado:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar el PDF:\n{e}")


# ==================================================================
# Diálogo de edición de gasto (sin cambios — no hace HTTP)
# ==================================================================
class EditExpenseDialog(QDialog):
    def __init__(self, expense: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar Gasto")
        self.setMinimumWidth(400)
        self.expense = expense

        layout = QFormLayout(self)

        self.txt_desc = QLineEdit(expense.get("description", ""))
        layout.addRow("Descripción:", self.txt_desc)

        self.cmb_cat = QComboBox()
        self.cmb_cat.addItems(EXPENSE_CATEGORIES)
        current_cat = expense.get("category", "")
        idx = self.cmb_cat.findText(current_cat)
        if idx >= 0: self.cmb_cat.setCurrentIndex(idx)
        layout.addRow("Categoría:", self.cmb_cat)

        self.txt_amount = QLineEdit(str(expense.get("amount", "")))
        layout.addRow("Monto (₡):", self.txt_amount)

        self.cmb_method = QComboBox()
        self.cmb_method.addItems(ALL_PAYMENT_METHODS)
        current_pm = expense.get("payment_method", "")
        idx_pm = self.cmb_method.findText(current_pm)
        if idx_pm >= 0: self.cmb_method.setCurrentIndex(idx_pm)
        layout.addRow("Método de pago:", self.cmb_method)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_updates(self) -> dict:
        updates = {}
        new_desc = self.txt_desc.text().strip()
        if new_desc != (self.expense.get("description") or ""):
            updates["description"] = new_desc
        new_cat = self.cmb_cat.currentText()
        if new_cat != self.expense.get("category", ""):
            updates["category"] = new_cat
        try:
            new_amount = float(self.txt_amount.text().strip())
            if new_amount != self.expense.get("amount"):
                updates["amount"] = new_amount
        except ValueError:
            pass
        new_pm = self.cmb_method.currentText()
        if new_pm != self.expense.get("payment_method", ""):
            updates["payment_method"] = new_pm
        return updates