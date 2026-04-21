"""
app/scripts/import_economic_activities.py — Importador de actividades económicas

Importa las 203 actividades económicas de Hacienda CR desde el CSV
al tabla economic_activities. Idempotente: hace upsert por código.

AUDITORÍA FIX 1.2 / 4.2: Corregida ruta del CSV para usar APP_DIR
en vez de os.getcwd(), que falla cuando se ejecuta como .exe (PyInstaller
cambia el directorio de trabajo).
"""

import csv
import os
import logging
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models.economic_activity import EconomicActivity
from app.core.config import APP_DIR

logger = logging.getLogger(__name__)

CSV_PATH = str(APP_DIR / "economic_activities.csv")


def run(db: Session | None = None):
    """
    Importa actividades económicas desde el CSV.

    Acepta una sesión existente (para ser llamado desde seed_db)
    o crea una propia si se ejecuta standalone.
    """
    if not os.path.exists(CSV_PATH):
        msg = f"No se encontró el archivo en: {CSV_PATH}"
        logger.warning(msg)
        print(f"  ⚠  {msg}")
        return

    own_session = db is None
    if own_session:
        db = SessionLocal()

    created = 0
    updated = 0

    try:
        with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                raw_code = (row.get("codigo_atv") or "").strip()
                desc = (row.get("nombre_atv") or "").strip()

                if not raw_code or not desc:
                    continue

                # Normalización: Hacienda espera 6 dígitos.
                # Si viene "11701", lo convertimos en "011701"
                code = raw_code.zfill(6)

                # Buscar si ya existe
                obj = db.query(EconomicActivity).filter_by(code=code).first()
                if obj:
                    if obj.description != desc:
                        obj.description = desc
                        updated += 1
                else:
                    db.add(EconomicActivity(code=code, description=desc))
                    created += 1

                # Commit cada 200 filas para que sea rápido
                if (created + updated) % 200 == 0:
                    db.commit()

        db.commit()
        total = created + updated
        if total > 0:
            print(f"  ✅ Actividades económicas: {created} creadas, {updated} actualizadas.")
        else:
            print("  ⏭  Actividades económicas ya están al día.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error importando actividades económicas: {e}")
        print(f"  ❌ Error importando actividades económicas: {e}")
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    run()