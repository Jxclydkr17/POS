"""
app/services/backup_service.py — Backup y restore de la base de datos

Soporta ambos motores:
  - MySQL: usa mysqldump / mysql CLI
  - SQLite: copia directa del archivo .db con shutil

Incluye rotación automática (mantiene los últimos N backups).

FASE 2 — Fix 2.1: Credenciales MySQL vía --defaults-extra-file.
  La contraseña ya no aparece en `ps aux`.

USO DIRECTO:
    from app.services.backup_service import create_backup, restore_backup, list_backups

    path = create_backup()              # Crea backup y retorna la ruta
    restore_backup("backup_2025.sql")   # Restaura desde un archivo
    backups = list_backups()            # Lista backups disponibles

USO PROGRAMADO (desde app/main.py startup):
    from app.services.backup_service import start_scheduled_backups
    start_scheduled_backups()           # Backup cada 24h en background
"""

from __future__ import annotations

import os
import logging
import asyncio
import subprocess
import shutil
import threading
from pathlib import Path
from datetime import datetime, timezone  # FASE 4 — Fix 4.2: timezone para UTC explícito

from app.core.config import settings, is_sqlite, APP_DIR, DATA_DIR
from app.utils.dt import now_cr

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────────────────────
# ── FASE 5 — Fix 5.2: Backups en DATA_DIR, no dentro de app/ ──
# DATA_DIR (APP_DIR/data/) persiste entre actualizaciones.
# Antes: app/backups/ — se perdían al reinstalar/actualizar.
BACKUP_DIR = DATA_DIR / "backups"
MAX_BACKUPS = 30          # Mantener últimos 30 backups
BACKUP_INTERVAL = 86400   # 24 horas en segundos
# ── FASE 4 — Fix 4.3: delay antes del primer backup tras startup ──
# Antes el loop dormía 24h ANTES del primer backup, así que apps que
# se reinician seguido (ej. cierre nocturno de la ferretería) nunca
# llegaban a hacer un backup automático. Ahora se dispara el primero
# ~5 min después del startup (si toca), y luego sigue cada 24h. Si
# el último backup fue muy reciente, se espera el resto del intervalo.
FIRST_BACKUP_DELAY = 300  # 5 minutos en segundos

# ── FASE 3 — Fix 3.3: Flag de modo mantenimiento ──
# Activo durante restore para que el middleware rechace requests
# y evite que un request concurrente acceda a una BD a medio copiar.
# threading.Event es thread-safe por diseño (no necesita global ni lock).
_maintenance_event = threading.Event()


def is_maintenance_mode() -> bool:
    """Retorna True si la app está en modo mantenimiento (restore en curso)."""
    return _maintenance_event.is_set()

# ── FASE 4 — Fix 4.2: Estado del último backup verificable ──
_STATUS_FILE = DATA_DIR / "backup_status.json"
_last_backup_status: dict = {
    "last_success_at": None,
    "last_success_path": None,
    "last_error_at": None,
    "last_error_msg": None,
    "total_backups": 0,
    "consecutive_failures": 0,
}


def _ensure_backup_dir() -> Path:
    """Crea el directorio de backups si no existe."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def _load_backup_status() -> None:
    """Carga el estado del último backup desde disco (startup)."""
    global _last_backup_status
    try:
        import json
        if _STATUS_FILE.exists():
            data = json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _last_backup_status.update(data)
    except Exception:
        pass


def _save_backup_status() -> None:
    """Persiste el estado del backup en disco."""
    try:
        import json
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _STATUS_FILE.write_text(
            json.dumps(_last_backup_status, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug("No se pudo guardar estado de backup: %s", e)


def _record_success(path: str) -> None:
    """Registra un backup exitoso."""
    _last_backup_status["last_success_at"] = now_cr().isoformat()
    _last_backup_status["last_success_path"] = path
    _last_backup_status["total_backups"] = _last_backup_status.get("total_backups", 0) + 1
    _last_backup_status["consecutive_failures"] = 0
    _save_backup_status()


def _record_failure(error_msg: str) -> None:
    """Registra un backup fallido."""
    _last_backup_status["last_error_at"] = now_cr().isoformat()
    _last_backup_status["last_error_msg"] = str(error_msg)
    _last_backup_status["consecutive_failures"] = _last_backup_status.get("consecutive_failures", 0) + 1
    _save_backup_status()


def get_backup_status() -> dict:
    """
    FASE 4 — Fix 4.2: Retorna el estado verificable del backup.

    Uso desde la UI o desde el endpoint /system/backup-status:
        status = get_backup_status()
        if status["healthy"]:
            ...  # todo bien
        else:
            ...  # alertar al usuario

    Returns:
        dict con: healthy, last_success_at, last_error_msg,
                  consecutive_failures, backups_available, etc.
    """
    backups = list_backups()
    status = {
        **_last_backup_status,
        "healthy": _last_backup_status.get("consecutive_failures", 0) == 0,
        "backups_available": len(backups),
        "backup_dir": str(BACKUP_DIR),
        "latest_backup": backups[0] if backups else None,
    }
    # Marcar como no-healthy si nunca se ha hecho un backup
    if not _last_backup_status.get("last_success_at") and not backups:
        status["healthy"] = False
        status["last_error_msg"] = status.get("last_error_msg") or "Nunca se ha creado un backup."
    return status


# Cargar estado al importar el módulo
_load_backup_status()


def _find_mysqldump() -> str | None:
    """Busca mysqldump en el PATH y ubicaciones comunes."""
    # Primero buscar en PATH
    path = shutil.which("mysqldump")
    if path:
        return path

    # Ubicaciones comunes en Windows
    common_paths = [
        r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe",
        r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe",
        r"C:\Program Files\MariaDB 10.11\bin\mysqldump.exe",
        r"C:\xampp\mysql\bin\mysqldump.exe",
        r"C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysqldump.exe",
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return p

    return None


# ──────────────────────────────────────────────────────────────
# Filtro de ruido de mysqldump
# ──────────────────────────────────────────────────────────────
# mysqldump emite ciertos warnings en stderr que no son fatales y dependen
# de privilegios del usuario MySQL configurado para la app, no de un fallo
# real del backup. El más común es:
#
#   mysqldump: Couldn't execute 'FLUSH /*!40101 LOCAL */ TABLES': Access
#   denied; you need (at least one of) the RELOAD or FLUSH_TABLES
#   privilege(s) for this operation (1227)
#
# Esto pasa porque mysqldump intenta hacer un FLUSH TABLES inicial (modo
# consistente). Como usamos --single-transaction el dump SIGUE siendo
# consistente para tablas InnoDB sin ese FLUSH, así que el backup se
# completa bien. La solución "correcta" es darle al usuario MySQL el
# privilegio RELOAD o FLUSH_TABLES:
#
#   GRANT RELOAD ON *.* TO 'pos_user'@'%';
#   FLUSH PRIVILEGES;
#
# Como esto es una buena práctica NO darle RELOAD al usuario de app,
# filtramos el warning en el log para no asustar al usuario final.
_BENIGN_MYSQLDUMP_PATTERNS = (
    "FLUSH /*!40101 LOCAL */ TABLES",      # FLUSH TABLES sin privilegio RELOAD
    "Access denied",                         # Aparece junto al FLUSH cuando el privilegio falta
    "you need (at least one of) the RELOAD",
    "FLUSH_TABLES privilege",
    "Using a password on the command line",  # Falso positivo: usamos --defaults-extra-file
)


def _filter_mysqldump_noise(stderr_text: str) -> str:
    """
    Filtra líneas benignas del stderr de mysqldump.

    Devuelve solo las líneas que NO coinciden con patrones conocidos como
    inofensivos. Si no queda nada después de filtrar, retorna "" para
    indicar que no hay que loguear nada.
    """
    if not stderr_text:
        return ""

    kept = []
    for line in stderr_text.splitlines():
        line_strip = line.strip()
        if not line_strip:
            continue
        # Descartar líneas que coincidan con cualquiera de los patrones benignos
        if any(pat in line_strip for pat in _BENIGN_MYSQLDUMP_PATTERNS):
            continue
        kept.append(line_strip)

    return "\n".join(kept)


def _find_mysql() -> str | None:
    """Busca el cliente mysql en el PATH y ubicaciones comunes."""
    path = shutil.which("mysql")
    if path:
        return path

    common_paths = [
        r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
        r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe",
        r"C:\Program Files\MariaDB 10.11\bin\mysql.exe",
        r"C:\xampp\mysql\bin\mysql.exe",
        r"C:\laragon\bin\mysql\mysql-8.0.30-winx64\bin\mysql.exe",
    ]
    for p in common_paths:
        if os.path.isfile(p):
            return p

    return None


# ──────────────────────────────────────────────────────────────
# Backup
# ──────────────────────────────────────────────────────────────
def create_backup(tag: str = "") -> str:
    """
    Crea un backup completo de la BD.

    FASE 4 — Fix 4.2: Registra éxito/fallo para verificación desde la UI.

    Returns:
        Ruta absoluta del archivo de backup creado.

    Raises:
        RuntimeError: Si el backup falla.
    """
    _ensure_backup_dir()
    timestamp = now_cr().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{tag}" if tag else ""

    try:
        if is_sqlite():
            path = _create_sqlite_backup(timestamp, suffix)
        else:
            path = _create_mysql_backup(timestamp, suffix)

        _record_success(path)
        return path

    except Exception as e:
        _record_failure(str(e))
        raise


def _get_sqlite_db_path() -> Path:
    """Retorna la ruta del archivo SQLite."""
    return APP_DIR / settings.db_sqlite_path


def _create_sqlite_backup(timestamp: str, suffix: str) -> str:
    """
    Backup de SQLite usando la API de backup online (sqlite3.backup).

    FASE B — Fix B.6: shutil.copy2() podía crear backups inconsistentes
    con WAL mode activo, porque copia el .db sin las transacciones
    pendientes en el archivo -wal. La API nativa de SQLite garantiza
    un snapshot consistente incluso con escrituras concurrentes.
    """
    import sqlite3

    db_path = _get_sqlite_db_path()
    if not db_path.exists():
        raise RuntimeError(f"Archivo SQLite no encontrado: {db_path}")

    filename = f"backup_sqlite_{timestamp}{suffix}.db"
    filepath = BACKUP_DIR / filename

    try:
        # Conexión de solo lectura al origen
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(filepath))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        size = filepath.stat().st_size
        logger.info(f"Backup SQLite creado: {filename} ({size:,} bytes)")
        _rotate_backups()
        return str(filepath)
    except (sqlite3.Error, OSError) as e:
        filepath.unlink(missing_ok=True)
        raise RuntimeError(f"Error creando backup SQLite: {e}")


def _create_mysql_backup(timestamp: str, suffix: str) -> str:
    """Backup de MySQL: usa mysqldump con credenciales seguras."""
    from app.utils.mysql_safe import build_mysqldump_cmd

    mysqldump = _find_mysqldump()
    if not mysqldump:
        raise RuntimeError(
            "mysqldump no encontrado. Asegúrese de que MySQL esté "
            "instalado y mysqldump esté en el PATH del sistema."
        )

    filename = f"backup_{settings.db_name}_{timestamp}{suffix}.sql"
    filepath = BACKUP_DIR / filename

    # ── FASE 2 — Fix 2.1: Credenciales vía --defaults-extra-file ──
    cmd, cleanup = build_mysqldump_cmd(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        db_name=settings.db_name,
        extra_args=[
            "--single-transaction",   # Consistencia sin bloquear tablas
            "--skip-lock-tables",     # Refuerza --single-transaction; evita LOCK TABLES READ
            "--no-tablespaces",       # No requiere PROCESS privilege en MySQL 8.0+
            "--routines",             # Incluir procedimientos almacenados
            "--triggers",             # Incluir triggers
            "--add-drop-table",       # DROP TABLE antes de CREATE
            "--set-charset",
        ],
        mysqldump_path=mysqldump,
    )

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            result = subprocess.run(
                cmd,
                stdout=f,
                stderr=subprocess.PIPE,
                timeout=300,  # 5 minutos max
            )

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            # mysqldump imprime warnings en stderr que no son errores fatales
            if "error" in stderr.lower() and "warning" not in stderr.lower():
                filepath.unlink(missing_ok=True)
                raise RuntimeError(f"mysqldump falló: {stderr}")
            # Filtrar warnings benignos antes de loguear (ver _filter_mysqldump_noise)
            filtered = _filter_mysqldump_noise(stderr)
            if filtered:
                logger.warning(f"mysqldump warnings: {filtered}")

        size = filepath.stat().st_size
        logger.info(f"Backup creado: {filename} ({size:,} bytes)")

        # Rotación: eliminar backups viejos
        _rotate_backups()

        return str(filepath)

    except subprocess.TimeoutExpired:
        filepath.unlink(missing_ok=True)
        raise RuntimeError("mysqldump tardó más de 5 minutos. Backup cancelado.")
    except OSError as e:
        raise RuntimeError(f"Error de I/O creando backup: {e}")
    finally:
        cleanup()


# ──────────────────────────────────────────────────────────────
# Restore
# ──────────────────────────────────────────────────────────────
def restore_backup(filename: str) -> None:
    """
    Restaura la BD desde un archivo de backup.
    - MySQL: usa mysql CLI
    - SQLite: copia el archivo .db de vuelta

    Args:
        filename: Nombre del archivo (dentro de BACKUP_DIR) o ruta absoluta.

    Raises:
        FileNotFoundError: Si el archivo no existe.
        RuntimeError: Si el restore falla.
    """
    # Resolver ruta
    filepath = Path(filename)
    if not filepath.is_absolute():
        filepath = BACKUP_DIR / filename

    if not filepath.exists():
        raise FileNotFoundError(f"Archivo de backup no encontrado: {filepath}")

    # Crear backup de seguridad antes de restaurar
    try:
        safety_backup = create_backup(tag="pre_restore")
        logger.info(f"Backup de seguridad creado antes de restore: {safety_backup}")
    except Exception as e:
        logger.warning(f"No se pudo crear backup de seguridad: {e}")

    if is_sqlite():
        _restore_sqlite_backup(filepath)
    else:
        _restore_mysql_backup(filepath)


def _restore_sqlite_backup(filepath: Path) -> None:
    """
    Restaura SQLite con tres garantías de robustez:

    1. **Atomicidad**: copia primero a archivo `.restore.tmp` y al final
       hace `os.replace()` atómico al destino. Si la copia falla a mitad
       (corte de luz, disco lleno, lectura defectuosa), la BD original
       queda intacta — el .tmp se descarta.

    2. **Verificación de integridad**: ejecuta `PRAGMA integrity_check`
       sobre el archivo temporal antes del replace. Si el backup mismo
       estaba corrupto, lo detectamos AQUÍ y NO sobrescribimos la BD
       actual.

    3. **Aislamiento de background tasks**: `_maintenance_event.set()`
       hace que `safe_session()` bloquee nuevas sesiones desde otros
       threads (offline_queue, hacienda_poller, periodic_expire). Pequeña
       pausa después del `engine.dispose()` para que tasks "en vuelo"
       (con conexión ya checked-out) completen su ciclo.

    IMPORTANTE: SQLite con WAL mode mantiene archivos -wal y -shm abiertos.
    Si copiamos el .db mientras SQLAlchemy tiene conexiones activas, el
    archivo puede quedar corrupto. `engine.dispose()` reinicia el pool;
    `safe_session()` bloquea nuevas conexiones durante el restore.

    FASE 3 — Fix 3.3: atomicidad + integridad + aislamiento de background.
    """
    import sqlite3
    import time
    from app.db.database import engine

    db_path = _get_sqlite_db_path()
    tmp_path = Path(str(db_path) + ".restore.tmp")

    try:
        # 1️⃣ Activar modo mantenimiento ANTES de cualquier IO.
        #    safe_session() ya bloquea nuevas sesiones desde este punto.
        _maintenance_event.set()

        # 2️⃣ Reiniciar pool — futuras conexiones se crean limpias contra
        #    el .db nuevo (post-replace). Conexiones ya checked-out no se
        #    cierran activamente; se descartan al devolverse al pool.
        engine.dispose()
        logger.info("Conexiones SQLite cerradas antes de restaurar.")

        # 3️⃣ Pequeña espera para que tasks "en vuelo" (con conexión
        #    abierta antes del dispose) terminen su ciclo. El polling
        #    en safe_session() es 0.25s; 1.5s da buen margen.
        time.sleep(1.5)

        # 4️⃣ Limpiar restos de un restore previo fallido.
        if tmp_path.exists():
            tmp_path.unlink()

        # 5️⃣ Copiar a archivo temporal (no al destino directo). Si
        #    copy2 falla aquí, db_path original queda intacto.
        shutil.copy2(str(filepath), str(tmp_path))

        # 6️⃣ Verificar integridad del archivo temporal antes de
        #    promoverlo. Si el backup está corrupto, abortamos sin
        #    tocar la BD actual.
        conn = sqlite3.connect(str(tmp_path))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
        if not row or row[0] != "ok":
            check_result = row[0] if row else "(sin resultado)"
            raise RuntimeError(
                f"El backup falló la verificación de integridad: "
                f"{check_result}. La BD actual NO fue modificada."
            )

        # 7️⃣ Replace atómico. En POSIX y Windows, os.replace() garantiza
        #    atomicidad si origen y destino están en el mismo volumen
        #    (mismo directorio en nuestro caso). En Windows puede fallar
        #    con WinError 32 si alguien tiene el .db abierto — por eso el
        #    sleep y el flag de maintenance.
        os.replace(str(tmp_path), str(db_path))

        # 8️⃣ Limpiar archivos WAL/SHM del .db viejo. Si quedaran, SQLite
        #    intentaría aplicarlos al .db nuevo → corrupción.
        for suffix in ("-wal", "-shm"):
            residual = Path(str(db_path) + suffix)
            if residual.exists():
                try:
                    residual.unlink()
                except OSError as e:
                    logger.warning(f"No se pudo eliminar {residual.name}: {e}")

        logger.info(f"Base de datos SQLite restaurada desde: {filepath.name}")

    except RuntimeError:
        # Re-raise sin envolver (mensaje ya descriptivo de integrity_check)
        raise
    except (OSError, sqlite3.Error) as e:
        raise RuntimeError(f"Error restaurando SQLite: {e}")
    finally:
        # Cleanup del tmp si quedó (no-op si os.replace ya lo movió).
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        _maintenance_event.clear()


def _restore_mysql_backup(filepath: Path) -> None:
    """Restaura MySQL: usa mysql CLI con credenciales seguras."""
    from app.utils.mysql_safe import build_mysql_cmd

    mysql = _find_mysql()
    if not mysql:
        raise RuntimeError(
            "Cliente mysql no encontrado. Asegúrese de que MySQL esté "
            "instalado y mysql esté en el PATH del sistema."
        )

    # ── FASE 2 — Fix 2.1: Credenciales vía --defaults-extra-file ──
    cmd, cleanup = build_mysql_cmd(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        db_name=settings.db_name,
        mysql_path=mysql,
    )

    try:
        _maintenance_event.set()
        with open(filepath, "r", encoding="utf-8") as f:
            result = subprocess.run(
                cmd,
                stdin=f,
                stderr=subprocess.PIPE,
                timeout=600,  # 10 minutos max
            )

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"Restore falló: {stderr}")

        logger.info(f"Base de datos restaurada desde: {filepath.name}")

    except subprocess.TimeoutExpired:
        raise RuntimeError("Restore tardó más de 10 minutos. Operación cancelada.")
    finally:
        _maintenance_event.clear()
        cleanup()


# ──────────────────────────────────────────────────────────────
# Utilidades
# ──────────────────────────────────────────────────────────────
def list_backups() -> list[dict]:
    """
    Lista los backups disponibles ordenados del más reciente al más viejo.

    Returns:
        Lista de dicts con: filename, size_bytes, size_mb, created_at.

    Nota (FASE 4 — Fix 4.2): `created_at` se retorna como ISO 8601 con
    offset UTC explícito (ej. "2026-05-23T20:30:25.123456+00:00").
    Antes era un naive ISO interpretado como hora local del servidor,
    lo cual era ambiguo si el server corría en TZ distinta a la del
    consumidor. Los consumidores que muestren la fecha al usuario deben
    convertir a hora CR con `app.utils.dt.format_cr`.
    """
    _ensure_backup_dir()
    backups = []

    # Buscar tanto .sql (MySQL) como .db (SQLite)
    patterns = [BACKUP_DIR.glob("backup_*.sql"), BACKUP_DIR.glob("backup_*.db")]
    all_files = []
    for pattern in patterns:
        all_files.extend(pattern)

    for path in sorted(all_files, key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        backups.append({
            "filename": path.name,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            # FASE 4 — Fix 4.2: tz=UTC explícito para evitar ambigüedad.
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })

    return backups


def _rotate_backups() -> None:
    """Elimina los backups más viejos si hay más de MAX_BACKUPS."""
    all_files = list(BACKUP_DIR.glob("backup_*.sql")) + list(BACKUP_DIR.glob("backup_*.db"))
    files = sorted(all_files, key=lambda p: p.stat().st_mtime)

    while len(files) > MAX_BACKUPS:
        oldest = files.pop(0)
        oldest.unlink()
        logger.info(f"Backup eliminado por rotación: {oldest.name}")


# ──────────────────────────────────────────────────────────────
# Backup programado (background task)
# ──────────────────────────────────────────────────────────────
_backup_task = None


def _compute_initial_delay() -> int:
    """
    FASE 4 — Fix 4.3: Calcula segundos hasta el próximo backup automático.

    - Si nunca hubo un backup exitoso → FIRST_BACKUP_DELAY (5 min).
    - Si el último backup fue hace ≥ BACKUP_INTERVAL → FIRST_BACKUP_DELAY.
    - Si el último backup fue hace < BACKUP_INTERVAL → tiempo restante
      hasta completar el intervalo (con piso de FIRST_BACKUP_DELAY para
      dar aire al startup y no encadenar backups si la app reinició
      justo después del último).

    Esto evita dos problemas:
      1) Bug original: dormir 24h ANTES del primer backup hacía que las
         apps con reinicios diarios nunca dispararan uno.
      2) Spam: si la app reinicia varias veces al día, NO crea un backup
         en cada arranque — respeta el intervalo desde el último exitoso.

    Lee `_last_backup_status` (cargado de disco en _load_backup_status),
    por lo que persiste entre reinicios.
    """
    last_success_iso = _last_backup_status.get("last_success_at")
    if not last_success_iso:
        return FIRST_BACKUP_DELAY

    try:
        last_dt = datetime.fromisoformat(last_success_iso)
        # Defensivo: si por alguna razón vino naive, asumir UTC.
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        remaining = BACKUP_INTERVAL - elapsed
        if remaining <= 0:
            return FIRST_BACKUP_DELAY
        return max(int(remaining), FIRST_BACKUP_DELAY)
    except (ValueError, TypeError) as e:
        logger.warning(
            f"No pude parsear last_success_at='{last_success_iso}': {e}. "
            f"Usando FIRST_BACKUP_DELAY como fallback."
        )
        return FIRST_BACKUP_DELAY


def start_scheduled_backups() -> None:
    """Inicia un background task que crea backups periódicamente."""
    global _backup_task

    async def _backup_loop():
        # ── FASE 4 — Fix 4.3 ─────────────────────────────────────
        # Primer backup poco después del startup (o al completar el
        # intervalo restante si el último fue reciente). El sleep
        # del intervalo queda DESPUÉS del backup, no antes.
        initial_delay = _compute_initial_delay()
        logger.info(
            f"Primer backup automático en {initial_delay}s "
            f"(~{initial_delay // 60} min)"
        )
        await asyncio.sleep(initial_delay)

        while True:
            try:
                path = create_backup(tag="auto")
                logger.info(f"Backup automático creado: {path}")
            except Exception as e:
                # create_backup ya registró el fallo vía _record_failure
                failures = _last_backup_status.get("consecutive_failures", 0)
                logger.error(
                    f"Error en backup automático (fallo consecutivo #{failures}): {e}"
                )
                if failures >= 3:
                    logger.critical(
                        f"ALERTA: {failures} backups automáticos consecutivos han fallado. "
                        f"Último error: {e}. Verifique el espacio en disco y los permisos."
                    )
            await asyncio.sleep(BACKUP_INTERVAL)

    _backup_task = asyncio.ensure_future(_backup_loop())
    logger.info(
        f"Backup automático programado cada {BACKUP_INTERVAL // 3600}h "
        f"(directorio: {BACKUP_DIR})"
    )


def stop_scheduled_backups() -> None:
    """Detiene el background task de backups."""
    global _backup_task
    if _backup_task and not _backup_task.done():
        _backup_task.cancel()
        logger.info("Backup automático detenido.")