from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QScrollArea, QGridLayout, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox,
    QSpinBox, QMenu
)
from PySide6.QtCore import Qt, QSize, QTimer, QEvent
from PySide6.QtGui import QDoubleValidator, QPixmap
from PySide6.QtWidgets import QApplication

from ui.utils.http_worker import api_call, api_request, run_async
import copy
import time

from ui.session_manager import session
from ui.components.toast_notifier import show_toast
import re
from ui.dialogs.confirm_sale_dialog import ConfirmSaleDialog
from ui.dialogs.edit_cart_item_dialog import EditCartItemDialog
from ui.dialogs.day_sales_dialog import DaySalesDialog
from ui.dialogs.common_product_dialog import CommonProductDialog
from ui.dialogs.quantity_input_dialog import QuantityInputDialog
from PySide6.QtWidgets import QDialog
from PySide6.QtWidgets import QCompleter
from PySide6.QtCore import QStringListModel

from app.utils.unit_helpers import is_unit_based, format_quantity, UNIT_LABELS



from ui.api import BASE_URL

API_BASE_URL = BASE_URL
PRODUCTS_URL = f"{API_BASE_URL}/products/"
CATEGORIES_URL = f"{API_BASE_URL}/categories/"
CUSTOMERS_URL = f"{API_BASE_URL}/customers/"
SALES_URL = f"{API_BASE_URL}/sales/"
FAVORITES_URL = f"{API_BASE_URL}/products/favorites/quick"



