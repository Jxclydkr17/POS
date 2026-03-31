from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve


class Toast(QWidget):
    def __init__(self, message, success=True, duration=3000, parent=None):
        super().__init__(parent)
        self._closing = False
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFixedSize(320, 80)

        # 🔹 Diseño general
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        lbl = QLabel(message)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                font-weight: 600;
            }
        """)
        layout.addWidget(lbl)

        bg_color = "#2ecc71" if success else "#e74c3c"
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_color};
                border-radius: 10px;
                border: 1px solid rgba(255,255,255,0.1);
            }}
        """)

        # 🔸 Efecto de transparencia
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)

        # Fade-in
        self.animation_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.animation_in.setDuration(500)
        self.animation_in.setStartValue(0)
        self.animation_in.setEndValue(1)
        self.animation_in.setEasingCurve(QEasingCurve.OutCubic)
        self.animation_in.start()

        # 🔸 Cerrar automáticamente después del tiempo indicado
        QTimer.singleShot(duration, self.fade_out)

    def fade_out(self):
        """Efecto de salida (fade out) antes de cerrar."""
        if self._closing:
            return
        self._closing = True
        self.animation_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.animation_out.setDuration(800)
        self.animation_out.setStartValue(1)
        self.animation_out.setEndValue(0)
        self.animation_out.setEasingCurve(QEasingCurve.InOutCubic)
        self.animation_out.finished.connect(self.safe_close)
        self.animation_out.start()

    def safe_close(self):
        """Evita errores de repintado al cerrar el toast (soluciona GetDC failed)."""
        try:
            self.setUpdatesEnabled(False)
            self.hide()
            self.close()
        except RuntimeError:
            pass

    def paintEvent(self, event):
        """Evita repintado si ya se está cerrando."""
        if self._closing:
            return
        super().paintEvent(event)


def show_toast(message, success=True, parent=None, duration=3000):
    """Muestra el toast en la esquina inferior derecha de la ventana padre."""
    toast = Toast(message, success=success, duration=duration, parent=parent)

    # Posición respecto a la ventana principal
    if parent:
        geo = parent.geometry()
        x = geo.x() + geo.width() - toast.width() - 20
        y = geo.y() + geo.height() - toast.height() - 40
    else:
        # Si no hay ventana padre, lo muestra en una posición fija
        x, y = 100, 100

    toast.move(x, y)
    toast.show()