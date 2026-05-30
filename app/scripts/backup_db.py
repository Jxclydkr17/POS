"""
app/scripts/backup_db.py — Crear backup manual de la base de datos

USO:
    python -m app.scripts.backup_db                  → Backup normal
    python -m app.scripts.backup_db --tag pre_update → Backup con etiqueta
    python -m app.scripts.backup_db --list           → Listar backups existentes
"""

import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.backup_service import create_backup, list_backups
from app.utils.dt import format_cr  # FASE 4 — Fix 4.2: mostrar fecha en hora CR

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Backup de la BD de Violette POS")
    parser.add_argument("--tag", default="", help="Etiqueta para el nombre del backup")
    parser.add_argument("--list", action="store_true", help="Listar backups existentes")
    args = parser.parse_args()

    if args.list:
        backups = list_backups()
        if not backups:
            logger.info("No hay backups disponibles.")
            return

        logger.info(f"\n📦 Backups disponibles ({len(backups)}):\n" + "─" * 60)
        for b in backups:
            # FASE 4 — Fix 4.2: convertir ISO UTC → hora CR para display.
            created = format_cr(datetime.fromisoformat(b['created_at']))
            logger.info(f"  {b['filename']}  ({b['size_mb']} MB)  {created}")
        logger.info("")
        return

    logger.info("\n💾 Creando backup de la base de datos...\n")
    try:
        path = create_backup(tag=args.tag)
        logger.info("✅ Backup creado exitosamente:")
        logger.info(f"   📁 {path}\n")
    except RuntimeError as e:
        logger.error(f"❌ Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()