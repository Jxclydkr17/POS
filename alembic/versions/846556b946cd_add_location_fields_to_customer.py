"""add_location_fields_to_customer (DUPLICADO vacío de f905b7338a79)

⚠️  Esta migración es un placeholder duplicado — fue generada por accidente.
La migración real es f905b7338a79. Se mantiene en la cadena por compatibilidad.

Revision ID: 846556b946cd
Revises: 04caac52643e
Create Date: 2026-02-16 09:41:22.863315

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '846556b946cd'
down_revision: Union[str, Sequence[str], None] = '04caac52643e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass