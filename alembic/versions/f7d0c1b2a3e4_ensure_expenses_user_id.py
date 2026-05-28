"""ensure_expenses_user_id

Revision ID: f7d0c1b2a3e4
Revises: fb340249e5fa
Create Date: 2026-05-27 18:00:00.000000

"""
# ----------------------------------------------------------------------
# Auditoria de Gastos -- Asegurar que expenses.user_id existe.
#
# Contexto:
#   El modelo Expense declara user_id (FK a users.id) y la migracion
#   inicial efd19c998f1c ya lo incluye en el CREATE TABLE. Sin embargo,
#   instalaciones MySQL provisionadas antes de que user_id se consolidara
#   en el initial schema pueden quedarse sin esa columna.
#
#   Sintoma: el Registro de Gastos Operativos muestra la columna "Usuario"
#   vacia para todos los gastos.
#
#   Esta migracion es la red de seguridad: si la columna ya existe (caso
#   feliz, instalacion nueva) no hace nada. Si falta, la agrega junto con
#   el indice ix_expenses_user_id y la FK a users.id.
#
# Diseno idempotente:
#   - Chequea la columna antes de agregarla (no falla con Duplicate column).
#   - Chequea el indice antes de crearlo (no falla con Duplicate key name).
#   - Chequea la FK por columna referenciada, no por nombre (los nombres
#     autogenerados varian: expenses_ibfk_1, fk_expenses_users, etc).
#
# SQLite: ADD COLUMN soportado; ADD FOREIGN KEY no es nativo sin recreate,
# asi que en SQLite agregamos solo columna + indice. La integridad la da
# el modelo SQLAlchemy + PRAGMA foreign_keys=ON.
#
# Downgrade: NO-OP intencional. Quitar la columna borraria auditoria real.
# ----------------------------------------------------------------------
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'f7d0c1b2a3e4'
down_revision: Union[str, Sequence[str], None] = 'fb340249e5fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = 'expenses'
_COLUMN = 'user_id'
_INDEX = 'ix_expenses_user_id'
_FK_NAME = 'fk_expenses_user_id_users'


def _is_sqlite(bind) -> bool:
    return bind.dialect.name == 'sqlite'


def _column_exists(inspector, table: str, column: str) -> bool:
    try:
        return column in {c['name'] for c in inspector.get_columns(table)}
    except Exception:
        return False


def _index_exists(inspector, table: str, index_name: str) -> bool:
    try:
        return index_name in {i['name'] for i in inspector.get_indexes(table)}
    except Exception:
        return False


def _fk_to_users_id_exists(inspector, table: str, column: str) -> bool:
    # Detecta si ya hay una FK desde table.column hacia users.id,
    # sin importar el nombre que le haya puesto el motor.
    try:
        for fk in inspector.get_foreign_keys(table):
            if (
                fk.get('referred_table') == 'users'
                and column in (fk.get('constrained_columns') or [])
                and 'id' in (fk.get('referred_columns') or [])
            ):
                return True
    except Exception:
        pass
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 1) Columna user_id
    if not _column_exists(inspector, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.Integer(), nullable=True),
        )
        inspector = inspect(bind)

    # 2) Indice (acelera filtros por usuario)
    if not _index_exists(inspector, _TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, [_COLUMN], unique=False)
        inspector = inspect(bind)

    # 3) Foreign key hacia users.id (se omite en SQLite)
    if _is_sqlite(bind):
        return

    if not _fk_to_users_id_exists(inspector, _TABLE, _COLUMN):
        op.create_foreign_key(
            _FK_NAME,
            source_table=_TABLE,
            referent_table='users',
            local_cols=[_COLUMN],
            remote_cols=['id'],
        )


def downgrade() -> None:
    # NO-OP intencional. Ver comentario de cabecera.
    pass