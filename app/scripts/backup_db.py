"""
app/scripts/backup_db.py — Crear backup manual de la base de datos

USO:
    python -m app.scripts.backup_db                  → Backup normal
    python -m app.scripts.backup_db --tag pre_update → Backup con etiqueta
    python -m app.scripts.backup_db --list           → Listar backups existentes
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.backup_service import create_backup, list_backups


def main():
    parser = argparse.ArgumentParser(description="Backup de la BD de Violette POS")
    parser.add_argument("--tag", default="", help="Etiqueta para el nombre del backup")
    parser.add_argument("--list", action="store_true", help="Listar backups existentes")
    args = parser.parse_args()

    if args.list:
        backups = list_backups()
        if not backups:
            print("No hay backups disponibles.")
            return

        print(f"\n📦 Backups disponibles ({len(backups)}):\n" + "─" * 60)
        for b in backups:
            print(f"  {b['filename']}  ({b['size_mb']} MB)  {b['created_at']}")
        print()
        return

    print("\n💾 Creando backup de la base de datos...\n")
    try:
        path = create_backup(tag=args.tag)
        print(f"✅ Backup creado exitosamente:")
        print(f"   📁 {path}\n")
    except RuntimeError as e:
        print(f"❌ Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()