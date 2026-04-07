"""fix sale_total precision to match sale_details

Revision ID: h2i3_sale_total_precision
Revises: g1h2_add_user_permissions
Create Date: 2025-04-06
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "e2a9de11ecdb"
down_revision = "872473d1b86f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Sale.total: Numeric(12,2) → Numeric(18,5)
    # Iguala la precisión de SaleDetail.subtotal para evitar truncamiento.
    with op.batch_alter_table("sales") as batch_op:
        batch_op.alter_column(
            "total",
            existing_type=sa.Numeric(12, 2),
            type_=sa.Numeric(18, 5),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("sales") as batch_op:
        batch_op.alter_column(
            "total",
            existing_type=sa.Numeric(18, 5),
            type_=sa.Numeric(12, 2),
            existing_nullable=False,
        )