"""add_pdf_generated_to_sales

Revision ID: c2d3e4f5a6b7
Revises: b1f2a3c4d5e6
Create Date: 2026-04-18 14:00:00.000000

FASE C — Fix C.3: Columna pdf_generated en tabla sales.
Permite al frontend saber si el PDF de la venta se generó correctamente.
NULL = no intentado, True = generado OK, False = falló.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1f2a3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('sales', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('pdf_generated', sa.Boolean(), nullable=True, default=None)
        )


def downgrade() -> None:
    with op.batch_alter_table('sales', schema=None) as batch_op:
        batch_op.drop_column('pdf_generated')