# app/main.py
"""
FASE 5 — Hardening para producción:
  - CORS restringido (solo localhost en producción)
  - Manejo global de errores con respuestas consistentes
  - Cola offline para comprobantes sin internet
  - Logging estructurado
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
import asyncio
import traceback
import app.db.models

from app.routers import (
    analytics_router,
    cabys_router,
    cash_router,
    categories_router,
    credits_router,
    customers_router,
    expenses_router,
    financial_reports_router,
    products_router,
    purchases_router,
    reports_extended_router,
    sales_router,
    settings_router,
    suppliers_router,
    users_router,
    einvoice_router,
    proformas_router,
)

from app.core.config import settings, APP_VERSION
from app.core.logger import logger
from app.ai.insights.router import router as ai_insights_router

from app.routers.economic_activities import router as economic_activities_router
from app.routers.locations import router as locations_router

from app.routers.electronic_reps import router as ereps_router
from app.ai.chat_handler import router as chat_router
from app.routers.dashboard import router as dashboard_router
from app.routers.receptor_messages import router as receptor_messages_router

# FASE 5: Router de sistema
from app.routers.system import router as system_router

from app.utils.dt import utcnow


# ══════════════════════════════════════════════════════════════
# Lifespan (reemplaza @app.on_event deprecado — Fase 8, Bug 8.1)
# ══════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestiona startup y shutdown de la aplicación."""

    # ── STARTUP ──────────────────────────────────────────────

    # Proformas: vencimiento automático
    from app.db.database import SessionLocal
    from app.db.models.proforma import Proforma

    def _do_expire():
        db = SessionLocal()
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            count = (
                db.query(Proforma)
                .filter(Proforma.status == "VIGENTE", Proforma.valid_until < now)
                .update({"status": "VENCIDA"}, synchronize_session="fetch")
            )
            if count:
                db.commit()
                logger.info(f"Startup: {count} proforma(s) marcadas como VENCIDA.")
        except Exception:
            db.rollback()
        finally:
            db.close()

    _do_expire()

    async def _periodic_expire():
        while True:
            await asyncio.sleep(3600)
            # ── FASE 3 — Fix 3.4: Ejecutar query síncrona en thread separado
            # para no bloquear el event loop de asyncio durante el commit. ──
            await asyncio.to_thread(_do_expire)

    expire_task = asyncio.create_task(_periodic_expire())

    # Hacienda background tasks
    has_user = bool(settings.hacienda_user)
    has_pass = bool(settings.hacienda_password)

    if has_user and has_pass:
        try:
            from app.einvoice.hacienda_poller import start_background_tasks
            start_background_tasks()
            logger.info(f"Hacienda: background tasks iniciados | env={settings.hacienda_env}")
        except Exception as e:
            logger.error(f"Hacienda: error iniciando background tasks: {e}")
    else:
        logger.info("Hacienda: background tasks NO iniciados (credenciales no configuradas)")

    # Backup automático
    try:
        from app.services.backup_service import start_scheduled_backups
        start_scheduled_backups()
    except Exception as e:
        logger.warning(f"Backup automático no disponible: {e}")

    # Cola offline
    try:
        from app.services.offline_queue import start_offline_processor
        start_offline_processor()
        logger.info("Cola offline iniciada")
    except Exception as e:
        logger.warning(f"Cola offline no disponible: {e}")

    yield  # ── La app corre aquí ──

    # ── SHUTDOWN ─────────────────────────────────────────────
    expire_task.cancel()

    for stop_fn_path in [
        ("app.einvoice.hacienda_poller", "stop_background_tasks"),
        ("app.services.backup_service", "stop_scheduled_backups"),
        ("app.services.offline_queue", "stop_offline_processor"),
    ]:
        try:
            mod = __import__(stop_fn_path[0], fromlist=[stop_fn_path[1]])
            getattr(mod, stop_fn_path[1])()
        except Exception:
            pass


# Crear aplicación
app = FastAPI(
    title=settings.app_name,
    description="Sistema de Punto de Venta Inteligente - Violette POS",
    version=APP_VERSION,
    lifespan=lifespan,
    # En producción, ocultar docs
    docs_url="/docs" if settings.app_debug else None,
    redoc_url="/redoc" if settings.app_debug else None,
)


# ══════════════════════════════════════════════════════════════
# FASE 5.1: CORS restringido
# ══════════════════════════════════════════════════════════════
_CORS_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
]

# ── FASE 1 — Fix 1.5: CORS seguro ──
# En desarrollo, permitir todo pero SIN credentials (la spec lo prohíbe con "*")
# En producción, origins explícitos con credentials habilitado
if settings.app_debug:
    _CORS_ORIGINS = ["*"]

_allow_credentials = _CORS_ORIGINS != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)


# ══════════════════════════════════════════════════════════════
# FASE 5.3: Manejo global de errores
# ══════════════════════════════════════════════════════════════
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    """
    Captura cualquier excepción no manejada y retorna un JSON limpio
    en vez de un stack trace al usuario.
    """
    # Loggear el error completo al archivo
    logger.error(
        f"Error no manejado | {request.method} {request.url.path} | "
        f"{type(exc).__name__}: {exc}",
        exc_info=True,
    )

    # En desarrollo, incluir detalle; en producción, mensaje genérico
    if settings.app_debug:
        detail = f"{type(exc).__name__}: {str(exc)}"
    else:
        detail = "Error interno del servidor. Contacte al administrador."

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Error interno del servidor",
            "detail": detail,
            "timestamp": utcnow().isoformat(),
        },
    )


@app.exception_handler(404)
async def _not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "success": False,
            "message": f"Ruta no encontrada: {request.url.path}",
        },
    )



# ══════════════════════════════════════════════════════════════
# Registrar routers
# ══════════════════════════════════════════════════════════════
app.include_router(users_router)
app.include_router(einvoice_router)
app.include_router(products_router)
app.include_router(customers_router)
app.include_router(sales_router)
app.include_router(credits_router)
app.include_router(suppliers_router)
app.include_router(categories_router)
app.include_router(purchases_router)
app.include_router(expenses_router)
app.include_router(financial_reports_router)
app.include_router(analytics_router)
app.include_router(cabys_router)
app.include_router(cash_router)
app.include_router(settings_router)
app.include_router(reports_extended_router)
app.include_router(ai_insights_router)
app.include_router(economic_activities_router)
app.include_router(locations_router)
app.include_router(ereps_router)
app.include_router(chat_router)
app.include_router(dashboard_router)
app.include_router(proformas_router)
app.include_router(receptor_messages_router)
app.include_router(system_router)  # FASE 5


# ══════════════════════════════════════════════════════════════
# Endpoints base
# ══════════════════════════════════════════════════════════════
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": app.version,
        "env": settings.app_env,
        "timestamp": utcnow().isoformat(),
    }


@app.get("/")
def root():
    return {
        "message": f"Bienvenido a {settings.app_name}",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }