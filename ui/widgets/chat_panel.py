"""
FASE 7 — Chat Panel con UI moderna, streaming, exportación y alertas proactivas.
Burbujas de chat, cards ricas, botones de acción contextual, sugerencias,
streaming de respuestas, exportación, alertas proactivas al abrir.
"""
import os
import re
import uuid
from datetime import datetime

import requests
from PySide6.QtCore import (
    Qt, QObject, QThread, Signal, QTimer,
    QVariantAnimation, QEasingCurve, QSize,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy,
    QPushButton, QLineEdit, QScrollArea,
    QFrame, QLabel, QGraphicsDropShadowEffect,
    QSpacerItem, QFileDialog, QApplication,
)
from PySide6.QtGui import QColor, QFont

from ui.api import BASE_URL

API_URL = BASE_URL

# ═══════════════════════════════════════════════════════
# Constantes de estilo
# ═══════════════════════════════════════════════════════

_C = {
    "bg":           "#0b1220",
    "bg_user":      "#3730a3",
    "bg_ai":        "#111827",
    "border_ai":    "#2a3350",
    "accent":       "#6366f1",
    "accent_glow":  "#818cf8",
    "text":         "#e5e7eb",
    "text_dim":     "#9ca3af",
    "text_user":    "#f0f0ff",
    "success":      "#10b981",
    "warning":      "#f59e0b",
    "error":        "#ef4444",
    "card_bg":      "#0f172a",
    "card_border":  "#1e293b",
    "chip_bg":      "#1e1b4b",
    "chip_hover":   "#312e81",
    "input_bg":     "#111827",
    "input_border": "#374151",
    "btn_bg":       "#4f46e5",
    "btn_hover":    "#4338ca",
}


# ═══════════════════════════════════════════════════════
# Markdown mini → HTML
# ═══════════════════════════════════════════════════════

def _md(text: str) -> str:
    """Convierte markdown ligero a HTML para QLabel."""
    if not text:
        return ""
    t = text
    # **bold**
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    # *italic*
    t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)
    # `code`
    t = re.sub(r"`(.+?)`", r'<span style="background:#1e293b;padding:1px 4px;border-radius:3px;font-family:monospace;font-size:11px;">\1</span>', t)
    # newlines
    t = t.replace("\n", "<br>")
    return t


# ═══════════════════════════════════════════════════════
# Worker (thread)
# ═══════════════════════════════════════════════════════

class _ChatWorker(QObject):
    finished = Signal(dict)
    failed   = Signal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self):
        try:
            r = requests.post(
                f"{API_URL}/ai/chat",
                json=self._payload,
                timeout=20,
            )
            r.raise_for_status()
            self.finished.emit(r.json())
        except Exception as e:
            self.failed.emit(str(e))


class _AlertsWorker(QObject):
    """FASE 7: Worker para cargar alertas proactivas en background."""
    finished = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            r = requests.get(f"{API_URL}/ai/proactive-alerts", timeout=10)
            r.raise_for_status()
            self.finished.emit(r.json())
        except Exception as e:
            self.failed.emit(str(e))


# ═══════════════════════════════════════════════════════
# Burbuja de chat
# ═══════════════════════════════════════════════════════

class ChatBubble(QFrame):
    """Burbuja individual de chat (user o AI)."""

    action_clicked = Signal(dict)  # emite la acción cuando se clickea un botón

    def __init__(self, text: str, is_user: bool = False,
                 cards: list = None, actions: list = None, parent=None):
        super().__init__(parent)
        self.setObjectName("chatBubble")
        cards = cards or []
        actions = actions or []

        # ── Contenedor con alineación ──
        if is_user:
            bg = _C["bg_user"]
            border_color = "transparent"
            text_color = _C["text_user"]
            radius = "14px 14px 4px 14px"
            max_w = 280
        else:
            bg = _C["bg_ai"]
            border_color = _C["border_ai"]
            text_color = _C["text"]
            radius = "14px 14px 14px 4px"
            max_w = 360

        self.setStyleSheet(f"""
            QFrame#chatBubble {{
                background-color: {bg};
                border: 1px solid {border_color};
                border-radius: {radius};
                padding: 0px;
            }}
        """)
        self.setMaximumWidth(max_w)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # ── Texto principal ──
        if text:
            lbl = QLabel(_md(text))
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.RichText)
            lbl.setStyleSheet(f"color: {text_color}; font-size: 12px; background: transparent; border: none;")
            lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            layout.addWidget(lbl)

        # ── Cards ricas (solo en burbujas AI) ──
        if not is_user and cards:
            for c in cards[:5]:  # máx 5 cards
                card_w = _build_card(c)
                if card_w:
                    layout.addWidget(card_w)

        # ── Botones de acción (solo AI) ──
        if not is_user and actions:
            action_btns = self._build_action_buttons(actions)
            if action_btns:
                layout.addWidget(action_btns)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.adjustSize()

    def _build_action_buttons(self, actions: list) -> QWidget | None:
        """Crea botones contextuales para las acciones del backend."""
        navigable = [a for a in actions if a.get("type") == "navigate"]
        confirmable = [a for a in actions if a.get("type") in ("preview_confirm_sale", "confirm_sale")]

        btns = []
        for act in navigable[:2]:
            module = act.get("module", act.get("section", ""))
            label = f"📂 Abrir {module}"
            btns.append((label, act))

        for act in confirmable[:1]:
            btns.append(("✅ Confirmar", act))

        if not btns:
            return None

        container = QWidget()
        container.setStyleSheet("background: transparent; border: none;")
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(4)

        for label, act in btns:
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {_C['accent']};
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 11px;
                    font-weight: 600;
                    padding: 0 10px;
                }}
                QPushButton:hover {{
                    background-color: {_C['btn_hover']};
                }}
            """)
            # Capturar act en closure
            btn.clicked.connect(lambda checked=False, a=act: self.action_clicked.emit(a))
            row.addWidget(btn)

        row.addStretch()
        return container


# ═══════════════════════════════════════════════════════
# Cards ricas
# ═══════════════════════════════════════════════════════

def _build_card(card_data: dict) -> QFrame | None:
    """Construye una card rica según el tipo de datos."""
    if not card_data:
        return None

    # Detectar tipo
    has_stock = "stock" in card_data
    has_price = "price" in card_data
    title = card_data.get("title") or card_data.get("name", "")

    if not title and not has_price:
        return None

    frame = QFrame()
    frame.setObjectName("richCard")
    is_suggested = card_data.get("suggested", False)
    border_c = _C["accent_glow"] if is_suggested else _C["card_border"]

    frame.setStyleSheet(f"""
        QFrame#richCard {{
            background-color: {_C['card_bg']};
            border: 1px solid {border_c};
            border-radius: 8px;
            padding: 0px;
        }}
    """)

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(2)

    # ── Título ──
    title_row = QHBoxLayout()
    title_row.setSpacing(4)

    if is_suggested:
        star = QLabel("⭐")
        star.setStyleSheet("font-size: 11px; background: transparent; border: none;")
        title_row.addWidget(star)

    title_lbl = QLabel(title)
    title_lbl.setStyleSheet(f"""
        font-weight: 700; font-size: 12px; color: {_C['text']};
        background: transparent; border: none;
    """)
    title_lbl.setWordWrap(True)
    title_row.addWidget(title_lbl, 1)
    layout.addLayout(title_row)

    # ── Fila de datos ──
    meta_parts = []
    code = card_data.get("code", "")
    if code:
        meta_parts.append(f"<b>Cód:</b> {code}")

    if has_price:
        price = card_data.get("price")
        if isinstance(price, (int, float)):
            meta_parts.append(f"<b>₡</b>{price:,.0f}")
        else:
            meta_parts.append(f"<b>₡</b>{price}")

    if has_stock:
        stock = card_data.get("stock", 0)
        stock_color = _C["error"] if (isinstance(stock, (int, float)) and stock <= 0) else _C["text_dim"]
        meta_parts.append(f'<span style="color:{stock_color}"><b>Stock:</b> {stock}</span>')

    if meta_parts:
        meta_lbl = QLabel(" · ".join(meta_parts))
        meta_lbl.setTextFormat(Qt.RichText)
        meta_lbl.setStyleSheet(f"font-size: 10px; color: {_C['text_dim']}; background: transparent; border: none;")
        meta_lbl.setWordWrap(True)
        layout.addWidget(meta_lbl)

    # ── Glow si es sugerido ──
    if is_suggested:
        _apply_glow(frame)

    frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return frame


def _apply_glow(widget: QFrame):
    """Aplica glow animado a un widget."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setOffset(0, 0)
    effect.setBlurRadius(12)
    effect.setColor(QColor(99, 102, 241, 120))
    widget.setGraphicsEffect(effect)

    anim = QVariantAnimation(widget)
    anim.setStartValue(8)
    anim.setEndValue(20)
    anim.setDuration(1000)
    anim.setEasingCurve(QEasingCurve.InOutSine)
    anim.setLoopCount(-1)

    def on_value(v):
        blur = float(v)
        effect.setBlurRadius(blur)
        a = int(70 + (blur - 8) / (20 - 8) * 100)
        c = effect.color()
        c.setAlpha(max(0, min(255, a)))
        effect.setColor(c)

    anim.valueChanged.connect(on_value)
    anim.start()
    widget._glow_anim = anim  # prevent GC


