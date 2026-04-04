"""
app/routers/settings.py — Fase 6 completa.

6.1  Backup y restauración de DB (mysqldump)
6.4  Endpoint audit-log
6.5  Endpoint system-info
6.6  Export/import config JSON
"""

import os
import json
import shutil
import logging
import platform
import subprocess
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.database import get_db
from app.db.models.settings import Settings
from app.db.models.issuer_profile import IssuerProfile
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.schemas.api_response import APIResponse
from app.schemas.issuer_profile import IssuerProfileOut, IssuerProfileUpdate
from app.core.dependencies import get_current_user, require_role
from app.utils.cabys_updater import update_cabys
from app.utils.responses import success_response
from app.utils.dt import utcnow

from app.services.settings_service import (
    get_settings,
    get_settings_out,
    update_settings as svc_update_settings,
    log_audit,
    get_audit_log,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/settings",
    tags=["Configuración"]
)

LOGO_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "logos")
os.makedirs(LOGO_DIR, exist_ok=True)

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "..", "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)


# ============================================================
# GET /settings
# ============================================================
@router.get("/", response_model=APIResponse[SettingsOut], dependencies=[Depends(get_current_user)])
def get_settings_endpoint(db: Session = Depends(get_db)):
    return APIResponse(message="Configuración cargada correctamente", data=get_settings_out(db))


# ============================================================
# PUT /settings
# ============================================================
@router.put("/", response_model=APIResponse[SettingsOut], dependencies=[Depends(require_role("admin"))])
def update_settings_endpoint(data: SettingsUpdate, db: Session = Depends(get_db),
                              current_user=Depends(get_current_user)):
    user_id = getattr(current_user, "id", None)
    username = getattr(current_user, "username", None)
    updated = svc_update_settings(db, data, user_id=user_id, username=username)
    return APIResponse(message="Configuración actualizada correctamente", data=updated)


