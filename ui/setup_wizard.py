"""
ui/setup_wizard.py — Wizard de configuración inicial de base de datos.

Se ejecuta UNA sola vez, en el primer arranque (cuando no existe `.env`
o existe pero no tiene `DB_ENGINE` definido). Permite al usuario elegir
entre SQLite (instalación standalone, una sola caja) o MySQL (instalación
multi-caja con servidor externo), y en el caso de MySQL captura las
credenciales y valida la conexión antes de guardar.

────────────────────────────────────────────────────────────────────────
RESTRICCIÓN CRÍTICA DE IMPORTS — no eliminar ni reorganizar:
────────────────────────────────────────────────────────────────────────
Este módulo NO debe importar nada de `app.core.*` (ni transitivamente).
La razón:

  - `app.core.config` ejecuta `_ensure_secret_key()` y
    `_auto_detect_engine()` en su import, los cuales:
      1. Crean un `.env` por defecto desde `.env.example` si no existe.
      2. Fijan `DB_ENGINE` en `os.environ` (default: "sqlite").
  - `app.core.logger` importa `app.core.config`, así que tampoco.

Si esos efectos ocurrieran antes del wizard, el archivo `.env` ya tendría
una elección por defecto antes de que el usuario pueda decidir, y la
detección de "primer arranque" (`is_setup_needed`) devolvería False
incorrectamente.

Por el mismo motivo, el llamador (`launcher.main`) debe invocar este
wizard ANTES de cualquier `from app.core...`.
"""

import re
import sys
import shutil
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QStackedWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QSpinBox, QMessageBox,
    QFrame, QSizePolicy,
)

logger = logging.getLogger("launcher")  # reutilizamos el logger del launcher

# ── Paleta — coherente con ui/login_view.py ───────────────────────────
VIOLET_ACCENT = "#8b5cf6"
PANEL_BG      = "#12091f"
INPUT_BG      = "#1e1133"
INPUT_BORDER  = "#3b2170"
TEXT_PRIMARY  = "#f0e8ff"
TEXT_MUTED    = "#8b7aaa"

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"


# ══════════════════════════════════════════════════════════════════════
# API pública usada por launcher.main()
# ══════════════════════════════════════════════════════════════════════

def is_setup_needed(app_dir: Path) -> bool:
    """¿Hay que mostrar el wizard en este arranque?

    Retorna True si:
      - El archivo `.env` no existe, o
      - Existe pero NO contiene una línea `DB_ENGINE=sqlite|mysql`
        no comentada con un valor válido.

    Retorna False (skip wizard) si `DB_ENGINE` ya está configurado.
    Esto garantiza que el wizard nunca aparezca en instalaciones
    existentes, ni siquiera si el usuario solo borró otras variables.
    """
    env_path = app_dir / ".env"
    if not env_path.exists():
        return True
    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError:
        # Si no podemos leerlo, asumimos que algo está mal y mostramos
        # el wizard para reconstruir.
        return True

    for raw in content.splitlines():
        if raw.lstrip().startswith("#"):
            continue
        m = re.match(r"^\s*DB_ENGINE\s*=\s*(.+?)\s*$", raw)
        if m:
            value = m.group(1).strip().strip('"').strip("'").lower()
            if value in ("sqlite", "mysql"):
                return False
    return True


def run_setup_wizard(app_dir: Path) -> bool:
    """Ejecuta el wizard modal. Retorna:
      - True  → el usuario completó la configuración (el `.env` ya
                contiene la elección y, si aplica, las credenciales).
      - False → el usuario canceló (cerró sin elegir, ESC, o botón X).
                El wizard ya mostró una advertencia; el llamador debe
                cerrar la app limpia.

    Crea una `QApplication` temporal si no existe, siguiendo el mismo
    patrón que `launcher._handle_migration_failure`.
    """
    if QApplication.instance() is None:
        QApplication(sys.argv)

    dlg = SetupWizard(app_dir)
    return dlg.exec() == QDialog.Accepted


