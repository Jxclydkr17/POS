# ui/dialogs/proforma_detail_dialog.py
"""
Diálogo de detalle de proforma con flujo de conversión mejorado.
Al convertir: primero pre-valida stock/precios, muestra resumen de
discrepancias, y permite al usuario decidir antes de confirmar.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QMessageBox, QComboBox, QSpinBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
import logging
import os
import subprocess

from ui.api import BASE_URL
from ui.session_manager import session
from ui.components.toast_notifier import show_toast
from ui.utils.http_worker import api_call

logger = logging.getLogger(__name__)

API_PROFORMAS = f"{BASE_URL}/proformas"

STATUS_COLORS = {
    "VIGENTE": "#16a34a",
    "VENCIDA": "#dc2626",
    "CONVERTIDA": "#2563eb",
    "ANULADA": "#6b7280",
}


class ProformaDetailDialog(QDialog):
    def __init__(self, proforma_id, parent=None, auto_convert=False):
        super().__init__(parent)
        self.proforma_id = proforma_id
        self.auto_convert = auto_convert
        self.proforma_data = None

        self.setWindowTitle("📋 Detalle de proforma")
        self.setMinimumSize(780, 620)
        self.resize(840, 680)

        self._build_ui()
        self._load_data()

        if self.auto_convert and self.proforma_data:
            if self.proforma_data.get("status") == "VIGENTE":
                self._start_conversion()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {session.token}"}

    # ══════════════════════════════════════════════════
    # UI
    # ══════════════════════════════════════════════════
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── Header ──
        self.lbl_title = QLabel("📋 Proforma")
        self.lbl_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(self.lbl_title)

        self.lbl_meta = QLabel("")
        self.lbl_meta.setStyleSheet("color: #94a3b8; font-size: 13px;")
        self.lbl_meta.setWordWrap(True)
        root.addWidget(self.lbl_meta)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #1f2937;")
        root.addWidget(line)

        # ── Tabla de productos ──
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Producto", "Cant.", "P. Unit.", "Desc. %", "Impuesto", "Subtotal",
        ])
        self.table.setStyleSheet(
            "QTableWidget{background:#0b1220;color:#e5e7eb;border:1px solid #1f2937;border-radius:8px;}"
            "QHeaderView::section{background:#111827;color:#e5e7eb;border:none;padding:5px;font-weight:bold;}"
            "QTableWidget::item{padding:5px;}"
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        # ── Total ──
        self.lbl_total = QLabel("Total: ₡0,00")
        self.lbl_total.setStyleSheet("font-size: 16px; font-weight: bold; color: #16a34a;")
        self.lbl_total.setAlignment(Qt.AlignRight)
        root.addWidget(self.lbl_total)

        # ── Notas ──
        self.lbl_notes = QLabel("")
        self.lbl_notes.setWordWrap(True)
        self.lbl_notes.setStyleSheet(
            "background:#111827;color:#cbd5e1;border:1px solid #1f2937;"
            "border-radius:6px;padding:8px;font-size:12px;"
        )
        self.lbl_notes.hide()
        root.addWidget(self.lbl_notes)

        # ── Panel de validación (oculto hasta que se valide) ──
        self.validation_frame = QFrame()
        self.validation_frame.setStyleSheet(
            "QFrame{background:#0f172a;border:1px solid #1f2937;border-radius:8px;padding:10px;}"
        )
        vf_layout = QVBoxLayout(self.validation_frame)
        vf_layout.setSpacing(6)

        self.lbl_validation_title = QLabel("")
        self.lbl_validation_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        vf_layout.addWidget(self.lbl_validation_title)

        self.validation_table = QTableWidget()
        self.validation_table.setColumnCount(5)
        self.validation_table.setHorizontalHeaderLabels([
            "Producto", "Estado", "Stock", "Precio proforma", "Precio actual",
        ])
        self.validation_table.setStyleSheet(
            "QTableWidget{background:#111827;color:#e5e7eb;border:1px solid #1e293b;border-radius:6px;}"
            "QHeaderView::section{background:#1e293b;color:#94a3b8;border:none;padding:4px;font-size:11px;}"
            "QTableWidget::item{padding:4px;font-size:12px;}"
        )
        self.validation_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.validation_table.setSelectionMode(QTableWidget.NoSelection)
        self.validation_table.verticalHeader().setVisible(False)
        self.validation_table.setMaximumHeight(160)
        vhdr = self.validation_table.horizontalHeader()
        vhdr.setSectionResizeMode(0, QHeaderView.Stretch)
        vf_layout.addWidget(self.validation_table)

        # Opciones de pago (dentro del panel de validación)
        pay_row = QHBoxLayout()
        pay_row.setSpacing(8)

        pay_row.addWidget(QLabel("Pago:"))
        self.cmb_payment = QComboBox()
        self.cmb_payment.addItems(["Efectivo", "Tarjeta", "SINPE", "Transferencia", "Crédito"])
        self.cmb_payment.setFixedWidth(130)
        pay_row.addWidget(self.cmb_payment)

        pay_row.addWidget(QLabel("Documento:"))
        self.cmb_doctype = QComboBox()
        self.cmb_doctype.addItem("Tiquete electrónico", "04")
        self.cmb_doctype.addItem("Factura electrónica", "01")
        self.cmb_doctype.setFixedWidth(180)
        pay_row.addWidget(self.cmb_doctype)

        self.lbl_credit_days = QLabel("Días crédito:")
        self.spn_credit_days = QSpinBox()
        self.spn_credit_days.setRange(1, 365)
        self.spn_credit_days.setValue(30)
        self.spn_credit_days.setFixedWidth(70)
        self.lbl_credit_days.hide()
        self.spn_credit_days.hide()
        pay_row.addWidget(self.lbl_credit_days)
        pay_row.addWidget(self.spn_credit_days)
        pay_row.addStretch()

        self.cmb_payment.currentTextChanged.connect(self._on_payment_changed)
        vf_layout.addLayout(pay_row)

        # Botones dentro del panel de validación
        vbtn_row = QHBoxLayout()
        vbtn_row.setSpacing(8)

        self.btn_edit_proforma = QPushButton("✏️ Editar proforma")
        self.btn_edit_proforma.setStyleSheet(
            "QPushButton{background:#f59e0b;color:white;padding:7px 14px;"
            "font-weight:600;border-radius:8px;}"
            "QPushButton:hover{background:#d97706;}"
        )
        self.btn_edit_proforma.clicked.connect(self._go_edit_proforma)
        vbtn_row.addWidget(self.btn_edit_proforma)

        self.btn_cancel_convert = QPushButton("❌ Cancelar")
        self.btn_cancel_convert.setStyleSheet(
            "QPushButton{background:#334155;color:white;padding:7px 14px;border-radius:8px;}"
            "QPushButton:hover{background:#475569;}"
        )
        self.btn_cancel_convert.clicked.connect(self._cancel_conversion)
        vbtn_row.addWidget(self.btn_cancel_convert)

        vbtn_row.addStretch()

        self.btn_confirm_convert = QPushButton("✅ Confirmar conversión a venta")
        self.btn_confirm_convert.setStyleSheet(
            "QPushButton{background:#16a34a;color:white;padding:7px 14px;"
            "font-weight:700;border-radius:8px;}"
            "QPushButton:hover{background:#15803d;}"
        )
        self.btn_confirm_convert.clicked.connect(self._do_convert)
        vbtn_row.addWidget(self.btn_confirm_convert)

        vf_layout.addLayout(vbtn_row)

        self.validation_frame.hide()
        root.addWidget(self.validation_frame)

        # ── Botones principales ──
        btns = QHBoxLayout()
        btns.setSpacing(8)

        self.btn_pdf = QPushButton("📄 Descargar PDF")
        self.btn_pdf.setStyleSheet(
            "QPushButton{background:#334155;color:white;padding:8px 14px;border-radius:8px;}"
            "QPushButton:hover{background:#475569;}"
        )
        self.btn_pdf.clicked.connect(self._download_pdf)
        btns.addWidget(self.btn_pdf)

        self.btn_email = QPushButton("📧 Enviar email")
        self.btn_email.setStyleSheet(
            "QPushButton{background:#334155;color:white;padding:8px 14px;border-radius:8px;}"
            "QPushButton:hover{background:#475569;}"
        )
        self.btn_email.clicked.connect(self._send_email)
        btns.addWidget(self.btn_email)

        btns.addStretch()

        self.btn_convert = QPushButton("🛒 Convertir a venta")
        self.btn_convert.setStyleSheet(
            "QPushButton{background:#2563eb;color:white;padding:8px 14px;"
            "font-weight:700;border-radius:8px;}"
            "QPushButton:hover{background:#1d4ed8;}"
        )
        self.btn_convert.clicked.connect(self._start_conversion)
        btns.addWidget(self.btn_convert)

        btn_close = QPushButton("Cerrar")
        btn_close.setStyleSheet(
            "QPushButton{background:#334155;color:white;padding:8px 14px;border-radius:8px;}"
            "QPushButton:hover{background:#475569;}"
        )
        btn_close.clicked.connect(self.close)
        btns.addWidget(btn_close)

        root.addLayout(btns)

        self.setStyleSheet("QDialog { background-color: #080d1a; }")

    # ══════════════════════════════════════════════════
    # CARGAR DATOS
    # ══════════════════════════════════════════════════
    def _load_data(self):
        api_call(
            "get", f"{API_PROFORMAS}/{self.proforma_id}",
            headers=self._auth_headers(),
            on_success=self._on_data_loaded,
            on_error=lambda msg: QMessageBox.warning(self, "Error", f"No se pudo cargar la proforma: {msg}"),
        )

    def _on_data_loaded(self, data):
        try:
            self.proforma_data = data

            number = data.get("number", "")
            status = data.get("status", "")
            color = STATUS_COLORS.get(status, "#e5e7eb")

            self.lbl_title.setText(f"📋 Proforma {number}")

            customer = data.get("customer_name", "Cliente General")
            created = str(data.get("created_at", ""))[:16].replace("T", " ")
            valid_until = str(data.get("valid_until", ""))[:10]
            validity_days = data.get("validity_days", "")
            converted_id = data.get("converted_sale_id")

            meta = (
                f"<b>Cliente:</b> {customer} &nbsp;│&nbsp; "
                f"<b>Estado:</b> <span style='color:{color}'>{status}</span> &nbsp;│&nbsp; "
                f"<b>Creada:</b> {created} &nbsp;│&nbsp; "
                f"<b>Válida hasta:</b> {valid_until} ({validity_days} días)"
            )
            if converted_id:
                meta += f" &nbsp;│&nbsp; <b>Venta:</b> #{converted_id}"

            self.lbl_meta.setText(meta)

            # Tabla
            details = data.get("details", [])
            self.table.setRowCount(len(details))
            for row, d in enumerate(details):
                name = d.get("product_name", "")
                if d.get("is_common"):
                    name = f"📦 {d.get('common_description', name)}"

                self.table.setItem(row, 0, QTableWidgetItem(name))
                self.table.setItem(row, 1, QTableWidgetItem(str(d.get("quantity", 0))))

                price_item = QTableWidgetItem(f"₡{float(d.get('unit_price', 0)):,.2f}")
                price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, 2, price_item)

                disc = d.get("discount_percent", 0)
                self.table.setItem(row, 3, QTableWidgetItem(f"{disc:.1f}%" if disc else "—"))

                tax = d.get("tax_rate", 0)
                self.table.setItem(row, 4, QTableWidgetItem(f"{tax:.0f}%" if tax else "—"))

                sub_item = QTableWidgetItem(f"₡{float(d.get('subtotal', 0)):,.2f}")
                sub_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, 5, sub_item)

            total = data.get("total", 0)
            self.lbl_total.setText(f"Total: ₡{float(total):,.2f}")

            # Notas
            notes = data.get("notes")
            if notes and notes.strip():
                self.lbl_notes.setText(f"📝 {notes}")
                self.lbl_notes.show()

            # Mostrar/ocultar botón convertir según estado
            can_convert = status == "VIGENTE"
            self.btn_convert.setVisible(can_convert)

        except Exception as e:
            logger.error(f"Error cargando detalle: {e}")
            QMessageBox.warning(self, "Error", f"Error de conexión: {e}")

    # ══════════════════════════════════════════════════
    # FLUJO DE CONVERSIÓN (PRE-VALIDACIÓN)
    # ══════════════════════════════════════════════════
    def _on_payment_changed(self, text):
        is_credit = text.lower() in ("crédito", "credito")
        self.lbl_credit_days.setVisible(is_credit)
        self.spn_credit_days.setVisible(is_credit)

    def _start_conversion(self):
        """
        Paso 1: Llama al endpoint de pre-validación para revisar
        stock y precios ANTES de comprometerse.
        """
        api_call(
            "get", f"{API_PROFORMAS}/{self.proforma_id}/validate-conversion",
            headers=self._auth_headers(),
            on_success=self._show_validation_results,
            on_error=lambda msg: QMessageBox.warning(self, "Error de validación", msg),
        )

    def _show_validation_results(self, validation):
        """
        Paso 2: Muestra el panel de validación con resumen línea por línea.
        """
        can_convert = validation.get("can_convert", False)
        issues = validation.get("issues", [])
        summary = validation.get("summary", {})

        ok = summary.get("ok_lines", 0)
        warns = summary.get("warning_lines", 0)
        blocks = summary.get("blocking_lines", 0)
        total_lines = summary.get("total_lines", 0)

        # Título del panel
        if blocks > 0:
            self.lbl_validation_title.setText(
                f"🚫 No se puede convertir — {blocks} producto(s) con problemas bloqueantes"
            )
            self.lbl_validation_title.setStyleSheet(
                "font-size: 14px; font-weight: 700; color: #ef4444;"
            )
        elif warns > 0:
            self.lbl_validation_title.setText(
                f"⚠️ {warns} producto(s) con cambio de precio — {ok} OK"
            )
            self.lbl_validation_title.setStyleSheet(
                "font-size: 14px; font-weight: 700; color: #f59e0b;"
            )
        else:
            self.lbl_validation_title.setText(
                f"✅ Todo en orden — {total_lines} producto(s) listos"
            )
            self.lbl_validation_title.setStyleSheet(
                "font-size: 14px; font-weight: 700; color: #16a34a;"
            )

        # Poblar tabla de validación (solo issues)
        if issues:
            self.validation_table.setRowCount(len(issues))
            for row, issue in enumerate(issues):
                # Nombre
                self.validation_table.setItem(
                    row, 0, QTableWidgetItem(issue.get("product_name", ""))
                )

                # Estado (coloreado)
                itype = issue.get("type", "")
                blocking = issue.get("blocking", False)

                if itype == "stock":
                    status_text = "❌ Sin stock"
                    bg_color = "#7f1d1d"
                elif itype == "price":
                    status_text = "⚠️ Precio cambió"
                    bg_color = "#78350f"
                elif itype == "inactive":
                    status_text = "❌ Desactivado"
                    bg_color = "#7f1d1d"
                elif itype == "not_found":
                    status_text = "❌ No existe"
                    bg_color = "#7f1d1d"
                else:
                    status_text = "❌ " + itype
                    bg_color = "#7f1d1d"

                status_item = QTableWidgetItem(status_text)
                status_item.setBackground(QColor(bg_color))
                self.validation_table.setItem(row, 1, status_item)

                # Stock
                avail = issue.get("available_stock")
                needed = issue.get("proforma_qty", 0)
                stock_text = f"{avail}/{needed}" if avail is not None else "—"
                self.validation_table.setItem(row, 2, QTableWidgetItem(stock_text))

                # Precio proforma
                pp = issue.get("proforma_price", 0)
                self.validation_table.setItem(
                    row, 3, QTableWidgetItem(f"₡{pp:,.2f}")
                )

                # Precio actual
                cp = issue.get("current_price")
                cp_text = f"₡{cp:,.2f}" if cp is not None else "—"
                self.validation_table.setItem(row, 4, QTableWidgetItem(cp_text))

            self.validation_table.show()
        else:
            self.validation_table.setRowCount(0)
            self.validation_table.hide()

        # Habilitar/deshabilitar botones
        self.btn_confirm_convert.setEnabled(can_convert)
        self.btn_confirm_convert.setStyleSheet(
            "QPushButton{background:%s;color:white;padding:7px 14px;"
            "font-weight:700;border-radius:8px;}"
            "QPushButton:hover{background:%s;}" % (
                ("#16a34a", "#15803d") if can_convert else ("#4b5563", "#4b5563")
            )
        )

        self.btn_edit_proforma.setVisible(blocks > 0)

        # Mostrar panel, ocultar botón principal
        self.validation_frame.show()
        self.btn_convert.hide()

    def _cancel_conversion(self):
        """Cierra el panel de validación sin convertir."""
        self.validation_frame.hide()
        if self.proforma_data and self.proforma_data.get("status") == "VIGENTE":
            self.btn_convert.show()

    def _go_edit_proforma(self):
        """Abre el diálogo de edición de la proforma."""
        self.validation_frame.hide()
        self.close()
        # Señal para que el parent abra el editor
        parent = self.parent()
        if parent and hasattr(parent, "edit_proforma"):
            parent.edit_proforma(self.proforma_id)

    def _do_convert(self):
        """
        Paso 3: Ejecuta la conversión real llamando a POST /convert.
        """
        confirm = QMessageBox.question(
            self, "Confirmar conversión",
            "¿Convertir esta proforma en una venta real?\n\n"
            "Se descontará inventario y se generará factura electrónica.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        payment = self.cmb_payment.currentText()
        doctype = self.cmb_doctype.currentData()

        payload = {
            "payment_method": payment,
            "document_type": doctype,
        }

        if payment.lower() in ("crédito", "credito"):
            payload["credit_days"] = self.spn_credit_days.value()
            payload["condicion_venta_code"] = "02"

        api_call(
            "post", f"{API_PROFORMAS}/{self.proforma_id}/convert",
            json=payload, headers=self._auth_headers(),
            on_success=self._on_converted,
            on_error=lambda msg: QMessageBox.warning(self, "Error al convertir", msg),
        )

    def _on_converted(self, data):
        try:
            if True:
                sale_info = data.get("sale", {})
                sale_id = sale_info.get("id", "?")
                msg = data.get("message", "Convertida exitosamente")

                warnings = data.get("price_warnings", [])
                if warnings:
                    warn_text = "\n".join(f"• {w}" for w in warnings)
                    QMessageBox.information(
                        self, "Venta creada con avisos",
                        f"{msg}\nVenta #{sale_id}\n\n⚠️ Cambios de precio:\n{warn_text}",
                    )
                else:
                    show_toast(
                        f"✅ {msg} — Venta #{sale_id}",
                        success=True,
                        parent=self.parent(),
                    )

                self.validation_frame.hide()
                self._load_data()  # recargar para mostrar estado CONVERTIDA

        except Exception as e:
            logger.error(f"Error procesando conversión: {e}")

    # ══════════════════════════════════════════════════
    # PDF / EMAIL
    # ══════════════════════════════════════════════════
    def _download_pdf(self):
        from ui.utils.http_worker import run_async
        run_async(
            self._fetch_pdf_data,
            on_success=self._on_pdf_downloaded,
            on_error=lambda msg: show_toast("Error de conexión", success=False, parent=self),
        )

    def _fetch_pdf_data(self):
        import requests as _requests
        resp = _requests.get(
            f"{API_PROFORMAS}/{self.proforma_id}/pdf",
            headers=self._auth_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.content
        return None

    def _on_pdf_downloaded(self, content):
        try:
            if content:
                tmp_path = os.path.join(
                    os.path.expanduser("~"),
                    f"proforma_{self.proforma_id}.pdf",
                )
                with open(tmp_path, "wb") as f:
                    f.write(content)

                if os.name == "nt":
                    os.startfile(tmp_path)
                else:
                    subprocess.Popen(["xdg-open", tmp_path])

                show_toast("PDF descargado", success=True, parent=self)
            else:
                show_toast("Error al generar PDF", success=False, parent=self)
        except Exception as e:
            logger.error(f"Error PDF: {e}")
            show_toast("Error de conexión", success=False, parent=self)

    def _send_email(self):
        confirm = QMessageBox.question(
            self, "Enviar email",
            "¿Enviar esta proforma por correo al cliente?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        api_call(
            "post", f"{API_PROFORMAS}/{self.proforma_id}/send-email",
            headers=self._auth_headers(),
            on_success=lambda data: show_toast(data.get("message", "Email enviado") if isinstance(data, dict) else "Email enviado", success=True, parent=self),
            on_error=lambda msg: QMessageBox.warning(self, "Error", msg),
        )