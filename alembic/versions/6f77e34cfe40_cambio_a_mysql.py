"""cambio a mysql

Revision ID: 6f77e34cfe40
Revises: 914b7c5478ba
Create Date: 2026-03-28 08:35:36.574218

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f77e34cfe40'
down_revision: Union[str, Sequence[str], None] = '914b7c5478ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
