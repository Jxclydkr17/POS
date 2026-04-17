# ui/dialogs/day_sales_dialog.py

import os
import subprocess
from datetime import datetime

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.utils.print_ticket import print_pdf
from ui.api import BASE_URL
from ui.session_manager import session
from ui.utils.http_worker import api_call, api_request


API_URL = BASE_URL


class DaySalesDialog(QDialog):
    """
    Popup compacto para ver las ventas del día desde el módulo de ventas.
    Permite:
    - Ver lista de ventas del día
    - Ver detalle de la venta seleccionada
    - Abrir comprobante PDF
    - Reimprimir
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧾 Ventas del día")
        self.setModal(True)
        self.resize(1040, 620)

        self.current_sale_id = None
        self.sales_data = []

        self.setup_ui()
        self.load_today_sales()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Header
        title = QLabel("🧾 Ventas del día")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        root.addWidget(title)

        self.lbl_subtitle = QLabel("Consulta rápida de ventas registradas hoy")
        self.lbl_subtitle.setStyleSheet("color: #94a3b8; font-size: 12px;")
        root.addWidget(self.lbl_subtitle)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #1f2937;")
        root.addWidget(line)

        # Contenido principal
        content = QHBoxLayout()
        content.setSpacing(12)
        root.addLayout(content, 1)

        # --------------------- PANEL IZQUIERDO ---------------------
        left_box = QVBoxLayout()
        left_box.setSpacing(8)
        content.addLayout(left_box, 6)

        left_title = QLabel("Ventas registradas")
        left_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #e5e7eb;")
        left_box.addWidget(left_title)

        self.tbl_sales = QTableWidget(0, 5)
        self.tbl_sales.setHorizontalHeaderLabels(["#Venta", "Hora", "Cliente", "Pago", "Total"])
        self.tbl_sales.verticalHeader().setVisible(False)
        self.tbl_sales.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_sales.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_sales.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_sales.setAlternatingRowColors(True)
        self.tbl_sales.setShowGrid(False)
        self.tbl_sales.setWordWrap(False)
        self.tbl_sales.setSortingEnabled(False)
        self.tbl_sales.cellClicked.connect(self.on_row_clicked)
        self.tbl_sales.cellDoubleClicked.connect(self.open_pdf)

        sales_header = self.tbl_sales.horizontalHeader()
        sales_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        sales_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        sales_header.setSectionResizeMode(2, QHeaderView.Stretch)
        sales_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        sales_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        self.tbl_sales.setStyleSheet("""
            QTableWidget {
                background-color: #0b1220;
                border: 1px solid #1f2937;
                border-radius: 10px;
                color: #e5e7eb;
                alternate-background-color: #0f172a;
                selection-background-color: #1d4ed8;
                selection-color: white;
            }
            QHeaderView::section {
                background-color: #111827;
                color: #e5e7eb;
                font-weight: 700;
                padding: 7px;
                border: 0;
            }
            QTableWidget::item {
                padding: 6px;
            }
        """)
        left_box.addWidget(self.tbl_sales, 1)

        self.lbl_count = QLabel("0 ventas")
        self.lbl_count.setStyleSheet("color: #94a3b8; font-size: 12px;")
        left_box.addWidget(self.lbl_count)

        # --------------------- SEPARADOR ---------------------
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setStyleSheet("color: #1f2937;")
        content.addWidget(separator)

        # --------------------- PANEL DERECHO ---------------------
        right_box = QVBoxLayout()
        right_box.setSpacing(8)
        content.addLayout(right_box, 5)

        right_title = QLabel("Detalle de venta")
        right_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #e5e7eb;")
        right_box.addWidget(right_title)

        self.lbl_header = QLabel("Seleccione una venta")
        self.lbl_header.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc;")
        right_box.addWidget(self.lbl_header)

        self.lbl_meta = QLabel("Aquí se mostrará la información de la venta seleccionada")
        self.lbl_meta.setWordWrap(True)
        self.lbl_meta.setStyleSheet("color: #94a3b8; font-size: 12px;")
        right_box.addWidget(self.lbl_meta)

        self.tbl_items = QTableWidget(0, 4)
        self.tbl_items.setHorizontalHeaderLabels(["Producto", "Cant.", "Precio", "Subtotal"])
        self.tbl_items.verticalHeader().setVisible(False)
        self.tbl_items.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_items.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl_items.setAlternatingRowColors(True)
        self.tbl_items.setShowGrid(False)

        items_header = self.tbl_items.horizontalHeader()
        items_header.setSectionResizeMode(0, QHeaderView.Stretch)
        items_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        items_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        items_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        self.tbl_items.setStyleSheet("""
            QTableWidget {
                background-color: #0b1220;
                border: 1px solid #1f2937;
                border-radius: 10px;
                color: #e5e7eb;
                alternate-background-color: #0f172a;
            }
            QHeaderView::section {
                background-color: #111827;
                color: #e5e7eb;
                font-weight: 700;
                padding: 7px;
                border: 0;
            }
            QTableWidget::item {
                padding: 6px;
            }
        """)
        right_box.addWidget(self.tbl_items, 1)

        totals_card = QFrame()
        totals_card.setStyleSheet("""
            QFrame {
                background-color: #0b1220;
                border: 1px solid #1f2937;
                border-radius: 10px;
            }
            QLabel {
                color: #e5e7eb;
            }
        """)
        totals_layout = QVBoxLayout(totals_card)
        totals_layout.setContentsMargins(12, 10, 12, 10)
        totals_layout.setSpacing(6)

        self.lbl_total = QLabel("Total: ₡0.00")
        self.lbl_total.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        totals_layout.addWidget(self.lbl_total)

        right_box.addWidget(totals_card)

        # --------------------- BOTONES ---------------------
        btns = QHBoxLayout()
        btns.setSpacing(8)
        root.addLayout(btns)

        self.btn_refresh = QPushButton("🔄 Refrescar")
        self.btn_open_pdf = QPushButton("🧾 Ver PDF")
        self.btn_reprint = QPushButton("🖨 Reimprimir")
        self.btn_close = QPushButton("Cerrar")

        self.btn_refresh.clicked.connect(self.load_today_sales)
        self.btn_open_pdf.clicked.connect(self.open_pdf)
        self.btn_reprint.clicked.connect(self.reprint_sale)
        self.btn_close.clicked.connect(self.accept)

        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: white;
                padding: 8px 14px;
                border-radius: 8px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)

        self.btn_open_pdf.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                padding: 8px 14px;
                border-radius: 8px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)

        self.btn_reprint.setStyleSheet("""
            QPushButton {
                background-color: #16a34a;
                color: white;
                padding: 8px 14px;
                border-radius: 8px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #15803d;
            }
        """)

        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: white;
                padding: 8px 16px;
                border-radius: 8px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)

        btns.addWidget(self.btn_refresh)
        btns.addStretch()
        btns.addWidget(self.btn_open_pdf)
        btns.addWidget(self.btn_reprint)
        btns.addWidget(self.btn_close)

        # Estado inicial
        self._set_detail_enabled(False)

        self.setStyleSheet("""
            QDialog {
                background-color: #080d1a;
            }
        """)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _set_detail_enabled(self, enabled: bool):
        self.btn_open_pdf.setEnabled(enabled)
        self.btn_reprint.setEnabled(enabled)

    def _payment_label(self, method: str) -> str:
        mapping = {
            "cash": "💵 Efectivo",
            "efectivo": "💵 Efectivo",
            "card": "💳 Tarjeta",
            "tarjeta": "💳 Tarjeta",
            "sinpe": "📱 SINPE",
            "transferencia": "🏦 Transferencia",
            "credito": "📋 Crédito",
            "crédito": "📋 Crédito",
        }
        return mapping.get(str(method).lower(), str(method))

    def _money(self, value) -> str:
        try:
            return f"₡{float(value):,.2f}"
        except Exception:
            return "₡0.00"

    def _extract_hour(self, created_at: str) -> str:
        """
        Recibe algo como:
        2026-03-10 14:35
        y devuelve:
        14:35
        """
        if not created_at:
            return "--:--"

        try:
            dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M")
            return dt.strftime("%H:%M")
        except Exception:
            parts = str(created_at).split(" ")
            return parts[-1][:5] if len(parts) > 1 else str(created_at)

    def _pdf_path_for_sale(self, sale_id: int) -> str:
        return os.path.abspath(f"app/pdfs/venta_{sale_id}.pdf")

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def load_today_sales(self):
        try:
            today = QDate.currentDate().toString("yyyy-MM-dd")

            params = {
                "start_date": today,
                "end_date": today,
            }

            from ui.utils.http_worker import api_request
            response = api_request("get", f"{API_URL}/reports/sales/history", params=params)
            response.raise_for_status()

            payload = response.json()
            sales = payload.get("sales", [])

            self.sales_data = sales
            self.tbl_sales.setRowCount(len(sales))

            if not sales:
                self.tbl_sales.clearSelection()
                self.current_sale_id = None
                self.tbl_items.setRowCount(0)
                self.lbl_header.setText("No hay ventas hoy")
                self.lbl_meta.setText("Todavía no se registran ventas en el día actual")
                self.lbl_total.setText("Total: ₡0.00")
                self.lbl_count.setText("0 ventas")
                self._set_detail_enabled(False)
                return

            for row, sale in enumerate(sales):
                sale_id = sale.get("id", "")
                created_at = sale.get("created_at", "")
                customer_name = sale.get("customer_name") or "Cliente general"
                payment_method = sale.get("payment_method") or "-"
                total = sale.get("total", 0)

                self.tbl_sales.setItem(row, 0, QTableWidgetItem(str(sale_id)))
                self.tbl_sales.setItem(row, 1, QTableWidgetItem(self._extract_hour(created_at)))
                self.tbl_sales.setItem(row, 2, QTableWidgetItem(str(customer_name)))
                self.tbl_sales.setItem(row, 3, QTableWidgetItem(self._payment_label(payment_method)))
                self.tbl_sales.setItem(row, 4, QTableWidgetItem(self._money(total)))

            self.tbl_sales.sortItems(0, Qt.DescendingOrder)

            self.lbl_count.setText(f"{len(sales)} venta{'s' if len(sales) != 1 else ''} registradas hoy")

            # Seleccionar la primera automáticamente
            self.tbl_sales.selectRow(0)
            self.on_row_clicked(0, 0)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudieron cargar las ventas del día:\n{e}")

    def on_row_clicked(self, row, _column):
        try:
            item = self.tbl_sales.item(row, 0)
            if not item:
                return

            sale_id = int(item.text())
            self.current_sale_id = sale_id

            response = api_request("get", f"{API_URL}/reports/sales/{sale_id}")
            response.raise_for_status()

            data = response.json()

            self.lbl_header.setText(f"Venta #{data['id']} — {data['created_at']}")
            self.lbl_meta.setText(
                f"Cliente: <b>{data.get('customer_name', 'Cliente general')}</b>"
                f" &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"Pago: <b>{data.get('payment_method', '-')}</b>"
                f" &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"Estado: <b>{data.get('status', 'aprobada')}</b>"
            )

            items = data.get("items", [])
            self.tbl_items.setRowCount(len(items))

            for i, it in enumerate(items):
                product_name = str(it.get("product_name", "—"))
                quantity = str(it.get("quantity", 0))
                price = self._money(it.get("price", 0))
                subtotal = self._money(it.get("subtotal", 0))

                name_item = QTableWidgetItem(product_name)
                # ✅ PRODUCTO COMÚN: resaltar con color diferente
                if it.get("is_common", False):
                    from PySide6.QtGui import QColor, QBrush
                    name_item.setForeground(QBrush(QColor("#94a3b8")))
                    name_item.setToolTip("Producto común — sin inventario")

                self.tbl_items.setItem(i, 0, name_item)
                self.tbl_items.setItem(i, 1, QTableWidgetItem(quantity))
                self.tbl_items.setItem(i, 2, QTableWidgetItem(price))
                self.tbl_items.setItem(i, 3, QTableWidgetItem(subtotal))

            self.lbl_total.setText(f"Total: {self._money(data.get('total', 0))}")
            self._set_detail_enabled(True)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo cargar el detalle de la venta:\n{e}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def open_pdf(self):
        try:
            if not self.current_sale_id:
                QMessageBox.warning(self, "Atención", "Selecciona una venta.")
                return

            pdf_path = self._pdf_path_for_sale(self.current_sale_id)

            if not os.path.exists(pdf_path):
                reply = QMessageBox.question(
                    self,
                    "PDF no encontrado",
                    f"No existe el PDF para esta venta.\n¿Desea regenerarlo?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply != QMessageBox.Yes:
                    return

                try:
                    resp = api_request(
                        "post",
                        f"{API_URL}/sales/{self.current_sale_id}/regenerate-pdf",
                        timeout=15,
                    )
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
                subprocess.Popen(["xdg-open", pdf_path])
            else:
                QMessageBox.information(self, "PDF", f"Ruta del archivo:\n{pdf_path}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir el PDF:\n{e}")

    def reprint_sale(self):
        try:
            if not self.current_sale_id:
                QMessageBox.warning(self, "Atención", "Selecciona una venta.")
                return

            pdf_path = self._pdf_path_for_sale(self.current_sale_id)

            if not os.path.exists(pdf_path):
                reply = QMessageBox.question(
                    self,
                    "PDF no encontrado",
                    f"No existe el PDF para esta venta.\n¿Desea regenerarlo antes de imprimir?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply != QMessageBox.Yes:
                    return

                try:
                    resp = api_request(
                        "post",
                        f"{API_URL}/sales/{self.current_sale_id}/regenerate-pdf",
                        timeout=15,
                    )
                    resp.raise_for_status()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"No se pudo regenerar el PDF:\n{e}")
                    return

                if not os.path.exists(pdf_path):
                    QMessageBox.warning(self, "Error", "El PDF fue generado pero no se encontró en la ruta esperada.")
                    return

            print_pdf(pdf_path)
            QMessageBox.information(self, "Éxito", "Se envió el comprobante a impresión.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo reimprimir la venta:\n{e}")