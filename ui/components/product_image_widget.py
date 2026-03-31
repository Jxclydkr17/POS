"""
ProductImageWidget
==================
Widget reutilizable para seleccionar / previsualizar la imagen de un producto.

Características:
  - Preview 90×90 con esquinas redondeadas
  - Placeholder con ícono de cámara pintado (QPainter)
  - Botón "📂 Examinar" para abrir el file-picker
  - Botón "✖ Quitar" habilitado solo cuando hay imagen
  - Pequeña etiqueta con el nombre del archivo

Uso en diálogos:
    self.image_widget = ProductImageWidget()
    left_col.addWidget(self.image_widget)

    # Leer ruta al guardar
    path = self.image_widget.get_path()   # "" si no hay imagen

    # Pre-cargar (en edit)
    self.image_widget.set_path(product["image_path"] or "")
"""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QPixmap, QColor, QPainter, QPen, QBrush, QFont, QPainterPath
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de imagen
# ─────────────────────────────────────────────────────────────────────────────

def make_placeholder_pixmap(size: int = 90) -> QPixmap:
    """
    Genera un placeholder con ícono de cámara.
    Se puede llamar desde otros módulos (p. ej. products_view).
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)

    # Fondo redondeado
    bg_path = QPainterPath()
    bg_path.addRoundedRect(0, 0, size, size, 8, 8)
    painter.fillPath(bg_path, QColor("#2A2E35"))

    # Borde sutil
    pen = QPen(QColor("#4A5568"))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawPath(bg_path)

    # ── Cuerpo de la cámara ──────────────────────────────────
    cam_w  = size * 0.46
    cam_h  = size * 0.32
    cam_x  = (size - cam_w) / 2
    cam_y  = (size - cam_h) / 2 + size * 0.04

    painter.setBrush(QBrush(QColor("#4A5568")))
    pen.setColor(QColor("#6B7280"))
    pen.setWidth(1)
    painter.setPen(pen)
    painter.drawRoundedRect(int(cam_x), int(cam_y), int(cam_w), int(cam_h), 5, 5)

    # ── Bultito superior (visor) ────────────────────────────
    bw = cam_w * 0.28
    bh = cam_h * 0.28
    bx = cam_x + cam_w * 0.32
    by = cam_y - bh + 2
    painter.setBrush(QBrush(QColor("#4A5568")))
    painter.drawRoundedRect(int(bx), int(by), int(bw), int(bh), 2, 2)

    # ── Lente (círculo exterior) ────────────────────────────
    lx = size / 2
    ly = cam_y + cam_h / 2
    lr = size * 0.115

    painter.setBrush(QBrush(QColor("#1E2128")))
    pen.setColor(QColor("#9CA3AF"))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawEllipse(int(lx - lr), int(ly - lr), int(lr * 2), int(lr * 2))

    # Reflejo del lente
    painter.setBrush(QBrush(QColor("#9CA3AF")))
    painter.setPen(Qt.NoPen)
    rl = lr * 0.38
    painter.drawEllipse(int(lx - lr * 0.5), int(ly - lr * 0.55), int(rl), int(rl))

    # ── Texto "Sin foto" ────────────────────────────────────
    painter.setPen(QColor("#6B7280"))
    f = QFont()
    f.setPointSize(max(6, size // 13))
    painter.setFont(f)
    ty = int(cam_y + cam_h + 5)
    painter.drawText(0, ty, size, size - ty, Qt.AlignHCenter | Qt.AlignTop, "Sin foto")

    painter.end()
    return pm


def load_preview(image_path: str, size: int = 90) -> QPixmap:
    """Carga la imagen y la escala; devuelve placeholder si falla."""
    if not image_path:
        return make_placeholder_pixmap(size)
    try:
        if not os.path.isabs(image_path):
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            image_path = os.path.join(base, image_path)
        if os.path.exists(image_path):
            pm = QPixmap(image_path)
            if not pm.isNull():
                return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        pass
    return make_placeholder_pixmap(size)


# ─────────────────────────────────────────────────────────────────────────────
# Widget principal
# ─────────────────────────────────────────────────────────────────────────────

_BTN_BASE = """
    QPushButton {{
        background-color: {bg};
        color: {fg};
        border: 1px solid {border};
        border-radius: 5px;
        padding: 0 8px;
        font-size: 12px;
    }}
