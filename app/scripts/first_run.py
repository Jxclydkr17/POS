"""
app/scripts/first_run.py — Configuración inicial de Violette POS

Ejecuta todo lo necesario para una instalación nueva:
  1. Crea/verifica la base de datos
  2. Crea todas las tablas
  3. Ejecuta seed de datos iniciales
  4. Genera SECRET_KEY si no existe
  5. Muestra instrucciones al usuario

USO:
    python -m app.scripts.first_run              → Setup completo
    python -m app.scripts.first_run --check      → Solo verificar estado
    python -m app.scripts.first_run --reset-db   → Recrear BD desde cero (PELIGROSO)
"""

import sys
import os
import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Asegurar path del proyecto
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def check_status() -> dict:
    """Verifica el estado actual de la instalación."""
    status = {
        "env_exists": False,
        "db_engine": "unknown",
        "db_exists": False,
        "tables_count": 0,
        "has_admin": False,
        "has_settings": False,
        "has_issuer": False,
        "has_payment_methods": False,
    }

    # .env
    from app.core.config import APP_DIR
    status["env_exists"] = (APP_DIR / ".env").exists()

    # BD
    from app.core.config import settings, is_sqlite
    status["db_engine"] = settings.db_engine

    try:
        from app.db.database import engine
        from sqlalchemy import inspect

        insp = inspect(engine)
        tables = insp.get_table_names()
        status["db_exists"] = True
        status["tables_count"] = len(tables)

        if "users" in tables:
            from app.db.database import safe_session
            from app.db.models.user import User
            from app.db.models.settings import Settings
            from app.db.models.issuer_profile import IssuerProfile
            from app.db.models.payment_method import PaymentMethod

            # ── FASE 2: Una sola sesión para todas las verificaciones ──
            with safe_session() as db:
                status["has_admin"] = db.query(User).filter(User.username == "admin").first() is not None

                if "settings" in tables:
                    status["has_settings"] = db.query(Settings).filter(Settings.id == 1).first() is not None

                if "issuer_profiles" in tables:
                    status["has_issuer"] = db.query(IssuerProfile).first() is not None

                if "payment_methods" in tables:
                    status["has_payment_methods"] = db.query(PaymentMethod).count() >= 5

    except Exception as e:
        status["db_error"] = str(e)

    return status


def run_setup(reset_db: bool = False) -> None:
    """Ejecuta el setup completo."""
    from app.core.config import settings, is_sqlite, APP_DIR

    logger.info("\n" + "=" * 55)
    logger.info("  Violette POS — Configuración Inicial")
    logger.info("=" * 55)

    # ── Paso 1: Verificar .env ──
    env_path = APP_DIR / ".env"
    env_example = APP_DIR / ".env.example"

    if not env_path.exists():
        if env_example.exists():
            import shutil
            shutil.copy2(env_example, env_path)
            logger.info("  ✅ Archivo .env creado desde template.")
        else:
            # Crear .env mínimo para SQLite
            env_path.write_text(
                "# Violette POS — Configuración\n"
                "APP_NAME=ViolettePOS\n"
                "DB_ENGINE=sqlite\n"
                "DB_SQLITE_PATH=violette_pos.db\n"
                f"SECRET_KEY={os.environ.get('SECRET_KEY', '')}\n",
                encoding="utf-8",
            )
            logger.info("  ✅ Archivo .env creado (modo SQLite).")
    else:
        logger.info("  ✅ Archivo .env encontrado.")

    logger.info("  📦 Motor de BD: %s", settings.db_engine.upper())

    if is_sqlite():
        db_path = APP_DIR / settings.db_sqlite_path
        logger.info("  📁 Archivo BD: %s", db_path)

        if reset_db and db_path.exists():
            db_path.unlink()
            logger.info("  🗑  Base de datos eliminada (--reset-db).")

    # ── Paso 2: Crear tablas ──
    logger.info("\n  [2/4] Creando tablas...")
    from app.db.database import Base, engine
    import app.db.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    from sqlalchemy import inspect
    insp = inspect(engine)
    tables = insp.get_table_names()
    logger.info("  ✅ %d tablas verificadas/creadas.", len(tables))

    # ── Paso 3: Seed ──
    logger.info("\n  [3/4] Datos iniciales...")
    from app.scripts.seed_db import run as run_seed
    run_seed(force=False)

    # ── Paso 4: Resumen ──
    logger.info("\n  [4/4] Verificación final...")
    status = check_status()

    all_ok = all([
        status["has_admin"],
        status["has_settings"],
        status["has_issuer"],
        status["has_payment_methods"],
    ])

    if all_ok:
        logger.info("  ✅ Instalación completa.")
    else:
        if not status["has_admin"]:
            logger.warning("  ⚠  Falta usuario admin.")
        if not status["has_settings"]:
            logger.warning("  ⚠  Falta configuración.")
        if not status["has_issuer"]:
            logger.warning("  ⚠  Falta perfil emisor.")
        if not status["has_payment_methods"]:
            logger.warning("  ⚠  Faltan métodos de pago.")

    logger.info("\n" + "=" * 55)
    logger.info("  Próximos pasos:")
    logger.info("  1. Inicie la aplicación: python launcher.py")
    logger.info("  2. Inicie sesión: admin / admin123")
    logger.info("  3. Configure el emisor en Configuración > Emisor")
    logger.info("  4. Cargue su certificado .p12 de Hacienda")
    logger.info("=" * 55 + "\n")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Setup inicial de Violette POS")
    parser.add_argument("--check", action="store_true", help="Solo verificar estado")
    parser.add_argument("--reset-db", action="store_true", help="Recrear BD (PELIGROSO)")
    args = parser.parse_args()

    if args.check:
        status = check_status()
        logger.info("\n📊 Estado de la instalación:\n")
        for k, v in status.items():
            icon = "✅" if v else "❌"
            if isinstance(v, bool):
                logger.info("  %s %s: %s", icon, k, v)
            else:
                logger.info("  📌 %s: %s", k, v)
        logger.info("")
        return

    if args.reset_db:
        confirm = input("⚠  PELIGRO: Esto eliminará todos los datos. Escriba 'ELIMINAR' para confirmar: ")
        if confirm != "ELIMINAR":
            logger.info("Operación cancelada.")
            return

    run_setup(reset_db=args.reset_db)


if __name__ == "__main__":
    main()