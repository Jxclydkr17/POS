"""add_indexes_to_products_and_customers

Revision ID: b5df991dd1f0
Revises: 3b00960438df
Create Date: 2025-12-29 16:32:43.571837

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = 'b5df991dd1f0'
down_revision: Union[str, Sequence[str], None] = '3b00960438df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Índices en products
    op.create_index('ix_products_barcode', 'products', ['barcode'])
    op.create_index('ix_products_code', 'products', ['code'])
    
    # Índices en customers
    op.create_index('ix_customers_email', 'customers', ['email'])
    op.create_index('ix_customers_id_number', 'customers', ['id_number'])
    op.create_index('ix_customers_phone', 'customers', ['phone'])

def downgrade():
    op.drop_index('ix_products_barcode', 'products')
    op.drop_index('ix_products_code', 'products')
    op.drop_index('ix_customers_email', 'customers')
    op.drop_index('ix_customers_id_number', 'customers')
    op.drop_index('ix_customers_phone', 'customers')