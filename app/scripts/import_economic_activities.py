"""
app/scripts/import_economic_activities.py — Importador de actividades económicas

Importa las 203 actividades económicas de Hacienda CR desde el CSV
al tabla economic_activities. Idempotente: hace upsert por código.

AUDITORÍA FIX 1.2 / 4.2: Corregida ruta del CSV para usar APP_DIR
en vez de os.getcwd(), que falla cuando se ejecuta como .exe (PyInstaller
cambia el directorio de trabajo).

FASE 4 — Fix 4.8: el CSV se movió de la raíz del proyecto a `app/data/`
por organización. La ruta primaria ahora es `app/data/economic_activities.csv`.
Se mantiene un fallback a la ubicación legacy (raíz) con un warning, para
que las instalaciones que aún no movieron el archivo no se queden sin
catálogo. Cuando todas las instalaciones estén actualizadas, el bloque
de legacy puede borrarse.
"""

import csv
import logging
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models.economic_activity import EconomicActivity
from app.core.config import APP_DIR

logger = logging.getLogger(__name__)

# ── FASE 4 — Fix 4.8: ubicación canónica y fallback legacy ──
CSV_PATH = APP_DIR / "app" / "data" / "economic_activities.csv"
_LEGACY_CSV_PATH = APP_DIR / "economic_activities.csv"


def _resolve_csv_path() -> str | None:
    """
    Devuelve la ruta del CSV o None si no existe en ninguna ubicación.

    Prioriza la ruta canónica (app/data/). Si no existe ahí pero sí en
    la raíz del proyecto, lo acepta con un warning para suavizar la
    transición — el .spec del .exe ya copia el CSV a la ubicación nueva,
    así que el fallback solo aplica a installs en dev/source que aún no
    movieron el archivo.
    """
    if CSV_PATH.exists():
        return str(CSV_PATH)
    if _LEGACY_CSV_PATH.exists():
        logger.warning(
            "economic_activities.csv encontrado en la raíz del proyecto "
            "(ubicación legacy). Por favor muévalo a 'app/data/' — el .spec "
            "del .exe ya espera la nueva ruta y el fallback se removerá en "
            "una versión futura."
        )
        return str(_LEGACY_CSV_PATH)
    return None


def run(db: Session | None = None):
    """
    Importa actividades económicas desde el CSV.

    Acepta una sesión existente (para ser llamado desde seed_db)
    o crea una propia si se ejecuta standalone.
    """
    csv_path = _resolve_csv_path()
    if csv_path is None:
        logger.warning(
            "No se encontró economic_activities.csv ni en %s ni en %s. "
            "La tabla de actividades económicas se quedará vacía.",
            CSV_PATH, _LEGACY_CSV_PATH,
        )
        return

    own_session = db is None
    if own_session:
        db = SessionLocal()

    created = 0
    updated = 0

    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
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
            logger.info(f"  ✅ Actividades económicas: {created} creadas, {updated} actualizadas.")
        else:
            logger.info("  ⏭  Actividades económicas ya están al día.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error importando actividades económicas: {e}")
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run()