class SalesView(QWidget):
    """
    Vista de ventas moderna:
    - Izquierda: tarjetas de productos con colores según stock.
    - Arriba: buscador + filtro de categorías + cliente + método de pago.
    - Derecha: tabla de carrito + totales + pago del cliente.
    """

    def __init__(self):
        super().__init__()

        self.products = []          
        self.cart = {}
        self.paused_sales = []
        self.active_paused_sale_id = None
        self._paused_sale_seq = 0
        self.categories = set()
        self._category_name_to_id: dict[str, int] = {}   # ✅ nombre → id para filtrar en backend
        self.customers = []
        self.general_customer_id = None
        self._current_subtotal = 0.0
        self._current_discount = 0.0
        self._current_iva = 0.0
        self._current_total = 0.0
        self.selected_customer_id = None
        self.cash_session_open = False
        self._perma_focus_installed = False
        self.quick_sale_mode = False
        self.quick_sale_print_ticket = False
        self._sale_in_progress = False          # ← guardia anti doble-submit

        # FASE 2 — Fix 2.2: Flag para evitar doble-conexión de señales
        self._signals_connected = False

        # ✅ PRODUCTO COMÚN: IDs virtuales negativos para no colisionar con IDs reales
        self._common_seq = 0

        # Paginación / lazy loading
        self.page_size = 40
        self.current_offset = 0
        self.has_more_products = True
        self.is_loading_products = False
        self.current_search_term = ""
        self.current_category = "Todas las categorías"
        self.product_cards_by_id = {}
        self.favorite_products = []
        self.favorite_buttons = []

        self._build_ui()
        # Activar captura de teclado para atajos POS
        self.setFocusPolicy(Qt.StrongFocus)
        self.check_cash_session()
        self.load_customers()
        self.load_categories()  # PASO 12: categorías desde endpoint propio
        self.load_favorite_products()

        # Timer con debounce para la búsqueda por texto
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)

        # FASE 2 — Fix 2.2: Conectar señales una sola vez
        self._connect_signals()

        self.load_products_page(reset=True)
        self.toggle_amount_input()
        

    # ------------------------------------------------------------------
    # FASE 2 — Fix 2.2: Gestión de señales Qt
    # ------------------------------------------------------------------
    def _connect_signals(self):
        """Conecta las señales de búsqueda/categoría una sola vez."""
        if self._signals_connected:
            return
        self._signals_connected = True

        self.search_timer.timeout.connect(lambda: self.load_products_page(reset=True))
        self.search_input.textChanged.connect(self.on_search_text_changed)
        self.category_combo.currentIndexChanged.connect(self.on_category_changed)
        self.search_input.returnPressed.connect(self.handle_barcode_scan)

    def _disconnect_signals(self):
        """Desconecta señales para evitar acumulación si la vista se recrea."""
        if not self._signals_connected:
            return
        self._signals_connected = False

        try:
            self.search_timer.timeout.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            self.search_input.textChanged.disconnect(self.on_search_text_changed)
        except (RuntimeError, TypeError):
            pass
        try:
            self.category_combo.currentIndexChanged.disconnect(self.on_category_changed)
        except (RuntimeError, TypeError):
            pass
        try:
            self.search_input.returnPressed.disconnect(self.handle_barcode_scan)
        except (RuntimeError, TypeError):
            pass

    def closeEvent(self, event):
        """Limpia señales al destruir la vista."""
        # ──────────────────────────────────────────────────────────────
        # FIX CRÍTICO: remover event filter global instalado en
        # _apply_focus_policy.
        #
        # _apply_focus_policy() llama a app.installEventFilter(self) para
        # mantener el foco en la caja de búsqueda mientras la caja está
        # abierta. Si NO removemos este event filter al cerrar la vista,
        # Qt sigue invocando self.eventFilter() en este widget después
        # de que C++ lo destruyó (cuando MainWindow.deleteLater() limpia
        # toda la jerarquía tras logout), produciendo un Windows fatal
        # exception: access violation en el siguiente evento que Qt
        # procese (paint, mouse, key).
        # ──────────────────────────────────────────────────────────────
        self._cleanup_global_event_filter()
        self._disconnect_signals()
        super().closeEvent(event)

    def _cleanup_global_event_filter(self):
        """
        Remueve el event filter global de QApplication si está instalado.
        Idempotente y defensivo: nunca debe lanzar excepciones (se llama
        durante destrucción).
        """
        try:
            if getattr(self, "_perma_focus_installed", False):
                app = QApplication.instance()
                if app is not None:
                    app.removeEventFilter(self)
                self._perma_focus_installed = False
        except Exception:
            # Durante destrucción, cualquier error se traga silenciosamente.
            pass
        


    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        # --- Root: fondo base del widget completo ---
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- Scroll externo: seguridad para pantallas pequeñas ---
        outer_scroll = QScrollArea()
        outer_scroll.setWidgetResizable(True)
        outer_scroll.setFrameShape(QFrame.NoFrame)
        outer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        outer_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #080d1a;
            }
            QScrollBar:vertical {
                background: #0b1120;
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #1e293b;
                border-radius: 3px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #334155;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        # --- Contenedor visual unificado (hijo del scroll) ---
        content_frame = QFrame()
        content_frame.setObjectName("contentFrame")
        content_frame.setStyleSheet("""
            QFrame#contentFrame {
                background-color: transparent;
                border: 1px solid #1e293b;
                border-radius: 14px;
                margin: 6px;
            }
        """)

        main_layout = QHBoxLayout(content_frame)
        main_layout.setContentsMargins(4, 6, 4, 6)
        main_layout.setSpacing(2)

        outer_scroll.setWidget(content_frame)
        root_layout.addWidget(outer_scroll)

        # ------------------ IZQUIERDA: BUSCADOR + TARJETAS ------------------
        left_container = QVBoxLayout()
        left_container.setContentsMargins(0, 0, 0, 0)
        left_container.setSpacing(2)                   
        left_container.setAlignment(Qt.AlignTop)        

        # Fila de controles superiores
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)  # 
        controls_layout.setSpacing(4)                   

        # Buscador
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar producto o usar cantidad rápida: 5*cemento")
        self.search_input.setFixedHeight(32)

        # Botón buscar
        search_btn = QPushButton("🔍")
        search_btn.setFixedSize(36, 32)
        search_btn.clicked.connect(lambda: self.load_products_page(reset=True))

        # Filtro de categorías
        self.category_combo = QComboBox()
        self.category_combo.setFixedHeight(32)
        self.category_combo.addItem("Todas las categorías")

        # Botón recargar
        reload_btn = QPushButton("↻")
        reload_btn.setFixedSize(36, 32)
        reload_btn.clicked.connect(lambda: self.load_products_page(reset=True))

        controls_layout.addWidget(self.search_input, 3)
        controls_layout.addWidget(search_btn)
        controls_layout.addWidget(self.category_combo, 2)
        controls_layout.addWidget(reload_btn)

        left_container.addLayout(controls_layout)

        # ------------------ PRODUCTOS RÁPIDOS ------------------
        favorites_block = QVBoxLayout()
        favorites_block.setContentsMargins(0, 2, 0, 2)
        favorites_block.setSpacing(2)

        favorites_title = QLabel("⭐ Productos rápidos")
        favorites_title.setFixedHeight(18)
        favorites_title.setStyleSheet("""
            QLabel {
                font-size: 12px;
                font-weight: 700;
                color: #f8fafc;
                padding: 0;
                margin: 0;
            }
        """)
        favorites_block.addWidget(favorites_title)

        self.favorites_scroll = QScrollArea()
        self.favorites_scroll.setWidgetResizable(True)
        self.favorites_scroll.setFixedHeight(36)
        self.favorites_scroll.setFrameShape(QFrame.NoFrame)
        self.favorites_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.favorites_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.favorites_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:horizontal {
                height: 4px;
                background: #111827;
                border-radius: 2px;
            }
            QScrollBar::handle:horizontal {
                background: #374151;
                border-radius: 2px;
            }
        """)

        self.favorites_container = QWidget()
        self.favorites_layout = QHBoxLayout(self.favorites_container)
        self.favorites_layout.setContentsMargins(0, 0, 0, 0)
        self.favorites_layout.setSpacing(6)
        self.favorites_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.favorites_scroll.setWidget(self.favorites_container)
        favorites_block.addWidget(self.favorites_scroll)

        left_container.addLayout(favorites_block)

        # Área de tarjetas (scroll)
        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setFrameShape(QFrame.NoFrame)

        # QUITA TODOS LOS ESPACIOS INTERNOS
        self.cards_scroll.setViewportMargins(0, 0, 0, 0)
        self.cards_scroll.viewport().setContentsMargins(0, 0, 0, 0)
        self.cards_scroll.setStyleSheet("""
            QScrollArea { border: none; margin: 0; padding: 0; }
            QScrollArea > QWidget { margin: 0; padding: 0; }
        """)

        # Contenedor de tarjetas
        self.cards_container = QWidget()
        self.cards_layout = QGridLayout(self.cards_container)

        #  EL LAYOUT MÁS COMPACTO POSIBLE
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setHorizontalSpacing(2)
        self.cards_layout.setVerticalSpacing(2)
        self.cards_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self.cards_scroll.setWidget(self.cards_container)
        left_container.addWidget(self.cards_scroll)

        # Lazy loading: cargar más al llegar al fondo
        self.cards_scroll.verticalScrollBar().valueChanged.connect(self.on_products_scroll)

        # ------------------ DERECHA: CARRITO + TOTALES ------------------
        right_container = QVBoxLayout()
        right_container.setContentsMargins(2, 4, 2, 4)
        right_container.setSpacing(6)

        # --- Fila cliente + método de pago ---
        top_right_layout = QHBoxLayout()
        top_right_layout.setSpacing(8)
        
        self.btn_close_cash = QPushButton("🔒 Cerrar caja")
        self.btn_close_cash.clicked.connect(self.open_close_cash_dialog)

        self.btn_close_cash.setStyleSheet(
            "QPushButton { background-color: #7c2d12; color: white; padding: 8px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #9a3412; }"
        )

        self.btn_day_sales = QPushButton("🧾")
        self.btn_day_sales.setFixedSize(40, 34)
        self.btn_day_sales.setToolTip("Ventas del día")
        self.btn_day_sales.clicked.connect(self.open_day_sales_dialog)


        client_label = QLabel("Cliente:")

        self.customer_search = QLineEdit()
        self.customer_search.setPlaceholderText("Cliente (opcional)")
        self.customer_search.setClearButtonEnabled(True)
        self.customer_search.setFixedHeight(32)

        # Autocomplete (se configura cuando cargan los clientes)
        self.customer_completer = QCompleter(self)
        self.customer_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.customer_completer.setFilterMode(Qt.MatchContains)  # permite buscar por “contains”
        self.customer_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.customer_search.setCompleter(self.customer_completer)

        # Cuando el usuario elige una sugerencia
        self.customer_completer.activated.connect(self.on_customer_selected_from_text)
        
        # Cuando el usuario termina de editar manualmente (presiona Enter o sale del campo)
        self.customer_search.editingFinished.connect(self.on_customer_text_changed)


        

        doc_label = QLabel("Doc:")
        self.doc_type_combo = QComboBox()
        self.doc_type_combo.setFixedHeight(32)
        self.doc_type_combo.addItem("Tiquete electrónico", "04")
        self.doc_type_combo.addItem("Factura electrónica", "01")

        payment_label = QLabel("Pago:")
        self.payment_combo = QComboBox()
        self.payment_combo.setFixedHeight(32)
        self.payment_combo.addItems([
            "Efectivo", "Tarjeta", "SINPE", "Transferencia", "Crédito"
        ])
        self.payment_combo.currentIndexChanged.connect(self.toggle_amount_input)
        self.payment_combo.currentTextChanged.connect(self.on_payment_method_changed)

        # Input de días de crédito (visible solo cuando se selecciona Crédito)
        self.credit_days_label = QLabel("Plazo (días):")
        self.credit_days_input = QSpinBox()
        self.credit_days_input.setRange(1, 365)
        self.credit_days_input.setValue(30)
        self.credit_days_input.setFixedHeight(32)
        self.credit_days_input.setVisible(False)
        self.credit_days_label.setVisible(False)
        
        # --- Recuadro de información del cliente con scroll ---
        # Crear el scroll area que contendrá la información
        self.customer_info_scroll = QScrollArea()
        self.customer_info_scroll.setWidgetResizable(True)
        self.customer_info_scroll.setFrameShape(QFrame.NoFrame)
        self.customer_info_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.customer_info_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.customer_info_scroll.setMaximumHeight(100)
        self.customer_info_scroll.setVisible(False)
        self.customer_info_scroll.setStyleSheet("""
            QScrollArea {
                background-color: #2a2a2a;
                border: 1px solid #3b82f6;
                border-radius: 6px;
                margin-top: 4px;
            }
            QScrollBar:vertical {
                background: #1e1e1e;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #3b82f6;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # Frame interno que contendrá los labels
        self.customer_info_box = QFrame()
        self.customer_info_box.setStyleSheet("""
            QFrame {
                background-color: transparent;
                border: none;
                padding: 8px;
            }
            QLabel {
                color: #e5e7eb;
                font-size: 11px;
                padding: 2px 0px;
            }
        """)

        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(4, 4, 4, 4)
        info_layout.setSpacing(4)
        info_layout.setAlignment(Qt.AlignTop)

        self.lbl_info_name = QLabel("Nombre: -")
        self.lbl_info_name.setStyleSheet("font-weight: bold; font-size: 12px; color: #60a5fa;")
        self.lbl_info_name.setWordWrap(True)
        
        self.lbl_info_id = QLabel("Identificación: -")
        self.lbl_info_id.setWordWrap(True)
        
        self.lbl_info_email = QLabel("Correo: -")
        self.lbl_info_email.setWordWrap(True)
        
        self.lbl_info_address = QLabel("Dirección: -")
        self.lbl_info_address.setWordWrap(True)

        info_layout.addWidget(self.lbl_info_name)
        info_layout.addWidget(self.lbl_info_id)
        info_layout.addWidget(self.lbl_info_email)
        info_layout.addWidget(self.lbl_info_address)

        self.customer_info_box.setLayout(info_layout)
        
        # Agregar el frame al scroll area
        self.customer_info_scroll.setWidget(self.customer_info_box)


        top_right_layout.addWidget(client_label)
        top_right_layout.addWidget(self.customer_search, 2)
        top_right_layout.addSpacing(12)
        top_right_layout.addWidget(doc_label)
        top_right_layout.addWidget(self.doc_type_combo, 1)
        top_right_layout.addSpacing(12)
        top_right_layout.addWidget(payment_label)
        top_right_layout.addWidget(self.payment_combo, 1)
        top_right_layout.addWidget(self.credit_days_label)
        top_right_layout.addWidget(self.credit_days_input)

        right_container.addLayout(top_right_layout)
        right_container.addWidget(self.customer_info_scroll)


        # --- Tabla carrito ---
        self.cart_table = QTableWidget(0, 5)
        self.cart_table.setHorizontalHeaderLabels(
            ["Producto", "Cant", "Precio", "Subtotal", "Acciones"]
        )
        self.cart_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cart_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.cart_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.cart_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.cart_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.cart_table.setColumnWidth(1, 55)    # Cant
        self.cart_table.setColumnWidth(2, 85)    # Precio
        self.cart_table.setColumnWidth(3, 95)    # Subtotal
        self.cart_table.setColumnWidth(4, 150)   # Acciones
        self.cart_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cart_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cart_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.cart_table.setAlternatingRowColors(True)
        self.cart_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e2e;
                alternate-background-color: #262636;
                color: #e5e7eb;
                gridline-color: #333;
                font-size: 13px;
            }
            QHeaderView::section {
                background-color: #333;
                padding: 5px;
                border: none;
                color: white;
                font-weight: bold;
                font-size: 12px;
            }
        """)
        self.cart_table.setFixedHeight(260)
        self.cart_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cart_table.customContextMenuRequested.connect(self.open_cart_context_menu)
        self.cart_table.cellDoubleClicked.connect(self.on_cart_cell_double_clicked)
        right_container.addWidget(self.cart_table)

        # ============================
        # CARD DE TOTALES + PAGO
        # ============================
        totals_card = QFrame()
        totals_card.setStyleSheet("""
            QFrame {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 10px;
                padding: 6px;
            }
            QLabel {
                color: #e2e8f0;
                font-size: 13px;
                padding: 0;
                margin: 0;
            }
            QLineEdit {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px;
                color: #f1f5f9;
            }
        """)

        totals_card_layout = QVBoxLayout(totals_card)
        totals_card_layout.setSpacing(2)
        totals_card_layout.setContentsMargins(6, 6, 6, 6)

        # Totales
        self.subtotal_label = QLabel("Subtotal: ₡0.00")
        self.discount_label = QLabel("Descuento: ₡0.00")
        self.tax_label = QLabel("IVA: ₡0.00")
        self.total_label = QLabel("<b>Total: ₡0.00</b>")

        for lbl in (self.subtotal_label, self.discount_label, self.tax_label, self.total_label):
            lbl.setAlignment(Qt.AlignRight)
            totals_card_layout.addWidget(lbl)

        # Separador
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #1e293b;")
        line.setFixedHeight(4)
        totals_card_layout.addWidget(line)

        # Pago del cliente
        pay_label = QLabel("💰 Pago del cliente:")
        totals_card_layout.addWidget(pay_label)

        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("Ingrese monto recibido")
        self.amount_input.setFixedHeight(32)
        self.amount_input.setValidator(QDoubleValidator(0.0, 99999999.0, 2))
        self.amount_input.textChanged.connect(self.update_change)
        totals_card_layout.addWidget(self.amount_input)

        self.change_label = QLabel("Cambio: ₡0.00")
        self.change_label.setAlignment(Qt.AlignRight)
        totals_card_layout.addWidget(self.change_label)

        right_container.addWidget(totals_card)

        # --- Botones ---
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        cash_buttons_layout = QHBoxLayout()
        cash_buttons_layout.setSpacing(10)

        self.btn_cash_in = QPushButton("➕ Entrada")
        self.btn_cash_out = QPushButton("➖ Salida")
        self.pause_btn = QPushButton("⏸ Pausar venta")
        self.btn_common_product = QPushButton("📦 Común")

        self.btn_cash_in.clicked.connect(lambda: self.open_cash_movement("in"))
        self.btn_cash_out.clicked.connect(lambda: self.open_cash_movement("out"))
        self.pause_btn.clicked.connect(self.pause_current_sale)
        self.btn_common_product.clicked.connect(self.open_common_product_dialog)

        cash_buttons_layout.addWidget(self.btn_cash_in, 1)
        cash_buttons_layout.addWidget(self.btn_common_product, 1)
        cash_buttons_layout.addWidget(self.pause_btn, 1)
        cash_buttons_layout.addWidget(self.btn_cash_out, 1)

        right_container.addLayout(cash_buttons_layout)

        # ------------------ PESTAÑAS: VENTAS EN PAUSA ------------------
        self.paused_tabs_scroll = QScrollArea()
        self.paused_tabs_scroll.setWidgetResizable(True)
        self.paused_tabs_scroll.setFixedHeight(42)
        self.paused_tabs_scroll.setFrameShape(QFrame.NoFrame)
        self.paused_tabs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.paused_tabs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.paused_tabs_scroll.setVisible(False)
        self.paused_tabs_scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:horizontal { height: 4px; background: #111827; border-radius: 2px; }
            QScrollBar::handle:horizontal { background: #374151; border-radius: 2px; }
        """)

        self.paused_tabs_container = QWidget()
        self.paused_tabs_layout = QHBoxLayout(self.paused_tabs_container)
        self.paused_tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.paused_tabs_layout.setSpacing(6)
        self.paused_tabs_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.paused_tabs_scroll.setWidget(self.paused_tabs_container)
        right_container.addWidget(self.paused_tabs_scroll)

        self.cancel_btn = QPushButton("F6  Cancelar venta")
        self.cancel_btn.clicked.connect(self.clear_cart)

        self.confirm_btn = QPushButton("F10 ⚡  |  F5 Confirmar venta")
        self.confirm_btn.clicked.connect(self.confirm_sale)

        self.confirm_btn.setStyleSheet(
            "QPushButton { background-color: #22aa55; color: white; padding: 8px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1b8b45; }"
        )
        self.cancel_btn.setStyleSheet(
            "QPushButton { background-color: #aa2244; color: white; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #901b39; }"
        )
        self.btn_cash_in.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; padding: 8px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
        )

        self.pause_btn.setStyleSheet(
            "QPushButton { background-color: #7c3aed; color: white; padding: 8px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #6d28d9; }"
        )

        self.btn_cash_out.setStyleSheet(
            "QPushButton { background-color: #f59e0b; color: black; padding: 8px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #d97706; }"
        )

        self.btn_common_product.setStyleSheet(
            "QPushButton { background-color: #475569; color: white; padding: 8px 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #64748b; }"
        )

        self.btn_day_sales.setStyleSheet(
            "QPushButton { background-color: #1f2937; color: white; font-size: 16px; font-weight: bold; border-radius: 8px; }"
            "QPushButton:hover { background-color: #374151; }"
        )

        for btn in [self.btn_cash_in, self.btn_common_product, self.pause_btn, self.btn_cash_out]:
            btn.setFixedHeight(34)

        middle_tools_layout = QHBoxLayout()
        middle_tools_layout.setSpacing(8)
        middle_tools_layout.addWidget(self.btn_close_cash)
        middle_tools_layout.addWidget(self.btn_day_sales)

        buttons_layout.addWidget(self.cancel_btn)
        buttons_layout.addStretch()
        buttons_layout.addLayout(middle_tools_layout)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.confirm_btn)

        right_container.addLayout(buttons_layout)

        # Agregar ambas columnas al layout principal
        main_layout.addLayout(left_container, 4)
        main_layout.addLayout(right_container, 2)

        self._render_paused_tabs()

        # Estilo general
        self.setStyleSheet("""
            QWidget {
                background-color: #080d1a;
                color: #e4e4e4;
                font-size: 13px;
            }
            QFrame#contentFrame {
                background-color: transparent;
                border: 1px solid #1e293b;
                border-radius: 14px;
            }
            QLineEdit, QComboBox {
                background-color: #101828;
                border: 1px solid #1f2937;
                border-radius: 6px;
                padding: 4px 8px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #6366f1;
            }
            QHeaderView::section {
                background-color: #111827;
                color: #e5e7eb;
                padding: 4px;
                border: 0;
            }
        """)

    # ------------------------------------------------------------------
    # Carga de datos
    # ------------------------------------------------------------------
    def _auth_headers(self):
        headers = {"Content-Type": "application/json"}
        if session.token:
            headers["Authorization"] = f"Bearer {session.token}"
        return headers

    def load_products(self):
        """Compatibilidad: delega a load_products_page con reset."""
        self.load_products_page(reset=True)

    def reset_products_view(self):
        """Limpia el grid, reinicia offset y vacía self.products."""
        self.current_offset = 0
        self.has_more_products = True
        self.products = []

        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def load_products_page(self, reset=False):
        """Carga una página de productos desde la API (lazy loading paginado, async)."""
        if self.is_loading_products:
            return

        if not reset and not self.has_more_products:
            return

        self.is_loading_products = True

        if reset:
            self.reset_products_view()

        params = {
            "skip": self.current_offset,
            "limit": self.page_size,
        }

        search_text = (self.search_input.text() or "").strip()
        selected_category = self.category_combo.currentText()

        if search_text:
            params["search"] = search_text

        # ✅ Filtro de categoría en backend (antes era frontend)
        if selected_category != "Todas las categorías":
            cat_id = self._category_name_to_id.get(selected_category)
            if cat_id is not None:
                params["category_id"] = cat_id

        # Guardar contexto para el callback (evita lambdas en signals cross-thread)
        self._pending_products_reset = reset

        api_call("get",
            PRODUCTS_URL,
            headers=self._auth_headers(),
            params=params,
            timeout=10,
            on_success=self._on_products_loaded,
            on_error=self._on_products_error,
            on_finished=self._on_products_finished,
        )

    def _on_products_loaded(self, json_data):
        """Callback: procesa productos recibidos del servidor."""
        reset = self._pending_products_reset
        new_products = json_data.get("data", [])
        self.products.extend(new_products)
        # ✅ El backend ya aplicó search y category_id — mostramos directo
        self.build_cards_from_products(new_products, append=not reset)

        if len(new_products) < self.page_size:
            self.has_more_products = False
        else:
            self.current_offset += self.page_size

    def _on_products_error(self, msg):
        """Callback: error al cargar productos."""
        show_toast(f"Error cargando productos: {msg}", success=False, parent=self)

    def _on_products_finished(self):
        """Callback: siempre se ejecuta al terminar la carga de productos."""
        self.is_loading_products = False

    def build_cards_from_products(self, products, append=False):
        """
        Construye el grid de tarjetas con centrado visual real
        usando 8 columnas logicas. Cada tarjeta ocupa 2 columnas.
        """
        if not append:
            while self.cards_layout.count():
                item = self.cards_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()

        if not products:
            label = QLabel("No hay productos para mostrar.")
            label.setAlignment(Qt.AlignCenter)
            self.cards_layout.addWidget(label, 0, 0, 1, 8, Qt.AlignCenter)
            return

        logical_cols = 8
        card_span = 2
        max_cards_per_row = 4

        total = len(products)
        row = 0
        index = 0

        while index < total:
            remaining = total - index
            items_in_row = min(max_cards_per_row, remaining)

            used_cols = items_in_row * card_span
            start_col = (logical_cols - used_cols) // 2

            for i in range(items_in_row):
                product = products[index]
                card = self._create_product_card(product)
                self.cards_layout.addWidget(card, row, start_col + (i * card_span), 1, card_span)
                index += 1

            row += 1

    def on_search_text_changed(self):
        """Dispara búsqueda con debounce de 250 ms."""
        self.search_timer.start(250)

    def on_category_changed(self):
        """Recarga productos al cambiar categoría."""
        self.load_products_page(reset=True)

    def on_products_scroll(self, value):
        """Carga más productos al llegar casi al fondo del scroll."""
        scrollbar = self.cards_scroll.verticalScrollBar()
        if value >= scrollbar.maximum() - 80:
            self.load_products_page(reset=False)



    def _reload_category_combo(self):
        current = self.category_combo.currentText()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("Todas las categorías")
        for cat in sorted(self.categories):
            self.category_combo.addItem(cat)
        self.category_combo.blockSignals(False)

        if current and current in [self.category_combo.itemText(i) for i in range(self.category_combo.count())]:
            self.category_combo.setCurrentText(current)

    # PASO 12 — Cargar categorías desde su endpoint propio
    def load_categories(self):
        """Llena el combo de categorías desde /categories/ (async, no bloquea UI)."""
        api_call("get",
            CATEGORIES_URL,
            headers=self._auth_headers(),
            timeout=10,
            on_success=self._on_categories_loaded,
            on_error=self._on_categories_error,
        )

    def _on_categories_error(self, msg):
        show_toast(f"Error cargando categorías: {msg}", success=False, parent=self)

    def _on_categories_loaded(self, json_data):
        """Callback: procesa categorías recibidas del servidor."""
        cats = json_data.get("data", [])

        self.categories = set()
        self._category_name_to_id = {}
        for c in cats:
            name = (c.get("name") or "").strip()
            is_active = c.get("is_active", True)
            if name and name != "-" and is_active:
                self.categories.add(name)
                cat_id = c.get("id")
                if cat_id is not None:
                    self._category_name_to_id[name] = cat_id

        self._reload_category_combo()

    def load_favorite_products(self):
        """Carga productos rápidos basados en los más vendidos (async, no bloquea UI)."""
        api_call("get",
            FAVORITES_URL,
            headers=self._auth_headers(),
            params={"limit": 6, "days": 30},
            timeout=10,
            on_success=self._on_favorites_loaded,
            on_error=self._on_favorites_error,
        )

    def _on_favorites_error(self, msg):
        show_toast(f"Error cargando productos rápidos: {msg}", success=False, parent=self)

    def _on_favorites_loaded(self, json_data):
        """Callback: procesa productos favoritos recibidos del servidor."""
        self.favorite_products = json_data.get("data", [])
        self.render_favorite_products()

    def render_favorite_products(self):
        """Renderiza botones rápidos de productos favoritos."""
        while self.favorites_layout.count():
            item = self.favorites_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self.favorite_buttons = []

        if not self.favorite_products:
            empty_lbl = QLabel("No hay productos rápidos disponibles.")
            empty_lbl.setStyleSheet("color: #9ca3af; padding: 6px 2px;")
            self.favorites_layout.addWidget(empty_lbl)
            self.favorites_layout.addStretch()
            return

        for product in self.favorite_products[:6]:
            name = product.get("name", "Producto")
            price = float(product.get("price") or 0)
            btn = QPushButton(f"{name}  ₡{price:,.0f}")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(32)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #111827;
                    color: #f9fafb;
                    border: 1px solid #374151;
                    border-radius: 10px;
                    padding: 4px 10px;
                    font-weight: 600;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #1f2937;
                    border: 1px solid #6366f1;
                }
                QPushButton:pressed {
                    background-color: #0f172a;
                }
            """)
            btn.clicked.connect(lambda checked=False, p=product: self.add_favorite_product_to_cart(p))
            self.favorites_layout.addWidget(btn)
            self.favorite_buttons.append(btn)

        self.favorites_layout.addStretch()

    def add_favorite_product_to_cart(self, product: dict):
        """Agrega un producto rápido al carrito."""
        if not product:
            return
        self.add_to_cart_from_card(product, quantity=1)

    def load_customers(self):
        """Carga clientes para el combo de cliente (async, no bloquea UI)."""
        # ✅ Preservar selección actual (si venimos del chat / navegación)
        self._pending_customer_prev_id = getattr(self, "selected_customer_id", None)
        self._pending_customer_prev_text = ""
        try:
            self._pending_customer_prev_text = (self.customer_search.text() or "").strip()
        except Exception:
            self._pending_customer_prev_text = ""

        api_call("get", CUSTOMERS_URL,
            headers=self._auth_headers(),
            timeout=10,
            on_success=self._on_customers_loaded,
            on_error=self._on_customers_error,
        )

    def _on_customers_error(self, msg):
        show_toast(f"Error cargando clientes: {msg}", success=False, parent=self)

    def _on_customers_loaded(self, json_data):
        """Callback: procesa clientes recibidos del servidor."""
        prev_id = self._pending_customer_prev_id
        prev_text = self._pending_customer_prev_text
        self.customers = json_data.get("data", [])

        # Buscar Cliente General
        general = next(
            (c for c in self.customers if "general" in (c.get("name", "").lower())),
            None
        )
        self.general_customer_id = general["id"] if general else None

        # Mapa nombre -> id (y también una lista para completer)
        self.customer_name_to_id = {}
        names = []

        for c in self.customers:
            name = c.get("name", "Sin nombre").strip()
            cid = c.get("id")
            if not cid:
                continue
            self.customer_name_to_id[name] = cid
            names.append(name)

        # Configurar completer
        model = QStringListModel(sorted(names))
        self.customer_completer.setModel(model)

        # -----------------------------------------
        # ✅ Restaurar selección (NO limpiar al recargar)
        # -----------------------------------------
        restored_id = None

        # 1) Intentar por ID anterior
        if prev_id is not None:
            try:
                prev_id_int = int(prev_id)
            except Exception:
                prev_id_int = None
            if prev_id_int is not None and any(int(c.get("id") or 0) == prev_id_int for c in self.customers):
                restored_id = prev_id_int

        # 2) Fallback por texto anterior
        if restored_id is None and prev_text:
            prev_text_l = prev_text.lower()
            for cname, cid in self.customer_name_to_id.items():
                if (cname or "").lower() == prev_text_l:
                    restored_id = cid
                    prev_text = cname  # normalizar a nombre exacto
                    break

        # 3) Aplicar restauración
        if restored_id is not None:
            self.selected_customer_id = restored_id
            if hasattr(self, "customer_search"):
                try:
                    # Si no tenemos texto (por ID), resolver nombre por ID
                    if not prev_text:
                        for cname, cid in self.customer_name_to_id.items():
                            if int(cid) == int(restored_id):
                                prev_text = cname
                                break
                    self.customer_search.setText(prev_text)
                except Exception:
                    pass
        else:
            # Si no hay selección válida, mantener vacío
            self.selected_customer_id = None
            if hasattr(self, "customer_search"):
                try:
                    self.customer_search.clear()
                except Exception:
                    pass

        # Actualizar info box
        self.update_customer_info_box()            
            
    def _parse_quick_quantity_input(self, text: str):
        """
        Detecta formato tipo:
        5*cemento
        0.5*clavos
        12*tornillo
        Retorna: (quantity, search_term)
        Si no coincide, retorna (1, text original limpio)
        📏 Ahora soporta cantidades decimales para productos a granel.
        """
        raw = (text or "").strip()
        if not raw:
            return 1, ""

        match = re.fullmatch(r"(\d+\.?\d*)\*(.+)", raw)
        if not match:
            return 1, raw

        try:
            quantity = float(match.group(1))
        except ValueError:
            quantity = 1
        search_term = match.group(2).strip()

        if quantity <= 0:
            quantity = 1

        return quantity, search_term

    def handle_barcode_scan(self):
        """
        Se ejecuta cuando se presiona Enter en el buscador.
        Soporta formato de cantidad rápida:
        5*cemento
        3*7501234567890

        Primero intenta búsqueda exacta en backend por barcode/código (async),
        luego cae en productos cargados en memoria como fallback.
        """
        raw_input = self.search_input.text().strip()
        quantity, barcode = self._parse_quick_quantity_input(raw_input)

        if not barcode:
            return

        # Guardar contexto para los callbacks (evita lambdas en signals cross-thread)
        self._pending_barcode = barcode
        self._pending_barcode_qty = quantity
        self._pending_barcode_category = self.category_combo.currentText()

        # Lanzar búsqueda backend en hilo separado
        run_async(
            self._search_barcode_backend, barcode,
            on_success=self._on_barcode_success,
            on_error=self._on_barcode_error,
        )

    def _on_barcode_success(self, product):
        """Callback: resultado exitoso de búsqueda por barcode."""
        self._on_barcode_result(product, self._pending_barcode,
                                self._pending_barcode_qty,
                                self._pending_barcode_category)

    def _on_barcode_error(self, msg):
        """Callback: error en búsqueda por barcode, intentar fallback local."""
        self._on_barcode_result(None, self._pending_barcode,
                                self._pending_barcode_qty,
                                self._pending_barcode_category)

    def _search_barcode_backend(self, barcode):
        """Búsqueda de producto por barcode/código en el backend (ejecuta en hilo)."""
        import requests as _req

        headers = self._auth_headers()
        timeout = (5, 5)

        # Intentar endpoint /products/barcode/{barcode}
        try:
            resp = _req.get(
                f"{API_BASE_URL}/products/barcode/{barcode}",
                headers=headers, timeout=timeout
            )
            if resp.status_code == 200:
                data = resp.json().get("data")
                if data:
                    return data
        except Exception:
            pass

        # Fallback: búsqueda por código exacto
        try:
            resp = _req.get(
                PRODUCTS_URL,
                headers=headers,
                params={"search": barcode, "limit": 5, "skip": 0},
                timeout=timeout
            )
            if resp.status_code == 200:
                results = resp.json().get("data", [])
                exact = [
                    p for p in results
                    if (p.get("code") or "").lower() == barcode.lower()
                    or (p.get("barcode") or "").lower() == barcode.lower()
                ]
                if len(exact) == 1:
                    return exact[0]
        except Exception:
            pass

        return None

    def _on_barcode_result(self, product_found, barcode, quantity, selected_category):
        """Callback: procesa resultado de búsqueda por barcode (hilo principal)."""
        if product_found:
            self.add_to_cart_from_card(product_found, quantity=quantity)
            self.search_input.clear()
            self.search_input.setFocus()
            return

        # ------------------------------------------------------------------
        # Fallback: buscar en los productos ya cargados en memoria
        # ------------------------------------------------------------------
        search_text = barcode.lower().strip()

        filtered = []
        for p in self.products:
            prod_cat = p.get("category_name")

            if selected_category != "Todas las categorías":
                if prod_cat != selected_category:
                    continue

            name = (p.get("name") or "").lower()
            code = (p.get("code") or "").lower()
            prod_barcode = (p.get("barcode") or "").lower()

            if search_text not in name and search_text not in code and search_text not in prod_barcode:
                continue

            filtered.append(p)

        if len(filtered) == 0:
            show_toast("❌ Producto no encontrado", success=False, parent=self)
            return

        if len(filtered) == 1:
            self.add_to_cart_from_card(filtered[0], quantity=quantity)
            self.search_input.clear()
            self.search_input.setFocus()
        else:
            show_toast(
                f"⚠️ Se encontraron {len(filtered)} productos. Seleccione uno.",
                success=False,
                parent=self
            )

    # ------------------------------------------------------------------
    # Tarjetas de productos
    # ------------------------------------------------------------------
    def filtered_products(self):
        text = (self.search_input.text() or "").lower().strip()
        selected_category = self.category_combo.currentText()

        filtered = []

        for p in self.products:
            # ---- Categoría ----
            prod_cat = p.get("category_name")

            if selected_category != "Todas las categorías":
                if prod_cat != selected_category:
                    continue

            # ---- Búsqueda ----
            if text:
                name = (p.get("name") or "").lower()
                code = (p.get("code") or "").lower()
                barcode = (p.get("barcode") or "").lower()
                
                # Buscar en nombre, código O código de barras
                if text not in name and text not in code and text not in barcode:
                    continue

            filtered.append(p)

        return filtered


    def refresh_product_cards(self):
        """Reconstruye el grid usando los productos ya cargados en self.products."""
        self.build_cards_from_products(self.filtered_products(), append=False)


    def _create_product_image_placeholder(
        self,
        image_path: str | None = None,
        bg_color: str = "#0f172a",
        border_color: str = "#334155",
    ) -> QFrame:
        """
        Devuelve un QFrame de 90px de alto para el bloque visual superior de la card.
        - Si image_path existe y carga correctamente: muestra QPixmap escalado con
          KeepAspectRatio + SmoothTransformation (sin reventar rendimiento).
        - Si no hay imagen o el archivo falla: muestra placeholder 📦.
        """
        THUMB_W = 186   # ancho interno del contenedor (card 190 - 2px borde x2)
        THUMB_H = 86    # alto interno (90 - 2px borde x2)

        container = QFrame()
        container.setFixedHeight(90)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: transparent;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                border-bottom-left-radius: 0px;
                border-bottom-right-radius: 0px;
                border-bottom: 1px solid {border_color};
            }}
        """)

        inner_layout = QVBoxLayout(container)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        inner_layout.setAlignment(Qt.AlignCenter)

        img_lbl = QLabel()
        img_lbl.setAlignment(Qt.AlignCenter)
        img_lbl.setStyleSheet("background: transparent; border: none;")

        loaded = False
        if image_path:
            try:
                import os
                if os.path.isfile(image_path):
                    pixmap = QPixmap(image_path)
                    if not pixmap.isNull():
                        scaled = pixmap.scaled(
                            THUMB_W,
                            THUMB_H,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation,
                        )
                        img_lbl.setPixmap(scaled)
                        loaded = True
            except Exception:
                pass  # cualquier falla → fallback al placeholder

        if not loaded:
            img_lbl.setText("📦")
            img_lbl.setStyleSheet("""
                font-size: 36px;
                background: transparent;
                border: none;
                color: #475569;
            """)

        inner_layout.addWidget(img_lbl)
        return container

    def _create_product_card(self, product):
        """
        Crea una tarjeta clickable para un producto.
        product: dict con keys: id, name, price, stock, min_stock, category...
        """
        pid = product.get("id")
        name = product.get("name", "Sin nombre")
        price = float(product.get("price") or 0)
        stock = float(product.get("stock") or 0)
        min_stock = float(product.get("min_stock") or 0)
        unit_type = product.get("unit_type", "Unid") or "Unid"

        frame = QFrame()
        frame.setFixedSize(190, 255)
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setObjectName("productCard")

        # Color + estado visual según stock
        # ⚠️ Misma lógica que products_view.get_stock_status() para mantener consistencia
        low_margin = max(2, int(min_stock * 0.5))

        # 📏 Formatear stock con unidad de medida
        stock_formatted = format_quantity(stock, unit_type)

        if stock <= 0:
            border = "#b91c1c"
            stock_badge = "🔴 Agotado"
            stock_text = f"Stock: {stock_formatted} ✖"
            stock_color = "#fca5a5"
            image_bg = "#1a0a0a"
        elif stock <= min_stock:
            border = "#f97316"
            stock_badge = "🟠 Crítico"
            stock_text = f"Stock: {stock_formatted} ⚠"
            stock_color = "#fdba74"
            image_bg = "#1a1205"
        elif stock <= (min_stock + low_margin):
            border = "#f59e0b"
            stock_badge = "🟡 Bajo"
            stock_text = f"Stock: {stock_formatted}"
            stock_color = "#fcd34d"
            image_bg = "#1a1200"
        else:
            border = "#15803d"
            stock_badge = "🟢 Disponible"
            stock_text = f"Stock: {stock_formatted}"
            stock_color = "#86efac"
            image_bg = "#0a1a0e"

        frame.setStyleSheet(f"""
        QFrame#productCard {{
            background-color: transparent;
            border-radius: 12px;
            border: 2px solid {border};
        }}
        QFrame#productCard:hover {{
            border-color: #6366f1;
        }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(0)

        # --- Bloque visual superior (imagen o placeholder) ---
        image_path = product.get("image_path") or None
        image_widget = self._create_product_image_placeholder(
            image_path=image_path,
            bg_color=image_bg,
            border_color=border,
        )
        layout.addWidget(image_widget)

        # --- Área de texto central ---
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(8, 6, 8, 4)
        info_layout.setSpacing(4)

        name_lbl = QLabel(name)
        name_lbl.setWordWrap(True)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setFixedHeight(44)
        name_lbl.setStyleSheet("""
            font-weight: 700;
            font-size: 12px;
            color: #e5e7eb;
            background: transparent;
            border: none;
        """)

        # 📏 Precio con unidad de medida
        unit_suffix = "" if is_unit_based(unit_type) else f"/{UNIT_LABELS.get(unit_type, unit_type)}"
        price_lbl = QLabel(f"₡{price:,.2f}{unit_suffix}".replace(",", "."))
        price_lbl.setAlignment(Qt.AlignCenter)
        price_lbl.setStyleSheet("""
            font-size: 14px;
            font-weight: 800;
            color: #a5f3fc;
            background: transparent;
            border: none;
        """)

        stock_lbl = QLabel(stock_text)
        stock_lbl.setAlignment(Qt.AlignCenter)
        stock_lbl.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 600;
            color: {stock_color};
            background: transparent;
            border: none;
        """)

        badge_lbl = QLabel(stock_badge)
        badge_lbl.setAlignment(Qt.AlignCenter)
        badge_lbl.setStyleSheet(f"""
            font-size: 10px;
            font-weight: 700;
            color: #111827;
            background-color: {stock_color};
            border-radius: 8px;
            padding: 2px 8px;
            border: none;
        """)

        info_layout.addWidget(name_lbl)
        info_layout.addWidget(price_lbl)
        info_layout.addWidget(stock_lbl)
        info_layout.addWidget(badge_lbl)

        layout.addLayout(info_layout)
        layout.addStretch()

        # Hacer clic en toda la tarjeta
        def mousePressEvent(event):
            if event.button() == Qt.LeftButton:
                # 📏 Productos a granel: abrir diálogo de cantidad
                _unit = product.get("unit_type", "Unid") or "Unid"
                if not is_unit_based(_unit):
                    _stock = float(product.get("stock") or 0)
                    if _stock <= 0:
                        show_toast("❌ Sin stock disponible", success=False, parent=self)
                        return
                    dlg = QuantityInputDialog(
                        product_name=product.get("name", ""),
                        unit_type=_unit,
                        max_stock=_stock,
                        parent=self,
                    )
                    if dlg.exec() == QDialog.Accepted:
                        self.add_to_cart_from_card(product, quantity=dlg.get_quantity())
                else:
                    self.add_to_cart_from_card(product)

        frame.mousePressEvent = mousePressEvent

        return frame

    # ------------------------------------------------------------------
    # Carrito
    # ------------------------------------------------------------------
    def add_to_cart_from_card(self, product: dict, quantity=1):
        """Agrega el producto al carrito al hacer clic en la tarjeta o por escaneo."""
        pid = product.get("id")
        if pid is None:
            return

        unit_type = product.get("unit_type", "Unid") or "Unid"
        stock = float(product.get("stock") or 0)
        if stock <= 0:
            show_toast("❌ Sin stock disponible para este producto", success=False, parent=self)
            return

        # 📏 Normalizar cantidad según tipo de unidad
        if is_unit_based(unit_type):
            quantity = max(1, int(quantity or 1))
        else:
            quantity = float(quantity or 1)
            if quantity <= 0:
                quantity = 1.0

        unit_price = float(product.get("price") or 0)

        current_qty = float(self.cart.get(pid, {}).get("quantity") or 0)
        new_total_qty = current_qty + quantity

        if new_total_qty > stock:
            available = stock - current_qty
            if available <= 0:
                show_toast("⚠️ No hay más stock disponible", success=False, parent=self)
                return

            unit_label = UNIT_LABELS.get(unit_type, "unidades")
            show_toast(
                f"⚠️ Solo puedes agregar {available:.3g} {unit_label} más de este producto",
                success=False,
                parent=self
            )
            return

        if pid not in self.cart:
            self.cart[pid] = {
                "product": product,
                "quantity": quantity,
                "unit_price": unit_price,
                "discount_percent": 0.0,
            }
        else:
            self.cart[pid]["quantity"] = current_qty + quantity

        self.refresh_cart_table()

        # 📏 Mensaje con unidad
        unit_label = UNIT_LABELS.get(unit_type, "unidades")
        if is_unit_based(unit_type) and quantity == 1:
            msg = "➕ Producto agregado al carrito"
        else:
            qty_display = format_quantity(quantity, unit_type)
            msg = f"➕ {qty_display} agregado al carrito"

        show_toast(msg, success=True, parent=self)
        self._focus_product_search()

    # ------------------------------------------------------------------
    # ✅ PRODUCTO COMÚN: diálogo y carrito
    # ------------------------------------------------------------------
    def open_common_product_dialog(self):
        """Abre el diálogo para agregar un producto común sin inventario."""
        dialog = CommonProductDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            self.add_common_to_cart(
                description=data["description"],
                quantity=data["quantity"],
                price=data["price"],
            )

    def add_common_to_cart(self, description: str, quantity: int, price: float):
        """Agrega un producto común al carrito con ID virtual negativo."""
        self._common_seq -= 1
        pid = self._common_seq  # IDs negativos: -1, -2, -3...

        self.cart[pid] = {
            "product": {},                     # vacío — no hay producto real
            "quantity": max(1, int(quantity)),
            "unit_price": price,
            "discount_percent": 0.0,
            "is_common": True,
            "common_description": description.strip(),
        }

        self.refresh_cart_table()
        show_toast(f"📦 Producto común agregado: {description}", success=True, parent=self)
        self._focus_product_search()

    def refresh_cart_table(self):
        self.cart_table.setRowCount(0)

        for row_idx, (pid, item) in enumerate(self.cart.items()):
            product = item["product"]
            is_common = item.get("is_common", False)
            name = item.get("common_description", "") if is_common else product.get("name", "")
            if is_common:
                name = f"📦 {name}"
            quantity = item["quantity"]
            unit_price = float(item["unit_price"])

            self.cart_table.insertRow(row_idx)

            # Producto
            percent = float(item.get("discount_percent") or 0)    # ✅ FASE 2.4: float
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.UserRole, pid)
            name_item.setToolTip(
                f"Cantidad: {quantity}\n"
                f"Precio: ₡{unit_price:,.2f}\n"
                f"Descuento: {percent:.2f}%"
            )
            self.cart_table.setItem(row_idx, 0, name_item)

            # Cantidad (texto plano, sin QSpinBox)
            # 📏 Mostrar con unidad para productos a granel
            unit_type = product.get("unit_type", "Unid") or "Unid"
            qty_display = format_quantity(quantity, unit_type)
            qty_item = QTableWidgetItem(qty_display)
            qty_item.setTextAlignment(Qt.AlignCenter)
            self.cart_table.setItem(row_idx, 1, qty_item)

            # Precio
            price_item = QTableWidgetItem(f"{unit_price:.2f}")
            price_item.setTextAlignment(Qt.AlignCenter)
            self.cart_table.setItem(row_idx, 2, price_item)

            # Subtotal con descuento
            original = unit_price * quantity
            discount_amount = original * (percent / 100.0)
            subtotal = original - discount_amount
            subtotal_item = QTableWidgetItem(f"{subtotal:.2f}")
            subtotal_item.setData(Qt.UserRole, percent)
            subtotal_item.setTextAlignment(Qt.AlignCenter)
            if percent > 0:
                from PySide6.QtGui import QColor, QBrush
                subtotal_item.setForeground(QBrush(QColor("#fbbf24")))
            self.cart_table.setItem(row_idx, 3, subtotal_item)

            #
            # ACCIONES (− + % 🗑)
            #
            btn_minus = QPushButton("−")
            btn_minus.setFixedSize(QSize(28, 26))
            btn_minus.clicked.connect(lambda checked=False, pid=pid: self.decrease_quantity(pid))

            btn_plus = QPushButton("+")
            btn_plus.setFixedSize(QSize(28, 26))
            btn_plus.clicked.connect(lambda checked=False, pid=pid: self.increase_quantity(pid))

            btn_discount = QPushButton("%")
            btn_discount.setFixedSize(QSize(28, 26))

            def _row_for_button(btn: QPushButton) -> int:
                p = btn.mapTo(self.cart_table.viewport(), btn.rect().center())
                return self.cart_table.indexAt(p).row()

            btn_discount.clicked.connect(
                lambda checked=False, btn=btn_discount: self.apply_discount(_row_for_button(btn))
            )

            btn_remove = QPushButton("🗑")
            btn_remove.setFixedSize(QSize(30, 26))
            btn_remove.clicked.connect(lambda checked=False, pid=pid: self.remove_from_cart(pid))

            for btn in (btn_minus, btn_plus, btn_discount, btn_remove):
                btn.setCursor(Qt.PointingHandCursor)

            shared_btn_style = """
                QPushButton {
                    background-color: transparent;
                    color: #94a3b8;
                    border: 1px solid #1e293b;
                    border-radius: 6px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    color: #f1f5f9;
                    border-color: #475569;
                }
            """
            btn_minus.setStyleSheet(shared_btn_style)
            btn_plus.setStyleSheet(shared_btn_style)
            btn_discount.setStyleSheet(shared_btn_style)
            btn_remove.setStyleSheet(shared_btn_style)

            action_layout = QHBoxLayout()
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(4)
            action_layout.addWidget(btn_minus)
            action_layout.addWidget(btn_plus)
            action_layout.addWidget(btn_discount)
            action_layout.addWidget(btn_remove)

            action_widget = QWidget()
            action_widget.setLayout(action_layout)

            self.cart_table.setCellWidget(row_idx, 4, action_widget)

        self.update_totals()


    def update_quantity(self, product_id: int, value: int):
        if product_id in self.cart:
            self.cart[product_id]["quantity"] = max(1, int(value))
            self.refresh_cart_table()

    def increase_quantity(self, product_id: int):
        if product_id not in self.cart:
            return

        item = self.cart[product_id]
        current_qty = float(item.get("quantity") or 0)

        # 📏 Incremento según tipo de unidad
        product = item.get("product", {})
        unit_type = product.get("unit_type", "Unid") or "Unid"
        increment = 1 if is_unit_based(unit_type) else 0.5

        # Producto común → sin límite de stock
        if not item.get("is_common", False):
            stock = float(product.get("stock") or 0)
            if current_qty >= stock:
                show_toast("⚠️ No hay más stock disponible", success=False, parent=self)
                return
            # No exceder stock
            if current_qty + increment > stock:
                increment = stock - current_qty
                if increment <= 0:
                    show_toast("⚠️ No hay más stock disponible", success=False, parent=self)
                    return

        self.cart[product_id]["quantity"] = current_qty + increment
        self.refresh_cart_table()
        self._focus_product_search()

    def decrease_quantity(self, product_id: int):
        if product_id not in self.cart:
            return

        item = self.cart[product_id]
        current_qty = float(item.get("quantity") or 0)

        # 📏 Decremento según tipo de unidad
        product = item.get("product", {})
        unit_type = product.get("unit_type", "Unid") or "Unid"
        decrement = 1 if is_unit_based(unit_type) else 0.5

        min_qty = 1 if is_unit_based(unit_type) else 0.001

        if current_qty - decrement < min_qty:
            self.remove_from_cart(product_id)
            return

        self.cart[product_id]["quantity"] = current_qty - decrement
        self.refresh_cart_table()
        self._focus_product_search()

    def remove_from_cart(self, product_id: int):
        if product_id in self.cart:
            del self.cart[product_id]
            self.refresh_cart_table()
            self._focus_product_search()

    def clear_cart(self):
        self.cart.clear()
        self.refresh_cart_table()
        self.amount_input.clear()
        
        # 🔁 Resetear método de pago a Efectivo
        self.payment_combo.setCurrentText("Efectivo")
        self.amount_input.clear()
        self.change_label.setText("Cambio: ₡0.00")

        # Resetear cliente a vacío
        self.customer_search.clear()
        self.selected_customer_id = None
        
        # Actualizar el recuadro de info del cliente (lo ocultará)
        self.update_customer_info_box()

        # ── Resetear estado de totales explícitamente ──
        self._current_subtotal = 0.0
        self._current_discount = 0.0
        self._current_iva = 0.0
        self._current_total = 0.0

        # ── Resetear tipo de documento y días de crédito ──
        try:
            if hasattr(self, "doc_type_combo") and self.doc_type_combo.count() > 0:
                self.doc_type_combo.setCurrentIndex(0)
        except Exception:
            pass
        try:
            if hasattr(self, "credit_days_input"):
                self.credit_days_input.setValue(0)
        except Exception:
            pass

        show_toast("🧹 Carrito limpiado", success=True, parent=self)
        self._focus_product_search()

    # ------------------------------------------------------------------
    # Totales y cambio
    # ------------------------------------------------------------------
    def update_totals(self):
        """
        ✅ FASE 1.1: Calcula totales usando la tasa real de impuesto de cada producto,
        en lugar de asumir 13% fijo para todo.
        """
        total_base = 0.0        # suma de bases (sin IVA, sin descuento aplicado aún al gross)
        total_discount = 0.0    # suma de descuentos
        total_iva = 0.0         # suma de impuestos reales
        total_con_iva = 0.0     # gran total

        for pid, item in self.cart.items():
            price = float(item["unit_price"])           # precio CON IVA incluido
            qty = float(item["quantity"])                # 📏 float para soportar fracciones
            percent = float(item.get("discount_percent") or 0)

            # ─── Obtener tasa de impuesto real del producto ───
            product = item.get("product") or {}
            raw_rate = 0.0
            try:
                raw_rate = float(product.get("tax_rate") or 0)
            except (ValueError, TypeError):
                raw_rate = 0.0

            # Normalizar: si viene como 0.13 convertir a 13
            if 0 < raw_rate < 1:
                raw_rate = raw_rate * 100.0

            rate_frac = raw_rate / 100.0                # ej: 0.13
            tax_factor = 1.0 + rate_frac                # ej: 1.13

            # Precio unitario SIN IVA
            unit_net = price / tax_factor if rate_frac > 0 else price

            # Bruto de la línea (sin IVA, antes de descuento)
            gross = unit_net * qty

            # Descuento sobre base
            discount_amount = gross * (percent / 100.0)

            # Subtotal = base imponible
            subtotal_base = gross - discount_amount

            # Impuesto real de esta línea
            line_tax = subtotal_base * rate_frac if rate_frac > 0 else 0.0

            # Total de la línea (base + impuesto)
            line_total = subtotal_base + line_tax

            total_base += subtotal_base
            total_discount += discount_amount
            total_iva += line_tax
            total_con_iva += line_total

        # 🔥 FUENTE ÚNICA DE VERDAD
        self._current_subtotal = total_base
        self._current_discount = total_discount
        self._current_iva = total_iva
        self._current_total = total_con_iva

        # UI
        self.subtotal_label.setText(f"Subtotal: ₡{total_base:,.2f}")
        self.discount_label.setText(f"Descuento: ₡{total_discount:,.2f}")
        self.tax_label.setText(f"IVA: ₡{total_iva:,.2f}")
        self.total_label.setText(f"<b>Total: ₡{total_con_iva:,.2f}</b>")

        self.update_change()




    def update_change(self):
        text = self.amount_input.text().strip().replace(",", ".")
        total = getattr(self, "_current_total", 0.0)

        try:
            # 🔥 Si está vacío o en 0 → pago exacto
            received = float(text) if text else total
        except ValueError:
            received = total

        change = max(0.0, received - total)
        self.change_label.setText(f"Cambio: ₡{change:,.2f}")


    # ------------------------------------------------------------------
    # Confirmar venta
    # ------------------------------------------------------------------
    from PySide6.QtWidgets import QMessageBox, QDialog
    from PySide6.QtCore import Qt


    def on_quick_sale_toggled(self, checked: bool):
        self.quick_sale_mode = bool(checked)

        if checked:
            self.confirm_btn.setText("F10 ⚡  |  F5 Vender ahora")
            self.confirm_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f59e0b;
                    color: black;
                    padding: 8px 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #d97706;
                }
            """)
            show_toast(
                "⚡ Modo rápido activado: F5 venderá sin confirmación",
                success=True,
                parent=self
            )
        else:
            self.confirm_btn.setText("F10 ⚡  |  F5 Confirmar venta")
            self.confirm_btn.setStyleSheet(
                "QPushButton { background-color: #22aa55; color: white; padding: 8px 16px; font-weight: bold; }"
                "QPushButton:hover { background-color: #1b8b45; }"
            )
            show_toast(
                "🛑 Modo rápido desactivado: volverá la confirmación",
                success=True,
                parent=self
            )

    def _show_post_sale_stock_alerts(self, cart_snapshot: dict | None = None):
        """
        Muestra alertas rápidas de stock después de registrar una venta.
        Usa el snapshot del carrito capturado ANTES de limpiar.
        Ignora productos que ya estaban en 0 o sin stock válido.
        """
        source = cart_snapshot if cart_snapshot is not None else self.cart
        alerts = []

        for pid, item in source.items():
            # Producto común → no tiene stock
            if item.get("is_common", False):
                continue
            product = item.get("product", {}) or {}
            name = product.get("name", "Producto")
            try:
                stock_before = float(product.get("stock") or 0)
                sold_qty = float(item.get("quantity") or 0)
            except (ValueError, TypeError):
                continue

            if stock_before <= 0:
                continue

            remaining_stock = stock_before - sold_qty

            if remaining_stock == 0:
                alerts.append(f"⚠️ {name} quedó en stock 0")
            elif 0 < remaining_stock <= 2:
                alerts.append(f"⚠️ Quedan solo {remaining_stock} unidad(es) de {name}")

        # Escalonar cada alerta con delay para que no se sobrepongan entre sí
        # ni con el toast de "Venta registrada" que se mostró justo antes
        for i, msg in enumerate(alerts[:3]):
            delay_ms = 1200 + (i * 1400)  # 1.2s, 2.6s, 4.0s
            QTimer.singleShot(delay_ms, lambda m=msg: show_toast(m, success=False, parent=self, duration=3000))

    def _submit_sale(self, payload: dict, print_ticket: bool = False):
        # ── FASE 2: Async + protección doble-submit ──
        self._sale_in_progress = True
        self.confirm_btn.setEnabled(False)

        # ── Capturar snapshot del carrito ANTES del async ──
        # Así las alertas de stock funcionan incluso si el carrito ya se limpió.
        import copy
        cart_snapshot = copy.deepcopy(self.cart)

        def on_success(json_data):
            # ═══════════════════════════════════════════════════════
            # PASO 1 — Limpiar carrito PRIMERO (acción crítica).
            #           Si algo falla después, al menos no queda
            #           un carrito "zombie" que bloquea el flujo.
            # ═══════════════════════════════════════════════════════
            try:
                self.clear_cart()
            except Exception as exc:
                import logging
                logging.error(f"Error limpiando carrito post-venta: {exc}")
                # Fallback: limpiar manualmente lo esencial
                try:
                    self.cart.clear()
                    self.cart_table.setRowCount(0)
                except Exception:
                    pass

            # ═══════════════════════════════════════════════════════
            # PASO 2 — Todo lo demás es "nice to have": toasts,
            #           alertas de stock, ticket, recarga de productos.
            #           Nada de esto debe impedir una nueva venta.
            # ═══════════════════════════════════════════════════════
            try:
                show_toast("✅ Venta registrada correctamente", success=True, parent=self)
            except Exception:
                pass

            try:
                self._show_post_sale_stock_alerts(cart_snapshot)
            except Exception as exc:
                import logging
                logging.error(f"Error mostrando alertas de stock: {exc}")

            try:
                if print_ticket:
                    self.print_ticket(json_data, payload)
            except Exception as exc:
                import logging
                logging.error(f"Error imprimiendo ticket: {exc}")

            try:
                self.load_products_page(reset=True)
                self.load_favorite_products()
            except Exception as exc:
                import logging
                logging.error(f"Error recargando productos: {exc}")

            QTimer.singleShot(0, self._focus_product_search)

        def on_error(msg):
            QMessageBox.warning(
                self,
                "Error",
                f"No se pudo registrar la venta.\n{msg}"
            )

        def on_finished():
            # ═══════════════════════════════════════════════════════
            # SIEMPRE se ejecuta (éxito o error).  Restaurar estado.
            # ═══════════════════════════════════════════════════════
            self._sale_in_progress = False
            self.confirm_btn.setEnabled(True)

        api_call("post", SALES_URL,
            json=payload,
            headers=self._auth_headers(),
            timeout=15,
            on_success=on_success,
            on_error=on_error,
            on_finished=on_finished,
        )

    def confirm_sale(self):
        # ── Guardia: evitar doble-submit (F5, chat, botón) ──
        if self._sale_in_progress:
            show_toast("⏳ Ya hay una venta en proceso…", success=False, parent=self)
            return

        if not self.cart:
            show_toast("No hay productos en el carrito.", success=False, parent=self)
            return
        
        # 🔄 Asegurar que los totales estén actualizados
        self.update_totals()

        
        # -----------------------------
        # Cliente seleccionado
        # -----------------------------
        customer_id = self.selected_customer_id  # puede ser None

        # -----------------------------
        # 2. Validación de Crédito
        # -----------------------------
        payment_method = self.payment_combo.currentText()

        if payment_method == "Crédito" and customer_id is None:
            QMessageBox.warning(self, "Cliente requerido",
                                "Para ventas a crédito debes seleccionar un cliente.")
            return

        # -----------------------------
        # Totales calculados (FUENTE ÚNICA)
        # -----------------------------
        subtotal = getattr(self, "_current_subtotal", 0.0)
        discount = getattr(self, "_current_discount", 0.0)
        iva = getattr(self, "_current_iva", 0.0)
        total_value = getattr(self, "_current_total", 0.0)

        if total_value <= 0:
            QMessageBox.warning(
                self,
                "Error",
                "El total calculado es inválido. Intente nuevamente."
            )
            return

        # -----------------------------
        # 3️⃣ VALIDACIÓN DE CRÉDITO (UI BLOCK)
        # -----------------------------
        if payment_method == "Crédito":

            allowed, message = self.can_sell_on_credit(
                customer_id=customer_id,
                sale_total=total_value
            )

            # 🚫 Crédito totalmente bloqueado
            if not allowed:
                QMessageBox.critical(
                    self,
                    "Crédito bloqueado",
                    message
                )
                return  # ⛔ STOP TOTAL

            # ⚠️ Advertencia (cerca del límite)
            if message:
                confirm = QMessageBox.warning(
                    self,
                    "Advertencia de crédito",
                    message + "\n\n¿Deseas continuar?",
                    QMessageBox.Yes | QMessageBox.No
                )

                if confirm != QMessageBox.Yes:
                    return


        # -----------------------------
        # Construir detalles (BACKEND)
        # ✅ FASE 2.4: leer descuento desde self.cart (fuente de verdad), no desde la tabla UI
        # ✅ PRODUCTO COMÚN: incluir is_common y common_description
        # -----------------------------
        details = []
        for pid, item in self.cart.items():
            percent = float(item.get("discount_percent") or 0)
            is_common = item.get("is_common", False)

            detail_entry = {
                "quantity": float(item["quantity"]),    # 📏 float para soportar fracciones
                "unit_price": float(item["unit_price"]),
                "discount_percent": percent,
                "is_common": is_common,
            }

            if is_common:
                detail_entry["product_id"] = None
                detail_entry["common_description"] = item.get("common_description", "Producto común")
            else:
                detail_entry["product_id"] = pid

            details.append(detail_entry)
        
        # 🛡️ VALIDACIÓN FINAL: Asegurar que total_value no sea 0
        # Recalcular el total manualmente como respaldo
        if total_value <= 0:
            import logging
            logging.warning("confirm_sale: total_value era 0, recalculando...")
            manual_total = 0.0
            for pid, item in self.cart.items():
                price = float(item["unit_price"])
                qty = float(item["quantity"])            # 📏 float para soportar fracciones
                percent = float(item.get("discount_percent") or 0)
                original = price * qty
                discount_amount = original * (percent / 100)
                manual_total += (original - discount_amount)
            
            total_value = manual_total
            logging.info(f"confirm_sale: total recalculado = {total_value}")
            
            if total_value <= 0:
                QMessageBox.critical(
                    self,
                    "Error",
                    "No se pudo calcular el total de la venta. Por favor, intente nuevamente."
                )
                return

        payload = {
            "customer_id": int(customer_id) if customer_id is not None else None,
            "payment_method": payment_method,
            "document_type": self.doc_type_combo.currentData(),
            "details": details,
            "total": total_value,
            "credit_days": self.credit_days_input.value() if payment_method.lower() in ("credito", "crédito") else None,
        }

        # =========================================================
        # 🧾 ARMAR INFO PARA DIÁLOGO DE CONFIRMACIÓN (UI)
        # ✅ Calcula subtotal desde self.cart (fuente de verdad),
        #    NO desde self.cart_table (puede estar desincronizada).
        # =========================================================
        items = []

        for pid, item in self.cart.items():
            product = item["product"]
            is_common = item.get("is_common", False)
            display_name = f"📦 {item.get('common_description', '')}" if is_common else product.get("name", "")
            qty = float(item["quantity"])
            price = float(item["unit_price"])
            disc = float(item.get("discount_percent") or 0)
            line_subtotal = price * qty * (1 - disc / 100.0)
            items.append({
                "name": display_name,
                "qty": qty,
                "unit_price": price,
                "discount_percent": disc,
                "subtotal": round(line_subtotal, 2),
            })

        received = None
        change = None
        if payment_method == "Efectivo":
            txt = self.amount_input.text().strip().replace(",", ".")
            try:
                received = float(txt) if txt else total_value
            except ValueError:
                received = total_value

            change = max(0.0, received - total_value)


        totals = {
            "subtotal": subtotal,
            "discount": discount,
            "iva": iva,
            "total": total_value,
            "received": received,
            "change": change,
        }

        # Preferir el cliente seleccionado por ID (más robusto si el text input se refresca)
        customer_name = ""
        try:
            if customer_id is not None:
                for cname, cid in (getattr(self, "customer_name_to_id", {}) or {}).items():
                    try:
                        if int(cid) == int(customer_id):
                            customer_name = (cname or "").strip()
                            break
                    except Exception:
                        continue
        except Exception:
            pass

        if not customer_name:
            customer_name = (self.customer_search.text() or "").strip() or "Cliente"


        # =========================================================
        # 🪟 ABRIR DIÁLOGO / ⚡ MODO RÁPIDO
        # =========================================================
        chat_auto_action = getattr(self, "_chat_confirm_action", None)
        self._chat_confirm_action = None

        # Si viene una acción automática del chat, respetarla primero
        if chat_auto_action in ("no_print", "print"):
            self._submit_sale(payload, print_ticket=(chat_auto_action == "print"))
            return

        if chat_auto_action == "cancel":
            return

        # ⚡ Modo rápido: no abrir diálogo
        if getattr(self, "quick_sale_mode", False):
            self._submit_sale(payload, print_ticket=False)
            return

        # Flujo normal con diálogo
        dlg = ConfirmSaleDialog(
            self,
            customer_name=customer_name,
            payment_method=payment_method,
            items=items,
            totals=totals,
            auto_action=None
        )

        if dlg.exec() != QDialog.Accepted:
            return

        self._submit_sale(payload, print_ticket=dlg.print_ticket)




    def edit_cart_item_by_pid(self, product_id: int):
        if product_id not in self.cart:
            return

        item = self.cart[product_id]
        product = item.get("product", {})

        product_name = product.get("name", "Producto")
        current_qty = float(item.get("quantity") or 1)
        current_price = float(item.get("unit_price") or 0)
        current_discount = float(item.get("discount_percent") or 0)
        stock = float(product.get("stock") or 99999)
        unit_type = product.get("unit_type", "Unid") or "Unid"

        dlg = EditCartItemDialog(
            product_name=product_name,
            quantity=current_qty,
            unit_price=current_price,
            discount_percent=current_discount,
            max_stock=stock,
            unit_type=unit_type,
            parent=self
        )

        if dlg.exec() != QDialog.Accepted:
            return

        data = dlg.get_data()

        self.cart[product_id]["quantity"] = data["quantity"]
        self.cart[product_id]["unit_price"] = float(data["unit_price"])
        self.cart[product_id]["discount_percent"] = float(data["discount_percent"])

        self.refresh_cart_table()

        show_toast(
            f"✏️ {product_name} actualizado en el carrito",
            success=True,
            parent=self
        )
        self._focus_product_search()

    def on_cart_cell_double_clicked(self, row, column):
        if row < 0:
            return

        item = self.cart_table.item(row, 0)
        if not item:
            return

        pid = item.data(Qt.UserRole)
        if pid is None:
            return

        self.edit_cart_item_by_pid(pid)

    def open_cart_context_menu(self, pos):
        row = self.cart_table.rowAt(pos.y())
        if row < 0:
            return

        name_item = self.cart_table.item(row, 0)
        if not name_item:
            return

        pid = name_item.data(Qt.UserRole)
        if pid is None or pid not in self.cart:
            return

        current_discount = float(self.cart[pid].get("discount_percent") or 0)

        menu = QMenu(self)

        edit_action = menu.addAction("✏️ Editar ítem")
        menu.addSeparator()

        disc_label = f" ({current_discount:.2f}%)" if current_discount > 0 else ""
        discount_action = menu.addAction(
            f"🏷 Aplicar descuento{disc_label}"
        )

        remove_discount_action = None
        if current_discount > 0:
            remove_discount_action = menu.addAction("🧹 Quitar descuento")

        menu.addSeparator()
        remove_action = menu.addAction("🗑 Eliminar del carrito")

        selected = menu.exec(self.cart_table.viewport().mapToGlobal(pos))
        if not selected:
            return

        if selected == edit_action:
            self.edit_cart_item_by_pid(pid)

        elif selected == discount_action:
            self.apply_discount_by_pid(pid)

        elif remove_discount_action and selected == remove_discount_action:
            self.cart[pid]["discount_percent"] = 0.0             # ✅ FASE 2.4: float
            self.refresh_cart_table()
            show_toast("🧹 Descuento eliminado", success=True, parent=self)

        elif selected == remove_action:
            self.remove_from_cart(pid)

    def apply_discount_by_pid(self, product_id: int):
        from PySide6.QtWidgets import QInputDialog

        if product_id not in self.cart:
            return

        product = self.cart[product_id].get("product", {})
        product_name = product.get("name", "Producto")
        current_discount = float(self.cart[product_id].get("discount_percent") or 0)

        # ✅ FASE 2.4: getDouble para soportar descuentos fraccionarios (ej: 5.5%)
        percent, ok = QInputDialog.getDouble(
            self,
            "Descuento por producto",
            f"Ingrese el descuento (%) para:\n{product_name}",
            current_discount,
            0.0,
            100.0,
            2       # 2 decimales
        )

        if not ok:
            return

        self.cart[product_id]["discount_percent"] = float(percent)
        self.refresh_cart_table()

        if percent > 0:
            show_toast(
                f"🏷 Descuento de {percent:.2f}% aplicado a {product_name}",
                success=True,
                parent=self
            )
        else:
            show_toast(
                f"🧹 Descuento eliminado de {product_name}",
                success=True,
                parent=self
            )

    def apply_discount(self, row):
        if row < 0:
            return

        item = self.cart_table.item(row, 0)
        if not item:
            return

        pid = item.data(Qt.UserRole)
        if pid is None:
            return

        self.apply_discount_by_pid(pid)


    def update_customer_info_box(self):
        """Actualiza la info del cliente y muestra/oculta el recuadro."""
        # Usar el ID ya seleccionado, no el texto del campo
        cid = self.selected_customer_id

        # Si no hay cliente seleccionado o es el cliente general, ocultar
        if not cid or cid == self.general_customer_id:
            self.customer_info_scroll.setVisible(False)
            return

        # Buscar el cliente seleccionado en la lista cargada
        customer_data = next((c for c in self.customers if c.get("id") == cid), None)

        if not customer_data:
            self.customer_info_scroll.setVisible(False)
            return

        # Construir identificación bonita
        id_type = customer_data.get("id_type") or "Sin tipo"
        id_number = customer_data.get("id_number") or "Sin número"
        id_display = f"{id_type}: {id_number}"

        # Actualizar texto de labels con información más compacta
        self.lbl_info_name.setText(f"<b>{customer_data.get('name', 'Sin nombre')}</b>")
        self.lbl_info_id.setText(f"🪪 {id_display}")
        
        email = customer_data.get("email") or "Sin correo"
        self.lbl_info_email.setText(f"📧 {email}")
        
        address = customer_data.get("address") or "Sin dirección"
        self.lbl_info_address.setText(f"📍 {address}")

        # Mostrar scroll area
        self.customer_info_scroll.setVisible(True)

    def showEvent(self, event):
        super().showEvent(event)

        if self._is_cash_open():
            QTimer.singleShot(0, self._focus_product_search)
            QTimer.singleShot(150, self._focus_product_search)

    # ------------------------------------------------------------------
    # Perma-focus helpers
    # ------------------------------------------------------------------
    def _is_cash_open(self) -> bool:
        return bool(getattr(self, "cash_session_open", False))

    def _focus_product_search(self):
        """Enfoca el buscador solo si la caja está abierta."""
        if not self._is_cash_open():
            return

        if hasattr(self, "search_input") and self.isVisible():
            self.search_input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
            self.search_input.selectAll()

    def _apply_focus_policy(self):
        """Instala o remueve el eventFilter según estado de caja."""
        app = QApplication.instance()
        if not app:
            return

        if self._is_cash_open():
            if not self._perma_focus_installed:
                app.installEventFilter(self)
                self._perma_focus_installed = True
            QTimer.singleShot(0, self._focus_product_search)
        else:
            if self._perma_focus_installed:
                try:
                    app.removeEventFilter(self)
                except Exception:
                    pass
                self._perma_focus_installed = False

    def eventFilter(self, obj, event):
        if not self._is_cash_open():
            return super().eventFilter(obj, event)
        if not self.isVisible():
            return super().eventFilter(obj, event)

        if event.type() == QEvent.MouseButtonRelease:
            w = QApplication.focusWidget()

            protected = []
            if hasattr(self, "customer_search"):
                protected.append(self.customer_search)
            if hasattr(self, "amount_input"):
                protected.append(self.amount_input)
            if hasattr(self, "credit_days_input"):
                protected.append(self.credit_days_input)

            # Si el foco quedó en un input protegido, respetarlo
            if w in protected:
                return super().eventFilter(obj, event)

            # Si el click fue dentro de un input protegido, respetarlo
            target = (
                QApplication.widgetAt(event.globalPosition().toPoint())
                if hasattr(event, "globalPosition") else None
            )
            if target is not None:
                for p in protected:
                    if p is not None and (target is p or p.isAncestorOf(target)):
                        return super().eventFilter(obj, event)

            # ✅ FIX 3: No robar foco si el click fue sobre un widget interactivo
            interactive_types = (QPushButton, QSpinBox, QComboBox, QTableWidget, QAbstractItemView)
            if target is not None and isinstance(target, interactive_types):
                return super().eventFilter(obj, event)

            # No robar foco si el click fue fuera de SalesView (ej: sidebar)
            if target is not None and not self.isAncestorOf(target):
                return super().eventFilter(obj, event)

            # Click completado dentro de Ventas -> devolver foco al buscador
            QTimer.singleShot(0, self._focus_product_search)

        return super().eventFilter(obj, event)

    def check_cash_session(self):
        api_call("get",
            f"{API_BASE_URL}/cash/current",
            headers=self._auth_headers(),
            timeout=5,
            on_success=self._on_cash_session_checked,
            on_error=self._on_cash_session_error,
        )

    def _on_cash_session_checked(self, json_data):
        """Callback: procesa estado de sesión de caja."""
        data = json_data.get("data", {})
        if not data.get("is_open"):
            self.cash_session_open = False
            self._apply_focus_policy()
            self.ask_open_cash()
        else:
            self.cash_session_open = True
            self._apply_focus_policy()

    def _on_cash_session_error(self, msg):
        """Callback: error al verificar sesión de caja."""
        QMessageBox.critical(
            self,
            "Error de caja",
            f"No se pudo verificar la caja:\n{msg}"
        )
        self.cash_session_open = False
        self.set_cash_buttons_enabled(False)
        self._apply_focus_policy()
        self.setDisabled(True)

            
    def ask_open_cash(self):
        from PySide6.QtWidgets import QInputDialog

        amount, ok = QInputDialog.getDouble(
            self,
            "Apertura de caja",
            "Ingrese el monto inicial en caja:",
            0.0,
            0.0,
            99999999,
            2
        )

        if not ok:
            QMessageBox.warning(
                self,
                "Caja requerida",
                "Debe abrir la caja para poder vender."
            )
            self.ask_open_cash()
            return

        # ── FASE 2: Async para no congelar la UI ──
        def on_success(json_data):
            self.cash_session_open = True
            self.set_cash_buttons_enabled(True)
            show_toast("🟢 Caja abierta correctamente", success=True, parent=self)
            self._apply_focus_policy()
            QTimer.singleShot(0, self._focus_product_search)
            QTimer.singleShot(150, self._focus_product_search)

        def on_error(msg):
            QMessageBox.critical(self, "Error", msg)
            self.ask_open_cash()

        api_call("post",
            f"{API_BASE_URL}/cash/open",
            json={"opening_amount": amount},
            headers=self._auth_headers(),
            timeout=5,
            on_success=on_success,
            on_error=on_error,
        )

    def open_cash_movement(self, movement_type: str):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox

        dialog = QDialog(self)
        dialog.setWindowTitle(
            "Entrada de efectivo" if movement_type == "in" else "Salida de efectivo"
        )

        layout = QVBoxLayout(dialog)

        lbl_concept = QLabel("Concepto:")
        txt_concept = QLineEdit()
        txt_concept.setPlaceholderText("Ej: Cambio inicial / Pago proveedor")

        lbl_amount = QLabel("Monto:")
        txt_amount = QLineEdit()
        txt_amount.setPlaceholderText("0.00")

        btn_confirm = QPushButton("Confirmar")
        btn_cancel = QPushButton("Cancelar")

        layout.addWidget(lbl_concept)
        layout.addWidget(txt_concept)
        layout.addWidget(lbl_amount)
        layout.addWidget(txt_amount)
        layout.addWidget(btn_confirm)
        layout.addWidget(btn_cancel)

        btn_cancel.clicked.connect(dialog.reject)

        def submit():
            concept = txt_concept.text().strip()
            amount_text = txt_amount.text().strip()

            if not concept or not amount_text:
                QMessageBox.warning(dialog, "Error", "Debe completar todos los campos.")
                return

            try:
                amount = float(amount_text)
                if amount <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(dialog, "Error", "Monto inválido.")
                return

            self.send_cash_movement(movement_type, concept, amount)
            dialog.accept()

        btn_confirm.clicked.connect(submit)

        dialog.exec()

    def send_cash_movement(self, movement_type: str, concept: str, amount: float):
        payload = {
            "type": movement_type,
            "concept": concept,
            "amount": amount,
            "create_expense": movement_type == "out"
        }

        # ── FASE 2: Async para no congelar la UI ──
        def on_success(json_data):
            show_toast(
                "Movimiento registrado correctamente",
                success=True,
                parent=self
            )

        def on_error(msg):
            QMessageBox.critical(self, "Error", f"No se pudo registrar el movimiento:\n{msg}")

        api_call("post",
            f"{API_BASE_URL}/cash/movements",
            json=payload,
            headers=self._auth_headers(),
            timeout=5,
            on_success=on_success,
            on_error=on_error,
        )

    def set_cash_buttons_enabled(self, enabled: bool):
        self.btn_cash_in.setEnabled(enabled)
        self.btn_cash_out.setEnabled(enabled)

    def open_close_cash_dialog(self):
        api_call("get",
            f"{API_BASE_URL}/cash/report/today",
            headers=self._auth_headers(),
            timeout=5,
            on_success=self._on_cash_report_loaded,
            on_error=self._on_cash_report_error,
        )

    def _on_cash_report_error(self, msg):
        QMessageBox.critical(self, "Error", f"No se pudo obtener el reporte:\n{msg}")

    def _on_cash_report_loaded(self, json_data):
        """Callback: construye el diálogo de cierre de caja con los datos del reporte."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QLabel, QLineEdit,
            QPushButton, QMessageBox, QGridLayout
        )

        data = json_data["data"]

        dialog = QDialog(self)
        dialog.setWindowTitle("Cierre de caja")
        layout = QVBoxLayout(dialog)

        grid = QGridLayout()

        def row(label, value, r):
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(QLabel(f"₡ {value:.2f}"), r, 1)

        row("Apertura:", data["opening_amount"], 0)
        row("Entradas:", data["entries"], 1)
        row("Salidas:", data["exits"], 2)
        row("Ventas efectivo:", data["payment_breakdown"].get("Efectivo", 0), 3)
        row("Total esperado:", data["expected"], 4)

        layout.addLayout(grid)

        lbl_real = QLabel("💰 Efectivo contado:")
        txt_real = QLineEdit()
        txt_real.setPlaceholderText("0.00")

        lbl_diff = QLabel("Diferencia: ₡ 0.00")
        lbl_diff.setStyleSheet("font-weight: bold;")

        layout.addWidget(lbl_real)
        layout.addWidget(txt_real)
        layout.addWidget(lbl_diff)

        def update_diff():
            try:
                real = float(txt_real.text())
                diff = real - data["expected"]
                color = "#22c55e" if diff == 0 else "#f59e0b" if abs(diff) < 100 else "#ef4444"
                lbl_diff.setText(f"Diferencia: ₡ {diff:.2f}")
                lbl_diff.setStyleSheet(f"font-weight: bold; color: {color}")
            except (ValueError, TypeError):
                lbl_diff.setText("Diferencia: ₡ 0.00")

        txt_real.textChanged.connect(update_diff)

        btn_confirm = QPushButton("🔒 Confirmar cierre")
        btn_cancel = QPushButton("Cancelar")

        btn_confirm.clicked.connect(lambda: self.confirm_close_cash(dialog, txt_real.text()))
        btn_cancel.clicked.connect(dialog.reject)

        layout.addWidget(btn_confirm)
        layout.addWidget(btn_cancel)

        dialog.exec()

    def confirm_close_cash(self, dialog, real_amount_text):
        from PySide6.QtWidgets import QMessageBox

        try:
            real_amount = float(real_amount_text)
            if real_amount < 0:
                raise ValueError
        except (ValueError, TypeError):
            QMessageBox.warning(dialog, "Error", "Monto inválido.")
            return

        # ── FASE 2: Async para no congelar la UI ──
        def on_success(json_data):
            show_toast("🔒 Caja cerrada correctamente", success=True, parent=self)
            dialog.accept()
            self.btn_cash_in.setEnabled(False)
            self.btn_cash_out.setEnabled(False)
            self.confirm_btn.setEnabled(False)
            self.check_cash_session()

        def on_error(msg):
            QMessageBox.critical(self, "Error", f"No se pudo cerrar la caja:\n{msg}")

        api_call("post",
            f"{API_BASE_URL}/cash/close",
            json={"closing_amount": real_amount},
            headers=self._auth_headers(),
            timeout=5,
            on_success=on_success,
            on_error=on_error,
        )

    def print_ticket(self, api_response: dict, payload: dict):
        # 🔥 Placeholder (luego aquí conectamos tu generador PDF/impresora)
        # api_response normalmente trae el id de venta y data del backend
        show_toast("🖨 Ticket enviado a impresión (placeholder)", success=True, parent=self)

    def on_payment_method_changed(self, text: str):
        """Muestra/oculta el input de días de crédito según método de pago."""
        is_credit = text.strip().lower() in ("credito", "crédito")
        self.credit_days_input.setVisible(is_credit)
        self.credit_days_label.setVisible(is_credit)

    def toggle_amount_input(self):
        """Habilita el monto recibido solo si el pago es en Efectivo."""
        method = self.payment_combo.currentText()
        is_cash = (method == "Efectivo")
        
        # Activar/Desactivar el campo de monto recibido
        self.amount_input.setEnabled(is_cash)
        
        # 🛡️ Validación de cliente para Crédito
        if method == "Crédito" and not self.selected_customer_id:
            QMessageBox.warning(self, "Aviso", "Para ventas a crédito debe seleccionar un cliente registrado.")
            self.payment_combo.setCurrentText("Efectivo")
            self.amount_input.setEnabled(True)
            return

        if not is_cash:
            self.amount_input.clear()
            self.change_label.setText("Cambio: ₡0.00")
        else:
        # Poner el foco en el campo si es efectivo
            self.amount_input.setFocus()
            
    def fetch_customer_credit_status(self, customer_id: int):
        try:
            r = api_request("get",
                f"{API_BASE_URL}/credits/{customer_id}",
                headers=self._auth_headers()
            )

            if r.status_code != 200:
                return None

            data = r.json().get("data", {})
            customer = data.get("customer", {})

            balance = float(customer.get("credit_balance", 0.0))
            limit_ = float(customer.get("credit_limit", 0.0))

            return {
                "balance": balance,
                "limit": limit_,
                "usage_ratio": (balance / limit_) if limit_ > 0 else None
            }

        except Exception:
            return None

    def can_sell_on_credit(self, customer_id: int, sale_total: float):
        credit = self.fetch_customer_credit_status(customer_id)

        if not credit:
            return True, None  # no bloquear si no hay info

        balance = credit["balance"]
        limit_ = credit["limit"]

        # 🟢 Sin límite → siempre permitir
        if limit_ <= 0:
            return True, None

        projected_balance = balance + sale_total
        usage_ratio = projected_balance / limit_

        # 🔴 Bloqueo duro
        if projected_balance > limit_:
            return False, (
                f"❌ LÍMITE DE CRÉDITO SUPERADO\n\n"
                f"Saldo actual: ₡{balance:,.2f}\n"
                f"Venta: ₡{sale_total:,.2f}\n"
                f"Límite: ₡{limit_:,.2f}"
            )

        # 🟡 Advertencia (NO bloquea)
        if usage_ratio >= 0.8:
            return True, (
                f"⚠️ ADVERTENCIA DE CRÉDITO\n\n"
                f"El cliente alcanzará el {usage_ratio*100:.1f}% "
                f"de su límite de crédito."
            )

        return True, None

    def on_customer_selected_from_text(self, text: str):
        name = (text or "").strip()
        cid = self.customer_name_to_id.get(name)

        # Si no existe, no hacemos nada (pero igual ocultamos info box)
        self.selected_customer_id = cid

        # Si escogió cliente diferente a general, mostrar info
        self.update_customer_info_box()
    
    def on_customer_text_changed(self):
        """
        Se ejecuta cuando el usuario termina de editar el campo de búsqueda de cliente.
        Valida que el texto corresponda a un cliente real.
        """
        text = self.customer_search.text().strip()
        
        if not text:
            # Campo vacío -> sin cliente
            self.selected_customer_id = None
            self.customer_info_scroll.setVisible(False)
            return
        
        # Buscar el ID del cliente por nombre
        cid = self.customer_name_to_id.get(text)
        
        if cid is not None:
            # Cliente válido encontrado
            self.selected_customer_id = cid
        else:
            # Nombre no válido - limpiar campo
            self.customer_search.clear()
            self.selected_customer_id = None
            show_toast("Cliente no encontrado.", success=False, parent=self)
        
        self.update_customer_info_box()
        
    def add_product_by_id(self, product_id: int, qty: int = 1):
        """
        Usado por el chat: agrega qty unidades del producto al carrito.
        Reusa tu lógica actual (add_to_cart_from_card).
        """
        try:
            qty = max(1, int(qty))
        except Exception:
            qty = 1

        product = None
        for p in getattr(self, "products", []) or []:
            if p.get("id") == product_id:
                product = p
                break

        if not product:
            try:
                from ui.components.toast_notifier import show_toast
                show_toast(
                    "No encontré ese producto para agregar al carrito.",
                    success=False,
                    parent=self
                )
            except Exception:
                pass
            return False


        for _ in range(qty):
            self.add_to_cart_from_card(product)

        return True

    def show_sale_summary(self):
        """
        Muestra un resumen visual de la venta actual sin confirmarla.
        Se llama cuando el chat envía la acción 'preview_confirm_sale'.
        """
        # Obtener datos actuales
        customer_id = self.selected_customer_id
        customer_name = (self.customer_search.text().strip() or "Consumidor final")
        payment_method = self.payment_combo.currentText()
        
        # Calcular totales
        subtotal = self._current_subtotal
        discount = self._current_discount
        iva = self._current_iva
        total = self._current_total
        
        # Contar items en el carrito
        total_items = sum(float(item.get("quantity", 0)) for item in self.cart.values())
        
        # Crear mensaje de resumen
        summary = f"""
    🧾 <b>RESUMEN DE VENTA</b>

    <b>Cliente:</b> {customer_name}
    <b>Método de pago:</b> {payment_method}

    <b>Items en carrito:</b> {total_items}
    <b>Subtotal:</b> ₡{subtotal:,.2f}
    <b>Descuento:</b> ₡{discount:,.2f}
    <b>IVA:</b> ₡{iva:,.2f}
    <b>TOTAL:</b> ₡{total:,.2f}
    """
        
        # Opcional: Mostrar toast o actualizar algún label en la UI
        from ui.components.toast_notifier import show_toast
        show_toast(
            f"Revisa el resumen. Total: ₡{total:,.2f}",
            success=True,
            parent=self,
            duration=5000  # 5 segundos
        )
        
    def set_customer_by_name(self, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False

        # Asegurar que exista el mapa (según tu archivo ya lo usás)
        mapping = getattr(self, "customer_name_to_id", {}) or {}
        if not mapping:
            # si todavía no cargó clientes, al menos ponemos el texto
            if hasattr(self, "customer_search"):
                self.customer_search.setText(name)
            return False

        # match exact (case-insensitive)
        name_l = name.lower()
        found_id = None
        for cname, cid in mapping.items():
            if (cname or "").lower() == name_l:
                found_id = cid
                break

        # fallback parcial
        if found_id is None:
            for cname, cid in mapping.items():
                if name_l in (cname or "").lower():
                    found_id = cid
                    break

        if found_id is None:
            if hasattr(self, "customer_search"):
                self.customer_search.setText(name)
            return False

        self.selected_customer_id = found_id
        if hasattr(self, "customer_search"):
            self.customer_search.setText(name)

        if hasattr(self, "update_customer_info_box"):
            self.update_customer_info_box()

        return True


    def set_payment_method_from_chat(self, method: str) -> bool:
        method = (method or "").strip().lower()
        if not method or not hasattr(self, "payment_combo"):
            return False

        # normalizar lo que manda el backend (sinpe/cash/card)
        aliases = {
            "sinpe": ["sinpe"],
            "cash": ["cash", "efectivo"],
            "card": ["card", "tarjeta", "datáfono", "datafono"],
        }

        target_keywords = aliases.get(method, [method])

        for i in range(self.payment_combo.count()):
            txt = (self.payment_combo.itemText(i) or "").strip().lower()
            if any(k in txt for k in target_keywords):
                self.payment_combo.setCurrentIndex(i)
                return True

        return False
    
    def remove_from_cart_by_name(self, name_query: str) -> bool:
        """
        Quita del carrito el producto cuyo nombre matchee con name_query (contains, case-insensitive).
        Si hay múltiples, elige el mejor: exact > startswith > contains.
        Retorna True si removió algo.
        """
        q = (name_query or "").strip().lower()
        if not q or not self.cart:
            return False

        best_pid = None
        best_score = -10_000

        for pid, item in self.cart.items():
            prod = (item or {}).get("product") or {}
            name = (prod.get("name") or "").strip()
            n = name.lower()

            if not n:
                continue

            if n == q:
                score = 3000
            elif n.startswith(q):
                score = 2000
            elif q in n:
                score = 1000
            else:
                continue

            # desempate: preferir el más corto (más cercano)
            score -= len(n)

            if score > best_score:
                best_score = score
                best_pid = pid

        if best_pid is None:
            return False

        self.remove_from_cart(best_pid)
        return True
    
    def decrement_from_cart_by_name(self, name_query: str, qty: int = 1) -> tuple[bool, int, str]:
        """
        Resta qty unidades del producto que matchee por nombre.
        - Si qty >= cantidad actual: elimina la línea del carrito.
        Retorna: (ok, removed_qty, matched_name)
        """
        q = (name_query or "").strip().lower()
        if not q or not self.cart:
            return (False, 0, "")

        try:
            qty = max(1, int(qty))
        except Exception:
            qty = 1

        # Reusa la misma lógica de match que remove_from_cart_by_name
        best_pid = None
        best_name = ""
        best_score = -10_000

        for pid, item in self.cart.items():
            prod = (item or {}).get("product") or {}
            name = (prod.get("name") or "").strip()
            n = name.lower()
            if not n:
                continue

            if n == q:
                score = 3000
            elif n.startswith(q):
                score = 2000
            elif q in n:
                score = 1000
            else:
                continue

            score -= len(n)

            if score > best_score:
                best_score = score
                best_pid = pid
                best_name = name

        if best_pid is None:
            return (False, 0, "")

        current_qty = int(self.cart[best_pid].get("quantity") or 0)
        if current_qty <= 0:
            return (False, 0, best_name)

        removed = min(qty, current_qty)
        new_qty = current_qty - removed

        if new_qty <= 0:
            self.remove_from_cart(best_pid)
        else:
            self.cart[best_pid]["quantity"] = new_qty
            self.refresh_cart_table()

        return (True, removed, best_name)

    # ---------------------------------------------------------
    # Ventas pausadas
    # ---------------------------------------------------------
    def _calc_cart_total(self, cart: dict) -> float:
        total = 0.0
        for pid, item in (cart or {}).items():
            qty = float(item.get("quantity") or 0)
            price = float(item.get("unit_price") or 0)
            percent = float(item.get("discount_percent") or 0)
            original = price * qty
            discount_amount = original * (percent / 100.0)
            total += (original - discount_amount)
        return float(total)

    def _paused_tab_title(self, sale: dict) -> str:
        customer = (sale.get("customer_text") or "").strip() or "Venta"
        items = int(sale.get("items_count") or 0)
        total = float(sale.get("total") or 0.0)
        total_txt = f"₡{total:,.0f}".replace(",", ".")
        return f"{customer} · {items} ítems · {total_txt}"

    def _update_paused_sales_ui(self):
        n = len(getattr(self, "paused_sales", []) or [])
        self.paused_tabs_scroll.setVisible(n > 0)

    def _delete_paused_sale(self, sale_id: int):
        paused = getattr(self, "paused_sales", []) or []
        self.paused_sales = [s for s in paused if s.get("id") != sale_id]

        if getattr(self, "active_paused_sale_id", None) == sale_id:
            self.active_paused_sale_id = None

        show_toast("🗑 Venta pausada eliminada", success=True, parent=self)
        self._render_paused_tabs()

    def _render_paused_tabs(self):
        # limpiar
        while self.paused_tabs_layout.count():
            item = self.paused_tabs_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        paused = getattr(self, "paused_sales", []) or []
        self._update_paused_sales_ui()

        if not paused:
            return

        for sale in paused:
            sid = sale["id"]
            title = self._paused_tab_title(sale)
            is_active = (getattr(self, "active_paused_sale_id", None) == sid)

            # contenedor chip
            chip = QWidget()
            chip_layout = QHBoxLayout(chip)
            chip_layout.setContentsMargins(0, 0, 0, 0)
            chip_layout.setSpacing(0)

            # botón principal (reanuda)
            main_btn = QPushButton(title)
            main_btn.setCursor(Qt.PointingHandCursor)
            main_btn.setFixedHeight(34)

            # botón cerrar (elimina sin reanudar)
            close_btn = QPushButton("✖")
            close_btn.setCursor(Qt.PointingHandCursor)
            close_btn.setFixedSize(34, 34)
            close_btn.setToolTip("Eliminar venta pausada")

            main_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {"#1f2937" if is_active else "#0b1120"};
                    color: #f9fafb;
                    border: 1px solid {"#6366f1" if is_active else "#374151"};
                    border-right: none;
                    border-top-left-radius: 10px;
                    border-bottom-left-radius: 10px;
                    padding: 6px 10px;
                    font-weight: 800;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: #111827;
                    border: 1px solid #6366f1;
                    border-right: none;
                }}
            """)

            close_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {"#1f2937" if is_active else "#0b1120"};
                    color: #fca5a5;
                    border: 1px solid {"#6366f1" if is_active else "#374151"};
                    border-left: none;
                    border-top-right-radius: 10px;
                    border-bottom-right-radius: 10px;
                    font-weight: 900;
                }}
                QPushButton:hover {{
                    background-color: #111827;
                    color: #fecaca;
                    border: 1px solid #ef4444;
                    border-left: none;
                }}
            """)

            main_btn.clicked.connect(lambda checked=False, sale_id=sid: self.resume_paused_sale(sale_id=sale_id))
            close_btn.clicked.connect(lambda checked=False, sale_id=sid: self._delete_paused_sale(sale_id))

            chip_layout.addWidget(main_btn)
            chip_layout.addWidget(close_btn)

            self.paused_tabs_layout.addWidget(chip)

        self.paused_tabs_layout.addStretch()

    def pause_current_sale(self):
        if not self.cart:
            show_toast("No hay productos para pausar.", success=False, parent=self)
            return

        self._paused_sale_seq = getattr(self, "_paused_sale_seq", 0) + 1
        sale_id = int(time.time() * 1000) + self._paused_sale_seq

        # snapshot completo
        paused_total = self._calc_cart_total(self.cart)

        snapshot = {
            "id": sale_id,
            "cart": copy.deepcopy(self.cart),
            "customer_id": self.selected_customer_id,
            "customer_text": (self.customer_search.text() or "").strip(),
            "payment_method": self.payment_combo.currentText(),
            "doc_type_code": self.doc_type_combo.currentData(),
            "credit_days": int(self.credit_days_input.value()),
            "items_count": sum(int(x.get("quantity") or 0) for x in self.cart.values()),
            "total": paused_total,
        }

        self.paused_sales.append(snapshot)
        self.active_paused_sale_id = sale_id

        self.clear_cart()
        show_toast("⏸ Venta pausada", success=True, parent=self)

        self._render_paused_tabs()
        QTimer.singleShot(0, self._focus_product_search)

    def resume_paused_sale(self, sale_id: int | None = None):
        paused = getattr(self, "paused_sales", []) or []
        if not paused:
            show_toast("No hay ventas pausadas.", success=False, parent=self)
            return

        # si viene de pestaña, usar ese; si no, usar la última
        target = None
        if sale_id is not None:
            for s in paused:
                if s.get("id") == sale_id:
                    target = s
                    break
        if target is None:
            target = paused[-1]

        # quitar de lista
        self.paused_sales = [s for s in paused if s.get("id") != target.get("id")]
        self.active_paused_sale_id = None

        # restaurar UI + carrito
        self.cart = copy.deepcopy(target.get("cart") or {})
        self.selected_customer_id = target.get("customer_id")

        try:
            self.customer_search.setText(target.get("customer_text") or "")
        except Exception:
            pass
        self.update_customer_info_box()

        # doc type por code
        code = target.get("doc_type_code")
        if code is not None:
            for i in range(self.doc_type_combo.count()):
                if self.doc_type_combo.itemData(i) == code:
                    self.doc_type_combo.setCurrentIndex(i)
                    break

        # payment
        pm = target.get("payment_method") or "Efectivo"
        self.payment_combo.setCurrentText(pm)

        # credit days
        try:
            self.credit_days_input.setValue(int(target.get("credit_days") or 30))
        except Exception:
            pass

        self.refresh_cart_table()
        self.update_totals()

        show_toast("▶ Venta reanudada", success=True, parent=self)

        self._render_paused_tabs()
        QTimer.singleShot(0, self._focus_product_search)

    def _update_pause_resume_buttons(self):
        """Compatibilidad: delega a _render_paused_tabs."""
        self._render_paused_tabs()

    # ---------------------------------------------------------
    # Diálogo ventas del día
    # ---------------------------------------------------------
    def open_day_sales_dialog(self):
        dlg = DaySalesDialog(self)
        dlg.exec()

    # ---------------------------------------------------------
    # Atajos de teclado POS
    # ---------------------------------------------------------
    def keyPressEvent(self, event):
        key = event.key()

        # Ctrl+P → abrir diálogo de Producto Común
        if key == Qt.Key_P and event.modifiers() & Qt.ControlModifier:
            self.open_common_product_dialog()
            event.accept()
            return

        # F1 → buscar producto
        if key == Qt.Key_F1:
            self.search_input.setFocus()
            self.search_input.selectAll()
            return

        # F2 → seleccionar cliente
        if key == Qt.Key_F2:
            if hasattr(self, "customer_search"):
                self.customer_search.setFocus()
                self.customer_search.selectAll()
            return

        # F3 → descuento al item seleccionado en carrito
        if key == Qt.Key_F3:
            if hasattr(self, "discount_input"):
                self.discount_input.setFocus()
                self.discount_input.selectAll()
            else:
                row = self.cart_table.currentRow()
                if row >= 0:
                    self.apply_discount(row)
                else:
                    show_toast("Seleccioná un producto del carrito primero.", parent=self)
            return

        # F4 → editar cantidad del producto seleccionado en carrito
        if key == Qt.Key_F4:
            row = self.cart_table.currentRow()
            if row >= 0:
                spin = self.cart_table.cellWidget(row, 1)
                if spin:
                    spin.setFocus()
                    spin.selectAll()
            return

        # F5 → confirmar venta
        if key == Qt.Key_F5:
            self.confirm_sale()
            return

        # F6 → cancelar venta / limpiar carrito
        if key == Qt.Key_F6:
            self.clear_cart()
            return

        # F7 → método de pago: Efectivo
        if key == Qt.Key_F7:
            if hasattr(self, "payment_combo"):
                self.payment_combo.setCurrentText("Efectivo")
                show_toast("💵 Efectivo", success=True, parent=self)
            return

        # F8 → método de pago: Tarjeta
        if key == Qt.Key_F8:
            if hasattr(self, "payment_combo"):
                self.payment_combo.setCurrentText("Tarjeta")
                show_toast("💳 Tarjeta", success=True, parent=self)
            return

        # F9 → método de pago: SINPE
        if key == Qt.Key_F9:
            if hasattr(self, "payment_combo"):
                self.payment_combo.setCurrentText("SINPE")
                show_toast("📱 SINPE", success=True, parent=self)
            return

        # F10 → activar/desactivar modo rápido
        if key == Qt.Key_F10:
            self.on_quick_sale_toggled(not self.quick_sale_mode)
            event.accept()
            return

        # ESC → limpiar búsqueda y volver al buscador
        if key == Qt.Key_Escape:
            self.search_input.clear()
            self.search_input.setFocus()
            return

        super().keyPressEvent(event)