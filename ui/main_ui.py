from PySide6.QtWidgets import (
    QMainWindow, QLabel, QVBoxLayout, QWidget, QPushButton,
    QHBoxLayout, QMessageBox, QToolButton, QSizePolicy, QScrollArea,
    QFrame, QStackedLayout, QDialog
)
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QEvent, QTimer, Signal, QPoint, QObject
from ui.session_manager import session
from ui.widgets.chat_panel import ChatPanel
from datetime import date
from ui.components.toast_notifier import show_toast
import logging


class DraggableFabButton(QPushButton):
    def __init__(self, text, parent=None, *, on_click=None, on_moved=None, on_drag=None):
        super().__init__(text, parent)
        self._dragging = False
        self._drag_start_global = None
        self._drag_offset = None
        self._moved = False
        self._on_click = on_click
        self._on_moved = on_moved
        self._on_drag = on_drag

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._moved = False
            gp = event.globalPosition().toPoint()
            self._drag_start_global = gp
            self._drag_offset = self.mapFromGlobal(gp)  # offset dentro del botón
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            gp = event.globalPosition().toPoint()
            if (gp - self._drag_start_global).manhattanLength() > 6:
                if not self._moved:
                    self._moved = True
                    if callable(self._on_moved):
                        self._on_moved()

                parent = self.parentWidget()
                if parent:
                    new_pos = parent.mapFromGlobal(gp) - self._drag_offset

                    # clamp dentro de la ventana
                    rect = parent.rect()
                    x = max(0, min(new_pos.x(), rect.width() - self.width()))
                    y = max(0, min(new_pos.y(), rect.height() - self.height()))
                    self.move(x, y)

                    if callable(self._on_drag):
                        self._on_drag()

            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            # si no se movió, es click normal
            if not self._moved and callable(self._on_click):
                self._on_click()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    """Ventana principal del sistema POS Violette"""
    
    # Señal para notificar cambios de vista
    view_changed = Signal(str)

    # Estilo compartido por todos los botones del sidebar
    _MENU_BUTTON_STYLE = """
        QPushButton {
            background-color: #1f2933;
            color: #e5e7eb;
            border: 1px solid #374151;
            text-align: left;
            padding: 10px;
            font-size: 15px;
            border-radius: 12px;
            margin: 5px 4px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: #4f46e5;
            color: #f9fafb;
        }
    """
    
    def __init__(self, username):
        super().__init__()
        self.setWindowTitle("Violette POS - Panel Principal")
        self.resize(1200, 800)
        self.setMinimumSize(1200, 800)

        self.username = username
        self.role = session.role
        self.permissions = []  # Permisos granulares del usuario

        # Estado del sidebar
        self.sidebar_pinned = True  # True = expandido y fijo, False = colapsado
        
        # Dimensiones del sidebar
        self.sidebar_expanded_width = 230
        self.sidebar_collapsed_width = 60

        # Referencias a widgets principales
        self.sidebar_widget = None
        self.content_widget = None
        self.view_container = None
        self.view_layout = None
        self.chat_panel = None
        
        # Referencias a elementos del sidebar
        self.title_label = None
        self.user_label = None
        self.menu_buttons = []
        
        # Referencias a vistas (cache para evitar recreación innecesaria)
        self.current_view = None
        self.sales_history_view = None
        self.sales_view = None
        self.dashboard_view = None
        self._products_view = None
        self._customers_view = None
        self._expenses_view = None
        self._financial_view = None
        self._daily_report_view = None
        self._suppliers_view = None
        self._categories_view = None
        self._purchases_view = None
        self._settings_view = None
        self._analytics_view = None
        self._purchases_analytics_view = None
        self._proformas_view = None
        self._no_rotation_view = None
        self._einvoice_view = None
        
        self.root_widget = None
        self.stacked = None
        self.base_widget = None
        self.base_layout = None
        self.overlay_container = None
        self.sidebar_placeholder = None

        self.sidebar_in_overlay = False
        self._hover_tracking_enabled = False
        self._chat_cart_history = []  # pila LIFO de (product_id, qty) agregados desde el chat
        self._fab_user_moved = False



        self.setup_ui()
        self.showMaximized()

    def resizeEvent(self, event):
        super().resizeEvent(event)

        if not self.sidebar_pinned and self.sidebar_in_overlay and self.sidebar_widget:
            cw = self.centralWidget()
            h = cw.height() if cw else self.height()
            self.sidebar_widget.setGeometry(0, 0, self.sidebar_expanded_width, h)

        self._position_floating_chat()

    # ==========================================================
    # MÉTODOS PARA CREAR BOTONES DE GRUPO Y SUBMENUS
    # ==========================================================
    def make_group_button(self, title, icon="📂"):
        """Crea un botón de grupo expandible"""
        btn = QToolButton()
        btn.setText(f"{icon} {title}")
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setCheckable(True)
        btn.setChecked(False)
        btn.setArrowType(Qt.RightArrow)
        btn.setStyleSheet("""
            QToolButton {
                background-color: #1f2933;
                color: #e5e7eb;
                border: 1px solid #374151;
                padding: 8px;
                font-size: 15px;
                border-radius: 10px;
                margin: 5px 4px;
                text-align: left;
            }
            QToolButton:hover {
                background-color: #4f46e5;
            }
            QToolButton:checked {
                background-color: #4f46e5;
                color: white;
            }
        """)
        return btn

    def make_sub_button(self, text):
        """Crea un botón de submenú"""
        btn = QPushButton(text)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #161e2a;
                color: #a5b4fc;
                border: 1px solid #2a3350;
                text-align: left;
                padding: 7px 12px;
                font-size: 14px;
                border-radius: 8px;
                margin: 3px 20px;
            }
            QPushButton:hover {
                background-color: #4f46e5;
                color: #fff;
            }
        """)
        return btn

    # ==========================================================
    # SETUP UI PRINCIPAL
    # ==========================================================
    def setup_ui(self):
        central_style = """
            QWidget { background-color: #111827; color: #e5e7eb; }
            QLabel { color: #e5e7eb; }
            QCalendarWidget {
                background-color: #1e1e2e;
                color: #e5e7eb;
            }
            QCalendarWidget QAbstractItemView {
                background-color: #1e1e2e;
                color: #e5e7eb;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
                alternate-background-color: #252535;
            }
            QCalendarWidget QAbstractItemView:enabled {
                color: #e5e7eb;
            }
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: #111827;
            }
            QCalendarWidget QToolButton {
                color: #e5e7eb;
                background-color: #1e1e2e;
                border: none;
                padding: 4px 8px;
                border-radius: 4px;
            }
            QCalendarWidget QToolButton:hover {
                background-color: #2563eb;
            }
            QCalendarWidget QMenu {
                background-color: #1e1e2e;
                color: #e5e7eb;
            }
            QCalendarWidget QSpinBox {
                background-color: #1e1e2e;
                color: #e5e7eb;
                border: 1px solid #374151;
            }
            QDateEdit {
                background-color: #1e1e2e;
                color: #e5e7eb;
                border: 1px solid #374151;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QDateEdit::drop-down {
                border: none;
                background-color: #2563eb;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                width: 20px;
            }
        """

        # Root con stacked "StackAll" (overlay real)
        self.root_widget = QWidget()
        self.root_widget.setStyleSheet(central_style)

        self.stacked = QStackedLayout(self.root_widget)
        self.stacked.setContentsMargins(0, 0, 0, 0)
        self.stacked.setSpacing(0)
        self.stacked.setStackingMode(QStackedLayout.StackAll)

        # --- BASE (push normal) ---
        self.base_widget = QWidget()
        self.base_layout = QHBoxLayout(self.base_widget)
        self.base_layout.setContentsMargins(0, 0, 0, 0)
        self.base_layout.setSpacing(0)

        self._create_sidebar()
        self._create_content_area()

        self.base_layout.addWidget(self.sidebar_widget, 0)
        self.base_layout.addWidget(self.content_widget, 1)

        # --- OVERLAY container (arriba) ---
        self.overlay_container = QWidget()
        self.overlay_container.setStyleSheet("background: transparent;")

        # ✅ IMPORTANTE: que NO intercepte el mouse
        self.overlay_container.setAttribute(Qt.WA_TransparentForMouseEvents, True)


        # Agregar ambas capas
        self.stacked.addWidget(self.base_widget)
        self.stacked.addWidget(self.overlay_container)

        self.setCentralWidget(self.root_widget)

        self.apply_role_permissions()
        QTimer.singleShot(100, lambda: self.show_section("ventas"))
        
        self._create_floating_chat()



    def _create_sidebar(self):
        """Crea el sidebar con todos sus elementos"""
        # Layout principal del sidebar
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setAlignment(Qt.AlignTop)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        
        # Título
        self.title_label = QLabel("🧾 Violette POS")
        self.title_label.setAlignment(Qt.AlignLeft)
        self.title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #a5b4fc; margin: 10px 4px;")
        sidebar_layout.addWidget(self.title_label)

        # Usuario — botón para cambiar de cajero/usuario
        self.user_label = QPushButton(f"👤 {self.username} ({self.role})")
        self.user_label.setToolTip("Clic para cambiar de usuario")
        self.user_label.setCursor(Qt.PointingHandCursor)
        self.user_label.setStyleSheet("""
            QPushButton {
                font-size: 13px;
                color: #9ca3af;
                background-color: transparent;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 6px 8px;
                text-align: left;
                margin: 0 4px 10px 4px;
            }
            QPushButton:hover {
                background-color: #1f2937;
                color: #e5e7eb;
                border-color: #3a86ff;
            }
        """)
        self.user_label.clicked.connect(self._on_switch_user)
        sidebar_layout.addWidget(self.user_label)

        sidebar_layout.addSpacing(10)

        # Botón toggle
        self.btn_toggle_sidebar = QPushButton("☰")
        self.btn_toggle_sidebar.setFixedHeight(32)
        self.btn_toggle_sidebar.setStyleSheet("""
            QPushButton {
                background-color: #111827;
                color: #e5e7eb;
                border: none;
                font-size: 18px;
                text-align: left;
                padding-left: 6px;
            }
            QPushButton:hover { background-color: #1f2933; }
        """)
        self.btn_toggle_sidebar.clicked.connect(self.toggle_sidebar)
        sidebar_layout.addWidget(self.btn_toggle_sidebar)

        # Botones principales
        self._create_main_buttons(sidebar_layout)
        
        # Grupos expandibles
        self._create_utilities_group(sidebar_layout)
        self._create_finance_group(sidebar_layout)
        
        # Botones finales
        self._create_bottom_buttons(sidebar_layout)

        # Spacer
        sidebar_layout.addStretch()

        # Widget contenedor con scroll
        sidebar_content = QWidget()
        sidebar_content.setLayout(sidebar_layout)
        
        scroll_area = QScrollArea()
        scroll_area.setWidget(sidebar_content)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #111827;
            }
            QScrollBar:vertical {
                border: none;
                background-color: #1f2933;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #4f46e5;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #6366f1;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        # Layout que contiene el scroll area
        sidebar_main_layout = QVBoxLayout()
        sidebar_main_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_main_layout.addWidget(scroll_area)

        # Sidebar widget principal
        self.sidebar_widget = QFrame()
        self.sidebar_widget.setLayout(sidebar_main_layout)
        self.sidebar_widget.setFixedWidth(self.sidebar_expanded_width)
        self.sidebar_widget.installEventFilter(self)
        self.sidebar_widget.setStyleSheet("""
            QFrame {
                background-color: #111827;
                border-right: 2px solid #374151;
            }
        """)

    def _create_main_buttons(self, layout):
        """Crea los botones principales del menú"""
        self.btn_dashboard = QPushButton("📊 Dashboard")
        self.btn_sales = QPushButton("🛒 Ventas")
        self.btn_products = QPushButton("📦 Productos")
        self.btn_customers = QPushButton("👥 Clientes")

        main_buttons = [
            (self.btn_dashboard, "📊 Dashboard", "📊", lambda: self.show_section("dashboard")),
            (self.btn_sales, "🛒 Ventas", "🛒", lambda: self.show_section("ventas")),
            (self.btn_products, "📦 Productos", "📦", lambda: self.show_section("productos")),
            (self.btn_customers, "👥 Clientes", "👥", lambda: self.show_section("clientes")),
        ]

        for btn, full_text, short_text, callback in main_buttons:
            btn.setText(full_text)
            btn.setToolTip(full_text)
            btn.setStyleSheet(self._MENU_BUTTON_STYLE)
            btn.clicked.connect(callback)
            layout.addWidget(btn)
            self.menu_buttons.append((btn, full_text, short_text))

    def _create_utilities_group(self, layout):
        """Crea el grupo de Utilidades"""
        self.grp_utils = self.make_group_button("Utilidades", "🧰")

        utils_container = QWidget()
        utils_layout = QVBoxLayout(utils_container)
        utils_layout.setContentsMargins(0, 0, 0, 0)

        self.sub_suppliers = self.make_sub_button("🏭 Proveedores")
        self.sub_categories = self.make_sub_button("🗂️ Categorías")
        self.sub_purchases = self.make_sub_button("🧾 Compras / Facturas")
        self.sub_proformas = self.make_sub_button("📋 Proformas")
        self.sub_no_rotation = self.make_sub_button("🕳️ Sin Rotación")

        self.sub_suppliers.clicked.connect(lambda: self.show_section("proveedores"))
        self.sub_categories.clicked.connect(lambda: self.show_section("categorias"))
        self.sub_purchases.clicked.connect(lambda: self.show_section("compras/facturas"))
        self.sub_proformas.clicked.connect(lambda: self.show_section("proformas"))
        self.sub_no_rotation.clicked.connect(lambda: self.show_section("sin_rotacion"))

        utils_layout.addWidget(self.sub_suppliers)
        utils_layout.addWidget(self.sub_categories)
        utils_layout.addWidget(self.sub_purchases)
        utils_layout.addWidget(self.sub_proformas)
        utils_layout.addWidget(self.sub_no_rotation)

        self.sub_einvoice = self.make_sub_button("📋 Facturación Electrónica")
        self.sub_einvoice.clicked.connect(lambda: self.show_section("facturacion_electronica"))
        utils_layout.addWidget(self.sub_einvoice)

        utils_container.hide()

        def toggle_utils():
            if self.grp_utils.isChecked():
                self.grp_utils.setArrowType(Qt.DownArrow)
                utils_container.show()
            else:
                self.grp_utils.setArrowType(Qt.RightArrow)
                utils_container.hide()

        self.grp_utils.clicked.connect(toggle_utils)

        layout.addWidget(self.grp_utils)
        layout.addWidget(utils_container)

    def _create_finance_group(self, layout):
        """Crea el grupo de Finanzas"""
        self.grp_fin = self.make_group_button("Finanzas", "💰")

        fin_container = QWidget()
        fin_layout = QVBoxLayout(fin_container)
        fin_layout.setContentsMargins(0, 0, 0, 0)

        self.sub_analytics = self.make_sub_button("📊 Analíticas")
        self.sub_purchases_analytics = self.make_sub_button("📦 Analítica compras")
        self.sub_report = self.make_sub_button("📊 Registro de ventas")
        self.sub_daily = self.make_sub_button("📅 Reporte del día")
        self.sub_exp = self.make_sub_button("💸 Gastos operativos")
        self.sub_financial = self.make_sub_button("📊 Financiero")

        self.sub_analytics.clicked.connect(lambda: self.show_section("analytics"))
        self.sub_purchases_analytics.clicked.connect(lambda: self.show_section("purchases_analytics"))
        self.sub_report.clicked.connect(lambda: self.show_section("registro_ventas"))
        self.sub_daily.clicked.connect(lambda: self.show_section("reporte_diario"))
        self.sub_exp.clicked.connect(lambda: self.show_section("gastos"))
        self.sub_financial.clicked.connect(lambda: self.show_section("financiero"))

        fin_layout.addWidget(self.sub_analytics)
        fin_layout.addWidget(self.sub_purchases_analytics)
        fin_layout.addWidget(self.sub_report)
        fin_layout.addWidget(self.sub_daily)
        fin_layout.addWidget(self.sub_exp)
        fin_layout.addWidget(self.sub_financial)

        fin_container.hide()

        def toggle_fin():
            if self.grp_fin.isChecked():
                self.grp_fin.setArrowType(Qt.DownArrow)
                fin_container.show()
            else:
                self.grp_fin.setArrowType(Qt.RightArrow)
                fin_container.hide()

        self.grp_fin.clicked.connect(toggle_fin)

        layout.addWidget(self.grp_fin)
        layout.addWidget(fin_container)

    def _create_bottom_buttons(self, layout):
        """Crea los botones de configuración y logout"""
        self.btn_settings = QPushButton("⚙️ Configuración")
        self.btn_logout = QPushButton("🚪 Cerrar sesión")

        bottom_buttons = [
            (self.btn_settings, "⚙️ Configuración", "⚙️", lambda: self.show_section("configuración")),
            (self.btn_logout, "🚪 Cerrar sesión", "🚪", self.logout),
        ]

        for btn, full_text, short_text, callback in bottom_buttons:
            btn.setText(full_text)
            btn.setToolTip(full_text)
            btn.setStyleSheet(self._MENU_BUTTON_STYLE)
            btn.clicked.connect(callback)
            layout.addWidget(btn)
            self.menu_buttons.append((btn, full_text, short_text))

    def _create_content_area(self):
        """Crea el área de contenido principal"""
        self.content_widget = QWidget()
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Contenedor para las vistas
        self.view_container = QWidget()
        self.view_layout = QVBoxLayout(self.view_container)
        self.view_layout.setContentsMargins(0, 0, 0, 0)
        
        # Mensaje inicial
        initial_message = QLabel("Selecciona una opción del menú lateral para comenzar.")
        initial_message.setAlignment(Qt.AlignCenter)
        initial_message.setStyleSheet("font-size: 17px; color: #e5e7eb; margin-top: 100px;")
        self.view_layout.addWidget(initial_message)

        content_layout.addWidget(self.view_container, 1)


    # ==========================================================
    # EVENT FILTER - SIDEBAR HOVER
    # ==========================================================
    def eventFilter(self, obj, event):
        # ── Guard: PySide6 puede pasar QWidgetItem (no QObject) durante
        # operaciones de layout, lo cual crashea super().eventFilter().
        if not isinstance(obj, QObject):
            return False

        # Abrir overlay al entrar al sidebar colapsado
        if obj is self.sidebar_widget and (not self.sidebar_pinned) and (not self.sidebar_in_overlay):
            if event.type() == QEvent.Enter:
                self.sidebar_widget.setFixedWidth(self.sidebar_expanded_width)
                self._update_sidebar_content(collapsed=False)
                self._attach_sidebar_to_overlay()
                return False

        # Cerrar overlay con tracking global (NO usar Leave)
        if (not self.sidebar_pinned) and self.sidebar_in_overlay:
            if event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress):
                #  solo si el evento tiene globalPosition (Qt6)
                if not hasattr(event, "globalPosition"):
                    return super().eventFilter(obj, event)

                cw = self.centralWidget()
                if not cw:
                    return super().eventFilter(obj, event)

                p = cw.mapFromGlobal(event.globalPosition().toPoint())
                x, y = p.x(), p.y()

                # Rect del sidebar overlay
                h = cw.height()
                inside_sidebar = (0 <= x <= self.sidebar_expanded_width) and (0 <= y <= h)

                if not inside_sidebar:
                    self._attach_sidebar_to_base()
                    self.sidebar_widget.setFixedWidth(self.sidebar_collapsed_width)
                    self._update_sidebar_content(collapsed=True)

        return super().eventFilter(obj, event)


    # ==========================================================
    # GESTIÓN DEL SIDEBAR - SIMPLIFICADA
    # ==========================================================
    def toggle_sidebar(self):
        """Alterna entre sidebar fijo/expandido y colapsado"""
        self.sidebar_pinned = not self.sidebar_pinned
        
        if self.sidebar_pinned:
            self._pin_sidebar()
        else:
            self._unpin_sidebar()

    def _unpin_sidebar(self):
        self._attach_sidebar_to_base()
        self.sidebar_widget.setFixedWidth(self.sidebar_collapsed_width)
        self._update_sidebar_content(collapsed=True)

        if not self._hover_tracking_enabled:
            QApplication.instance().installEventFilter(self)
            self._hover_tracking_enabled = True

    def _pin_sidebar(self):
        # Si estaba en overlay, volver a base
        if self.sidebar_in_overlay:
            self._attach_sidebar_to_base()

        self.sidebar_widget.setFixedWidth(self.sidebar_expanded_width)
        self._update_sidebar_content(collapsed=False)

        if self._hover_tracking_enabled:
            QApplication.instance().removeEventFilter(self)
            self._hover_tracking_enabled = False

    def _update_sidebar_content(self, collapsed):
        """Actualiza el contenido del sidebar según su estado"""
        if collapsed:
            self.title_label.hide()
            self.user_label.hide()
            for btn, full_text, short_text in self.menu_buttons:
                btn.setText(short_text)
        else:
            self.title_label.show()
            self.user_label.show()
            for btn, full_text, short_text in self.menu_buttons:
                btn.setText(full_text)

    # ==========================================================
    # PERMISOS GRANULARES (Fase 5)
    # ==========================================================
    def _fetch_user_permissions(self) -> list[str]:
        """Obtiene los permisos del usuario actual desde la API."""
        try:
            from ui.utils.http_worker import api_request
            from ui.api import BASE_URL
            headers = {"Authorization": f"Bearer {session.token}"}
            r = api_request("get", f"{BASE_URL}/users/me", headers=headers, timeout=5)
            if r.status_code == 200:
                return r.json().get("permissions", [])
        except Exception as e:
            logging.warning(f"No se pudieron cargar permisos: {e}")
        return []

    def apply_role_permissions(self):
        """Aplica restricciones de acceso según los permisos granulares del usuario."""
        # Admin siempre tiene acceso total
        if self.role == "admin":
            self.permissions = []  # No necesita lista, tiene todo
            return

        perms = self._fetch_user_permissions()
        self.permissions = perms

        # Mapeo: permiso → botones/widgets que controla
        permission_map = {
            "ver_dashboard":          [self.btn_dashboard],
            "ver_ventas":             [self.btn_sales],
            "ver_productos":          [self.btn_products],
            "ver_clientes":           [self.btn_customers],
            "ver_proveedores":        [self.sub_suppliers],
            "ver_categorias":         [self.sub_categories],
            "ver_compras":            [self.sub_purchases, self.sub_purchases_analytics],
            "ver_proformas":          [self.sub_proformas],
            "ver_reportes":           [self.sub_analytics, self.sub_report,
                                       self.sub_daily, self.sub_no_rotation],
            "ver_gastos":             [self.sub_exp],
            "ver_financiero":         [self.sub_financial],
            "facturacion_electronica": [self.sub_einvoice],
            "acceder_configuracion":  [self.btn_settings],
        }

        for perm, widgets in permission_map.items():
            allowed = perm in perms
            for w in widgets:
                w.setEnabled(allowed)
                w.setVisible(allowed)

        # Si no tiene ningún permiso de finanzas, ocultar el grupo entero
        finance_perms = {"ver_reportes", "ver_gastos", "ver_financiero", "ver_compras"}
        if not finance_perms.intersection(perms):
            self.grp_fin.setVisible(False)
        else:
            self.grp_fin.setVisible(True)

        # Si no tiene ningún permiso de utilidades, ocultar el grupo entero
        utils_perms = {"ver_proveedores", "ver_categorias", "ver_compras",
                       "ver_proformas", "facturacion_electronica"}
        if not utils_perms.intersection(perms):
            self.grp_utils.setVisible(False)
        else:
            self.grp_utils.setVisible(True)

    # ==========================================================
    # CAMBIO DE VISTA - MEJORADO
    # ==========================================================
    def show_section(self, section):
        """Método unificado para navegar entre secciones.
        
        Fix 2.1: Todas las vistas se cachean en la primera visita y se
        reutilizan en visitas posteriores, llamando a su método de recarga
        para refrescar datos sin reconstruir la UI completa.
        """
        try:
            if section == "dashboard":
                self._show_dashboard()
                
            elif section == "productos":
                from ui.views.products_view import ProductsView
                if self._products_view is None:
                    self._products_view = ProductsView()
                else:
                    self._products_view.load_products()
                self.set_view(self._products_view)

            elif section == "clientes":
                from ui.views.customers_view import CustomersView
                if self._customers_view is None:
                    self._customers_view = CustomersView()
                else:
                    self._customers_view.load_customers()
                self.set_view(self._customers_view)

            elif section == "ventas":
                from ui.views.sales_view import SalesView
                if self.sales_view is None:
                    self.sales_view = SalesView()
                else:
                    # Recargar clientes cada vez que volvemos a Ventas
                    self.sales_view.load_customers()

                self.set_view(self.sales_view)

            elif section == "registro_ventas":
                from ui.views.sales_history_view import SalesHistoryView
                if self.sales_history_view is None:
                    self.sales_history_view = SalesHistoryView(parent=self)
                self.set_view(self.sales_history_view)

            elif section == "gastos":
                from ui.views.expenses_view import ExpensesView
                if self._expenses_view is None:
                    self._expenses_view = ExpensesView()
                else:
                    self._expenses_view.load_expenses()
                self.set_view(self._expenses_view)

            elif section == "financiero":
                from ui.views.financial_view import FinancialView
                if self._financial_view is None:
                    self._financial_view = FinancialView()
                else:
                    self._financial_view.load_data()
                self.set_view(self._financial_view)

            elif section == "reporte_diario":
                from ui.views.daily_report_view import DailyReportView
                if self._daily_report_view is None:
                    self._daily_report_view = DailyReportView()
                else:
                    self._daily_report_view.load_report()
                self.set_view(self._daily_report_view)

            elif section == "proveedores":
                from ui.views.suppliers_view import SuppliersView
                if self._suppliers_view is None:
                    self._suppliers_view = SuppliersView(self)
                else:
                    self._suppliers_view.load_suppliers()
                self.set_view(self._suppliers_view)

            elif section == "categorias":
                from ui.views.categories_view import CategoriesView
                if self._categories_view is None:
                    self._categories_view = CategoriesView()
                else:
                    self._categories_view.load_categories()
                self.set_view(self._categories_view)

            elif section == "compras/facturas":
                from ui.views.purchases_view import PurchasesView
                if self._purchases_view is None:
                    self._purchases_view = PurchasesView()
                else:
                    self._purchases_view.load_purchases()
                self.set_view(self._purchases_view)

            elif section == "configuración":
                from ui.views.settings_view import SettingsView
                if self._settings_view is None:
                    self._settings_view = SettingsView(self)
                else:
                    self._settings_view._start_load()
                self.set_view(self._settings_view)

            elif section == "analytics":
                from ui.views.sales_analytics_view import SalesAnalyticsView
                if self._analytics_view is None:
                    self._analytics_view = SalesAnalyticsView()
                else:
                    self._analytics_view.refresh_all()
                self.set_view(self._analytics_view)

            elif section == "purchases_analytics":
                from ui.views.purchases_analytics_view import PurchasesAnalyticsView
                if self._purchases_analytics_view is None:
                    self._purchases_analytics_view = PurchasesAnalyticsView()
                else:
                    self._purchases_analytics_view.refresh_all()
                self.set_view(self._purchases_analytics_view)

            elif section == "proformas":
                from ui.views.proformas_view import ProformasView
                if self._proformas_view is None:
                    self._proformas_view = ProformasView()
                else:
                    self._proformas_view.load_proformas()
                self.set_view(self._proformas_view)

            elif section == "sin_rotacion":
                from ui.views.no_rotation_view import NoRotationView
                if self._no_rotation_view is None:
                    self._no_rotation_view = NoRotationView()
                else:
                    self._no_rotation_view._load_data()
                self.set_view(self._no_rotation_view)

            elif section == "facturacion_electronica":
                from ui.views.einvoice_monitor_view import EinvoiceMonitorView
                if self._einvoice_view is None:
                    self._einvoice_view = EinvoiceMonitorView(self)
                else:
                    self._einvoice_view._load_all()
                self.set_view(self._einvoice_view)

            # Emitir señal de cambio de vista
            self.view_changed.emit(section)

            # FASE 5: Sincronizar contexto de pantalla al chat
            if self.chat_panel:
                self.chat_panel.set_current_screen(section)
                self._sync_cart_to_chat()

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_error_view(f"Error cargando la sección '{section}': {str(e)}")

    def _show_error_view(self, message):
        """Muestra una vista de error"""
        error_label = QLabel(f"❌ {message}")
        error_label.setAlignment(Qt.AlignCenter)
        error_label.setStyleSheet("font-size: 16px; color: #ef4444; margin: 50px;")
        self.set_view(error_label)

    def set_view(self, view_widget, *, destroy_previous: bool = False):
        # 3.5: Verificar cambios sin guardar en la vista actual
        if hasattr(self, 'current_view') and self.current_view is not None:
            if hasattr(self.current_view, 'has_unsaved_changes'):
                if self.current_view.has_unsaved_changes():
                    if not self.current_view.confirm_discard():
                        return  # El usuario canceló la navegación
        # quitar widgets del layout sin destruirlos (por defecto)
        while self.view_layout.count():
            item = self.view_layout.takeAt(0)
            w = item.widget()
            if not w:
                continue

            w.hide()
            w.setParent(None)

            # si explícitamente queremos destruir la vista anterior
            if destroy_previous:
                w.deleteLater()

        self.current_view = view_widget
        self.view_layout.addWidget(view_widget)
        view_widget.show()

        # mantener overlays arriba
        try:
            self._position_floating_chat()
        except Exception:
            pass

    # ==========================================================
    # DASHBOARD
    # ==========================================================
    def _show_dashboard(self):
        """Muestra la vista del dashboard (se crea una sola vez y se reutiliza)"""
        try:
            from ui.views.dashboard_view import DashboardView
            if self.dashboard_view is None:
                self.dashboard_view = DashboardView()
                self.dashboard_view.alert_clicked.connect(self.handle_dashboard_alert)
            self.set_view(self.dashboard_view)
        except Exception as e:
            self._show_error_view(f"Error cargando dashboard: {str(e)}")

    # ==========================================================
    # NAVEGACIÓN INTELIGENTE DESDE DASHBOARD
    # ==========================================================
    def handle_dashboard_alert(self, alert: dict):
        """Maneja los clicks en las alertas del dashboard y navega a la sección correspondiente.

        Orden de resolución:
          1. meta["action"]  → navegación precisa y explícita
          2. alert["type"]   → fallback genérico para alertas sin acción
        """
        from ui.components.toast_notifier import show_toast

        alert_type  = alert.get("type")
        reference   = alert.get("reference")
        root_action = alert.get("action")
        meta        = alert.get("meta") or {}
        action      = meta.get("action") or root_action

        # ------------------------------------------------------------------
        # PASO 12 — Priorizar meta["action"], con fallback a alert["action"]
        # ------------------------------------------------------------------
        if action == "open_supplier_products":
            show_toast("🏭 Abriendo productos del proveedor...", success=True, parent=self)
            self.go_to_supplier(
                supplier_id=reference,
                supplier_name=meta.get("supplier_name"),
                action=action,
            )

        elif action == "open_supplier_purchases":
            show_toast("🏭 Abriendo compras del proveedor...", success=True, parent=self)
            self.go_to_supplier(
                supplier_id=reference,
                supplier_name=meta.get("supplier_name"),
                action=action,
            )

        elif action == "open_customer_credit":
            show_toast("👥 Navegando a crédito del cliente...", success=True, parent=self)
            self.go_to_credits(customer_id=reference)

        elif action == "open_credit_ranking":
            show_toast("💳 Navegando a créditos...", success=True, parent=self)
            self.go_to_credits()

        elif action == "open_product":
            show_toast("📦 Abriendo productos con stock bajo...", success=True, parent=self)
            self.go_to_low_stock_products()

        elif action == "open_low_stock":
            show_toast("📦 Filtrando productos con stock bajo...", success=True, parent=self)
            self.go_to_low_stock_products()

        elif action == "open_cash":
            show_toast("💰 Navegando a caja...", success=True, parent=self)
            self.go_to_cash()

        elif action == "open_sales_history":
            show_toast("📊 Navegando a ventas del día...", success=True, parent=self)
            today = date.today().isoformat()
            self.go_to_sales_reports(start_date=today, end_date=today)

        # ------------------------------------------------------------------
        # Quick actions del dashboard (alert["action"] a nivel raíz)
        # ------------------------------------------------------------------
        elif action == "go_sales":
            show_toast("🛒 Navegando a ventas...", success=True, parent=self)
            self.show_section("ventas")

        elif action == "go_purchases":
            show_toast("🧾 Navegando a compras...", success=True, parent=self)
            self.show_section("compras/facturas")

        elif action == "go_low_stock":
            show_toast("📦 Filtrando productos con stock bajo...", success=True, parent=self)
            self.go_to_low_stock_products()

        elif action == "go_credits":
            show_toast("💳 Navegando a créditos...", success=True, parent=self)
            self.go_to_credits()

        elif action == "close_cash":
            show_toast("💰 Abriendo cierre de caja...", success=True, parent=self)
            self.go_to_cash()
            def _open_close_dialog():
                sv = getattr(self, "sales_view", None)
                if sv and hasattr(sv, "open_close_cash_dialog"):
                    sv.open_close_cash_dialog()
            QTimer.singleShot(300, _open_close_dialog)

        # ------------------------------------------------------------------
        # Fallback por type (alertas sin meta["action"])
        # ------------------------------------------------------------------
        else:
            fallback_toasts = {
                "stock":    "📦 Navegando a productos...",
                "credit":   "👥 Navegando a clientes...",
                "cash":     "💰 Navegando a caja...",
                "sales":    "📊 Navegando a ventas del día...",
                "supplier": "🏭 Navegando a proveedores...",
            }
            if alert_type in fallback_toasts:
                show_toast(fallback_toasts[alert_type], success=True, parent=self)

            if alert_type == "stock":
                self.go_to_low_stock_products()
            elif alert_type == "credit":
                self.go_to_credits(customer_id=reference)
            elif alert_type == "cash":
                self.go_to_cash()
            elif alert_type == "sales":
                today = date.today().isoformat()
                self.go_to_sales_reports(start_date=today, end_date=today)
            elif alert_type == "supplier":
                self.go_to_supplier(
                    supplier_id=reference,
                    supplier_name=meta.get("supplier_name"),
                    action=meta.get("action"),
                )

    def go_to_products(self, product_id=None, filter: str | None = None, threshold: int | None = None):
        """Navega a la vista de productos"""
        try:
            from ui.views.products_view import ProductsView
            products_view = ProductsView()
            self.set_view(products_view)

            # foco por id (ya lo tenías)
            if product_id:
                QTimer.singleShot(100, lambda: self._focus_product(products_view, product_id))

            # ✅ filtro stock bajo
            if filter == "low_stock":
                # tu ProductsView ya filtra <=3 en apply_filter_low_stock()
                QTimer.singleShot(150, products_view.apply_filter_low_stock)

        except Exception as e:
            logging.error(f"Error navegando a productos: {e}")

    def go_to_low_stock_products(self):
        """Navega a productos y aplica el filtro de stock bajo automáticamente."""
        self.go_to_products(filter="low_stock")

    def go_to_credits(self, customer_id=None, query: str | None = None):
        """Navega a la vista de clientes"""
        try:
            from ui.views.customers_view import CustomersView
            customers_view = CustomersView()
            self.set_view(customers_view)

            # 1) si viene por ID, mantenemos tu comportamiento actual
            if customer_id:
                def _focus_and_open_credit():
                    self._focus_customer(customers_view, customer_id)
                    if hasattr(customers_view, "manage_credit"):
                        customers_view.manage_credit()

                QTimer.singleShot(150, _focus_and_open_credit)
                return

            # 2) si viene por texto (nombre/correo), usamos el search_input + search_customer()
            if query:
                q = query.strip()
                def _apply_search_and_select():
                    # CustomersView tiene search_input y search_customer()
                    customers_view.search_input.setText(q)
                    customers_view.search_customer()

                    result = self._select_first_visible_customer_match(customers_view, q)

                    # Mensaje pro en el chat (si existe el panel flotante)
                    try:
                        if self.chat_panel and result.get("count", 0) > 0:
                            sel = result.get("selected_name") or result.get("selected_email") or q
                            n = result.get("count")
                            if n == 1:
                                msg = f"Encontré 1 coincidencia; seleccioné **{sel}**."
                            else:
                                msg = f"Encontré {n} coincidencias; seleccioné **{sel}**."
                            self.chat_panel.append_ai(msg)
                    except Exception:
                        pass

                QTimer.singleShot(120, _apply_search_and_select)

        except Exception as e:
            logging.error(f"Error navegando a clientes: {e}")

    def go_to_cash(self):
        """Navega a la caja operativa (SalesView)"""
        try:
            from ui.views.sales_view import SalesView
            sales_view = SalesView(self)
            self.set_view(sales_view)
            self.sales_view = sales_view
        except Exception as e:
            logging.error(f"Error navegando a caja: {e}")

    def go_to_sales_reports(self, start_date=None, end_date=None, period=None):
        """Navega al registro de ventas y (opcional) aplica filtro de fechas"""
        try:
            from ui.views.sales_history_view import SalesHistoryView
            if self.sales_history_view is None:
                self.sales_history_view = SalesHistoryView(parent=self)
            self.set_view(self.sales_history_view)

            if start_date and end_date:
                # esperar a que la vista termine de montar
                QTimer.singleShot(100, lambda: self.sales_history_view.apply_date_range(start_date, end_date))

        except Exception as e:
            logging.error(f"Error navegando a registro de ventas: {e}")

    def go_to_supplier(self, supplier_id=None, supplier_name=None, action=None):
        """Navega a Proveedores y opcionalmente abre Productos o Compras del proveedor."""
        try:
            from ui.views.suppliers_view import SuppliersView
            suppliers_view = SuppliersView(self)
            self.set_view(suppliers_view)

            def _focus_and_act():
                # 1) Filtrar por nombre para que aparezca en la tabla
                if supplier_name:
                    suppliers_view.search_input.setText(supplier_name)

                # 2) Seleccionar la fila por supplier_id
                if supplier_id:
                    self._select_row_by_id(suppliers_view.table, supplier_id, id_column=0)

                # 3) Ejecutar acción específica según meta.action
                if action == "open_supplier_products":
                    if hasattr(suppliers_view, "open_restock_view"):
                        suppliers_view.open_restock_view()
                elif action == "open_supplier_purchases":
                    if hasattr(suppliers_view, "open_purchases_view"):
                        suppliers_view.open_purchases_view()

            QTimer.singleShot(200, _focus_and_act)

        except Exception as e:
            logging.error(f"Error navegando a proveedor: {e}")

    

    # ==========================================================
    # MÉTODOS AUXILIARES DE NAVEGACIÓN
    # ==========================================================
    def _focus_product(self, products_view, product_id):
        """Enfoca un producto específico en la vista"""
        if hasattr(products_view, 'focus_product'):
            products_view.focus_product(product_id)
        elif hasattr(products_view, 'search_by_id'):
            products_view.search_by_id(product_id)
        elif hasattr(products_view, 'table'):
            self._select_row_by_id(products_view.table, product_id, id_column=0)

    def _focus_customer(self, customers_view, customer_id):
        """Enfoca un cliente específico en la vista"""
        if hasattr(customers_view, 'focus_customer'):
            customers_view.focus_customer(customer_id)
        elif hasattr(customers_view, 'search_by_id'):
            customers_view.search_by_id(customer_id)
        elif hasattr(customers_view, 'table'):
            self._select_row_by_id(customers_view.table, customer_id, id_column=0)

    def _select_row_by_id(self, table, target_id, id_column=0):
        """Busca y selecciona una fila en una tabla por ID"""
        try:
            for row in range(table.rowCount()):
                item = table.item(row, id_column)
                if item and str(item.text()) == str(target_id):
                    table.selectRow(row)
                    table.scrollToItem(item)
                    break
        except Exception as e:
            logging.error(f"Error seleccionando fila: {e}")

    def _select_first_visible_customer_match(self, customers_view, q: str) -> dict:
        """
        Selecciona cliente por ranking para queries cortos:
        1) exact (nombre/correo == query)
        2) startswith (prioriza nombre)
        3) token-prefix (palabras del query son prefijo de palabras del nombre)
        4) contains
        Retorna: {count, selected_name, selected_email, exact, score}
        """
        table = getattr(customers_view, "table", None)
        if table is None:
            return {"count": 0, "selected_name": None, "selected_email": None, "exact": False, "score": None}

        def norm(s: str) -> str:
            return " ".join((s or "").strip().lower().split())

        qn = norm(q)
        if not qn:
            return {"count": 0, "selected_name": None, "selected_email": None, "exact": False, "score": None}

        q_tokens = qn.split()

        candidates = []
        # columnas: ID=0, Nombre=1, Correo=2
        for row in range(table.rowCount()):
            if table.isRowHidden(row):
                continue

            name_item = table.item(row, 1)
            email_item = table.item(row, 2)

            name_raw = name_item.text() if name_item else ""
            email_raw = email_item.text() if email_item else ""

            name = norm(name_raw)
            email = norm(email_raw)

            # scoring (más alto = mejor)
            score = 0
            exact = False

            # 1) exact match
            if name == qn or email == qn:
                score = 1000
                exact = True
            else:
                # 2) startswith (nombre vale más)
                if name.startswith(qn):
                    score = max(score, 900)
                if email.startswith(qn):
                    score = max(score, 850)

                # 3) token-prefix match:
                # ej: q="rand vill" -> nombre "randall villagra galeano"
                if q_tokens:
                    name_words = name.split()
                    email_words = email.split()

                    def token_prefix_match(qtoks, words):
                        # todos los tokens del query deben matchear prefijos en orden (no necesariamente misma longitud)
                        if len(words) < len(qtoks):
                            return False
                        for i, t in enumerate(qtoks):
                            if not words[i].startswith(t):
                                return False
                        return True

                    if token_prefix_match(q_tokens, name_words):
                        score = max(score, 800)
                    if token_prefix_match(q_tokens, email_words):
                        score = max(score, 760)

                # 4) contains (nombre vale más)
                if qn in name:
                    score = max(score, 700)
                if qn in email:
                    score = max(score, 650)

                # micro-bonus: mientras más cerca del inicio, mejor
                if score in (700, 650):  # contains
                    try:
                        idx_name = name.find(qn)
                        idx_email = email.find(qn)
                        if idx_name >= 0:
                            score += max(0, 40 - idx_name) * 0.5  # bonus suave
                        if idx_email >= 0:
                            score += max(0, 30 - idx_email) * 0.3
                    except Exception:
                        pass

            candidates.append((score, exact, row, name_item, email_item, name_raw, email_raw))

        count = len(candidates)
        if count == 0:
            return {"count": 0, "selected_name": None, "selected_email": None, "exact": False, "score": None}

        # elegir mejor score; en empate: fila más arriba (menor row)
        candidates.sort(key=lambda x: (-x[0], x[2]))
        best_score, best_exact, best_row, _, _, best_name_raw, best_email_raw = candidates[0]

        table.selectRow(best_row)
        name_item = table.item(best_row, 1)
        if name_item:
            table.scrollToItem(name_item)

        selected_name = best_name_raw or (name_item.text() if name_item else None)
        selected_email = best_email_raw or ((table.item(best_row, 2).text()) if table.item(best_row, 2) else None)

        return {
            "count": count,
            "selected_name": selected_name,
            "selected_email": selected_email,
            "exact": bool(best_exact),
            "score": best_score,
        }
    # ==========================================================
    # FASE 5: Sincronización de contexto al chat
    # ==========================================================
    def _sync_cart_to_chat(self):
        """Sincroniza el estado del carrito real al ChatPanel."""
        if not self.chat_panel:
            return

        sv = getattr(self, "sales_view", None)
        if sv is None:
            return

        cart = getattr(sv, "cart", {})
        if not cart:
            self.chat_panel.update_cart_context({
                "items": [], "total": 0.0, "count": 0,
                "customer_name": None, "customer_id": None,
                "payment_method": None,
            })
            return

        items = []
        total = 0.0
        for pid, item in cart.items():
            product = item.get("product", {})
            qty = int(item.get("quantity", 0))
            unit_price = float(item.get("unit_price", 0))
            discount = float(item.get("discount_percent", 0))
            subtotal = unit_price * qty * (1 - discount / 100)
            total += subtotal
            items.append({
                "product_id": int(pid),
                "product_name": product.get("name", ""),
                "quantity": qty,
                "unit_price": unit_price,
                "discount_percent": discount,
                "subtotal": round(subtotal, 2),
            })

        # Customer
        customer_name = None
        customer_id = getattr(sv, "selected_customer_id", None)
        if customer_id and hasattr(sv, "customer_search"):
            customer_name = sv.customer_search.text().strip() or None

        # Payment
        payment_method = None
        if hasattr(sv, "payment_combo"):
            payment_method = sv.payment_combo.currentText() or None

        self.chat_panel.update_cart_context({
            "items": items,
            "total": round(total, 2),
            "count": len(items),
            "customer_name": customer_name,
            "customer_id": customer_id,
            "payment_method": payment_method,
        })

    # ==========================================================
    # CHAT PANEL HANDLER
    # ==========================================================
    def handle_chat_action(self, action_data):
        """Maneja las acciones solicitadas desde el chat panel"""
        from ui.components.toast_notifier import show_toast

        action_type = (action_data or {}).get("type")

        # Soporta: payload (nuevo), params (alterno), y fallback a raíz (viejo)
        payload = (action_data or {}).get("payload") or (action_data or {}).get("params") or {}
        if not isinstance(payload, dict):
            payload = {}

        # Helpers robustos
        def _get_int(*keys, default=None):
            for k in keys:
                v = payload.get(k)
                if v is None:
                    v = (action_data or {}).get(k)  # fallback a root
                if v is None:
                    continue
                try:
                    return int(v)
                except Exception:
                    continue
            return default

        def _get_str(*keys, default=None):
            for k in keys:
                v = payload.get(k)
                if v is None:
                    v = (action_data or {}).get(k)
                if v is None:
                    continue
                return str(v)
            return default

        try:
            from datetime import date, timedelta
            # -------------------------------------------------
            # COMPAT: acciones viejas del backend (chat.py)
            # -------------------------------------------------
            if action_type == "open_sales_day_report":
                # "ventas hoy" debe abrir Reporte del día
                self.show_section("reporte_diario")
                show_toast("📅 Abriendo reporte del día", success=True, parent=self)
                return

            if action_type == "open_sales_history":
                scope = _get_str("scope", default="week")  # "week" / "month" / etc.
                today = date.today()

                if scope == "week":
                    start = today - timedelta(days=today.weekday())  # lunes
                    end = today
                elif scope == "month":
                    start = today.replace(day=1)
                    end = today
                else:
                    # fallback seguro
                    start = today
                    end = today

                self.go_to_sales_reports(
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    period=scope
                )
                show_toast("📊 Abriendo registro de ventas", success=True, parent=self)
                return

            # ---------------------------
            # NAVIGATE (nuevo)
            # ---------------------------
            if action_type == "navigate":
                module = _get_str("module")

                if module == "daily_report":
                    self.show_section("reporte_diario")
                    show_toast("📅 Abriendo reporte del día", success=True, parent=self)
                    return

                if module == "sales_reports":
                    start_date = _get_str("start_date")
                    end_date = _get_str("end_date")
                    period = _get_str("period")  # week / month (opcional)
                    self.go_to_sales_reports(start_date=start_date, end_date=end_date, period=period)
                    show_toast("📊 Abriendo registro de ventas", success=True, parent=self)
                    return

                if module == "products":
                    product_id = _get_int("product_id")
                    filt = _get_str("filter")         # "low_stock"
                    threshold = _get_int("threshold") # opcional
                    self.go_to_products(product_id=product_id, filter=filt, threshold=threshold)
                    show_toast("📦 Navegando a productos", success=True, parent=self)
                    return

                if module == "customers":
                    customer_id = _get_int("customer_id")
                    query = _get_str("query", "name", "customer_name")
                    self.go_to_credits(customer_id=customer_id, query=query)
                    show_toast("👥 Navegando a clientes", success=True, parent=self)
                    return

                if module == "dashboard":
                    self.show_section("dashboard")
                    show_toast("📊 Navegando a dashboard", success=True, parent=self)
                    return

                if module == "analytics":
                    self.show_section("analytics")
                    show_toast("📊 Abriendo analíticas", success=True, parent=self)
                    return

                # ─── FASE 3: Navegación genérica por section ───
                # Si el action trae un campo "section", usarlo directamente
                section = _get_str("section")
                if section:
                    try:
                        self.show_section(section)
                        show_toast(f"🧭 Navegando a {section}", success=True, parent=self)
                    except Exception:
                        show_toast(f"⚠️ No se pudo abrir '{section}'", success=False, parent=self)
                    return

                # ─── Mapeo genérico module → section (fallback) ───
                _module_to_section = {
                    "sales": "ventas",
                    "sales_history": "registro_ventas",
                    "products": "productos",
                    "customers": "clientes",
                    "expenses": "gastos",
                    "cash": "reporte_diario",
                    "daily_report": "reporte_diario",
                    "suppliers": "proveedores",
                    "purchases": "compras/facturas",
                    "categories": "categorias",
                    "financial_reports": "financiero",
                    "settings": "configuración",
                    "credits": "clientes",
                    "no_rotation": "sin_rotacion",
                    "purchases_analytics": "purchases_analytics",
                }
                fallback_section = _module_to_section.get(module)
                if fallback_section:
                    try:
                        self.show_section(fallback_section)
                        show_toast(f"🧭 Navegando a {fallback_section}", success=True, parent=self)
                    except Exception:
                        show_toast(f"⚠️ No se pudo abrir '{module}'", success=False, parent=self)
                    return

                show_toast(f"⚠️ Módulo '{module}' no implementado", success=False, parent=self)
                return

            # ---------------------------
            # OPEN PRODUCT
            # ---------------------------
            elif action_type == "open_product":
                product_id = _get_int("product_id")
                if product_id is not None:
                    self.go_to_products(product_id=product_id)
                    show_toast(f"📦 Abriendo producto #{product_id}", success=True, parent=self)
                else:
                    show_toast("⚠️ ID de producto no especificado", success=False, parent=self)
                return

            # ---------------------------
            # ADD TO CART
            # ---------------------------
            elif action_type == "add_to_cart":
                product_id = _get_int("product_id")
                qty = _get_int("quantity", "qty", default=1)  # ✅ acepta ambos
                if qty < 1:
                    qty = 1

                if product_id is not None:
                    self.go_to_sales_and_add(product_id=product_id, qty=qty)
                    try:
                        self._chat_cart_history.append((int(product_id), int(qty)))
                    except Exception:
                        pass
                    show_toast(f"🛒 Agregando {qty}x producto #{product_id} al carrito", success=True, parent=self)
                else:
                    show_toast("⚠️ ID de producto no especificado", success=False, parent=self)
                return


            elif action_type == "undo_last":
                self.go_to_sales_and_undo_last()
                show_toast("↩️ Deshaciendo el último ítem", success=True, parent=self)
                return

            elif action_type == "set_customer":
                name = _get_str("name")
                if name:
                    self.go_to_sales_and_set_customer(name=name)
                    show_toast(f"👤 Cliente: {name}", success=True, parent=self)
                else:
                    show_toast("⚠️ No vino el nombre del cliente", success=False, parent=self)
                return

            elif action_type == "set_payment_method":
                method = _get_str("method")
                if method:
                    self.go_to_sales_and_set_payment_method(method=method)
                    show_toast(f"💳 Método de pago: {method}", success=True, parent=self)
                else:
                    show_toast("⚠️ No vino el método de pago", success=False, parent=self)
                return

            elif action_type == "remove_from_cart_by_name":
                name = _get_str("name")
                if name:
                    self.go_to_sales_and_remove_by_name(name=name)
                    show_toast(f"🗑 Quitando: {name}", success=True, parent=self)
                else:
                    show_toast("⚠️ No vino el nombre del producto a quitar", success=False, parent=self)
                return

            elif action_type == "decrement_from_cart_by_name":
                name = _get_str("name")
                qty = _get_int("qty", default=1)
                if name:
                    self.go_to_sales_and_decrement_by_name(name=name, qty=qty)
                else:
                    show_toast("⚠️ No vino el nombre del producto a quitar", success=False, parent=self)
                return

            # ---------------------------
            # PREVIEW CONFIRM SALE (nuevo: mostrar resumen sin confirmar)
            # ---------------------------
            elif action_type == "preview_confirm_sale":
                # Solo mostrar resumen, NO confirmar la venta
                self.show_section("ventas")
                QTimer.singleShot(150, self._show_sale_summary)
                show_toast("🧾 Revisá el resumen de la venta", success=True, parent=self)
                return

            # ---------------------------
            # CONFIRM SALE (confirmar después del resumen)
            # ---------------------------
            elif action_type in ("confirm_sale", "confirm_sale_no_print", "confirm_sale_print", "confirm_sale_cancel"):
                mode_map = {
                    "confirm_sale": None,
                    "confirm_sale_no_print": "no_print",
                    "confirm_sale_print": "print",
                    "confirm_sale_cancel": "cancel",
                }
                self.go_to_sales_and_confirm(auto_action=mode_map.get(action_type))
                show_toast("✅ Confirmando venta", success=True, parent=self)
                return

            # ---------------------------
            # COMPAT: formatos antiguos
            # ---------------------------
            elif action_type == "navigate_to_products":
                product_id = _get_int("product_id")
                self.go_to_products(product_id=product_id)
                show_toast("📦 Navegando a productos", success=True, parent=self)
                return

            elif action_type == "navigate_to_customers":
                customer_id = _get_int("customer_id")
                self.go_to_credits(customer_id=customer_id)
                show_toast("👥 Navegando a clientes", success=True, parent=self)
                return

            elif action_type == "navigate_to_sales":
                self.go_to_sales_reports()
                show_toast("🛒 Navegando a ventas", success=True, parent=self)
                return

            elif action_type == "navigate_to_dashboard":
                self.show_section("dashboard")
                show_toast("📊 Navegando a dashboard", success=True, parent=self)
                return

            elif action_type == "navigate_to_settings":
                self.show_section("configuración")
                show_toast("⚙️ Navegando a configuración", success=True, parent=self)
                return

            else:
                show_toast(f"⚠️ Acción '{action_type}' no implementada", success=False, parent=self)
                return

        except Exception as e:
            logging.error(f"Error manejando acción del chat: {e}")
            import traceback
            traceback.print_exc()
            show_toast(f"❌ Error: {str(e)}", success=False, parent=self)

        # FASE 5: Sincronizar contexto del carrito después de cualquier acción
        QTimer.singleShot(300, self._sync_cart_to_chat)

        

    # ==========================================================
    # LOGOUT
    # ==========================================================
    # ==========================================================
    # CAMBIO DE USUARIO (Fase 4)
    # ==========================================================
    def _on_switch_user(self):
        """Abre el diálogo de login para cambiar de usuario/cajero."""
        from ui.reauth_dialog import LoginDialog
        from ui.components.toast_notifier import show_toast
        from app.core.security import decode_token

        dlg = LoginDialog()
        dlg.setWindowTitle("Cambiar de usuario")

        if dlg.exec() == QDialog.Accepted and dlg.token:
            token = dlg.token
            payload = decode_token(token)
            if not payload:
                show_toast("❌ Token inválido", success=False, parent=self)
                return

            new_username = payload.get("sub", "")
            new_role = payload.get("role", "vendedor")

            # Actualizar sesión global
            session.start_session(new_username, new_role, token)

            # Actualizar estado interno
            self.username = new_username
            self.role = new_role

            # Actualizar botón del sidebar
            self.user_label.setText(f"👤 {new_username} ({new_role})")

            # Re-habilitar y mostrar todos los botones antes de re-aplicar permisos
            all_permission_widgets = [
                self.btn_dashboard, self.btn_sales, self.btn_products,
                self.btn_customers, self.btn_settings,
                self.sub_suppliers, self.sub_categories, self.sub_purchases,
                self.sub_proformas, self.sub_no_rotation, self.sub_einvoice,
                self.sub_analytics, self.sub_purchases_analytics,
                self.sub_report, self.sub_daily, self.sub_exp, self.sub_financial,
                self.grp_utils, self.grp_fin,
            ]
            for w in all_permission_widgets:
                w.setEnabled(True)
                w.setVisible(True)

            self.apply_role_permissions()

            # Limpiar la vista de ventas cacheada para forzar recarga
            self.sales_view = None

            # Volver al dashboard
            self.show_section("ventas")

            show_toast(
                f"✅ Sesión cambiada a: {new_username} ({new_role})",
                success=True,
                parent=self,
            )

    def logout(self):
        """Cierra la sesión actual y vuelve al login"""
        from ui.login_view import LoginWindow
        from ui.components.toast_notifier import show_toast
        from PySide6.QtWidgets import QApplication

        msg = QMessageBox(self)
        msg.setWindowTitle("Cerrar sesión")
        msg.setText("¿Deseas cerrar la sesión actual y volver al inicio?")
        msg.setIcon(QMessageBox.Question)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)

        if msg.exec() == QMessageBox.Yes:
            # Limpiar sesión
            session.end_session()

            show_toast("✅ Sesión cerrada correctamente", success=True, parent=self)

            # ──────────────────────────────────────────────────────────
            # FIX CRÍTICO: cleanup de event filters globales antes de
            # destruir MainWindow.
            #
            # Tanto MainWindow como SalesView instalan event filters
            # globales en QApplication (para hover tracking del sidebar
            # y para mantener foco en barra de búsqueda respectivamente).
            # Si se hace deleteLater() sin remover esos filters, Qt
            # sigue invocándolos en widgets C++ destruidos, produciendo
            # un Windows fatal exception: access violation cuando el
            # usuario hace login de nuevo o interactúa con la app.
            # ──────────────────────────────────────────────────────────
            self._cleanup_before_destruction()

            # Abrir ventana de login
            self.login_window = LoginWindow()
            self.login_window.show()

            QApplication.processEvents()

            # Cerrar ventana principal
            self.close()
            self.deleteLater()
        else:
            show_toast("⏎ Cancelado", success=False, parent=self)

    def _cleanup_before_destruction(self):
        """
        Limpia event filters globales y libera recursos antes de que
        MainWindow se destruya (deleteLater).

        Es defensivo: cada paso se envuelve en try/except porque se
        ejecuta durante un flow de destrucción y no debe propagar
        excepciones que podrían cancelar el cleanup.
        """
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return

        # 1. Remover el event filter de MainWindow (instalado en _unpin_sidebar)
        try:
            if getattr(self, "_hover_tracking_enabled", False):
                app.removeEventFilter(self)
                self._hover_tracking_enabled = False
        except Exception:
            pass

        # 2. Hacer cleanup en TODAS las views del stacked widget.
        # Cada view puede tener su propio cleanup (ej. SalesView removeEventFilter).
        try:
            if hasattr(self, "stacked"):
                for i in range(self.stacked.count()):
                    widget = self.stacked.widget(i)
                    if widget is None:
                        continue
                    # Llamar closeEvent manualmente para gatillar el cleanup
                    # de la view (que remueve sus event filters globales).
                    try:
                        widget.close()
                    except Exception:
                        pass
                    # También llamar _cleanup_global_event_filter si existe,
                    # como red de seguridad por si closeEvent no se invocó.
                    if hasattr(widget, "_cleanup_global_event_filter"):
                        try:
                            widget._cleanup_global_event_filter()
                        except Exception:
                            pass
        except Exception:
            pass
            
    def _ensure_placeholder(self):
        if self.sidebar_placeholder is None:
            self.sidebar_placeholder = QWidget()
            self.sidebar_placeholder.setFixedWidth(self.sidebar_collapsed_width)
            self.sidebar_placeholder.setStyleSheet("background: transparent;")

    def _attach_sidebar_to_base(self):
        """Vuelve el sidebar al layout base (push)"""
        if not self.base_layout:
            return

        # Si estaba en overlay, sacarlo
        if self.sidebar_in_overlay:
            self.sidebar_widget.setParent(self.base_widget)
            self.overlay_container.update()

        # Reemplazar placeholder por sidebar en el layout base
        idx_ph = self.base_layout.indexOf(self.sidebar_placeholder) if self.sidebar_placeholder else -1
        if idx_ph != -1:
            self.base_layout.removeWidget(self.sidebar_placeholder)
            self.base_layout.insertWidget(0, self.sidebar_widget, 0)
        else:
            # Asegurar que el sidebar esté como primer widget
            if self.base_layout.indexOf(self.sidebar_widget) == -1:
                self.base_layout.insertWidget(0, self.sidebar_widget, 0)

        self.sidebar_in_overlay = False
        self.sidebar_widget.show()
        self.base_widget.update()

    def _attach_sidebar_to_overlay(self):
        """Saca el sidebar del layout y lo pone arriba como overlay (NO empuja)"""
        if not self.base_layout or not self.root_widget:
            return

        self._ensure_placeholder()

        # Reemplazar sidebar por placeholder en el layout base
        idx_sb = self.base_layout.indexOf(self.sidebar_widget)
        if idx_sb != -1:
            self.base_layout.removeWidget(self.sidebar_widget)
            if self.base_layout.indexOf(self.sidebar_placeholder) == -1:
                self.base_layout.insertWidget(0, self.sidebar_placeholder, 0)

        # ✅ Poner el sidebar como hijo del root_widget (NO del overlay_container)
        self.sidebar_widget.setParent(self.root_widget)
        self.sidebar_widget.raise_()
        self.sidebar_widget.show()

        # Geometría overlay
        cw = self.centralWidget()
        h = cw.height() if cw else self.height()
        self.sidebar_widget.setGeometry(0, 0, self.sidebar_expanded_width, h)

        self.sidebar_in_overlay = True
        
    def _create_floating_chat(self):
        # Panel flotante (contenedor)
        self.chat_overlay = QFrame(self.root_widget)
        self.chat_overlay.setObjectName("ChatOverlay")
        self.chat_overlay.setStyleSheet("""
            QFrame#ChatOverlay {
                background-color: #0b1220;
                border: 1px solid #374151;
                border-radius: 16px;
            }
        """)
        self.chat_overlay.setFixedSize(420, 520)
        self.chat_overlay.hide()

        overlay_layout = QVBoxLayout(self.chat_overlay)
        overlay_layout.setContentsMargins(10, 10, 10, 10)
        overlay_layout.setSpacing(8)

        # Header mini (opcional, pero útil)
        header = QHBoxLayout()
        title = QLabel("💜 Violette")
        title.setStyleSheet("font-size: 14px; color: #e5e7eb; font-weight: 600;")
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(28, 28)
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #9ca3af;
                font-size: 14px;
            }
            QPushButton:hover { color: #fff; }
        """)
        btn_close.clicked.connect(self.hide_chat_overlay)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(btn_close)
        overlay_layout.addLayout(header)

        # Tu ChatPanel real
        self.chat_panel = ChatPanel(self.chat_overlay)
        self.chat_panel.action_requested.connect(self.handle_chat_action)
        overlay_layout.addWidget(self.chat_panel, 1)

        # Botón flotante (draggable)
        self.chat_fab = DraggableFabButton(
            "💬",
            self.root_widget,
            on_click=self.toggle_chat_overlay,
            on_moved=lambda: setattr(self, "_fab_user_moved", True),
            on_drag=lambda: (self._sync_chat_overlay_to_fab() if self.chat_overlay.isVisible() else None)
        )
        self.chat_fab.setFixedSize(56, 56)
        self.chat_fab.setStyleSheet("""
            QPushButton {
                background-color: #4f46e5;
                color: white;
                border: none;
                border-radius: 28px;
                font-size: 22px;
            }
            QPushButton:hover { background-color: #6366f1; }
            QPushButton:pressed { background-color: #4338ca; }
        """)

        # Posicionar por primera vez
        self._position_floating_chat()

    def _position_floating_chat(self):
        if not self.root_widget:
            return

        margin = 18
        cw = self.centralWidget() or self
        w = cw.width()
        h = cw.height()

        # 1) Botón: solo pegarlo a la esquina si el usuario NO lo movió
        if not getattr(self, "_fab_user_moved", False):
            self.chat_fab.move(
                w - self.chat_fab.width() - margin,
                h - self.chat_fab.height() - margin
            )
        else:
            # clamp por si el resize lo deja fuera
            x = min(self.chat_fab.x(), w - self.chat_fab.width() - 1)
            y = min(self.chat_fab.y(), h - self.chat_fab.height() - 1)
            self.chat_fab.move(max(0, x), max(0, y))

        # 2) Panel: anclado al botón (encima)
        fab_x = self.chat_fab.x()
        fab_y = self.chat_fab.y()

        panel_x = fab_x + self.chat_fab.width() - self.chat_overlay.width()
        panel_y = fab_y - self.chat_overlay.height() - 10

        # clamp panel
        panel_x = max(margin, min(panel_x, w - self.chat_overlay.width() - margin))
        panel_y = max(margin, min(panel_y, h - self.chat_overlay.height() - margin))

        self.chat_overlay.move(panel_x, panel_y)
        self.chat_overlay.raise_()
        self.chat_fab.raise_()

    def _sync_chat_overlay_to_fab(self):
        """Mueve el panel del chat encima de la burbuja (posición actual)."""
        if not self.chat_overlay or not self.chat_fab:
            return

        cw = self.centralWidget() or self
        w = cw.width()
        h = cw.height()
        margin = 18

        fab_x = self.chat_fab.x()
        fab_y = self.chat_fab.y()

        panel_x = fab_x + self.chat_fab.width() - self.chat_overlay.width()
        panel_y = fab_y - self.chat_overlay.height() - 10

        # clamp panel a la ventana
        panel_x = max(margin, min(panel_x, w - self.chat_overlay.width() - margin))
        panel_y = max(margin, min(panel_y, h - self.chat_overlay.height() - margin))

        self.chat_overlay.move(panel_x, panel_y)
        self.chat_overlay.raise_()
        self.chat_fab.raise_()

    def toggle_chat_overlay(self):
        if self.chat_overlay.isVisible():
            self.hide_chat_overlay()
        else:
            self.show_chat_overlay()

    def show_chat_overlay(self):
        # FASE 5: Sincronizar contexto al abrir chat
        self._sync_cart_to_chat()
        # FASE 7: Recargar alertas proactivas
        if hasattr(self.chat_panel, 'reload_alerts'):
            self.chat_panel.reload_alerts()
        self.chat_overlay.show()
        self._position_floating_chat()
        self.chat_overlay.raise_()

    def hide_chat_overlay(self):
        self.chat_overlay.hide()


    def go_to_sales_and_confirm(self, auto_action=None):
        """Navega a Ventas y ejecuta confirm_sale() en la vista actual."""
        try:
            self._pending_confirm_action = auto_action
            self.show_section("ventas")
            QTimer.singleShot(150, self._try_confirm_sale_in_current_sales)
            QTimer.singleShot(200, self._position_floating_chat)
        except Exception as e:
            logging.error(f"Error confirmando venta: {e}")

    def _try_confirm_sale_in_current_sales(self):
        """Llama SalesView.confirm_sale() si está disponible."""
        try:
            sales_view = getattr(self, "sales_view", None)
            if sales_view is None:
                sales_view = getattr(self, "current_view", None)

            from ui.components.toast_notifier import show_toast

            if sales_view is None:
                show_toast("No encontré la vista de Ventas activa.", success=False, parent=self)
                return

            #  Tomar acción pendiente (si viene del chat) y aplicarla al SalesView
            auto_action = getattr(self, "_pending_confirm_action", None)
            self._pending_confirm_action = None
            try:
                setattr(sales_view, "_chat_confirm_action", auto_action)
            except Exception:
                pass

            if hasattr(sales_view, "confirm_sale"):
                sales_view.confirm_sale()
                return

            show_toast("SalesView no expone confirm_sale().", success=False, parent=self)

        except Exception as e:
            logging.error(f"Error ejecutando confirm_sale: {e}")
            import traceback
            traceback.print_exc()
            from ui.components.toast_notifier import show_toast
            show_toast(f"❌ Error confirmando venta: {str(e)}", success=False, parent=self)


    def go_to_sales_and_add(self, product_id: int, qty: int = 1):
        """Navega a Ventas (sin romper layout) y agrega producto al carrito."""
        try:
            # 1) Ir a la sección de ventas usando tu sistema normal
            self.show_section("ventas")

            # 2) Esperar un toque para que la vista esté montada y luego agregar
            QTimer.singleShot(150, lambda: self._try_add_product_to_current_sales(product_id, qty))

            # 3) Mantener overlays visibles arriba
            QTimer.singleShot(200, self._position_floating_chat)

        except Exception as e:
            logging.error(f"Error navegando a ventas: {e}")

    def _show_sale_summary(self):
        """Muestra el resumen de la venta actual sin confirmarla.
        Se llama cuando el chat envía la acción 'preview_confirm_sale'.
        """
        try:
            sales_view = getattr(self, "sales_view", None)
            if sales_view is None:
                sales_view = getattr(self, "current_view", None)

            if sales_view is None:
                from ui.components.toast_notifier import show_toast
                show_toast("No encontré la vista de Ventas activa.", success=False, parent=self)
                return

            # Llamar al método show_sale_summary si existe
            if hasattr(sales_view, "show_sale_summary"):
                sales_view.show_sale_summary()
                return

            # Fallback: mostrar toast con resumen básico
            from ui.components.toast_notifier import show_toast
            try:
                total = getattr(sales_view, "_current_total", 0.0)
                items = sum(getattr(sales_view, "cart", {}).values())
                show_toast(
                    f"🧾 Resumen: {items} items - Total: ₡{total:,.2f}",
                    success=True,
                    parent=self,
                    duration=5000
                )
            except Exception:
                show_toast("🧾 Revisá el resumen en pantalla", success=True, parent=self)

        except Exception as e:
            logging.error(f"Error mostrando resumen de venta: {e}")
            import traceback
            traceback.print_exc()

    def _wrap_view(self, view):
        """
        Compatibilidad con código viejo que esperaba _wrap_view().
        No estorba y evita el crash: 'MainWindow' object has no attribute _wrap_view
        """
        from PySide6.QtWidgets import QWidget, QVBoxLayout

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(view)
        return container

    def go_to_sales_and_set_customer(self, name: str):
        try:
            self.show_section("ventas")  # tu SalesView cacheado :contentReference[oaicite:4]{index=4}
            QTimer.singleShot(150, lambda: self._try_set_customer_in_current_sales(name))
            QTimer.singleShot(200, self._position_floating_chat)
        except Exception as e:
            logging.error(f"Error seteando cliente desde chat: {e}")

    def _try_set_customer_in_current_sales(self, name: str):
        from ui.components.toast_notifier import show_toast
        sales_view = getattr(self, "sales_view", None) or getattr(self, "current_view", None)
        if sales_view is None:
            show_toast("No encontré la vista de Ventas activa.", success=False, parent=self)
            return

        if hasattr(sales_view, "set_customer_by_name"):
            ok = sales_view.set_customer_by_name(name)
            if not ok:
                show_toast(f"No pude asignar el cliente: {name}", success=False, parent=self)
            return

        show_toast("SalesView no expone set_customer_by_name().", success=False, parent=self)

    def go_to_sales_and_set_payment_method(self, method: str):
        try:
            self.show_section("ventas")
            QTimer.singleShot(150, lambda: self._try_set_payment_in_current_sales(method))
            QTimer.singleShot(200, self._position_floating_chat)
        except Exception as e:
            logging.error(f"Error seteando pago desde chat: {e}")

    def _try_set_payment_in_current_sales(self, method: str):
        from ui.components.toast_notifier import show_toast
        sales_view = getattr(self, "sales_view", None) or getattr(self, "current_view", None)
        if sales_view is None:
            show_toast("No encontré la vista de Ventas activa.", success=False, parent=self)
            return

        if hasattr(sales_view, "set_payment_method_from_chat"):
            ok = sales_view.set_payment_method_from_chat(method)
            if not ok:
                show_toast(f"No pude asignar el pago: {method}", success=False, parent=self)
            return

        show_toast("SalesView no expone set_payment_method_from_chat().", success=False, parent=self)

    def _try_add_product_to_current_sales(self, product_id: int, qty: int):
        """Agrega al carrito usando la instancia actual de SalesView."""
        try:
            sales_view = getattr(self, "sales_view", None)

            # fallback por si no usaste cache: intentar con current_view
            if sales_view is None:
                sales_view = getattr(self, "current_view", None)

            if sales_view is None:
                from ui.components.toast_notifier import show_toast
                show_toast("No encontré la vista de Ventas activa.", success=False, parent=self)
                return

            # Llamar el método que ya tenés
            if hasattr(sales_view, "add_product_by_id"):
                ok = sales_view.add_product_by_id(product_id, qty)
                if not ok:
                    from ui.components.toast_notifier import show_toast
                    show_toast("No se pudo agregar el producto al carrito.", success=False, parent=self)
                return

            # Compatibilidad si el método se llama diferente
            if hasattr(sales_view, "add_to_cart"):
                sales_view.add_to_cart(product_id, qty)
                return

            if hasattr(sales_view, "add_product_to_cart"):
                sales_view.add_product_to_cart(product_id, qty)
                return

            from ui.components.toast_notifier import show_toast
            show_toast(
                "SalesView no expone add_product_by_id / add_to_cart / add_product_to_cart.",
                success=False,
                parent=self
            )

        except Exception as e:
            logging.error(f"Error agregando al carrito: {e}")
            import traceback
            traceback.print_exc()

    def go_to_sales_and_undo_last(self):
        """Navega a Ventas y quita el último ítem agregado desde el chat (LIFO)."""
        try:
            self.show_section("ventas")
            QTimer.singleShot(150, self._try_undo_last_in_current_sales)
            QTimer.singleShot(200, self._position_floating_chat)
        except Exception as e:
            logging.error(f"Error deshaciendo último ítem: {e}")


    def _try_undo_last_in_current_sales(self):
        """
        Quita el último ítem del carrito en la vista de Ventas.
        Busca específicamente el botón de eliminar en la última fila.
        """
        from ui.components.toast_notifier import show_toast
        from PySide6.QtWidgets import QTableWidget, QPushButton

        sales_view = getattr(self, "sales_view", None) or getattr(self, "current_view", None)
        if sales_view is None:
            show_toast("No encontré la vista de Ventas activa.", success=False, parent=self)
            return

        # 1) Encontrar la tabla real del carrito
        tables = sales_view.findChildren(QTableWidget)
        if not tables:
            show_toast("No encontré la tabla del carrito en Ventas.", success=False, parent=self)
            return

        # elegir la que tenga filas
        tables_with_rows = [t for t in tables if t.rowCount() > 0]
        if not tables_with_rows:
            show_toast("No hay ítems que deshacer.", success=False, parent=self)
            return

        table = max(tables_with_rows, key=lambda t: t.rowCount())

        # 2) Última fila
        last_row = table.rowCount() - 1
        if last_row < 0:
            show_toast("No hay ítems que deshacer.", success=False, parent=self)
            return

        table.selectRow(last_row)

        # 3) Buscar botón de eliminar ESPECÍFICAMENTE en la última fila
        # Recorrer todas las columnas de la última fila
        delete_btn = None
        
        for col in range(table.columnCount()):
            w = table.cellWidget(last_row, col)
            if w is None:
                continue
                
            # Buscar botones dentro del widget de la celda
            buttons = []
            if isinstance(w, QPushButton):
                buttons = [w]
            else:
                buttons = w.findChildren(QPushButton)
            
            # Buscar el botón de eliminar por texto, tooltip o icono
            for btn in buttons:
                txt = (btn.text() or "").lower()
                tip = (btn.toolTip() or "").lower()
                
                # ✅ Filtros más específicos para el botón de ELIMINAR
                # Ignorar botones de descuento explícitamente
                if "%" in txt or "descuento" in tip or "discount" in tip:
                    continue
                    
                # Buscar botones de eliminar
                is_delete = (
                    "🗑" in txt or  # icono de papelera
                    "×" in txt or    # símbolo X
                    "x" == txt.strip() or  # X solo
                    "eliminar" in tip or
                    "borrar" in tip or
                    "quitar" in tip or
                    "remove" in tip.lower() or
                    "delete" in tip.lower()
                )
                
                if is_delete:
                    delete_btn = btn
                    break
            
            if delete_btn:
                break
        
        # 4) Si encontramos el botón, hacer clic
        if delete_btn is not None:
            delete_btn.click()
            show_toast("Listo ✅ Quité el último ítem del carrito.", success=True, parent=self)
            return
        
        # 5) Fallback: mensaje de error más claro
        show_toast(
            "No pude encontrar el botón de eliminar en la última fila del carrito.",
            success=False,
            parent=self
        )
        
    def go_to_sales_and_remove_by_name(self, name: str):
        try:
            self.show_section("ventas")
            QTimer.singleShot(150, lambda: self._try_remove_by_name_in_current_sales(name))
            QTimer.singleShot(200, self._position_floating_chat)
        except Exception as e:
            logging.error(f"Error quitando producto desde chat: {e}")

    def _try_remove_by_name_in_current_sales(self, name: str):
        from ui.components.toast_notifier import show_toast
        sales_view = getattr(self, "sales_view", None) or getattr(self, "current_view", None)
        if sales_view is None:
            show_toast("No encontré la vista de Ventas activa.", success=False, parent=self)
            return

        if hasattr(sales_view, "remove_from_cart_by_name"):
            ok = sales_view.remove_from_cart_by_name(name)
            if not ok:
                show_toast(f"No encontré '{name}' en el carrito.", success=False, parent=self)
            return

        show_toast("SalesView no expone remove_from_cart_by_name().", success=False, parent=self)
        
    def go_to_sales_and_decrement_by_name(self, name: str, qty: int = 1):
        try:
            self.show_section("ventas")
            QTimer.singleShot(150, lambda: self._try_decrement_by_name_in_current_sales(name, qty))
            QTimer.singleShot(200, self._position_floating_chat)
        except Exception as e:
            logging.error(f"Error decrementando producto desde chat: {e}")

    def _try_decrement_by_name_in_current_sales(self, name: str, qty: int):
  
        sales_view = getattr(self, "sales_view", None) or getattr(self, "current_view", None)
        if sales_view is None:
            show_toast("No encontré la vista de Ventas activa.", success=False, parent=self)
            return

        if hasattr(sales_view, "decrement_from_cart_by_name"):
            ok, removed, matched_name = sales_view.decrement_from_cart_by_name(name, qty)
            if ok:
                show_toast(f"➖ Quité {removed} de '{matched_name}'", success=True, parent=self)
            else:
                show_toast(f"No encontré '{name}' en el carrito.", success=False, parent=self)
            return

        show_toast("SalesView no expone decrement_from_cart_by_name().", success=False, parent=self)