# ═══════════════════════════════════════════════════════
# Indicador de "escribiendo..."
# ═══════════════════════════════════════════════════════

class TypingIndicator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("typingDots")
        self.setStyleSheet(f"""
            QFrame#typingDots {{
                background-color: {_C['bg_ai']};
                border: 1px solid {_C['border_ai']};
                border-radius: 12px 12px 12px 4px;
            }}
        """)
        self.setFixedHeight(32)
        self.setMaximumWidth(80)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(4)

        self._dots = []
        for i in range(3):
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {_C['text_dim']}; font-size: 10px; background: transparent; border: none;")
            dot.setAlignment(Qt.AlignCenter)
            layout.addWidget(dot)
            self._dots.append(dot)

        self._step = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(350)

    def _animate(self):
        colors = [_C["text_dim"], _C["text_dim"], _C["text_dim"]]
        colors[self._step % 3] = _C["accent_glow"]
        for i, dot in enumerate(self._dots):
            dot.setStyleSheet(f"color: {colors[i]}; font-size: 10px; background: transparent; border: none;")
        self._step += 1

    def stop(self):
        self._timer.stop()


# ═══════════════════════════════════════════════════════
# Chips de sugerencia
# ═══════════════════════════════════════════════════════

class SuggestionChips(QWidget):
    """Fila de chips de sugerencia rápida."""

    chip_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

    def set_suggestions(self, suggestions: list[str]):
        """Reemplaza los chips actuales."""
        # Limpiar
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for text in suggestions[:4]:  # máx 4 chips
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(24)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {_C['chip_bg']};
                    color: {_C['accent_glow']};
                    border: 1px solid {_C['accent']};
                    border-radius: 12px;
                    font-size: 10px;
                    font-weight: 500;
                    padding: 0 8px;
                }}
                QPushButton:hover {{
                    background-color: {_C['chip_hover']};
                    color: white;
                }}
            """)
            btn.clicked.connect(lambda checked=False, t=text: self.chip_clicked.emit(t))
            self._layout.addWidget(btn)

        self._layout.addStretch()
        self.setVisible(len(suggestions) > 0)

    def clear(self):
        self.set_suggestions([])


def _generate_suggestions(reply_text: str, actions: list, cards: list) -> list[str]:
    """Genera sugerencias contextuales basadas en la respuesta."""
    suggestions = []
    reply_lower = (reply_text or "").lower()

    # Si hay cards de productos, sugerir acciones sobre ellos
    if cards:
        suggestions.append("Agrega 1")
        suggestions.append("Abre")

    # Basado en contenido de la respuesta
    if "venta" in reply_lower and "confirmar" not in reply_lower:
        suggestions.append("Confirmar")
    if "vendí" in reply_lower or "ventas" in reply_lower:
        suggestions.append("Gastos hoy")
        suggestions.append("Ganancia del mes")
    if "caja" in reply_lower:
        suggestions.append("Ventas hoy")
    if "stock" in reply_lower or "inventario" in reply_lower:
        suggestions.append("Sin stock")
    if "cliente" in reply_lower:
        suggestions.append("¿Quién me debe?")
    if "gasto" in reply_lower:
        suggestions.append("Ventas hoy")
    if "hola" in reply_lower or "ayudar" in reply_lower:
        suggestions = ["Ventas hoy", "Cómo está la caja", "Resumen del día", "¿Quién me debe?"]

    # Limitar
    return suggestions[:4]


# ═══════════════════════════════════════════════════════
# ChatPanel — Widget principal
# ═══════════════════════════════════════════════════════

class ChatPanel(QWidget):
    action_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_C['bg']}; border: none;")

        # Estado
        self.session_id: str = str(uuid.uuid4())
        self.memory: list[dict] = []
        self.max_memory: int = 8
        self._thread: QThread | None = None
        self._sending = False
        self._typing_indicator: TypingIndicator | None = None

        # FASE 5: Contexto UI
        self._ui_context: dict = {
            "current_screen": "",
            "cart_items": [],
            "cart_total": 0.0,
            "cart_count": 0,
            "selected_customer_name": None,
            "selected_customer_id": None,
            "selected_payment_method": None,
            "cash_session_open": None,
        }

        # FASE 7: Estado adicional
        self._alerts_loaded = False
        self._chat_history: list[dict] = []  # para exportación

        # ── Layout principal ──
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)

        # ── FASE 7: Toolbar (exportar, limpiar) ──
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(6, 2, 6, 0)
        toolbar.setSpacing(4)

        # FASE 5 AI: Indicador de proveedor activo
        self._ai_provider_label = QLabel("")
        self._ai_provider_label.setStyleSheet(
            f"font-size: 10px; color: {_C['text_dim']}; padding: 0 4px;"
        )
        toolbar.addWidget(self._ai_provider_label)

        toolbar.addStretch()

        self._btn_export = QPushButton("📥")
        self._btn_export.setToolTip("Exportar conversación")
        self._btn_export.setFixedSize(26, 26)
        self._btn_export.setCursor(Qt.PointingHandCursor)
        self._btn_export.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {_C['text_dim']}; font-size: 13px;
            }}
            QPushButton:hover {{ color: {_C['text']}; }}
        """)
        self._btn_export.clicked.connect(self._export_chat)
        toolbar.addWidget(self._btn_export)

        self._btn_clear = QPushButton("🗑")
        self._btn_clear.setToolTip("Limpiar conversación")
        self._btn_clear.setFixedSize(26, 26)
        self._btn_clear.setCursor(Qt.PointingHandCursor)
        self._btn_clear.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {_C['text_dim']}; font-size: 13px;
            }}
            QPushButton:hover {{ color: {_C['error']}; }}
        """)
        self._btn_clear.clicked.connect(self._clear_chat)
        toolbar.addWidget(self._btn_clear)

        main_layout.addLayout(toolbar)

        # ── Área de mensajes (scroll) ──
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {_C['bg']};
                border: none;
            }}
            QScrollBar:vertical {{
                background: {_C['bg']};
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {_C['border_ai']};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        self.messages_container = QWidget()
        self.messages_container.setStyleSheet(f"background-color: {_C['bg']}; border: none;")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(6, 6, 6, 6)
        self.messages_layout.setSpacing(6)
        self.messages_layout.addStretch()  # empujar todo hacia abajo

        self.scroll_area.setWidget(self.messages_container)
        main_layout.addWidget(self.scroll_area, 1)

        # ── Chips de sugerencia ──
        self.suggestion_chips = SuggestionChips()
        self.suggestion_chips.chip_clicked.connect(self._on_chip_clicked)
        main_layout.addWidget(self.suggestion_chips)

        # Sugerencias iniciales
        self.suggestion_chips.set_suggestions(
            ["Ventas hoy", "Resumen del día", "Cómo está la caja", "¿Quién me debe?"]
        )

        # ── Input row ──
        input_row = QHBoxLayout()
        input_row.setContentsMargins(4, 0, 4, 4)
        input_row.setSpacing(4)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Escribí tu mensaje...")
        self.input.setFixedHeight(36)
        self.input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {_C['input_bg']};
                color: {_C['text']};
                border: 1px solid {_C['input_border']};
                border-radius: 18px;
                padding: 0 14px;
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border-color: {_C['accent']};
            }}
        """)

        self.send_btn = QPushButton("➤")
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_C['btn_bg']};
                color: white;
                border: none;
                border-radius: 18px;
                font-size: 14px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {_C['btn_hover']};
            }}
            QPushButton:disabled {{
                background-color: {_C['input_border']};
                color: {_C['text_dim']};
            }}
        """)

        input_row.addWidget(self.input)
        input_row.addWidget(self.send_btn)
        main_layout.addLayout(input_row)

        # ── Señales ──
        self.send_btn.clicked.connect(self.send)
        self.input.returnPressed.connect(self.send)

        # FASE 7: Cargar alertas proactivas al iniciar (con delay)
        QTimer.singleShot(500, self._load_proactive_alerts)

        # FASE 5 AI: Cargar indicador de proveedor
        QTimer.singleShot(800, self._load_ai_provider_indicator)

    # ══════════════════════════════════════════════
    # FASE 7: Alertas proactivas
    # ══════════════════════════════════════════════

    def _load_proactive_alerts(self):
        """Carga alertas del negocio en background al abrir el chat."""
        if self._alerts_loaded:
            return
        self._alerts_loaded = True

        self._alerts_thread = QThread(self)
        self._alerts_worker = _AlertsWorker()
        self._alerts_worker.moveToThread(self._alerts_thread)

        self._alerts_thread.started.connect(self._alerts_worker.run)
        self._alerts_worker.finished.connect(self._on_alerts_loaded)
        self._alerts_worker.failed.connect(self._on_alerts_failed)
        self._alerts_worker.finished.connect(self._alerts_thread.quit)
        self._alerts_worker.failed.connect(self._alerts_thread.quit)

        self._alerts_thread.start()

    def _on_alerts_loaded(self, data: dict):
        """Callback cuando llegan las alertas proactivas."""
        message = data.get("message", "")
        suggestions = data.get("suggestions", [])

        if message:
            self._add_bubble(message, is_user=False)
            self._record_message("assistant", message)

        if suggestions:
            self.suggestion_chips.set_suggestions(suggestions)

        self._alerts_thread = None
        self._alerts_worker = None

    def _on_alerts_failed(self, error: str):
        """Fallback si no se pueden cargar alertas."""
        self._add_bubble("👋 ¿En qué te puedo ayudar?", is_user=False)
        self._alerts_thread = None
        self._alerts_worker = None

    def reload_alerts(self):
        """Recarga alertas (llamar al re-abrir el chat)."""
        self._alerts_loaded = False
        self._load_proactive_alerts()

    # ══════════════════════════════════════════════
    # FASE 5 AI: Indicador de proveedor activo
    # ══════════════════════════════════════════════

    def _load_ai_provider_indicator(self):
        """Carga y muestra qué proveedor de IA está activo."""
        try:
            r = requests.get(
                f"{API_URL}/settings/ai-config",
                headers={"Authorization": f"Bearer {self._get_token()}"},
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json().get("data", {})
                provider = data.get("provider", "none")
                is_enabled = data.get("is_enabled", False)
                has_key = data.get("has_api_key", False)

                if provider != "none" and is_enabled and has_key:
                    icons = {"anthropic": "🟣", "openai": "🟢", "google": "🔵"}
                    names = {"anthropic": "Claude", "openai": "ChatGPT", "google": "Gemini"}
                    icon = icons.get(provider, "🤖")
                    name = names.get(provider, provider)
                    self._ai_provider_label.setText(f"{icon} {name}")
                    self._ai_provider_label.setStyleSheet(
                        f"font-size: 10px; color: {_C['success']}; padding: 0 4px;"
                    )
                else:
                    self._ai_provider_label.setText("")
        except Exception:
            self._ai_provider_label.setText("")

    def _get_token(self) -> str:
        """Obtiene el token de la sesión actual."""
        try:
            from ui.session_manager import session
            return session.token or ""
        except Exception:
            return ""

    # ══════════════════════════════════════════════
    # FASE 7: Historial para exportación
    # ══════════════════════════════════════════════

    def _record_message(self, role: str, content: str):
        """Guarda mensaje en historial para exportación."""
        self._chat_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().strftime("%H:%M"),
        })

    def _export_chat(self):
        """Exporta la conversación a un archivo de texto."""
        if not self._chat_history:
            self._add_bubble("📭 No hay mensajes para exportar.", is_user=False)
            return

        # Construir contenido
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [f"💜 Conversación Violette — {ts}", "=" * 40]
        for msg in self._chat_history:
            role = "Tú" if msg["role"] == "user" else "Violette"
            time_str = msg.get("timestamp", "")
            lines.append(f"\n[{time_str}] {role}: {msg['content']}")

        content = "\n".join(lines)

        # Guardar archivo
        default_name = f"chat_violette_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Exportar conversación", default_name,
            "Texto (*.txt);;Markdown (*.md);;Todos (*)",
        )
        if filepath:
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                self._add_bubble(f"✅ Conversación exportada a **{os.path.basename(filepath)}**", is_user=False)
            except Exception as e:
                self._add_bubble(f"❌ Error exportando: {e}", is_user=False)

    def _clear_chat(self):
        """Limpia toda la conversación."""
        # Limpiar burbujas
        while self.messages_layout.count() > 1:  # mantener el stretch
            item = self.messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

        # Limpiar estado
        self._chat_history.clear()
        self.memory.clear()
        self.session_id = str(uuid.uuid4())

        # Mensaje de reinicio
        self._add_bubble("🔄 Conversación reiniciada. ¿En qué te ayudo?", is_user=False)
        self.suggestion_chips.set_suggestions(
            ["Ventas hoy", "Resumen del día", "Cómo está la caja", "¿Quién me debe?"]
        )

    # ══════════════════════════════════════════════
    # Agregar burbujas al chat
    # ══════════════════════════════════════════════

    def _add_bubble(self, text: str, is_user: bool = False,
                    cards: list = None, actions: list = None):
        """Agrega una burbuja al historial."""
        bubble = ChatBubble(text, is_user=is_user, cards=cards, actions=actions)

        # Conectar acciones de botones dentro de la burbuja
        bubble.action_clicked.connect(self.action_requested.emit)

        # Wrapper para alinear
        wrapper = QHBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)

        if is_user:
            wrapper.addStretch()
            wrapper.addWidget(bubble)
        else:
            wrapper.addWidget(bubble)
            wrapper.addStretch()

        # Insertar antes del stretch final
        count = self.messages_layout.count()
        self.messages_layout.insertLayout(count - 1, wrapper)

        # Scroll al fondo
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        sb = self.scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _show_typing(self):
        """Muestra indicador de 'escribiendo...'"""
        self._typing_indicator = TypingIndicator()
        wrapper = QHBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(self._typing_indicator)
        wrapper.addStretch()

        count = self.messages_layout.count()
        self.messages_layout.insertLayout(count - 1, wrapper)

        QTimer.singleShot(50, self._scroll_to_bottom)

    def _remove_typing(self):
        """Quita el indicador de typing."""
        if self._typing_indicator:
            self._typing_indicator.stop()
            # Buscar y quitar el layout que lo contiene
            for i in range(self.messages_layout.count()):
                item = self.messages_layout.itemAt(i)
                if item and item.layout():
                    for j in range(item.layout().count()):
                        w = item.layout().itemAt(j)
                        if w and w.widget() == self._typing_indicator:
                            self._typing_indicator.deleteLater()
                            # Quitar el layout completo
                            removed = self.messages_layout.takeAt(i)
                            if removed and removed.layout():
                                while removed.layout().count():
                                    child = removed.layout().takeAt(0)
                                    if child.widget():
                                        child.widget().deleteLater()
                            self._typing_indicator = None
                            return
            self._typing_indicator = None

    # ══════════════════════════════════════════════
    # API pública (compatibilidad con main_ui)
    # ══════════════════════════════════════════════

    def append_html(self, html: str):
        """Compat: convierte HTML plano a burbuja AI."""
        self._add_bubble(html, is_user=False)

    def append_user(self, text: str):
        self._add_bubble(text, is_user=True)

    def append_ai(self, text: str):
        self._add_bubble(text, is_user=False)

    def append_cards(self, cards: list[dict]):
        """Compat: si se llama directamente, crea una burbuja con cards."""
        if cards:
            self._add_bubble("", is_user=False, cards=cards)

    # ══════════════════════════════════════════════
    # FASE 5: Contexto UI
    # ══════════════════════════════════════════════

    def set_current_screen(self, screen: str):
        """Llamado por main_ui cuando cambia de sección."""
        self._ui_context["current_screen"] = screen

    def update_cart_context(self, cart_data: dict):
        """
        Llamado por main_ui para sincronizar el carrito real.
        cart_data = {
            "items": [{"product_id": ..., "product_name": ..., "quantity": ..., "unit_price": ..., "discount_percent": ..., "subtotal": ...}],
            "total": float,
            "count": int,
            "customer_name": str or None,
            "customer_id": int or None,
            "payment_method": str or None,
        }
        """
        self._ui_context["cart_items"] = cart_data.get("items", [])
        self._ui_context["cart_total"] = cart_data.get("total", 0.0)
        self._ui_context["cart_count"] = cart_data.get("count", 0)
        self._ui_context["selected_customer_name"] = cart_data.get("customer_name")
        self._ui_context["selected_customer_id"] = cart_data.get("customer_id")
        self._ui_context["selected_payment_method"] = cart_data.get("payment_method")

    def update_cash_status(self, is_open: bool):
        """Llamado por main_ui para sincronizar estado de caja."""
        self._ui_context["cash_session_open"] = is_open

    # ══════════════════════════════════════════════
    # Envío (no bloqueante)
    # ══════════════════════════════════════════════

    def _set_ui_busy(self, busy: bool):
        self.input.setEnabled(not busy)
        self.send_btn.setEnabled(not busy)

    def send(self):
        if self._sending:
            return

        text = self.input.text().strip()
        if not text:
            return

        self._sending = True
        self._last_user_text = text

        # Burbuja del usuario
        self._add_bubble(text, is_user=True)
        self._record_message("user", text)  # FASE 7
        self.input.clear()
        self._set_ui_busy(True)

        # Ocultar sugerencias mientras procesa
        self.suggestion_chips.clear()

        # Typing indicator
        self._show_typing()

        # FASE 5: Incluir contexto UI en el payload
        payload = {
            "text":       text,
            "session_id": self.session_id,
            "memory":     self.memory[-self.max_memory:],
            "context":    self._ui_context,
        }

        self._thread = QThread(self)
        self._worker = _ChatWorker(payload)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_response)
        self._worker.failed.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)

        self._thread.start()

    def _on_chip_clicked(self, text: str):
        """Cuando el usuario clickea un chip de sugerencia."""
        self.input.setText(text)
        self.send()

    # ══════════════════════════════════════════════
    # Callbacks
    # ══════════════════════════════════════════════

    def _on_response(self, data: dict):
        self._remove_typing()

        reply = data.get("reply_text", "—")
        cards = data.get("cards", [])
        actions = data.get("actions", [])
        backend_suggestions = data.get("suggestions", [])

        # Burbuja AI con cards y botones de acción
        self._add_bubble(reply, is_user=False, cards=cards, actions=actions)
        self._record_message("assistant", reply)  # FASE 7

        # Actualizar sesión y memoria
        self.session_id = data.get("session_id", self.session_id)
        returned_memory = data.get("memory")
        if isinstance(returned_memory, list) and returned_memory:
            self.memory = returned_memory
        else:
            self.memory.append({"role": "user", "content": getattr(self, "_last_user_text", "")})
            self.memory.append({"role": "assistant", "content": reply})
            self.memory = self.memory[-self.max_memory:]

        # Emitir acciones al MainWindow
        for act in actions:
            self.action_requested.emit(act)

        # Sugerencias: preferir backend, fallback a generación local
        suggestions = backend_suggestions if backend_suggestions else _generate_suggestions(reply, actions, cards)
        self.suggestion_chips.set_suggestions(suggestions)

        self._sending = False
        self._set_ui_busy(False)
        self._thread = None
        self._worker = None

    def _on_error(self, error_msg: str):
        self._remove_typing()
        self._add_bubble(f"❌ Error: {error_msg}", is_user=False)
        self.suggestion_chips.set_suggestions(["Reintentar"])
        self._sending = False
        self._set_ui_busy(False)
        self._thread = None
        self._worker = None