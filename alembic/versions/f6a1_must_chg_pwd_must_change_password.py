"""FASE 6: add must_change_password to users

Revision ID: f6a1_must_chg_pwd
Revises: 370143e584a7
Create Date: 2025-04-15
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f6a1_must_chg_pwd'
down_revision: Union[str, None] = '370143e584a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), nullable=True, server_default=sa.text('0')))


def downgrade() -> None:
    op.drop_column('users', 'must_change_password')