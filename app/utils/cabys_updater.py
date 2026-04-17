import pandas as pd
import requests
import io
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from app.core.logger import logger   
from app.utils.dt import now_cr

URL_CABYS = "https://www.bccr.fi.cr/indicadores-economicos/cabys/Catalogo-de-bienes-servicios.xlsx"


def update_cabys(db: Session) -> int:
    """
    Actualiza el catálogo CABYS usando la sesión del POS (db).
    Devuelve la cantidad de registros cargados.
    """

    logger.info(f"🔄 Descargando CABYS desde Hacienda... ({now_cr().strftime('%Y-%m-%d %H:%M')})")

    # Descargar archivo Excel
    response = requests.get(URL_CABYS, timeout=20)
    response.raise_for_status()

    # --- INICIO DE LA CORRECCIÓN ---
    try:
        # Leemos la hoja 0 (Catálogo) con encabezado en fila 2 (índice 1)
        df = pd.read_excel(io.BytesIO(response.content), sheet_name=0, header=1)
        logger.info("Hoja 0 ('Catálogo') cargada correctamente con encabezado en la fila 2.")
    except Exception as e:
        logger.error(f"Error al cargar la hoja 0 del Excel: {e}")
        raise Exception(f"No se pudo leer la hoja 'Catálogo' del Excel: {e}")

    logger.info(f"📄 {len(df)} registros leídos del archivo CABYS.")
    # --- FIN DE LECTURA DEL EXCEL ---

    # Normalizar columnas
    df.columns = [col.strip().lower() for col in df.columns]

    # Identificar nombres reales de columnas
    code_col = next((c for c in df.columns if c == "categoría 9"), None)
    desc_col = next((c for c in df.columns if c == "descripción (categoría 9)"), None)
    iva_col = next((c for c in df.columns if c == "impuesto"), None)

    if not code_col or not desc_col:
        logger.error("❌ No se encontraron columnas válidas en el archivo CABYS.")
        logger.error(
            f"Encontradas: Código={code_col}, Descripción={desc_col}, IVA={iva_col}. "
            f"Disponibles: {df.columns.tolist()}"
        )
        raise Exception(
            "No se encontraron columnas válidas. Revise 'Categoría 9', 'Descripción (categoría 9)' e 'Impuesto'."
        )

    # --- Ajustes solicitados ---
    MAX_DESC_LENGTH = 500  # límite para evitar truncamiento en MySQL

    data = []

    for _, row in df.iterrows():
        # Código completo (con puntos)
        code = str(row.get(code_col, "")).strip()

        # --- Truncado de descripción ---
        desc_raw = str(row.get(desc_col, "")).strip()
        desc = desc_raw[:MAX_DESC_LENGTH]

        # IVA
        iva_raw = str(row.get(iva_col, "0.13")).replace("%", "").strip() if iva_col else "0.13"

        try:
            iva_float = float(iva_raw)

            # Si viene 0.13 -> convertir a 13
            iva_calculated = iva_float * 100 if iva_float < 1 else iva_float

            # Forzar a entero porque la columna DB es INTEGER
            iva = int(iva_calculated)
        except ValueError:
            iva = 13  # valor por defecto

        # Tomar solo códigos finales (13 dígitos quitando puntos)
        if code and desc and len(code.replace(".", "")) == 13:
            data.append((code, desc, iva))

    # Guardar en DB
    logger.info("🧹 Limpiando tabla CABYS...")
    db.execute(text("DELETE FROM cabys;"))

    logger.info("💾 Insertando registros CABYS...")
    insert_data = [{"code": c, "description": d, "iva": i} for (c, d, i) in data]

    db.execute(
        text("INSERT INTO cabys (code, description, iva) VALUES (:code, :description, :iva)"),
        insert_data
    )
    db.commit()

    logger.info(f"✅ CABYS actualizado correctamente ({len(data)} registros).")

    return len(data)