# ══════════════════════════════════════════════════════════════════════
# Helpers de archivo .env (puros, sin Qt — testeables aislados)
# ══════════════════════════════════════════════════════════════════════

_DB_KEYS_TO_CLEAR_FOR_SQLITE = (
    "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME",
)


def _seed_env_from_template(env_path: Path) -> None:
    """Si `.env` no existe, lo crea copiando `.env.example` (preservando
    comentarios) o, si no hay template, como archivo vacío. El upsert
    posterior se encargará de rellenar los campos relevantes.
    """
    if env_path.exists():
        return
    template = env_path.parent / ".env.example"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if template.exists():
        shutil.copy2(template, env_path)
    else:
        env_path.write_text("", encoding="utf-8")


def _upsert_env_var(env_path: Path, key: str, value: str) -> None:
    """Inserta o actualiza una variable en el `.env`.

    Comportamiento:
      - Si la clave ya existe (en cualquier variante: comentada,
        con espacios al inicio, sin comentar), reemplaza la PRIMERA
        aparición con `KEY=value` (sin comentar) y elimina duplicados
        posteriores para la misma clave.
      - Si no existe, la agrega al final del archivo.
      - Crea el archivo si no existe.

    Notas:
      - El valor se escribe sin comillas. Si el usuario tiene caracteres
        exóticos en una contraseña que confunden a python-dotenv, deberá
        editar `.env` a mano y entrecomillar.
      - Maneja el caso de `.env.example` actual que tiene líneas con
        espacio inicial (` DB_USER=root`).
    """
    lines: list[str] = []
    if env_path.exists():
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []

    # Matches: KEY=...   #KEY=...   # KEY=...    KEY=...  (con espacios iniciales)
    pattern = re.compile(rf"^\s*#?\s*{re.escape(key)}\s*=")
    new_lines: list[str] = []
    replaced = False
    for line in lines:
        if pattern.match(line):
            if not replaced:
                new_lines.append(f"{key}={value}")
                replaced = True
            # else: descartamos duplicados (incluidos los comentados)
        else:
            new_lines.append(line)

    if not replaced:
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.append(f"{key}={value}")

    output = "\n".join(new_lines)
    if not output.endswith("\n"):
        output += "\n"

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(output, encoding="utf-8")


def _persist_sqlite_choice(env_path: Path) -> None:
    """Escribe `DB_ENGINE=sqlite` en `.env` y limpia las credenciales
    MySQL del template (`.env.example` trae `DB_USER=root`,
    `DB_PASSWORD=tu_password`, etc.) para no dejar datos sensibles
    aparentando estar en uso.
    """
    _seed_env_from_template(env_path)
    _upsert_env_var(env_path, "DB_ENGINE", "sqlite")
    for key in _DB_KEYS_TO_CLEAR_FOR_SQLITE:
        _upsert_env_var(env_path, key, "")


def _persist_mysql_choice(env_path: Path, *,
                          host: str, port: int, user: str,
                          password: str, db_name: str) -> None:
    """Escribe la elección de MySQL y todas las credenciales en `.env`."""
    _seed_env_from_template(env_path)
    _upsert_env_var(env_path, "DB_ENGINE", "mysql")
    _upsert_env_var(env_path, "DB_HOST", host)
    _upsert_env_var(env_path, "DB_PORT", str(port))
    _upsert_env_var(env_path, "DB_USER", user)
    _upsert_env_var(env_path, "DB_PASSWORD", password)
    _upsert_env_var(env_path, "DB_NAME", db_name)


