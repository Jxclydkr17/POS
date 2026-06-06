"""add_printer_system_name

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-06-06 08:30:00.000000

AUTODETECCIÓN DE IMPRESORAS — modo "system".

Contexto:
    El modo `usb` (ESC/POS por pyusb) obliga al usuario a conocer y
    escribir el USB Vendor ID / Product ID a mano, y en Windows exige
    instalar un backend libusb (Zadig), reemplazando el driver normal
    de la impresora. Es la mayor fricción de la configuración.

Esta migración:
    Agrega `printer_system_name` para soportar un nuevo modo `system`
    que imprime ESC/POS en RAW por el spooler del sistema operativo
    (Windows: win32print / Win32Raw), eligiendo la impresora por
    NOMBRE desde un desplegable. No necesita VID/PID ni libusb.

    El enum de `printer_type` pasa a {"system","network","usb","none"}
    a nivel de validación Pydantic (schemas/settings.py). NO se cambia
    el DDL de `printer_type` (sigue siendo String(20)), por lo que esta
    migración solo agrega la nueva columna.

Compatibilidad de motores:
    - MySQL (5.7, 8.0, 8.4, MariaDB): ADD COLUMN nullable es operación
      "INSTANT"/"INPLACE" — sin reescritura ni bloqueo. Para `settings`
      (1 fila) es irrelevante igual.
    - SQLite (dev local): ALTER TABLE ADD COLUMN funciona; las columnas
      nuevas son nullable por default.

Diseño idempotente (igual que g7b8c9d0e1f2):
    Se chequea con el inspector si la columna ya existe antes de
    agregarla, para tolerar re-ejecución de `alembic upgrade head` sin
    error "Duplicate column name".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'k1l2m3n4o5p6'
down_revision: Union[str, None] = 'j0k1l2m3n4o5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Columnas que agrega esta migración. (nombre, tipo SQLAlchemy)
_NEW_COLUMNS = [
    ('printer_system_name', sa.String(length=200)),
]


def _existing_columns(table_name: str) -> set:
    """Set de nombres de columnas existentes (cross-dialecto)."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return {col['name'] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _existing_columns('settings')
    for col_name, col_type in _NEW_COLUMNS:
        if col_name in existing:
            # Idempotencia: no re-agregar si ya existe.
            continue
        op.add_column(
            'settings',
            sa.Column(col_name, col_type, nullable=True),
        )


def downgrade() -> None:
    existing = _existing_columns('settings')
    for col_name, _ in reversed(_NEW_COLUMNS):
        if col_name not in existing:
            continue
        op.drop_column('settings', col_name)