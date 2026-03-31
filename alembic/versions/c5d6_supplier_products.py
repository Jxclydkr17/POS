"""create_supplier_products_table

Revision ID: c5d6_supplier_products
Revises: b3c4_float_to_numeric
Create Date: 2026-03-30 16:00:00.000000

Fase 1 — Tabla puente proveedor ↔ producto (muchos-a-muchos).
Permite registrar qué proveedores venden qué producto y a qué precio.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "c5d6_supplier_products"
down_revision: Union[str, Sequence[str], None] = "b3c4_float_to_numeric"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Verificar si la tabla ya existe (idempotencia)
    bind = op.get_bind()
    insp = inspect(bind)
    if "supplier_products" in insp.get_table_names():
        return

    op.create_table(
        "supplier_products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "unit_cost",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_purchase_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_preferred",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # Índices individuales para búsquedas frecuentes
    op.create_index(
        "ix_supplier_products_supplier_id",
        "supplier_products",
        ["supplier_id"],
    )
    op.create_index(
        "ix_supplier_products_product_id",
        "supplier_products",
        ["product_id"],
    )

    # Índice único compuesto: un solo registro por par proveedor-producto
    op.create_unique_constraint(
        "uq_supplier_product",
        "supplier_products",
        ["supplier_id", "product_id"],
    )


def downgrade() -> None:
    op.drop_table("supplier_products")