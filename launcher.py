"""
launcher.py — Punto de entrada principal de Violette POS

Levanta el backend FastAPI en un hilo separado y luego abre la UI PySide6.
Este es el archivo que PyInstaller empaqueta como .exe.

FASE 1 — Fixes aplicados:
  - Fix 1.4: Detección de conflicto de puerto antes de iniciar uvicorn.
             Si el puerto 8000 ya está en uso por otra instancia de Violette,
             se reutiliza. Si es un proceso ajeno, se muestra error claro.
  - Fix 1.5: Eliminada referencia a "styles (1).qss" (artefacto de desarrollo).

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
import logging
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

logging.basicConfig(
    level=logging.INFO,
    handlers=[_file_handler, _console_handler],
)
logger = logging.getLogger("launcher")

# ── Puerto y host del backend ──
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"


def _first_run_check():
    """Verifica si es la primera ejecución y ejecuta setup inicial."""
    from app.core.config import settings, is_sqlite, APP_DIR

    if is_sqlite():
        db_path = APP_DIR / settings.db_sqlite_path
        if not db_path.exists():
            logger.info("Primera ejecución detectada. Creando base de datos...")
            _initialize_database()
            return True

    # ── FASE 4 — Fix 4.4: Auto-migración en cada arranque ──
    # Si la BD ya existe, aplicar migraciones pendientes automáticamente.
    # Esto cubre el caso donde el dueño de la ferretería actualiza la app
    # (nuevo .exe) pero la BD tiene esquema viejo. Sin esto, tendría que
    # correr 'alembic upgrade head' manualmente.
    _auto_migrate()
    return False


def _initialize_database():
    """Crea tablas y datos iniciales."""
    try:
        from app.db.database import Base, engine
        import app.db.models  # noqa: F401

        logger.info("Creando tablas...")
        Base.metadata.create_all(bind=engine)

        logger.info("Insertando datos iniciales...")
        from app.scripts.seed_db import run as run_seed
        run_seed(force=False)

        logger.info("Base de datos inicializada correctamente.")

        # Marcar alembic como up-to-date para que no intente re-migrar
        _stamp_alembic_head()

    except Exception as e:
        logger.error(f"Error inicializando BD: {e}")
        raise


def _auto_migrate():
    """
    FASE 4 — Fix 4.4: Aplica migraciones Alembic pendientes automáticamente.

    Seguridades:
      - Si alembic no está configurado, no hace nada (log warning).
      - Si no hay migraciones pendientes, termina en <50ms.
      - Crea backup antes de migrar (por si algo sale mal).
      - Si la migración falla, el error se loguea pero la app intenta iniciar
        de todas formas (la BD vieja probablemente funcione con el código nuevo).
    """
    try:
        from alembic.config import Config
        from alembic import command
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        from app.db.database import engine

        # Buscar alembic.ini
        if getattr(sys, 'frozen', False):
            base = Path(sys.executable).parent
        else:
            base = Path(__file__).parent

        ini_path = base / "alembic.ini"
        if not ini_path.exists():
            logger.debug("alembic.ini no encontrado, omitiendo auto-migración.")
            return

        alembic_cfg = Config(str(ini_path))
        # Asegurar que script_location apunte al directorio correcto
        alembic_cfg.set_main_option("script_location", str(base / "alembic"))

        script = ScriptDirectory.from_config(alembic_cfg)

        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()

        head_rev = script.get_current_head()

        if current_rev == head_rev:
            logger.debug("Base de datos al día, sin migraciones pendientes.")
            return

        logger.info(
            f"Migraciones pendientes detectadas: {current_rev or '(ninguna)'} → {head_rev}. "
            f"Aplicando automáticamente..."
        )

        # Backup de seguridad antes de migrar
        try:
            from app.services.backup_service import create_backup
            backup_path = create_backup(tag="pre_migration")
            logger.info(f"Backup pre-migración creado: {backup_path}")
        except Exception as be:
            logger.warning(f"No se pudo crear backup pre-migración: {be}")

        # Aplicar migraciones
        command.upgrade(alembic_cfg, "head")
        logger.info("Migraciones aplicadas correctamente.")

    except ImportError:
        logger.debug("Alembic no disponible, omitiendo auto-migración.")
    except Exception as e:
        logger.error(
            f"Error en auto-migración: {e}. "
            f"La app intentará iniciar de todas formas. "
            f"Si hay problemas, ejecute 'alembic upgrade head' manualmente.",
            exc_info=True,
        )


def _stamp_alembic_head():
    """
    Marca la BD como up-to-date en alembic sin ejecutar migraciones.
    Se usa después de create_all() en first run.
    """
    try:
        from alembic.config import Config
        from alembic import command

        if getattr(sys, 'frozen', False):
            base = Path(sys.executable).parent
        else:
            base = Path(__file__).parent

        ini_path = base / "alembic.ini"
        if not ini_path.exists():
            return

        alembic_cfg = Config(str(ini_path))
        alembic_cfg.set_main_option("script_location", str(base / "alembic"))
        command.stamp(alembic_cfg, "head")
        logger.info("Alembic marcado en HEAD (primera ejecución).")
    except Exception as e:
        logger.warning(f"No se pudo marcar alembic HEAD: {e}")


# ═══════════════════════════════════════════════════════════════
# FASE 1 — Fix 1.4: Detección de conflicto de puerto
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


def _check_port_availability() -> str:
    """
    Verifica si el puerto del backend está disponible.

    Returns:
        "available"   — puerto libre, se puede iniciar el backend
        "ours"        — ya hay una instancia de Violette corriendo, reutilizar
        "conflict"    — el puerto está ocupado por otro programa
    """
    if not _is_port_in_use(BACKEND_HOST, BACKEND_PORT):
        return "available"

    logger.info(f"Puerto {BACKEND_PORT} en uso. Verificando si es Violette POS...")

    if _is_our_backend(BACKEND_URL):
        logger.info("Detectada instancia existente de Violette POS. Reutilizando.")
        return "ours"

    return "conflict"


def _start_backend():
    """Inicia el servidor FastAPI/uvicorn en un hilo daemon."""
    import uvicorn

    # ── FASE 1 — Fix 1.4: Verificar puerto antes de iniciar ──
    port_status = _check_port_availability()

    if port_status == "ours":
        # Ya hay una instancia corriendo — no iniciar otra
        logger.info("Backend ya está corriendo. Conectando...")
        return None

    if port_status == "conflict":
        # Otro programa usa el puerto — error fatal
        error_msg = (
            f"El puerto {BACKEND_PORT} está ocupado por otro programa.\n\n"
            f"Violette POS necesita el puerto {BACKEND_PORT} para funcionar.\n"
            "Cierre el programa que está usando este puerto e intente de nuevo.\n\n"
            "Si el problema persiste, reinicie la computadora."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Puerto disponible — iniciar normalmente
    logger.info(f"Iniciando backend en {BACKEND_URL} ...")

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

    app = QApplication(sys.argv)
    app.setApplicationName("Violette POS")
    app.setOrganizationName("Violette")

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
        window = MainWindow()
        window.showMaximized()
    else:
        from ui.login_view import LoginWindow
        window = LoginWindow()
        window.show()

    return app.exec()


def main():
    """Flujo principal: setup → backend → UI."""
    # Ahora que app está en el path, usar el logger estructurado
    from app.core.logger import logger as app_logger
    app_logger.info("=" * 50)
    app_logger.info("Violette POS iniciando...")
    app_logger.info("=" * 50)

    try:
        _first_run_check()
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