"""check_sync

Revision ID: 08ff997cd14f
Revises: 846556b946cd
Create Date: 2026-02-16 10:12:05.913853

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '08ff997cd14f'
down_revision: Union[str, Sequence[str], None] = '846556b946cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
