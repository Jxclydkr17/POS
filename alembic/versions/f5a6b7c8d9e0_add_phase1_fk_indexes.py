"""add_phase1_fk_indexes

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-04-29 12:00:00.000000

FASE 1 — Fix 1.3: Índices faltantes en Foreign Keys.

Sin estos índices, las queries con JOIN o filtro por FK hacen full table
scan conforme la base de datos crece (inventory_movements ya puede tener
decenas de miles de registros en una ferretería activa).

Nota: credit_sales.sale_id ya tiene UNIQUE constraint, lo cual genera un
índice implícito en SQLite y PostgreSQL; no se crea uno duplicado.
electronic_rep y electronic_rep_reference ya tenían index=True en sus FKs.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Índices a crear: (tabla, nombre_índice, columna)
_INDEXES = [
    ("inventory_movements", "ix_inventory_movements_product_id", "product_id"),
    ("settings",            "ix_settings_default_supplier_id",   "default_supplier_id"),
]


def upgrade() -> None:
    for table, index_name, column in _INDEXES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_index(index_name, [column], unique=False)


def downgrade() -> None:
    for table, index_name, _column in reversed(_INDEXES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(index_name)