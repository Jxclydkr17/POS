"""fase3_proforma_total_precision

FASE 3 — Fix 3.5: Estandariza Proforma.total de Numeric(12, 2) a Numeric(18, 5)
para que coincida con Sale.total y SaleDetail.subtotal.

Esto previene pérdida de centavos al convertir proformas a ventas.

Revision ID: c3f5a0_proforma_prec
Revises: e2a9de11ecdb
Create Date: 2025-06-01

NOTA: Si tu base tiene múltiples heads en alembic, ejecuta:
    alembic heads
    alembic merge heads -m "merge"
    alembic upgrade head
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "c3f5a0_proforma_prec"
down_revision: Union[str, Sequence[str], None] = "e2a9de11ecdb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Proforma.total: Numeric(12, 2) → Numeric(18, 5)
    with op.batch_alter_table("proformas") as batch_op:
        batch_op.alter_column(
            "total",
            existing_type=sa.Numeric(12, 2),
            type_=sa.Numeric(18, 5),
            existing_nullable=False,
            existing_server_default=sa.text("0"),
        )


def downgrade() -> None:
    with op.batch_alter_table("proformas") as batch_op:
        batch_op.alter_column(
            "total",
            existing_type=sa.Numeric(18, 5),
            type_=sa.Numeric(12, 2),
            existing_nullable=False,
            existing_server_default=sa.text("0"),
        )