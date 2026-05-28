"""
app/scripts/seed_db.py — Inicialización de datos obligatorios

Crea los datos mínimos para que el POS funcione en una instalación nueva:
  1. Métodos de pago (catálogo oficial Hacienda)
  2. Fila de configuración (settings) vacía
  3. Perfil emisor placeholder
  4. Actividades económicas (catálogo Hacienda, 203 registros)
  5. Catálogo CABYS (descarga desde el Banco Central de Costa Rica)

NO crea ningún usuario administrador. La creación del admin se hace
desde la UI mediante el wizard "Primera ejecución" que se dispara
automáticamente cuando la BD tiene cero usuarios (ver
`ui/login_view.py:_check_needs_setup`).

USO:
    python -m app.scripts.seed_db          → Ejecutar seed

SEGURIDAD:
    - FASE 3.1 — Fix 3.1: ya NO se crea un admin con contraseña
      conocida (antes "admin/admin123"). El dueño de la ferretería
      crea su propio admin con su propia contraseña la primera vez
      que abre la app, gracias al wizard de primera ejecución.
    - El script es IDEMPOTENTE: si los datos ya existen no los duplica.

AUDITORÍA FIX 1.2: Agregada llamada a import_economic_activities para
que la tabla economic_activities no quede vacía en instalación nueva.

CABYS AUTO-DOWNLOAD (esta revisión):
    seed_cabys() descarga el catálogo CABYS del BCCR automáticamente en
    la primera ejecución. La descarga es TOLERANTE A FALLOS: si no hay
    internet o el BCCR está caído, NO aborta el arranque — loggea un
    warning, deja la tabla vacía, y el usuario puede actualizar más
    tarde desde Configuración > CABYS.
    El resultado de la última ejecución del seed queda expuesto en
    `LAST_RUN_RESULT` para que la UI (splash en launcher.py, banner en
    login_view.py) pueda mostrar feedback al usuario.
"""

import sys
import argparse
import logging
from pathlib import Path
from typing import Callable, Optional

