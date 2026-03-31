from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt


class KPICard(QFrame):
    def __init__(
        self,
        title: str,
        value: str = "—",
        subtitle: str = "",
        trend_text: str = "",
        parent=None
    ):
        super().__init__(parent)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(132)
        self.setMaximumHeight(132)

        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background-color: #1f2933;
                border-radius: 16px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(16, 14, 16, 14)

        # -------------------------
        # Título
        # -------------------------
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("""
            color: #9ca3af;
            font-size: 13px;
        """)
        layout.addWidget(self.lbl_title)

        # -------------------------
        # Valor principal
        # -------------------------
        self.lbl_value = QLabel(value)
        self.lbl_value.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: #e5e7eb;
        """)
        self.lbl_value.setAlignment(Qt.AlignLeft)
        layout.addWidget(self.lbl_value)

        # -------------------------
        # Tendencia
        # -------------------------
        self.lbl_trend = QLabel(trend_text)
        self.lbl_trend.setStyleSheet("""
            color: #6b7280;
            font-size: 11px;
            font-weight: 600;
        """)
        self.lbl_trend.setAlignment(Qt.AlignLeft)
        self.lbl_trend.setVisible(bool(trend_text))
        layout.addWidget(self.lbl_trend)

        # -------------------------
        # Subtítulo
        # -------------------------
        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setStyleSheet("""
            color: #6b7280;
            font-size: 12px;
        """)
        layout.addWidget(self.lbl_sub)

    # -------------------------
    # Tendencia dinámica
    # -------------------------
    def set_trend(self, text: str = "", trend_type: str = "neutral"):
        self.lbl_trend.setText(text or "")
        self.lbl_trend.setVisible(bool(text))

        colors = {
            "positive": "#22c55e",
            "negative": "#ef4444",
            "warning":  "#f59e0b",
            "neutral":  "#9ca3af",
        }

        color = colors.get(trend_type, colors["neutral"])
        self.lbl_trend.setStyleSheet(f"""
            color: {color};
            font-size: 11px;
            font-weight: 600;
        """)

    # -------------------------
    # Update dinámico
    # -------------------------
    def set_value(
        self,
        value: str,
        subtitle: str = "",
        trend_text: str | None = None,
        trend_type: str = "neutral"
    ):
        self.lbl_value.setText(value)

        if subtitle is not None:
            self.lbl_sub.setText(subtitle)

        if trend_text is not None:
            self.set_trend(trend_text, trend_type)