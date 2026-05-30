# ui/views/einvoice_monitor_view.py
"""
FASE 6 — Monitor de Facturación Electrónica

Vista completa con 3 pestañas:
  1. Monitor: tabla de comprobantes con filtros, acciones y KPIs
  2. Configuración Hacienda: credenciales, certificado, test conexión
  3. Diagnóstico: estado XSD, firma, conexión API
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QTabWidget,
    QGroupBox, QFormLayout, QLineEdit, QMessageBox, QFrame, QFileDialog, QTextEdit,
)
from PySide6.QtCore import Qt, QObject, QThread, Signal, QTimer
from PySide6.QtGui import QColor
import requests
import logging

from ui.api import BASE_URL
from ui.session_manager import session
from ui.components.toast_notifier import show_toast
from ui.utils.http_worker import api_call, run_async

logger = logging.getLogger(__name__)

API = BASE_URL


def _headers():
    if not session.token:
        return {}
    return {"Authorization": f"Bearer {session.token}"}


# ════════════════════════════════════════════════════════════
# Workers (QThread)
# ════════════════════════════════════════════════════════════

class _LoadInvoicesWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, status_filter=""):
        super().__init__()
        self._filter = status_filter

    def run(self):
        try:
            params = {}
            if self._filter and self._filter != "Todos":
                params["status"] = self._filter
            r = requests.get(f"{API}/reports/sales/history",
                             params={"limit": 200}, headers=_headers(), timeout=15)
            if r.status_code != 200:
                self.failed.emit(f"HTTP {r.status_code}")
                return

            # Fix 1.3: parsear JSON una sola vez
            data = r.json()
            sales = data if isinstance(data, list) else data.get("data", [])

            # Fix 1.2: obtener einvoices en UN solo request batch
            sale_ids = [s.get("id") for s in sales[:200] if s.get("id")]
            if not sale_ids:
                self.finished.emit([])
                return

            # Construir mapa sale_id → sale para enriquecer después
            sales_map = {s["id"]: s for s in sales[:200] if s.get("id")}

            br = requests.post(
                f"{API}/einvoices/by-sales",
                json={"sale_ids": sale_ids},
                headers=_headers(),
                timeout=15,
            )

            results = []
            if br.status_code == 200:
                einvoices_map = br.json()  # {sale_id: einvoice_data}
                for sid_str, einv in einvoices_map.items():
                    sid = int(sid_str)
                    sale = sales_map.get(sid, {})
                    einv["sale_total"] = sale.get("total", 0)
                    einv["sale_customer"] = sale.get("customer", "")
                    einv["sale_date"] = sale.get("created_at", "")
                    results.append(einv)

            self.finished.emit(results)
        except Exception as e:
            self.failed.emit(str(e))


class _SummaryWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            r = requests.get(f"{API}/einvoices/pending-summary",
                             headers=_headers(), timeout=10)
            if r.status_code == 200:
                self.finished.emit(r.json())
            else:
                self.failed.emit(f"HTTP {r.status_code}")
        except Exception as e:
            self.failed.emit(str(e))


class _ActionWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, url, method="post"):
        super().__init__()
        self._url = url
        self._method = method

    def run(self):
        try:
            fn = requests.post if self._method == "post" else requests.get
            r = fn(self._url, headers=_headers(), timeout=30)
            data = r.json() if r.status_code in (200, 202, 422) else {"error": r.text[:300]}
            data["_http_status"] = r.status_code
            self.finished.emit(data)
        except Exception as e:
            self.failed.emit(str(e))


# ════════════════════════════════════════════════════════════
# Vista principal
# ════════════════════════════════════════════════════════════

STATUS_COLORS = {
    "ACCEPTED": "#27ae60",
    "REJECTED": "#e74c3c",
    "SENT": "#2980b9",
    "XML_READY": "#8e44ad",
    "PENDING": "#95a5a6",
    "SEND_ERROR": "#e67e22",
    "SIGN_ERROR": "#e67e22",
    "XML_UNSIGNED": "#f39c12",
    "XSD_ERROR": "#e74c3c",
    "FAILED": "#c0392b",
}

STATUS_LABELS = {
    "ACCEPTED": "✅ Aceptado",
    "REJECTED": "❌ Rechazado",
    "SENT": "📤 Enviado",
    "XML_READY": "📝 Listo",
    "PENDING": "⏳ Pendiente",
    "SEND_ERROR": "⚠️ Error envío",
    "SIGN_ERROR": "⚠️ Error firma",
    "XML_UNSIGNED": "🔓 Sin firma",
    "XSD_ERROR": "❌ Error XSD",
    "FAILED": "💀 Fallido",
}

DOC_LABELS = {
    "01": "FE", "02": "ND", "03": "NC", "04": "TE", "10": "REP",
}


class EinvoiceMonitorView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = parent
        self._threads = []
        self._init_ui()
        QTimer.singleShot(300, self._load_all)

    # Fix 2.2: Limpieza de threads terminados para evitar memory leak
    def _cleanup_finished_threads(self):
        """Elimina de la lista los threads que ya terminaron."""
        alive = []
        for thread, worker in self._threads:
            if thread.isRunning():
                alive.append((thread, worker))
            else:
                worker.deleteLater()
                thread.deleteLater()
        self._threads = alive

    def closeEvent(self, event):
        """Detiene todos los threads pendientes al cerrar la vista."""
        for thread, worker in self._threads:
            if thread.isRunning():
                thread.quit()
                thread.wait(2000)
            worker.deleteLater()
            thread.deleteLater()
        self._threads.clear()
        super().closeEvent(event)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)

        # Título
        title = QLabel("📋 Facturación Electrónica — Hacienda CR")
        title.setStyleSheet("font-size: 20px; font-weight: bold; margin-bottom: 8px;")
        root.addWidget(title)

        # KPI cards
        self.kpi_frame = QFrame()
        self.kpi_frame.setStyleSheet("QFrame { background: transparent; }")
        kpi_layout = QHBoxLayout(self.kpi_frame)
        kpi_layout.setContentsMargins(0, 0, 0, 8)

        self.kpi_total = self._make_kpi("Total", "0", "#34495e")
        self.kpi_accepted = self._make_kpi("Aceptados", "0", "#27ae60")
        self.kpi_sent = self._make_kpi("Enviados", "0", "#2980b9")
        self.kpi_rejected = self._make_kpi("Rechazados", "0", "#e74c3c")
        self.kpi_pending = self._make_kpi("Pendientes", "0", "#f39c12")

        for kpi in [self.kpi_total, self.kpi_accepted, self.kpi_sent, self.kpi_rejected, self.kpi_pending]:
            kpi_layout.addWidget(kpi)

        root.addWidget(self.kpi_frame)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_monitor_tab(), "📊 Monitor")
        self.tabs.addTab(self._build_config_tab(), "⚙️ Config Hacienda")
        self.tabs.addTab(self._build_diag_tab(), "🔍 Diagnóstico")
        root.addWidget(self.tabs)

    # ── KPI helper ──
    def _make_kpi(self, label, value, color):
        frame = QFrame()
        frame.setMinimumHeight(70)
        frame.setStyleSheet(f"""
            QFrame {{
                background: {color}; border-radius: 8px;
                padding: 10px 8px;
            }}
            QLabel {{ color: white; background: transparent; }}
        """)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        val_lbl = QLabel(value)
        val_lbl.setStyleSheet("font-size: 22px; font-weight: bold;")
        val_lbl.setAlignment(Qt.AlignCenter)
        name_lbl = QLabel(label)
        name_lbl.setStyleSheet("font-size: 12px;")
        name_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(val_lbl)
        lay.addWidget(name_lbl)
        frame._val_lbl = val_lbl
        return frame

    def _set_kpi(self, kpi, value):
        kpi._val_lbl.setText(str(value))

    # ════════════════════════════════════════════════════════
    # Tab 1: Monitor
    # ════════════════════════════════════════════════════════

    def _build_monitor_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        # Filtros
        filters = QHBoxLayout()
        self.cmb_status = QComboBox()
        self.cmb_status.addItems(["Todos", "PENDING", "XML_READY", "SENT", "ACCEPTED", "REJECTED", "SEND_ERROR", "FAILED"])
        self.cmb_status.setFixedWidth(160)

        btn_refresh = QPushButton("🔄 Actualizar")
        btn_refresh.clicked.connect(self._load_all)

        btn_build_all = QPushButton("🔨 Build pendientes")
        btn_build_all.setToolTip("Genera XML para todos los PENDING")
        btn_build_all.clicked.connect(self._build_all_pending)

        filters.addWidget(QLabel("Filtro:"))
        filters.addWidget(self.cmb_status)
        filters.addWidget(btn_refresh)
        filters.addStretch()
        filters.addWidget(btn_build_all)
        lay.addLayout(filters)

        # Tabla
        self.tbl = QTableWidget()
        self.tbl.setColumnCount(9)
        self.tbl.setHorizontalHeaderLabels([
            "#", "Tipo", "Clave", "Estado", "Hacienda",
            "Cliente", "Total", "Fecha", "Acciones"
        ])
        self.tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl.setSelectionMode(QTableWidget.SingleSelection)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setStyleSheet("""
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
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setColumnWidth(0, 50)
        self.tbl.setColumnWidth(1, 50)
        self.tbl.setColumnWidth(2, 180)
        self.tbl.setColumnWidth(3, 120)
        self.tbl.setColumnWidth(4, 100)
        self.tbl.setColumnWidth(5, 130)
        self.tbl.setColumnWidth(6, 90)
        self.tbl.setColumnWidth(7, 130)
        lay.addWidget(self.tbl)

        # Detalle panel (abajo)
        self.detail_lbl = QLabel("Seleccioná un comprobante para ver opciones.")
        self.detail_lbl.setStyleSheet("color: #7f8c8d; padding: 4px;")
        lay.addWidget(self.detail_lbl)

        return w

    # ════════════════════════════════════════════════════════
    # Tab 2: Configuración Hacienda
    # ════════════════════════════════════════════════════════

    def _build_config_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignTop)

        # Ambiente
        grp_env = QGroupBox("Ambiente")
        env_form = QFormLayout(grp_env)
        self.cmb_env = QComboBox()
        self.cmb_env.addItems(["sandbox", "production"])
        env_form.addRow("Ambiente:", self.cmb_env)
        lay.addWidget(grp_env)

        # Credenciales OAuth2
        grp_creds = QGroupBox("Credenciales OAuth2 (ATV)")
        creds_form = QFormLayout(grp_creds)
        self.txt_hacienda_user = QLineEdit()
        self.txt_hacienda_user.setPlaceholderText("cpf-01-1234-5678@comprobanteselectronicos.go.cr")
        self.txt_hacienda_pass = QLineEdit()
        self.txt_hacienda_pass.setEchoMode(QLineEdit.Password)
        self.txt_hacienda_pass.setPlaceholderText("Contraseña del ATV")
        creds_form.addRow("Usuario:", self.txt_hacienda_user)
        creds_form.addRow("Contraseña:", self.txt_hacienda_pass)
        lay.addWidget(grp_creds)

        # Certificado
        grp_cert = QGroupBox("Certificado de Firma Digital (.p12)")
        cert_form = QFormLayout(grp_cert)
        cert_path_row = QHBoxLayout()
        self.txt_cert_path = QLineEdit()
        self.txt_cert_path.setPlaceholderText("/ruta/al/certificado.p12")
        btn_browse = QPushButton("📂")
        btn_browse.setFixedWidth(40)
        btn_browse.clicked.connect(self._browse_cert)
        cert_path_row.addWidget(self.txt_cert_path)
        cert_path_row.addWidget(btn_browse)
        self.txt_cert_pass = QLineEdit()
        self.txt_cert_pass.setEchoMode(QLineEdit.Password)
        self.txt_cert_pass.setPlaceholderText("Contraseña del .p12")
        cert_form.addRow("Ruta .p12:", cert_path_row)
        cert_form.addRow("Contraseña:", self.txt_cert_pass)

        self.lbl_cert_status = QLabel("—")
        self.lbl_cert_status.setStyleSheet("padding: 4px;")
        cert_form.addRow("Estado:", self.lbl_cert_status)
        lay.addWidget(grp_cert)

        # Botones
        btn_row = QHBoxLayout()
        btn_test = QPushButton("🔌 Probar conexión")
        btn_test.clicked.connect(self._test_connection)
        btn_check_cert = QPushButton("🔐 Verificar certificado")
        btn_check_cert.clicked.connect(self._check_cert)
        self.lbl_connection_status = QLabel("")
        btn_row.addWidget(btn_test)
        btn_row.addWidget(btn_check_cert)
        btn_row.addStretch()
        btn_row.addWidget(self.lbl_connection_status)
        lay.addLayout(btn_row)

        info_lbl = QLabel(
            "💡 Estas credenciales se configuran en el archivo .env del servidor.\n"
            "Los campos de arriba son solo para consulta/prueba, no modifican la configuración."
        )
        info_lbl.setStyleSheet("color: #7f8c8d; font-size: 11px; margin-top: 12px;")
        info_lbl.setWordWrap(True)
        lay.addWidget(info_lbl)

        lay.addStretch()
        return w

    def _browse_cert(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar certificado .p12", "", "PKCS12 (*.p12);;Todos (*)")
        if path:
            self.txt_cert_path.setText(path)

    # ════════════════════════════════════════════════════════
    # Tab 3: Diagnóstico
    # ════════════════════════════════════════════════════════

    def _build_diag_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignTop)

        btn_refresh = QPushButton("🔄 Actualizar diagnóstico")
        btn_refresh.clicked.connect(self._load_diagnostics)
        lay.addWidget(btn_refresh)

        self.diag_text = QTextEdit()
        self.diag_text.setReadOnly(True)
        self.diag_text.setStyleSheet("font-family: monospace; font-size: 12px;")
        lay.addWidget(self.diag_text)

        return w

    # ════════════════════════════════════════════════════════
    # Data loading
    # ════════════════════════════════════════════════════════

    def _load_all(self):
        self._load_summary()
        self._load_invoices()

    def _load_summary(self):
        self._cleanup_finished_threads()
        worker = _SummaryWorker()
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda data: self._on_summary(data))
        worker.finished.connect(thread.quit)
        worker.failed.connect(lambda e: logger.warning(f"Summary failed: {e}"))
        worker.failed.connect(thread.quit)
        thread.start()
        self._threads.append((thread, worker))

    def _on_summary(self, data):
        inv = data.get("invoices", {})
        self._set_kpi(self.kpi_total, inv.get("total", 0))
        self._set_kpi(self.kpi_accepted, inv.get("accepted", 0))
        self._set_kpi(self.kpi_sent, inv.get("sent", 0))
        self._set_kpi(self.kpi_rejected, inv.get("rejected", 0))
        pending = inv.get("pending", 0) + inv.get("xml_ready", 0) + inv.get("send_error", 0)
        self._set_kpi(self.kpi_pending, pending)

        # Alerta si hay rechazados
        rejected = inv.get("rejected", 0)
        failed = inv.get("failed", 0)
        if rejected > 0 or failed > 0:
            show_toast(
                f"⚠️ {rejected} rechazado(s), {failed} fallido(s) en Hacienda",
                success=False, parent=self._main, duration=5000,
            )

    def _load_invoices(self):
        self._cleanup_finished_threads()
        status = self.cmb_status.currentText()
        worker = _LoadInvoicesWorker(status)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda data: self._populate_table(data))
        worker.finished.connect(thread.quit)
        worker.failed.connect(lambda e: self.detail_lbl.setText(f"❌ Error: {e}"))
        worker.failed.connect(thread.quit)
        thread.start()
        self._threads.append((thread, worker))

    def _populate_table(self, invoices):
        status_filter = self.cmb_status.currentText()
        if status_filter and status_filter != "Todos":
            invoices = [inv for inv in invoices if inv.get("status") == status_filter]

        self.tbl.setRowCount(len(invoices))
        for row, inv in enumerate(invoices):
            eid = inv.get("id", "")
            doc_type = inv.get("document_type", "")
            clave = inv.get("clave", "") or ""
            status = inv.get("status", "")
            h_status = inv.get("hacienda_status", "") or ""
            customer = inv.get("sale_customer", "")
            if isinstance(customer, dict):
                customer = customer.get("name", "")
            total = inv.get("sale_total", 0)
            date = inv.get("sale_date", "")

            self.tbl.setItem(row, 0, QTableWidgetItem(str(eid)))
            self.tbl.setItem(row, 1, QTableWidgetItem(DOC_LABELS.get(doc_type, doc_type)))

            clave_short = f"...{clave[-12:]}" if len(clave) > 12 else clave
            clave_item = QTableWidgetItem(clave_short)
            clave_item.setToolTip(clave)
            self.tbl.setItem(row, 2, clave_item)

            status_item = QTableWidgetItem(STATUS_LABELS.get(status, status))
            color = STATUS_COLORS.get(status, "#95a5a6")
            status_item.setForeground(QColor(color))
            self.tbl.setItem(row, 3, status_item)

            self.tbl.setItem(row, 4, QTableWidgetItem(h_status))
            self.tbl.setItem(row, 5, QTableWidgetItem(str(customer)[:20]))
            self.tbl.setItem(row, 6, QTableWidgetItem(f"₡{total:,.0f}" if total else ""))

            date_short = str(date)[:16] if date else ""
            self.tbl.setItem(row, 7, QTableWidgetItem(date_short))

            # Acciones
            btn_container = QWidget()
            btn_lay = QHBoxLayout(btn_container)
            btn_lay.setContentsMargins(2, 2, 2, 2)

            if status == "PENDING":
                btn = QPushButton("🔨")
                btn.setToolTip("Build XML")
                btn.setFixedSize(30, 26)
                btn.clicked.connect(lambda _, x=eid: self._action_build(x))
                btn_lay.addWidget(btn)
            elif status in ("XML_READY", "SEND_ERROR"):
                btn = QPushButton("📤")
                btn.setToolTip("Enviar a Hacienda")
                btn.setFixedSize(30, 26)
                btn.clicked.connect(lambda _, x=eid: self._action_send(x))
                btn_lay.addWidget(btn)
            elif status == "SENT":
                btn = QPushButton("🔍")
                btn.setToolTip("Consultar estado")
                btn.setFixedSize(30, 26)
                btn.clicked.connect(lambda _, x=eid: self._action_check(x))
                btn_lay.addWidget(btn)
            elif status in ("SIGN_ERROR", "XML_UNSIGNED"):
                btn = QPushButton("🔐")
                btn.setToolTip("Re-firmar")
                btn.setFixedSize(30, 26)
                btn.clicked.connect(lambda _, x=eid: self._action_resign(x))
                btn_lay.addWidget(btn)

            # Ver respuesta (siempre disponible si hay hacienda_status)
            if h_status:
                btn_resp = QPushButton("📄")
                btn_resp.setToolTip("Ver respuesta Hacienda")
                btn_resp.setFixedSize(30, 26)
                btn_resp.clicked.connect(lambda _, x=eid: self._action_view_response(x))
                btn_lay.addWidget(btn_resp)

            self.tbl.setCellWidget(row, 8, btn_container)

        self.detail_lbl.setText(f"Mostrando {len(invoices)} comprobante(s)")

    # ════════════════════════════════════════════════════════
    # Acciones
    # ════════════════════════════════════════════════════════

    def _run_action(self, url, msg_ok, msg_err, method="post"):
        self._cleanup_finished_threads()
        self.detail_lbl.setText("⏳ Procesando...")
        worker = _ActionWorker(url, method)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda data: self._on_action_done(data, msg_ok, msg_err))
        worker.finished.connect(thread.quit)
        worker.failed.connect(lambda e: self._on_action_fail(e, msg_err))
        worker.failed.connect(thread.quit)
        thread.start()
        self._threads.append((thread, worker))

    def _on_action_done(self, data, msg_ok, msg_err):
        http = data.get("_http_status", 0)
        if http in (200, 202):
            show_toast(msg_ok, success=True, parent=self._main)
            self.detail_lbl.setText(f"✅ {msg_ok}")
        else:
            err = data.get("detail", data.get("error", data.get("message", str(data))))
            if isinstance(err, dict):
                err = err.get("message", str(err))
            self.detail_lbl.setText(f"⚠️ {err}")
            show_toast(f"{msg_err}: {str(err)[:80]}", success=False, parent=self._main)
        QTimer.singleShot(1500, self._load_all)

    def _on_action_fail(self, error, msg_err):
        self.detail_lbl.setText(f"❌ {msg_err}: {error}")
        show_toast(f"{msg_err}", success=False, parent=self._main)

    def _action_build(self, einv_id):
        self._run_action(f"{API}/einvoices/{einv_id}/build-xml", "XML generado", "Error generando XML")

    def _action_send(self, einv_id):
        self._run_action(f"{API}/einvoices/{einv_id}/send", "Enviado a Hacienda", "Error enviando")

    def _action_check(self, einv_id):
        self._run_action(f"{API}/einvoices/{einv_id}/check-status", "Estado actualizado", "Error consultando")

    def _action_resign(self, einv_id):
        self._run_action(f"{API}/einvoices/{einv_id}/re-sign", "XML refirmado", "Error refirmando")

    def _action_view_response(self, einv_id):
        api_call(
            "get", f"{API}/einvoices/{einv_id}/hacienda-response",
            headers=_headers(),
            on_success=self._on_hacienda_response,
            on_error=lambda msg: QMessageBox.warning(self, "Error", msg),
        )

    def _on_hacienda_response(self, data):
        parsed = data.get("parsed") or {}
        msg = (
            f"Estado: {data.get('hacienda_status', '?')}\n"
            f"Mensaje: {parsed.get('mensaje', '?')} "
            f"({'Aceptado' if parsed.get('mensaje') == '1' else 'Rechazado' if parsed.get('mensaje') == '3' else 'Parcial'})\n"
            f"Detalle: {parsed.get('detalle_mensaje', 'Sin detalle')}\n"
        )
        QMessageBox.information(self, "Respuesta de Hacienda", msg)

    def _build_all_pending(self):
        reply = QMessageBox.question(
            self, "Confirmar",
            "¿Generar XML para todos los comprobantes PENDING?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            # Get all by-sale won't work for batch, so we iterate
            # For now, show instruction
            show_toast("Usá el botón 🔨 en cada fila PENDING", success=True, parent=self._main)
        except Exception as e:
            show_toast(f"Error: {e}", success=False, parent=self._main)

    # ════════════════════════════════════════════════════════
    # Config tab actions
    # ════════════════════════════════════════════════════════

    def _test_connection(self):
        self._cleanup_finished_threads()
        self.lbl_connection_status.setText("⏳ Conectando...")
        self.lbl_connection_status.setStyleSheet("color: #7f8c8d;")

        worker = _ActionWorker(f"{API}/einvoices/connection-status", method="get")
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_connection_result)
        worker.finished.connect(thread.quit)
        worker.failed.connect(lambda e: self._on_connection_fail(e))
        worker.failed.connect(thread.quit)
        thread.start()
        self._threads.append((thread, worker))

    def _on_connection_result(self, data):
        configured = data.get("configured", False)
        token_valid = data.get("token_valid", False)
        error = data.get("error", "")
        env = data.get("env", "?")

        if token_valid:
            self.lbl_connection_status.setText(f"✅ Conectado ({env})")
            self.lbl_connection_status.setStyleSheet("color: #27ae60; font-weight: bold;")
            show_toast(f"Conexión exitosa a Hacienda ({env})", success=True, parent=self._main)
        elif configured:
            self.lbl_connection_status.setText(f"❌ Error: {error[:60]}")
            self.lbl_connection_status.setStyleSheet("color: #e74c3c;")
        else:
            self.lbl_connection_status.setText("⚠️ Sin configurar")
            self.lbl_connection_status.setStyleSheet("color: #f39c12;")

    def _on_connection_fail(self, error):
        self.lbl_connection_status.setText(f"❌ {error[:60]}")
        self.lbl_connection_status.setStyleSheet("color: #e74c3c;")

    def _check_cert(self):
        self._cleanup_finished_threads()
        self.lbl_cert_status.setText("⏳ Verificando...")
        worker = _ActionWorker(f"{API}/einvoices/signing-status", method="get")
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_cert_result)
        worker.finished.connect(thread.quit)
        worker.failed.connect(lambda e: self.lbl_cert_status.setText(f"❌ {e}"))
        worker.failed.connect(thread.quit)
        thread.start()
        self._threads.append((thread, worker))

    def _on_cert_result(self, data):
        available = data.get("available", False)
        error = data.get("error", "")
        days = data.get("days_remaining", "?")
        subject = data.get("subject", "")
        key_size = data.get("key_size", "?")

        if available:
            self.lbl_cert_status.setText(f"✅ Válido | {days} días | RSA {key_size} | {subject[:40]}")
            self.lbl_cert_status.setStyleSheet("color: #27ae60;")

            if isinstance(days, int) and days <= 30:
                show_toast(
                    f"⚠️ Certificado expira en {days} días",
                    success=False, parent=self._main, duration=6000,
                )
        else:
            self.lbl_cert_status.setText(f"❌ {error[:80]}")
            self.lbl_cert_status.setStyleSheet("color: #e74c3c;")

    # ════════════════════════════════════════════════════════
    # Diagnóstico tab
    # ════════════════════════════════════════════════════════

    def _load_diagnostics(self):
        self.diag_text.setText("⏳ Cargando diagnóstico...")
        run_async(
            self._fetch_diagnostics_data,
            on_success=self._on_diagnostics_loaded,
            on_error=lambda msg: self.diag_text.setText(f"❌ Error cargando diagnóstico:\n{msg}"),
        )

    def _fetch_diagnostics_data(self):
        """Se ejecuta en hilo de background — NO tocar widgets Qt aquí."""
        hdrs = _headers()
        lines = []

        try:
            r = requests.get(f"{API}/einvoices/xsd-status", headers=hdrs, timeout=5)
            if r.status_code == 200:
                xsd = r.json()
                lines.append("═══ VALIDACIÓN XSD ═══")
                lines.append(f"  lxml instalado: {xsd.get('lxml_installed', '?')}")
                lines.append(f"  Directorio: {xsd.get('xsd_directory', '?')}")
                lines.append(f"  Existe: {xsd.get('xsd_directory_exists', '?')}")
                for doc, info in xsd.get("schemas", {}).items():
                    status = "✅" if info.get("exists") else "❌"
                    lines.append(f"  {status} {doc}: {info.get('filename', '?')}")
        except Exception as e:
            lines.append(f"XSD: error {e}")

        lines.append("")

        try:
            r = requests.get(f"{API}/einvoices/signing-status", headers=hdrs, timeout=5)
            if r.status_code == 200:
                sig = r.json()
                lines.append("═══ FIRMA DIGITAL ═══")
                lines.append(f"  Disponible: {sig.get('available', '?')}")
                lines.append(f"  Ruta cert: {sig.get('cert_path', 'no configurada')}")
                if sig.get("available"):
                    lines.append(f"  Sujeto: {sig.get('subject', '?')}")
                    lines.append(f"  Emisor: {sig.get('issuer', '?')}")
                    lines.append(f"  Válido hasta: {sig.get('not_valid_after', '?')}")
                    lines.append(f"  Días restantes: {sig.get('days_remaining', '?')}")
                    lines.append(f"  Tamaño clave: {sig.get('key_size', '?')}")
                if sig.get("error"):
                    lines.append(f"  ⚠️ Error: {sig['error']}")
        except Exception as e:
            lines.append(f"Firma: error {e}")

        lines.append("")

        try:
            r = requests.get(f"{API}/einvoices/connection-status", headers=hdrs, timeout=10)
            if r.status_code == 200:
                conn = r.json()
                lines.append("═══ CONEXIÓN HACIENDA ═══")
                lines.append(f"  Configurada: {conn.get('configured', '?')}")
                lines.append(f"  Ambiente: {conn.get('env', '?')}")
                lines.append(f"  API URL: {conn.get('api_url', '?')}")
                lines.append(f"  Token válido: {conn.get('token_valid', '?')}")
                if conn.get("error"):
                    lines.append(f"  ⚠️ Error: {conn['error']}")
        except Exception as e:
            lines.append(f"Conexión: error {e}")

        lines.append("")

        try:
            r = requests.get(f"{API}/einvoices/pending-summary", headers=hdrs, timeout=5)
            if r.status_code == 200:
                summary = r.json()
                inv = summary.get("invoices", {})
                lines.append("═══ RESUMEN COMPROBANTES ═══")
                for key, val in inv.items():
                    lines.append(f"  {key}: {val}")
                lines.append(f"  ⚠️ Necesitan atención: {summary.get('needs_attention', 0)}")
        except Exception as e:
            lines.append(f"Resumen: error {e}")

        return "\n".join(lines)

    def _on_diagnostics_loaded(self, text):
        """Callback en hilo principal — seguro actualizar la UI."""
        self.diag_text.setText(text)