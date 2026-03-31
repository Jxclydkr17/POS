from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QDateEdit, QMessageBox, QFrame
)
from PySide6.QtCore import Qt, QDate
import requests
import os
from datetime import date
from PySide6.QtCore import QDate
import logging


from ui.api import BASE_URL

API_URL = BASE_URL


class SalesHistoryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main = parent  # referencia al MainWindow
        self.setWindowTitle("Registro de Ventas")
        self.resize(1100, 650)
        self.setup_ui()
        self.load_sales()

    # ----------------------------------------------------------------------

    def setup_ui(self):
        root = QHBoxLayout(self)

        # ----- Panel izquierdo -----
        left = QVBoxLayout()
        left.setAlignment(Qt.AlignTop)


        # ----- TÍTULO -----
        title = QLabel("🧾 Registro de Ventas")
        title.setStyleSheet("font-size:18px; font-weight:bold; margin:6px 0;")
        left.addWidget(title)

        # ----- FILTROS -----
        filters = QHBoxLayout()
        self.dt_from = QDateEdit(calendarPopup=True)
        self.dt_from.setDate(QDate.currentDate().addDays(-7))
        self.dt_to = QDateEdit(calendarPopup=True)
        self.dt_to.setDate(QDate.currentDate())
        self.cmb_payment = QComboBox()
        self.cmb_payment.addItems(["Todos", "Efectivo", "Tarjeta", "SINPE", "Crédito"])
        self.cmb_status = QComboBox()
        self.cmb_status.addItems(["Todos", "Aprobada", "Pendiente", "Anulada"])
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Buscar por #venta o cliente…")

        btn_apply = QPushButton("🔎 Filtrar")
        btn_apply.clicked.connect(self.load_sales)

        btn_pdf = QPushButton("📄 Exportar PDF")
        btn_excel = QPushButton("📊 Exportar Excel")

        btn_pdf.clicked.connect(self.export_pdf)
        btn_excel.clicked.connect(self.export_excel)

        for w in [
            QLabel("Desde:"), self.dt_from, QLabel("Hasta:"), self.dt_to,
            QLabel("Pago:"), self.cmb_payment, QLabel("Estado:"), self.cmb_status,
            self.txt_search, btn_apply, btn_pdf, btn_excel
        ]:
            filters.addWidget(w)

        left.addLayout(filters)

        # ----- TABLA PRINCIPAL -----
        self.tbl = QTableWidget()
        self.tbl.setColumnCount(5)
        self.tbl.setHorizontalHeaderLabels(["#Venta", "Fecha", "Cliente", "Pago", "Total (₡)"])
        self.tbl.cellClicked.connect(self.on_row_clicked)

        self.tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl.setSelectionMode(QTableWidget.SingleSelection)

        self.tbl.setStyleSheet("""
            QTableWidget::item:selected {
                background-color: #0078d7;
                color: white;
            }
        """)

        left.addWidget(self.tbl)

        root.addLayout(left, 6)

        # ----- Separador -----
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        root.addWidget(line)

        # ----- PANEL DERECHO -----
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignTop)

        self.lbl_header = QLabel("Detalle de la factura")
        self.lbl_header.setStyleSheet("font-size:16px; font-weight:bold;")
        right.addWidget(self.lbl_header)

        self.lbl_meta = QLabel("Seleccione una factura de la lista")
        right.addWidget(self.lbl_meta)

        self.tbl_items = QTableWidget()
        self.tbl_items.setColumnCount(4)
        self.tbl_items.setHorizontalHeaderLabels(["Producto", "Cantidad", "Precio", "Subtotal"])
        right.addWidget(self.tbl_items)

        self.lbl_total = QLabel("Total: ₡0.00")
        self.lbl_total.setStyleSheet("font-size:16px; font-weight:bold;")
        right.addWidget(self.lbl_total)

        # Botón PDF individual
        self.btn_open_pdf = QPushButton("🧾 Ver comprobante PDF")
        self.btn_open_pdf.clicked.connect(self.open_pdf)
        right.addWidget(self.btn_open_pdf)

        # Botones futuros
        btns = QHBoxLayout()
        self.btn_email = QPushButton("📧 Enviar factura (placeholder)")
        self.btn_return = QPushButton("↩️ Devolución (placeholder)")
        self.btn_cancel = QPushButton("🛑 Anular (placeholder)")

        for b in [self.btn_email, self.btn_return, self.btn_cancel]:
            btns.addWidget(b)

        right.addLayout(btns)
        root.addLayout(right, 5)

    # ----------------------------------------------------------------------

    def load_sales(self):
        try:
            params = {
                "start_date": self.dt_from.date().toString("yyyy-MM-dd"),
                "end_date": self.dt_to.date().toString("yyyy-MM-dd")
            }

            pay = self.cmb_payment.currentText().lower()
            if pay != "todos":
                params["payment"] = pay

            st = self.cmb_status.currentText().lower()
            if st != "todos":
                params["status"] = st

            q = self.txt_search.text()
            if q:
                params["q"] = q

            r = requests.get(f"{API_URL}/reports/sales/history", params=params)
            r.raise_for_status()

            data = r.json()["sales"]

            self.tbl.setRowCount(len(data))
            for row, s in enumerate(data):
                self.tbl.setItem(row, 0, QTableWidgetItem(str(s["id"])))
                self.tbl.setItem(row, 1, QTableWidgetItem(s["created_at"]))
                self.tbl.setItem(row, 2, QTableWidgetItem(s["customer_name"]))
                self.tbl.setItem(row, 3, QTableWidgetItem(s["payment_method"]))
                self.tbl.setItem(row, 4, QTableWidgetItem(f"{s['total']:,.2f}"))

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo cargar el registro:\n{e}")

    # ----------------------------------------------------------------------

    def on_row_clicked(self, row, col):
        try:
            sale_id = int(self.tbl.item(row, 0).text())
            r = requests.get(f"{API_URL}/reports/sales/{sale_id}")
            r.raise_for_status()

            d = r.json()

            self.lbl_header.setText(f"Factura #{d['id']} — {d['created_at']}")
            self.lbl_meta.setText(
                f"Cliente: <b>{d['customer_name']}</b>  |  Método: <b>{d['payment_method']}</b>  |  Estado: <b>{d['status']}</b>"
            )

            items = d.get("items", [])

            self.tbl_items.clearContents()
            self.tbl_items.setRowCount(len(items))

            if not items:
                self.tbl_items.setRowCount(1)
                self.tbl_items.setItem(0, 0, QTableWidgetItem("Sin productos"))
                self.tbl_items.setItem(0, 1, QTableWidgetItem("-"))
                self.tbl_items.setItem(0, 2, QTableWidgetItem("-"))
                self.tbl_items.setItem(0, 3, QTableWidgetItem("-"))
            else:
                for i, it in enumerate(items):
                    name_item = QTableWidgetItem(it["product_name"])
                    # ✅ PRODUCTO COMÚN: resaltar con color diferente
                    if it.get("is_common", False):
                        from PySide6.QtGui import QColor, QBrush
                        name_item.setForeground(QBrush(QColor("#94a3b8")))
                        name_item.setToolTip("Producto común — sin inventario")
                    self.tbl_items.setItem(i, 0, name_item)
                    self.tbl_items.setItem(i, 1, QTableWidgetItem(str(it["quantity"])))
                    self.tbl_items.setItem(i, 2, QTableWidgetItem(f"{it['price']:,.2f}"))
                    self.tbl_items.setItem(i, 3, QTableWidgetItem(f"{it['subtotal']:,.2f}"))

            self.lbl_total.setText(f"Total: ₡{d['total']:,.2f}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo cargar el detalle:\n{e}")

    # ----------------------------------------------------------------------

    def export_excel(self):
        try:
            if self.tbl.rowCount() == 0:
                QMessageBox.warning(self, "Atención", "No hay ventas para exportar.")
                return

            data = []
            for i in range(self.tbl.rowCount()):
                data.append({
                    "id": int(self.tbl.item(i, 0).text()),
                    "created_at": self.tbl.item(i, 1).text(),
                    "customer_name": self.tbl.item(i, 2).text(),
                    "payment_method": self.tbl.item(i, 3).text(),
                    "total": float(self.tbl.item(i, 4).text().replace(",", "")),
                })

            from app.utils.export_utils import export_sales_history_excel
            filename = export_sales_history_excel(data)
            QMessageBox.information(self, "Éxito", f"Archivo Excel generado:\n{filename}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar el Excel:\n{e}")

    # ----------------------------------------------------------------------

    def export_pdf(self):
        try:
            if self.tbl.rowCount() == 0:
                QMessageBox.warning(self, "Atención", "No hay ventas para exportar.")
                return

            data = []
            for i in range(self.tbl.rowCount()):
                data.append({
                    "id": int(self.tbl.item(i, 0).text()),
                    "created_at": self.tbl.item(i, 1).text(),
                    "customer_name": self.tbl.item(i, 2).text(),
                    "payment_method": self.tbl.item(i, 3).text(),
                    "total": float(self.tbl.item(i, 4).text().replace(",", "")),
                })

            from app.utils.export_utils import export_sales_history_pdf
            filename = export_sales_history_pdf(
                data,
                self.dt_from.date().toString("yyyy-MM-dd"),
                self.dt_to.date().toString("yyyy-MM-dd")
            )
            QMessageBox.information(self, "Éxito", f"Reporte PDF generado:\n{filename}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar el PDF:\n{e}")

    # ----------------------------------------------------------------------

    def open_pdf(self):
        try:
            row = self.tbl.currentRow()
            if row == -1:
                QMessageBox.warning(self, "Atención", "Selecciona una venta.")
                return

            sale_id = int(self.tbl.item(row, 0).text())
            pdf_path = os.path.abspath(f"app/pdfs/venta_{sale_id}.pdf")

            if not os.path.exists(pdf_path):
                reply = QMessageBox.question(
                    self,
                    "PDF no encontrado",
                    "No existe el PDF para esta venta.\n¿Desea regenerarlo?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply != QMessageBox.Yes:
                    return
                try:
                    resp = requests.post(f"{API_URL}/sales/{sale_id}/regenerate-pdf", timeout=15)
                    resp.raise_for_status()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"No se pudo regenerar el PDF:\n{e}")
                    return
                if not os.path.exists(pdf_path):
                    QMessageBox.warning(self, "Error", "El PDF fue generado pero no se encontró en la ruta esperada.")
                    return

            if os.name == "nt":
                os.startfile(pdf_path)
            elif os.name == "posix":
                import subprocess
                subprocess.Popen(["xdg-open", pdf_path])

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir el PDF:\n{e}")

    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    def apply_period_filter(self, period: str, start_iso: str | None = None, end_iso: str | None = None):
        """
        Aplica un filtro de periodo desde IA:
        period: today | week | month
        start_iso / end_iso: fechas yyyy-mm-dd (opcional)
        """
        today = QDate.currentDate()

        if period == "today":
            self.dt_from.setDate(today)
            self.dt_to.setDate(today)

        elif period == "week":
            # lunes a domingo
            start = today.addDays(-today.dayOfWeek() + 1)
            end = start.addDays(6)
            self.dt_from.setDate(start)
            self.dt_to.setDate(end)

        elif period == "month":
            start = QDate(today.year(), today.month(), 1)
            end = start.addMonths(1).addDays(-1)
            self.dt_from.setDate(start)
            self.dt_to.setDate(end)

        # Si vienen fechas exactas desde el backend, tienen prioridad
        if start_iso and end_iso:
            self.dt_from.setDate(QDate.fromString(start_iso, "yyyy-MM-dd"))
            self.dt_to.setDate(QDate.fromString(end_iso, "yyyy-MM-dd"))

        # 🔄 refrescar tabla
        self.load_sales()
        
    def apply_date_range(self, start_date: str, end_date: str):
        """
        start_date/end_date vienen ISO: 'YYYY-MM-DD'
        """
        try:
            y, m, d = map(int, start_date.split("-"))
            y2, m2, d2 = map(int, end_date.split("-"))

            self.dt_from.setDate(QDate(y, m, d))
            self.dt_to.setDate(QDate(y2, m2, d2))

            # dispara el filtrado normal
            self.load_sales()

        except Exception as e:
            logging.error(f"apply_date_range error: {e}")