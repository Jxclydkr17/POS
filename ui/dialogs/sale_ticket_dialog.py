from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QFrame, QHBoxLayout, QMessageBox
)
from PySide6.QtCore import Qt
import os
import subprocess
import webbrowser
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class SaleTicketDialog(QDialog):
    def __init__(self, sale_data):
        super().__init__()
        self.sale_data = sale_data
        self.setWindowTitle("Ticket de venta")
        self.setFixedSize(400, 580)
        self.setStyleSheet("""
            QDialog {
                background-color: #fefefe;
            }
            QLabel {
                font-family: 'Consolas';
                color: #333;
            }
        """)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)

        # --- Encabezado ---
        header = QLabel("<b>🧾 FERRETERÍA AGROMATINA</b>")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #222;")
        layout.addWidget(header)

        date_str = self.sale_data.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
        layout.addWidget(QLabel(f"<center>{date_str}</center>"))

        layout.addWidget(self.divider())

        # --- Datos principales ---
        info = f"""
        <b>ID Venta:</b> {self.sale_data['sale_id']}<br>
        <b>Cliente:</b> {self.sale_data.get('customer_name', 'Cliente general')}<br>
        <b>Método:</b> {self.sale_data['payment_method']}<br>
        """
        info_label = QLabel(info)
        info_label.setAlignment(Qt.AlignLeft)
        layout.addWidget(info_label)

        layout.addWidget(self.divider())

        # --- Lista de productos ---
        layout.addWidget(QLabel("<b>Productos:</b>"))
        for item in self.sale_data["items"]:
            line = QLabel(f"{item['name']}  x{item['quantity']}   ₡{item['subtotal']:.2f}")
            line.setAlignment(Qt.AlignLeft)
            layout.addWidget(line)

        layout.addWidget(self.divider())

        # --- Total ---
        total_label = QLabel(f"<b>Total:</b> ₡{self.sale_data['total']:,.2f}")
        total_label.setAlignment(Qt.AlignRight)
        total_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #111;")
        layout.addWidget(total_label)

        # --- Mostrar pago y cambio si aplica ---
        if "amount_paid" in self.sale_data:
            layout.addWidget(QLabel(f"Pagó con: ₡{self.sale_data['amount_paid']:,.2f}"))
        if "change" in self.sale_data:
            layout.addWidget(QLabel(f"Cambio: ₡{self.sale_data['change']:,.2f}"))

        layout.addWidget(self.divider())

        # --- Botones de acción ---
        btn_layout = QHBoxLayout()

        btn_pdf = QPushButton("📄 Ver comprobante")
        btn_pdf.setFixedWidth(160)

        btn_print = QPushButton("🧾 Imprimir ticket")
        btn_print.setFixedWidth(160)

        btn_close = QPushButton("🆕 Nueva venta")
        btn_close.setFixedWidth(140)

        # --- Estilos por color ---
        btn_pdf.setStyleSheet("""
            QPushButton {
                background-color: #17A2B8;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #138496;
            }
        """)

        btn_print.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)

        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #FFC107;
                color: black;
                font-weight: bold;
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #E0A800;
                color: white;
            }
        """)

        # --- Añadir botones ---
        btn_layout.addWidget(btn_pdf)
        btn_layout.addWidget(btn_print)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        # --- Conexiones ---
        btn_pdf.clicked.connect(self.open_pdf)
        btn_print.clicked.connect(self.print_ticket)
        btn_close.clicked.connect(self.accept)

        # --- Pie ---
        layout.addStretch()
        footer = QLabel("<center>¡Gracias por su compra! 🙌</center>")
        footer.setStyleSheet("font-size: 12px; color: #777; margin-top: 10px;")
        layout.addWidget(footer)

        self.setLayout(layout)

    def divider(self):
        """Línea separadora"""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("color: #ccc;")
        return line

    # -------------------------------------------------------
    # 📄 Abrir comprobante PDF
    # -------------------------------------------------------
    def open_pdf(self):
        """Abre el comprobante PDF o muestra aviso si no existe"""
        pdf_path = self.sale_data.get("pdf")

        if not pdf_path:
            QMessageBox.information(
                self,
                "Comprobante no disponible",
                "El comprobante PDF aún no se ha generado en el servidor."
            )
            return

        # Si el backend devuelve una URL
        if pdf_path.startswith("http"):
            webbrowser.open(pdf_path)
            return

        # Si es una ruta local
        if not os.path.exists(pdf_path):
            QMessageBox.warning(self, "PDF no encontrado", "El archivo PDF no está disponible localmente.")
            return

        try:
            if os.name == "nt":  # Windows
                os.startfile(pdf_path)
            elif os.name == "posix":
                subprocess.run(["xdg-open", pdf_path])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir el PDF:\n{e}")

    # -------------------------------------------------------
    # 🖨️ Imprimir ticket
    # -------------------------------------------------------
    def print_ticket(self):
        """Imprimir el ticket via el flujo del sistema operativo.

        FASE 2 — Fix 2.5:
          Antes esta función importaba `print_sale_ticket` de
          app.utils.print_ticket — pero esa función no existe (referencia
          muerta a una refactorización pasada), así que el botón "Imprimir"
          siempre tiraba ImportError.

          La idea original era enviar el PDF crudo al puerto 9100 de la
          impresora térmica configurada, lo cual NO funciona (las térmicas
          POS no interpretan PDF; producen caracteres aleatorios o se
          cuelgan — ver Fix 2.5 en app/utils/print_ticket.py).

          Hasta que se implemente generación ESC/POS, este botón abre el
          PDF en el flujo de impresión nativo del SO (`os.startfile(pdf,
          "print")` en Windows, `lp`/`lpr` en macOS/Linux). El usuario
          selecciona la impresora desde el diálogo del SO.
        """
        try:
            # Lee la config solo para respetar printer_type == "none"
            # (desactivación explícita). Para el resto, vamos al PDF.
            printer_config = self._get_printer_config()
            if printer_config["type"] == "none":
                QMessageBox.information(
                    self, "Impresión deshabilitada",
                    "La impresión está deshabilitada en Configuración → Impresora."
                )
                return

            pdf_path = self.sale_data.get("pdf")
            # `pdf` puede ser ruta local o URL (ver open_pdf). Para imprimir
            # vía SO necesitamos una ruta local existente.
            if not pdf_path or (isinstance(pdf_path, str) and pdf_path.startswith("http")):
                QMessageBox.warning(
                    self, "PDF no disponible",
                    "El comprobante PDF aún no se generó localmente.\n"
                    "Reintente en unos segundos o use el botón 'Abrir PDF'."
                )
                return
            if not os.path.exists(pdf_path):
                QMessageBox.warning(
                    self, "PDF no encontrado",
                    "El archivo PDF no se encuentra en el disco. "
                    "Regenérelo desde el listado de ventas."
                )
                return

            from app.utils.print_ticket import print_pdf
            print_pdf(pdf_path)
            QMessageBox.information(
                self, "Enviado a impresora",
                "Ticket enviado a la impresora del sistema operativo."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo imprimir el ticket:\n{e}")

    def _get_printer_config(self) -> dict:
        """Obtiene la configuración de impresora desde la API.
        Si falla, usa valores de respaldo."""
        try:
            from ui.services.settings_service import fetch_settings
            data = fetch_settings()
            p_type = data.get("printer_type", "network") or "network"
            p_ip = data.get("printer_ip", "192.168.0.120") or "192.168.0.120"
            p_port = data.get("printer_port", 9100) or 9100
            return {
                "type": p_type,
                "info": {"ip": p_ip, "port": int(p_port)}
            }
        except Exception as e:
            logger.warning(f"No se pudo leer config de impresora, usando defaults: {e}")
            return {
                "type": "network",
                "info": {"ip": "192.168.0.120", "port": 9100}
            }