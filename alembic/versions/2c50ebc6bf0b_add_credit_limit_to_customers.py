"""add credit_limit to customers

Revision ID: 2c50ebc6bf0b
Revises: b5df991dd1f0
Create Date: 2026-01-12 15:58:49.228291

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c50ebc6bf0b'
down_revision: Union[str, Sequence[str], None] = 'b5df991dd1f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("customers", sa.Column("credit_limit", sa.Float(), nullable=False, server_default="0"))

def downgrade():
    op.drop_column("customers", "credit_limit")
