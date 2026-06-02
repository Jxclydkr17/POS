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

# Fix 3.3: bcrypt directo (passlib está abandonado y genera DeprecationWarning
# en Python 3.12+). Los hashes existentes ($2b$) son 100% compatibles.
import bcrypt as _bcrypt
import hashlib as _hashlib
import base64 as _base64

SECRET_KEY = settings.secret_key

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120  # 2 horas


# ═══════════════════════════════════════════════════════════════
# FASE 3 — Fix: límite de 72 bytes de bcrypt
# ═══════════════════════════════════════════════════════════════
# bcrypt SOLO usa los primeros 72 bytes de la contraseña y descarta el
# resto SILENCIOSAMENTE (verificado: dos contraseñas que comparten los
# primeros 72 bytes producen el mismo hash). Como el esquema acepta
# contraseñas de hasta 255 caracteres, esto era una debilidad real: parte
# de la contraseña no contaba para nada.
#
# Solución — esquema "bcrypt-sha256" (el mismo que usan Django y passlib):
# se pre-hashea la contraseña con SHA-256 y se codifica en base64 ANTES de
# pasarla a bcrypt. El resultado mide SIEMPRE 44 bytes (< 72), así bcrypt
# nunca trunca y se preserva TODA la entropía de la contraseña completa.
#
# Compatibilidad hacia atrás (sin bloquear a nadie):
#   - Hashes nuevos      → llevan el prefijo `bcrypt-sha256$`.
#   - Hashes legacy ($2b$…) → se verifican con bcrypt directo, truncando a
#     72 bytes EXACTAMENTE como bcrypt lo hacía internamente al crearlos,
#     de modo que siguen validando igual que antes.
# Los usuarios migran al esquema nuevo de forma natural: al crear su cuenta,
# al cambiar su contraseña, o automáticamente en su próximo login exitoso
# (ver `needs_rehash` y el endpoint /login).
_NEW_SCHEME_PREFIX = "bcrypt-sha256$"


def _prehash(password: str) -> bytes:
    """SHA-256(password) en base64 → 44 bytes, siempre < 72 (límite bcrypt)."""
    digest = _hashlib.sha256(password.encode("utf-8")).digest()
    return _base64.b64encode(digest)


def hash_password(password: str) -> str:
    """Genera el hash de una contraseña con el esquema bcrypt-sha256.

    Pre-hashea con SHA-256 para eludir el límite de 72 bytes de bcrypt SIN
    truncar la contraseña (se conserva la entropía completa, hasta los 255
    caracteres que permite el esquema).
    """
    bcrypt_hash = _bcrypt.hashpw(_prehash(password), _bcrypt.gensalt()).decode("utf-8")
    return _NEW_SCHEME_PREFIX + bcrypt_hash


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica la contraseña contra el hash almacenado.

    Soporta de forma transparente los dos formatos:
      - Nuevo  (`bcrypt-sha256$…`): SHA-256 + bcrypt.
      - Legacy (`$2b$…`)         : bcrypt directo, truncando a 72 bytes
        (idéntico a como se crearon esos hashes).
    """
    try:
        if hashed_password.startswith(_NEW_SCHEME_PREFIX):
            bcrypt_hash = hashed_password[len(_NEW_SCHEME_PREFIX):]
            return _bcrypt.checkpw(
                _prehash(plain_password),
                bcrypt_hash.encode("utf-8"),
            )
        # Legacy: bcrypt sólo usaba los primeros 72 bytes; replicamos ese
        # truncado explícitamente para verificar correctamente y sin error
        # (bcrypt 4.x trunca en silencio; con el corte explícito el
        # comportamiento queda determinista).
        legacy_pw = plain_password.encode("utf-8")[:72]
        return _bcrypt.checkpw(legacy_pw, hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        # Hash corrupto o formato incompatible
        return False


def needs_rehash(hashed_password: str) -> bool:
    """True si el hash NO usa el esquema nuevo (bcrypt-sha256).

    Permite migrar de forma transparente los hashes legacy a bcrypt-sha256
    tras un login exitoso, cuando tenemos la contraseña en claro.
    """
    return not (hashed_password or "").startswith(_NEW_SCHEME_PREFIX)


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