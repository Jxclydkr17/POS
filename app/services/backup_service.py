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
import glob
import logging
import asyncio
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

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


def _ensure_backup_dir() -> Path:
    """Crea el directorio de backups si no existe."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


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
    - MySQL: usa mysqldump
    - SQLite: copia el archivo .db

    Args:
        tag: Etiqueta opcional para el nombre del archivo (ej: "pre_update")

    Returns:
        Ruta absoluta del archivo de backup creado.

    Raises:
        RuntimeError: Si el backup falla.
    """
    _ensure_backup_dir()
    # FASE 4 — Fix 4.3: now_cr() en vez de datetime.now() para consistencia
    timestamp = now_cr().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{tag}" if tag else ""

    if is_sqlite():
        return _create_sqlite_backup(timestamp, suffix)
    else:
        return _create_mysql_backup(timestamp, suffix)


def _get_sqlite_db_path() -> Path:
    """Retorna la ruta del archivo SQLite."""
    return APP_DIR / settings.db_sqlite_path


def _create_sqlite_backup(timestamp: str, suffix: str) -> str:
    """Backup de SQLite: copia del archivo .db."""
    db_path = _get_sqlite_db_path()
    if not db_path.exists():
        raise RuntimeError(f"Archivo SQLite no encontrado: {db_path}")

    filename = f"backup_sqlite_{timestamp}{suffix}.db"
    filepath = BACKUP_DIR / filename

    try:
        shutil.copy2(str(db_path), str(filepath))
        size = filepath.stat().st_size
        logger.info(f"Backup SQLite creado: {filename} ({size:,} bytes)")
        _rotate_backups()
        return str(filepath)
    except OSError as e:
        filepath.unlink(missing_ok=True)
        raise RuntimeError(f"Error copiando archivo SQLite: {e}")


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
            logger.warning(f"mysqldump warnings: {stderr}")

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
    """Restaura SQLite: copia el archivo .db de vuelta."""
    db_path = _get_sqlite_db_path()
    try:
        shutil.copy2(str(filepath), str(db_path))
        logger.info(f"Base de datos SQLite restaurada desde: {filepath.name}")
    except OSError as e:
        raise RuntimeError(f"Error restaurando SQLite: {e}")


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
        cleanup()


# ──────────────────────────────────────────────────────────────
# Utilidades
# ──────────────────────────────────────────────────────────────
def list_backups() -> list[dict]:
    """
    Lista los backups disponibles ordenados del más reciente al más viejo.

    Returns:
        Lista de dicts con: filename, size_bytes, size_mb, created_at
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
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
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


def start_scheduled_backups() -> None:
    """Inicia un background task que crea backups periódicamente."""
    global _backup_task

    async def _backup_loop():
        while True:
            await asyncio.sleep(BACKUP_INTERVAL)
            try:
                path = create_backup(tag="auto")
                logger.info(f"Backup automático creado: {path}")
            except Exception as e:
                logger.error(f"Error en backup automático: {e}")

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