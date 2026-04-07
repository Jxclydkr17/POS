"""add permissions column to users

Revision ID: g1h2_user_permissions
Revises: e6f7_ai_config
Create Date: 2026-04-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "872473d1b86f"
down_revision: Union[str, Sequence[str], None] = "870a23186c5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("permissions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "permissions")