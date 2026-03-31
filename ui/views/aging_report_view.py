"""
aging_report_view.py
Reporte global de aging de crédito. Exportable a Excel.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QFileDialog, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
import requests
import csv
import io
from ui.session_manager import session
from ui.api import BASE_URL

API_URL = f"{BASE_URL}/customers/reports/aging"


class AgingReportView(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 Reporte de Aging de Crédito")
        self.resize(950, 600)
        self.setModal(True)
        self._data = None

        self.setup_ui()
        self.load_report()

    def _auth(self):
        return {"Authorization": f"Bearer {session.token}"}

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("📊 Reporte de Aging de Crédito — Todos los Clientes")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #E8E8E8;")
        layout.addWidget(title)

        # ── Totales ──
        totals_frame = QFrame()
        totals_frame.setStyleSheet("QFrame { background-color: #1e1e1e; border-radius: 8px; padding: 8px; }")
        totals_layout = QHBoxLayout(totals_frame)

        self.lbl_total = QLabel("Total: ₡0.00")
        self.lbl_total.setStyleSheet("font-size: 16px; font-weight: bold; color: #ef4444;")
        self.lbl_0_30 = self._aging_lbl("0-30d", "#3b82f6")
        self.lbl_31_60 = self._aging_lbl("31-60d", "#f59e0b")
        self.lbl_61_90 = self._aging_lbl("61-90d", "#f97316")
        self.lbl_90_plus = self._aging_lbl("+90d", "#ef4444")

        totals_layout.addWidget(self.lbl_total)
        totals_layout.addStretch()
        totals_layout.addWidget(self.lbl_0_30)
        totals_layout.addWidget(self.lbl_31_60)
        totals_layout.addWidget(self.lbl_61_90)
        totals_layout.addWidget(self.lbl_90_plus)
        layout.addWidget(totals_frame)

        # ── Tabla ──
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "ID", "Nombre", "Identificación", "Teléfono",
            "0-30 días", "31-60 días", "61-90 días", "+90 días"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #2b2b2b; color: #fff; gridline-color: #444; font-size: 13px; }
            QHeaderView::section { background-color: #1e88e5; padding: 5px; border: none; color: white; font-weight: bold; }
        """)
        layout.addWidget(self.table, stretch=1)

        # ── Botones ──
        btn_layout = QHBoxLayout()

        self.btn_export = QPushButton("📥 Exportar Excel/CSV")
        self.btn_export.clicked.connect(self.export_csv)
        self.btn_export.setStyleSheet("background-color: #28A745; color: white; font-weight: bold; padding: 8px 16px; border-radius: 6px;")

        btn_refresh = QPushButton("🔄 Refrescar")
        btn_refresh.clicked.connect(self.load_report)
        btn_refresh.setStyleSheet("background-color: #17A2B8; color: white; font-weight: bold; padding: 8px 16px; border-radius: 6px;")

        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.close)
        btn_close.setStyleSheet("background-color: #444; color: white; padding: 8px 16px; border-radius: 6px;")

        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(btn_refresh)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _aging_lbl(self, label, color):
        lbl = QLabel(f"{label}: ₡0")
        lbl.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold; padding: 0 8px;")
        return lbl

    def load_report(self):
        try:
            r = requests.get(API_URL, headers=self._auth(), timeout=15)
            if r.status_code != 200:
                QMessageBox.warning(self, "Error", f"No se pudo cargar el reporte.\n{r.text}")
                return

            data = r.json().get("data", {})
            self._data = data
            items = data.get("items", [])
            totals = data.get("totals", {})

            self.lbl_total.setText(f"Total adeudado: ₡{totals.get('total', 0):,.2f}")
            self.lbl_0_30.setText(f"0-30d: ₡{totals.get('0_30', 0):,.2f}")
            self.lbl_31_60.setText(f"31-60d: ₡{totals.get('31_60', 0):,.2f}")
            self.lbl_61_90.setText(f"61-90d: ₡{totals.get('61_90', 0):,.2f}")
            self.lbl_90_plus.setText(f"+90d: ₡{totals.get('90_plus', 0):,.2f}")

            self.table.setRowCount(len(items))
            for row, it in enumerate(items):
                self.table.setItem(row, 0, QTableWidgetItem(str(it["customer_id"])))
                self.table.setItem(row, 1, QTableWidgetItem(it["name"]))
                self.table.setItem(row, 2, QTableWidgetItem(it.get("id_number", "")))
                self.table.setItem(row, 3, QTableWidgetItem(it.get("phone", "")))

                for col, key, color in [
                    (4, "0_30", "#3b82f6"), (5, "31_60", "#f59e0b"),
                    (6, "61_90", "#f97316"), (7, "90_plus", "#ef4444"),
                ]:
                    val = it.get(key, 0)
                    item = QTableWidgetItem(f"₡{val:,.2f}")
                    if val > 0:
                        item.setForeground(QColor(color))
                    self.table.setItem(row, col, item)

            self.table.resizeColumnsToContents()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error cargando reporte:\n{e}")

    def export_csv(self):
        if not self._data:
            QMessageBox.warning(self, "Sin datos", "Carga el reporte primero.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar reporte", "aging_credito.csv", "CSV (*.csv)"
        )
        if not path:
            return

        try:
            items = self._data.get("items", [])
            totals = self._data.get("totals", {})

            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["ID", "Nombre", "Identificación", "Teléfono",
                                 "Saldo Total", "0-30 días", "31-60 días", "61-90 días", "+90 días"])
                for it in items:
                    writer.writerow([
                        it["customer_id"], it["name"], it.get("id_number", ""),
                        it.get("phone", ""), it.get("balance", 0),
                        it.get("0_30", 0), it.get("31_60", 0),
                        it.get("61_90", 0), it.get("90_plus", 0),
                    ])
                writer.writerow([])
                writer.writerow(["", "TOTALES", "", "",
                                 totals.get("total", 0), totals.get("0_30", 0),
                                 totals.get("31_60", 0), totals.get("61_90", 0),
                                 totals.get("90_plus", 0)])

            QMessageBox.information(self, "Éxito", f"Reporte exportado a:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error exportando:\n{e}")
