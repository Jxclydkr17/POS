from io import BytesIO
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


class PerformanceChartCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setStyleSheet("""
            QFrame {
                background-color: #1f2933;
                border-radius: 16px;
                padding: 12px;
            }
            QLabel {
                background: transparent;
                color: #e5e7eb;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.lbl_title = QLabel("Rendimiento últimos 7 días")
        self.lbl_title.setStyleSheet("""
            font-size: 16px;
            font-weight: 700;
            color: #e5e7eb;
        """)
        layout.addWidget(self.lbl_title)

        self.lbl_subtitle = QLabel("Ventas, gastos y utilidad")
        self.lbl_subtitle.setStyleSheet("""
            font-size: 12px;
            color: #9ca3af;
        """)
        layout.addWidget(self.lbl_subtitle)

        self.chart_label = QLabel("Cargando gráfica...")
        self.chart_label.setAlignment(Qt.AlignCenter)
        self.chart_label.setFixedHeight(280)
        self.chart_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.chart_label)

        self._original_pixmap = None

    def set_chart_data(self, chart_data: list[dict]):
        if not chart_data:
            self.chart_label.clear()
            self._original_pixmap = None
            self.chart_label.setText("Sin datos para los últimos 7 días.")
            return

        fechas = [item.get("fecha", "")[5:] for item in chart_data]  # MM-DD
        ventas = [float(item.get("ventas", 0) or 0) for item in chart_data]
        gastos = [float(item.get("gastos", 0) or 0) for item in chart_data]
        utilidad = [float(item.get("utilidad", 0) or 0) for item in chart_data]

        # FASE 5.3 — API orientada a objetos con canvas Agg (sin pyplot).
        # pyplot mantiene un registro GLOBAL de figuras (estado compartido,
        # no thread-safe) y, al estar activo el backend QtAgg por las otras
        # vistas, creaba un figure-manager de Qt solo para guardar a PNG. Con
        # Figure + FigureCanvasAgg el render es local, sin estado global y
        # desacoplado del backend GUI.
        fig = Figure(figsize=(9, 3.6))
        FigureCanvasAgg(fig)  # canvas Agg off-screen (no GUI)
        fig.patch.set_facecolor("#1f2933")
        ax = fig.add_subplot(111)
        ax.set_facecolor("#1f2933")

        ax.plot(fechas, ventas, marker="o", linewidth=2, label="Ventas")
        ax.plot(fechas, gastos, marker="o", linewidth=2, label="Gastos")
        ax.plot(fechas, utilidad, marker="o", linewidth=2, linestyle="--", label="Utilidad")

        ax.set_title("Últimos 7 días", color="#e5e7eb", fontsize=12)
        ax.tick_params(axis="x", colors="#9ca3af")
        ax.tick_params(axis="y", colors="#9ca3af")
        ax.grid(True, alpha=0.20)
        ax.legend()

        for spine in ax.spines.values():
            spine.set_color("#374151")

        fig.tight_layout()

        buf = BytesIO()
        fig.savefig(buf, format="png", transparent=False, facecolor=fig.get_facecolor())
        buf.seek(0)

        self._original_pixmap = QPixmap()
        self._original_pixmap.loadFromData(buf.read())
        self._update_pixmap()

    def _update_pixmap(self):
        if self._original_pixmap and not self._original_pixmap.isNull():
            scaled = self._original_pixmap.scaled(
                self.chart_label.width(),
                self.chart_label.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.chart_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmap()