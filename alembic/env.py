"""
alembic/env.py — Configuración de entorno para migraciones Alembic

FASE 2 FIX:
- Importa TODOS los modelos via app.db.models (no una lista parcial)
- Lee la URL de la BD desde .env via app.core.config
- Soporta tanto migraciones online como offline
"""

import sys
from pathlib import Path
from os.path import abspath, dirname
from logging.config import fileConfig
from sqlalchemy import pool, engine_from_config, create_engine
from alembic import context

# --- 1. CONFIGURAR EL PATH PRIMERO QUE NADA ---
# Esto permite que Python encuentre la carpeta 'app'
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

# --- 2. AHORA SÍ, IMPORTAR LO DE TU APP ---
from app.db.database import Base
import app.db.models  # noqa: F401
from app.core.config import get_database_url

# ... el resto de tu código (config, target_metadata, funciones) se queda igual

# Agregar raíz del proyecto al path ANTES de importar app.*
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))


# Configuración de Alembic
config = context.config

# Logging desde alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic usa esto para detectar cambios en los modelos
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Ejecuta migraciones en modo 'offline' (genera SQL sin conectar)."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Ejecuta migraciones conectando a la BD."""
    connectable = create_engine(
        get_database_url(),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()