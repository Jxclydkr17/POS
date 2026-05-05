"""
app/core/config.py — Variables de entorno (.env)

FASE 4: Soporte dual de base de datos:
  - DB_ENGINE=sqlite  → Para .exe standalone (default si no hay MySQL configurado)
  - DB_ENGINE=mysql   → Para instalaciones con MySQL externo

Si DB_ENGINE no está definido, se auto-detecta:
  - Si DB_USER/DB_PASSWORD están configurados → MySQL
  - Si no → SQLite (archivo local violette_pos.db)
"""

import os
import sys
import secrets
import logging
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings
from pydantic import field_validator

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Determinar directorio base (funciona tanto en dev como en .exe)
# ──────────────────────────────────────────────────────────────
def get_app_dir() -> Path:
    """Retorna el directorio base de la aplicación."""
    if getattr(sys, 'frozen', False):
        # Ejecutando como .exe (PyInstaller)
        return Path(sys.executable).parent
    else:
        # Ejecutando como script
        return Path(__file__).resolve().parents[2]

APP_DIR = get_app_dir()


# ──────────────────────────────────────────────────────────────
# Auto-generar SECRET_KEY
# ──────────────────────────────────────────────────────────────
_INSECURE_DEFAULT_KEYS = {
    "",
    "tu_clave_super_secreta_genera_una_aleatoria_aqui_min_32_caracteres",
    "changeme",
    "secret",
}


def _ensure_secret_key() -> str:
    current = os.environ.get("SECRET_KEY", "").strip()
    if current.lower() not in _INSECURE_DEFAULT_KEYS:
        return current

    new_key = secrets.token_hex(32)
    env_path = APP_DIR / ".env"
    try:
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
            if "SECRET_KEY=" in content:
                import re
                content = re.sub(
                    r"^SECRET_KEY=.*$",
                    f"SECRET_KEY={new_key}",
                    content,
                    flags=re.MULTILINE,
                )
            else:
                content += f"\nSECRET_KEY={new_key}\n"
            env_path.write_text(content, encoding="utf-8")
        else:
            env_path.write_text(f"SECRET_KEY={new_key}\n", encoding="utf-8")
        logger.warning("SECRET_KEY genérica detectada. Se generó una nueva.")
    except OSError as e:
        logger.error(
            f"⚠️ CRÍTICO: No se pudo persistir SECRET_KEY en .env ({e}). "
            f"La clave se generó solo en memoria. Al reiniciar la aplicación: "
            f"(1) se generará una clave diferente, "
            f"(2) TODOS los tokens JWT activos se invalidarán (sesiones cerradas), "
            f"(3) las API keys encriptadas no se podrán descifrar. "
            f"Solución: asegúrese de que el archivo .env tenga permisos de escritura."
        )

    os.environ["SECRET_KEY"] = new_key
    return new_key


_ensure_secret_key()


class Settings(BaseSettings):
    app_name: str = "Violette POS"
    app_env: str = "development"
    # ── FASE 1 — Fix 1.5: Default seguro (False) para producción ──
    app_debug: bool = False

    # ── FASE 3 — Fix 3.1: Flag independiente para docs API ──
    # Permite acceder a /docs y /redoc sin activar debug mode completo.
    # Activar en .env con ENABLE_DOCS=true para diagnóstico en producción.
    enable_docs: bool = False

    # ── FASE 4: Motor de BD ──
    # "sqlite" = standalone (default para .exe)
    # "mysql"  = servidor MySQL externo
    db_engine: str = "sqlite"

    # Campos MySQL (opcionales si db_engine=sqlite)
    db_user: str = ""
    db_password: str = ""
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "violette_db"

    # Ruta del archivo SQLite (relativa al directorio de la app)
    db_sqlite_path: str = "violette_pos.db"

    # ── Pool de conexiones MySQL (Fase 5 — Bug 5.3) ──
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800    # segundos (30 min) — evita "MySQL has gone away"
    db_pool_timeout: int = 30

    secret_key: str = ""

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    email_user: str | None = None
    email_pass: str | None = None

    # ── Hacienda ──
    hacienda_api: str | None = None
    hacienda_cert_path: str | None = None
    hacienda_cert_pass: str | None = None
    hacienda_env: str = "sandbox"
    hacienda_user: str | None = None
    hacienda_password: str | None = None

    @field_validator('db_engine')
    @classmethod
    def check_db_engine(cls, v):
        v = (v or "sqlite").lower().strip()
        if v not in ("sqlite", "mysql"):
            raise ValueError("DB_ENGINE debe ser 'sqlite' o 'mysql'")
        return v

    @field_validator('hacienda_env')
    @classmethod
    def check_hacienda_env(cls, v):
        if v and v not in ("sandbox", "production"):
            raise ValueError("HACIENDA_ENV debe ser 'sandbox' o 'production'")
        return v or "sandbox"

    class Config:
        env_file = os.environ.get("VIOLETTE_ENV_FILE", str(APP_DIR / ".env"))
        env_file_encoding = "utf-8"


