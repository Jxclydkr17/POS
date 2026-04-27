"""
app/scripts/seed_db.py — Inicialización de datos obligatorios

Crea los datos mínimos para que el POS funcione en una instalación nueva:
  1. Usuario admin inicial
  2. Métodos de pago (catálogo oficial Hacienda)
  3. Fila de configuración (settings) vacía
  4. Perfil emisor placeholder
  5. Actividades económicas (catálogo Hacienda, 203 registros)

USO:
    python -m app.scripts.seed_db          → Ejecutar seed
    python -m app.scripts.seed_db --force  → Re-crear admin aunque exista

SEGURIDAD:
    - El admin se crea con contraseña "admin123" que DEBE cambiarse
      en el primer inicio de sesión.
    - El script es IDEMPOTENTE: si los datos ya existen no los duplica.

AUDITORÍA FIX 1.2: Agregada llamada a import_economic_activities para
que la tabla economic_activities no quede vacía en instalación nueva.
"""

import sys
import argparse
import logging
from pathlib import Path

# Asegurar que el proyecto raíz esté en el path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models.user import User
from app.db.models.payment_method import PaymentMethod
from app.db.models.settings import Settings
from app.db.models.issuer_profile import IssuerProfile
from app.core.security import hash_password

logger = logging.getLogger(__name__)


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


def seed_admin(db: Session, force: bool = False) -> None:
    """Crea el usuario administrador inicial."""
    existing = db.query(User).filter(User.username == "admin").first()

    if existing and not force:
        logger.info("Usuario 'admin' ya existe. Use --force para recrearlo.")
        return

    if existing and force:
        existing.password = hash_password("admin123")
        existing.role = "admin"
        existing.is_active = True
        existing.full_name = "Administrador"
        existing.must_change_password = True
        db.commit()
        logger.info("Usuario 'admin' actualizado (contraseña: admin123).")
        return

    admin = User(
        username="admin",
        password=hash_password("admin123"),
        full_name="Administrador",
        role="admin",
        is_active=True,
        must_change_password=True,
    )
    db.add(admin)
    db.commit()
    logger.info("Usuario 'admin' creado (contraseña: admin123).")
    logger.warning("CAMBIE la contraseña en el primer inicio de sesión.")


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


def run(force: bool = False) -> None:
    """Ejecuta todos los seeds."""
    logger.info("Violette POS — Seed de datos iniciales")

    db = SessionLocal()
    try:
        seed_admin(db, force=force)
        seed_payment_methods(db)
        seed_settings(db)
        seed_issuer_profile(db)
        seed_economic_activities(db)
        logger.info("Seed completado.")
    except Exception as e:
        db.rollback()
        logger.error(f"Error en seed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed de datos iniciales para Violette POS")
    parser.add_argument("--force", action="store_true", help="Forzar recreación del admin")
    args = parser.parse_args()
    run(force=args.force)