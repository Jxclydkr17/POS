# app/core/security.py
"""
FASE 2 — Fix 2.1: Migración de python-jose a PyJWT.

python-jose no se actualiza desde 2022 y tiene CVEs publicados.
PyJWT es la librería estándar, activamente mantenida, con API compatible.

Cambios:
  - `from jose import jwt, JWTError` → `import jwt` + `jwt.InvalidTokenError`
  - El resto de la API es idéntica (encode, decode, algorithms)
"""
from app.core.config import settings
from datetime import timedelta
from app.utils.dt import utcnow

import jwt

# Configuración de encriptación
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = settings.secret_key

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120  # 2 horas


def hash_password(password: str) -> str:
    """Genera el hash de una contraseña"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si la contraseña es correcta"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict):
    """Genera un token JWT de acceso."""
    to_encode = data.copy()
    now = utcnow()
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # ── FASE 3 — Fix 3.3: iat para revocación por timestamp ──
    to_encode.update({"exp": expire, "iat": now, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


REFRESH_TOKEN_EXPIRE_MINUTES = 1440  # 24 horas


def create_refresh_token(data: dict):
    """Genera un refresh token JWT (mayor duración, solo para renovar access)."""
    to_encode = data.copy()
    now = utcnow()
    expire = now + timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)
    # ── FASE 3 — Fix 3.3: iat para revocación por timestamp ──
    to_encode.update({"exp": expire, "iat": now, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str):
    """Decodifica un token JWT"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.InvalidTokenError:
        return None


# ── FASE 3 — Fix 3.1 ──────────────────────────────────────
# get_current_user, require_role y oauth2_scheme viven SOLO
# en app/core/dependencies.py.  Este módulo exporta únicamente
# utilidades de tokens y passwords.
# ───────────────────────────────────────────────────────────