"""

_BORDER_WITH_IMG   = "border: 2px solid #5B9BD5; border-radius: 8px; background-color: #2A2E35;"
_BORDER_NO_IMG     = "border: 2px solid #4A5568; border-radius: 8px; background-color: #2A2E35;"


class ProductImageWidget(QWidget):
    """
    Widget compacto para la sección de imagen en los diálogos
    add_product y edit_product.
    """

    path_changed = Signal(str)   # emite el path nuevo (o "" al quitar)

    PREVIEW_SIZE = 90

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._setup_ui()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        lbl_title = QLabel("Imagen del producto")
        lbl_title.setStyleSheet("font-weight: bold; color: #E0E0E0; margin-top: 2px;")
        layout.addWidget(lbl_title)

        # Fila horizontal: preview | botones
        row = QHBoxLayout()
        row.setSpacing(10)

        # ── Preview ─────────────────────────────────────────
        self.preview_lbl = QLabel()
        self.preview_lbl.setFixedSize(self.PREVIEW_SIZE, self.PREVIEW_SIZE)
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        self.preview_lbl.setStyleSheet(_BORDER_NO_IMG)
        self.preview_lbl.setPixmap(make_placeholder_pixmap(self.PREVIEW_SIZE))
        row.addWidget(self.preview_lbl)

        # ── Columna de botones ───────────────────────────────
        btn_col = QVBoxLayout()
        btn_col.setSpacing(5)

        self.btn_browse = QPushButton("📂 Examinar")
        self.btn_browse.setFixedHeight(28)
        self.btn_browse.setAutoDefault(False)
        self.btn_browse.setDefault(False)
        self.btn_browse.setStyleSheet(
            _BTN_BASE.format(bg="#3A3F47", fg="#E0E0E0", border="#555")
            + "QPushButton:hover { background-color: #5B9BD5; color: white; }"
        )
        self.btn_browse.clicked.connect(self._browse)
        btn_col.addWidget(self.btn_browse)

        self.btn_clear = QPushButton("✖ Quitar imagen")
        self.btn_clear.setFixedHeight(28)
        self.btn_clear.setAutoDefault(False)
        self.btn_clear.setDefault(False)
        self.btn_clear.setEnabled(False)
        self.btn_clear.setStyleSheet(
            _BTN_BASE.format(bg="#3A3F47", fg="#AAAAAA", border="#444")
            + "QPushButton:hover:enabled { background-color: #DC3545; color: white; border-color: #DC3545; }"
            + "QPushButton:disabled { color: #555; border-color: #333; }"
        )
        self.btn_clear.clicked.connect(self._clear)
        btn_col.addWidget(self.btn_clear)

        # Nombre del archivo (truncado)
        self.path_lbl = QLabel("Sin imagen")
        self.path_lbl.setStyleSheet("color: #6B7280; font-size: 10px;")
        self.path_lbl.setMaximumWidth(170)
        btn_col.addWidget(self.path_lbl)
        btn_col.addStretch()

        row.addLayout(btn_col)
        row.addStretch()
        layout.addLayout(row)

    # ── API pública ───────────────────────────────────────────────────────────

    def get_path(self) -> str:
        """Devuelve la ruta actual ('' si no hay imagen)."""
        return self._path

    def set_path(self, path: str):
        """Establece la ruta y actualiza la UI."""
        self._path = path or ""
        self._refresh()
        self.path_changed.emit(self._path)

    # ── Slots privados ────────────────────────────────────────────────────────

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar imagen del producto",
            self._path or "",
            "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
        )
        if path:
            self.set_path(path)

    def _clear(self):
        self.set_path("")

    # ── Refresco visual ───────────────────────────────────────────────────────

    def _refresh(self):
        if self._path:
            pm = load_preview(self._path, self.PREVIEW_SIZE)
            self.preview_lbl.setPixmap(pm)
            self.preview_lbl.setStyleSheet(_BORDER_WITH_IMG)

            filename = os.path.basename(self._path)
            if len(filename) > 22:
                filename = filename[:19] + "…"
            self.path_lbl.setText(filename)
            self.path_lbl.setStyleSheet("color: #9CA3AF; font-size: 10px;")
            self.btn_clear.setEnabled(True)
        else:
            self.preview_lbl.setPixmap(make_placeholder_pixmap(self.PREVIEW_SIZE))
            self.preview_lbl.setStyleSheet(_BORDER_NO_IMG)
            self.path_lbl.setText("Sin imagen")
            self.path_lbl.setStyleSheet("color: #6B7280; font-size: 10px;")
            self.btn_clear.setEnabled(False)