# Asegurar que el proyecto raíz esté en el path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy.orm import Session
from app.db.database import SessionLocal
# FASE 3.1 — Fix 3.1: imports de User y hash_password removidos.
# La creación del usuario admin ya no ocurre desde el seed; la hace
# el wizard de la UI vía POST /users/setup.
from app.db.models.payment_method import PaymentMethod
from app.db.models.settings import Settings
from app.db.models.issuer_profile import IssuerProfile
from app.db.models.cabys import Cabys

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Estado del último seed — consumido por la UI (launcher splash
# y banner del diálogo "Primera ejecución") para mostrar feedback
# sobre la descarga del catálogo CABYS.
#
# Valores de "cabys_status":
#   "skipped"    → tabla ya tenía datos, no se intentó descargar
#   "downloaded" → descarga OK
#   "failed"     → se intentó pero falló (sin internet, BCCR caído, etc.)
#   None         → seed aún no ejecutado en este proceso
# ──────────────────────────────────────────────────────────────
LAST_RUN_RESULT: dict = {
    "cabys_status": None,
    "cabys_records": 0,
    "cabys_error": None,
}


# ──────────────────────────────────────────────────────────────
# Catálogo de métodos de pago (Hacienda CR)
# ──────────────────────────────────────────────────────────────
PAYMENT_METHODS = [
    ("01", "Efectivo"),
    ("02", "Tarjeta"),
    ("03", "Cheque"),
    ("04", "Transferencia - depósito bancario"),
    ("05", "Recaudado por terceros"),
    ("06", "Otros"),
    ("99", "Otros medios"),
]


def seed_payment_methods(db: Session) -> None:
    """Inserta los métodos de pago oficiales de Hacienda."""
    existing_codes = {pm.code for pm in db.query(PaymentMethod).all()}
    created = 0

    for code, name in PAYMENT_METHODS:
        if code not in existing_codes:
            db.add(PaymentMethod(code=code, name=name))
            created += 1

    if created:
        db.commit()
        logger.info(f"{created} método(s) de pago creados.")
    else:
        logger.info("Métodos de pago ya existen.")


def seed_settings(db: Session) -> None:
    """Crea la fila de configuración si no existe."""
    existing = db.query(Settings).filter(Settings.id == 1).first()
    if existing:
        logger.info("Configuración (settings) ya existe.")
        return

    s = Settings(
        id=1,
        business_name="Mi Negocio",
        default_tax="13",
        default_currency="CRC",
        exchange_rate=1.00,
        printer_type="network",
        printer_ip="192.168.0.120",
        printer_port=9100,
    )
    db.add(s)
    db.commit()
    logger.info("Configuración inicial creada.")


def seed_issuer_profile(db: Session) -> None:
    """Crea un perfil emisor placeholder si no existe ninguno."""
    existing = db.query(IssuerProfile).first()
    if existing:
        logger.info("Perfil emisor ya existe.")
        return

    profile = IssuerProfile(
        legal_name="NOMBRE LEGAL POR CONFIGURAR",
        id_type="02",
        id_number="000000000",
        email="facturacion@configurar.com",
        branch_code="001",
        terminal_code="00001",
        phone_country_code="506",
    )
    db.add(profile)
    db.commit()
    logger.info("Perfil emisor placeholder creado.")
    logger.warning("Configure los datos reales desde Configuración > Emisor.")


def seed_economic_activities(db: Session) -> None:
    """Importa las actividades económicas de Hacienda desde el CSV."""
    from app.scripts.import_economic_activities import run as import_activities
    import_activities(db=db)


def seed_cabys(db: Session) -> None:
    """
    Descarga el catálogo CABYS del Banco Central de Costa Rica e inserta
    los ~14 000 registros en la tabla `cabys`.

    Características clave:

    - IDEMPOTENTE: si la tabla ya tiene al menos un registro, se omite
      la descarga (mismo patrón que `seed_payment_methods`). Para forzar
      re-descarga el usuario usa POST /settings/update-cabys desde la UI.

    - TOLERANTE A FALLOS: si la descarga falla (sin internet en el
      momento de instalación, BCCR caído, timeout) NO aborta el arranque.
      Loggea un warning, marca el resultado en `LAST_RUN_RESULT` para que
      la UI pueda avisar al usuario, y retorna normalmente. La tabla
      cabys quedará vacía y el usuario podrá actualizarla más tarde
      manualmente desde Configuración > CABYS.

    - PORTABLE: funciona en SQLite, MySQL y MariaDB sin cambios. La
      idempotencia usa ORM (`query(Cabys).limit(1)`) y la inserción
      la hace `update_cabys()` que ya usa `text()` parametrizado portable.

    - NO MODIFICA `update_cabys()`: respeta el contrato existente. Solo
      lo envuelve con manejo de errores extra y actualización de metadata.
    """
    # Idempotencia: verificar con LIMIT 1 (no count) para no escanear las
    # ~14k filas en cada arranque cuando la tabla ya está poblada.
    already_loaded = db.query(Cabys).limit(1).first() is not None
    if already_loaded:
        LAST_RUN_RESULT["cabys_status"] = "skipped"
        # cabys_records y cabys_last_update ya están en Settings de la
        # carga previa; no los tocamos.
        logger.info("Catálogo CABYS ya cargado — descarga omitida.")
        return

    logger.info("Descargando catálogo CABYS del Banco Central de Costa Rica...")

    try:
        # Import diferido: si el módulo falla al importar (ej. openpyxl
        # ausente en una instalación rota) NO debe tirar abajo todo el seed.
        from app.utils.cabys_updater import update_cabys
        total = update_cabys(db=db)
    except Exception as e:
        # Errores típicos aquí:
        #   - requests.exceptions.ConnectionError (sin internet)
        #   - requests.exceptions.Timeout (BCCR lento)
        #   - requests.exceptions.HTTPError (BCCR devolvió 5xx)
        #   - openpyxl errores (formato cambió)
        #   - SQLAlchemyError (fallo al insertar en BD)
        # En CUALQUIER caso seguimos con el arranque.
        db.rollback()
        LAST_RUN_RESULT["cabys_status"] = "failed"
        LAST_RUN_RESULT["cabys_error"] = str(e)
        logger.warning(
            "No se pudo descargar el catálogo CABYS: %s. "
            "El arranque continuará y la tabla cabys quedará vacía. "
            "El usuario puede actualizar el catálogo más tarde desde "
            "Configuración > CABYS.",
            e,
        )
        return

    # Descarga OK — actualizar metadata en Settings (mismo comportamiento
    # que POST /settings/update-cabys para que la UI muestre "Última
    # actualización: hoy" desde el primer arranque).
    try:
        # Import diferido para evitar ciclo con utils.dt si algo cambia.
        from app.utils.dt import utcnow
        settings_row = db.query(Settings).filter(Settings.id == 1).first()
        if settings_row is not None:
            settings_row.cabys_last_update = utcnow()
            settings_row.cabys_records = total
            db.commit()
    except Exception as e:
        # No crítico: el catálogo se cargó OK, solo no actualizamos el
        # campo de "última actualización". El usuario lo verá vacío
        # hasta la próxima actualización manual.
        db.rollback()
        logger.warning(
            "CABYS descargado correctamente (%d registros) pero no se pudo "
            "actualizar la metadata en settings: %s",
            total, e,
        )

    LAST_RUN_RESULT["cabys_status"] = "downloaded"
    LAST_RUN_RESULT["cabys_records"] = total
    logger.info("Catálogo CABYS descargado: %d registros.", total)


def run(force: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None) -> None:
    """
    Ejecuta todos los seeds.

    FASE 3.1 — Fix 3.1: ya no se crea admin automáticamente. El argumento
    `force` se mantiene por retrocompatibilidad pero no hace nada
    (antes forzaba la re-creación del admin con contraseña conocida).

    Parámetros:
        force: obsoleto, ignorado.
        progress_callback: opcional. Si se pasa, se llama con cada paso
            (string en español) para que la UI lo muestre en un splash
            o progress dialog. Las excepciones del callback se ignoran
            para no romper el seed.
    """

    def _step(msg: str) -> None:
        """Reporta un paso al callback (si existe) y al log."""
        logger.info(msg)
        if progress_callback is not None:
            try:
                progress_callback(msg)
            except Exception as cb_err:
                # Un callback roto NUNCA debe abortar el seed.
                logger.debug("progress_callback lanzó excepción: %s", cb_err)

    logger.info("Violette POS — Seed de datos iniciales")

    # Resetear estado por si se llama dos veces en el mismo proceso (tests).
    LAST_RUN_RESULT["cabys_status"] = None
    LAST_RUN_RESULT["cabys_records"] = 0
    LAST_RUN_RESULT["cabys_error"] = None

    db = SessionLocal()
    try:
        # NO seed_admin: el wizard de UI crea el admin con la contraseña
        # del dueño cuando la BD tiene cero usuarios.
        _step("Configurando métodos de pago...")
        seed_payment_methods(db)

        _step("Creando configuración inicial...")
        seed_settings(db)

        _step("Creando perfil emisor...")
        seed_issuer_profile(db)

        _step("Importando actividades económicas...")
        seed_economic_activities(db)

        # CABYS al final porque es el paso más lento (descarga ~14k filas
        # desde el BCCR, 20-30s en conexión típica). Si todo falla antes
        # de llegar aquí, al menos la BD queda con los catálogos locales.
        _step("Descargando catálogo CABYS del BCCR (puede tardar)...")
        seed_cabys(db)

        logger.info("Seed completado.")
    except Exception as e:
        # Importante: este except NO captura fallos de seed_cabys (esos
        # son manejados internamente y nunca propagan). Solo errores
        # críticos en payment_methods / settings / issuer / actividades.
        db.rollback()
        logger.error(f"Error en seed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed de datos iniciales para Violette POS")
    # `--force` queda como flag aceptado pero ya no afecta (no hay admin que recrear)
    parser.add_argument("--force", action="store_true",
                        help="(Obsoleto en Fase 3.1; antes recreaba el admin con contraseña conocida)")
    args = parser.parse_args()
    run(force=args.force)