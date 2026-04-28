"""
app/scripts/restore_db.py — Restaurar base de datos desde backup

USO:
    python -m app.scripts.restore_db                              → Muestra backups y pide elegir
    python -m app.scripts.restore_db backup_violette_db_20250601.sql  → Restaura directamente
    python -m app.scripts.restore_db --latest                     → Restaura el más reciente

SEGURIDAD:
    - Antes de restaurar, se crea un backup automático con tag "pre_restore"
    - Se pide confirmación interactiva (salvo con --yes)
"""

import sys
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.backup_service import restore_backup, list_backups, create_backup

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Restaurar BD de Violette POS desde backup")
    parser.add_argument("filename", nargs="?", default=None, help="Archivo de backup a restaurar")
    parser.add_argument("--latest", action="store_true", help="Restaurar el backup más reciente")
    parser.add_argument("--yes", "-y", action="store_true", help="Saltar confirmación interactiva")
    args = parser.parse_args()

    backups = list_backups()

    # Determinar qué archivo restaurar
    target = args.filename

    if args.latest:
        if not backups:
            logger.error("❌ No hay backups disponibles.")
            sys.exit(1)
        target = backups[0]["filename"]
        logger.info(f"📦 Último backup: {target}")

    if not target:
        # Modo interactivo: mostrar lista y pedir selección
        if not backups:
            logger.error("❌ No hay backups disponibles. Cree uno primero con:")
            logger.error("   python -m app.scripts.backup_db")
            sys.exit(1)

        logger.info(f"\n📦 Backups disponibles ({len(backups)}):\n" + "─" * 60)
        for i, b in enumerate(backups, 1):
            logger.info(f"  [{i}] {b['filename']}  ({b['size_mb']} MB)  {b['created_at']}")
        logger.info("")

        try:
            choice = input("Seleccione el número del backup a restaurar (0 para cancelar): ").strip()
            idx = int(choice)
            if idx == 0:
                logger.info("Operación cancelada.")
                return
            if idx < 1 or idx > len(backups):
                logger.error("❌ Selección inválida.")
                sys.exit(1)
            target = backups[idx - 1]["filename"]
        except (ValueError, EOFError, KeyboardInterrupt):
            logger.info("\nOperación cancelada.")
            return

    # Confirmación
    if not args.yes:
        logger.info(f"\n⚠  Está a punto de RESTAURAR la base de datos desde:")
        logger.info(f"   {target}")
        logger.info(f"\n   Esto REEMPLAZARÁ todos los datos actuales.")
        logger.info(f"   Se creará un backup de seguridad antes de proceder.\n")

        try:
            confirm = input("¿Desea continuar? (escriba 'si' para confirmar): ").strip().lower()
            if confirm not in ("si", "sí", "yes", "s", "y"):
                logger.info("Operación cancelada.")
                return
        except (EOFError, KeyboardInterrupt):
            logger.info("\nOperación cancelada.")
            return

    # Ejecutar restore
    logger.info(f"\n🔄 Restaurando desde {target}...\n")
    try:
        restore_backup(target)
        logger.info("✅ Base de datos restaurada exitosamente.")
        logger.info("   Reinicie el servidor para que los cambios tomen efecto.\n")
    except FileNotFoundError as e:
        logger.error(f"❌ {e}")
        sys.exit(1)
    except RuntimeError as e:
        logger.error(f"❌ Error en restore: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()