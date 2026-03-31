"""add_location_fields_to_customer

Revision ID: f905b7338a79
Revises: 08ff997cd14f
Create Date: 2026-02-16 10:13:11.306265

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'f905b7338a79'
down_revision: Union[str, Sequence[str], None] = '08ff997cd14f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOCATION_COLS = [
    ("province_id", sa.String(length=2)),
    ("province_name", sa.String(length=50)),
    ("canton_id", sa.String(length=2)),
    ("canton_name", sa.String(length=80)),
    ("district_id", sa.String(length=2)),
    ("district_name", sa.String(length=80)),
    ("neighborhood", sa.String(length=80)),
]


def upgrade():
    bind = op.get_bind()
    existing = [c["name"] for c in inspect(bind).get_columns("customers")]
    for col_name, col_type in _LOCATION_COLS:
        if col_name not in existing:
            op.add_column("customers", sa.Column(col_name, col_type, nullable=True))


def downgrade():
    for col_name, _ in reversed(_LOCATION_COLS):
        op.drop_column("customers", col_name)