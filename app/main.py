# app/main.py
"""
FASE 5 — Hardening para producción:
  - CORS restringido (solo localhost en producción)
  - Manejo global de errores con respuestas consistentes
  - Cola offline para comprobantes sin internet
  - Logging estructurado
"""
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import os
# FASE 4.1 — Fix: import con efecto colateral (registra todos los modelos en
# Base.metadata). Antes era `import app.db.models`, que liga el nombre `app` al
# PAQUETE app; más abajo `app = FastAPI(...)` lo reasignaba a la instancia. Esa
# doble definición de `app` (paquete → instancia) era frágil: cualquier código
# entre medias que usara `app` esperando la instancia, o después esperando el
# paquete, fallaría en silencio. El alias `_models` registra los modelos igual
# pero ya NO toca el nombre `app`.
import app.db.models as _models  # noqa: F401

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
from app.constants.status_enums import ProformaStatus
from sqlalchemy.orm import Session
from app.db.database import get_db


# ══════════════════════════════════════════════════════════════
# Lifespan (reemplaza @app.on_event deprecado — Fase 8, Bug 8.1)
# ══════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestiona startup y shutdown de la aplicación."""

    # ── STARTUP ──────────────────────────────────────────────

    # ── FASE 2 — Fix 2.2: Migrar directorios legacy a DATA_DIR ──
    # Debe ir ANTES de cualquier código que dependa del cert/logo
    # (en particular, antes de los background tasks de Hacienda).
    try:
        from app.core.data_migration import migrate_legacy_data_dirs
        migrate_legacy_data_dirs()
    except Exception as e:
        logger.warning(f"Migración de directorios legacy no se completó: {e}")

    # Proformas: vencimiento automático
    from app.db.database import safe_session
    from app.db.models.proforma import Proforma

    def _do_expire():
        with safe_session() as db:
            try:
                from app.utils.dt import utcnow as _utcnow
                # valid_until se almacena como naive UTC (ver proforma_crud._now_naive),
                # así que la comparación debe ser naive vs naive.
                now = _utcnow().replace(tzinfo=None)
                count = (
                    db.query(Proforma)
                    .filter(Proforma.status == ProformaStatus.VIGENTE, Proforma.valid_until < now)
                    .update({"status": ProformaStatus.VENCIDA}, synchronize_session="fetch")
                )
                if count:
                    db.commit()
                    logger.info(f"Startup: {count} proforma(s) marcadas como VENCIDA.")
            except Exception:
                db.rollback()

    _do_expire()

    async def _periodic_expire():
        while True:
            # ── FASE C — Fix C.4: Intervalo reducido a 10 min (era 1h) ──
            # Si una proforma vence a las 10:30, ahora se marca VENCIDA
            # a más tardar a las 10:40 (antes podía tardar hasta las 11:30).
            # El CRUD ya hace verificación on-demand al consultar, pero
            # esto cubre los casos donde nadie consulta activamente.
            await asyncio.sleep(600)
            # ── FASE 3 — Fix 3.4: Ejecutar query síncrona en thread separado
            # para no bloquear el event loop de asyncio durante el commit. ──
            await asyncio.to_thread(_do_expire)

    expire_task = asyncio.create_task(_periodic_expire())

    # Hacienda background tasks
    from app.core.credentials import hacienda_user, hacienda_password, hacienda_env
    has_user = bool(hacienda_user())
    has_pass = bool(hacienda_password())

    if has_user and has_pass:
        try:
            from app.einvoice.hacienda_poller import start_background_tasks
            start_background_tasks()
            logger.info(f"Hacienda: background tasks iniciados | env={hacienda_env()}")
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
        
    # Verificar API keys encriptadas
    try:
        from app.core.crypto import check_encrypted_keys_on_startup
        with safe_session() as _db:
            check_encrypted_keys_on_startup(_db)
    except Exception as e:
        logger.warning(f"No se pudo verificar API keys: {e}")

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
        ("app.db.crud.sale_crud", "stop_pdf_executor"),
    ]:
        try:
            mod = __import__(stop_fn_path[0], fromlist=[stop_fn_path[1]])
            getattr(mod, stop_fn_path[1])()
        except Exception:
            pass


# Crear aplicación
# ── FASE 4 — Fix 4.5: docs no se activan por accidente en producción ──
# Antes:
#   `_show_docs = settings.app_debug or settings.enable_docs`
#   → si alguien dejaba `app_debug=true` por error en el .env de
#     producción, /docs y /openapi.json quedaban expuestos, dándole a
#     un atacante con acceso a localhost el mapa completo de la API.
#
# Ahora (defensa en profundidad):
#   - enable_docs=true   → /docs ON. Opt-in explícito (Fix 3.1) para
#                          diagnóstico en producción; se respeta sin
#                          condiciones porque la variable existe
#                          precisamente para ese caso de uso.
#   - app_debug=true     → /docs ON sólo si APP_ENV NO es producción.
#                          En producción `app_debug` se ignora para
#                          esta decisión y queda un warning en logs.
#
# Además /openapi.json se gatea junto con /docs y /redoc: antes seguía
# accesible aunque /docs estuviera apagado, filtrando el schema completo.
# El mismo trato recibe la sección de "links" en GET / más abajo.
#
# Convención APP_ENV: igual que `app/core/logger.py` — "production" y
# "prod" (case-insensitive) cuentan como producción.
_is_production = (settings.app_env or "").strip().lower() in ("production", "prod")

if _is_production:
    _show_docs = settings.enable_docs
    if settings.app_debug and not settings.enable_docs:
        logger.warning(
            "app_debug=true detectado con app_env=%s. Se IGNORA app_debug "
            "para activar /docs (Fix 4.5). Si realmente necesita la API "
            "documentada en producción, use ENABLE_DOCS=true explícitamente.",
            settings.app_env,
        )
else:
    _show_docs = settings.app_debug or settings.enable_docs

app = FastAPI(
    title=settings.app_name,
    description="Sistema de Punto de Venta Inteligente - Violette POS",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if _show_docs else None,
    redoc_url="/redoc" if _show_docs else None,
    # ── Fix 4.5: cerrar /openapi.json junto con la UI de docs ──
    # Sin esto el schema queda accesible aunque /docs esté oculto.
    openapi_url="/openapi.json" if _show_docs else None,
)


# ══════════════════════════════════════════════════════════════
# FASE 5.1: CORS restringido
# ══════════════════════════════════════════════════════════════
# El launcher puede caer a un puerto alterno si el 8000 está ocupado por
# un programa ajeno (launcher.py: VIOLETTE_PORT_RANGE_START/END, default
# 8000..8009). Por eso CORS debe permitir TODOS los puertos de ese rango
# en localhost/127.0.0.1; si solo permitiéramos el 8000, un cliente que
# apunte al puerto efectivo (p. ej. 8001) sería bloqueado en producción.
# Se leen las MISMAS variables de entorno que el launcher para no quedar
# desincronizados, con idéntica validación defensiva.
def _cors_port_range() -> range:
    def _read_int(name: str, default: int) -> int:
        raw = os.getenv(name)
        if not raw:
            return default
        try:
            v = int(raw)
        except ValueError:
            return default
        return v if 1024 <= v <= 65535 else default

    start = _read_int("VIOLETTE_PORT_RANGE_START", 8000)
    end = _read_int("VIOLETTE_PORT_RANGE_END", 8009)
    if end < start:
        end = start
    # Cota defensiva: evita generar una lista enorme si el rango es absurdo.
    if end - start > 100:
        end = start + 100
    return range(start, end + 1)


_CORS_ORIGINS: list[str] = []
for _port in _cors_port_range():
    _CORS_ORIGINS.append(f"http://127.0.0.1:{_port}")
    _CORS_ORIGINS.append(f"http://localhost:{_port}")
# Frontend web de desarrollo (Vite/React) en el 3000, si se usa.
_CORS_ORIGINS += [
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
# FASE 3 — Fix 3.3: Middleware de modo mantenimiento
# Rechaza requests mientras se restaura un backup para evitar
# que consultas concurrentes accedan a una BD a medio copiar.
# ══════════════════════════════════════════════════════════════
@app.middleware("http")
async def _maintenance_guard(request: Request, call_next):
    from app.services.backup_service import is_maintenance_mode
    if is_maintenance_mode() and not request.url.path.startswith("/settings/restore"):
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "message": "Sistema en mantenimiento — restore en curso. Intente en unos segundos.",
            },
        )
    return await call_next(request)


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

    # ── FASE 3 — Fix 3.5: defensa en profundidad como /docs ──
    # Bug previo: `if settings.app_debug:` exponía type(exc).__name__ + str(exc)
    # al cliente HTTP siempre que app_debug=true. Si alguien dejaba
    # APP_DEBUG=true por error en producción, cada excepción no manejada
    # filtraba detalles internos (clase de excepción, mensaje real con
    # posibles paths, queries SQL, valores, etc.) al cliente.
    #
    # Mismo patrón que `_show_docs` arriba (línea ~195): en producción se
    # ignora `app_debug` sin importar su valor. El warning de startup
    # (líneas ~197-203) ya alerta al operador si quedó en true.
    if settings.app_debug and not _is_production:
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
    # Si el HTTPException tiene un detail dict (viene de error_response / lógica de negocio),
    # preservar el mensaje original en vez de sobreescribirlo con "Ruta no encontrada".
    if hasattr(exc, "detail") and isinstance(exc.detail, dict) and "message" in exc.detail:
        return JSONResponse(
            status_code=404,
            content=exc.detail,
        )
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
app.include_router(system_router)


# ══════════════════════════════════════════════════════════════
# Endpoints base
# ══════════════════════════════════════════════════════════════
@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    # ── FASE B — Fix B.2: Usa Depends(get_db) en lugar de SessionLocal manual ──
    # Antes creaba SessionLocal() a mano, sin beneficiarse del cleanup automático
    # de FastAPI. Ahora sigue el mismo patrón que todos los demás endpoints.
    from sqlalchemy import text

    db_ok = False
    db_error = None
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        db_error = str(e)

    status_str = "healthy" if db_ok else "degraded"
    result = {
        "status": status_str,
        "app": settings.app_name,
        "version": app.version,
        "env": settings.app_env,
        "timestamp": utcnow().isoformat(),
        "database": db_ok,
    }
    if db_error:
        result["db_error"] = db_error
    return result


@app.get("/")
def root():
    # ── FASE 4 — Fix 4.5: anunciar /docs y /redoc sólo si están activos ──
    # No tiene sentido (y filtra info) sugerir endpoints inexistentes.
    info: dict = {
        "message": f"Bienvenido a {settings.app_name}",
        "health": "/health",
    }
    if _show_docs:
        info["docs"] = "/docs"
        info["redoc"] = "/redoc"
    return info