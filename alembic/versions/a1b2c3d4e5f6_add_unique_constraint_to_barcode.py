"""add_unique_constraint_to_barcode

Revision ID: a1b2c3d4e5f6
Revises: efd19c998f1c
Create Date: 2026-04-17 10:00:00.000000

FASE 2 — Fix 2.3: El campo barcode tenía index=True pero no unique=True.
Esto permitía que dos productos compartieran el mismo código de barras,
causando que el escáner devolviera el producto incorrecto.

La migración convierte el índice existente en un índice único.
SQLite permite múltiples NULLs en columnas unique, así que productos
sin código de barras (barcode=NULL) no se ven afectados.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'efd19c998f1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # render_as_batch=True en env.py permite esto en SQLite
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_index('ix_products_barcode')
        batch_op.create_index(
            'ix_products_barcode',
            ['barcode'],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_index('ix_products_barcode')
        batch_op.create_index(
            'ix_products_barcode',
            ['barcode'],
            unique=False,
        )
