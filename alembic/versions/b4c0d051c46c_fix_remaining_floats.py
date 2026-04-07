"""Fase 2 — Fix remaining Float columns and Numeric without precision

Convierte columnas monetarias/fiscales restantes de Float a Numeric
y agrega precisión a columnas Numeric que no la tenían.

Tablas afectadas:
  - products: price, cost, tax_rate, factor_calculo_iva,
              imp_esp_impuesto_unidad, imp_esp_porcentaje,
              imp_esp_volumen_unidad_consumo, imp_esp_cantidad_unidad_medida
  - sale_details: unit_price, subtotal (Numeric sin precisión → con precisión)
  - proformas: total
  - proforma_details: tax_rate

Revision ID: b4c0d051c46c (antes: d4e5_fix_remaining_floats)
Revises: c5d6_supplier_products
Create Date: 2026-04-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "b4c0d051c46c"
down_revision: Union[str, Sequence[str], None] = "4f8930c14162"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Columnas a migrar: (tabla, columna, tipo_nuevo, tipo_rollback)
_CHANGES = [
    # ── Product: monetarios ──
    ("products", "price",                        sa.Numeric(12, 2),  sa.Float()),
    ("products", "cost",                         sa.Numeric(12, 2),  sa.Float()),
    ("products", "tax_rate",                     sa.Numeric(5, 2),   sa.Float()),
    ("products", "factor_calculo_iva",           sa.Numeric(5, 4),   sa.Float()),
    # ── Product: impuestos específicos ──
    ("products", "imp_esp_impuesto_unidad",      sa.Numeric(18, 5),  sa.Float()),
    ("products", "imp_esp_porcentaje",           sa.Numeric(5, 2),   sa.Float()),
    ("products", "imp_esp_volumen_unidad_consumo", sa.Numeric(12, 3), sa.Float()),
    ("products", "imp_esp_cantidad_unidad_medida", sa.Numeric(12, 3), sa.Float()),
    # ── SaleDetail: precisión faltante ──
    ("sale_details", "unit_price",               sa.Numeric(18, 5),  sa.Numeric()),
    ("sale_details", "subtotal",                 sa.Numeric(18, 5),  sa.Numeric()),
    # ── Proforma ──
    ("proformas", "total",                       sa.Numeric(12, 2),  sa.Float()),
    # ── ProformaDetail ──
    ("proforma_details", "tax_rate",             sa.Numeric(5, 2),   sa.Float()),
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

        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=_old_type,
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