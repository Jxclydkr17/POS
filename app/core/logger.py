"""
app/core/logger.py — Logging estructurado para Violette POS

FASE 5:
  - Rotación automática (5 archivos x 5MB)
  - Formato estructurado con contexto
  - En producción: solo archivo (no stdout)
  - En desarrollo: archivo + consola
  - Log separado para errores críticos
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Directorio de logs ──
# ── FASE 6 — Fix 6.3: Consolidar bajo DATA_DIR/logs/ ──
from app.core.config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "app.log"
ERROR_LOG_FILE = LOG_DIR / "errors.log"

# ── Determinar modo ──
_ENV = os.environ.get("APP_ENV", "development").lower()
_IS_PRODUCTION = _ENV in ("production", "prod")
_LOG_LEVEL = logging.WARNING if _IS_PRODUCTION else logging.INFO

# ── Formato ──
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _setup_logger() -> logging.Logger:
    """Configura y retorna el logger principal de la aplicación."""
    root_logger = logging.getLogger("violette_pos")
    root_logger.setLevel(logging.DEBUG)

    # Evitar duplicar handlers en hot-reload
    if root_logger.handlers:
        return root_logger

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    # ── Handler 1: Archivo principal (rotativo) ──
    file_handler = RotatingFileHandler(
        str(LOG_FILE),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # ── Handler 2: Archivo de errores (rotativo, solo ERROR+) ──
    error_handler = RotatingFileHandler(
        str(ERROR_LOG_FILE),
        maxBytes=2 * 1024 * 1024,  # 2 MB
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    # ── Handler 3: Consola (solo en desarrollo) ──
    if not _IS_PRODUCTION:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(_LOG_LEVEL)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # ── Silenciar loggers ruidosos ──
    for noisy in ("uvicorn.access", "uvicorn.error", "sqlalchemy.engine",
                   "httpcore", "httpx", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root_logger.info(
        f"Logger iniciado | env={_ENV} | level={logging.getLevelName(_LOG_LEVEL)} "
        f"| log_dir={LOG_DIR}"
    )

    return root_logger


# ── Instancia global ──
logger = _setup_logger()