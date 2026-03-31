"""
launcher.py — Punto de entrada principal de Violette POS

Levanta el backend FastAPI en un hilo separado y luego abre la UI PySide6.
Este es el archivo que PyInstaller empaqueta como .exe.

FASE 5: Usa logging estructurado con rotación.
"""

import sys
import os
import time
import threading
import logging

# ── Configurar directorio de trabajo ──
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Configurar logging mínimo antes de importar app
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("launcher")


def _first_run_check():
    """Verifica si es la primera ejecución y ejecuta setup inicial."""
    from app.core.config import settings, is_sqlite, APP_DIR

    if is_sqlite():
        db_path = APP_DIR / settings.db_sqlite_path
        if not db_path.exists():
            logger.info("Primera ejecución detectada. Creando base de datos...")
            _initialize_database()
            return True
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
    except Exception as e:
        logger.error(f"Error inicializando BD: {e}")
        raise


def _start_backend():
    """Inicia el servidor FastAPI/uvicorn en un hilo daemon."""
    import uvicorn

    logger.info("Iniciando backend en http://127.0.0.1:8000 ...")

    config = uvicorn.Config(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    import requests
    for i in range(30):
        try:
            r = requests.get("http://127.0.0.1:8000/health", timeout=1)
            if r.status_code == 200:
                logger.info("Backend listo.")
                return thread
        except Exception:
            pass
        time.sleep(0.5)

    logger.warning("Backend tardó en responder, iniciando UI de todas formas.")
    return thread


def _start_ui():
    """Inicia la interfaz gráfica PySide6."""
    from PySide6.QtWidgets import QApplication
    from ui.session_manager import session

    app = QApplication(sys.argv)
    app.setApplicationName("Violette POS")
    app.setOrganizationName("Violette")

    qss_paths = [
        "ui/assets/styles (1).qss",
        "ui/assets/styles.qss",
    ]
    for qss_path in qss_paths:
        if os.path.exists(qss_path):
            try:
                with open(qss_path, "r", encoding="utf-8") as f:
                    app.setStyleSheet(f.read())
                break
            except Exception:
                pass

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