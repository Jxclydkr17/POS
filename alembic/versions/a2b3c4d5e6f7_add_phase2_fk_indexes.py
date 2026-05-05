"""add_phase2_fk_indexes

Revision ID: a2b3c4d5e6f7
Revises: f5a6b7c8d9e0
Create Date: 2026-05-04 12:00:00.000000

FASE 2 — Rendimiento: Índices en Foreign Keys faltantes.

Sin índices en FK, las queries con JOIN o filtro por estas columnas
hacen full table scan. Conforme la ferretería acumula ventas, compras
y proformas, la degradación se hace notar.

Columnas indexadas:
  - proformas.customer_id, user_id, converted_sale_id
  - proforma_details.proforma_id, product_id
  - purchases.supplier_id
  - sale_details.product_id
  - sales.updated_by
  - purchase_credit_notes.product_id
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Índices a crear: (tabla, nombre_índice, columna)
_INDEXES = [
    ("proformas",             "ix_proformas_customer_id",           "customer_id"),
    ("proformas",             "ix_proformas_user_id",               "user_id"),
    ("proformas",             "ix_proformas_converted_sale_id",     "converted_sale_id"),
    ("proforma_details",      "ix_proforma_details_proforma_id",   "proforma_id"),
    ("proforma_details",      "ix_proforma_details_product_id",    "product_id"),
    ("purchases",             "ix_purchases_supplier_id",           "supplier_id"),
    ("sale_details",          "ix_sale_details_product_id",         "product_id"),
    ("sales",                 "ix_sales_updated_by",                "updated_by"),
    ("purchase_credit_notes", "ix_purchase_credit_notes_product_id","product_id"),
]


def upgrade() -> None:
    for table, index_name, column in _INDEXES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_index(index_name, [column], unique=False)


def downgrade() -> None:
    for table, index_name, _column in reversed(_INDEXES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(index_name)