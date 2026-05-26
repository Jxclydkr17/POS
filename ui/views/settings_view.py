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
    QFileDialog, QSpinBox, QDoubleSpinBox, QTextEdit, QDialog,
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


# ── Workers para Hacienda y Email config ──

class _LoadHaciendaConfigWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            from ui.services.settings_service import fetch_hacienda_config
            result = fetch_hacienda_config()
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class _SaveHaciendaConfigWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self):
        try:
            from ui.services.settings_service import save_hacienda_config
            result = save_hacienda_config(self._payload)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class _UploadCertWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, filepath: str, password: str, parent=None):
        super().__init__(parent)
        self._filepath = filepath
        self._password = password

    def run(self):
        try:
            from ui.services.settings_service import upload_hacienda_cert
            result = upload_hacienda_cert(self._filepath, self._password)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

class _LoadEmailConfigWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            from ui.services.settings_service import fetch_email_config
            result = fetch_email_config()
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class _SaveEmailConfigWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self):
        try:
            from ui.services.settings_service import save_email_config
            result = save_email_config(self._payload)
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

        # Cache de usuarios (tab Usuarios)
        self._users_cache = []
        self._all_permissions = []
        self._default_permissions = {}

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
        self.tab_widget.addTab(self._build_tab_usuarios(), "👥 Usuarios")

        self.tab_widget.currentChanged.connect(self._on_tab_changed)

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
    def _on_tab_changed(self, index: int):
        """Carga datos bajo demanda al cambiar de pestaña."""
        tab_text = self.tab_widget.tabText(index)
        if "Usuarios" in tab_text and not self._users_cache:
            self._load_users()

    # ----------------------------------------------------------
    # Tab: Empresa (datos)
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

        # ── Hacienda: credenciales editables desde la UI ──
        box_hacienda = QGroupBox("🔗 Conexión con Hacienda")
        hac_layout = QVBoxLayout()

        form_hac = QFormLayout()
        form_hac.setSpacing(10)

        self.combo_hacienda_env = QComboBox()
        self.combo_hacienda_env.addItems(["sandbox", "production"])
        form_hac.addRow("Ambiente:", self.combo_hacienda_env)

        self.input_hacienda_api = QLineEdit()
        self.input_hacienda_api.setPlaceholderText("https://api.comprobanteselectronicos.go.cr")
        form_hac.addRow("URL API:", self.input_hacienda_api)

        self.input_hacienda_user = QLineEdit()
        self.input_hacienda_user.setPlaceholderText("Usuario OAuth2 de Hacienda")
        form_hac.addRow("Usuario:", self.input_hacienda_user)

        self.input_hacienda_password = QLineEdit()
        self.input_hacienda_password.setEchoMode(QLineEdit.Password)
        self.input_hacienda_password.setPlaceholderText("Contraseña OAuth2")
        form_hac.addRow("Contraseña:", self.input_hacienda_password)

        hac_layout.addLayout(form_hac)

        # Certificado .p12
        cert_row = QHBoxLayout()
        self.label_cert_status = QLabel("Sin certificado")
        self.label_cert_status.setStyleSheet("font-size: 12px; color: #888;")
        cert_row.addWidget(self.label_cert_status)

        self.btn_upload_cert = QPushButton("📁 Subir .p12")
        self.btn_upload_cert.setMinimumHeight(30)
        self.btn_upload_cert.clicked.connect(self._on_upload_cert)
        cert_row.addWidget(self.btn_upload_cert)
        cert_row.addStretch()
        hac_layout.addLayout(cert_row)

        # Status general
        self.label_hacienda_status = QLabel("")
        self.label_hacienda_status.setStyleSheet("font-size: 12px; color: #aaa;")
        self.label_hacienda_status.setWordWrap(True)
        hac_layout.addWidget(self.label_hacienda_status)

        # Botón guardar Hacienda
        btn_row_hac = QHBoxLayout()
        self.btn_save_hacienda = QPushButton("💾 Guardar Hacienda")
        self.btn_save_hacienda.setMinimumHeight(34)
        self.btn_save_hacienda.setStyleSheet("""
            QPushButton {
                background-color: #6366f1; color: white;
                font-weight: bold; font-size: 13px;
                padding: 6px 20px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background-color: #4f46e5; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        self.btn_save_hacienda.clicked.connect(self._on_save_hacienda)
        btn_row_hac.addWidget(self.btn_save_hacienda)
        btn_row_hac.addStretch()
        hac_layout.addLayout(btn_row_hac)

        box_hacienda.setLayout(hac_layout)
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
    # Tab: Impresora (Fase 4.3 + Fix 2.5 cerrado)
    # ----------------------------------------------------------
    def _build_tab_impresora(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignTop)

        box = QGroupBox("🖨️ Impresora Térmica")
        form = QFormLayout()
        form.setSpacing(10)

        self.combo_printer_type = QComboBox()
        # Fix 2.5 (cerrado): los tres modos ahora funcionan de verdad.
        # 'network' → ESC/POS por TCP, 'usb' → ESC/POS por USB,
        # 'none' → desactiva el botón "Imprimir" del ticket.
        self.combo_printer_type.addItems(["network", "usb", "none"])

        # ── Campos para "network" ──
        self.input_printer_ip = QLineEdit()
        self.input_printer_ip.setPlaceholderText("192.168.0.120")

        self.input_printer_port = QSpinBox()
        self.input_printer_port.setRange(1, 65535)
        self.input_printer_port.setValue(9100)

        # ── Campos para "usb" ──
        # Vendor/Product IDs como strings hex ("0x04b8") — el user los
        # copia textualmente desde lsusb o Administrador de dispositivos.
        # Validación final ocurre en el schema Pydantic del backend.
        self.input_printer_usb_vendor = QLineEdit()
        self.input_printer_usb_vendor.setPlaceholderText("0x04b8 (ej. Epson)")
        self.input_printer_usb_vendor.setMaxLength(10)

        self.input_printer_usb_product = QLineEdit()
        self.input_printer_usb_product.setPlaceholderText("0x0202 (ej. TM-T20)")
        self.input_printer_usb_product.setMaxLength(10)

        # ── Campos comunes (network + usb) ──
        self.input_printer_profile = QLineEdit()
        self.input_printer_profile.setPlaceholderText("(opcional) TM-T20II, TM-T88III…")
        self.input_printer_profile.setMaxLength(40)

        self.combo_printer_paper_width = QComboBox()
        self.combo_printer_paper_width.addItem("80 mm (común)", 80)
        self.combo_printer_paper_width.addItem("58 mm (POS pequeño)", 58)

        # Filas del form. Guardamos referencia a las filas USB para
        # mostrarlas/ocultarlas según printer_type.
        form.addRow("Tipo de conexión:", self.combo_printer_type)

        # Etiquetas en variables para poder ocultarlas también (QFormLayout
        # asocia un label con cada field; setRowVisible las maneja juntas
        # en Qt6 pero acá guardamos refs para .setVisible explícito).
        self._lbl_printer_ip = QLabel("Dirección IP:")
        form.addRow(self._lbl_printer_ip, self.input_printer_ip)

        self._lbl_printer_port = QLabel("Puerto:")
        form.addRow(self._lbl_printer_port, self.input_printer_port)

        self._lbl_printer_usb_vendor = QLabel("USB Vendor ID:")
        form.addRow(self._lbl_printer_usb_vendor, self.input_printer_usb_vendor)

        self._lbl_printer_usb_product = QLabel("USB Product ID:")
        form.addRow(self._lbl_printer_usb_product, self.input_printer_usb_product)

        self._lbl_printer_profile = QLabel("Perfil python-escpos:")
        form.addRow(self._lbl_printer_profile, self.input_printer_profile)

        self._lbl_printer_paper_width = QLabel("Ancho de papel:")
        form.addRow(self._lbl_printer_paper_width, self.combo_printer_paper_width)

        box.setLayout(form)
        layout.addWidget(box)

        # ── Botón "Probar impresión" (Fix 2.5 cerrado) ──
        btn_row_test = QHBoxLayout()
        self.btn_test_printer = QPushButton("🧾 Probar impresión")
        self.btn_test_printer.setMinimumHeight(34)
        self.btn_test_printer.setStyleSheet("""
            QPushButton {
                background-color: #10b981; color: white;
                font-weight: bold; font-size: 13px;
                padding: 6px 20px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        self.btn_test_printer.clicked.connect(self._on_test_printer)
        btn_row_test.addWidget(self.btn_test_printer)
        btn_row_test.addStretch()
        layout.addLayout(btn_row_test)

        note = QLabel(
            "ℹ️ Estos valores se usan al imprimir tickets de venta y "
            "comprobantes electrónicos.\n\n"
            "Tipo 'network': impresora térmica en red — envía ESC/POS por TCP "
            "al puerto configurado (típicamente 9100, modo RAW).\n"
            "Tipo 'usb': impresora térmica USB — requiere instalar `pyusb` "
            "y conocer Vendor/Product IDs (consulte `lsusb` en Linux o el "
            "Administrador de dispositivos en Windows).\n"
            "Tipo 'none': desactiva el botón 'Imprimir' del ticket; el PDF "
            "se sigue generando para visualización.\n\n"
            "💡 Antes de guardar cambios, use 'Probar impresión' para validar "
            "la conectividad con un ticket corto. La primera vez que se "
            "imprime puede tardar unos segundos mientras el SO inicializa "
            "el driver USB."
        )
        note.setStyleSheet("color: #888; font-size: 12px; margin-top: 12px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        # ── Email: credenciales editables desde la UI ──
        box_email = QGroupBox("📧 Configuración de Email")
        email_layout = QVBoxLayout()

        form_email = QFormLayout()
        form_email.setSpacing(10)

        self.input_email_user = QLineEdit()
        self.input_email_user.setPlaceholderText("correo@gmail.com")
        form_email.addRow("Correo:", self.input_email_user)

        self.input_email_pass = QLineEdit()
        self.input_email_pass.setEchoMode(QLineEdit.Password)
        self.input_email_pass.setPlaceholderText("Contraseña o App Password")
        form_email.addRow("Contraseña:", self.input_email_pass)

        email_layout.addLayout(form_email)

        self.label_email_status = QLabel("")
        self.label_email_status.setStyleSheet("font-size: 12px; color: #aaa;")
        email_layout.addWidget(self.label_email_status)

        note_email = QLabel(
            "ℹ️ Para Gmail usá una 'App Password' (no tu contraseña normal).\n"
            "Generala en myaccount.google.com > Seguridad > Contraseñas de apps."
        )
        note_email.setStyleSheet("color: #666; font-size: 11px;")
        note_email.setWordWrap(True)
        email_layout.addWidget(note_email)

        btn_row_email = QHBoxLayout()
        self.btn_save_email = QPushButton("💾 Guardar Email")
        self.btn_save_email.setMinimumHeight(34)
        self.btn_save_email.setStyleSheet("""
            QPushButton {
                background-color: #6366f1; color: white;
                font-weight: bold; font-size: 13px;
                padding: 6px 20px; border-radius: 8px; border: none;
            }
            QPushButton:hover { background-color: #4f46e5; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        self.btn_save_email.clicked.connect(self._on_save_email)
        btn_row_email.addWidget(self.btn_save_email)
        btn_row_email.addStretch()
        email_layout.addLayout(btn_row_email)

        box_email.setLayout(email_layout)
        layout.addWidget(box_email)

        # Dirty tracking
        self.combo_printer_type.currentIndexChanged.connect(self._mark_dirty)
        self.input_printer_ip.textChanged.connect(self._mark_dirty)
        self.input_printer_port.valueChanged.connect(self._mark_dirty)
        self.input_printer_usb_vendor.textChanged.connect(self._mark_dirty)
        self.input_printer_usb_product.textChanged.connect(self._mark_dirty)
        self.input_printer_profile.textChanged.connect(self._mark_dirty)
        self.combo_printer_paper_width.currentIndexChanged.connect(self._mark_dirty)

        # Mostrar/ocultar campos según printer_type seleccionado.
        # Conectamos DESPUÉS del dirty para que la sincronización
        # inicial (al cargar settings) no marque dirty=True.
        self.combo_printer_type.currentTextChanged.connect(self._sync_printer_fields_visibility)

        layout.addStretch()
        return tab

    # ----------------------------------------------------------
    # Fix 2.5 (cerrado): muestra/oculta campos según el tipo de
    # impresora seleccionado. Mantiene la UI limpia: no tiene sentido
    # mostrar el IP cuando elegiste USB.
    # ----------------------------------------------------------
    def _sync_printer_fields_visibility(self, *_args):
        printer_type = self.combo_printer_type.currentText().lower()
        is_network = printer_type == "network"
        is_usb = printer_type == "usb"
        is_active = is_network or is_usb  # "none" oculta todo lo demás

        # Network-only
        self._lbl_printer_ip.setVisible(is_network)
        self.input_printer_ip.setVisible(is_network)
        self._lbl_printer_port.setVisible(is_network)
        self.input_printer_port.setVisible(is_network)

        # USB-only
        self._lbl_printer_usb_vendor.setVisible(is_usb)
        self.input_printer_usb_vendor.setVisible(is_usb)
        self._lbl_printer_usb_product.setVisible(is_usb)
        self.input_printer_usb_product.setVisible(is_usb)

        # Comunes (solo cuando hay impresora activa)
        self._lbl_printer_profile.setVisible(is_active)
        self.input_printer_profile.setVisible(is_active)
        self._lbl_printer_paper_width.setVisible(is_active)
        self.combo_printer_paper_width.setVisible(is_active)

        # Botón de prueba se deshabilita si está en "none"
        self.btn_test_printer.setEnabled(is_active)

    # ----------------------------------------------------------
    # Fix 2.5 (cerrado): Botón "Probar impresión"
    # Llama al endpoint POST /settings/printer-test que envía una
    # página corta ESC/POS usando la config actual GUARDADA en la
    # BD (no los valores en pantalla todavía sin guardar).
    # ----------------------------------------------------------
    def _on_test_printer(self):
        if self._dirty:
            reply = QMessageBox.question(
                self, "Cambios sin guardar",
                "La prueba usa la configuración guardada en la base de datos, "
                "no los valores actuales en pantalla.\n\n"
                "¿Querés guardar primero y luego probar?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Cancel:
                return
            if reply == QMessageBox.Yes:
                # Guardar y dejar al usuario disparar la prueba después.
                # No encadenamos automáticamente para no esconder errores
                # de guardado bajo "prueba falló".
                self._on_save()
                show_toast(
                    "Guardando… pulsá 'Probar impresión' de nuevo cuando termine.",
                    success=True, parent=self.main_window,
                )
                return

        self.btn_test_printer.setEnabled(False)
        self.btn_test_printer.setText("Enviando…")

        def _do_test():
            from ui.services.settings_service import test_printer
            import requests as _req
            try:
                return test_printer()
            except _req.HTTPError as e:
                try:
                    detail = e.response.json().get("detail", str(e))
                except Exception:
                    detail = str(e)
                raise RuntimeError(detail) from None

        def _on_ok(result):
            data = (result or {}).get("data") or {}
            msg = (result or {}).get("message", "OK")
            printed = data.get("printed", False)
            if printed:
                show_toast(f"✅ {msg}", success=True, parent=self.main_window)
            else:
                # printed=False cubre el caso "printer_type=none"; no es
                # un error, solo informativo.
                show_toast(f"ℹ️ {msg}", success=True, parent=self.main_window)

        def _on_err(msg):
            QMessageBox.warning(
                self, "Error de impresión",
                f"No se pudo imprimir la página de prueba:\n\n{msg}\n\n"
                "Verifique IP/puerto (network) o Vendor/Product ID (USB) "
                "y que la impresora esté encendida y accesible."
            )

        def _on_done():
            self.btn_test_printer.setEnabled(
                self.combo_printer_type.currentText().lower() != "none"
            )
            self.btn_test_printer.setText("🧾 Probar impresión")

        from ui.utils.http_worker import run_async
        run_async(
            _do_test,
            on_success=_on_ok,
            on_error=_on_err,
            on_finished=_on_done,
            owner=self,
        )

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

        # --- Tab Impresora (4.3 + Fix 2.5 cerrado) ---
        pt = data.get("printer_type", "network") or "network"
        idx_pt = self.combo_printer_type.findText(pt)
        if idx_pt >= 0:
            self.combo_printer_type.setCurrentIndex(idx_pt)
        self.input_printer_ip.setText(data.get("printer_ip", "192.168.0.120") or "192.168.0.120")
        self.input_printer_port.setValue(data.get("printer_port", 9100) or 9100)

        # Fix 2.5 (cerrado): campos USB + perfil + ancho papel.
        # Si la BD viene sin estos campos (instalación previa a la
        # migración g7b8c9d0e1f2), get(...) devuelve None y los
        # widgets quedan vacíos — que es lo correcto.
        self.input_printer_usb_vendor.setText(data.get("printer_usb_vendor_id") or "")
        self.input_printer_usb_product.setText(data.get("printer_usb_product_id") or "")
        self.input_printer_profile.setText(data.get("printer_profile") or "")

        paper_width = data.get("printer_paper_width_mm") or 80
        idx_pw = self.combo_printer_paper_width.findData(int(paper_width))
        if idx_pw >= 0:
            self.combo_printer_paper_width.setCurrentIndex(idx_pw)

        # Sincronizar visibilidad de campos según el tipo cargado.
        # Esto NO marca dirty porque ya conectamos la señal de visibilidad
        # con currentTextChanged y el setCurrentIndex de arriba dispara
        # ese mismo callback como efecto colateral. Llamamos explícito
        # acá por si el índice no cambió (ya estaba en "network").
        self._sync_printer_fields_visibility()

        # --- Tab Facturación (4.1): Issuer Profile ---
        self._populate_issuer(issuer)

        # --- Env status (4.4/4.5) ---
        self._populate_env_status(env_status)
        # --- Hacienda config (carga desde secure_config) ---
        self._load_hacienda_config()
        # --- Email config (carga desde secure_config) ---
        self._load_email_config()

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
            # Fase 4.3 + Fix 2.5 (cerrado)
            "printer_type": self.combo_printer_type.currentText(),
            "printer_ip": self.input_printer_ip.text(),
            "printer_port": self.input_printer_port.value(),
            "printer_usb_vendor_id": self.input_printer_usb_vendor.text(),
            "printer_usb_product_id": self.input_printer_usb_product.text(),
            "printer_profile": self.input_printer_profile.text(),
            "printer_paper_width_mm": self.combo_printer_paper_width.currentData(),
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
        # Este mapa es solo un fallback inicial mientras el backend responde.
        # El método `_on_ai_config_loaded` lo sobrescribe con los modelos
        # reales que devuelve el backend (provider.supported_models).
        # FASE 1.2 — Fix 1.2: modelos vigentes de Anthropic (mayo 2026).
        self._ai_provider_models = {
            "none": [],
            "anthropic": [
                "claude-sonnet-4-6",
                "claude-opus-4-7",
                "claude-haiku-4-5-20251001",
                "claude-sonnet-4-5-20250929",
                "claude-opus-4-1-20250805",
            ],
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
    # CONFIG-UI: Hacienda config
    # ==========================================================

    def _load_hacienda_config(self):
        """Carga la config de Hacienda desde el backend."""
        self._cleanup_thread()
        self._worker = _LoadHaciendaConfigWorker()
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_hacienda_config_loaded)
        self._worker.failed.connect(self._on_hacienda_config_load_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_hacienda_config_loaded(self, data: dict):
        """Rellena los campos de Hacienda con datos del backend."""
        env = data.get("hacienda_env", "sandbox") or "sandbox"
        idx = self.combo_hacienda_env.findText(env)
        if idx >= 0:
            self.combo_hacienda_env.setCurrentIndex(idx)

        self.input_hacienda_api.setText(data.get("hacienda_api", "") or "")

        # Usuario: mostrar hint si hay, sino vacío
        if data.get("has_hacienda_user"):
            hint = data.get("hacienda_user_hint", "")
            self.input_hacienda_user.setPlaceholderText(f"Guardado: {hint} (dejá vacío para mantener)")
        else:
            self.input_hacienda_user.setPlaceholderText("Usuario OAuth2 de Hacienda")

        # Password: indicar si existe
        if data.get("has_hacienda_password"):
            self.input_hacienda_password.setPlaceholderText("••••• (dejá vacío para mantener)")
        else:
            self.input_hacienda_password.setPlaceholderText("Contraseña OAuth2")

        # Certificado
        cert_name = data.get("hacienda_cert_filename", "")
        has_cert = data.get("has_cert", False)
        cert_exists = data.get("cert_file_exists", False)

        if has_cert and cert_exists:
            self.label_cert_status.setText(f"✅ {cert_name}")
            self.label_cert_status.setStyleSheet("font-size: 12px; color: #10b981;")
        elif has_cert and not cert_exists:
            self.label_cert_status.setText(f"⚠️ {cert_name} (archivo no encontrado)")
            self.label_cert_status.setStyleSheet("font-size: 12px; color: #f59e0b;")
        else:
            self.label_cert_status.setText("Sin certificado")
            self.label_cert_status.setStyleSheet("font-size: 12px; color: #888;")

        # Status general
        parts = []
        if data.get("hacienda_api"):
            parts.append("✅ API configurada")
        else:
            parts.append("⚠️ API no configurada")
        if data.get("has_hacienda_user") and data.get("has_hacienda_password"):
            parts.append("✅ Credenciales configuradas")
        else:
            parts.append("⚠️ Credenciales pendientes")
        if has_cert and cert_exists:
            parts.append("✅ Certificado OK")
        else:
            parts.append("⚠️ Certificado pendiente")

        all_ok = (data.get("hacienda_api") and data.get("has_hacienda_user")
                  and data.get("has_hacienda_password") and has_cert and cert_exists)
        color = "#10b981" if all_ok else "#f59e0b"
        self.label_hacienda_status.setText("  |  ".join(parts))
        self.label_hacienda_status.setStyleSheet(f"font-size: 12px; color: {color};")

    def _on_hacienda_config_load_failed(self, error: str):
        logger.debug(f"No se pudo cargar config Hacienda: {error}")
        self.label_hacienda_status.setText("⚠️ No se pudo cargar la configuración de Hacienda")
        self.label_hacienda_status.setStyleSheet("font-size: 12px; color: #f59e0b;")

    def _on_save_hacienda(self):
        """Guarda las credenciales de Hacienda."""
        payload = {}

        # Siempre enviar ambiente y API
        payload["hacienda_env"] = self.combo_hacienda_env.currentText()
        api_text = self.input_hacienda_api.text().strip()
        if api_text:
            payload["hacienda_api"] = api_text

        # Solo enviar usuario/password si el campo tiene texto
        user_text = self.input_hacienda_user.text().strip()
        if user_text:
            payload["hacienda_user"] = user_text

        pass_text = self.input_hacienda_password.text().strip()
        if pass_text:
            payload["hacienda_password"] = pass_text

        self.btn_save_hacienda.setEnabled(False)
        self.btn_save_hacienda.setText("Guardando...")

        self._cleanup_thread()
        self._worker = _SaveHaciendaConfigWorker(payload)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_hacienda_save_success)
        self._worker.failed.connect(self._on_hacienda_save_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_hacienda_save_success(self, result: dict):
        self.btn_save_hacienda.setEnabled(True)
        self.btn_save_hacienda.setText("💾 Guardar Hacienda")
        self.input_hacienda_user.clear()
        self.input_hacienda_password.clear()
        show_toast("✅ Configuración de Hacienda guardada", success=True, parent=self.main_window)
        self._load_hacienda_config()

    def _on_hacienda_save_failed(self, error: str):
        self.btn_save_hacienda.setEnabled(True)
        self.btn_save_hacienda.setText("💾 Guardar Hacienda")
        show_toast(f"Error guardando Hacienda: {error}", success=False, parent=self.main_window)

    def _on_upload_cert(self):
        """Abre diálogo para subir certificado .p12."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar certificado .p12",
            "", "Certificados (*.p12)"
        )
        if not filepath:
            return

        # Pedir contraseña del certificado
        from PySide6.QtWidgets import QInputDialog
        password, ok = QInputDialog.getText(
            self, "Contraseña del certificado",
            "Ingresá la contraseña del archivo .p12:",
            QLineEdit.Password,
        )
        if not ok:
            return

        self.btn_upload_cert.setEnabled(False)
        self.btn_upload_cert.setText("Subiendo...")

        self._cleanup_thread()
        self._worker = _UploadCertWorker(filepath, password)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_cert_upload_success)
        self._worker.failed.connect(self._on_cert_upload_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_cert_upload_success(self, result: dict):
        self.btn_upload_cert.setEnabled(True)
        self.btn_upload_cert.setText("📁 Subir .p12")
        show_toast("✅ Certificado subido correctamente", success=True, parent=self.main_window)
        self._load_hacienda_config()

    def _on_cert_upload_failed(self, error: str):
        self.btn_upload_cert.setEnabled(True)
        self.btn_upload_cert.setText("📁 Subir .p12")
        show_toast(f"Error subiendo certificado: {error}", success=False, parent=self.main_window)
        
    # ==========================================================
    # CONFIG-UI: Email config
    # ==========================================================

    def _load_email_config(self):
        self._cleanup_thread()
        self._worker = _LoadEmailConfigWorker()
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_email_config_loaded)
        self._worker.failed.connect(self._on_email_config_load_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_email_config_loaded(self, data: dict):
        if data.get("has_email_user"):
            hint = data.get("email_user_hint", "")
            self.input_email_user.setPlaceholderText(f"Guardado: {hint} (dejá vacío para mantener)")
            self.label_email_status.setText(f"✅ Email configurado — {hint}")
            self.label_email_status.setStyleSheet("font-size: 12px; color: #10b981;")
        else:
            self.input_email_user.setPlaceholderText("correo@gmail.com")
            self.label_email_status.setText("⚠️ Email no configurado")
            self.label_email_status.setStyleSheet("font-size: 12px; color: #f59e0b;")

        if data.get("has_email_pass"):
            self.input_email_pass.setPlaceholderText("••••• (dejá vacío para mantener)")
        else:
            self.input_email_pass.setPlaceholderText("Contraseña o App Password")

    def _on_email_config_load_failed(self, error: str):
        logger.debug(f"No se pudo cargar config email: {error}")
        self.label_email_status.setText("⚠️ No se pudo cargar la configuración de email")
        self.label_email_status.setStyleSheet("font-size: 12px; color: #f59e0b;")

    def _on_save_email(self):
        payload = {}

        user_text = self.input_email_user.text().strip()
        if user_text:
            payload["email_user"] = user_text

        pass_text = self.input_email_pass.text().strip()
        if pass_text:
            payload["email_pass"] = pass_text

        if not payload:
            show_toast("No hay cambios que guardar", success=False, parent=self.main_window)
            return

        self.btn_save_email.setEnabled(False)
        self.btn_save_email.setText("Guardando...")

        self._cleanup_thread()
        self._worker = _SaveEmailConfigWorker(payload)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_email_save_success)
        self._worker.failed.connect(self._on_email_save_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_email_save_success(self, result: dict):
        self.btn_save_email.setEnabled(True)
        self.btn_save_email.setText("💾 Guardar Email")
        self.input_email_user.clear()
        self.input_email_pass.clear()
        show_toast("✅ Configuración de email guardada", success=True, parent=self.main_window)
        self._load_email_config()

    def _on_email_save_failed(self, error: str):
        self.btn_save_email.setEnabled(True)
        self.btn_save_email.setText("💾 Guardar Email")
        show_toast(f"Error guardando email: {error}", success=False, parent=self.main_window)

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

    # ----------------------------------------------------------
    # Tab: Usuarios (Fase 3)
    # ----------------------------------------------------------
    def _build_tab_usuarios(self) -> QWidget:
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Barra superior
        top_bar = QHBoxLayout()
        lbl = QLabel("Gestión de usuarios y cajeros")
        lbl.setStyleSheet("font-size: 15px; font-weight: bold;")
        top_bar.addWidget(lbl)
        top_bar.addStretch()

        self.btn_add_user = QPushButton("➕ Agregar usuario")
        self.btn_add_user.setMinimumHeight(34)
        self.btn_add_user.setStyleSheet("""
            QPushButton {
                background-color: #22c55e; color: white;
                font-weight: bold; padding: 6px 18px;
                border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #16a34a; }
        """)
        self.btn_add_user.clicked.connect(self._on_add_user)
        top_bar.addWidget(self.btn_add_user)

        self.btn_refresh_users = QPushButton("🔄 Actualizar")
        self.btn_refresh_users.setMinimumHeight(34)
        self.btn_refresh_users.setStyleSheet("""
            QPushButton {
                background-color: #374151; color: white;
                padding: 6px 14px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #4b5563; }
        """)
        self.btn_refresh_users.clicked.connect(self._load_users)
        top_bar.addWidget(self.btn_refresh_users)

        layout.addLayout(top_bar)

        # Tabla de usuarios
        self.users_table = QTableWidget()
        self.users_table.setColumnCount(6)
        self.users_table.setHorizontalHeaderLabels([
            "ID", "Usuario", "Nombre", "Rol", "Estado", "Acciones"
        ])
        self.users_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.users_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.users_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.users_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.users_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.users_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.users_table.setAlternatingRowColors(True)
        self.users_table.setStyleSheet("""
            QTableWidget {
                background-color: #1f2937;
                color: #e5e7eb;
                gridline-color: #374151;
                border: 1px solid #374151;
                border-radius: 8px;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QTableWidget::item:selected {
                background-color: #3a86ff;
            }
            QHeaderView::section {
                background-color: #111827;
                color: #a5b4fc;
                font-weight: bold;
                padding: 8px;
                border: none;
                border-bottom: 2px solid #3a86ff;
            }
            QTableWidget::item:alternate {
                background-color: #1a2332;
            }
        """)

        layout.addWidget(self.users_table, 1)

        return tab

    # ----------------------------------------------------------
    # Usuarios: cargar datos
    # ----------------------------------------------------------
    def _load_users(self):
        """Carga la lista de usuarios y permisos disponibles (async)."""
        self.btn_refresh_users.setEnabled(False)

        def _fetch():
            from ui.services.users_service import fetch_users, fetch_available_permissions
            users = fetch_users()
            try:
                perms = fetch_available_permissions()
            except Exception:
                perms = {}
            return {"users": users, "perms": perms}

        from ui.utils.http_worker import run_async
        run_async(
            _fetch,
            on_success=self._on_users_loaded,
            on_error=self._on_users_load_error,
            on_finished=lambda: self.btn_refresh_users.setEnabled(True),
            owner=self,
        )

    def _on_users_loaded(self, data):
        """Callback: actualiza tabla y cache de permisos."""
        self._users_cache = data["users"]
        self._populate_users_table(self._users_cache)
        perms = data.get("perms", {})
        if perms:
            self._all_permissions = perms.get("all_permissions", [])
            self._default_permissions = perms.get("default_permissions", {})

    def _on_users_load_error(self, msg):
        """Callback: error al cargar usuarios."""
        logger.error(f"Error cargando usuarios: {msg}")
        show_toast(f"Error al cargar usuarios: {msg}", success=False, parent=self.main_window)

    def _populate_users_table(self, users: list[dict]):
        """Llena la tabla con los datos de usuarios."""
        from PySide6.QtWidgets import QTableWidgetItem

        self.users_table.setRowCount(0)
        self.users_table.setRowCount(len(users))

        for row, user in enumerate(users):
            # ID
            id_item = QTableWidgetItem(str(user.get("id", "")))
            id_item.setTextAlignment(Qt.AlignCenter)
            self.users_table.setItem(row, 0, id_item)

            # Usuario
            self.users_table.setItem(row, 1, QTableWidgetItem(user.get("username", "")))

            # Nombre
            self.users_table.setItem(row, 2, QTableWidgetItem(user.get("full_name", "") or ""))

            # Rol
            role = user.get("role", "")
            role_item = QTableWidgetItem(role.capitalize())
            role_item.setTextAlignment(Qt.AlignCenter)
            self.users_table.setItem(row, 3, role_item)

            # Estado
            is_active = user.get("is_active", True)
            status_item = QTableWidgetItem("✅ Activo" if is_active else "⛔ Inactivo")
            status_item.setTextAlignment(Qt.AlignCenter)
            self.users_table.setItem(row, 4, status_item)

            # Botones de acciones
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(4, 2, 4, 2)
            actions_layout.setSpacing(4)

            btn_edit = QPushButton("✏️")
            btn_edit.setFixedSize(32, 28)
            btn_edit.setToolTip("Editar usuario")
            btn_edit.setStyleSheet("""
                QPushButton {
                    background-color: #3a86ff; color: white;
                    border-radius: 4px; border: none; font-size: 14px;
                }
                QPushButton:hover { background-color: #2b6fe0; }
            """)
            user_id = user.get("id")
            btn_edit.clicked.connect(lambda checked, uid=user_id: self._on_edit_user(uid))
            actions_layout.addWidget(btn_edit)

            btn_delete = QPushButton("🗑️")
            btn_delete.setFixedSize(32, 28)
            btn_delete.setToolTip("Eliminar usuario")
            btn_delete.setStyleSheet("""
                QPushButton {
                    background-color: #ef4444; color: white;
                    border-radius: 4px; border: none; font-size: 14px;
                }
                QPushButton:hover { background-color: #dc2626; }
            """)
            btn_delete.clicked.connect(lambda checked, uid=user_id: self._on_delete_user(uid))
            actions_layout.addWidget(btn_delete)

            self.users_table.setCellWidget(row, 5, actions_widget)

    # ----------------------------------------------------------
    # Usuarios: agregar
    # ----------------------------------------------------------
    def _on_add_user(self):
        self._ensure_permissions_then(self._show_add_user_dialog)

    def _show_add_user_dialog(self):
        """Abre el diálogo de creación de usuario (main thread)."""
        from ui.dialogs.user_dialog import UserDialog
        dlg = UserDialog(
            user_data=None,
            all_permissions=self._all_permissions,
            default_permissions=self._default_permissions,
            parent=self,
        )

        if dlg.exec() == QDialog.Accepted and dlg.result_data:
            perms = dlg.result_data.pop("permissions", [])
            create_data = {
                "username": dlg.result_data["username"],
                "password": dlg.result_data["password"],
                "full_name": dlg.result_data.get("full_name"),
                "role": dlg.result_data["role"],
            }

            self._set_users_buttons_enabled(False)
            from ui.utils.http_worker import run_async
            run_async(
                self._do_create_user, create_data, perms,
                on_success=self._on_user_created,
                on_error=lambda msg: QMessageBox.critical(self, "Error al crear usuario", msg),
                on_finished=lambda: self._set_users_buttons_enabled(True),
                owner=self,
            )

    def _do_create_user(self, create_data, perms):
        """Ejecuta creación de usuario en hilo de background."""
        from ui.services.users_service import create_user, fetch_users, update_permissions
        import requests as _req
        try:
            create_user(create_data)
        except _req.HTTPError as e:
            raise RuntimeError(self._extract_api_error(e)) from None

        if perms and create_data["role"] != "admin":
            try:
                users = fetch_users()
                new_user = next(
                    (u for u in users if u["username"] == create_data["username"]),
                    None,
                )
                if new_user:
                    update_permissions(new_user["id"], perms)
            except _req.HTTPError as e:
                raise RuntimeError(self._extract_api_error(e)) from None
        return create_data["username"]

    def _on_user_created(self, username):
        """Callback: usuario creado exitosamente."""
        show_toast(f"Usuario '{username}' creado ✔", success=True, parent=self.main_window)
        self._load_users()

    # ----------------------------------------------------------
    # Usuarios: editar
    # ----------------------------------------------------------
    def _on_edit_user(self, user_id: int):
        # Buscar datos del usuario en cache
        user_data = next((u for u in self._users_cache if u["id"] == user_id), None)
        if not user_data:
            QMessageBox.warning(self, "Error", "No se encontró el usuario.")
            return

        self._ensure_permissions_then(self._show_edit_user_dialog, user_id, user_data)

    def _show_edit_user_dialog(self, user_id, user_data):
        """Abre el diálogo de edición de usuario (main thread)."""
        from ui.dialogs.user_dialog import UserDialog
        dlg = UserDialog(
            user_data=user_data,
            all_permissions=self._all_permissions,
            default_permissions=self._default_permissions,
            parent=self,
        )

        if dlg.exec() == QDialog.Accepted and dlg.result_data:
            perms = dlg.result_data.pop("permissions", [])

            # Solo enviar campos que cambiaron
            update_payload = {}
            if dlg.result_data.get("username") != user_data.get("username"):
                update_payload["username"] = dlg.result_data["username"]
            if dlg.result_data.get("full_name") != user_data.get("full_name"):
                update_payload["full_name"] = dlg.result_data["full_name"]
            if dlg.result_data.get("role") != user_data.get("role"):
                update_payload["role"] = dlg.result_data["role"]
            if "is_active" in dlg.result_data:
                if dlg.result_data["is_active"] != user_data.get("is_active"):
                    update_payload["is_active"] = dlg.result_data["is_active"]
            if dlg.result_data.get("password"):
                update_payload["password"] = dlg.result_data["password"]

            role = dlg.result_data.get("role", user_data.get("role", ""))

            self._set_users_buttons_enabled(False)
            from ui.utils.http_worker import run_async
            run_async(
                self._do_edit_user, user_id, user_data, update_payload, perms, role,
                on_success=lambda _: self._on_user_updated(),
                on_error=lambda msg: QMessageBox.critical(self, "Error al actualizar", msg),
                on_finished=lambda: self._set_users_buttons_enabled(True),
                owner=self,
            )

    def _do_edit_user(self, user_id, user_data, update_payload, perms, role):
        """Ejecuta actualización de usuario en hilo de background."""
        from ui.services.users_service import update_user, update_permissions
        import requests as _req

        if update_payload:
            try:
                update_user(user_id, update_payload)
            except _req.HTTPError as e:
                raise RuntimeError(self._extract_api_error(e)) from None

        # ── Re-login automático si el admin editó su propia cuenta ──
        from ui.session_manager import session as _session
        _is_self_edit = user_data.get("username") == _session.username
        _new_password = update_payload.get("password")
        _new_username = update_payload.get("username", user_data.get("username"))

        if _is_self_edit and _new_password:
            try:
                from ui.api import BASE_URL as _BASE_URL
                from app.core.security import decode_token as _decode_token
                _resp = _req.post(
                    f"{_BASE_URL}/users/login",
                    data={"username": _new_username, "password": _new_password},
                    timeout=10,
                )
                _resp.raise_for_status()
                _data = _resp.json()
                _new_token = _data.get("access_token")
                # FASE 2 — Fix 2.4: capturar refresh_token también para que la
                # sesión recargada pueda renovar tokens vencidos automáticamente.
                _new_refresh = _data.get("refresh_token")
                _payload = _decode_token(_new_token)
                _role = _payload.get("role", _session.role)
                _session.start_session(_new_username, _role, _new_token, refresh_token=_new_refresh)
            except Exception as _re_err:
                logger.warning(f"Re-login automático falló: {_re_err}")

        # Actualizar permisos (si no es admin)
        if role != "admin":
            try:
                update_permissions(user_id, perms)
            except _req.HTTPError as e:
                raise RuntimeError(self._extract_api_error(e)) from None

        return True

    def _on_user_updated(self):
        """Callback: usuario actualizado exitosamente."""
        show_toast("Usuario actualizado ✔", success=True, parent=self.main_window)
        self._load_users()

    # ----------------------------------------------------------
    # Usuarios: eliminar
    # ----------------------------------------------------------
    def _on_delete_user(self, user_id: int):
        user_data = next((u for u in self._users_cache if u["id"] == user_id), None)
        username = user_data.get("username", "?") if user_data else "?"

        reply = QMessageBox.question(
            self,
            "Confirmar eliminación",
            f"¿Está seguro que desea eliminar al usuario '{username}'?\n\n"
            "Esta acción no se puede deshacer.",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        self._set_users_buttons_enabled(False)

        def _do_delete():
            from ui.services.users_service import delete_user
            import requests as _req
            try:
                delete_user(user_id)
            except _req.HTTPError as e:
                raise RuntimeError(self._extract_api_error(e)) from None
            return username

        from ui.utils.http_worker import run_async
        run_async(
            _do_delete,
            on_success=self._on_user_deleted,
            on_error=lambda msg: QMessageBox.critical(self, "Error al eliminar", msg),
            on_finished=lambda: self._set_users_buttons_enabled(True),
            owner=self,
        )

    def _on_user_deleted(self, username):
        """Callback: usuario eliminado exitosamente."""
        show_toast(f"Usuario '{username}' eliminado ✔", success=True, parent=self.main_window)
        self._load_users()

    # ----------------------------------------------------------
    # Usuarios: utilidades async
    # ----------------------------------------------------------
    def _ensure_permissions_then(self, callback, *args):
        """
        Garantiza que los permisos estén cargados antes de ejecutar callback.
        Si ya están en cache, llama callback inmediatamente.
        Si no, los carga async y llama callback al terminar.
        """
        if self._all_permissions:
            callback(*args)
            return

        def _on_loaded(data):
            self._all_permissions = data.get("all_permissions", [])
            self._default_permissions = data.get("default_permissions", {})
            callback(*args)

        from ui.utils.http_worker import run_async
        from ui.services.users_service import fetch_available_permissions
        run_async(
            fetch_available_permissions,
            on_success=_on_loaded,
            on_error=lambda msg: QMessageBox.critical(
                self, "Error", f"No se pudieron cargar los permisos:\n{msg}"
            ),
        )

    def _set_users_buttons_enabled(self, enabled: bool):
        """Habilita/deshabilita botones de la pestaña usuarios durante operaciones."""
        self.btn_add_user.setEnabled(enabled)
        self.btn_refresh_users.setEnabled(enabled)

    @staticmethod
    def _extract_api_error(exc):
        """Extrae el detail de un HTTPError de requests (respuesta FastAPI)."""
        try:
            return exc.response.json().get("detail", str(exc))
        except Exception:
            return str(exc)

    def _cleanup_thread(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)
        self._thread = None
        self._worker = None