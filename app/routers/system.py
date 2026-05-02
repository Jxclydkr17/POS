"""
app/routers/system.py — Endpoints de sistema y administración

FASE 5:
  - Estado de cola offline
  - Forzar procesamiento de cola
  - Verificar actualizaciones
  - Health check extendido
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.utils.responses import success_response

router = APIRouter(prefix="/system", tags=["Sistema"])


# ══════════════════════════════════════════════════════════════
# Cola offline
# ══════════════════════════════════════════════════════════════

@router.get("/offline-queue/status", dependencies=[Depends(get_current_user)])
def offline_queue_status(db: Session = Depends(get_db)):
    """Estado actual de la cola offline."""
    from app.services.offline_queue import get_queue_status
    return get_queue_status(db)


@router.get("/offline-queue/list", dependencies=[Depends(get_current_user)])
def offline_queue_list(db: Session = Depends(get_db)):
    """Lista comprobantes en cola offline."""
    from app.services.offline_queue import get_queued_invoices
    return get_queued_invoices(db)


@router.post("/offline-queue/process", dependencies=[Depends(get_current_user)])
def offline_queue_process():
    """Fuerza un ciclo de procesamiento inmediato de la cola offline."""
    from app.services.offline_queue import force_process_queue
    processed = force_process_queue()
    return success_response(
        message=f"{processed} comprobante(s) procesados",
        data={"processed": processed},
    )


@router.get("/connectivity", dependencies=[Depends(get_current_user)])
def check_connectivity():
    """Verifica conexión a internet y a Hacienda."""
    from app.services.offline_queue import check_internet
    has_internet = check_internet()
    return {
        "internet": has_internet,
        "hacienda_reachable": has_internet,
    }


# ══════════════════════════════════════════════════════════════
# Actualización
# ══════════════════════════════════════════════════════════════

@router.get("/update/check", dependencies=[Depends(get_current_user)])
def check_for_updates():
    """Verifica si hay una versión más reciente disponible."""
    from app.services.updater import check_update
    return check_update()


@router.post("/update/download", dependencies=[Depends(get_current_user)])
def download_update():
    """Descarga la actualización más reciente (si hay)."""
    from app.services.updater import download_update
    result = download_update()
    return success_response(
        message=result.get("message", ""),
        data=result,
    )


# ══════════════════════════════════════════════════════════════
# Diagnóstico extendido
# ══════════════════════════════════════════════════════════════

@router.get("/diagnostics", dependencies=[Depends(get_current_user)])
def system_diagnostics(db: Session = Depends(get_db)):
    """Diagnóstico completo del sistema."""
    import platform
    import os
    from pathlib import Path
    from app.core.config import settings, is_sqlite, APP_DIR
    from app.core.credentials import (
        hacienda_user as _fn_hac_user, hacienda_password as _fn_hac_pass,
        hacienda_env as _fn_hac_env, hacienda_cert_path as _fn_hac_cert,
    )
    _cred_hacienda_user = _fn_hac_user()
    _cred_hacienda_pass = _fn_hac_pass()
    _cred_hacienda_env = _fn_hac_env()
    _cred_hacienda_cert = _fn_hac_cert()

    diag = {
        "app": {
            "name": settings.app_name,
            "env": settings.app_env,
            "debug": settings.app_debug,
            "db_engine": settings.db_engine,
        },
        "system": {
            "os": platform.system(),
            "os_version": platform.version(),
            "python": platform.python_version(),
            "architecture": platform.machine(),
        },
        "database": {
            "engine": settings.db_engine,
            "connected": False,
        },
        "hacienda": {
            "configured": bool(_cred_hacienda_user and _cred_hacienda_pass),
            "env": _cred_hacienda_env,
            "cert_configured": bool(_cred_hacienda_cert),
        },
        "storage": {
            "app_dir": str(APP_DIR),
            "logs_dir_exists": (APP_DIR / "logs").exists(),
            "backups_dir_exists": (APP_DIR / "app" / "backups").exists(),
        },
    }

    # Verificar BD
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        diag["database"]["connected"] = True
    except Exception as e:
        diag["database"]["error"] = str(e)

    # Cola offline
    try:
        from app.services.offline_queue import get_queue_status
        diag["offline_queue"] = get_queue_status(db)
    except Exception:
        diag["offline_queue"] = {"error": "No disponible"}

    return diag


# ══════════════════════════════════════════════════════════════
# FASE 3 — Fix 3.1: Listado de endpoints (admin)
# Permite ver los endpoints disponibles en producción sin
# necesidad de activar /docs.  Solo accesible por admin.
# ══════════════════════════════════════════════════════════════

@router.get("/routes", dependencies=[Depends(require_role("admin"))])
def list_routes(request: Request):
    """Lista todos los endpoints registrados (solo admin)."""
    routes = []
    for route in request.app.routes:
        if hasattr(route, "methods"):
            routes.append({
                "path": route.path,
                "methods": sorted(route.methods),
                "name": route.name,
            })
    routes.sort(key=lambda r: r["path"])
    return success_response(
        message=f"{len(routes)} endpoints registrados",
        data=routes,
    )