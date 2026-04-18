"""add_index_sale_details_sale_id

Revision ID: b1f2a3c4d5e6
Revises: a1b2c3d4e5f6
Create Date: 2026-04-18 12:00:00.000000

FASE B — Fix B.4: Agregar índice en sale_details.sale_id.
Cada consulta de detalle de venta hace JOIN por sale_id. Sin índice,
SQLite recorre toda la tabla sale_details (full table scan).
Con 10,000+ ventas al año, esto se vuelve notablemente lento.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b1f2a3c4d5e6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('sale_details', schema=None) as batch_op:
        batch_op.create_index(
            'ix_sale_details_sale_id',
            ['sale_id'],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('sale_details', schema=None) as batch_op:
        batch_op.drop_index('ix_sale_details_sale_id')