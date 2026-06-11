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
import re
import sys
import secrets
import logging
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict
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
# Directorio de RECURSOS de solo lectura empaquetados (read-only)
# ──────────────────────────────────────────────────────────────
# IMPORTANTE — distinción frente a APP_DIR:
#
#   - APP_DIR       → datos ESCRIBIBLES y persistentes del usuario
#                     (.env, violette_pos.db, data/logs, data/backups,
#                      data/pdfs, certs). En el .exe es la carpeta del
#                      ejecutable ({app}\), que sobrevive a las
#                      actualizaciones.
#
#   - RESOURCE_DIR  → recursos de SOLO LECTURA que viajan dentro del
#                     paquete (migraciones alembic, esquemas XSD, el
#                     catálogo economic_activities.csv, VERSION, los
#                     assets de ui/assets, la plantilla .env.example).
#
# Por qué son distintos en el .exe:
#   PyInstaller 6.x (onedir) coloca TODOS los archivos empaquetados en
#   una subcarpeta `_internal\` y deja solo el .exe en la raíz. Por eso
#   `sys._MEIPASS` (= la carpeta `_internal`) es la raíz de los recursos,
#   mientras que `Path(sys.executable).parent` (= {app}\) es la carpeta
#   de datos escribibles. Resolver los recursos contra APP_DIR fallaba
#   porque buscaba en {app}\ archivos que en realidad están en
#   {app}\_internal\ (alembic.ini, el CSV, VERSION, el logo de los PDF…).
#
# En modo desarrollo ambas rutas coinciden con la raíz del proyecto, así
# que el comportamiento es idéntico al de siempre.
def get_resource_dir() -> Path:
    """Retorna la raíz de los recursos de solo lectura empaquetados."""
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return Path(meipass)
        # Fallback defensivo: si por alguna razón no hay _MEIPASS
        # (build con layout plano antiguo), los recursos están junto
        # al ejecutable.
        return Path(sys.executable).parent
    # Desarrollo: raíz del proyecto (igual que APP_DIR).
    return Path(__file__).resolve().parents[2]


RESOURCE_DIR = get_resource_dir()


def resolve_resource(relative_path: str) -> Path | None:
    """Resuelve un recurso empaquetado de solo lectura.

    Busca primero en RESOURCE_DIR (la ubicación correcta en el .exe) y,
    como red de seguridad, también en APP_DIR (cubre builds con layout
    plano o copias manuales del instalador). En desarrollo ambas rutas
    son la misma, así que se comporta como antes.

    Args:
        relative_path: ruta relativa al recurso, p. ej. "VERSION" o
                       "ui/assets/logo.png".

    Returns:
        Path absoluto si el recurso existe en alguna de las ubicaciones,
        None si no se encuentra.
    """
    seen: set[Path] = set()
    for base in (RESOURCE_DIR, APP_DIR):
        if base in seen:
            continue
        seen.add(base)
        candidate = base / relative_path
        if candidate.exists():
            return candidate
    return None


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
    # 1) Prioridad: SECRET_KEY explícita en el entorno (permite override externo).
    current = os.environ.get("SECRET_KEY", "").strip()
    if current.lower() not in _INSECURE_DEFAULT_KEYS:
        os.environ["SECRET_KEY"] = current
        return current

    env_path = APP_DIR / ".env"

    # 2) FASE 4 — Fix del churn de SECRET_KEY: reutilizar la clave YA persistida
    #    en el .env. Antes esta función solo miraba os.environ, que en un proceso
    #    nuevo está vacío (el .env NO se carga al entorno del sistema), por lo que
    #    generaba una clave NUEVA en cada arranque y reescribía el .env. Eso
    #    invalidaba las sesiones (JWT) y dejaba IRRECUPERABLES las API keys
    #    cifradas (Fernet deriva su clave del SECRET_KEY). Si el .env ya tiene una
    #    SECRET_KEY válida, la reutilizamos y NO regeneramos.
    if env_path.exists():
        try:
            existing = env_path.read_text(encoding="utf-8")
            m = re.search(r"^\s*SECRET_KEY\s*=(.*)$", existing, flags=re.MULTILINE)
            if m and m.group(1).strip().lower() not in _INSECURE_DEFAULT_KEYS:
                persisted = m.group(1).strip()
                os.environ["SECRET_KEY"] = persisted
                return persisted
        except OSError:
            pass  # ilegible → caemos a generar una nueva

    # 3) No hay clave válida en ningún lado → generar y persistir.
    new_key = secrets.token_hex(32)
    try:
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
            if "SECRET_KEY=" in content:
                content = re.sub(
                    r"^SECRET_KEY=.*$",
                    f"SECRET_KEY={new_key}",
                    content,
                    flags=re.MULTILINE,
                )
            else:
                content += f"\nSECRET_KEY={new_key}\n"
            env_path.write_text(content, encoding="utf-8")
        # DESPUÉS — Si no hay .env, copia desde .env.example o crea uno completo
        else:
            # La plantilla .env.example es un recurso de SOLO LECTURA que
            # viaja dentro del paquete (en el .exe vive en _internal\), así
            # que se resuelve con resolve_resource (RESOURCE_DIR + fallback
            # a APP_DIR). El .env destino sí se crea en APP_DIR (escribible).
            env_example = resolve_resource(".env.example")
            if env_example is not None:
                import shutil
                shutil.copy2(env_example, env_path)
                # Ahora sí, reemplaza el SECRET_KEY dentro del template copiado
                content = env_path.read_text(encoding="utf-8")
                content = re.sub(
                    r"^SECRET_KEY=.*$",
                    f"SECRET_KEY={new_key}",
                    content,
                    flags=re.MULTILINE,
                )
                env_path.write_text(content, encoding="utf-8")
            else:
                # Fallback mínimo pero honesto
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

    # ── Actualizaciones automáticas (GitHub Releases) ──────────
    # El updater consulta la API pública de GitHub:
    #   https://api.github.com/repos/<GITHUB_OWNER>/<GITHUB_REPO>/releases/latest
    # Requiere que el repositorio sea PÚBLICO (así no hace falta token).
    # Si owner/repo quedan vacíos, el chequeo de actualizaciones se
    # desactiva solo (get_github_releases_api_url() devuelve None) y la app
    # funciona normal — útil en desarrollo o instalaciones sin updates.
    github_owner: str = ""
    github_repo: str = ""

    # Chequeo automático al iniciar sesión (solo lo ve el admin).
    # Poner UPDATE_CHECK_ENABLED=False en el .env para desactivarlo sin
    # tocar github_owner/github_repo (p. ej. durante una jornada de ventas).
    update_check_enabled: bool = True

    @field_validator('db_port', mode='before')
    @classmethod
    def _empty_port_to_default(cls, v):
        # FASE 3.3: el wizard (al elegir SQLite) y los .env manuales pueden
        # dejar DB_PORT vacío. pydantic intentaría convertir "" a int y
        # lanzaría ValidationError, abortando el arranque. Tratamos vacío /
        # solo-espacios / None como "usar el default 3306".
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return 3306
        return v

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

    model_config = SettingsConfigDict(
        env_file=os.environ.get("VIOLETTE_ENV_FILE", str(APP_DIR / ".env")),
        env_file_encoding="utf-8",
    )


