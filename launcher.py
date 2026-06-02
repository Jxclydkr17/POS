"""
launcher.py — Punto de entrada principal de Violette POS

Levanta el backend FastAPI en un hilo separado y luego abre la UI PySide6.
Este es el archivo que PyInstaller empaqueta como .exe.

FASE 1 — Fixes aplicados:
  - Fix 1.4: Detección de conflicto de puerto antes de iniciar uvicorn.
             Si el puerto 8000 ya está en uso por otra instancia de Violette,
             se reutiliza. Si es un proceso ajeno, se muestra error claro.
  - Fix 1.5: Eliminada referencia a "styles (1).qss" (artefacto de desarrollo).

FASE 4 (revisión 2026-05) — Fix 4.4: Fallback dinámico de puerto.
  Extiende Fix 1.4: cuando el 8000 está ocupado por un programa AJENO
  (no es otra instancia de Violette), en vez de abortar se prueban
  8001, 8002, ... 8009 hasta encontrar uno libre o detectar una
  instancia ya corriendo. Solo se aborta si toda la franja está
  ocupada. El puerto efectivo se publica vía `API_BASE_URL` para que
  la UI (`ui.api.BASE_URL`) se conecte al puerto correcto.
  El rango es configurable con las variables de entorno
  `VIOLETTE_PORT_RANGE_START` y `VIOLETTE_PORT_RANGE_END`.

FASE 5: Usa logging estructurado con rotación.
"""

import sys
import os
import time
import socket
import threading
import logging
from pathlib import Path

# ── Configurar directorio de trabajo ──
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── FASE 4 — Fix 4.3: Logging con rotación desde el inicio ──
# ── FASE 6 — Fix 6.3: Logs consolidados bajo data/logs/ ──
from logging.handlers import RotatingFileHandler
from pathlib import Path as _LogPath

_app_base = _LogPath(os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, 'frozen', False)
    else __file__
)))
_log_dir = _app_base / "data" / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)

_log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Handler rotativo: 3 archivos × 3MB = máximo 9MB de logs del launcher
_file_handler = RotatingFileHandler(
    str(_log_dir / "launcher.log"),
    maxBytes=3 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setFormatter(_log_formatter)

# Handler de consola para desarrollo
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_formatter)

# ── FASE 4 — Fix 4.8: Logger nombrado en vez de basicConfig ──
# basicConfig() modifica el root logger, lo que causa mensajes duplicados
# cuando app/core/logger.py agrega sus propios handlers de consola.
# Solución: configurar solo el logger "launcher" con sus propios handlers.
logger = logging.getLogger("launcher")
logger.setLevel(logging.INFO)
logger.addHandler(_file_handler)
logger.addHandler(_console_handler)
logger.propagate = False  # evitar que suba al root logger

# ── Puerto y host del backend ──
# BACKEND_PORT y BACKEND_URL son los valores POR DEFECTO.
# Tras `_select_backend_port()` (Fix 4.4), pueden quedar reasignados a otro
# puerto del rango si el 8000 está ocupado por un programa ajeno.
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

# ── FASE 4.4 — Rango de puertos para el fallback dinámico ──
# Por defecto se prueba 8000-8009 (10 puertos). El usuario puede sobrescribir
# con variables de entorno si todos los puertos de esa franja están en uso
# por otros servicios:
#   set VIOLETTE_PORT_RANGE_START=9000
#   set VIOLETTE_PORT_RANGE_END=9009
DEFAULT_PORT_RANGE_START = 8000
DEFAULT_PORT_RANGE_END = 8009


# ──────────────────────────────────────────────────────────────
# Splash de primera ejecución
#
# Se muestra UNA sola vez en la vida de una instalación, mientras corre
# el seed inicial (que incluye la descarga del catálogo CABYS desde el
# BCCR, paso lento de ~20-30s). Sin esto, el launcher parecería
# "congelado" durante toda la descarga.
#
# El splash se construye con QApplication temprana — el mismo
# QApplication singleton es reutilizado luego por _start_ui() (la
# llamada a QApplication.instance() devuelve la existente).
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# FASE 0 — Resolución de recursos empaquetados (read-only)
# ──────────────────────────────────────────────────────────────
# PyInstaller 6.x (onedir) coloca TODOS los archivos empaquetados en
# una subcarpeta `_internal\` y deja solo el .exe en la raíz. Por eso
# los recursos de solo lectura (alembic.ini, la carpeta alembic/, los
# assets de la UI) NO están junto al ejecutable sino en `sys._MEIPASS`
# (= la carpeta `_internal`). Resolverlos con `Path(sys.executable).parent`
# fallaba en el .exe: las migraciones no se aplicaban y el splash no
# encontraba el logo.
#
# NOTA: este helper es una réplica autónoma de
# app.core.config.get_resource_dir(). No se puede importar app.core.*
# tan temprano porque dispararía la carga de config (y la creación del
# .env por defecto) ANTES del wizard de selección de base de datos.
def _resource_dir() -> Path:
    """Raíz de los recursos de solo lectura empaquetados.

    - .exe (PyInstaller onedir): sys._MEIPASS (carpeta _internal).
      Fallback defensivo: carpeta del ejecutable.
    - desarrollo: carpeta de este archivo (raíz del proyecto).
    """
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _alembic_paths() -> tuple[Path | None, Path | None]:
    """Localiza (alembic.ini, carpeta alembic/) en el bundle.

    Devuelve (ini_path, script_location) con la primera ubicación que
    contenga alembic.ini, o (None, None) si no se encuentra.

    Orden de búsqueda:
      1. RESOURCE_DIR (sys._MEIPASS en el .exe = _internal\\).
      2. Carpeta del ejecutable (fallback defensivo para builds con
         layout plano o copias manuales del instalador).
    """
    candidates: list[Path] = []
    rd = _resource_dir()
    candidates.append(rd)
    if getattr(sys, 'frozen', False):
        exe_parent = Path(sys.executable).parent
        if exe_parent != rd:
            candidates.append(exe_parent)
    for base in candidates:
        ini = base / "alembic.ini"
        if ini.exists():
            return ini, base / "alembic"
    return None, None


