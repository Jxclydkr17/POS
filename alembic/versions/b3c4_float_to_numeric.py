"""Fase 3 — Float a Numeric en columnas monetarias

Convierte columnas monetarias de Float (IEEE 754) a Numeric(12,2)
para evitar errores de redondeo acumulativos.

Tablas afectadas:
  - sales.total
  - customers.credit_balance, credit_limit
  - cash_movements.amount
  - credit_sales.total_amount
  - credits.amount
  - sale_details.tax_rate, exon_tarifa, factor_calculo_iva

Revision ID: b3c4_float_to_numeric
Revises: a1b2_unique_credit_sale
Create Date: 2026-03-28 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "b3c4_float_to_numeric"
down_revision: Union[str, Sequence[str], None] = "a1b2_unique_credit_sale"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Columnas a migrar: (tabla, columna, tipo_nuevo, tipo_rollback)
_CHANGES = [
    ("sales",          "total",          sa.Numeric(12, 2), sa.Float()),
    ("customers",      "credit_balance", sa.Numeric(12, 2), sa.Float()),
    ("customers",      "credit_limit",   sa.Numeric(12, 2), sa.Float()),
    ("cash_movements", "amount",         sa.Numeric(12, 2), sa.Float()),
    ("credit_sales",   "total_amount",   sa.Numeric(12, 2), sa.Float()),
    ("credits",        "amount",         sa.Numeric(12, 2), sa.Float()),
    ("sale_details",   "tax_rate",       sa.Numeric(5, 2),  sa.Float()),
    ("sale_details",   "exon_tarifa",    sa.Numeric(5, 2),  sa.Float()),
    ("sale_details",   "factor_calculo_iva", sa.Numeric(5, 4), sa.Float()),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    for table, column, new_type, _old_type in _CHANGES:
        if table not in existing_tables:
            continue
        cols = [c["name"] for c in inspector.get_columns(table)]
        if column not in cols:
            continue

        # batch_alter_table funciona tanto en MySQL como SQLite
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.Float(),
                type_=new_type,
                existing_nullable=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    for table, column, new_type, old_type in _CHANGES:
        if table not in existing_tables:
            continue
        cols = [c["name"] for c in inspector.get_columns(table)]
        if column not in cols:
            continue

        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=new_type,
                type_=old_type,
                existing_nullable=True,
            )