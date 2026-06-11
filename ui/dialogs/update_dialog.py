"""
ui/dialogs/update_dialog.py — Diálogo "Actualización disponible".

Se abre cuando check_update() detecta una versión más nueva en GitHub
Releases. Muestra la versión nueva y el changelog, y permite descargar e
instalar la actualización.

Flujo interno (todo sobre el modelo seguro de la app):
  · "Actualizar ahora" → download_async() (en segundo plano, vía run_async,
    sin congelar la UI) → al terminar, apply_update_and_exit(): lanza el
    instalador /VERYSILENT y cierra Violette POS para que Inno reemplace los
    archivos. La app se reabre ya actualizada.
  · "Después" → cierra el diálogo sin hacer nada.

La descarga se muestra con un indicador INDETERMINADO (no porcentual): con el
patrón run_async, mostrar una barra con porcentaje real exigiría reportar
bytes desde el hilo de red, lo que añade complejidad por poco valor en una
descarga única. El cursor de espera + "Descargando…" es suficiente.

Paleta violeta/oscura coherente con login_view.py / password_recovery_dialog.py
(se redeclara local para que el archivo sea auto-contenido).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QProgressDialog, QMessageBox, QApplication,
)

from ui.services.update_manager import download_async, apply_update_and_exit

# ── Paleta — coherente con el resto de diálogos ──────────────────────
PANEL_BG      = "#12091f"
INPUT_BG      = "#1e1133"
INPUT_BORDER  = "#3b2170"
VIOLET_ACCENT = "#8b5cf6"
TEXT_PRIMARY  = "#f0e8ff"
TEXT_MUTED    = "#8b7aaa"


class UpdateDialog(QDialog):
    """Diálogo de actualización disponible.

    Args:
        check_result: dict devuelto por updater.check_update() con, al menos,
                      'current_version', 'latest_version', 'changelog',
                      'required'.
        parent: ventana padre (para centrar y heredar contexto).
    """

    def __init__(self, check_result: dict, parent=None):
        super().__init__(parent)
        self._result = check_result or {}
        self._progress = None

        current = self._result.get("current_version", "?")
        latest = self._result.get("latest_version", "?")
        changelog = self._result.get("changelog") or "Sin notas de versión."
        required = bool(self._result.get("required"))

        self.setWindowTitle("Actualización disponible — Violette POS")
        self.setMinimumSize(520, 480)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {PANEL_BG}; }}
            QLabel {{ color: {TEXT_PRIMARY}; background: transparent; }}
            QTextEdit {{
                background-color: {INPUT_BG};
                border: 1.5px solid {INPUT_BORDER};
                border-radius: 8px;
                color: {TEXT_PRIMARY};
                padding: 8px;
                font-size: 13px;
            }}
            QPushButton {{
                background-color: transparent;
                color: {TEXT_PRIMARY};
                border: 1.5px solid {INPUT_BORDER};
                border-radius: 8px;
                padding: 10px 18px;
                font-size: 14px;
            }}
            QPushButton:hover {{ border-color: {VIOLET_ACCENT}; }}
            QPushButton#primary {{
                background-color: {VIOLET_ACCENT};
                color: white; border: none; font-weight: bold;
            }}
            QPushButton#primary:hover {{ background-color: #7c4ddb; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("🚀 Hay una nueva versión disponible")
        title.setStyleSheet("font-size: 19px; font-weight: bold;")
        root.addWidget(title)

        version_line = QLabel(f"Versión instalada: {current}    →    Nueva versión: {latest}")
        version_line.setStyleSheet(f"color: {VIOLET_ACCENT}; font-size: 14px; font-weight: bold;")
        root.addWidget(version_line)

        if required:
            req = QLabel("⚠️ Esta actualización es importante y se recomienda instalarla cuanto antes.")
            req.setWordWrap(True)
            req.setStyleSheet("color: #fca5a5; font-size: 13px;")
            root.addWidget(req)

        notes_label = QLabel("Novedades:")
        notes_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        root.addWidget(notes_label)

        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        # Render markdown si está disponible (changelog de GitHub); si no,
        # texto plano. Defensivo ante versiones de Qt sin setMarkdown.
        try:
            self.notes.setMarkdown(changelog)
        except Exception:
            self.notes.setPlainText(changelog)
        root.addWidget(self.notes, 1)

        # Aviso de qué pasará al actualizar.
        info = QLabel(
            "Al actualizar, Violette POS se cerrará brevemente, instalará la "
            "nueva versión y se reabrirá automáticamente. Tus datos y ventas "
            "se conservan."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        root.addWidget(info)

        # Botones
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_later = QPushButton("Después")
        self.btn_later.clicked.connect(self.reject)
        buttons.addWidget(self.btn_later)

        self.btn_update = QPushButton("Actualizar ahora")
        self.btn_update.setObjectName("primary")
        self.btn_update.clicked.connect(self._on_update_now)
        buttons.addWidget(self.btn_update)
        root.addLayout(buttons)

    # ──────────────────────────────────────────────────────────────
    def _on_update_now(self):
        """Descarga el instalador y, al terminar, aplica el relevo."""
        self.btn_update.setEnabled(False)
        self.btn_later.setEnabled(False)

        # Progreso indeterminado, no cancelable (None como botón de cancelar).
        self._progress = QProgressDialog(
            "Descargando actualización…\nPor favor espera, no cierres la aplicación.",
            None, 0, 0, self,
        )
        self._progress.setWindowTitle("Actualizando Violette POS")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setMinimumWidth(420)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.show()
        # Forzar el primer render del diálogo de progreso antes de la descarga.
        QApplication.processEvents()

        # download_async usa run_async: corre en hilo de red puro y vuelve por
        # callbacks en el hilo principal, bombeando eventos para no congelar.
        download_async(
            on_success=self._on_downloaded,
            on_error=self._on_download_error,
            on_finished=self._on_download_finished,
        )

    def _on_downloaded(self, result: dict):
        """Callback de éxito de la descarga (en el hilo principal)."""
        result = result or {}
        if result.get("downloaded") and result.get("path"):
            self._close_progress()
            # apply_update_and_exit NO retorna si el instalador se lanza bien:
            # cierra el proceso (os._exit) para liberar el .exe.
            ok = apply_update_and_exit(result["path"], app=QApplication.instance())
            if not ok:
                # Solo llega aquí si NO se pudo lanzar el instalador.
                self._reenable()
                QMessageBox.critical(
                    self, "Error",
                    "No se pudo iniciar el instalador de la actualización.\n"
                    "Intenta de nuevo o descarga la nueva versión manualmente.",
                )
        else:
            # La descarga no se concretó (p. ej. SHA-256 inválido, error de red).
            self._close_progress()
            self._reenable()
            QMessageBox.warning(
                self, "No se pudo actualizar",
                result.get("message") or "No se pudo descargar la actualización.",
            )

    def _on_download_error(self, msg: str):
        """Callback de error inesperado de la descarga."""
        self._close_progress()
        self._reenable()
        QMessageBox.critical(self, "Error de descarga", str(msg))

    def _on_download_finished(self):
        """Siempre se ejecuta al terminar; cierre defensivo del progreso."""
        self._close_progress()

    # ──────────────────────────────────────────────────────────────
    def _close_progress(self):
        if self._progress is not None:
            try:
                self._progress.close()
            except Exception:
                pass
            self._progress = None

    def _reenable(self):
        self.btn_update.setEnabled(True)
        self.btn_later.setEnabled(True)