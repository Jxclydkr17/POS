from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QWidget, QHBoxLayout
from PySide6.QtCore import Qt


class TopListCard(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None):
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

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("""
            font-size: 15px;
            font-weight: 700;
            color: #e5e7eb;
        """)
        layout.addWidget(self.lbl_title)

        self.lbl_subtitle = QLabel(subtitle)
        self.lbl_subtitle.setStyleSheet("""
            font-size: 12px;
            color: #9ca3af;
        """)
        layout.addWidget(self.lbl_subtitle)

        self.items_container = QVBoxLayout()
        self.items_container.setSpacing(8)
        layout.addLayout(self.items_container)

        layout.addStretch()

    def _clear_items(self):
        while self.items_container.count():
            item = self.items_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def set_items(self, items: list[dict], empty_text: str = "Sin datos"):
        self._clear_items()

        if not items:
            lbl = QLabel(empty_text)
            lbl.setStyleSheet("color: #9ca3af; font-size: 12px; padding: 8px 0;")
            self.items_container.addWidget(lbl)
            return

        for idx, item in enumerate(items, start=1):
            row = QFrame()
            row.setStyleSheet("""
                QFrame {
                    background-color: #111827;
                    border-radius: 10px;
                    padding: 8px;
                }
            """)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(4)

            top = QHBoxLayout()
            top.setSpacing(8)

            lbl_name = QLabel(f"{idx}. {item.get('name', '—')}")
            lbl_name.setStyleSheet("font-size: 13px; font-weight: 600; color: #f3f4f6;")
            lbl_name.setWordWrap(True)

            lbl_value = QLabel(str(item.get("value", "—")))
            lbl_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl_value.setStyleSheet("font-size: 13px; font-weight: 700; color: #60a5fa;")

            top.addWidget(lbl_name, 1)
            top.addWidget(lbl_value)

            row_layout.addLayout(top)

            detail = item.get("detail")
            if detail:
                lbl_detail = QLabel(detail)
                lbl_detail.setWordWrap(True)
                lbl_detail.setStyleSheet("font-size: 11px; color: #9ca3af;")
                row_layout.addWidget(lbl_detail)

            self.items_container.addWidget(row)