_ASSETS_DIR = _resource_dir() / "ui" / "assets"


def _make_first_run_splash():
    """
    Crea (no muestra todavía) el QDialog de splash + el QObject puente
    para recibir señales de progreso desde el thread del seed.

    Retorna: (splash, bridge, app) donde:
      - splash: QDialog con label de paso actualizable
      - bridge: QObject con signals `step(str)` y `finished()`
      - app:    QApplication (creado si no existía)
    """
    from PySide6.QtWidgets import (
        QApplication, QDialog, QLabel, QVBoxLayout, QProgressBar,
    )
    from PySide6.QtCore import Qt, QObject, Signal
    from PySide6.QtGui import QPixmap

    # Paleta consistente con login_view BrandPanel.
    PANEL_BG     = "#12091f"
    VIOLET_ACCENT = "#8b5cf6"
    TEXT_PRIMARY = "#f0e8ff"
    TEXT_MUTED   = "#8b7aaa"
    INPUT_BORDER = "#3b2170"

    app = QApplication.instance() or QApplication(sys.argv)

    class _Bridge(QObject):
        step = Signal(str)
        finished = Signal()
    bridge = _Bridge()

    dlg = QDialog()
    dlg.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    dlg.setFixedSize(440, 240)
    dlg.setStyleSheet(f"""
        QDialog {{
            background-color: {PANEL_BG};
            border: 1px solid {INPUT_BORDER};
            border-radius: 12px;
        }}
        QLabel#title  {{ color: {TEXT_PRIMARY}; font-size: 18px; font-weight: 700; }}
        QLabel#sub    {{ color: {TEXT_MUTED};   font-size: 12px; }}
        QLabel#step   {{ color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 500; }}
        QLabel#hint   {{ color: {TEXT_MUTED};   font-size: 10px; font-style: italic; }}
        QProgressBar  {{
            background-color: {INPUT_BORDER};
            border: none;
            border-radius: 4px;
            height: 6px;
        }}
        QProgressBar::chunk {{
            background-color: {VIOLET_ACCENT};
            border-radius: 4px;
        }}
    """)

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(28, 24, 28, 22)
    layout.setSpacing(8)

    # Logo (si existe el asset; si no, omitir sin error)
    logo_path = _ASSETS_DIR / "violette_assistant_icon.png"
    if logo_path.exists():
        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        pix = QPixmap(str(logo_path)).scaled(
            56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        logo.setPixmap(pix)
        layout.addWidget(logo)
        layout.addSpacing(4)

    title = QLabel("Violette POS")
    title.setObjectName("title")
    title.setAlignment(Qt.AlignCenter)
    layout.addWidget(title)

    sub = QLabel("Configurando la base de datos por primera vez")
    sub.setObjectName("sub")
    sub.setAlignment(Qt.AlignCenter)
    layout.addWidget(sub)

    layout.addSpacing(14)

    step_label = QLabel("Iniciando...")
    step_label.setObjectName("step")
    step_label.setAlignment(Qt.AlignCenter)
    step_label.setWordWrap(True)
    layout.addWidget(step_label)

    progress = QProgressBar()
    progress.setRange(0, 0)  # indeterminate
    progress.setTextVisible(False)
    layout.addWidget(progress)

    hint = QLabel("Este paso solo ocurre una vez. Los próximos arranques serán inmediatos.")
    hint.setObjectName("hint")
    hint.setAlignment(Qt.AlignCenter)
    hint.setWordWrap(True)
    layout.addWidget(hint)

    # Conectar signal del bridge al label (cross-thread safe: el bridge
    # vive en main thread; la signal queue automáticamente).
    bridge.step.connect(step_label.setText)

    # Atributos auxiliares para que el llamador centre la ventana, etc.
    dlg._step_label = step_label
    return dlg, bridge, app


def _bootstrap_db_engine_if_needed():
    """Wizard de selección de motor de BD para el primer arranque.

    Se ejecuta ANTES de cualquier `from app.core...` porque:
      - `app.core.config` en su import llama `_ensure_secret_key()` que
        crea un .env por defecto desde .env.example.
      - `app.core.logger` importa `app.core.config`, así que cualquier
        import indirecto también lo dispara.
    Si esos efectos ocurrieran antes del wizard, el .env ya tendría
    `DB_ENGINE=sqlite` por defecto (copiado del template) y el wizard
    no aparecería nunca.

    Si el usuario cierra el wizard sin elegir, ya se le mostró una
    advertencia desde el propio wizard; aquí solo cerramos la app.
    """
    # Determinar APP_DIR localmente, replicando la lógica de
    # app.core.config.get_app_dir(), sin importar config.
    if getattr(sys, 'frozen', False):
        app_dir = Path(sys.executable).parent
    else:
        app_dir = Path(__file__).resolve().parent

    # `ui.setup_wizard` está aislado: no importa nada de app.core.*.
    from ui.setup_wizard import is_setup_needed, run_setup_wizard

    if not is_setup_needed(app_dir):
        return  # ya configurado en arranques previos → flujo normal

    logger.info(
        "Primer arranque: no se encontró DB_ENGINE en .env. "
        "Lanzando wizard de selección de base de datos."
    )
    ok = run_setup_wizard(app_dir)
    if not ok:
        logger.info("Wizard cancelado por el usuario. Cerrando Violette POS.")
        sys.exit(0)
    logger.info("Wizard completado. Continuando con el arranque normal.")


def _first_run_check():
    """Verifica si es la primera ejecución y ejecuta setup inicial.

    FASE 3.10 — Fix 3.10: blinda contra estado inconsistente.

    Antes:
      Si `_initialize_database()` fallaba a mitad (corte de luz, disco
      lleno, error transitorio de SQLite), el archivo `.db` ya estaba
      creado con algunas tablas, sin `alembic_version` correcto. El
      siguiente arranque vería `db_path.exists() == True` y mandaría
      a `_auto_migrate()` que fallaría intentando ejecutar migraciones
      sobre una BD a medio crear.

    Ahora:
      1. Si la inicialización falla, BORRAMOS el archivo `.db` parcial
         antes de re-lanzar el error. El próximo arranque vuelve a
         intentar desde cero limpio.
      2. Si la BD existe, verificamos su consistencia ANTES de
         `_auto_migrate()`. Si faltan tablas declaradas en los modelos
         → abortar con `MigrationFailedError` y dejar que el usuario
         decida (restaurar backup o borrar y empezar de nuevo).
    """
    from app.core.config import settings, is_sqlite, APP_DIR

    if is_sqlite():
        db_path = APP_DIR / settings.db_sqlite_path

        if not db_path.exists():
            logger.info("Primera ejecución detectada. Creando base de datos...")
            try:
                _initialize_database()
            except Exception:
                # FASE 3.10 — Fix 3.10: borrar BD parcial para reintento limpio.
                if db_path.exists():
                    try:
                        db_path.unlink()
                        logger.warning(
                            "Inicialización falló. BD parcial eliminada para "
                            "que el próximo arranque vuelva a intentar limpio."
                        )
                    except Exception as cleanup_err:
                        logger.error(
                            "Inicialización falló Y no se pudo borrar la BD "
                            "parcial: %s. Borre manualmente: %s",
                            cleanup_err, db_path,
                        )
                raise
            return True

        # FASE 3.10 — Fix 3.10: BD existe → verificar consistencia ANTES
        # de intentar migrar. Si está corrupta, fallar limpio con guía.
        ok, issues = _verify_existing_db_health()
        if not ok:
            raise MigrationFailedError(
                "La base de datos existe pero está en estado inconsistente "
                "(probablemente la creación inicial falló a mitad en un arranque previo).",
                backup_path=None,
                details=issues + [
                    f"Para reparar: elimine '{db_path}' y reinicie Violette POS "
                    f"para crear una BD nueva, o restaure manualmente desde "
                    f"el último backup en data/backups/."
                ],
            )

    _auto_migrate()
    return False


def _verify_existing_db_health() -> tuple[bool, list[str]]:
    """
    FASE 3.10 — Fix 3.10: Chequea si una BD pre-existente está sana
    para auto-migrar.

    Retorna (True, []) si es seguro proceder con _auto_migrate().
    Retorna (False, [problemas]) si la BD parece corrupta o a medio crear.

    Side effect controlado:
      Si la BD tiene TODAS las tablas esperadas pero le falta
      `alembic_version` (instalación legacy creada con `create_all`
      sin stamp, pre-Fix 2.6), aplica `stamp head` para sincronizar.
      Esto permite que las migraciones futuras la traten como una
      instalación normal.
    """
    issues: list[str] = []
    try:
        from sqlalchemy import inspect
        from app.db.database import Base, engine
        import app.db.models  # noqa: F401  - registrar modelos en metadata

        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        # Caso 1: BD vacía (archivo existe pero sin tablas)
        if len(tables) == 0:
            issues.append(
                "El archivo de base de datos existe pero está vacío "
                "(0 tablas). Probablemente la creación inicial se "
                "interrumpió antes de aplicar migraciones."
            )
            return False, issues

        # Caso 2: faltan tablas esperadas por los modelos
        expected = set(Base.metadata.tables.keys())
        missing = sorted(expected - tables)
        if missing:
            issues.append(
                f"Faltan tablas declaradas en los modelos: {missing[:8]}"
                + (f" (y {len(missing) - 8} más)" if len(missing) > 8 else "")
            )
            return False, issues

        # Caso 3: tablas completas pero sin alembic_version
        # (instalación legacy pre-Fix 2.6). Stampeamos head para
        # sincronizar y dejar que migraciones futuras sigan normal.
        if "alembic_version" not in tables:
            logger.warning(
                "BD con tablas completas pero sin alembic_version. "
                "Aplicando stamp head para sincronizar (instalación legacy)."
            )
            try:
                _stamp_alembic_head()
            except Exception as e:
                issues.append(
                    f"No se pudo aplicar stamp head a BD legacy: {e}"
                )
                return False, issues

        return True, []

    except Exception as e:
        # Si la verificación rompe por algo no esperado, considerar la BD
        # inválida — mejor que intentar migrarla a ciegas.
        issues.append(f"La verificación de consistencia de BD falló: {e}")
        return False, issues


# ═══════════════════════════════════════════════════════════════
# FASE 2.5 — Fix 2.5: Verificación de consistencia post-migración
# ═══════════════════════════════════════════════════════════════

class MigrationFailedError(Exception):
    """
    La auto-migración Alembic falló y la BD puede estar en estado
    inconsistente. Conserva la ruta del backup pre-migración para
    que `main()` pueda ofrecer al usuario la opción de restaurarlo
    en lugar de seguir con una BD rota.
    """

    def __init__(self, message: str, backup_path: str | None = None,
                 details: list[str] | None = None):
        super().__init__(message)
        self.backup_path = backup_path
        self.details = details or []


def _verify_schema_consistency(expected_head: str | None = None) -> tuple[bool, list[str]]:
    """
    FASE 2.5 — Fix 2.5: Verifica que la BD está en el estado esperado
    después de aplicar migraciones.

    Chequea:
      1. La versión actual de Alembic en BD coincide con HEAD.
      2. Todas las tablas declaradas en los modelos existen en BD.

    NO verifica columnas individuales — eso requeriría una comparación
    exhaustiva que es costosa y propensa a falsos positivos (columnas
    computed, defaults SQL, etc.). Las tablas faltantes son indicador
    suficiente de migración fallida a mitad.

    Args:
        expected_head: revisión Alembic esperada. Si es None, se intenta
                       obtener automáticamente.

    Returns:
        (ok, issues): ok=True si todo está bien; issues=lista de strings
                      describiendo cada problema encontrado.
    """
    issues: list[str] = []

    try:
        from sqlalchemy import inspect
        from app.db.database import Base, engine
        import app.db.models  # noqa: F401  (carga todos los modelos en Base.metadata)

        # 1) Alembic version = HEAD
        from alembic.runtime.migration import MigrationContext
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()

        if expected_head is None:
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            ini_path, _script_loc = _alembic_paths()
            if ini_path is not None:
                cfg = Config(str(ini_path))
                cfg.set_main_option("script_location", str(_script_loc))
                expected_head = ScriptDirectory.from_config(cfg).get_current_head()

        if expected_head and current_rev != expected_head:
            issues.append(
                f"Versión Alembic en BD ({current_rev or '(ninguna)'}) "
                f"no coincide con HEAD esperado ({expected_head})."
            )

        # 2) Tablas declaradas vs tablas reales
        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names())
        expected_tables = set(Base.metadata.tables.keys())

        missing = sorted(expected_tables - actual_tables)
        if missing:
            issues.append(
                f"Tablas declaradas en los modelos que faltan en la BD: {missing}"
            )
        # Tablas extra (no en modelos) NO son problema: alembic_version y
        # tablas legacy son válidas; no las reportamos.

    except Exception as e:
        # Si la propia verificación rompe, NO bloqueamos el arranque por
        # un fallo del verificador. Pero sí lo logueamos como warning.
        logger.warning(
            "No se pudo verificar consistencia del esquema: %s. "
            "Continuando con el arranque.", e,
        )
        return True, []

    return len(issues) == 0, issues


def _initialize_database():
    """
    Crea tablas y datos iniciales en una BD nueva.

    FASE 2.6 — Fix 2.6: Inicialización vía Alembic, no `create_all`.

    Antes:
        Base.metadata.create_all() + alembic stamp head
        Problema: las migraciones futuras DEBÍAN ser idempotentes porque
        `create_all` ya creaba todo el schema y `stamp head` solo marcaba
        la revisión. Si una migración nueva intentaba `op.create_index(...)`
        sobre un índice que `create_all` ya creó implícitamente, fallaba
        con "index already exists".

    Ahora:
        alembic upgrade head desde BD vacía.
        Las migraciones se aplican en orden y dejan `alembic_version`
        correctamente seteada. Cualquier migración futura puede asumir que
        la BD fue construida POR la cadena Alembic — no por SQLAlchemy
        directo. Esto elimina la necesidad de idempotencia y permite que
        las migraciones usen comandos DDL normales (create_table, create_index,
        add_column).

    Fallback: si Alembic no está disponible (caso muy raro: instalación
    rota), se usa `create_all` como red de seguridad. En ese caso se
    advierte en logs porque la BD quedará con `alembic_version` vacío y
    las migraciones futuras pueden requerir intervención manual.

    REVISIÓN CABYS-AUTO: el seed ahora descarga el catálogo CABYS del
    BCCR (paso lento de ~20-30s). Para no congelar al usuario sin
    feedback, el seed se ejecuta en un thread y un splash muestra el
    progreso. Si CABYS falla, se avisa con un QMessageBox amigable y
    se continúa — la tabla queda vacía y el usuario actualiza después.
    """
    try:
        # Cargar todos los modelos (registra en Base.metadata para fallback)
        from app.db.database import Base, engine
        import app.db.models  # noqa: F401

        # ── Ruta correcta: Alembic upgrade head ──
        used_alembic = _initialize_via_alembic()

        if not used_alembic:
            # Fallback solo si Alembic no está disponible
            logger.warning(
                "Alembic no disponible — usando create_all como fallback. "
                "Las migraciones futuras pueden requerir intervención manual."
            )
            Base.metadata.create_all(bind=engine)

        # Datos iniciales (seed) — solo después de que las tablas existen
        logger.info("Insertando datos iniciales...")
        _run_seed_with_splash()

        logger.info("Base de datos inicializada correctamente.")

    except MigrationFailedError:
        raise
    except Exception as e:
        logger.error(f"Error inicializando BD: {e}")
        raise


def _run_seed_with_splash():
    """
    Ejecuta el seed inicial mostrando un splash con progreso.

    Diseño:
      - QApplication se crea acá (si no existe). _start_ui() la reusa.
      - El seed corre en un threading.Thread daemon — NO en el main
        thread — para que el event loop de Qt pueda repintar el splash
        durante las llamadas bloqueantes de `requests.get()` y openpyxl.
      - La comunicación thread→UI se hace exclusivamente vía signals
        Qt sobre un QObject puente (cross-thread safe en PySide6).
      - El main thread espera con QEventLoop (no busy-loop).
      - Cualquier excepción crítica del seed se re-lanza en main thread
        para que el flujo de error existente (_first_run_check) la
        capture y limpie la BD parcial.
      - Si CABYS falla (sub-fallo del seed, no crítico) se muestra un
        QMessageBox amigable. El resto del seed se completó bien.
    """
    import threading
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QMessageBox

    splash, bridge, app = _make_first_run_splash()

    # Centrar en pantalla
    screen = app.primaryScreen().availableGeometry() if app.primaryScreen() else None
    if screen is not None:
        splash.move(
            screen.center().x() - splash.width() // 2,
            screen.center().y() - splash.height() // 2,
        )

    splash.show()
    app.processEvents()  # asegurar que se pinta antes de empezar

    # Resultado del thread (capturado por closure)
    result = {"critical_error": None}

    def _worker():
        try:
            from app.scripts.seed_db import run as run_seed
            # progress_callback es llamado desde este thread; Qt mueve
            # el slot al main thread automáticamente al ser una signal.
            run_seed(
                force=False,
                progress_callback=lambda msg: bridge.step.emit(msg),
            )
        except Exception as e:
            # Solo errores CRÍTICOS llegan acá (seed_cabys nunca propaga).
            result["critical_error"] = e
        finally:
            bridge.finished.emit()

    loop = QEventLoop()
    bridge.finished.connect(loop.quit)

    t = threading.Thread(target=_worker, daemon=True, name="violette-seed")
    t.start()

    loop.exec()  # bloquea hasta que finished se emita
    t.join(timeout=2)  # ya terminó, pero por higiene

    splash.close()
    app.processEvents()

    # Propagar errores críticos (BD se borrará desde _first_run_check)
    if result["critical_error"] is not None:
        raise result["critical_error"]

    # Aviso amigable si CABYS no se pudo descargar — el resto del seed
    # sí terminó bien, así que el arranque continúa normalmente.
    from app.scripts.seed_db import LAST_RUN_RESULT
    if LAST_RUN_RESULT.get("cabys_status") == "failed":
        QMessageBox.information(
            None,
            "Catálogo CABYS no disponible",
            "No se pudo descargar el catálogo CABYS del Banco Central de "
            "Costa Rica en este momento.\n\n"
            "Esto suele deberse a falta de conexión a internet durante la "
            "instalación. Violette POS arrancará normalmente y podrá usar "
            "el sistema; solo el campo CABYS de los productos quedará "
            "vacío hasta que actualice el catálogo.\n\n"
            "Para descargarlo más tarde:\n"
            "    Configuración → CABYS → Actualizar catálogo",
        )


def _initialize_via_alembic() -> bool:
    """
    FASE 2.6 — Fix 2.6: Aplica `alembic upgrade head` desde BD vacía.

    Retorna True si se aplicó correctamente, False si Alembic no está
    disponible (en ese caso el caller usa el fallback `create_all`).

    Levanta MigrationFailedError si Alembic está disponible pero las
    migraciones fallan — no debería ocurrir en una instalación normal,
    pero si pasa, el paquete está roto y el dueño tiene que reinstalar.
    """
    try:
        from alembic.config import Config
        from alembic import command
    except ImportError:
        return False

    ini_path, _script_loc = _alembic_paths()
    if ini_path is None:
        logger.debug("alembic.ini no encontrado en first-run; usando fallback.")
        return False

    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(_script_loc))

    logger.info("Aplicando cadena de migraciones desde cero (upgrade head)...")
    try:
        command.upgrade(alembic_cfg, "head")
        logger.info("Cadena de migraciones aplicada en first-run.")
    except Exception as e:
        logger.error("Error en upgrade inicial: %s", e, exc_info=True)
        raise MigrationFailedError(
            "No se pudo crear la base de datos aplicando las migraciones de Alembic. "
            "Esto suele indicar un paquete de instalación dañado o un problema con "
            "permisos de escritura.",
            backup_path=None,  # No hay backup en first-run
            details=[f"Error inicial: {e}"],
        )

    # Verificación post-creación (defensa frente a fallos silenciosos)
    ok, issues = _verify_schema_consistency()
    if not ok:
        raise MigrationFailedError(
            "La inicialización completó pero el esquema quedó inconsistente.",
            backup_path=None,
            details=issues,
        )

    return True


def _auto_migrate():
    """
    FASE 4 — Fix 4.4: Aplica migraciones Alembic pendientes automáticamente.
    FASE 2.5 — Fix 2.5: Backup obligatorio + verificación de consistencia.

    Flujo:
      1. Detectar si hay migraciones pendientes.
      2. Si las hay, crear backup pre-migración. Si el backup FALLA, no migrar.
      3. Aplicar migraciones.
      4. Verificar consistencia post-migración (versión Alembic + tablas).
      5. Si la migración o la verificación fallan, levantar MigrationFailedError
         con la ruta del backup para que main() ofrezca restaurarlo.

    Casos en los que NO levantamos excepción crítica:
      - Alembic no está instalado/disponible (instalación no usa migrations).
      - No hay migraciones pendientes (no-op).
    """
    try:
        from alembic.config import Config
        from alembic import command
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        from app.db.database import engine
    except ImportError:
        logger.debug("Alembic no disponible, omitiendo auto-migración.")
        return

    # Buscar alembic.ini
    ini_path, _script_loc = _alembic_paths()
    if ini_path is None:
        logger.debug("alembic.ini no encontrado, omitiendo auto-migración.")
        return

    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(_script_loc))

    try:
        script = ScriptDirectory.from_config(alembic_cfg)
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()
        head_rev = script.get_current_head()
    except Exception as e:
        logger.error(
            "Error consultando estado de Alembic: %s. "
            "Omitiendo auto-migración.", e,
        )
        return

    if current_rev == head_rev:
        logger.debug("Base de datos al día, sin migraciones pendientes.")
        return

    logger.info(
        "Migraciones pendientes detectadas: %s → %s. Aplicando automáticamente...",
        current_rev or "(ninguna)", head_rev,
    )

    # ── FASE 2.5 — Fix 2.5: Backup pre-migración OBLIGATORIO ──
    # Sin backup, no migramos. Si algo sale mal después no podríamos
    # ofrecer recovery al usuario y la ferretería podría perder datos.
    try:
        from app.services.backup_service import create_backup
        backup_path = create_backup(tag="pre_migration")
        logger.info("Backup pre-migración creado: %s", backup_path)
    except Exception as be:
        logger.error("No se pudo crear backup pre-migración: %s", be, exc_info=True)
        raise MigrationFailedError(
            "Migración cancelada: no se pudo crear el backup de seguridad. "
            "La base de datos NO fue modificada. "
            "Verifique espacio en disco y permisos de escritura en data/backups/.",
            backup_path=None,
            details=[f"Error de backup: {be}"],
        )

    # ── Aplicar migraciones ──
    try:
        command.upgrade(alembic_cfg, "head")
        logger.info("Migraciones aplicadas (upgrade head OK).")
    except Exception as e:
        logger.error("Error aplicando migraciones: %s", e, exc_info=True)
        raise MigrationFailedError(
            "La migración falló y la base de datos puede estar en estado inconsistente.",
            backup_path=backup_path,
            details=[f"Error de Alembic: {e}"],
        )

    # ── FASE 2.5 — Fix 2.5: Verificación post-migración ──
    # Es posible que `command.upgrade` reporte éxito pero la BD quede
    # parcialmente migrada (ej. dialect cliente con autocommit no soportado
    # para DDL, error de constraint, etc.). Validamos explícitamente.
    ok, issues = _verify_schema_consistency(expected_head=head_rev)
    if not ok:
        logger.error("Verificación post-migración falló:\n  - %s", "\n  - ".join(issues))
        raise MigrationFailedError(
            "La migración completó pero la base de datos quedó en estado inconsistente. "
            "Tablas esperadas faltan o la versión de Alembic no coincide.",
            backup_path=backup_path,
            details=issues,
        )

    logger.info("Verificación post-migración OK. Schema en estado esperado.")


def _stamp_alembic_head():
    """
    DEPRECATED — FASE 2.6 — Fix 2.6.

    Esta función ya no se usa en el flujo principal. Se mantenía solo para
    el caso "first run con create_all" que ahora se reemplazó por
    `_initialize_via_alembic()` (que aplica las migraciones reales en orden
    y deja `alembic_version` correctamente seteada por la cadena).

    Se conserva el código por si algún script externo / tarea de mantenimiento
    necesita marcar manualmente la BD como up-to-date sin correr migraciones
    (ej. después de un restore desde un dump que no incluyó `alembic_version`).
    No es invocada automáticamente en ningún flujo del launcher.
    """
    try:
        from alembic.config import Config
        from alembic import command

        ini_path, _script_loc = _alembic_paths()
        if ini_path is None:
            return

        alembic_cfg = Config(str(ini_path))
        alembic_cfg.set_main_option("script_location", str(_script_loc))
        command.stamp(alembic_cfg, "head")
        logger.info("Alembic marcado en HEAD (uso manual).")
    except Exception as e:
        logger.warning(f"No se pudo marcar alembic HEAD: {e}")


# ═══════════════════════════════════════════════════════════════
# FASE 1 — Fix 1.4: Detección de conflicto de puerto
# FASE 4 — Fix 4.4: Fallback dinámico de puerto (8001, 8002, ...)
# ═══════════════════════════════════════════════════════════════

