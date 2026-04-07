"""Add UNIQUE constraint to credit_sales.sale_id

Evita que una misma venta genere crédito duplicado (Fase 2 — Bug 2.4).

Revision ID: d83fa69bc13a (antes: a1b2_unique_credit_sale)
Revises: f2a0_sync_all_tables
Create Date: 2026-03-28 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "d83fa69bc13a"
down_revision: Union[str, Sequence[str], None] = "567841fa0e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # Verificar si la tabla existe
    if "credit_sales" not in inspector.get_table_names():
        return

    # Verificar si ya existe un unique constraint en sale_id
    existing_uq = inspector.get_unique_constraints("credit_sales")
    has_uq = any(
        "sale_id" in (c.get("column_names") or [])
        for c in existing_uq
    )
    if not has_uq:
        # También verificar índices únicos
        existing_idx = inspector.get_indexes("credit_sales")
        has_uq = any(
            idx.get("unique") and "sale_id" in (idx.get("column_names") or [])
            for idx in existing_idx
        )

    if not has_uq:
        op.create_unique_constraint(
            "uq_credit_sales_sale_id",
            "credit_sales",
            ["sale_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "credit_sales" not in inspector.get_table_names():
        return

    try:
        op.drop_constraint("uq_credit_sales_sale_id", "credit_sales", type_="unique")
    except Exception:
        pass