def _test_mysql_connection(host: str, port: int, user: str,
                           password: str, db_name: str,
                           timeout: int = 5) -> tuple[bool, str]:
    """Prueba la conexión a MySQL usando pymysql directamente (NO
    SQLAlchemy), porque el engine de SQLAlchemy aún no se ha
    inicializado en este punto del arranque.

    Retorna (ok, mensaje_legible).

    En errores conocidos, traduce el código nativo de MySQL a una
    sugerencia accionable para el usuario:
      - 1045 → credenciales inválidas
      - 1049 → la BD no existe (con sugerencia de CREATE DATABASE)
      - 2003 → no se pudo alcanzar el host:puerto
    """
    try:
        import pymysql
    except ImportError:
        return False, (
            "El driver pymysql no está instalado. Esto indica una "
            "instalación corrupta de Violette POS — reinstale la aplicación."
        )

    try:
        conn = pymysql.connect(
            host=host,
            port=int(port),
            user=user,
            password=password,
            database=db_name,
            connect_timeout=timeout,
            charset="utf8mb4",
        )
        conn.close()
        return True, f"✓ Conexión exitosa a '{db_name}' en {host}:{port}."
    except Exception as e:
        msg = str(e)
        if "1049" in msg or "Unknown database" in msg:
            hint = (
                f"\n\nLa base de datos '{db_name}' no existe en el servidor.\n"
                f"Créela primero ejecutando en MySQL:\n"
                f"    CREATE DATABASE {db_name} "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            )
            return False, f"{msg}{hint}"
        if "1045" in msg or "Access denied" in msg:
            return False, (
                f"{msg}\n\nVerifique el usuario y la contraseña, y que el "
                f"usuario tenga permisos sobre la base '{db_name}'."
            )
        if "2003" in msg or "Can't connect" in msg:
            return False, (
                f"{msg}\n\nVerifique que el servidor MySQL esté corriendo "
                f"en {host}:{port} y que el firewall permita la conexión."
            )
        return False, msg


# ══════════════════════════════════════════════════════════════════════
# Widget principal
# ══════════════════════════════════════════════════════════════════════

