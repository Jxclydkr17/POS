"""normalize_sale_created_at_to_utc

Revision ID: f6a7b8c9d0e1
Revises: a2b3c4d5e6f7
Create Date: 2026-05-15 12:00:00.000000

FASE 2.2 — Fix 2.2: Normalizar Sale.created_at a UTC.

Antes:
    Sale.created_at usaba `default=now_cr` (hora local CR, UTC-6).
    En SQLite el offset se preservaba dentro del string del datetime,
    en MySQL el offset se truncaba silenciosamente. Las queries de
    rango (`Sale.created_at >= start, <= end`) se comportaban distinto
    según el motor.

Ahora:
    Sale.created_at usa `default=utcnow` (UTC, igual que el resto de
    modelos). Los datos existentes — que estaban en CR — se desplazan
    +6 horas para alinear con la nueva convención.

Comportamiento:
    - SQLite: usa `datetime(created_at, '+6 hours')` (función nativa).
    - MySQL : usa `DATE_ADD(created_at, INTERVAL 6 HOUR)`.
    - Otros motores: se itera en Python (fallback portable).

La migración es segura sobre BD vacía (no-op) y sobre BD nuevas
(no hay filas para tocar).

Downgrade: resta 6 horas, restaurando el comportamiento anterior.
"""
from datetime import timedelta
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _shift_created_at(hours: int) -> None:
    """
    Aplica un offset de `hours` (positivo o negativo) a sales.created_at.

    Usa SQL nativo cuando el dialecto lo soporta (SQLite / MySQL) para
    velocidad; cae a iteración Python para otros motores.
    """
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Caso 1: SQLite — función `datetime()` con modifier
    if dialect == "sqlite":
        # SQLite acepta offsets negativos como '-6 hours'
        sign = "+" if hours >= 0 else "-"
        op.execute(
            sa.text(
                f"UPDATE sales "
                f"SET created_at = datetime(created_at, '{sign}{abs(hours)} hours') "
                f"WHERE created_at IS NOT NULL"
            )
        )
        return

    # Caso 2: MySQL — DATE_ADD con intervalo (acepta negativos)
    if dialect in ("mysql", "mariadb"):
        op.execute(
            sa.text(
                f"UPDATE sales "
                f"SET created_at = DATE_ADD(created_at, INTERVAL {hours} HOUR) "
                f"WHERE created_at IS NOT NULL"
            )
        )
        return

    # Caso 3: Cualquier otro motor — fallback Python (lento pero seguro)
    rows = bind.execute(
        sa.text("SELECT id, created_at FROM sales WHERE created_at IS NOT NULL")
    ).fetchall()
    for row in rows:
        new_dt = row.created_at + timedelta(hours=hours)
        bind.execute(
            sa.text("UPDATE sales SET created_at = :dt WHERE id = :id"),
            {"dt": new_dt, "id": row.id},
        )


def upgrade() -> None:
    """Suma 6 horas: CR → UTC."""
    _shift_created_at(+6)


def downgrade() -> None:
    """Resta 6 horas: UTC → CR (revierte el cambio)."""
    _shift_created_at(-6)