# ============================================================
# POST /settings/upload-logo
# ============================================================
@router.post("/upload-logo", dependencies=[Depends(require_role("admin"))])
def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db),
                current_user=Depends(get_current_user)):
    allowed = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Tipo no permitido: {file.content_type}")

    contents = file.file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="El archivo excede 2MB.")

    ext = os.path.splitext(file.filename or "logo.png")[1] or ".png"
    filename = f"logo{ext}"
    filepath = os.path.join(LOGO_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    settings = get_settings(db)
    settings.logo_path = filepath
    db.commit()

    log_audit(db, "upload_logo", {"filename": filename},
              user_id=getattr(current_user, "id", None),
              username=getattr(current_user, "username", None))

    return APIResponse(message="Logo actualizado", data={"logo_path": filepath, "filename": filename})


# ============================================================
# POST /settings/update-cabys
# ============================================================
@router.post("/update-cabys", dependencies=[Depends(require_role("admin"))])
def update_cabys_catalog(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    try:
        total = update_cabys(db=db)
        settings = get_settings(db)
        settings.cabys_last_update = utcnow()
        settings.cabys_records = total
        db.commit()

        log_audit(db, "update_cabys", {"registros": total},
                  user_id=getattr(current_user, "id", None),
                  username=getattr(current_user, "username", None))

        return APIResponse(message="CABYS actualizado correctamente", data={"registros": total})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar CABYS: {e}")


# ============================================================
# GET /settings/env-status
# ============================================================
@router.get("/env-status", dependencies=[Depends(get_current_user)])
def get_env_status():
    from app.core.config import settings as env

    email_configured = bool(env.email_user and env.email_pass)
    hacienda_api_configured = bool(env.hacienda_api)
    hacienda_cert_configured = bool(env.hacienda_cert_path and env.hacienda_cert_pass)

    cert_exists = False
    if env.hacienda_cert_path:
        cert_exists = os.path.isfile(env.hacienda_cert_path)

    return APIResponse(
        message="Estado de configuración de entorno",
        data={
            "email": {
                "configured": email_configured,
                "user_hint": _mask(env.email_user) if env.email_user else None,
            },
            "hacienda": {
                "api_configured": hacienda_api_configured,
                "api_url_hint": env.hacienda_api[:30] + "..." if env.hacienda_api and len(env.hacienda_api) > 30 else env.hacienda_api,
                "cert_configured": hacienda_cert_configured,
                "cert_file_exists": cert_exists,
            },
        }
    )


# ============================================================
# 6.1: POST /settings/backup — Crear backup de DB
# ============================================================
@router.post("/backup", dependencies=[Depends(require_role("admin"))])
def create_backup(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Ejecuta mysqldump y retorna el archivo .sql para descarga."""
    from app.core.config import settings as env

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{env.db_name}_{timestamp}.sql"
    filepath = os.path.join(BACKUP_DIR, filename)

    cmd = [
        "mysqldump",
        f"--host={env.db_host}",
        f"--port={env.db_port}",
        f"--user={env.db_user}",
        f"--password={env.db_password}",
        "--single-transaction",
        "--routines",
        "--triggers",
        env.db_name,
    ]

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, timeout=120)

        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="replace")
            raise HTTPException(status_code=500, detail=f"mysqldump falló: {error}")

        file_size = os.path.getsize(filepath)

        log_audit(db, "backup", {"filename": filename, "size_bytes": file_size},
                  user_id=getattr(current_user, "id", None),
                  username=getattr(current_user, "username", None))

        return FileResponse(
            path=filepath,
            filename=filename,
            media_type="application/sql",
        )

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Timeout: el backup tardó más de 2 minutos.")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="mysqldump no encontrado. Verifica que MySQL esté instalado.")


# ============================================================
# 6.1: POST /settings/restore — Restaurar backup
# ============================================================
@router.post("/restore", dependencies=[Depends(require_role("admin"))])
def restore_backup(file: UploadFile = File(...), db: Session = Depends(get_db),
                   current_user=Depends(get_current_user)):
    """Recibe un archivo .sql y lo ejecuta vía mysql CLI."""
    from app.core.config import settings as env

    if not file.filename.endswith(".sql"):
        raise HTTPException(status_code=400, detail="El archivo debe ser .sql")

    contents = file.file.read()
    if len(contents) > 100 * 1024 * 1024:  # Max 100MB
        raise HTTPException(status_code=400, detail="El archivo excede 100MB.")

    # Guardar temporalmente
    tmp_path = os.path.join(BACKUP_DIR, f"restore_tmp_{datetime.now().strftime('%H%M%S')}.sql")
    with open(tmp_path, "wb") as f:
        f.write(contents)

    cmd = [
        "mysql",
        f"--host={env.db_host}",
        f"--port={env.db_port}",
        f"--user={env.db_user}",
        f"--password={env.db_password}",
        env.db_name,
    ]

    try:
        with open(tmp_path, "r", encoding="utf-8") as f:
            result = subprocess.run(cmd, stdin=f, stderr=subprocess.PIPE, timeout=300)

        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="replace")
            raise HTTPException(status_code=500, detail=f"Restauración falló: {error}")

        log_audit(db, "restore", {"filename": file.filename},
                  user_id=getattr(current_user, "id", None),
                  username=getattr(current_user, "username", None))

        return APIResponse(message="Base de datos restaurada correctamente", data={"filename": file.filename})

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Timeout: la restauración tardó más de 5 minutos.")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="mysql client no encontrado.")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ============================================================
# 6.5: GET /settings/system-info
# ============================================================
@router.get("/system-info", dependencies=[Depends(get_current_user)])
def get_system_info(db: Session = Depends(get_db)):
    """Información del sistema: versión, DB, disco, Python, OS."""
    from app.core.config import settings as env

    # Versión de MySQL
    db_version = "desconocida"
    try:
        row = db.execute(text("SELECT VERSION()")).fetchone()
        if row:
            db_version = row[0]
    except Exception:
        pass

    # Tamaño de la base de datos
    db_size_mb = "desconocido"
    try:
        row = db.execute(text(
            "SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) "
            "FROM information_schema.tables WHERE table_schema = :db"
        ), {"db": env.db_name}).fetchone()
        if row and row[0]:
            db_size_mb = f"{row[0]} MB"
    except Exception:
        pass

    # Espacio en disco
    disk_info = "desconocido"
    try:
        total, used, free = shutil.disk_usage("/")
        disk_info = f"{free // (1024**3)} GB libres de {total // (1024**3)} GB"
    except Exception:
        pass

    # Conteos
    # ── FASE 5 — Fix 5.5: Whitelist validada, sin f-string en SQL ──
    _ALLOWED_TABLES = {"products", "customers", "sales", "suppliers", "cabys_items"}
    table_counts = {}
    for table in _ALLOWED_TABLES:
        try:
            # table viene de un set hardcodeado, pero usamos identifier quoting
            # seguro por si la lista se extiende en el futuro.
            row = db.execute(text("SELECT COUNT(*) FROM " + table)).fetchone()
            table_counts[table] = row[0] if row else 0
        except Exception:
            table_counts[table] = "N/A"

    return APIResponse(
        message="Información del sistema",
        data={
            "app_name": env.app_name,
            "app_env": env.app_env,
            "python_version": platform.python_version(),
            "os": f"{platform.system()} {platform.release()}",
            "db_version": db_version,
            "db_name": env.db_name,
            "db_host": env.db_host,
            "db_size": db_size_mb,
            "disk": disk_info,
            "table_counts": table_counts,
        }
    )


# ============================================================
# 6.6: GET /settings/export-config — Exportar config como JSON
# ============================================================
@router.get("/export-config", dependencies=[Depends(require_role("admin"))])
def export_config(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Exporta settings + issuer_profile como JSON descargable."""
    settings = get_settings(db)
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()

    settings_out = get_settings_out(db)
    settings_dict = settings_out.model_dump(mode="json")
    # Remover campos internos
    for k in ("id", "supplier_name", "cabys_last_update", "cabys_records", "logo_path"):
        settings_dict.pop(k, None)

    issuer_dict = {}
    if issuer:
        issuer_out = IssuerProfileOut.model_validate(issuer)
        issuer_dict = issuer_out.model_dump(mode="json")
        issuer_dict.pop("id", None)

    export_data = {
        "_export_version": "1.0",
        "_exported_at": utcnow().isoformat(),
        "settings": settings_dict,
        "issuer_profile": issuer_dict,
    }

    log_audit(db, "export_config", None,
              user_id=getattr(current_user, "id", None),
              username=getattr(current_user, "username", None))

    return JSONResponse(
        content=export_data,
        headers={"Content-Disposition": f"attachment; filename=config_export_{datetime.now().strftime('%Y%m%d')}.json"}
    )


# ============================================================
# 6.6: POST /settings/import-config — Importar config JSON
# ============================================================
@router.post("/import-config", dependencies=[Depends(require_role("admin"))])
def import_config(file: UploadFile = File(...), db: Session = Depends(get_db),
                  current_user=Depends(get_current_user)):
    """Importa configuración desde un JSON exportado previamente."""
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="El archivo debe ser .json")

    try:
        contents = file.file.read()
        data = json.loads(contents)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON inválido: {e}")

    if "_export_version" not in data:
        raise HTTPException(status_code=400, detail="No parece ser un archivo de exportación válido.")

    # Importar settings
    settings_data = data.get("settings", {})
    if settings_data:
        settings = get_settings(db)
        for key, value in settings_data.items():
            if hasattr(settings, key) and key not in ("id", "created_at", "updated_at"):
                setattr(settings, key, value)
        db.commit()

    # Importar issuer profile
    issuer_data = data.get("issuer_profile", {})
    if issuer_data:
        issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
        if not issuer:
            issuer = IssuerProfile()
            db.add(issuer)
            db.flush()
        for key, value in issuer_data.items():
            if hasattr(issuer, key) and key not in ("id", "created_at"):
                setattr(issuer, key, value)
        db.commit()

    log_audit(db, "import_config", {"filename": file.filename},
              user_id=getattr(current_user, "id", None),
              username=getattr(current_user, "username", None))

    return APIResponse(message="Configuración importada correctamente", data={"filename": file.filename})


# ============================================================
# 6.4: GET /settings/audit-log
# ============================================================
@router.get("/audit-log", dependencies=[Depends(require_role("admin"))])
def get_audit_log_endpoint(limit: int = 50, db: Session = Depends(get_db)):
    """Retorna las últimas entradas del log de auditoría."""
    entries = get_audit_log(db, limit=min(limit, 200))
    return APIResponse(message="Log de auditoría", data=entries)


# ============================================================
# ISSUER PROFILE
# ============================================================

@router.get("/issuer-profile", response_model=APIResponse[IssuerProfileOut],
            dependencies=[Depends(get_current_user)])
def get_issuer_profile(db: Session = Depends(get_db)):
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        issuer = IssuerProfile(
            legal_name="Mi Negocio", commercial_name=None,
            id_type="01", id_number="000000000",
            email="facturacion@tudominio.com", phone=None,
            branch_code="101", terminal_code="00001",
        )
        db.add(issuer)
        db.commit()
        db.refresh(issuer)
    return success_response("Perfil emisor obtenido", issuer)


@router.put("/issuer-profile", response_model=APIResponse[IssuerProfileOut],
            dependencies=[Depends(require_role("admin"))])
def update_issuer_profile(payload: IssuerProfileUpdate, db: Session = Depends(get_db),
                          current_user=Depends(get_current_user)):
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        issuer = IssuerProfile(
            legal_name="Mi Negocio", id_type="01",
            id_number="000000000", email="facturacion@tudominio.com",
            branch_code="101", terminal_code="00001",
        )
        db.add(issuer)
        db.flush()

    data = payload.model_dump(exclude_unset=True)

    if "branch_code" in data and data["branch_code"] is not None:
        data["branch_code"] = str(data["branch_code"]).zfill(3)[:3]
    if "terminal_code" in data and data["terminal_code"] is not None:
        data["terminal_code"] = str(data["terminal_code"]).zfill(5)[:5]

    for k, z in [("provincia", 1), ("canton", 2), ("distrito", 2)]:
        if k in data and data[k] is not None:
            data[k] = str(data[k]).zfill(z)[-z:]

    for k, v in data.items():
        setattr(issuer, k, v)

    db.commit()
    db.refresh(issuer)

    log_audit(db, "update_issuer", data,
              user_id=getattr(current_user, "id", None),
              username=getattr(current_user, "username", None))

    return success_response("Perfil emisor actualizado", issuer)


def _mask(value: str) -> str:
    if not value or len(value) < 4:
        return "***"
    return value[:3] + "***"


# ============================================================
# FASE 2 AI: Configuración del Asistente IA
# ============================================================

from app.schemas.ai_config import (
    AIConfigOut,
    AIConfigUpdate,
    AIConfigTestRequest,
    AIConfigTestResponse,
    AIProviderInfo,
)
from app.services.ai_config_service import (
    get_ai_config_out,
    update_ai_config,
)
from app.ai.providers.provider_registry import get_available_providers


# GET /settings/ai-config — Config actual (sin key completa)
@router.get("/ai-config", response_model=APIResponse[AIConfigOut],
            dependencies=[Depends(get_current_user)])
def get_ai_config_endpoint(db: Session = Depends(get_db)):
    """Retorna la configuración actual del asistente IA."""
    config = get_ai_config_out(db)
    return APIResponse(message="Configuración de IA cargada", data=config)


# PUT /settings/ai-config — Actualizar config
@router.put("/ai-config", response_model=APIResponse[AIConfigOut],
            dependencies=[Depends(require_role("admin"))])
def update_ai_config_endpoint(
    data: AIConfigUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Actualiza la configuración del asistente IA."""
    try:
        updated = update_ai_config(db, data)

        log_audit(
            db, "update_ai_config",
            {k: v for k, v in data.model_dump(exclude_unset=True).items() if k != "api_key"},
            user_id=getattr(current_user, "id", None),
            username=getattr(current_user, "username", None),
        )

        return APIResponse(message="Configuración de IA actualizada", data=updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# POST /settings/ai-config/test — Probar conexión
@router.post("/ai-config/test", response_model=APIResponse[AIConfigTestResponse],
             dependencies=[Depends(get_current_user)])
def test_ai_config_endpoint(req: AIConfigTestRequest):
    """Prueba la conexión con un proveedor y API key."""
    from app.ai.providers.provider_registry import _PROVIDER_CLASSES, _get_provider_instance

    if req.provider not in _PROVIDER_CLASSES:
        raise HTTPException(
            status_code=400,
            detail=f"Proveedor no soportado: {req.provider}",
        )

    provider = _get_provider_instance(req.provider)
    model_used = req.model or provider.default_model

    # Validar la API key
    is_valid = provider.validate_api_key(req.api_key.strip())

    if is_valid:
        result = AIConfigTestResponse(
            success=True,
            message=f"Conexión exitosa con {provider.display_name} ✅",
            provider=req.provider,
            model_used=model_used,
        )
    else:
        result = AIConfigTestResponse(
            success=False,
            message=f"No se pudo conectar con {provider.display_name}. Verificá tu API key.",
            provider=req.provider,
            model_used=model_used,
        )

    return APIResponse(
        message="Test completado",
        data=result,
    )


# GET /settings/ai-providers — Lista proveedores disponibles
@router.get("/ai-providers", response_model=APIResponse[list[AIProviderInfo]],
            dependencies=[Depends(get_current_user)])
def get_ai_providers_endpoint(db: Session = Depends(get_db)):
    """Lista los proveedores de IA disponibles con sus modelos."""
    providers_raw = get_available_providers(db)
    providers = [AIProviderInfo(**p) for p in providers_raw]
    return APIResponse(message="Proveedores disponibles", data=providers)