"""fix_missing_economic_tables

Revision ID: 914b7c5478ba
Revises: 5f45481088fb
Create Date: 2026-02-16 11:26:46.491340

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '914b7c5478ba'
down_revision: Union[str, Sequence[str], None] = '5f45481088fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
