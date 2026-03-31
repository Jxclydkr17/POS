"""drop_sale_items_table

Revision ID: 3b00960438df
Revises: ec1bb92d5527
Create Date: 2025-12-29 15:51:03.584849

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b00960438df'
down_revision: Union[str, Sequence[str], None] = 'ec1bb92d5527'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.drop_table('sale_items')

def downgrade():
    # Recrear tabla si necesitas rollback (opcional)
    pass
