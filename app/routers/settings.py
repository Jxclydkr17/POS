"""
app/routers/settings.py — Fase 6 completa.

6.1  Backup y restauración de DB (mysqldump)
6.4  Endpoint audit-log
6.5  Endpoint system-info
6.6  Export/import config JSON

FASE 2 — Seguridad:
  2.1  Credenciales MySQL vía --defaults-extra-file (no visibles en ps aux)
  2.2  Validación de contenido SQL en restore
  2.3  Archivo temporal con tempfile seguro
  2.5  Extensión de logo validada contra whitelist
"""

import os
import re
import json
import shutil
import logging
import platform
import tempfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.database import get_db
from app.db.models.issuer_profile import IssuerProfile
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.schemas.api_response import APIResponse
from app.schemas.issuer_profile import IssuerProfileOut, IssuerProfileUpdate
from app.core.dependencies import get_current_user, require_role
from app.utils.cabys_updater import update_cabys
from app.utils.responses import success_response
from app.utils.dt import utcnow, now_cr

from app.services.settings_service import (
    get_settings,
    get_settings_out,
    update_settings as svc_update_settings,
    log_audit,
    get_audit_log,
)
from app.core.config import is_sqlite, DATA_DIR  # FASE 2 — Fix 2.2: DATA_DIR persiste updates
from app.services import backup_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/settings",
    tags=["Configuración"]
)

# ── FASE 2 — Fix 2.2: directorios persistentes en DATA_DIR ──
# Antes vivían en app/uploads/logos (→ _internal/ en .exe), que se
# borra cada update del installer. DATA_DIR/uploads/logos persiste.
LOGO_DIR = DATA_DIR / "uploads" / "logos"
os.makedirs(LOGO_DIR, exist_ok=True)

# ── FASE 2 — Fix 2.2: Eliminado BACKUP_DIR muerto. El real está en
# app/services/backup_service.py (BACKUP_DIR = DATA_DIR / "backups").
# El de acá nunca se usaba pero creaba un directorio huérfano por carga.

# ── FASE 2 — Fix 2.5: Extensiones permitidas para logo ──
_ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


