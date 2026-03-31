"""add credit_limit to customers (DUPLICADO de 2c50ebc6bf0b)

⚠️  Esta migración es duplicada — fue generada por accidente.
Se mantiene en la cadena por compatibilidad con BDs existentes,
pero verifica si la columna ya existe antes de actuar.

Revision ID: 04caac52643e
Revises: 2c50ebc6bf0b
Create Date: 2026-01-12 16:55:16.697596

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '04caac52643e'
down_revision: Union[str, Sequence[str], None] = '2c50ebc6bf0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Solo agregar si no existe (la migración anterior ya la creó)
    bind = op.get_bind()
    columns = [c["name"] for c in inspect(bind).get_columns("customers")]
    if "credit_limit" not in columns:
        op.add_column(
            "customers",
            sa.Column("credit_limit", sa.Float(), nullable=False, server_default="0")
        )

def downgrade():
    op.drop_column("customers", "credit_limit")