import csv
import os
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models.economic_activity import EconomicActivity

CSV_PATH = os.path.join(os.getcwd(), "economic_activities.csv")

def run():
    if not os.path.exists(CSV_PATH):
        print(f"❌ No se encontró el archivo en: {CSV_PATH}")
        return

    db: Session = SessionLocal()
    created = 0
    updated = 0

    try:
        with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
            # Tu archivo usa comas como separador, eso está bien.
            reader = csv.DictReader(f)
            
            for row in reader:
                # Ajustamos a los nombres reales de tus columnas
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
        print(f"✅ ¡Proceso terminado!")
        print(f"📊 Creados: {created} | Actualizados: {updated}")

    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run()