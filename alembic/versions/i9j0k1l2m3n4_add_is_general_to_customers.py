"""add_is_general_to_customers

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-05-29 12:00:00.000000

Agrega la columna booleana `is_general` a la tabla `customers`.

Marca al "Cliente General" (mostrador / publico general). El backend usa
esta bandera —junto con el caso de venta sin cliente (customer_id = NULL)—
para negar credito, reemplazando el antiguo hardcode `customer_id == 1`
en sale_crud.py, que bloqueaba por error al PRIMER cliente real registrado
(quien obtenia id=1) y, ademas, no reconocia a un Cliente General con otro id.

Comportamiento de la bandera:
  - is_general = True  -> no admite credito (es el mostrador).
  - is_general = False -> cliente normal, admite credito si tiene cupo.

Compatibilidad:
  - SQLite : ADD COLUMN con DEFAULT es compatible (>= 3.25).
  - MySQL  : ADD COLUMN nullable=False con DEFAULT es INSTANT/INPLACE.
Las filas existentes quedan con is_general = 0 (False) gracias al
server_default. La fila del Cliente General se crea/marca en el seed
(app/scripts/seed_db.py).
"""
from alembic import op
import sqlalchemy as sa

# -- Identificadores de revision ---------------------------------------------
revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("customers") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_general",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
                comment="True si es el Cliente General (mostrador). No admite credito.",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("customers") as batch_op:
        batch_op.drop_column("is_general")