# ── Auto-detectar engine si no está definido explícitamente ──
def _auto_detect_engine():
    """Si DB_ENGINE no está en .env, auto-detecta según las credenciales."""
    explicit = os.environ.get("DB_ENGINE", "").strip().lower()
    if explicit:
        return  # El usuario lo definió, respetar

    db_user = os.environ.get("DB_USER", "").strip()
    db_pass = os.environ.get("DB_PASSWORD", "").strip()

    if db_user and db_pass:
        os.environ.setdefault("DB_ENGINE", "mysql")
    else:
        os.environ.setdefault("DB_ENGINE", "sqlite")


_auto_detect_engine()

settings = Settings()


def get_database_url() -> str:
    """Retorna la URL de conexión según el engine configurado."""
    if settings.db_engine == "sqlite":
        db_path = APP_DIR / settings.db_sqlite_path
        return f"sqlite:///{db_path}"
    else:
        # ── FASE 1 — Fix 1.4: URL-encode usuario y password ──
        # Caracteres como @, #, /, % en el password rompen la URL de conexión.
        user = quote_plus(settings.db_user)
        password = quote_plus(settings.db_password)
        return (
            f"mysql+pymysql://{user}:{password}"
            f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
        )


def is_sqlite() -> bool:
    """Helper para saber si estamos usando SQLite."""
    return settings.db_engine == "sqlite"


# ── FASE 5 — Fix 5.4 + Fix 3.2: Versión centralizada ──────
# Fuente única de verdad: archivo VERSION en la raíz del proyecto.
# config.py, installer.iss y build.bat leen de este mismo archivo.
def _read_version() -> str:
    version_file = APP_DIR / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        logger.warning("Archivo VERSION no encontrado, usando fallback '1.0.0'")
        return "1.0.0"

APP_VERSION = _read_version()


# ── FASE 5 — Fix 5.2: Directorio de datos externo ───────────
# Los PDFs y otros archivos generados van en APP_DIR/data/
# para que no se pierdan al actualizar la app.
DATA_DIR = APP_DIR / "data"


def get_pdf_dir() -> Path:
    """Retorna el directorio para PDFs generados, creándolo si no existe."""
    pdf_dir = DATA_DIR / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    return pdf_dir


# ── FASE 7 — Fix 7.1: Resolución portable de assets ─────────
# Las rutas relativas como "ui/assets/logo.png" no funcionan
# cuando la app corre como .exe empaquetado con PyInstaller,
# porque el CWD puede ser distinto a APP_DIR.
# Estas funciones resuelven assets relativas a APP_DIR, que ya
# maneja correctamente tanto el modo dev como el modo .exe
# (ver get_app_dir() arriba).

def get_asset_path(relative_path: str) -> Path | None:
    """Resuelve un asset relativo a APP_DIR.

    Args:
        relative_path: Ruta relativa al directorio de la app
                       (ej: "ui/assets/logo.png").

    Returns:
        Path absoluto si el archivo existe, None si no.
    """
    full = APP_DIR / relative_path
    return full if full.exists() else None


def get_logo_path() -> str | None:
    """Busca el logo del negocio en las ubicaciones conocidas.

    Recorre una lista de nombres comunes de logo en ui/assets/.
    Retorna la ruta absoluta como string (compatible con ReportLab,
    os.path.exists, etc.), o None si no se encuentra ninguno.

    El usuario puede colocar su logo como cualquiera de estos archivos:
      - ui/assets/logoferre.jpg  (nombre actual del proyecto)
      - ui/assets/logo.png
      - ui/assets/logo.jpg
    """
    candidates = [
        "ui/assets/logoferre.jpg",
        "ui/assets/logo.png",
        "ui/assets/logo.jpg",
    ]
    for candidate in candidates:
        path = get_asset_path(candidate)
        if path:
            return str(path)
    return None