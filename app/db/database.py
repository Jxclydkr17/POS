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


@contextmanager
def safe_session():
    """Context manager for background tasks that need their own DB session.

    Guarantees:
      - Session is always closed (even on unhandled exceptions).
      - Rollback on exception so the connection returns clean to the pool.
      - pool_pre_ping (MySQL) tests the connection at checkout, so stale
        connections after pool_recycle are replaced transparently.

    Usage:
        from app.db.database import safe_session

        with safe_session() as db:
            rows = db.query(Model).all()
            db.commit()   # caller manages commit/rollback as needed
    """
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