"""
app/db/database.py — Conexión a base de datos

FASE 4: Soporte dual SQLite/MySQL
  - SQLite: ideal para .exe standalone, WAL mode para mejor concurrencia
  - MySQL: para instalaciones multi-usuario con servidor externo
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
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