from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHBoxLayout, QMessageBox
)
from PySide6.QtCore import Qt, Signal
import os
import subprocess


class SaleSummaryDialog(QDialog):
    # 🧩 Señal para notificar que debe actualizar productos
    sale_closed = Signal()

    def __init__(self, sale_data):
        super().__init__()
        self.sale_data = sale_data
        self.setWindowTitle("🧾 Resumen de venta")
        self.setFixedSize(600, 520)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)

        # 🧾 Título
        title = QLabel("🧾 Resumen de la venta")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px; color: #E8E8E8;")
        layout.addWidget(title)

        # 📋 Información general
        info_label = QLabel(
            f"""
            <b>ID Venta:</b> {self.sale_data.get('sale_id', '—')}<br>
            <b>Cliente:</b> {self.sale_data.get('customer_name', 'Cliente general')}<br>
            <b>Método de pago:</b> {self.sale_data.get('payment_method', '—')}<br>
            <b>Total:</b> ₡{self.sale_data.get('total', 0):,.2f}<br>
            <b>Fecha:</b> {self.sale_data.get('created_at', '—')}
            """
        )
        info_label.setStyleSheet("font-size: 14px; color: #D9D9D9; margin-bottom: 15px;")
        layout.addWidget(info_label)

        # 🧩 Tabla de productos
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Producto", "Cantidad", "Subtotal"])
        items = self.sale_data.get("items", [])
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(str(item.get("name", ""))))
            self.table.setItem(row, 1, QTableWidgetItem(str(item.get("quantity", 0))))
            subtotal = item.get("subtotal", 0)
            self.table.setItem(row, 2, QTableWidgetItem(f"₡{float(subtotal):,.2f}"))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #2C2F33;
                alternate-background-color: #32383E;
                color: #FFFFFF;
                gridline-color: #444;
            }
            QHeaderView::section {
                background-color: #5B9BD5;
                color: white;
                font-weight: bold;
                padding: 4px;
                border: none;
            }
        """)
        layout.addWidget(self.table)

        # --- Botones ---
        btn_layout = QHBoxLayout()
        btn_open_pdf = QPushButton("🖨️ Ver comprobante PDF")
        btn_close = QPushButton("Cerrar y actualizar")

        for b in [btn_open_pdf, btn_close]:
            b.setFixedWidth(220)
            b.setStyleSheet("""
                QPushButton {
                    background-color: #5B9BD5;
                    color: white;
                    font-weight: bold;
                    padding: 8px;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #4A8ACD;
                }
            """)
            btn_layout.addWidget(b)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

        # Eventos
        btn_open_pdf.clicked.connect(self.open_pdf)
        btn_close.clicked.connect(self.close_and_update)

    # --------------------------------------------------------
    # 🖨️ ABRIR PDF
    # --------------------------------------------------------
    def open_pdf(self):
        """Abre el comprobante PDF"""
        pdf_path = self.sale_data.get("pdf")
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "PDF no encontrado", "El comprobante PDF no está disponible.")
            return

        try:
            if os.name == "nt":  # Windows
                os.startfile(pdf_path)
            elif os.name == "posix":  # macOS / Linux
                subprocess.Popen(["xdg-open", pdf_path])
            else:
                QMessageBox.information(self, "Info", f"Ruta del PDF: {pdf_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir el PDF:\n{e}")

    # --------------------------------------------------------
    # 🔁 CERRAR Y ACTUALIZAR
    # --------------------------------------------------------
    def close_and_update(self):
        """Emite la señal para refrescar inventario y cierra"""
        self.sale_closed.emit()
        self.close()