# ── Resolución del motor de BD ──
# FASE 3.3: el motor se toma de DB_ENGINE en el .env (lo lee pydantic-settings),
# con default "sqlite" si no está definido (ver el campo `db_engine` arriba).
#
# Antes existía `_auto_detect_engine()`, que ESCRIBÍA os.environ["DB_ENGINE"]
# ANTES de que Settings() leyera el .env. Como en pydantic-settings las
# variables de os.environ tienen PRIORIDAD sobre el archivo .env, ese
# `setdefault` pisaba el valor del .env: aunque el usuario (o el wizard de
# primer arranque) escribiera DB_ENGINE=mysql en el .env, la app terminaba
# usando sqlite. Al eliminarlo, el .env vuelve a ser la única fuente de verdad
# y la elección del wizard (sqlite o mysql) sí tiene efecto.

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
# El VERSION es un recurso de solo lectura empaquetado → resolve_resource
# (en el .exe vive en _internal\, no junto al ejecutable).
def _read_version() -> str:
    version_file = resolve_resource("VERSION")
    if version_file is not None:
        try:
            return version_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    logger.warning("Archivo VERSION no encontrado, usando fallback '1.0.0'")
    return "1.0.0"

APP_VERSION = _read_version()


# ── Actualizaciones automáticas — URL de la API de GitHub Releases ──────
# Construye la URL del endpoint "latest release" a partir de GITHUB_OWNER /
# GITHUB_REPO (definidos en el .env). Devuelve None si no están configurados,
# en cuyo caso el updater queda inactivo sin romper nada.
#
# El repositorio debe ser PÚBLICO: así la API responde sin token y no hace
# falta embeber credenciales (un PAT dentro del .exe sería extraíble por
# cualquiera). Ver app/services/updater.py para el consumo de esta URL.
def get_github_releases_api_url() -> str | None:
    """Retorna la URL de la API de GitHub para el último release, o None."""
    owner = (settings.github_owner or "").strip()
    repo = (settings.github_repo or "").strip()
    if not owner or not repo:
        return None
    return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"


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
# porque el CWD puede ser distinto y, en PyInstaller 6.x, los assets
# viajan en la subcarpeta _internal\ (no junto al ejecutable).
# get_asset_path resuelve los assets como recursos de solo lectura
# (RESOURCE_DIR primero, con fallback a APP_DIR), de modo que el logo
# de las facturas/PDF aparece tanto en modo dev como en el .exe.

def get_asset_path(relative_path: str) -> Path | None:
    """Resuelve un asset empaquetado de solo lectura (ej: el logo).

    Args:
        relative_path: Ruta relativa al recurso
                       (ej: "ui/assets/logo.png").

    Returns:
        Path absoluto si el archivo existe, None si no.
    """
    return resolve_resource(relative_path)


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