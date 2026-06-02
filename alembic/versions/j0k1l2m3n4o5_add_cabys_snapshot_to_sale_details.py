"""add_cabys_snapshot_to_sale_details

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-06-01 12:00:00.000000

FASE 1 — Correctitud fiscal.

Agrega la columna `cabys_code` a la tabla `sale_details`.

Guarda el CABYS vigente del producto AL MOMENTO de la venta (snapshot).
Antes, xml_builder_v44 leia el CABYS actual del producto al construir el
XML; si el CABYS se editaba/corregia entre la venta y el build (por ejemplo
ventas hechas offline que se facturan despues), la factura no reflejaba lo
que realmente se vendio. Con este snapshot la factura queda congelada.

Comportamiento:
  - Productos del inventario  -> sale_crud guarda product.cabys_code aqui.
  - Productos comunes         -> siguen usando `common_cabys_code`.
  - Ventas antiguas (NULL)    -> el builder cae al CABYS actual del
                                 producto (retrocompatibilidad).

Compatibilidad:
  - SQLite : ADD COLUMN nullable es nativo (>= 3.25), via batch_alter_table.
  - MySQL  : ADD COLUMN nullable es INSTANT/INPLACE.
Las filas existentes quedan con cabys_code = NULL.
"""
from alembic import op
import sqlalchemy as sa

# -- Identificadores de revision ---------------------------------------------
revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sale_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "cabys_code",
                sa.String(length=20),
                nullable=True,
                comment="Snapshot del CABYS del producto al momento de la venta.",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("sale_details") as batch_op:
        batch_op.drop_column("cabys_code")