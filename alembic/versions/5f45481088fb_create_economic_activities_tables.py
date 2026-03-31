"""create_economic_activities_tables

Revision ID: 5f45481088fb
Revises: f905b7338a79
Create Date: 2026-02-16 10:26:08.968778

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f45481088fb'
down_revision: Union[str, Sequence[str], None] = 'f905b7338a79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # 1. Crear tabla de actividades
    op.create_table(
        "economic_activities",
        sa.Column("code", sa.String(length=10), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
    )

    # 2. Crear tabla pivote para la relación muchos-a-muchos
    op.create_table(
        "customer_economic_activity",
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), primary_key=True),
        sa.Column("activity_code", sa.String(length=10), sa.ForeignKey("economic_activities.code"), primary_key=True),
    )

def downgrade():
    op.drop_table("customer_economic_activity")
    op.drop_table("economic_activities")