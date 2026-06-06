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
        """
        Imprimir el ticket de venta respetando la configuración de
        impresora (Settings → Impresora).

        FASE 2 — Fix 2.5 (cerrado):
          - 'network' / 'usb': se genera el ticket como comandos ESC/POS
            y se envía directo a la impresora térmica configurada.
          - 'none': muestra mensaje "deshabilitada".
          - cualquier otra cosa o falla de config: fallback a imprimir
            el PDF via el flujo del sistema operativo.

        El path ESC/POS reemplaza al viejo intento de mandar PDF crudo
        al puerto 9100, que no funcionaba (las térmicas POS no entienden
        PDF). Ahora la app produce comandos ESC/POS válidos (vía
        python-escpos) y los envía por TCP o USB.
        """
        try:
            printer_config = self._get_printer_config()
            p_type = (printer_config.get("type") or "").lower()

            if p_type == "none":
                QMessageBox.information(
                    self, "Impresión deshabilitada",
                    "La impresión está deshabilitada en Configuración → Impresora."
                )
                return

            # Camino térmico directo (ESC/POS): system / network / usb
            if p_type in ("system", "network", "usb"):
                if self._try_print_thermal(printer_config):
                    return  # éxito — terminamos
                # _try_print_thermal devolvió False → ya mostró el error
                # al usuario y opcionalmente le ofreció caer al PDF. Si
                # llegamos acá es porque el usuario eligió no usar el
                # fallback PDF.
                return

            # Cualquier otro p_type → PDF via SO
            self._print_via_system(printer_config)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo imprimir el ticket:\n{e}")

    # -------------------------------------------------------
    # ESC/POS directo (Fix 2.5 cerrado)
    # -------------------------------------------------------
    def _try_print_thermal(self, printer_config: dict) -> bool:
        """
        Intenta imprimir el ticket via ESC/POS (TCP o USB).

        Returns:
            True  si la impresión fue exitosa.
            False si falló y el usuario NO eligió fallback a PDF.

        Si la impresión térmica falla, ofrece al usuario imprimir el
        PDF via SO como fallback — útil cuando la impresora térmica
        está apagada o desconectada y hay otra impresora disponible.
        """

        p_type = (printer_config.get("type") or "").lower()
        info = printer_config.get("info") or {}
        paper_width = int(info.get("paper_width_mm") or 80)
        profile = info.get("profile") or None

        try:
            from app.utils.escpos_ticket import build_sale_ticket_bytes
            from app.utils.print_ticket import (
                print_to_thermal, print_to_thermal_usb, print_to_system_printer,
            )

            # Normalizar Decimal en items (vienen del backend) para
            # build_sale_ticket_bytes — la función ya tolera Decimal/float/str.
            data = build_sale_ticket_bytes(
                self.sale_data,
                business_name=info.get("business_name") or "Mi Negocio",
                business_id=info.get("business_id"),
                business_address=info.get("business_address"),
                business_phone=info.get("business_phone"),
                paper_width_mm=paper_width,
                profile=profile,
            )

            if p_type == "system":
                # RAW por el spooler del SO eligiendo por nombre. Si el
                # nombre está vacío, usa la impresora predeterminada.
                print_to_system_printer(
                    data,
                    printer_name=info.get("system_name") or None,
                    profile=profile,
                )
            elif p_type == "network":
                ip = info.get("ip")
                port = int(info.get("port") or 9100)
                if not ip:
                    raise ValueError(
                        "La impresora de red no tiene IP configurada. "
                        "Configure la IP en Settings → Impresora."
                    )
                print_to_thermal(data, ip=ip, port=port)
            elif p_type == "usb":
                vid = info.get("usb_vendor_id")
                pid = info.get("usb_product_id")
                if vid is None or pid is None:
                    raise ValueError(
                        "La impresora USB no tiene Vendor/Product ID "
                        "configurados. Configúrelos en Settings → Impresora."
                    )
                print_to_thermal_usb(
                    data,
                    vendor_id=vid,
                    product_id=pid,
                    profile=profile,
                )
            else:
                # Defensivo — _print_via_system maneja todo lo demás
                return False

            QMessageBox.information(
                self, "Ticket impreso",
                "Ticket enviado a la impresora térmica."
            )
            return True

        except Exception as e:
            logger.warning(f"Fallo en impresión térmica: {e}")
            reply = QMessageBox.question(
                self, "Error de impresión térmica",
                f"No se pudo imprimir en la impresora térmica:\n\n{e}\n\n"
                "¿Querés intentar imprimir el PDF en una impresora del "
                "sistema (cuadro de impresión nativo del SO)?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                try:
                    self._print_via_system(printer_config)
                    return True
                except Exception as e2:
                    QMessageBox.critical(
                        self, "Error",
                        f"Tampoco se pudo imprimir el PDF:\n{e2}"
                    )
            return False

    # -------------------------------------------------------
    # PDF via SO (fallback / camino default cuando no hay térmica)
    # -------------------------------------------------------
    def _print_via_system(self, printer_config: dict) -> None:
        """Imprime el PDF del comprobante vía el spool del SO."""
        pdf_path = self.sale_data.get("pdf")
        # `pdf` puede ser ruta local o URL (ver open_pdf). Para imprimir
        # vía SO necesitamos una ruta local existente.
        if not pdf_path or (isinstance(pdf_path, str) and pdf_path.startswith("http")):
            QMessageBox.warning(
                self, "PDF no disponible",
                "El comprobante PDF aún no se generó localmente.\n"
                "Reintente en unos segundos o use el botón 'Ver comprobante'."
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

    def _get_printer_config(self) -> dict:
        """
        Lee la configuración de impresora desde la API.

        Devuelve un dict con:
            type: 'network' | 'usb' | 'none' | (fallback 'network')
            info: dict con
                ip, port (network)
                usb_vendor_id, usb_product_id (usb, en int)
                profile, paper_width_mm
                business_name, business_id, business_address, business_phone

        Si la API falla, devuelve un fallback seguro a 'network' con
        defaults para que el botón "Imprimir" haga algo razonable.
        """
        try:
            from ui.services.settings_service import fetch_settings
            data = fetch_settings()
            p_type = data.get("printer_type", "network") or "network"

            # Parser de USB IDs (vienen del backend como hex string).
            def _parse_usb_id(v):
                if v is None or v == "":
                    return None
                s = str(v).strip().lower()
                if s.startswith("0x"):
                    s = s[2:]
                try:
                    return int(s, 16)
                except ValueError:
                    return None

            return {
                "type": p_type,
                "info": {
                    "ip": data.get("printer_ip", "192.168.0.120") or "192.168.0.120",
                    "port": int(data.get("printer_port") or 9100),
                    "system_name": data.get("printer_system_name") or None,
                    "usb_vendor_id": _parse_usb_id(data.get("printer_usb_vendor_id")),
                    "usb_product_id": _parse_usb_id(data.get("printer_usb_product_id")),
                    "profile": data.get("printer_profile") or None,
                    "paper_width_mm": int(data.get("printer_paper_width_mm") or 80),
                    # Datos del negocio (para la cabecera del ticket ESC/POS).
                    "business_name": data.get("business_name") or "Mi Negocio",
                    "business_id": data.get("id_number"),
                    "business_address": data.get("address"),
                    "business_phone": data.get("phone"),
                },
            }
        except Exception as e:
            logger.warning(f"No se pudo leer config de impresora, usando defaults: {e}")
            return {
                "type": "network",
                "info": {
                    "ip": "192.168.0.120",
                    "port": 9100,
                    "system_name": None,
                    "usb_vendor_id": None,
                    "usb_product_id": None,
                    "profile": None,
                    "paper_width_mm": 80,
                    "business_name": "Mi Negocio",
                    "business_id": None,
                    "business_address": None,
                    "business_phone": None,
                },
            }