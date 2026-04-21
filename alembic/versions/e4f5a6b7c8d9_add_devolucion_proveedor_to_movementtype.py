"""add_devolucion_proveedor_to_movementtype

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-04-21 12:00:00.000000

AUDITORÍA FIX 2.3: Agrega el valor 'devolucion_proveedor' al enum
MovementType en la columna inventory_movements.type.

Esto distingue devoluciones de CLIENTE (devolucion → suma stock)
de devoluciones a PROVEEDOR (devolucion_proveedor → resta stock).

- SQLite: No requiere cambio de esquema (almacena como VARCHAR).
- MySQL:  ALTER TABLE para agregar el nuevo valor al ENUM nativo.
"""
from typing import Sequence, Union

from alembic import op
from alembic import context


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    """Detecta si el motor actual es SQLite."""
    return context.get_context().dialect.name == "sqlite"


def upgrade() -> None:
    if _is_sqlite():
        # SQLite almacena enums como VARCHAR — no necesita cambio de esquema.
        # El nuevo valor simplemente se acepta al insertarse.
        return

    # MySQL: modificar la columna ENUM para incluir el nuevo valor
    op.execute(
        "ALTER TABLE inventory_movements "
        "MODIFY COLUMN `type` ENUM("
        "'venta','devolucion','devolucion_proveedor','entrada','ajuste','anulacion'"
        ") NOT NULL"
    )


def downgrade() -> None:
    if _is_sqlite():
        return

    # MySQL: revertir al enum original (sin devolucion_proveedor)
    # NOTA: si existen filas con 'devolucion_proveedor', el downgrade
    # las convertirá a '' (string vacío) en MySQL — eso es intencional
    # como señal de que se necesita limpiar antes de hacer downgrade.
    op.execute(
        "ALTER TABLE inventory_movements "
        "MODIFY COLUMN `type` ENUM("
        "'venta','devolucion','entrada','ajuste','anulacion'"
        ") NOT NULL"
    )