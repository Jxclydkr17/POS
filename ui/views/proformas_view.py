# ui/views/proformas_view.py
"""
Vista principal de proformas/cotizaciones.
FASE 1 — Fix 1.1 / 1.2: Carga asíncrona + timeout en acciones.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QDialog,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
import logging
import os
import subprocess

from ui.api import BASE_URL
from ui.session_manager import session
from ui.components.toast_notifier import show_toast
from ui.utils.http_worker import api_call, api_request

logger = logging.getLogger(__name__)

API_PROFORMAS = f"{BASE_URL}/proformas"

TABLE_STYLE = """
    QTableWidget {
        background-color: #0b1220; alternate-background-color: #131d30;
        color: #e5e7eb; gridline-color: #1f2937;
        border: 1px solid #1f2937; border-radius: 10px; outline: 0;
    }
    QTableWidget::item { padding: 6px; }
    QTableWidget::item:selected { background-color: #1e3a5f; color: white; }
    QHeaderView::section {
        background-color: #111827; color: #e5e7eb;
        padding: 6px; border: none; font-weight: bold;
    }
"""
BTN_PRIMARY = "QPushButton{background-color:#2563eb;color:white;padding:8px 14px;font-weight:700;border-radius:8px;}QPushButton:hover{background-color:#1d4ed8;}"
BTN_SUCCESS = "QPushButton{background-color:#16a34a;color:white;padding:8px 14px;font-weight:700;border-radius:8px;}QPushButton:hover{background-color:#15803d;}"
BTN_DANGER = "QPushButton{background-color:#dc2626;color:white;padding:8px 14px;font-weight:700;border-radius:8px;}QPushButton:hover{background-color:#b91c1c;}"
BTN_NEUTRAL = "QPushButton{background-color:#334155;color:white;padding:8px 14px;border-radius:8px;}QPushButton:hover{background-color:#475569;}"

STATUS_COLORS = {"VIGENTE": "#16a34a", "VENCIDA": "#dc2626", "CONVERTIDA": "#2563eb", "ANULADA": "#6b7280"}


class ProformasView(QWidget):
    def __init__(self):
        super().__init__()
        self.current_page = 1
        self.page_size = 50
        self.total_pages = 1
        self.setup_ui()
        self.load_proformas()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {session.token}"}

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("📋 Proformas / Cotizaciones")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 4px;")
        layout.addWidget(title)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_new = QPushButton("➕ Nueva proforma")
        self.btn_new.setStyleSheet(BTN_SUCCESS)
        self.btn_new.clicked.connect(self.open_create_dialog)
        actions.addWidget(self.btn_new)
        actions.addStretch()

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Buscar por número o cliente…")
        self.txt_search.setFixedWidth(250)
        self.txt_search.setStyleSheet(
            "QLineEdit{background:#111827;color:#e5e7eb;border:1px solid #374151;border-radius:8px;padding:6px 10px;}"
        )
        actions.addWidget(self.txt_search)

        self.cmb_status = QComboBox()
        self.cmb_status.addItems(["Todos", "VIGENTE", "VENCIDA", "CONVERTIDA", "ANULADA"])
        self.cmb_status.setFixedWidth(140)
        actions.addWidget(self.cmb_status)

        btn_filter = QPushButton("🔎 Filtrar")
        btn_filter.setStyleSheet(BTN_PRIMARY)
        btn_filter.clicked.connect(self.filter_first_page)
        actions.addWidget(btn_filter)
        layout.addLayout(actions)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setHorizontalHeaderLabels(["Número", "Cliente", "Total (₡)", "Estado", "Creada", "Vence", "Acciones"])
        self.table.setStyleSheet(TABLE_STYLE)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Fixed)
        header.setMinimumSectionSize(40)
        self.table.setColumnWidth(6, 240)
        layout.addWidget(self.table, 1)

        pag = QHBoxLayout()
        pag.setSpacing(8)
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color: #94a3b8;")
        pag.addWidget(self.lbl_info)
        pag.addStretch()
        self.btn_prev = QPushButton("◀ Anterior")
        self.btn_prev.setStyleSheet(BTN_NEUTRAL)
        self.btn_prev.clicked.connect(self.prev_page)
        pag.addWidget(self.btn_prev)
        self.lbl_page = QLabel("Página 1")
        self.lbl_page.setStyleSheet("color: #cbd5e1;")
        pag.addWidget(self.lbl_page)
        self.btn_next = QPushButton("Siguiente ▶")
        self.btn_next.setStyleSheet(BTN_NEUTRAL)
        self.btn_next.clicked.connect(self.next_page)
        pag.addWidget(self.btn_next)
        layout.addLayout(pag)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.filter_first_page)
        self.txt_search.textChanged.connect(lambda: self._search_timer.start(400))

    # ─────────────────────────────────────────────────────
    # FASE 1 — Fix 1.1: Carga asíncrona
    # ─────────────────────────────────────────────────────
    def load_proformas(self):
        params = {"page": self.current_page, "page_size": self.page_size}
        search = self.txt_search.text().strip()
        if search:
            params["search"] = search
        status = self.cmb_status.currentText()
        if status != "Todos":
            params["status"] = status

        api_call(
            "get", f"{API_PROFORMAS}/",
            headers=self._auth_headers(),
            params=params,
            on_success=self._on_proformas_loaded,
            on_error=lambda msg: show_toast("Error al cargar proformas", success=False, parent=self),
        )

    def _on_proformas_loaded(self, data):
        if not isinstance(data, dict):
            return
        items = data.get("data", [])
        self.total_pages = data.get("total_pages", 1)
        total_count = data.get("total_count", 0)
        self._populate_table(items)
        self._update_pagination(total_count)

    def _populate_table(self, items):
        self.table.setRowCount(len(items))
        for row, p in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(p.get("number", "")))

            cid = p.get("customer_id")
            customer_text = self._fetch_customer_name(cid) if cid else "Cliente General"
            self.table.setItem(row, 1, QTableWidgetItem(customer_text))

            total_item = QTableWidgetItem(f"₡{float(p.get('total', 0)):,.2f}")
            total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 2, total_item)

            status = p.get("status", "")
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignCenter)
            color = STATUS_COLORS.get(status, "#e5e7eb")
            status_item.setForeground(Qt.GlobalColor.white)
            status_item.setBackground(QColor(color))
            self.table.setItem(row, 3, status_item)

            created = str(p.get("created_at", ""))[:10]
            self.table.setItem(row, 4, QTableWidgetItem(created))
            valid = str(p.get("valid_until", ""))[:10]
            self.table.setItem(row, 5, QTableWidgetItem(valid))

            self._add_action_buttons(row, p)

    def _add_action_buttons(self, row, proforma):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        widget.setMinimumHeight(36)

        pid = proforma.get("id")
        status = proforma.get("status", "")
        _s = "QPushButton{background:%s;color:white;border-radius:3px;font-size:13px;} QPushButton:hover{background:%s;}"

        def _btn(icon, tip, color_pair, callback, w=28):
            b = QPushButton(icon)
            b.setToolTip(tip)
            b.setFixedSize(w, 24)
            b.setStyleSheet(_s % color_pair)
            b.clicked.connect(lambda _, x=pid: callback(x))
            layout.addWidget(b)
            return b

        _btn("👁", "Ver detalle",       ("#334155", "#475569"), self.view_proforma)
        _btn("📄", "Descargar PDF",     ("#334155", "#475569"), self.download_pdf)
        _btn("📧", "Enviar por email",  ("#334155", "#475569"), self.send_email)

        if status == "VIGENTE":
            _btn("✏️", "Editar",          ("#2563eb", "#1d4ed8"), self.edit_proforma)
            _btn("🛒", "Convertir a venta",("#16a34a", "#15803d"), self.convert_to_sale)
            _btn("🗑", "Anular",          ("#dc2626", "#b91c1c"), self.void_proforma)
        elif status == "VENCIDA":
            _btn("✏️", "Editar (reactivar)",("#f59e0b", "#d97706"), self.edit_proforma)

        self.table.setCellWidget(row, 6, widget)

    def _fetch_customer_name(self, customer_id):
        """Obtiene nombre del cliente. Sync con timeout (ya tiene timeout=5)."""
        try:
            resp = api_request("get", f"{BASE_URL}/customers/{customer_id}", headers=self._auth_headers(), timeout=5)
            if resp.status_code == 200:
                body = resp.json()
                if isinstance(body, dict) and "data" in body:
                    return body["data"].get("name", "Cliente General")
                return body.get("name", "Cliente General")
        except Exception:
            pass
        return "Cliente General"

    def _update_pagination(self, total_count):
        self.lbl_info.setText(f"{total_count} proforma(s) encontrada(s)")
        self.lbl_page.setText(f"Página {self.current_page} de {self.total_pages}")
        self.btn_prev.setEnabled(self.current_page > 1)
        self.btn_next.setEnabled(self.current_page < self.total_pages)

    # ── Paginación ──
    def filter_first_page(self):
        self.current_page = 1
        self.load_proformas()

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load_proformas()

    def next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.load_proformas()

    # ─────────────────────────────────────────────────────
    # ACCIONES (sync con timeout via api_request)
    # ─────────────────────────────────────────────────────
    def open_create_dialog(self):
        from ui.dialogs.create_proforma_dialog import CreateProformaDialog
        dlg = CreateProformaDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.load_proformas()

    def view_proforma(self, proforma_id):
        from ui.dialogs.proforma_detail_dialog import ProformaDetailDialog
        dlg = ProformaDetailDialog(proforma_id, parent=self)
        dlg.exec()
        self.load_proformas()

    def edit_proforma(self, proforma_id):
        from ui.dialogs.create_proforma_dialog import CreateProformaDialog
        dlg = CreateProformaDialog(parent=self, proforma_id=proforma_id)
        if dlg.exec() == QDialog.Accepted:
            self.load_proformas()

    def download_pdf(self, proforma_id):
        try:
            resp = api_request("get", f"{API_PROFORMAS}/{proforma_id}/pdf", headers=self._auth_headers(), timeout=15)
            if resp.status_code == 200:
                tmp_path = os.path.join(os.path.expanduser("~"), f"proforma_{proforma_id}.pdf")
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)
                if os.name == "nt":
                    os.startfile(tmp_path)
                else:
                    subprocess.Popen(["xdg-open", tmp_path])
                show_toast("PDF descargado", success=True, parent=self)
            else:
                show_toast("Error al generar PDF", success=False, parent=self)
        except Exception as e:
            logger.error(f"Error descargando PDF: {e}")
            show_toast("Error de conexión", success=False, parent=self)

    def send_email(self, proforma_id):
        confirm = QMessageBox.question(self, "Enviar por email", "¿Enviar esta proforma por correo al cliente?", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            resp = api_request("post", f"{API_PROFORMAS}/{proforma_id}/send-email", headers=self._auth_headers(), timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                show_toast(data.get("message", "Email enviado"), success=True, parent=self)
            else:
                detail = "Error"
                try: detail = resp.json().get("detail", resp.text)
                except Exception: detail = resp.text
                QMessageBox.warning(self, "Error", str(detail))
        except Exception as e:
            logger.error(f"Error enviando email: {e}")
            show_toast("Error de conexión", success=False, parent=self)

    def convert_to_sale(self, proforma_id):
        from ui.dialogs.proforma_detail_dialog import ProformaDetailDialog
        dlg = ProformaDetailDialog(proforma_id, parent=self, auto_convert=True)
        dlg.exec()
        self.load_proformas()

    def void_proforma(self, proforma_id):
        confirm = QMessageBox.question(self, "Anular proforma", "¿Está seguro de anular esta proforma?\nEsta acción no se puede deshacer.", QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            resp = api_request("delete", f"{API_PROFORMAS}/{proforma_id}", headers=self._auth_headers(), timeout=10)
            if resp.status_code == 200:
                show_toast("Proforma anulada", success=True, parent=self)
                self.load_proformas()
            else:
                detail = "Error"
                try: detail = resp.json().get("detail", resp.text)
                except Exception: detail = resp.text
                QMessageBox.warning(self, "Error", str(detail))
        except Exception as e:
            logger.error(f"Error anulando proforma: {e}")
            show_toast("Error de conexión", success=False, parent=self)