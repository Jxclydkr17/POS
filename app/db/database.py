"""
app/db/database.py — Conexión a base de datos

FASE 4: Soporte dual SQLite/MySQL
  - SQLite: ideal para .exe standalone, WAL mode para mejor concurrencia
  - MySQL: para instalaciones multi-usuario con servidor externo
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import contextmanager
import logging

from app.core.config import get_database_url, is_sqlite, settings

DATABASE_URL = get_database_url()

# ── Configurar engine según el motor ──
if is_sqlite():
    # SQLite: check_same_thread=False necesario para FastAPI (multi-thread)
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # Activar WAL mode y foreign keys en cada conexión SQLite
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
else:
    # MySQL — pool configurado para multi-terminal + background tasks
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_timeout=settings.db_pool_timeout,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_bg_logger = logging.getLogger("app.db.background")

# ── FASE 3 — Fix 3.3: ventana de espera para background tasks ──
# Cuando un restore SQLite está en curso, safe_session() bloquea hasta
# que el _maintenance_event se libere o se agote este timeout. 60s es
# generoso para restores grandes (>500MB) y a la vez evita colgar
# tasks indefinidamente. El intervalo de polling es 0.25s.
_MAINTENANCE_WAIT_SECONDS = 60.0
_MAINTENANCE_POLL_INTERVAL = 0.25


@contextmanager
def safe_session():
    """Context manager for background tasks that need their own DB session.

    Guarantees:
      - Session is always closed (even on unhandled exceptions).
      - Rollback on exception so the connection returns clean to the pool.
      - pool_pre_ping (MySQL) tests the connection at checkout, so stale
        connections after pool_recycle are replaced transparently.

    FASE 3 — Fix 3.3: respeta el modo mantenimiento del backup_service.
    Si un restore SQLite está en curso (_maintenance_event activo), esta
    función espera hasta `_MAINTENANCE_WAIT_SECONDS` a que termine. Si
    el restore tarda más, lanza RuntimeError para que el background task
    aborte ese ciclo y lo reintente naturalmente en la siguiente vuelta.
    Esto evita que un task abra una conexión a la BD a medio copiar.

    Usage:
        from app.db.database import safe_session

        with safe_session() as db:
            rows = db.query(Model).all()
            db.commit()   # caller manages commit/rollback as needed
    """
    # ── FASE 3 — Fix 3.3: respetar modo mantenimiento ──
    # Lazy import para evitar ciclo con backup_service (que importa
    # `engine` desde este módulo dentro de _restore_sqlite_backup).
    _maintenance_event = None
    try:
        from app.services.backup_service import _maintenance_event as _ev
        _maintenance_event = _ev
    except Exception:
        # Si backup_service aún no se cargó (early startup) o falla
        # el import, continuamos sin bloqueo — modo defensivo.
        pass

    if _maintenance_event is not None and _maintenance_event.is_set():
        import time
        deadline = time.monotonic() + _MAINTENANCE_WAIT_SECONDS
        while _maintenance_event.is_set() and time.monotonic() < deadline:
            time.sleep(_MAINTENANCE_POLL_INTERVAL)
        if _maintenance_event.is_set():
            # El restore sigue activo tras el timeout — abortar este
            # ciclo del background task. La excepción es manejada por
            # el caller (cada loop hace `except Exception: logger.error`).
            raise RuntimeError(
                "BD en modo mantenimiento (restore en curso). "
                "Operación abortada para evitar corrupción; se reintentará."
            )

    db = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception as rollback_err:
            _bg_logger.debug(f"Rollback failed in safe_session: {rollback_err}")
        raise
    finally:
        db.close()