def _is_port_in_use(host: str, port: int) -> bool:
    """Verifica si un puerto TCP está en uso."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _is_our_backend(url: str) -> bool:
    """
    Verifica si el servicio en el puerto es una instancia de Violette POS.
    Revisa el endpoint /health y busca el nombre de la app en la respuesta.
    """
    import requests
    try:
        r = requests.get(f"{url}/health", timeout=3)
        if r.status_code == 200:
            data = r.json()
            app_name = data.get("app", "")
            if "Violette" in app_name or "violette" in app_name.lower():
                return True
    except Exception:
        pass
    return False


def _classify_port(host: str, port: int) -> str:
    """
    Clasifica el estado de un puerto candidato.

    Returns:
        "available" — puerto libre, se puede iniciar uvicorn ahí.
        "ours"      — ya hay una instancia de Violette POS escuchando ahí.
        "conflict"  — el puerto está ocupado por otro programa.
    """
    if not _is_port_in_use(host, port):
        return "available"
    if _is_our_backend(f"http://{host}:{port}"):
        return "ours"
    return "conflict"


def _resolve_port_range() -> tuple[int, int]:
    """
    Resuelve el rango de puertos a probar.

    Permite override vía variables de entorno:
        VIOLETTE_PORT_RANGE_START (default 8000)
        VIOLETTE_PORT_RANGE_END   (default 8009, inclusivo)

    Valores no numéricos o fuera de rango (1024..65535) caen al default
    sin abortar el arranque.
    """
    def _read_int(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None or raw == "":
            return default
        try:
            v = int(raw)
        except ValueError:
            logger.warning(
                "%s='%s' no es un entero válido. Usando default %d.",
                name, raw, default,
            )
            return default
        if v < 1024 or v > 65535:
            logger.warning(
                "%s=%d fuera del rango válido (1024..65535). Usando default %d.",
                name, v, default,
            )
            return default
        return v

    start = _read_int("VIOLETTE_PORT_RANGE_START", DEFAULT_PORT_RANGE_START)
    end = _read_int("VIOLETTE_PORT_RANGE_END", DEFAULT_PORT_RANGE_END)
    if end < start:
        logger.warning(
            "VIOLETTE_PORT_RANGE_END (%d) < START (%d). Igualando END=START.",
            end, start,
        )
        end = start
    return start, end


def _select_backend_port() -> tuple[int, str, list[int]]:
    """
    FASE 4.4 — Selecciona un puerto del rango configurado.

    Itera del START al END inclusive. Para cada puerto:
      - Si está LIBRE  → se elige y se retorna ("available").
      - Si tiene una instancia de Violette POS corriendo → se reutiliza
        ("ours") y se retorna sin iniciar otro uvicorn.
      - Si está ocupado por OTRO programa → se anota y se prueba el siguiente.

    Returns:
        (port, status, conflicts) donde:
          port       — el puerto efectivamente seleccionado.
          status     — "available" (hay que iniciar uvicorn) o
                       "ours" (reutilizar la instancia ya viva).
          conflicts  — puertos ocupados por procesos ajenos durante la
                       búsqueda (para diagnóstico en logs).

    Raises:
        RuntimeError si TODOS los puertos del rango están ocupados por
        programas ajenos a Violette POS. El mensaje incluye instrucciones
        para que el usuario elija un rango distinto.
    """
    start, end = _resolve_port_range()
    conflicts: list[int] = []

    for port in range(start, end + 1):
        status = _classify_port(BACKEND_HOST, port)

        if status == "available":
            if port == start and not conflicts:
                # Caso normal: el primer puerto del rango está libre.
                logger.debug("Puerto %d libre.", port)
            else:
                logger.info(
                    "Puerto(s) %s ocupado(s) por otro(s) programa(s). "
                    "Usando %d en su lugar.",
                    conflicts, port,
                )
            return port, "available", conflicts

        if status == "ours":
            if conflicts:
                logger.info(
                    "Detectada instancia existente de Violette POS en puerto %d. "
                    "Reutilizando. (Puertos %s ocupados por otros programas.)",
                    port, conflicts,
                )
            else:
                logger.info(
                    "Detectada instancia existente de Violette POS en puerto %d. "
                    "Reutilizando.", port,
                )
            return port, "ours", conflicts

        # status == "conflict" → siguiente puerto
        conflicts.append(port)
        logger.info(
            "Puerto %d ocupado por otro programa. Probando siguiente...", port,
        )

    # Agotamos el rango sin encontrar puerto utilizable
    raise RuntimeError(
        f"No se pudo encontrar un puerto libre en el rango "
        f"{start}-{end} para el servidor interno.\n\n"
        f"Todos los puertos están ocupados por otros programas: {conflicts}\n\n"
        "Violette POS necesita uno de estos puertos para funcionar.\n"
        "Opciones:\n"
        "  - Cierre los programas que están usando estos puertos e intente "
        "de nuevo.\n"
        "  - Reinicie la computadora.\n"
        "  - Configure un rango distinto antes de abrir Violette POS:\n"
        "        set VIOLETTE_PORT_RANGE_START=9000\n"
        "        set VIOLETTE_PORT_RANGE_END=9009"
    )


def _start_backend():
    """
    Inicia el servidor FastAPI/uvicorn en un hilo daemon.

    FASE 4.4 — Fix 4.4: Si el puerto preferido (8000) está ocupado por un
    programa ajeno, prueba 8001, 8002, ... hasta el final del rango.
    Una vez elegido el puerto, lo publica en `os.environ["API_BASE_URL"]`
    para que la UI (`ui.api.BASE_URL`) se conecte al puerto correcto.
    """
    import uvicorn

    global BACKEND_PORT, BACKEND_URL

    # ── FASE 4.4 — Seleccionar puerto del rango configurado ──
    port, status, _conflicts = _select_backend_port()

    # Actualizar globals y env var ANTES de cualquier import de `ui.api`
    # (ui.api lee API_BASE_URL en import-time). El primer import de ui.api
    # ocurre dentro de _start_ui() — bastante después de este punto — por
    # lo que setearla aquí garantiza coherencia entre backend y UI.
    BACKEND_PORT = port
    BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
    os.environ["API_BASE_URL"] = BACKEND_URL

    if status == "ours":
        # Ya hay una instancia corriendo — no iniciar otra.
        logger.info("Backend ya está corriendo en %s. Conectando...", BACKEND_URL)
        return None

    # status == "available" → iniciar uvicorn en el puerto elegido
    logger.info("Iniciando backend en %s ...", BACKEND_URL)

    config = uvicorn.Config(
        "app.main:app",
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Esperar a que el backend esté listo
    import requests
    for i in range(30):
        try:
            r = requests.get(f"{BACKEND_URL}/health", timeout=2)
            if r.status_code == 200:
                logger.info("Backend listo.")
                return thread
        except Exception:
            pass
        time.sleep(0.5)

    # ── FASE 1 — Fix 1.4: Error claro si el backend no inicia ──
    error_msg = (
        "El servidor interno no pudo iniciarse después de 15 segundos.\n\n"
        "Esto puede ocurrir si:\n"
        "- La base de datos está corrupta\n"
        "- Falta un archivo de configuración\n"
        "- Hay un error en la aplicación\n\n"
        "Revise el archivo logs/errors.log para más detalles."
    )
    logger.error(error_msg)
    raise RuntimeError(error_msg)


def _start_ui():
    """Inicia la interfaz gráfica PySide6."""
    from PySide6.QtWidgets import QApplication
    from ui.session_manager import session

    # ── FASE 1 — Fix 1.1: Configurar thread pool para HTTP async ──
    from ui.utils.http_worker import configure_thread_pool
    configure_thread_pool()

    # ── FASE 3.3 — Fix: reutilizar el QApplication existente ──
    # El wizard de primer arranque (_bootstrap_db_engine_if_needed) ya crea
    # un QApplication para poder mostrarse. Qt solo admite UNA instancia de
    # QApplication por proceso, así que crear otra aquí lanzaba:
    #   "Please destroy the QApplication singleton before creating a new
    #    QApplication instance"
    # y abortaba el arranque justo después de completar el wizard. Reutilizamos
    # la instancia si ya existe (mismo patrón que el resto del launcher).
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Violette POS")
    app.setOrganizationName("Violette")

    # ── FIX CRÍTICO: instalar manejadores globales de excepciones ──
    # Sin esto, cualquier excepción no manejada dentro de un slot de Qt
    # (clicked.connect, on_success del HttpWorker, timers, etc.) cierra
    # la app silenciosamente en PySide6 6.6+. Debe llamarse después de
    # crear QApplication.
    from ui.utils.exception_hooks import install_global_exception_hooks
    install_global_exception_hooks()

    # ── FASE 1 — Fix 1.5: Solo buscar el archivo QSS correcto ──
    # Eliminada la referencia a "styles (1).qss" que era un artefacto
    # de desarrollo (archivo duplicado por Windows).
    qss_path = "ui/assets/styles.qss"
    if os.path.exists(qss_path):
        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
        except Exception as e:
            logger.warning(f"No se pudo cargar estilos: {e}")

    if session.is_logged_in():
        from ui.main_ui import MainWindow
        window = MainWindow(session.username)
        window.showMaximized()
    else:
        from ui.login_view import LoginWindow
        window = LoginWindow()
        window.show()

    return app.exec()


# ═══════════════════════════════════════════════════════════════
# FASE 2.5 — Fix 2.5: Handler del diálogo de recovery
# ═══════════════════════════════════════════════════════════════

def _handle_migration_failure(error: MigrationFailedError) -> bool:
    """
    Muestra un diálogo modal al usuario cuando la auto-migración falla y
    le ofrece restaurar desde el backup pre-migración.

    Returns:
        True  → el usuario eligió restaurar Y el restore fue exitoso.
                Se debe cerrar la app para que el siguiente arranque tome
                el estado restaurado.
        False → el usuario eligió no restaurar, o el restore falló.
    """
    from PySide6.QtWidgets import QApplication, QMessageBox

    if QApplication.instance() is None:
        QApplication(sys.argv)

    details_text = "\n  • ".join(error.details) if error.details else "(sin detalles)"

    main_msg = (
        f"{error}\n\n"
        f"Detalle:\n  • {details_text}\n\n"
        "Para evitar daños, Violette POS no continuará con la base de datos "
        "en este estado."
    )

    box = QMessageBox()
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle("Error de actualización — Violette POS")
    box.setText("La actualización de la base de datos falló.")
    box.setInformativeText(main_msg)

    if error.backup_path:
        # Tenemos backup → ofrecer restaurar
        btn_restore = box.addButton("Restaurar backup automáticamente", QMessageBox.AcceptRole)
        btn_close = box.addButton("Cerrar (restaurar manualmente)", QMessageBox.RejectRole)
        box.setDefaultButton(btn_restore)
        box.setDetailedText(
            f"Backup pre-migración disponible en:\n{error.backup_path}\n\n"
            "Si elige 'Restaurar backup', la BD volverá al estado previo a la "
            "actualización. Después puede contactar soporte.\n\n"
            "Si elige 'Cerrar', deberá restaurar manualmente el backup antes "
            "de volver a abrir Violette POS."
        )
        box.exec()

        if box.clickedButton() is btn_restore:
            return _attempt_restore(error.backup_path)
        return False
    else:
        # Sin backup (caso: backup falló antes de migrar). La BD NO fue tocada.
        box.addButton("Cerrar", QMessageBox.RejectRole)
        box.setDetailedText(
            "Como el backup no se pudo crear, la migración se canceló a "
            "tiempo y la base de datos NO fue modificada. Verifique espacio "
            "en disco y permisos de escritura en data/backups/, luego vuelva "
            "a iniciar Violette POS."
        )
        box.exec()
        return False


def _attempt_restore(backup_path: str) -> bool:
    """
    Intenta restaurar el backup pre-migración. Si tiene éxito, retorna True.
    Si falla, muestra un nuevo diálogo informando al usuario que debe
    restaurar manualmente.
    """
    from PySide6.QtWidgets import QMessageBox

    try:
        from app.services.backup_service import restore_backup
        # restore_backup espera filename relativo a BACKUP_DIR o ruta absoluta.
        # `backup_path` viene como ruta absoluta de create_backup() → OK.
        logger.info("Restaurando backup pre-migración: %s", backup_path)
        restore_backup(backup_path)
        logger.info("Restore completado. La app se cerrará para reiniciar.")

        QMessageBox.information(
            None,
            "Restauración completada",
            "La base de datos se restauró al estado previo a la actualización.\n\n"
            "Violette POS se cerrará. Vuelva a abrirlo para usarlo normalmente.",
        )
        return True

    except Exception as e:
        logger.error("Error restaurando backup: %s", e, exc_info=True)
        QMessageBox.critical(
            None,
            "Error restaurando backup",
            f"No se pudo restaurar el backup automáticamente:\n\n{e}\n\n"
            f"Restaure manualmente el archivo:\n{backup_path}\n\n"
            "Contacte soporte si necesita ayuda.",
        )
        return False


def main():
    """Flujo principal: setup → backend → UI."""
    # ── Wizard de selección de BD (solo en primer arranque) ──
    # DEBE ejecutarse antes de cualquier `from app.core...` porque ese
    # import dispara `_ensure_secret_key()` (que crea .env por defecto)
    # y `_auto_detect_engine()` (que fija DB_ENGINE=sqlite si no está
    # definido). Ver docstring de _bootstrap_db_engine_if_needed.
    _bootstrap_db_engine_if_needed()

    # Ahora que app está en el path, usar el logger estructurado
    from app.core.logger import logger as app_logger
    app_logger.info("=" * 50)
    app_logger.info("Violette POS iniciando...")
    app_logger.info("=" * 50)

    try:
        # ── FASE 2.5 — Fix 2.5: capturar fallos de migración por separado ──
        # MigrationFailedError tiene contexto suficiente para ofrecer recovery.
        # Las demás excepciones siguen el flujo de "error fatal genérico".
        try:
            _first_run_check()
        except MigrationFailedError as me:
            app_logger.error("Migración fallida: %s", me)
            _handle_migration_failure(me)
            # En cualquier caso (restore OK o usuario rechazó), terminamos.
            # Si el restore fue OK, el siguiente arranque toma el estado limpio.
            sys.exit(2)

        _start_backend()
        exit_code = _start_ui()

        app_logger.info("Violette POS cerrado.")
        sys.exit(exit_code)

    except Exception as e:
        app_logger.error(f"Error fatal: {e}", exc_info=True)

        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if not QApplication.instance():
                QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "Error Fatal — Violette POS",
                f"No se pudo iniciar la aplicación:\n\n{e}\n\n"
                "Revise el archivo logs/errors.log para más detalles."
            )
        except Exception:
            pass

        sys.exit(1)


if __name__ == "__main__":
    main()