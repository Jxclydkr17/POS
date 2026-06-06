"""add_cedula_correo_to_users

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-06-06 17:00:00.000000

RECUPERACIÓN DE CONTRASEÑA (estilo Google) — datos de identidad del admin.

Contexto:
    El flujo de "¿Olvidó su contraseña?" (exclusivo del administrador)
    necesita verificar la identidad del admin con dos datos que solo él
    conoce —su cédula y su correo— antes de enviarle un código de 6
    dígitos. Esta migración agrega esas dos columnas a `users`.

Esta migración:
    Agrega `cedula` (String 50) y `correo` (String 255) a `users`, ambas
    NULLABLE. El administrador inicial los captura obligatoriamente en el
    formulario de primera ejecución (ver /users/setup); las instalaciones
    existentes quedan con NULL hasta que el admin los complete desde
    Configuración → Usuarios.

Compatibilidad de motores:
    - MySQL (5.7, 8.0, 8.4, MariaDB): ADD COLUMN nullable es operación
      "INSTANT"/"INPLACE" — sin reescritura ni bloqueo.
    - SQLite (dev local / standalone): ALTER TABLE ADD COLUMN funciona; las
      columnas nuevas son nullable por default.

Diseño idempotente (igual que g7b8c9d0e1f2 y k1l2m3n4o5p6):
    Se chequea con el inspector si la columna ya existe antes de agregarla,
    para tolerar la re-ejecución de `alembic upgrade head` sin el error
    "Duplicate column name".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'l2m3n4o5p6q7'
down_revision: Union[str, None] = 'k1l2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Columnas que agrega esta migración. (nombre, tipo SQLAlchemy)
_NEW_COLUMNS = [
    ('cedula', sa.String(length=50)),
    ('correo', sa.String(length=255)),
]


def _existing_columns(table_name: str) -> set:
    """Set de nombres de columnas existentes (cross-dialecto)."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return {col['name'] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _existing_columns('users')
    for col_name, col_type in _NEW_COLUMNS:
        if col_name in existing:
            # Idempotencia: no re-agregar si ya existe.
            continue
        op.add_column(
            'users',
            sa.Column(col_name, col_type, nullable=True),
        )


def downgrade() -> None:
    existing = _existing_columns('users')
    for col_name, _ in reversed(_NEW_COLUMNS):
        if col_name not in existing:
            continue
        op.drop_column('users', col_name)