class SetupWizard(QDialog):
    """Diálogo modal de dos pantallas:
      Pantalla 1 — Bienvenida y elección de motor.
      Pantalla 2 — Credenciales MySQL + prueba de conexión.

    El estilo replica la paleta de `ui/login_view.py` para que el wizard
    se integre visualmente con el resto de la UI.
    """

    def __init__(self, app_dir: Path):
        super().__init__()
        self._app_dir = app_dir
        self._env_path = app_dir / ".env"
        self._mysql_tested_ok = False
        # Bandera para que reject() no muestre warning cuando aceptamos
        # (ej.: tras elegir SQLite o guardar MySQL exitosamente).
        self._completed_ok = False

        self.setWindowTitle("Configuración inicial — Violette POS")
        self.setFixedSize(560, 560)
        self.setModal(True)
        self.setStyleSheet(self._build_stylesheet())

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._build_choice_page())
        self._stack.addWidget(self._build_mysql_page())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._stack)

    # ── Hoja de estilos ────────────────────────────────────────────
    def _build_stylesheet(self) -> str:
        return f"""
            QDialog {{
                background-color: {PANEL_BG};
            }}
            QWidget#page {{
                background-color: {PANEL_BG};
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
                background: transparent;
            }}
            QLabel#title {{
                font-size: 22px;
                font-weight: 800;
                color: {TEXT_PRIMARY};
            }}
            QLabel#subtitle {{
                font-size: 13px;
                color: {TEXT_MUTED};
            }}
            QLabel#hint {{
                font-size: 11px;
                color: {TEXT_MUTED};
                font-style: italic;
            }}
            QLabel#cardDesc {{
                color: {TEXT_MUTED};
                font-size: 12px;
                background: transparent;
            }}
            QLabel#error {{
                color: #ff6b6b;
                font-size: 12px;
                background: transparent;
            }}
            QLabel#success {{
                color: #6bd97a;
                font-size: 12px;
                background: transparent;
            }}
            QLabel#muted {{
                color: {TEXT_MUTED};
                font-size: 12px;
                background: transparent;
            }}
            QFrame#card {{
                background-color: {INPUT_BG};
                border: 1.5px solid {INPUT_BORDER};
                border-radius: 10px;
            }}
            QFrame#card:hover {{
                border: 1.5px solid {VIOLET_ACCENT};
            }}
            QPushButton#cardBtn {{
                background-color: transparent;
                color: {TEXT_PRIMARY};
                border: none;
                text-align: left;
                padding: 0px;
                font-size: 14px;
                font-weight: 700;
            }}
            QPushButton#cardBtn:hover {{
                color: {VIOLET_ACCENT};
            }}
            QLineEdit, QSpinBox {{
                background-color: {INPUT_BG};
                border: 1.5px solid {INPUT_BORDER};
                border-radius: 8px;
                padding: 8px 12px;
                color: {TEXT_PRIMARY};
                font-size: 13px;
            }}
            QLineEdit:focus, QSpinBox:focus {{
                border-color: {VIOLET_ACCENT};
            }}
            QPushButton#primary {{
                background-color: {VIOLET_ACCENT};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton#primary:hover {{
                background-color: #9d6cf7;
            }}
            QPushButton#primary:disabled {{
                background-color: {INPUT_BORDER};
                color: {TEXT_MUTED};
            }}
            QPushButton#secondary {{
                background-color: transparent;
                color: {TEXT_MUTED};
                border: 1.5px solid {INPUT_BORDER};
                border-radius: 8px;
                padding: 10px 18px;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton#secondary:hover {{
                color: {TEXT_PRIMARY};
                border-color: {VIOLET_ACCENT};
            }}
        """

    # ══════════════════════════════════════════════════════════════
    # Pantalla 1: elección de motor
    # ══════════════════════════════════════════════════════════════
    def _build_choice_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 30, 36, 26)
        layout.setSpacing(8)

        # Logo opcional (mismo asset que el splash de primer arranque)
        logo_path = _ASSETS_DIR / "violette_assistant_icon.png"
        if logo_path.exists():
            logo = QLabel()
            logo.setAlignment(Qt.AlignCenter)
            pix = QPixmap(str(logo_path)).scaled(
                56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            logo.setPixmap(pix)
            layout.addWidget(logo)
            layout.addSpacing(2)

        title = QLabel("Bienvenido a Violette POS")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "Es la primera vez que abre la aplicación.\n"
            "Seleccione el tipo de instalación:"
        )
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(16)

        # — Tarjeta SQLite —
        layout.addWidget(self._make_choice_card(
            label_main="SQLite — Instalación simple",
            label_desc=(
                "Una sola caja, sin servidor. La base de datos vive en un "
                "archivo local dentro de la carpeta de Violette POS.\n"
                "Recomendado para la mayoría de usuarios."
            ),
            on_click=self._on_choose_sqlite,
        ))
        layout.addSpacing(10)

        # — Tarjeta MySQL —
        layout.addWidget(self._make_choice_card(
            label_main="MySQL — Instalación avanzada",
            label_desc=(
                "Múltiples cajas, servidor externo, página web. "
                "Requiere un servidor MySQL ya instalado y accesible por "
                "red, con una base de datos creada."
            ),
            on_click=self._on_choose_mysql,
        ))
        layout.addStretch()

        hint = QLabel(
            "Puede cambiar esta elección más adelante editando el archivo .env."
        )
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        return page

    def _make_choice_card(self, *, label_main: str, label_desc: str,
                          on_click) -> QFrame:
        """Crea una "tarjeta" clickeable con título destacado y descripción.
        El click se dispara desde el botón interno o desde cualquier
        parte del área de la tarjeta.
        """
        card = QFrame()
        card.setObjectName("card")
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumHeight(108)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(6)

        btn = QPushButton(label_main)
        btn.setObjectName("cardBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(on_click)
        v.addWidget(btn)

        desc = QLabel(label_desc)
        desc.setObjectName("cardDesc")
        desc.setWordWrap(True)
        v.addWidget(desc)

        # Click en cualquier parte del card también dispara la acción.
        card.mousePressEvent = lambda ev, b=btn: b.click()
        return card

    def _on_choose_sqlite(self):
        try:
            _persist_sqlite_choice(self._env_path)
        except OSError as e:
            QMessageBox.critical(
                self,
                "Error escribiendo configuración",
                f"No se pudo guardar la configuración en .env:\n\n{e}\n\n"
                f"Verifique los permisos de escritura en:\n{self._app_dir}",
            )
            return
        logger.info("Wizard: usuario eligió SQLite.")
        self._completed_ok = True
        self.accept()

    def _on_choose_mysql(self):
        self._stack.setCurrentIndex(1)
        self._inp_password.setFocus()

    # ══════════════════════════════════════════════════════════════
    # Pantalla 2: credenciales MySQL
    # ══════════════════════════════════════════════════════════════
    def _build_mysql_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 28, 36, 24)
        layout.setSpacing(10)

        title = QLabel("Configurar conexión MySQL")
        title.setObjectName("title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Ingrese los datos del servidor MySQL. La base de datos debe "
            "existir antes de continuar — si no, el botón \"Probar conexión\" "
            "le indicará cómo crearla."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(12)

        # — Formulario —
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._inp_host = QLineEdit("localhost")
        self._inp_port = QSpinBox()
        self._inp_port.setRange(1, 65535)
        self._inp_port.setValue(3306)
        self._inp_user = QLineEdit("root")
        self._inp_password = QLineEdit()
        self._inp_password.setEchoMode(QLineEdit.Password)
        self._inp_password.setPlaceholderText("(contraseña del usuario MySQL)")
        self._inp_db = QLineEdit("violette_db")

        for label, widget in (
            ("Host:", self._inp_host),
            ("Puerto:", self._inp_port),
            ("Usuario:", self._inp_user),
            ("Contraseña:", self._inp_password),
            ("Base de datos:", self._inp_db),
        ):
            lab = QLabel(label)
            lab.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
            form.addRow(lab, widget)

        layout.addLayout(form)

        # — Mensaje de resultado de prueba —
        self._test_msg = QLabel("Pruebe la conexión antes de continuar.")
        self._test_msg.setObjectName("muted")
        self._test_msg.setWordWrap(True)
        self._test_msg.setMinimumHeight(54)
        self._test_msg.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self._test_msg)

        # Invalidar el OK del test si el usuario edita cualquier campo
        # después de una prueba exitosa.
        for w in (self._inp_host, self._inp_user,
                  self._inp_password, self._inp_db):
            w.textChanged.connect(self._invalidate_test)
        self._inp_port.valueChanged.connect(self._invalidate_test)

        layout.addStretch()

        # — Botonera —
        btns = QHBoxLayout()
        btns.setSpacing(10)

        self._btn_back = QPushButton("← Atrás")
        self._btn_back.setObjectName("secondary")
        self._btn_back.clicked.connect(self._on_back_to_choice)
        btns.addWidget(self._btn_back)

        btns.addStretch()

        self._btn_test = QPushButton("Probar conexión")
        self._btn_test.setObjectName("secondary")
        self._btn_test.clicked.connect(self._on_test_connection)
        btns.addWidget(self._btn_test)

        self._btn_continue = QPushButton("Guardar y continuar")
        self._btn_continue.setObjectName("primary")
        self._btn_continue.setEnabled(False)
        self._btn_continue.clicked.connect(self._on_save_mysql)
        btns.addWidget(self._btn_continue)

        layout.addLayout(btns)
        return page

    def _on_back_to_choice(self):
        self._stack.setCurrentIndex(0)

    def _invalidate_test(self, *_):
        """Si los datos cambiaron tras una prueba OK, desactivar el
        botón de continuar para forzar re-validación."""
        if self._mysql_tested_ok:
            self._mysql_tested_ok = False
            self._btn_continue.setEnabled(False)
            self._set_test_msg(
                "Los datos cambiaron — pruebe la conexión nuevamente.",
                kind="muted",
            )

    def _collect_mysql_inputs(self) -> Optional[dict]:
        """Lee y valida campos. Retorna dict si OK, None si faltan datos
        (en cuyo caso ya se mostró un mensaje de error)."""
        host = self._inp_host.text().strip()
        port = self._inp_port.value()
        user = self._inp_user.text().strip()
        password = self._inp_password.text()  # NO strip — los espacios cuentan
        db_name = self._inp_db.text().strip()

        missing = []
        if not host:
            missing.append("Host")
        if not user:
            missing.append("Usuario")
        if not db_name:
            missing.append("Base de datos")
        if missing:
            self._set_test_msg(
                f"Campos requeridos: {', '.join(missing)}.",
                kind="error",
            )
            return None
        return dict(host=host, port=port, user=user,
                    password=password, db_name=db_name)

    def _on_test_connection(self):
        data = self._collect_mysql_inputs()
        if data is None:
            return

        # Bloquear la UI durante el intento (timeout de 5s).
        # Nota: usamos blocking + processEvents para mantener simple el
        # código. Un QThread sería más limpio pero excesivo dado que la
        # ventana es corta y el timeout es acotado.
        self._btn_test.setEnabled(False)
        self._btn_test.setText("Probando…")
        self._btn_continue.setEnabled(False)
        self.setCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            ok, msg = _test_mysql_connection(**data, timeout=5)
        finally:
            self.unsetCursor()
            self._btn_test.setEnabled(True)
            self._btn_test.setText("Probar conexión")

        self._set_test_msg(msg, kind="success" if ok else "error")
        self._mysql_tested_ok = ok
        self._btn_continue.setEnabled(ok)
        if ok:
            logger.info(
                "Wizard: prueba de conexión MySQL exitosa "
                "(host=%s port=%s db=%s)",
                data["host"], data["port"], data["db_name"],
            )

    def _set_test_msg(self, text: str, *, kind: str):
        """kind ∈ {'success', 'error', 'muted'}"""
        self._test_msg.setText(text)
        self._test_msg.setObjectName(kind)
        # Forzar re-aplicación del stylesheet tras cambiar el objectName
        self._test_msg.style().unpolish(self._test_msg)
        self._test_msg.style().polish(self._test_msg)

    def _on_save_mysql(self):
        if not self._mysql_tested_ok:
            self._set_test_msg(
                "Pruebe la conexión primero.", kind="error",
            )
            return
        data = self._collect_mysql_inputs()
        if data is None:
            return
        try:
            _persist_mysql_choice(self._env_path, **data)
        except OSError as e:
            QMessageBox.critical(
                self,
                "Error escribiendo configuración",
                f"No se pudo guardar la configuración en .env:\n\n{e}",
            )
            return
        logger.info(
            "Wizard: configuración MySQL guardada en .env "
            "(host=%s port=%s db=%s).",
            data["host"], data["port"], data["db_name"],
        )
        self._completed_ok = True
        self.accept()

    # ══════════════════════════════════════════════════════════════
    # Cancelación / cierre sin elegir
    # ══════════════════════════════════════════════════════════════
    def reject(self):
        """Llamado al cerrar con ESC, X de la ventana, o programáticamente.

        Mostramos advertencia explicando que la app no puede continuar
        sin configurar la BD, y dejamos que el llamador (launcher)
        decida cerrar la aplicación.
        """
        if self._completed_ok:
            # No debería ocurrir (accept() no llama reject()), pero por
            # robustez no mostramos advertencia si la elección ya fue
            # persistida.
            super().reject()
            return

        QMessageBox.warning(
            self,
            "Configuración requerida",
            "Violette POS necesita una base de datos configurada para "
            "funcionar.\n\n"
            "La aplicación se cerrará. Vuelva a abrirla cuando esté "
            "listo para completar la configuración.",
        )
        logger.warning(
            "Wizard cerrado por el usuario sin elegir motor de BD."
        )
        super().reject()