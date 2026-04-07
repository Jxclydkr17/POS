"""create_ai_config_table

Revision ID: 870a23186c5d (antes: e6f7_ai_config)
Revises: d4e5_fix_remaining_floats
Create Date: 2026-04-04 20:00:00.000000

Fase 2 — Tabla de configuración de IA.
Almacena proveedor activo, API key encriptada, modelo y parámetros.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "870a23186c5d"
down_revision: Union[str, Sequence[str], None] = "b4c0d051c46c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Verificar si la tabla ya existe (idempotencia)
    bind = op.get_bind()
    insp = inspect(bind)
    if "ai_config" in insp.get_table_names():
        return

    op.create_table(
        "ai_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "provider",
            sa.String(50),
            nullable=False,
            server_default="none",
        ),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_tokens",
            sa.Integer(),
            nullable=False,
            server_default="1024",
        ),
        sa.Column(
            "temperature",
            sa.Float(),
            nullable=False,
            server_default="0.3",
        ),
        sa.Column("custom_prompt", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("ai_config")