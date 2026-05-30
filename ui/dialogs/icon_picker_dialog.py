from PySide6.QtWidgets import QDialog, QGridLayout, QPushButton, QVBoxLayout

ICON_OPTIONS = [
    "📦","🛒","🍎","🥤","🍬","🥖","🥩","🥫","🧴","🧼",
    "💄","💊","🏥","🐶","🌿","🌱","🧪","🔧","🪛","💡",
    "🚗","🛞","🛢","🏠","🛏","🪑","🍽","🧊","📚","🖊",
    "🏫","💻","📱","🎮","📺","🔌","👕","👟","👜","💍",
    "🧸","🎁","🎉","❤️","🎄","🎃","🏀","🎨","📷","🏢",
    "🎅","🎶","🎼","🎄","🍻","✝️","🎸","👻","🍏",
    "⚽","🍔","🍴","🔨"
]


class IconPickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Seleccionar Ícono")
        self.selected_icon = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        grid = QGridLayout()

        row = 0
        col = 0

        for icon in ICON_OPTIONS:
            btn = QPushButton(icon)
            btn.setFixedSize(50, 50)
            btn.setStyleSheet("""
                QPushButton {
                    font-size: 20px;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #2E86C1;
                }
            """)
            btn.clicked.connect(lambda checked, i=icon: self.select_icon(i))

            grid.addWidget(btn, row, col)

            col += 1
            if col == 10:
                col = 0
                row += 1

        layout.addLayout(grid)
        self.setLayout(layout)

    def select_icon(self, icon):
        self.selected_icon = icon
        self.accept()