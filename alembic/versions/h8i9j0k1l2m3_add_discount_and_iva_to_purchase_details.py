"""add_discount_and_iva_to_purchase_details

Revision ID: h8i9j0k1l2m3
Revises: f7d0c1b2a3e4
Create Date: 2026-05-28 14:00:00.000000

Agrega soporte de descuento por línea e IVA desglosado en purchase_details,
alineando la tabla con la estructura de la factura electrónica CR V4.4.

Columnas nuevas en `purchase_details`:
  - discount_pct    DECIMAL(5,2)  DEFAULT 0.00  — porcentaje de descuento
  - discount_amount DECIMAL(12,2) DEFAULT 0.00  — monto descontado en ₡
  - iva_pct         DECIMAL(5,2)  DEFAULT 13.00 — tarifa de IVA aplicada
  - iva_amount      DECIMAL(12,2) DEFAULT 0.00  — monto de IVA en ₡
  - total_line      DECIMAL(12,2) DEFAULT 0.00  — subtotal_neto + iva_amount

El campo `subtotal` existente pasa a almacenar el *subtotal_neto*
(base imponible = subtotal_bruto − discount_amount).  Para registros
anteriores la semántica no cambia: subtotal_bruto == subtotal_neto
porque discount_amount era implícitamente 0.

Compatibilidad:
  - MySQL  8.0+  : ADD COLUMN nullable/default es operación INSTANT.
  - MySQL  5.7   : ADD COLUMN es INPLACE (sin reescritura de tabla).
  - SQLite       : ADD COLUMN con DEFAULT es compatible desde la v3.25.
  - MariaDB      : ídem MySQL 5.7.
"""
from alembic import op
import sqlalchemy as sa

# ── Identificadores de revisión ──────────────────────────────────────────────
revision = "h8i9j0k1l2m3"
down_revision = "f7d0c1b2a3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Todas las columnas son nullable=False con server_default para no romper
    # filas existentes.  Podemos hacerlo en una sola operación por columna;
    # Alembic emitirá un ALTER TABLE por cada una.
    with op.batch_alter_table("purchase_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "discount_pct",
                sa.DECIMAL(5, 2),
                nullable=False,
                server_default="0.00",
                comment="Porcentaje de descuento aplicado a la línea (0-100)",
            )
        )
        batch_op.add_column(
            sa.Column(
                "discount_amount",
                sa.DECIMAL(12, 2),
                nullable=False,
                server_default="0.00",
                comment="Monto del descuento en colones (subtotal_bruto × discount_pct / 100)",
            )
        )
        batch_op.add_column(
            sa.Column(
                "iva_pct",
                sa.DECIMAL(5, 2),
                nullable=False,
                server_default="13.00",
                comment="Tarifa de IVA aplicada: 0, 1, 2, 4, 8 ó 13",
            )
        )
        batch_op.add_column(
            sa.Column(
                "iva_amount",
                sa.DECIMAL(12, 2),
                nullable=False,
                server_default="0.00",
                comment="Monto de IVA en colones (subtotal_neto × iva_pct / 100)",
            )
        )
        batch_op.add_column(
            sa.Column(
                "total_line",
                sa.DECIMAL(12, 2),
                nullable=False,
                server_default="0.00",
                comment="Total de la línea: subtotal_neto + iva_amount",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("purchase_details") as batch_op:
        batch_op.drop_column("total_line")
        batch_op.drop_column("iva_amount")
        batch_op.drop_column("iva_pct")
        batch_op.drop_column("discount_amount")
        batch_op.drop_column("discount_pct")