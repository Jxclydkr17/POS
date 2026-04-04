# ui/views/settings_view.py
"""
Vista de configuración del sistema — Fase 3 + Fase 4 + Fase 5 + Fase 6.

Fase 3: tabs, QThread, progress, toast, dirty tracking, service layer.
Fase 4: IssuerProfile (4.1), logo upload (4.2), impresora (4.3),
        email status (4.4), Hacienda status (4.5).
Fase 5: 5.5 — Sanitización de inputs (strip whitespace) antes de enviar.
Fase 6: 6.1 backup/restore, 6.2 moneda, 6.4 audit, 6.5 sys info, 6.6 export/import.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QMessageBox, QFormLayout, QGroupBox,
    QTabWidget, QProgressDialog, QScrollArea, QCheckBox,
    QFileDialog, QSpinBox, QDoubleSpinBox, QTextEdit,
)
from PySide6.QtCore import Qt, QObject, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap
import logging
import os

from ui.components.toast_notifier import show_toast

logger = logging.getLogger(__name__)


# ================================================================
# Workers — ejecutan HTTP en hilo separado, nunca tocan la UI
# ================================================================

class _LoadAllWorker(QObject):
    """Carga settings + suppliers + issuer + env_status + system_info en un solo hilo."""
    finished = Signal(dict, list, dict, dict, dict)  # settings, suppliers, issuer, env_status, sys_info
    failed = Signal(str)

    def run(self):
        try:
            from ui.services.settings_service import (
                fetch_settings, fetch_suppliers,
                fetch_issuer_profile, fetch_env_status,
                fetch_system_info,
            )
            settings = fetch_settings()
            suppliers = fetch_suppliers()
            issuer = fetch_issuer_profile()
            try:
                env_status = fetch_env_status()
            except Exception:
                env_status = {}
            try:
                sys_info = fetch_system_info()
            except Exception:
                sys_info = {}
            self.finished.emit(settings, suppliers, issuer, env_status, sys_info)
        except Exception as e:
            self.failed.emit(str(e))


class _SaveSettingsWorker(QObject):
    """Guarda la configuración general."""
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self):
        try:
            from ui.services.settings_service import save_settings
            result = save_settings(self._payload)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class _SaveIssuerWorker(QObject):
    """Guarda el perfil del emisor."""
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self):
        try:
            from ui.services.settings_service import save_issuer_profile
            result = save_issuer_profile(self._payload)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class _UpdateCabysWorker(QObject):
    """Actualiza el catálogo CABYS (puede tardar minutos)."""
    finished = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            from ui.services.settings_service import update_cabys
            result = update_cabys()
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class _UploadLogoWorker(QObject):
    """Sube el logo al servidor."""
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, filepath: str, parent=None):
        super().__init__(parent)
        self._filepath = filepath

    def run(self):
        try:
            from ui.services.settings_service import upload_logo
            result = upload_logo(self._filepath)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class _BackupWorker(QObject):
    """6.1: Crea backup de la DB."""
    finished = Signal(str)   # filepath del backup descargado
    failed = Signal(str)

    def __init__(self, save_to: str, parent=None):
        super().__init__(parent)
        self._save_to = save_to

    def run(self):
        try:
            from ui.services.settings_service import create_backup
            path = create_backup(self._save_to)
            self.finished.emit(path)
        except Exception as e:
            self.failed.emit(str(e))


class _RestoreWorker(QObject):
    """6.1: Restaura backup."""
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, filepath: str, parent=None):
        super().__init__(parent)
        self._filepath = filepath

    def run(self):
        try:
            from ui.services.settings_service import restore_backup
            result = restore_backup(self._filepath)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class _ExportConfigWorker(QObject):
    """6.6: Exporta config como JSON."""
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, save_to: str, parent=None):
        super().__init__(parent)
        self._save_to = save_to

    def run(self):
        try:
            from ui.services.settings_service import export_config
            path = export_config(self._save_to)
            self.finished.emit(path)
        except Exception as e:
            self.failed.emit(str(e))


class _ImportConfigWorker(QObject):
    """6.6: Importa config desde JSON."""
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, filepath: str, parent=None):
        super().__init__(parent)
        self._filepath = filepath

    def run(self):
        try:
            from ui.services.settings_service import import_config
            result = import_config(self._filepath)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


# ── FASE 5 AI: Workers para configuración de IA ──

class _LoadAIConfigWorker(QObject):
    """Carga la config de IA desde el backend."""
    finished = Signal(dict, list)  # ai_config, providers
    failed = Signal(str)

    def run(self):
        try:
            from ui.services.settings_service import fetch_ai_config, fetch_ai_providers
            config = fetch_ai_config()
            try:
                providers = fetch_ai_providers()
            except Exception:
                providers = []
            self.finished.emit(config, providers)
        except Exception as e:
            self.failed.emit(str(e))


class _SaveAIConfigWorker(QObject):
    """Guarda la config de IA."""
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self):
        try:
            from ui.services.settings_service import save_ai_config
            result = save_ai_config(self._payload)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class _TestAIConfigWorker(QObject):
    """Prueba la conexión con el proveedor de IA."""
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self):
        try:
            from ui.services.settings_service import test_ai_connection
            result = test_ai_connection(self._payload)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


# ================================================================
# Vista principal
# ================================================================

class SettingsView(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.settings_data = {}
        self.issuer_data = {}
        self._dirty = False

        # Referencias a hilos activos
        self._thread = None
        self._worker = None

        self._init_ui()
        self._start_load()

    # ==========================================================
    # API pública — dirty tracking
    # ==========================================================
    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        reply = QMessageBox.question(
            self, "Cambios sin guardar",
            "Hay cambios sin guardar en Configuración.\n¿Deseas salir sin guardar?",
            QMessageBox.Yes | QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    # ==========================================================
    # UI — Estructura con pestañas
    # ==========================================================
    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        title = QLabel("⚙️ Configuración del Sistema")
        title.setStyleSheet("font-size: 20px; font-weight: bold; margin: 8px;")
        root.addWidget(title)

        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("settingsTabs")
        self.tab_widget.setStyleSheet("""
            QTabWidget#settingsTabs::pane {
                border: none;
                background-color: #1c1c1c;
                border-radius: 10px;
            }
            QTabWidget#settingsTabs > QTabBar::tab {
                background-color: #2A2A2A;
                color: white;
                padding: 10px 22px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-size: 13px;
            }
            QTabWidget#settingsTabs > QTabBar::tab:selected {
                background-color: #3a86ff;
                font-weight: bold;
            }
        """)

        self.tab_widget.addTab(self._build_tab_empresa(), "🏢 Empresa")
        self.tab_widget.addTab(self._build_tab_pos(), "🛒 POS")
        self.tab_widget.addTab(self._build_tab_facturacion(), "📄 Facturación")
        self.tab_widget.addTab(self._build_tab_impresora(), "🖨️ Impresora")
        self.tab_widget.addTab(self._build_tab_ai(), "🤖 Asistente IA")
        self.tab_widget.addTab(self._build_tab_avanzado(), "⚙️ Avanzado")

        root.addWidget(self.tab_widget, 1)

        # Barra de botones inferior
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        self.btn_save = QPushButton("💾 Guardar configuración")
        self.btn_save.setMinimumHeight(38)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #3a86ff; color: white;
                font-weight: bold; font-size: 14px;
                padding: 8px 28px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background-color: #2b6fe0; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        self.btn_save.clicked.connect(self._on_save)
        btn_bar.addWidget(self.btn_save)
        btn_bar.addStretch()

        root.addLayout(btn_bar)

    # ----------------------------------------------------------
    # Tab: Empresa
    # ----------------------------------------------------------
    def _build_tab_empresa(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(12)

        self.input_business_name = QLineEdit()
        self.input_legal_name = QLineEdit()

        self.combo_id_type = QComboBox()
        self.combo_id_type.addItems(["Física", "Jurídica", "DIMEX"])

        self.input_id_number = QLineEdit()
        self.input_phone = QLineEdit()
        self.input_email = QLineEdit()
        self.input_address = QLineEdit()

        # Fase 4.2: Logo
        logo_row = QHBoxLayout()
        self.label_logo_preview = QLabel("Sin logo")
        self.label_logo_preview.setFixedSize(64, 64)
        self.label_logo_preview.setAlignment(Qt.AlignCenter)
        self.label_logo_preview.setStyleSheet(
            "border: 1px dashed #555; border-radius: 6px; color: #888; font-size: 11px;"
        )
        self.btn_upload_logo = QPushButton("📁 Subir logo")
        self.btn_upload_logo.clicked.connect(self._on_upload_logo)
        logo_row.addWidget(self.label_logo_preview)
        logo_row.addWidget(self.btn_upload_logo)
        logo_row.addStretch()

        form.addRow("Nombre comercial:", self.input_business_name)
        form.addRow("Razón social:", self.input_legal_name)
        form.addRow("Tipo de identificación:", self.combo_id_type)
        form.addRow("Número ID:", self.input_id_number)
        form.addRow("Teléfono:", self.input_phone)
        form.addRow("Email:", self.input_email)
        form.addRow("Dirección:", self.input_address)
        form.addRow("Logo de empresa:", logo_row)

        for w in (self.input_business_name, self.input_legal_name,
                  self.input_id_number, self.input_phone,
                  self.input_email, self.input_address):
            w.textChanged.connect(self._mark_dirty)
        self.combo_id_type.currentIndexChanged.connect(self._mark_dirty)

        return tab

    # ----------------------------------------------------------
    # Tab: POS
    # ----------------------------------------------------------
    def _build_tab_pos(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(12)

        self.input_default_tax = QComboBox()
        self.input_default_tax.addItems(["13", "8", "4", "2", "0"])

        self.input_rounding = QComboBox()
        self.input_rounding.addItems(["Desactivado", "Activado"])

        self.combo_default_supplier = QComboBox()
        self.combo_default_supplier.addItem("— Ninguno —", None)

        # 6.2: Moneda
        self.combo_currency = QComboBox()
        self.combo_currency.addItems(["CRC", "USD"])

        self.input_exchange_rate = QDoubleSpinBox()
        self.input_exchange_rate.setRange(0.01, 99999.00)
        self.input_exchange_rate.setDecimals(2)
        self.input_exchange_rate.setValue(1.00)
        self.input_exchange_rate.setPrefix("₡ ")

        form.addRow("IVA predeterminado (%):", self.input_default_tax)
        form.addRow("Redondeo automático:", self.input_rounding)
        form.addRow("Proveedor predeterminado:", self.combo_default_supplier)
        form.addRow("Moneda predeterminada:", self.combo_currency)
        form.addRow("Tipo de cambio:", self.input_exchange_rate)

        self.input_default_tax.currentIndexChanged.connect(self._mark_dirty)
        self.input_rounding.currentIndexChanged.connect(self._mark_dirty)
        self.combo_default_supplier.currentIndexChanged.connect(self._mark_dirty)
        self.combo_currency.currentIndexChanged.connect(self._mark_dirty)
        self.input_exchange_rate.valueChanged.connect(self._mark_dirty)

        return tab

    # ----------------------------------------------------------
    # Tab: Facturación Electrónica (Fase 4.1)
    # ----------------------------------------------------------
    def _build_tab_facturacion(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)

        # --- Datos del emisor ---
        box_emisor = QGroupBox("👤 Datos del Emisor")
        form_e = QFormLayout()

        self.iss_legal_name = QLineEdit()
        self.iss_commercial_name = QLineEdit()
        self.iss_id_type = QComboBox()
        self.iss_id_type.addItems([
            "01 - Cédula Física", "02 - Cédula Jurídica",
            "03 - DIMEX", "04 - NITE"
        ])
        self.iss_id_number = QLineEdit()
        self.iss_email = QLineEdit()
        self.iss_phone = QLineEdit()

        form_e.addRow("Razón social:", self.iss_legal_name)
        form_e.addRow("Nombre comercial:", self.iss_commercial_name)
        form_e.addRow("Tipo identificación:", self.iss_id_type)
        form_e.addRow("Número identificación:", self.iss_id_number)
        form_e.addRow("Email facturación:", self.iss_email)
        form_e.addRow("Teléfono:", self.iss_phone)

        box_emisor.setLayout(form_e)
        layout.addWidget(box_emisor)

        # --- Actividad y sistema ---
        box_act = QGroupBox("📋 Actividad Económica y Sistema")
        form_a = QFormLayout()

        self.iss_economic_activity = QLineEdit()
        self.iss_economic_activity.setPlaceholderText("Ej: 477190")
        self.iss_provider_system = QLineEdit()
        self.iss_provider_system.setPlaceholderText("Código del proveedor del sistema")

        form_a.addRow("Código actividad económica:", self.iss_economic_activity)
        form_a.addRow("Proveedor del sistema:", self.iss_provider_system)

        box_act.setLayout(form_a)
        layout.addWidget(box_act)

        # --- Ubicación ---
        box_ubi = QGroupBox("📍 Ubicación del Emisor")
        form_u = QFormLayout()

        self.iss_provincia = QLineEdit()
        self.iss_provincia.setPlaceholderText("1 dígito (ej: 7)")
        self.iss_provincia.setMaxLength(1)
        self.iss_canton = QLineEdit()
        self.iss_canton.setPlaceholderText("2 dígitos (ej: 01)")
        self.iss_canton.setMaxLength(2)
        self.iss_distrito = QLineEdit()
        self.iss_distrito.setPlaceholderText("2 dígitos (ej: 01)")
        self.iss_distrito.setMaxLength(2)
        self.iss_barrio = QLineEdit()
        self.iss_barrio.setPlaceholderText("Nombre del barrio")
        self.iss_otras_senas = QLineEdit()
        self.iss_otras_senas.setPlaceholderText("Dirección detallada")

        form_u.addRow("Provincia:", self.iss_provincia)
        form_u.addRow("Cantón:", self.iss_canton)
        form_u.addRow("Distrito:", self.iss_distrito)
        form_u.addRow("Barrio:", self.iss_barrio)
        form_u.addRow("Otras señas:", self.iss_otras_senas)

        box_ubi.setLayout(form_u)
        layout.addWidget(box_ubi)

        # --- Sucursal y terminal ---
        box_suc = QGroupBox("🏪 Sucursal y Terminal")
        form_s = QFormLayout()

        self.iss_branch_code = QLineEdit()
        self.iss_branch_code.setPlaceholderText("3 dígitos (ej: 001)")
        self.iss_branch_code.setMaxLength(3)
        self.iss_terminal_code = QLineEdit()
        self.iss_terminal_code.setPlaceholderText("5 dígitos (ej: 00001)")
        self.iss_terminal_code.setMaxLength(5)

        form_s.addRow("Código sucursal:", self.iss_branch_code)
        form_s.addRow("Código terminal:", self.iss_terminal_code)

        box_suc.setLayout(form_s)
        layout.addWidget(box_suc)

        # --- REP ---
        box_rep = QGroupBox("🧾 Recibo Electrónico de Pago (REP)")
        form_r = QFormLayout()

        self.iss_enable_rep = QCheckBox("Habilitar REP")
        self.iss_rep_condicion = QComboBox()
        self.iss_rep_condicion.addItems([
            "", "01 - Contado", "02 - Crédito", "03 - Consignación",
            "04 - Apartado", "05 - Arrendamiento", "06 - Arrendamiento con opción",
            "07 - Cobro a favor de tercero", "99 - Otros"
        ])
        self.iss_rep_referencia = QComboBox()
        self.iss_rep_referencia.addItems([
            "", "01 - Anula doc referencia", "02 - Corrige texto",
            "03 - Corrige monto", "04 - Ref. a otro doc",
            "05 - Sustituye comprobante provisional", "99 - Otros"
        ])

        form_r.addRow(self.iss_enable_rep)
        form_r.addRow("Condición de venta:", self.iss_rep_condicion)
        form_r.addRow("Código de referencia:", self.iss_rep_referencia)

        box_rep.setLayout(form_r)
        layout.addWidget(box_rep)

        # Botón guardar emisor
        btn_save_issuer = QPushButton("💾 Guardar Perfil Emisor")
        btn_save_issuer.setMinimumHeight(36)
        btn_save_issuer.setStyleSheet("""
            QPushButton {
                background-color: #10b981; color: white;
                font-weight: bold; font-size: 13px;
                padding: 8px 24px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        btn_save_issuer.clicked.connect(self._on_save_issuer)
        self.btn_save_issuer = btn_save_issuer
        layout.addWidget(btn_save_issuer)

        # Fase 4.5: Estado de Hacienda
        box_hacienda = QGroupBox("🔗 Estado de Conexión con Hacienda")
        h_layout = QVBoxLayout()
        self.label_hacienda_status = QLabel("Cargando...")
        self.label_hacienda_status.setStyleSheet("font-size: 12px; color: #aaa;")
        h_layout.addWidget(self.label_hacienda_status)
        box_hacienda.setLayout(h_layout)
        layout.addWidget(box_hacienda)

        layout.addStretch()

        # Dirty tracking para todos los campos del emisor
        for w in (self.iss_legal_name, self.iss_commercial_name, self.iss_id_number,
                  self.iss_email, self.iss_phone, self.iss_economic_activity,
                  self.iss_provider_system, self.iss_provincia, self.iss_canton,
                  self.iss_distrito, self.iss_barrio, self.iss_otras_senas,
                  self.iss_branch_code, self.iss_terminal_code):
            w.textChanged.connect(self._mark_dirty)
        for c in (self.iss_id_type, self.iss_rep_condicion, self.iss_rep_referencia):
            c.currentIndexChanged.connect(self._mark_dirty)
        self.iss_enable_rep.stateChanged.connect(self._mark_dirty)

        scroll.setWidget(tab)
        return scroll

    # ----------------------------------------------------------
    # Tab: Impresora (Fase 4.3)
    # ----------------------------------------------------------
    def _build_tab_impresora(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignTop)

        box = QGroupBox("🖨️ Impresora Térmica")
        form = QFormLayout()

        self.combo_printer_type = QComboBox()
        self.combo_printer_type.addItems(["network", "usb", "none"])

        self.input_printer_ip = QLineEdit()
        self.input_printer_ip.setPlaceholderText("192.168.0.120")

        self.input_printer_port = QSpinBox()
        self.input_printer_port.setRange(1, 65535)
        self.input_printer_port.setValue(9100)

        form.addRow("Tipo de conexión:", self.combo_printer_type)
        form.addRow("Dirección IP:", self.input_printer_ip)
        form.addRow("Puerto:", self.input_printer_port)

        box.setLayout(form)
        layout.addWidget(box)

        note = QLabel(
            "ℹ️ Estos valores se usan al imprimir tickets de venta.\n"
            "Tipo 'network': impresora en red (IP + puerto).\n"
            "Tipo 'usb': impresora USB conectada localmente.\n"
            "Tipo 'none': impresión deshabilitada."
        )
        note.setStyleSheet("color: #888; font-size: 12px; margin-top: 12px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        # Fase 4.4: Estado de email
        box_email = QGroupBox("📧 Configuración de Email")
        email_layout = QVBoxLayout()
        self.label_email_status = QLabel("Cargando...")
        self.label_email_status.setStyleSheet("font-size: 12px; color: #aaa;")
        email_layout.addWidget(self.label_email_status)
        note_email = QLabel(
            "ℹ️ Las credenciales de email se configuran en el archivo .env del servidor.\n"
            "Aquí solo se muestra si están configuradas."
        )
        note_email.setStyleSheet("color: #666; font-size: 11px;")
        note_email.setWordWrap(True)
        email_layout.addWidget(note_email)
        box_email.setLayout(email_layout)
        layout.addWidget(box_email)

        # Dirty tracking
        self.combo_printer_type.currentIndexChanged.connect(self._mark_dirty)
        self.input_printer_ip.textChanged.connect(self._mark_dirty)
        self.input_printer_port.valueChanged.connect(self._mark_dirty)

        layout.addStretch()
        return tab

    # ----------------------------------------------------------
    # Tab: Avanzado (CABYS + info)
    # ----------------------------------------------------------
    def _build_tab_avanzado(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignTop)

        # --- CABYS ---
        box_cabys = QGroupBox("📘 Catálogo CABYS")
        cabys_layout = QVBoxLayout()
        self.label_cabys_last = QLabel("Última actualización: -")
        self.label_cabys_records = QLabel("Registros cargados: 0")
        self.btn_update_cabys = QPushButton("🔄 Actualizar CABYS desde Hacienda")
        self.btn_update_cabys.setMinimumHeight(36)
        self.btn_update_cabys.clicked.connect(self._on_update_cabys)
        cabys_layout.addWidget(self.label_cabys_last)
        cabys_layout.addWidget(self.label_cabys_records)
        cabys_layout.addWidget(self.btn_update_cabys)
        box_cabys.setLayout(cabys_layout)
        layout.addWidget(box_cabys)

        # --- 6.1: Backup y Restauración ---
        box_backup = QGroupBox("💾 Backup y Restauración de Base de Datos")
        backup_layout = QVBoxLayout()

        backup_note = QLabel(
            "Crea una copia completa de la base de datos (mysqldump).\n"
            "Guárdala en un lugar seguro para poder restaurarla si es necesario."
        )
        backup_note.setStyleSheet("color: #aaa; font-size: 12px;")
        backup_note.setWordWrap(True)
        backup_layout.addWidget(backup_note)

        btn_row_backup = QHBoxLayout()
        self.btn_backup = QPushButton("📥 Crear Backup")
        self.btn_backup.setMinimumHeight(34)
        self.btn_backup.clicked.connect(self._on_backup)
        btn_row_backup.addWidget(self.btn_backup)

        self.btn_restore = QPushButton("📤 Restaurar Backup")
        self.btn_restore.setMinimumHeight(34)
        self.btn_restore.setStyleSheet("""
            QPushButton { background-color: #dc2626; color: white;
                font-weight: bold; border-radius: 6px; padding: 6px 16px; border: none; }
            QPushButton:hover { background-color: #b91c1c; }
        """)
        self.btn_restore.clicked.connect(self._on_restore)
        btn_row_backup.addWidget(self.btn_restore)
        btn_row_backup.addStretch()

        backup_layout.addLayout(btn_row_backup)
        box_backup.setLayout(backup_layout)
        layout.addWidget(box_backup)

        # --- 6.6: Exportar / Importar configuración ---
        box_config = QGroupBox("📋 Exportar / Importar Configuración")
        config_layout = QVBoxLayout()

        config_note = QLabel(
            "Exporta la configuración de empresa y emisor como archivo JSON.\n"
            "Útil para replicar en otra sucursal o como respaldo de la configuración."
        )
        config_note.setStyleSheet("color: #aaa; font-size: 12px;")
        config_note.setWordWrap(True)
        config_layout.addWidget(config_note)

        btn_row_config = QHBoxLayout()
        self.btn_export_config = QPushButton("📤 Exportar Config")
        self.btn_export_config.setMinimumHeight(34)
        self.btn_export_config.clicked.connect(self._on_export_config)
        btn_row_config.addWidget(self.btn_export_config)

        self.btn_import_config = QPushButton("📥 Importar Config")
        self.btn_import_config.setMinimumHeight(34)
        self.btn_import_config.clicked.connect(self._on_import_config)
        btn_row_config.addWidget(self.btn_import_config)
        btn_row_config.addStretch()

        config_layout.addLayout(btn_row_config)
        box_config.setLayout(config_layout)
        layout.addWidget(box_config)

        # --- 6.5: Info del sistema ---
        box_info = QGroupBox("ℹ️ Información del Sistema")
        info_layout = QVBoxLayout()
        self.label_sys_info = QLabel("Cargando...")
        self.label_sys_info.setStyleSheet("color: #aaa; font-size: 12px;")
        self.label_sys_info.setWordWrap(True)
        info_layout.addWidget(self.label_sys_info)
        box_info.setLayout(info_layout)
        layout.addWidget(box_info)

        layout.addStretch()
        scroll.setWidget(tab)
        return scroll

    # ==========================================================
    # Carga asíncrona
    # ==========================================================
    def _start_load(self):
        self._cleanup_thread()

        self._worker = _LoadAllWorker()
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_all_loaded)
        self._worker.failed.connect(self._on_load_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)

        self._thread.start()

    def _on_all_loaded(self, data: dict, suppliers: list, issuer: dict, env_status: dict, sys_info: dict):
        self.settings_data = data
        self.issuer_data = issuer

        # --- Tab Empresa ---
        self.input_business_name.setText(data.get("business_name", "") or "")
        self.input_legal_name.setText(data.get("legal_name", "") or "")
        self.combo_id_type.setCurrentText(data.get("id_type", "Física") or "Física")
        self.input_id_number.setText(data.get("id_number", "") or "")
        self.input_phone.setText(data.get("phone", "") or "")
        self.input_email.setText(data.get("email", "") or "")
        self.input_address.setText(data.get("address", "") or "")

        # Logo preview
        logo = data.get("logo_path")
        if logo and os.path.isfile(logo):
            pix = QPixmap(logo).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.label_logo_preview.setPixmap(pix)
        else:
            self.label_logo_preview.setText("Sin logo")

        # --- Tab POS ---
        self.input_default_tax.setCurrentText(str(data.get("default_tax", "13")))
        self.input_rounding.setCurrentIndex(1 if data.get("rounding_enabled") else 0)

        self.combo_default_supplier.clear()
        self.combo_default_supplier.addItem("— Ninguno —", None)
        for s in suppliers:
            self.combo_default_supplier.addItem(s["name"], s["id"])
        current = data.get("default_supplier_id")
        if current:
            idx = self.combo_default_supplier.findData(current)
            if idx >= 0:
                self.combo_default_supplier.setCurrentIndex(idx)

        # 6.2: Moneda
        currency = data.get("default_currency", "CRC") or "CRC"
        idx_cur = self.combo_currency.findText(currency)
        if idx_cur >= 0:
            self.combo_currency.setCurrentIndex(idx_cur)
        rate = data.get("exchange_rate")
        self.input_exchange_rate.setValue(float(rate) if rate else 1.00)

        # --- Tab Impresora (4.3) ---
        pt = data.get("printer_type", "network") or "network"
        idx_pt = self.combo_printer_type.findText(pt)
        if idx_pt >= 0:
            self.combo_printer_type.setCurrentIndex(idx_pt)
        self.input_printer_ip.setText(data.get("printer_ip", "192.168.0.120") or "192.168.0.120")
        self.input_printer_port.setValue(data.get("printer_port", 9100) or 9100)

        # --- Tab Facturación (4.1): Issuer Profile ---
        self._populate_issuer(issuer)

        # --- Env status (4.4/4.5) ---
        self._populate_env_status(env_status)

        # --- Tab Avanzado ---
        last = data.get("cabys_last_update")
        self.label_cabys_last.setText(f"Última actualización: {last or '-'}")
        rec = data.get("cabys_records", 0)
        self.label_cabys_records.setText(f"Registros cargados: {rec}")

        # 6.5: Info del sistema enriquecida
        self._populate_sys_info(sys_info, data)

        self._dirty = False

    def _populate_issuer(self, issuer: dict):
        """Rellena los campos del tab Facturación con datos del IssuerProfile."""
        self.iss_legal_name.setText(issuer.get("legal_name", "") or "")
        self.iss_commercial_name.setText(issuer.get("commercial_name", "") or "")

        # Mapear id_type a combo
        id_type = issuer.get("id_type", "01") or "01"
        id_type_map = {"01": 0, "02": 1, "03": 2, "04": 3}
        self.iss_id_type.setCurrentIndex(id_type_map.get(id_type, 0))

        self.iss_id_number.setText(issuer.get("id_number", "") or "")
        self.iss_email.setText(issuer.get("email", "") or "")
        self.iss_phone.setText(issuer.get("phone", "") or "")

        self.iss_economic_activity.setText(issuer.get("economic_activity_code", "") or "")
        self.iss_provider_system.setText(issuer.get("provider_system_id", "") or "")

        self.iss_provincia.setText(issuer.get("provincia", "") or "")
        self.iss_canton.setText(issuer.get("canton", "") or "")
        self.iss_distrito.setText(issuer.get("distrito", "") or "")
        self.iss_barrio.setText(issuer.get("barrio", "") or "")
        self.iss_otras_senas.setText(issuer.get("otras_senas", "") or "")

        self.iss_branch_code.setText(issuer.get("branch_code", "001") or "001")
        self.iss_terminal_code.setText(issuer.get("terminal_code", "00001") or "00001")

        self.iss_enable_rep.setChecked(bool(issuer.get("enable_rep", 0)))

        # REP condicion
        cond = issuer.get("rep_default_condicion_venta", "") or ""
        for i in range(self.iss_rep_condicion.count()):
            if self.iss_rep_condicion.itemText(i).startswith(cond):
                self.iss_rep_condicion.setCurrentIndex(i)
                break

        # REP referencia
        ref = issuer.get("rep_default_codigo_referencia", "") or ""
        for i in range(self.iss_rep_referencia.count()):
            if self.iss_rep_referencia.itemText(i).startswith(ref):
                self.iss_rep_referencia.setCurrentIndex(i)
                break

    def _populate_env_status(self, env_status: dict):
        """Rellena los indicadores de email y Hacienda."""
        # Email (4.4)
        email_info = env_status.get("email", {})
        if email_info.get("configured"):
            hint = email_info.get("user_hint", "***")
            self.label_email_status.setText(f"✅ Email configurado — usuario: {hint}")
            self.label_email_status.setStyleSheet("font-size: 12px; color: #10b981;")
        else:
            self.label_email_status.setText("⚠️ Email NO configurado en .env")
            self.label_email_status.setStyleSheet("font-size: 12px; color: #f59e0b;")

        # Hacienda (4.5)
        hac_info = env_status.get("hacienda", {})
        parts = []
        if hac_info.get("api_configured"):
            url_hint = hac_info.get("api_url_hint", "")
            parts.append(f"✅ API Hacienda configurada ({url_hint})")
        else:
            parts.append("⚠️ API Hacienda NO configurada")

        if hac_info.get("cert_configured"):
            exists = "archivo existe" if hac_info.get("cert_file_exists") else "⚠️ ARCHIVO NO ENCONTRADO"
            parts.append(f"✅ Certificado configurado — {exists}")
        else:
            parts.append("⚠️ Certificado NO configurado en .env")

        color = "#10b981" if hac_info.get("api_configured") and hac_info.get("cert_configured") else "#f59e0b"
        self.label_hacienda_status.setText("\n".join(parts))
        self.label_hacienda_status.setStyleSheet(f"font-size: 12px; color: {color};")

    def _on_load_failed(self, error: str):
        logger.error(f"Error cargando configuración: {error}")
        show_toast("Error cargando configuración", success=False, parent=self.main_window)

    # ==========================================================
    # Guardar Settings generales + impresora
    # ==========================================================
    def _on_save(self):
        self.btn_save.setEnabled(False)
        self.btn_save.setText("Guardando...")

        payload = {
            "business_name": self.input_business_name.text(),
            "legal_name": self.input_legal_name.text(),
            "id_type": self.combo_id_type.currentText(),
            "id_number": self.input_id_number.text(),
            "phone": self.input_phone.text(),
            "email": self.input_email.text(),
            "address": self.input_address.text(),
            "default_tax": self.input_default_tax.currentText(),
            "rounding_enabled": self.input_rounding.currentIndex() == 1,
            "default_supplier_id": self.combo_default_supplier.currentData(),
            # Fase 4.3
            "printer_type": self.combo_printer_type.currentText(),
            "printer_ip": self.input_printer_ip.text(),
            "printer_port": self.input_printer_port.value(),
            # Fase 6.2
            "default_currency": self.combo_currency.currentText(),
            "exchange_rate": self.input_exchange_rate.value(),
        }

        # 5.5: Sanitizar inputs (strip whitespace, vacíos → None)
        payload = self._sanitize_payload(payload)

        self._cleanup_thread()
        self._worker = _SaveSettingsWorker(payload)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_save_success)
        self._worker.failed.connect(self._on_save_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)

        self._thread.start()

    def _on_save_success(self, result: dict):
        self._dirty = False
        self.btn_save.setEnabled(True)
        self.btn_save.setText("💾 Guardar configuración")
        show_toast("✅ Configuración guardada correctamente", success=True, parent=self.main_window)

    def _on_save_failed(self, error: str):
        self.btn_save.setEnabled(True)
        self.btn_save.setText("💾 Guardar configuración")
        logger.error(f"Error guardando configuración: {error}")
        show_toast(f"Error al guardar: {error}", success=False, parent=self.main_window)

    # ==========================================================
    # 4.1: Guardar Issuer Profile
    # ==========================================================
    def _on_save_issuer(self):
        self.btn_save_issuer.setEnabled(False)
        self.btn_save_issuer.setText("Guardando emisor...")

        # Extraer código de id_type del combo (e.g. "02 - Cédula Jurídica" → "02")
        id_type_text = self.iss_id_type.currentText()
        id_type_code = id_type_text.split(" - ")[0].strip() if " - " in id_type_text else "01"

        # Extraer código de condición/referencia
        cond_text = self.iss_rep_condicion.currentText()
        cond_code = cond_text.split(" - ")[0].strip() if " - " in cond_text else None
        ref_text = self.iss_rep_referencia.currentText()
        ref_code = ref_text.split(" - ")[0].strip() if " - " in ref_text else None

        payload = {
            "legal_name": self.iss_legal_name.text() or None,
            "commercial_name": self.iss_commercial_name.text() or None,
            "id_type": id_type_code,
            "id_number": self.iss_id_number.text() or None,
            "email": self.iss_email.text() or None,
            "phone": self.iss_phone.text() or None,
            "economic_activity_code": self.iss_economic_activity.text() or None,
            "provider_system_id": self.iss_provider_system.text() or None,
            "provincia": self.iss_provincia.text() or None,
            "canton": self.iss_canton.text() or None,
            "distrito": self.iss_distrito.text() or None,
            "barrio": self.iss_barrio.text() or None,
            "otras_senas": self.iss_otras_senas.text() or None,
            "branch_code": self.iss_branch_code.text() or None,
            "terminal_code": self.iss_terminal_code.text() or None,
            "enable_rep": 1 if self.iss_enable_rep.isChecked() else 0,
            "rep_default_condicion_venta": cond_code if cond_code else None,
            "rep_default_codigo_referencia": ref_code if ref_code else None,
        }

        # 5.5: Sanitizar inputs (strip whitespace, vacíos → None)
        payload = self._sanitize_payload(payload)

        # Eliminar keys con valor None para no enviar campos vacíos
        payload = {k: v for k, v in payload.items() if v is not None}

        self._cleanup_thread()
        self._worker = _SaveIssuerWorker(payload)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_issuer_save_success)
        self._worker.failed.connect(self._on_issuer_save_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)

        self._thread.start()

    def _on_issuer_save_success(self, result: dict):
        self._dirty = False
        self.btn_save_issuer.setEnabled(True)
        self.btn_save_issuer.setText("💾 Guardar Perfil Emisor")
        show_toast("✅ Perfil de emisor guardado", success=True, parent=self.main_window)

    def _on_issuer_save_failed(self, error: str):
        self.btn_save_issuer.setEnabled(True)
        self.btn_save_issuer.setText("💾 Guardar Perfil Emisor")
        logger.error(f"Error guardando emisor: {error}")
        show_toast(f"Error al guardar emisor: {error}", success=False, parent=self.main_window)

    # ==========================================================
    # 4.2: Upload de logo
    # ==========================================================
    def _on_upload_logo(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar logo",
            "", "Imágenes (*.png *.jpg *.jpeg *.webp)"
        )
        if not filepath:
            return

        self.btn_upload_logo.setEnabled(False)
        self.btn_upload_logo.setText("Subiendo...")

        self._cleanup_thread()
        self._worker = _UploadLogoWorker(filepath)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_logo_success)
        self._worker.failed.connect(self._on_logo_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)

        self._thread.start()

    def _on_logo_success(self, result: dict):
        self.btn_upload_logo.setEnabled(True)
        self.btn_upload_logo.setText("📁 Subir logo")

        logo_path = result.get("data", {}).get("logo_path", "")
        if logo_path and os.path.isfile(logo_path):
            pix = QPixmap(logo_path).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.label_logo_preview.setPixmap(pix)

        show_toast("✅ Logo actualizado", success=True, parent=self.main_window)

    def _on_logo_failed(self, error: str):
        self.btn_upload_logo.setEnabled(True)
        self.btn_upload_logo.setText("📁 Subir logo")
        logger.error(f"Error subiendo logo: {error}")
        show_toast(f"Error al subir logo: {error}", success=False, parent=self.main_window)

    # ==========================================================
    # CABYS
    # ==========================================================
    def _on_update_cabys(self):
        reply = QMessageBox.question(
            self, "Actualizar CABYS",
            "¿Deseas actualizar el catálogo CABYS?\nEsto puede tardar varios minutos.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._cabys_progress = QProgressDialog(
            "Descargando y procesando catálogo CABYS...\n"
            "Esto puede tardar varios minutos. Por favor espera.",
            None, 0, 0, self,
        )
        self._cabys_progress.setWindowTitle("Actualizando CABYS")
        self._cabys_progress.setWindowModality(Qt.WindowModal)
        self._cabys_progress.setMinimumWidth(400)
        self._cabys_progress.show()

        self.btn_update_cabys.setEnabled(False)
        self.btn_update_cabys.setText("Actualizando...")

        self._cleanup_thread()
        self._worker = _UpdateCabysWorker()
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_cabys_success)
        self._worker.failed.connect(self._on_cabys_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)

        self._thread.start()

    def _on_cabys_success(self, result: dict):
        if hasattr(self, '_cabys_progress') and self._cabys_progress:
            self._cabys_progress.close()
        self.btn_update_cabys.setEnabled(True)
        self.btn_update_cabys.setText("🔄 Actualizar CABYS desde Hacienda")
        registros = result.get("data", {}).get("registros", 0)
        show_toast(f"✅ CABYS actualizado ({registros} registros)", success=True, parent=self.main_window)
        self._start_load()

    def _on_cabys_failed(self, error: str):
        if hasattr(self, '_cabys_progress') and self._cabys_progress:
            self._cabys_progress.close()
        self.btn_update_cabys.setEnabled(True)
        self.btn_update_cabys.setText("🔄 Actualizar CABYS desde Hacienda")
        logger.error(f"Error actualizando CABYS: {error}")
        show_toast(f"Error CABYS: {error}", success=False, parent=self.main_window)

    # ==========================================================
    # 6.5: Populate system info
    # ==========================================================
    def _populate_sys_info(self, sys_info: dict, settings_data: dict):
        if not sys_info:
            supplier_name = settings_data.get("supplier_name", "—") or "—"
            rec = settings_data.get("cabys_records", 0)
            self.label_sys_info.setText(
                f"Proveedor predeterminado: {supplier_name}\n"
                f"Registros CABYS: {rec}"
            )
            return

        counts = sys_info.get("table_counts", {})
        lines = [
            f"🖥️ {sys_info.get('app_name', '?')} — {sys_info.get('app_env', '?')}",
            f"🐍 Python {sys_info.get('python_version', '?')} | {sys_info.get('os', '?')}",
            f"🗄️ MySQL {sys_info.get('db_version', '?')} — {sys_info.get('db_name', '?')} ({sys_info.get('db_size', '?')})",
            f"💽 Disco: {sys_info.get('disk', '?')}",
            f"📊 Productos: {counts.get('products', '?')} | Clientes: {counts.get('customers', '?')} | "
            f"Ventas: {counts.get('sales', '?')} | Proveedores: {counts.get('suppliers', '?')} | "
            f"CABYS: {counts.get('cabys_items', '?')}",
        ]
        self.label_sys_info.setText("\n".join(lines))

    # ==========================================================
    # 6.1: Backup
    # ==========================================================
    def _on_backup(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar backup", "backup.sql", "SQL Files (*.sql)"
        )
        if not path:
            return

        self.btn_backup.setEnabled(False)
        self.btn_backup.setText("Creando backup...")

        self._cleanup_thread()
        self._worker = _BackupWorker(path)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_backup_success)
        self._worker.failed.connect(self._on_backup_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_backup_success(self, filepath: str):
        self.btn_backup.setEnabled(True)
        self.btn_backup.setText("📥 Crear Backup")
        show_toast(f"✅ Backup guardado en: {os.path.basename(filepath)}", success=True, parent=self.main_window)

    def _on_backup_failed(self, error: str):
        self.btn_backup.setEnabled(True)
        self.btn_backup.setText("📥 Crear Backup")
        show_toast(f"Error al crear backup: {error}", success=False, parent=self.main_window)

    # ==========================================================
    # 6.1: Restore
    # ==========================================================
    def _on_restore(self):
        reply = QMessageBox.warning(
            self, "⚠️ Restaurar Base de Datos",
            "ATENCIÓN: Esto reemplazará TODOS los datos actuales\n"
            "con los del archivo de backup seleccionado.\n\n"
            "Esta acción NO se puede deshacer.\n\n"
            "¿Estás seguro de continuar?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar backup", "", "SQL Files (*.sql)"
        )
        if not path:
            return

        self.btn_restore.setEnabled(False)
        self.btn_restore.setText("Restaurando...")

        self._cleanup_thread()
        self._worker = _RestoreWorker(path)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_restore_success)
        self._worker.failed.connect(self._on_restore_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_restore_success(self, result: dict):
        self.btn_restore.setEnabled(True)
        self.btn_restore.setText("📤 Restaurar Backup")
        show_toast("✅ Base de datos restaurada correctamente", success=True, parent=self.main_window)
        self._start_load()

    def _on_restore_failed(self, error: str):
        self.btn_restore.setEnabled(True)
        self.btn_restore.setText("📤 Restaurar Backup")
        show_toast(f"Error al restaurar: {error}", success=False, parent=self.main_window)

    # ==========================================================
    # 6.6: Export config
    # ==========================================================
    def _on_export_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar configuración", "config_export.json", "JSON Files (*.json)"
        )
        if not path:
            return

        self.btn_export_config.setEnabled(False)
        self._cleanup_thread()
        self._worker = _ExportConfigWorker(path)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(lambda p: (
            self.btn_export_config.setEnabled(True),
            show_toast(f"✅ Config exportada: {os.path.basename(p)}", success=True, parent=self.main_window),
        ))
        self._worker.failed.connect(lambda e: (
            self.btn_export_config.setEnabled(True),
            show_toast(f"Error exportando: {e}", success=False, parent=self.main_window),
        ))
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    # ==========================================================
    # 6.6: Import config
    # ==========================================================
    def _on_import_config(self):
        reply = QMessageBox.question(
            self, "Importar configuración",
            "Esto sobrescribirá la configuración actual con los datos del archivo.\n"
            "¿Deseas continuar?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo de configuración", "", "JSON Files (*.json)"
        )
        if not path:
            return

        self.btn_import_config.setEnabled(False)
        self._cleanup_thread()
        self._worker = _ImportConfigWorker(path)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(lambda r: (
            self.btn_import_config.setEnabled(True),
            show_toast("✅ Configuración importada", success=True, parent=self.main_window),
            self._start_load(),
        ))
        self._worker.failed.connect(lambda e: (
            self.btn_import_config.setEnabled(True),
            show_toast(f"Error importando: {e}", success=False, parent=self.main_window),
        ))
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    # ==========================================================
    # FASE 5 AI: Tab Asistente IA
    # ==========================================================
    def _build_tab_ai(self) -> QWidget:
        """Construye la pestaña de configuración del asistente IA."""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ── Mapa de proveedores → modelos (se actualiza al cargar) ──
        self._ai_provider_models = {
            "none": [],
            "anthropic": ["claude-sonnet-4-20250514"],
            "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
            "google": ["gemini-2.0-flash"],
        }

        # ── Estado ──
        grp_status = QGroupBox("Estado del Asistente")
        grp_status.setStyleSheet(self._group_style())
        status_layout = QHBoxLayout(grp_status)

        self.ai_status_led = QLabel("●")
        self.ai_status_led.setFixedWidth(20)
        self.ai_status_led.setStyleSheet("font-size: 18px; color: #ef4444;")
        status_layout.addWidget(self.ai_status_led)

        self.ai_status_label = QLabel("Sin configurar")
        self.ai_status_label.setStyleSheet("font-size: 13px; color: #9ca3af;")
        status_layout.addWidget(self.ai_status_label)
        status_layout.addStretch()

        self.btn_ai_reload = QPushButton("🔄 Recargar")
        self.btn_ai_reload.setCursor(Qt.PointingHandCursor)
        self.btn_ai_reload.setStyleSheet(self._small_btn_style())
        self.btn_ai_reload.clicked.connect(self._load_ai_config)
        status_layout.addWidget(self.btn_ai_reload)

        layout.addWidget(grp_status)

        # ── Proveedor y API Key ──
        grp_provider = QGroupBox("Proveedor de IA")
        grp_provider.setStyleSheet(self._group_style())
        form_provider = QFormLayout(grp_provider)
        form_provider.setSpacing(12)

        self.combo_ai_provider = QComboBox()
        self.combo_ai_provider.addItem("— Ninguno —", "none")
        self.combo_ai_provider.addItem("🟣 Claude (Anthropic)", "anthropic")
        self.combo_ai_provider.addItem("🟢 ChatGPT (OpenAI)", "openai")
        self.combo_ai_provider.addItem("🔵 Gemini (Google)", "google")
        self.combo_ai_provider.currentIndexChanged.connect(self._on_ai_provider_changed)
        form_provider.addRow("Proveedor:", self.combo_ai_provider)

        # API Key con toggle de visibilidad
        key_row = QHBoxLayout()
        self.input_ai_key = QLineEdit()
        self.input_ai_key.setEchoMode(QLineEdit.Password)
        self.input_ai_key.setPlaceholderText("Pegá tu API key aquí...")
        self.input_ai_key.setMinimumWidth(300)
        key_row.addWidget(self.input_ai_key)

        self.btn_ai_show_key = QPushButton("👁")
        self.btn_ai_show_key.setFixedSize(32, 28)
        self.btn_ai_show_key.setCursor(Qt.PointingHandCursor)
        self.btn_ai_show_key.setToolTip("Mostrar/ocultar API key")
        self.btn_ai_show_key.setStyleSheet(self._small_btn_style())
        self.btn_ai_show_key.clicked.connect(self._toggle_ai_key_visibility)
        key_row.addWidget(self.btn_ai_show_key)
        form_provider.addRow("API Key:", key_row)

        self.ai_key_hint = QLabel("")
        self.ai_key_hint.setStyleSheet("font-size: 11px; color: #6b7280;")
        form_provider.addRow("", self.ai_key_hint)

        # Modelo
        self.combo_ai_model = QComboBox()
        form_provider.addRow("Modelo:", self.combo_ai_model)

        # Habilitado
        self.chk_ai_enabled = QCheckBox("Asistente IA habilitado")
        self.chk_ai_enabled.setStyleSheet("font-size: 13px; color: #e5e7eb;")
        form_provider.addRow("", self.chk_ai_enabled)

        layout.addWidget(grp_provider)

        # ── Botón probar conexión ──
        test_row = QHBoxLayout()
        self.btn_ai_test = QPushButton("🔌 Probar conexión")
        self.btn_ai_test.setCursor(Qt.PointingHandCursor)
        self.btn_ai_test.setMinimumHeight(34)
        self.btn_ai_test.setStyleSheet("""
            QPushButton {
                background-color: #1e293b; color: #e5e7eb;
                font-weight: bold; font-size: 13px;
                padding: 6px 20px; border-radius: 8px;
                border: 1px solid #334155;
            }
            QPushButton:hover { background-color: #334155; }
            QPushButton:disabled { color: #555; }
        """)
        self.btn_ai_test.clicked.connect(self._on_test_ai)
        test_row.addWidget(self.btn_ai_test)
        test_row.addStretch()
        layout.addLayout(test_row)

        # ── Opciones avanzadas (colapsable) ──
        self.btn_ai_advanced_toggle = QPushButton("▶ Opciones avanzadas")
        self.btn_ai_advanced_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_ai_advanced_toggle.setStyleSheet("""
            QPushButton {
                background: transparent; border: none;
                color: #6366f1; font-size: 12px; text-align: left;
                padding: 4px 0;
            }
            QPushButton:hover { color: #818cf8; }
        """)
        self.btn_ai_advanced_toggle.clicked.connect(self._toggle_ai_advanced)
        layout.addWidget(self.btn_ai_advanced_toggle)

        self.ai_advanced_container = QWidget()
        adv_form = QFormLayout(self.ai_advanced_container)
        adv_form.setSpacing(10)

        self.spin_ai_temperature = QDoubleSpinBox()
        self.spin_ai_temperature.setRange(0.0, 1.0)
        self.spin_ai_temperature.setSingleStep(0.1)
        self.spin_ai_temperature.setDecimals(1)
        self.spin_ai_temperature.setValue(0.3)
        adv_form.addRow("Temperature:", self.spin_ai_temperature)

        self.spin_ai_max_tokens = QSpinBox()
        self.spin_ai_max_tokens.setRange(256, 4096)
        self.spin_ai_max_tokens.setSingleStep(256)
        self.spin_ai_max_tokens.setValue(1024)
        adv_form.addRow("Max tokens:", self.spin_ai_max_tokens)

        self.input_ai_custom_prompt = QTextEdit()
        self.input_ai_custom_prompt.setPlaceholderText(
            "Instrucciones adicionales para el asistente...\n"
            "Ej: \"Somos una ferretería en Heredia. "
            "Nuestros clientes principales son contratistas.\""
        )
        self.input_ai_custom_prompt.setMaximumHeight(100)
        self.input_ai_custom_prompt.setStyleSheet(
            "background-color: #1c1c1c; color: #e5e7eb; border: 1px solid #333; "
            "border-radius: 6px; padding: 6px; font-size: 12px;"
        )
        adv_form.addRow("Prompt personalizado:", self.input_ai_custom_prompt)

        self.ai_advanced_container.setVisible(False)
        layout.addWidget(self.ai_advanced_container)

        # ── Botón guardar AI config ──
        save_row = QHBoxLayout()
        save_row.addStretch()
        self.btn_ai_save = QPushButton("💾 Guardar configuración IA")
        self.btn_ai_save.setCursor(Qt.PointingHandCursor)
        self.btn_ai_save.setMinimumHeight(38)
        self.btn_ai_save.setStyleSheet("""
            QPushButton {
                background-color: #3a86ff; color: white;
                font-weight: bold; font-size: 14px;
                padding: 8px 28px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background-color: #2b6fe0; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        self.btn_ai_save.clicked.connect(self._on_save_ai)
        save_row.addWidget(self.btn_ai_save)
        save_row.addStretch()
        layout.addLayout(save_row)

        layout.addStretch()
        scroll.setWidget(content)

        wrapper = QVBoxLayout(tab)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(scroll)

        # Cargar la config al iniciar
        QTimer.singleShot(500, self._load_ai_config)

        return tab

    # ── Helpers de estilo para la tab AI ──

    @staticmethod
    def _group_style() -> str:
        return """
            QGroupBox {
                font-size: 14px; font-weight: bold; color: #e5e7eb;
                border: 1px solid #2a2a2a; border-radius: 8px;
                margin-top: 12px; padding-top: 18px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px; padding: 0 6px;
            }
        """

    @staticmethod
    def _small_btn_style() -> str:
        return """
            QPushButton {
                background-color: #1e293b; color: #e5e7eb;
                border: 1px solid #334155; border-radius: 4px;
                padding: 2px 8px; font-size: 12px;
            }
            QPushButton:hover { background-color: #334155; }
        """

    # ── Eventos de la tab AI ──

    def _on_ai_provider_changed(self, index: int):
        """Actualiza los modelos disponibles al cambiar proveedor."""
        provider = self.combo_ai_provider.currentData() or "none"
        models = self._ai_provider_models.get(provider, [])
        self.combo_ai_model.clear()
        for m in models:
            self.combo_ai_model.addItem(m, m)

        # Deshabilitar campos si no hay proveedor
        has_provider = provider != "none"
        self.input_ai_key.setEnabled(has_provider)
        self.btn_ai_test.setEnabled(has_provider)
        self.combo_ai_model.setEnabled(has_provider)
        self.chk_ai_enabled.setEnabled(has_provider)

    def _toggle_ai_key_visibility(self):
        """Alterna entre mostrar y ocultar la API key."""
        if self.input_ai_key.echoMode() == QLineEdit.Password:
            self.input_ai_key.setEchoMode(QLineEdit.Normal)
            self.btn_ai_show_key.setText("🙈")
        else:
            self.input_ai_key.setEchoMode(QLineEdit.Password)
            self.btn_ai_show_key.setText("👁")

    def _toggle_ai_advanced(self):
        """Muestra u oculta las opciones avanzadas."""
        visible = not self.ai_advanced_container.isVisible()
        self.ai_advanced_container.setVisible(visible)
        self.btn_ai_advanced_toggle.setText(
            "▼ Opciones avanzadas" if visible else "▶ Opciones avanzadas"
        )

    # ── Cargar AI config ──

    def _load_ai_config(self):
        """Carga la config de IA desde el backend en un hilo."""
        self._cleanup_thread()
        self._worker = _LoadAIConfigWorker()
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_ai_config_loaded)
        self._worker.failed.connect(self._on_ai_config_load_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_ai_config_loaded(self, config: dict, providers: list):
        """Rellena los campos con la config de IA cargada."""
        # Actualizar mapa de modelos si el backend envió proveedores
        if providers:
            for p in providers:
                name = p.get("name", "")
                models = p.get("models", [])
                if name and models:
                    self._ai_provider_models[name] = models

        # Seleccionar proveedor
        provider = config.get("provider", "none")
        for i in range(self.combo_ai_provider.count()):
            if self.combo_ai_provider.itemData(i) == provider:
                self.combo_ai_provider.setCurrentIndex(i)
                break

        # Key hint
        has_key = config.get("has_api_key", False)
        hint = config.get("api_key_hint", "")
        if has_key and hint:
            self.ai_key_hint.setText(f"🔑 Key guardada: {hint}")
            self.input_ai_key.setPlaceholderText("Dejá vacío para mantener la key actual...")
        else:
            self.ai_key_hint.setText("")
            self.input_ai_key.setPlaceholderText("Pegá tu API key aquí...")

        # Modelo
        model = config.get("model") or ""
        if model:
            idx = self.combo_ai_model.findData(model)
            if idx >= 0:
                self.combo_ai_model.setCurrentIndex(idx)

        # Habilitado
        self.chk_ai_enabled.setChecked(config.get("is_enabled", False))

        # Avanzado
        self.spin_ai_temperature.setValue(config.get("temperature", 0.3))
        self.spin_ai_max_tokens.setValue(config.get("max_tokens", 1024))
        self.input_ai_custom_prompt.setPlainText(config.get("custom_prompt") or "")

        # Status LED
        if config.get("is_enabled") and has_key and provider != "none":
            self.ai_status_led.setStyleSheet("font-size: 18px; color: #10b981;")
            prov_names = {"anthropic": "Claude", "openai": "ChatGPT", "google": "Gemini"}
            self.ai_status_label.setText(f"Conectado — {prov_names.get(provider, provider)}")
            self.ai_status_label.setStyleSheet("font-size: 13px; color: #10b981;")
        else:
            self.ai_status_led.setStyleSheet("font-size: 18px; color: #ef4444;")
            self.ai_status_label.setText("Sin configurar")
            self.ai_status_label.setStyleSheet("font-size: 13px; color: #9ca3af;")

    def _on_ai_config_load_failed(self, error: str):
        logger.debug(f"No se pudo cargar AI config (normal si es primera vez): {error}")
        self.ai_status_led.setStyleSheet("font-size: 18px; color: #f59e0b;")
        self.ai_status_label.setText("No disponible")
        self.ai_status_label.setStyleSheet("font-size: 13px; color: #f59e0b;")

    # ── Guardar AI config ──

    def _on_save_ai(self):
        """Guarda la configuración de IA."""
        provider = self.combo_ai_provider.currentData() or "none"

        payload = {
            "provider": provider,
            "model": self.combo_ai_model.currentData() or self.combo_ai_model.currentText(),
            "is_enabled": self.chk_ai_enabled.isChecked(),
            "max_tokens": self.spin_ai_max_tokens.value(),
            "temperature": self.spin_ai_temperature.value(),
            "custom_prompt": self.input_ai_custom_prompt.toPlainText().strip() or None,
        }

        # Solo enviar api_key si el usuario escribió algo nuevo
        key_text = self.input_ai_key.text().strip()
        if key_text:
            payload["api_key"] = key_text

        self.btn_ai_save.setEnabled(False)
        self.btn_ai_save.setText("Guardando...")

        self._cleanup_thread()
        self._worker = _SaveAIConfigWorker(payload)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_ai_save_success)
        self._worker.failed.connect(self._on_ai_save_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_ai_save_success(self, result: dict):
        self.btn_ai_save.setEnabled(True)
        self.btn_ai_save.setText("💾 Guardar configuración IA")
        self.input_ai_key.clear()
        show_toast("✅ Configuración de IA guardada", success=True, parent=self.main_window)
        self._load_ai_config()

    def _on_ai_save_failed(self, error: str):
        self.btn_ai_save.setEnabled(True)
        self.btn_ai_save.setText("💾 Guardar configuración IA")
        show_toast(f"Error guardando config IA: {error}", success=False, parent=self.main_window)

    # ── Test de conexión ──

    def _on_test_ai(self):
        """Prueba la conexión con el proveedor seleccionado."""
        provider = self.combo_ai_provider.currentData() or "none"
        if provider == "none":
            show_toast("Seleccioná un proveedor primero", success=False, parent=self.main_window)
            return

        key = self.input_ai_key.text().strip()
        if not key:
            show_toast("Ingresá la API key para probar", success=False, parent=self.main_window)
            return

        payload = {
            "provider": provider,
            "api_key": key,
            "model": self.combo_ai_model.currentData() or self.combo_ai_model.currentText() or None,
        }

        self.btn_ai_test.setEnabled(False)
        self.btn_ai_test.setText("Probando...")

        self._cleanup_thread()
        self._worker = _TestAIConfigWorker(payload)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_ai_test_result)
        self._worker.failed.connect(self._on_ai_test_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_ai_test_result(self, result: dict):
        self.btn_ai_test.setEnabled(True)
        self.btn_ai_test.setText("🔌 Probar conexión")
        success = result.get("success", False)
        message = result.get("message", "Sin respuesta")
        show_toast(message, success=success, parent=self.main_window)

    def _on_ai_test_failed(self, error: str):
        self.btn_ai_test.setEnabled(True)
        self.btn_ai_test.setText("🔌 Probar conexión")
        show_toast(f"Error en test: {error}", success=False, parent=self.main_window)

    # ==========================================================
    # Dirty tracking y utilidades
    # ==========================================================
    def _mark_dirty(self, *_args):
        self._dirty = True

    @staticmethod
    def _sanitize(text: str) -> str:
        """Strip de espacios en blanco en un string (5.5)."""
        return text.strip() if isinstance(text, str) else text

    @staticmethod
    def _sanitize_payload(payload: dict) -> dict:
        """Aplica strip() a todos los valores string del payload (5.5)."""
        cleaned = {}
        for k, v in payload.items():
            if isinstance(v, str):
                v = v.strip()
                # Convertir strings vacíos a None para no enviar basura
                cleaned[k] = v if v else None
            else:
                cleaned[k] = v
        return cleaned

    def _cleanup_thread(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)
        self._thread = None
        self._worker = None