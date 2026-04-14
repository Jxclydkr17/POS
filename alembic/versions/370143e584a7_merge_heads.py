"""merge_heads

Revision ID: 370143e584a7
Revises: b2dfc7cf6f1a, c3f5a0_proforma_prec
Create Date: 2026-04-13 09:14:44.892232

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '370143e584a7'
down_revision: Union[str, Sequence[str], None] = ('b2dfc7cf6f1a', 'c3f5a0_proforma_prec')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
