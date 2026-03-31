from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton
)
from PySide6.QtCore import Qt


class CabysSelectorDialog(QDialog):
    def __init__(self, results):
        super().__init__()
        self.setWindowTitle("Seleccionar CABYS")
        self.setMinimumSize(700, 400)

        self.selected = None
        layout = QVBoxLayout(self)

        label = QLabel("Seleccione el CABYS correcto:")
        label.setStyleSheet("font-weight:bold; font-size:14px;")
        layout.addWidget(label)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Código", "Descripción", "IVA"])
        self.table.setRowCount(len(results))
        self.table.horizontalHeader().setStretchLastSection(True)
        
        
        self.table.setColumnWidth(0, 150)   # Código
        self.table.setColumnWidth(1, 430)   # Descripción (más grande)
        self.table.setColumnWidth(2, 60)    # IVA (más pequeña)

        for row, item in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(item["code"]))
            self.table.setItem(row, 1, QTableWidgetItem(item["description"]))
            self.table.setItem(row, 2, QTableWidgetItem(str(item["iva"])))

            
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 750)
        self.table.setColumnWidth(2, 80)


        for row, item in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(item["code"]))
            self.table.setItem(row, 1, QTableWidgetItem(item["description"]))
            self.table.setItem(row, 2, QTableWidgetItem(str(item["iva"])))

        self.table.cellDoubleClicked.connect(self.select_item)

        layout.addWidget(self.table)

        btn = QPushButton("Cancelar")
        btn.clicked.connect(self.reject)
        layout.addWidget(btn)

    def select_item(self, row, col):
        self.selected = {
            "code": self.table.item(row, 0).text(),
            "description": self.table.item(row, 1).text(),
            "iva": self.table.item(row, 2).text(),
        }
        self.accept()