# ══════════════════════════════════════════════════════════════
# FASE 2 — Fix 2.2: Validación de contenido SQL en restore
# ══════════════════════════════════════════════════════════════
_DANGEROUS_SQL_PATTERNS = re.compile(
    r"""
    \b(DROP\s+DATABASE)\b         |
    \b(CREATE\s+USER)\b           |
    \b(GRANT\s+)\b                |
    \b(REVOKE\s+)\b               |
    \b(LOAD_FILE\s*\()\b          |
    \b(INTO\s+OUTFILE)\b          |
    \b(INTO\s+DUMPFILE)\b         |
    \b(SYSTEM\s+)\b               |
    \b(CHANGE\s+MASTER)\b         |
    \b(RESET\s+SLAVE)\b           |
    \b(SET\s+GLOBAL)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _validate_sql_content(content: bytes) -> None:
    """
    Valida que el contenido SQL no contenga sentencias peligrosas.
    Solo permite DDL/DML normales de un dump (CREATE TABLE, INSERT, etc.)
    Lanza HTTPException si encuentra algo sospechoso.
    """
    # Decodificar para escaneo (solo los primeros 5MB para no bloquear)
    sample = content[:5 * 1024 * 1024].decode("utf-8", errors="replace")
    match = _DANGEROUS_SQL_PATTERNS.search(sample)
    if match:
        found = match.group(0).strip()
        raise HTTPException(
            status_code=400,
            detail=(
                f"El archivo SQL contiene sentencias no permitidas: '{found}'. "
                f"Solo se aceptan backups generados por mysqldump con instrucciones "
                f"CREATE TABLE, INSERT, ALTER, DROP TABLE, etc."
            ),
        )


# ============================================================
# GET /settings
# ============================================================
@router.get("/", response_model=APIResponse[SettingsOut], dependencies=[Depends(get_current_user)])
def get_settings_endpoint(db: Session = Depends(get_db)):
    result = get_settings_out(db)
    db.commit()
    return APIResponse(message="Configuración cargada correctamente", data=result)


# ============================================================
# PUT /settings
# ============================================================
@router.put("/", response_model=APIResponse[SettingsOut], dependencies=[Depends(require_role("admin"))])
def update_settings_endpoint(data: SettingsUpdate, db: Session = Depends(get_db),
                              current_user=Depends(get_current_user)):
    user_id = getattr(current_user, "id", None)
    username = getattr(current_user, "username", None)
    updated = svc_update_settings(db, data, user_id=user_id, username=username)
    db.commit()
    return APIResponse(message="Configuración actualizada correctamente", data=updated)


# ============================================================
# POST /settings/upload-logo
# ── FASE 2 — Fix 2.5: Extensión validada contra whitelist ──
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

    # ── FASE 2: Validar extensión contra whitelist en vez de confiar en el filename ──
    ext = os.path.splitext(file.filename or "logo.png")[1].lower()
    if ext not in _ALLOWED_LOGO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Extensión no permitida: '{ext}'. Use: {', '.join(_ALLOWED_LOGO_EXTENSIONS)}",
        )

    filename = f"logo{ext}"
    filepath = os.path.join(LOGO_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    settings = get_settings(db)
    settings.logo_path = filepath
    # FASE 4 — Fix 4.1: try/except + rollback
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    log_audit(db, "upload_logo", {"filename": filename},
              user_id=getattr(current_user, "id", None),
              username=getattr(current_user, "username", None))
    db.commit()

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
        db.commit()

        return APIResponse(message="CABYS actualizado correctamente", data={"registros": total})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar CABYS: {e}")


# ============================================================
# GET /settings/env-status
# ============================================================
@router.get("/env-status", dependencies=[Depends(get_current_user)])
def get_env_status(db: Session = Depends(get_db)):
    # Las credenciales pueden estar guardadas en la base de datos (subidas
    # desde la interfaz, vía secure_config) o en el .env (método antiguo).
    # get_secure consulta AMBOS —DB primero, .env como respaldo— de modo que
    # este indicador refleje el estado REAL. Antes leía solo el .env y por eso
    # mostraba "Certificado NO configurado en .env" pese a que el .p12 estaba
    # correctamente cargado en la base de datos.
    from app.services.secure_config_service import get_secure as _get_secure

    email_user = _get_secure(db, "email_user")
    email_pass = _get_secure(db, "email_pass")
    hacienda_api = _get_secure(db, "hacienda_api")
    hacienda_cert_path = _get_secure(db, "hacienda_cert_path")
    hacienda_cert_pass = _get_secure(db, "hacienda_cert_pass")

    email_configured = bool(email_user and email_pass)
    hacienda_api_configured = bool(hacienda_api)
    hacienda_cert_configured = bool(hacienda_cert_path and hacienda_cert_pass)

    cert_exists = bool(hacienda_cert_path) and os.path.isfile(hacienda_cert_path)

    return APIResponse(
        message="Estado de configuración",
        data={
            "email": {
                "configured": email_configured,
                "user_hint": _mask(email_user) if email_user else None,
            },
            "hacienda": {
                "api_configured": hacienda_api_configured,
                "api_url_hint": (hacienda_api[:30] + "...") if hacienda_api and len(hacienda_api) > 30 else hacienda_api,
                "cert_configured": hacienda_cert_configured,
                "cert_file_exists": cert_exists,
            },
        }
    )


# ============================================================
# 6.1: POST /settings/backup — Crear backup de DB
# ── FASE 3 — Fix 3.4: Soporta MySQL y SQLite vía backup_service ──
# ============================================================
@router.post("/backup", dependencies=[Depends(require_role("admin"))])
def create_backup(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Crea un backup de la BD (MySQL o SQLite) y lo retorna para descarga."""
    try:
        filepath = backup_service.create_backup(tag="manual")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    filename = os.path.basename(filepath)
    file_size = os.path.getsize(filepath)

    log_audit(db, "backup", {"filename": filename, "size_bytes": file_size},
              user_id=getattr(current_user, "id", None),
              username=getattr(current_user, "username", None))
    db.commit()

    media = "application/x-sqlite3" if filepath.endswith(".db") else "application/sql"
    return FileResponse(path=filepath, filename=filename, media_type=media)


# ============================================================
# 6.1: POST /settings/restore — Restaurar backup
# ── FASE 3 — Fix 3.4: Soporta MySQL (.sql) y SQLite (.db) ──
# ── FASE 2 — Fixes 2.1, 2.2, 2.3 se mantienen para MySQL ──
# ============================================================
@router.post("/restore", dependencies=[Depends(require_role("admin"))])
def restore_backup(file: UploadFile = File(...), db: Session = Depends(get_db),
                   current_user=Depends(get_current_user)):
    """Restaura la BD desde un archivo .sql (MySQL) o .db (SQLite)."""

    fname = file.filename or ""
    is_sql = fname.endswith(".sql")
    is_db = fname.endswith(".db")

    if is_sqlite():
        if not is_db:
            raise HTTPException(status_code=400,
                                detail="Para SQLite el archivo debe ser .db")
    else:
        if not is_sql:
            raise HTTPException(status_code=400,
                                detail="Para MySQL el archivo debe ser .sql")

    contents = file.file.read()
    if len(contents) > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="El archivo excede 100MB.")

    # Validación SQL solo para MySQL
    if is_sql:
        _validate_sql_content(contents)

    # Guardar en temporal seguro
    suffix = ".db" if is_db else ".sql"
    fd, tmp_path = tempfile.mkstemp(prefix="vp_restore_", suffix=suffix)
    try:
        os.write(fd, contents)
        os.close(fd)

        try:
            backup_service.restore_backup(tmp_path)
        except (RuntimeError, FileNotFoundError) as e:
            raise HTTPException(status_code=500, detail=str(e))

        log_audit(db, "restore", {"filename": fname},
                  user_id=getattr(current_user, "id", None),
                  username=getattr(current_user, "username", None))
        db.commit()

        return APIResponse(message="Base de datos restaurada correctamente",
                           data={"filename": fname})
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ============================================================
# 6.5: GET /settings/system-info
# ============================================================
@router.get("/system-info", dependencies=[Depends(get_current_user)])
def get_system_info(db: Session = Depends(get_db)):
    """Información del sistema: versión, DB, disco, Python, OS."""
    from app.core.config import settings as env, APP_DIR

    # ── Versión del motor de BD ──
    db_version = "desconocida"
    try:
        if is_sqlite():
            row = db.execute(text("SELECT sqlite_version()")).fetchone()
            if row:
                db_version = f"SQLite {row[0]}"
        else:
            row = db.execute(text("SELECT VERSION()")).fetchone()
            if row:
                db_version = row[0]
    except Exception:
        pass

    # ── Tamaño de la base de datos ──
    db_size_mb = "desconocido"
    try:
        if is_sqlite():
            db_path = APP_DIR / env.db_sqlite_path
            if db_path.exists():
                size_bytes = os.path.getsize(db_path)
                db_size_mb = f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
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
    _ALLOWED_TABLES = {"products", "customers", "sales", "suppliers", "cabys"}
    table_counts = {}
    for table in _ALLOWED_TABLES:
        try:
            # table viene de un set hardcodeado, pero usamos identifier quoting
            # seguro por si la lista se extiende en el futuro.
            row = db.execute(text("SELECT COUNT(*) FROM " + table)).fetchone()
            table_counts[table] = row[0] if row else 0
        except Exception:
            table_counts[table] = "N/A"

    # ── Nombre y host adaptados al motor ──
    db_display_name = env.db_sqlite_path if is_sqlite() else env.db_name
    db_display_host = "local (archivo)" if is_sqlite() else env.db_host

    return APIResponse(
        message="Información del sistema",
        data={
            "app_name": env.app_name,
            "app_env": env.app_env,
            "python_version": platform.python_version(),
            "os": f"{platform.system()} {platform.release()}",
            "db_version": db_version,
            "db_name": db_display_name,
            "db_host": db_display_host,
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
    db.commit()

    return JSONResponse(
        content=export_data,
        headers={"Content-Disposition": f"attachment; filename=config_export_{now_cr().strftime('%Y%m%d')}.json"}
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

    # FASE 4 — Fix 4.1: Un solo commit atómico para settings + issuer
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    log_audit(db, "import_config", {"filename": file.filename},
              user_id=getattr(current_user, "id", None),
              username=getattr(current_user, "username", None))
    db.commit()

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
        # FASE 4 — Fix 4.1: try/except + rollback
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(issuer)
    return success_response("Perfil emisor obtenido", issuer)


# ──────────────────────────────────────────────────────────
# FASE 2.4 — Fix 2.4: Status del perfil emisor (gate de UI)
# ──────────────────────────────────────────────────────────
@router.get("/issuer-profile/status",
            dependencies=[Depends(get_current_user)])
def get_issuer_profile_status(db: Session = Depends(get_db)):
    """
    Indica si el perfil del emisor está configurado con datos reales.

    Lo consulta el UI antes de abrir la vista de Ventas: si el perfil
    está sin configurar (placeholder), muestra un modal bloqueante
    para forzar al dueño a completar los datos antes de la primera venta.

    Response:
        {
          "data": {
            "is_configured": bool,
            "missing_fields": [str, ...],
            "blocking_reason": str | null,
          },
          ...
        }

    `is_configured = false` indica que el emisor:
      - no existe, o
      - tiene id_number = "000000000" (placeholder), o
      - tiene legal_name aún por configurar.
    """
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()

    _DUMMY_ID = "000000000"
    _DUMMY_LEGAL_PREFIX = "NOMBRE LEGAL POR CONFIGURAR"

    missing = []
    reason = None

    if not issuer:
        missing = ["legal_name", "id_type", "id_number", "email", "branch_code", "terminal_code"]
        reason = "No hay perfil de emisor configurado."
        return success_response(
            "Estado del perfil emisor",
            {
                "is_configured": False,
                "missing_fields": missing,
                "blocking_reason": reason,
            },
        )

    if issuer.id_number == _DUMMY_ID:
        missing.append("id_number")
        reason = "El perfil tiene cédula genérica '000000000'."

    if issuer.legal_name and issuer.legal_name.upper().startswith(_DUMMY_LEGAL_PREFIX):
        missing.append("legal_name")
        if reason is None:
            reason = "La razón social está en estado 'por configurar'."

    # Otros campos críticos vacíos (defensivo, aunque seed los llena)
    for field in ("email", "branch_code", "terminal_code"):
        if not getattr(issuer, field, None):
            missing.append(field)

    is_configured = len(missing) == 0
    if not is_configured and reason is None:
        reason = "Faltan campos críticos: " + ", ".join(missing)

    return success_response(
        "Estado del perfil emisor",
        {
            "is_configured": is_configured,
            "missing_fields": missing,
            "blocking_reason": reason,
        },
    )


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

    # FASE 4 — Fix 4.1: try/except + rollback
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(issuer)

    log_audit(db, "update_issuer", data,
              user_id=getattr(current_user, "id", None),
              username=getattr(current_user, "username", None))
    db.commit()

    return success_response("Perfil emisor actualizado", issuer)


def _mask(value: str) -> str:
    if not value or len(value) < 4:
        return "***"
    return value[:3] + "***"


# ============================================================
# Fix 2.5 (cerrado): Endpoint de prueba de impresión ESC/POS.
# Útil para que el botón "Probar impresión" en Settings → Impresora
# valide IP/puerto/USB sin tener que armar una venta completa.
# ============================================================
@router.post("/printer-test", dependencies=[Depends(require_role("admin"))])
def printer_test_endpoint(db: Session = Depends(get_db),
                          current_user=Depends(get_current_user)):
    """
    Imprime una página de prueba ESC/POS a la impresora configurada.

    Lee la config de Settings (printer_type / IP / USB IDs / perfil /
    ancho de papel) y manda un ticket corto. Si el printer_type es
    "none", informa que está deshabilitado en lugar de fallar.
    """
    try:
        from app.utils.print_ticket import print_test_page
        from app.services.settings_service import get_settings

        settings = get_settings(db)
        if not settings:
            raise HTTPException(status_code=400, detail="No hay configuración cargada.")

        printer_type = (settings.printer_type or "none").lower()
        if printer_type == "none":
            return success_response(
                message="Impresora deshabilitada (printer_type=none)",
                data={"printed": False}
            )

        def _parse_usb_id(v):
            if not v:
                return None
            s = str(v).strip().lower()
            if s.startswith("0x"):
                s = s[2:]
            try:
                return int(s, 16)
            except ValueError:
                return None

        kwargs = dict(
            thermal_kind=printer_type,
            paper_width_mm=getattr(settings, "printer_paper_width_mm", None) or 80,
            profile=getattr(settings, "printer_profile", None),
        )
        if printer_type == "system":
            kwargs["thermal_system_name"] = getattr(settings, "printer_system_name", None)
        elif printer_type == "network":
            kwargs["thermal_ip"] = settings.printer_ip
            kwargs["thermal_port"] = settings.printer_port
        elif printer_type == "usb":
            kwargs["thermal_usb_vendor_id"] = _parse_usb_id(
                getattr(settings, "printer_usb_vendor_id", None)
            )
            kwargs["thermal_usb_product_id"] = _parse_usb_id(
                getattr(settings, "printer_usb_product_id", None)
            )

        print_test_page(**kwargs)

        return success_response(
            message="Página de prueba enviada a la impresora",
            data={"printed": True, "mode": printer_type}
        )
    except ValueError as e:
        # Falta config (IP no seteada, USB IDs vacíos).
        raise HTTPException(status_code=400, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except RuntimeError as e:
        logger.error(f"Error en página de prueba: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error inesperado en printer-test")
        raise HTTPException(status_code=500, detail=f"Error interno: {e}")


# ============================================================
# Autodetección de impresoras (modo "system" + USB).
# Pobla el desplegable de Settings → Impresora para que el usuario
# elija su impresora sin escribir Vendor/Product ID a mano.
# ============================================================
@router.get("/printer-discovery", dependencies=[Depends(require_role("admin"))])
def printer_discovery_endpoint():
    """
    Detecta impresoras disponibles en la máquina donde corre la app.

    Devuelve dos listas:
      - "system": impresoras instaladas en el SO (Windows: win32print),
        por NOMBRE. Se imprimen en RAW por el spooler (modo "system").
      - "usb":    dispositivos USB crudos (pyusb) con vendor/product ID
        ya formateados, para el modo "usb" directo.

    Además informa qué backends están disponibles y notas guía. La
    detección nunca levanta: si algo falla, devuelve listas vacías y
    una nota legible (la UI las muestra al usuario).
    """
    try:
        from app.utils.printer_discovery import discover_printers
        result = discover_printers()
        return success_response(
            message="Impresoras detectadas",
            data=result,
        )
    except Exception as e:
        # discover_printers ya es defensivo, pero por si la importación
        # u otra cosa rompe, no tumbamos el endpoint.
        logger.exception("Error inesperado en printer-discovery")
        return success_response(
            message="No se pudo completar la detección de impresoras",
            data={
                "platform": None,
                "backends": {"win32print": False, "pyusb": False},
                "system": [],
                "usb": [],
                "notes": [f"Error de detección: {e}"],
            },
        )


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
    db.commit()
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
        db.commit()

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

# ============================================================
# FASE CONFIG-UI: Hacienda y Email desde la UI
# ============================================================

from app.schemas.secure_config import (
    HaciendaConfigOut, HaciendaConfigUpdate,
    EmailConfigOut, EmailConfigUpdate,
)
from app.services.secure_config_service import get_secure, set_secure


# ── FASE 2 — Fix 2.2: cert persistente en DATA_DIR ──
# CRÍTICO: el certificado .p12 de Hacienda no debe perderse al actualizar.
# Antes: app/certs (→ _internal/app/certs en .exe, borrado en cada update).
CERT_DIR = DATA_DIR / "certs"
os.makedirs(CERT_DIR, exist_ok=True)


# ── GET /settings/hacienda-config ──
@router.get("/hacienda-config", response_model=APIResponse[HaciendaConfigOut],
            dependencies=[Depends(require_role("admin"))])
def get_hacienda_config(db: Session = Depends(get_db)):
    """Retorna config de Hacienda (valores enmascarados)."""
    h_env = get_secure(db, "hacienda_env") or "sandbox"
    h_api = get_secure(db, "hacienda_api") or ""
    h_user = get_secure(db, "hacienda_user") or ""
    h_pass = get_secure(db, "hacienda_password") or ""
    h_cert_path = get_secure(db, "hacienda_cert_path") or ""
    h_cert_pass = get_secure(db, "hacienda_cert_pass") or ""

    cert_exists = bool(h_cert_path) and os.path.isfile(h_cert_path)
    cert_filename = os.path.basename(h_cert_path) if h_cert_path else ""

    out = HaciendaConfigOut(
        hacienda_env=h_env,
        hacienda_api=h_api,
        hacienda_user_hint=_mask(h_user) if h_user else "",
        has_hacienda_user=bool(h_user),
        has_hacienda_password=bool(h_pass),
        hacienda_cert_filename=cert_filename,
        has_cert=bool(h_cert_path and h_cert_pass),
        cert_file_exists=cert_exists,
    )
    return APIResponse(message="Configuración de Hacienda", data=out)


# ── PUT /settings/hacienda-config ──
@router.put("/hacienda-config", response_model=APIResponse[HaciendaConfigOut],
            dependencies=[Depends(require_role("admin"))])
def update_hacienda_config(
    data: HaciendaConfigUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Actualiza credenciales de Hacienda (se guardan encriptadas)."""
    updates = data.model_dump(exclude_unset=True)

    if "hacienda_env" in updates:
        val = (updates["hacienda_env"] or "sandbox").lower().strip()
        if val not in ("sandbox", "production"):
            raise HTTPException(status_code=400, detail="hacienda_env debe ser 'sandbox' o 'production'")
        set_secure(db, "hacienda_env", val)

    if "hacienda_api" in updates:
        set_secure(db, "hacienda_api", (updates["hacienda_api"] or "").strip())

    if "hacienda_user" in updates:
        set_secure(db, "hacienda_user", (updates["hacienda_user"] or "").strip())

    if "hacienda_password" in updates:
        set_secure(db, "hacienda_password", updates["hacienda_password"] or "")

    log_audit(db, "update_hacienda_config",
              {k: "***" if "pass" in k.lower() else v for k, v in updates.items()},
              user_id=getattr(current_user, "id", None),
              username=getattr(current_user, "username", None))
    db.commit()

    # Retornar estado actualizado
    return get_hacienda_config(db=db)


# ── POST /settings/hacienda-cert — Upload certificado .p12 ──
@router.post("/hacienda-cert", dependencies=[Depends(require_role("admin"))])
def upload_hacienda_cert(
    file: UploadFile = File(...),
    # CRÍTICO: debe ser Form(...) — si se declara como `str = ""` sin Form,
    # FastAPI lo trata como query param y NUNCA lee la contraseña que la UI
    # envía en el multipart/form-data. Eso dejaba `hacienda_cert_pass` vacío
    # y el certificado quedaba en estado "pendiente" pese al 200 OK.
    cert_password: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Sube el certificado .p12 de firma digital."""
    fname = file.filename or ""
    if not fname.lower().endswith(".p12"):
        raise HTTPException(status_code=400, detail="El archivo debe ser .p12")

    # La contraseña es obligatoria: un .p12 de Hacienda siempre tiene PIN y,
    # sin él, el firmador XAdES no puede cargar la llave privada (el cert
    # quedaría inutilizable y en estado "pendiente").
    if not cert_password:
        raise HTTPException(
            status_code=400,
            detail="Debés ingresar la contraseña del certificado .p12."
        )

    contents = file.file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="El certificado excede 5MB.")

    # Validar que el .p12 se puede abrir con la contraseña antes de guardarlo.
    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
        pkcs12.load_key_and_certificates(
            contents, cert_password.encode("utf-8")
        )
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="No se pudo abrir el .p12 con la contraseña proporcionada."
        )

    # Guardar archivo
    filepath = os.path.join(CERT_DIR, "firma.p12")
    with open(filepath, "wb") as f:
        f.write(contents)

    # Guardar path y password encriptados (ambos, siempre).
    set_secure(db, "hacienda_cert_path", filepath)
    set_secure(db, "hacienda_cert_pass", cert_password)

    log_audit(db, "upload_hacienda_cert", {"filename": fname},
              user_id=getattr(current_user, "id", None),
              username=getattr(current_user, "username", None))
    db.commit()

    return APIResponse(
        message="Certificado subido correctamente",
        data={"filename": fname, "path": filepath}
    )


# ── GET /settings/email-config ──
@router.get("/email-config", response_model=APIResponse[EmailConfigOut],
            dependencies=[Depends(require_role("admin"))])
def get_email_config(db: Session = Depends(get_db)):
    """Retorna config de email (valores enmascarados)."""
    e_user = get_secure(db, "email_user") or ""
    e_pass = get_secure(db, "email_pass") or ""

    out = EmailConfigOut(
        email_user_hint=_mask(e_user) if e_user else "",
        has_email_user=bool(e_user),
        has_email_pass=bool(e_pass),
    )
    return APIResponse(message="Configuración de email", data=out)


# ── PUT /settings/email-config ──
@router.put("/email-config", response_model=APIResponse[EmailConfigOut],
            dependencies=[Depends(require_role("admin"))])
def update_email_config(
    data: EmailConfigUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Actualiza credenciales de email (se guardan encriptadas)."""
    updates = data.model_dump(exclude_unset=True)

    if "email_user" in updates:
        set_secure(db, "email_user", (updates["email_user"] or "").strip())

    if "email_pass" in updates:
        set_secure(db, "email_pass", updates["email_pass"] or "")

    log_audit(db, "update_email_config",
              {k: "***" if "pass" in k.lower() else v for k, v in updates.items()},
              user_id=getattr(current_user, "id", None),
              username=getattr(current_user, "username", None))
    db.commit()

    return get_email_config(db=db)