"""add_printer_usb_and_profile_fields

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-25 18:00:00.000000

FASE 2 — Fix 2.5 (cerrado): Soporte ESC/POS real con python-escpos.

Antes:
    `printer_type` aceptaba 'network'/'usb'/'none' pero ninguno de los
    dos primeros estaba realmente implementado: enviaban PDF crudo al
    puerto 9100 — eso corrompe el output de impresoras térmicas POS.
    El enum se mantenía como placeholder para no romper configs
    existentes (ver comentario en schemas/settings.py).

Ahora:
    'network' y 'usb' funcionan de verdad usando python-escpos:
      - 'network' usa printer_ip + printer_port (sin cambios al schema).
      - 'usb' necesita vendor_id/product_id — los agregamos acá.

    También agregamos:
      - printer_profile: nombre opcional del perfil python-escpos
        (e.g. 'TM-T20II') para mejor soporte de cut/QR en modelos
        específicos. NULL → la librería usa 'default'.
      - printer_paper_width_mm: 58 (POS pequeño) o 80 (más común).
        Afecta a cuántos caracteres caben por línea.

Compatibilidad de motores:
    - MySQL (5.7, 8.0, 8.4, MariaDB): ADD COLUMN nullable es operación
      "INSTANT" en MySQL 8.0+ y "INPLACE" en 5.7 — sin reescritura de
      tabla, sin bloqueo de escrituras. Para `settings` (1 fila) es
      irrelevante igual.
    - SQLite (dev local): ALTER TABLE ADD COLUMN funciona desde la
      versión 3.2.0 (2004); todas las columnas son nullable por
      default. No requiere recreate.

Diseño idempotente:
    MySQL hace auto-commit por DDL: si un ADD COLUMN falla a mitad de
    la migración, las columnas previas ya están agregadas y NO se
    revierten al re-ejecutar `alembic upgrade head`. Para soportar
    re-ejecución sin error "Duplicate column name", chequeamos cada
    columna con el inspector antes de agregarla. El UPDATE de
    inicialización lleva `WHERE IS NULL` para no pisar valores ya
    seteados en re-ejecuciones.

Downgrade:
    Igual de defensivo: solo dropea las columnas que existen, para
    permitir re-ejecuciones y para no romper si alguien ya dropeó una
    manualmente.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'g7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Lista declarativa de las columnas que esta migración agrega.
# Mantener acá centralizado evita el patrón de copiar nombres y errar
# de tipeo entre upgrade/downgrade/_existing_columns.
_NEW_COLUMNS = [
    # (nombre, tipo SQLAlchemy)
    ('printer_usb_vendor_id', sa.String(length=10)),
    ('printer_usb_product_id', sa.String(length=10)),
    ('printer_profile', sa.String(length=40)),
    ('printer_paper_width_mm', sa.Integer()),
]


def _existing_columns(table_name: str) -> set:
    """
    Devuelve el set de nombres de columnas existentes en una tabla.

    Usa el Inspector de SQLAlchemy: funciona en MySQL, MariaDB, SQLite
    y PostgreSQL sin SQL específico de dialecto.
    """
    bind = op.get_bind()
    inspector = inspect(bind)
    return {col['name'] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _existing_columns('settings')

    # 1) ADD COLUMN para cada campo que falte.
    #    En MySQL cada op.add_column emite un ALTER TABLE separado.
    #    Para `settings` (tabla de 1 fila) esto es irrelevante en
    #    performance. Si en un futuro crece, se puede empaquetar en un
    #    solo ALTER TABLE con SQL crudo — pero la simplicidad gana acá.
    for col_name, col_type in _NEW_COLUMNS:
        if col_name in existing:
            # Idempotencia: si re-ejecutamos por un fallo previo, no
            # tirar "Duplicate column name 'X'" en MySQL.
            continue
        op.add_column(
            'settings',
            sa.Column(col_name, col_type, nullable=True),
        )

    # 2) Inicializar printer_paper_width_mm = 80 en las filas existentes.
    #
    #    Por qué no `server_default='80'` en el ADD COLUMN:
    #      - server_default queda fijo en el DDL de la tabla, lo cual
    #        ata el schema a una preferencia de UI. Si en el futuro
    #        queremos default 58 para algún cliente, hay que migrar
    #        DDL. Manejarlo en el UPDATE (de una sola vez) y en el
    #        modelo Python (default=80) deja el schema neutro.
    #      - server_default + nullable=True + MySQL viejo (5.6) a
    #        veces tira warnings de strict mode con tipos numéricos.
    #
    #    `WHERE IS NULL` protege contra re-ejecuciones: si la columna
    #    ya tenía valores (porque el upgrade corrió antes), no los
    #    pisamos.
    op.execute(
        "UPDATE settings "
        "SET printer_paper_width_mm = 80 "
        "WHERE printer_paper_width_mm IS NULL"
    )


def downgrade() -> None:
    existing = _existing_columns('settings')

    # Dropeamos en orden inverso al upgrade. No es estrictamente
    # necesario (no hay dependencias entre las columnas), pero es buena
    # higiene y facilita debugging si alguien ve los logs.
    #
    # Idempotente: si una columna no existe (porque alguien la dropeó
    # manualmente o porque el upgrade falló antes de agregarla), no
    # explotamos.
    for col_name, _ in reversed(_NEW_COLUMNS):
        if col_name not in existing:
            continue
        op.drop_column('settings', col_name)