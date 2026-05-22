# app/core/data_migration.py
"""
FASE 2 — Fix 2.2: Migración de directorios persistentes.

Antes (buggy):
  - LOGO_DIR        = app/uploads/logos        (en .exe: _internal/app/uploads/logos)
  - CERT_DIR        = app/certs                (en .exe: _internal/app/certs)
  - PURCHASES_DIR   = uploads/purchases        (en .exe: _internal/uploads/purchases)

Todos vivían dentro del bundle (`_internal/` en modo PyInstaller --onedir),
que el instalador Inno Setup sobrescribe con `recursesubdirs` en cada
actualización → pérdida total del certificado .p12 de Hacienda, logos
y PDFs adjuntos a compras.

Ahora viven en DATA_DIR (= APP_DIR/data/), que es externo al bundle
y persiste entre updates.

Este módulo migra al startup:
  1. Copia archivos de ubicaciones legacy a DATA_DIR (idempotente,
     no sobrescribe destinos que ya existen).
  2. Si `hacienda_cert_path` en secure_config apunta a una ruta que
     ya no existe pero el cert está en DATA_DIR/certs/firma.p12,
     actualiza el path en BD para que la facturación electrónica
     siga funcionando.

Se COPIA, no se mueve: si algo sale mal, los archivos viejos siguen
disponibles. Tampoco se borran las carpetas legacy: el siguiente
update del installer las limpia naturalmente.

La migración es idempotente y silenciosa (loggea pero no falla):
si la corremos 10 veces, el resultado es el mismo que correrla una.
"""
from __future__ import annotations

import shutil
import logging
from pathlib import Path

from app.core.config import APP_DIR, DATA_DIR

logger = logging.getLogger(__name__)


# Pares (src relativo a APP_DIR, dst relativo a APP_DIR).
# Cubre tanto modo dev (sin _internal/) como modo .exe frozen (con _internal/).
# En la práctica, en .exe el directorio _internal/ se sobrescribe en cada
# update así que estos paths rara vez tendrán contenido al momento de la
# migración — pero los chequeamos por defensa, son baratos.
_LEGACY_PAIRS: tuple[tuple[str, str], ...] = (
    # Modo dev / source (rutas relativas al proyecto)
    ("app/uploads/logos",            "data/uploads/logos"),
    ("app/certs",                    "data/certs"),
    ("uploads/purchases",            "data/uploads/purchases"),
    # Modo .exe (PyInstaller --onedir): contenido bajo _internal/
    ("_internal/app/uploads/logos",  "data/uploads/logos"),
    ("_internal/app/certs",          "data/certs"),
    ("_internal/uploads/purchases",  "data/uploads/purchases"),
)


def _copy_files_only(src: Path, dst: Path) -> int:
    """Copia archivos (no recursivo, sólo files de primer nivel) de src a dst.

    - Si src no existe o es igual al destino, retorna 0.
    - Crea dst si no existe.
    - NUNCA sobrescribe archivos en destino — el destino siempre tiene
      prioridad (es la "verdad nueva").
    - Errores por archivo se loggean pero no detienen la migración.
    """
    if not src.is_dir():
        return 0
    try:
        if src.resolve() == dst.resolve():
            return 0
    except OSError:
        # resolve() puede fallar en rutas raras; seguimos con la comparación textual
        if str(src) == str(dst):
            return 0

    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for item in src.iterdir():
        if not item.is_file():
            continue
        target = dst / item.name
        if target.exists():
            # No sobrescribir: el destino nuevo tiene prioridad
            continue
        try:
            shutil.copy2(item, target)
            copied += 1
        except OSError as e:
            logger.warning(
                f"Migración Fase 2.2: no se pudo copiar {item} → {target}: {e}"
            )
    return copied


def _migrate_files() -> int:
    """Itera los _LEGACY_PAIRS y copia. Retorna total de archivos copiados."""
    total = 0
    for src_rel, dst_rel in _LEGACY_PAIRS:
        total += _copy_files_only(APP_DIR / src_rel, APP_DIR / dst_rel)
    return total


def _migrate_hacienda_cert_path() -> bool:
    """
    Si `hacienda_cert_path` en secure_config apunta a un archivo que
    ya no existe (típicamente porque el installer borró _internal/),
    PERO el cert está disponible en DATA_DIR/certs/firma.p12, actualiza
    la ruta en BD.

    Retorna True si actualizó algo.

    Caso defensivo: la BD podría no estar lista (primera instalación,
    error de import). Cualquier fallo se loggea como warning y
    retornamos False — la migración no debe romper el startup.
    """
    new_path = DATA_DIR / "certs" / "firma.p12"
    if not new_path.is_file():
        return False  # No hay cert nuevo, no podemos arreglar nada

    try:
        from app.db.database import safe_session
        from app.services.secure_config_service import get_secure, set_secure
    except Exception as e:
        logger.warning(
            f"Migración Fase 2.2: no se pudo cargar secure_config_service: {e}"
        )
        return False

    try:
        with safe_session() as db:
            stored = get_secure(db, "hacienda_cert_path") or ""
            if not stored:
                return False  # Nunca se subió cert, no hay nada que actualizar
            stored_path = Path(stored)
            if stored_path.is_file():
                # La ruta actual sigue siendo válida (cert no se movió)
                return False
            new_path_str = str(new_path)
            if stored == new_path_str:
                # Ya apuntaba a la nueva, pero el .is_file() falló arriba
                # — caso raro, no hacer nada
                return False
            # La ruta almacenada está rota y el cert sí existe en la nueva
            # ubicación: actualizar.
            set_secure(db, "hacienda_cert_path", new_path_str)
            db.commit()
            logger.info(
                f"Migración Fase 2.2: hacienda_cert_path actualizado "
                f"de '{stored}' a '{new_path_str}' (cert encontrado en DATA_DIR)."
            )
            return True
    except Exception as e:
        logger.warning(
            f"Migración Fase 2.2: error actualizando hacienda_cert_path: {e}"
        )
        return False


def migrate_legacy_data_dirs() -> None:
    """
    FASE 2 — Fix 2.2: Punto de entrada. Idempotente.

    Llamar UNA vez al startup, antes de cualquier código que dependa
    de los directorios persistentes (en particular antes de los
    background tasks de Hacienda, que cargan el cert).

    No levanta excepciones: si algo falla, se loggea y el startup
    continúa. Mejor degradar a "el cert/logo viejo no se migró"
    que tumbar la app entera.
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        copied = _migrate_files()
        if copied:
            logger.info(
                f"Migración Fase 2.2: {copied} archivo(s) copiado(s) de "
                f"ubicaciones legacy a DATA_DIR."
            )
        _migrate_hacienda_cert_path()
    except Exception as e:
        logger.error(
            f"Migración Fase 2.2 falló (continuando con startup): {e}",
            exc_info=True,
        )