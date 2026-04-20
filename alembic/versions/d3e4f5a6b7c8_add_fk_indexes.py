"""add_fk_indexes

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-04-20 12:00:00.000000

FASE 3 — Rendimiento de BD: Agregar índices a Foreign Keys consultadas
frecuentemente que SQLAlchemy no indexa automáticamente.

Sin estos índices, las consultas con JOIN o filtro por FK hacen full table scan.
Con miles de registros (ventas, productos, compras), la degradación es notable.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Índices a crear: (tabla, nombre_índice, columna)
_INDEXES = [
    ("purchase_details", "ix_purchase_details_purchase_id", "purchase_id"),
    ("products",         "ix_products_category_id",         "category_id"),
    ("products",         "ix_products_supplier_id",         "supplier_id"),
    ("expenses",         "ix_expenses_user_id",             "user_id"),
    ("sales",            "ix_sales_customer_id",            "customer_id"),
    ("sales",            "ix_sales_user_id",                "user_id"),
    ("sales",            "ix_sales_cash_session_id",        "cash_session_id"),
    ("settings_audit_log", "ix_settings_audit_log_user_id", "user_id"),
]


def upgrade() -> None:
    for table, index_name, column in _INDEXES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_index(index_name, [column], unique=False)


def downgrade() -> None:
    for table, index_name, _column in reversed(_INDEXES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(index_name)