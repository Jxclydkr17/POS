"""
Utilidad para corregir los colores rojos de fin de semana
en los QCalendarWidget / QDateEdit de toda la aplicación.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCharFormat, QColor


def fix_calendar_colors(date_edit):
    """
    Aplica formato de texto neutro (blanco/claro) a los días
    sábado y domingo del calendario popup de un QDateEdit,
    eliminando el rojo por defecto de Qt.
    """
    cal = date_edit.calendarWidget()
    if cal is None:
        return

    # Formato para días de fin de semana — mismo color que días normales
    fmt = QTextCharFormat()
    fmt.setForeground(QColor("#e5e7eb"))

    cal.setWeekdayTextFormat(Qt.Saturday, fmt)
    cal.setWeekdayTextFormat(Qt.Sunday, fmt)

    # Estilo del calendario
    cal.setStyleSheet("""
        QCalendarWidget QAbstractItemView {
            background-color: #1e1e2e;
            color: #e5e7eb;
            selection-background-color: #2563eb;
            selection-color: #ffffff;
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
    """)