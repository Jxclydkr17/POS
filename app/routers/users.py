from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models.user import User, ALL_PERMISSIONS, DEFAULT_PERMISSIONS
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token as _decode_token
# ── FASE 3 — Fix 3.1: Fuente única para auth ──
from app.core.dependencies import get_current_user, require_role
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime, timedelta, timezone
from typing import Optional

import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)


# ── Schemas de validación (Fase 8 — Bug 8.2) ─────────────
class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    # ── FASE 1 — Fix 1.3: Password mínimo 8 caracteres ──
    password: str = Field(..., min_length=8, max_length=255)
    full_name: Optional[str] = Field(None, max_length=150)
    role: str = Field("vendedor", pattern=r"^(admin|vendedor|cajero)$")


class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    password: Optional[str] = Field(None, min_length=8, max_length=255)
    full_name: Optional[str] = Field(None, max_length=150)
    role: Optional[str] = Field(None, pattern=r"^(admin|vendedor|cajero)$")
    is_active: Optional[bool] = None


class UserOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str]
    role: str
    is_active: bool
    permissions: list[str] = []
    created_at: Optional[datetime]

    class Config:
        from_attributes = True

    @classmethod
    def from_user(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            permissions=user.get_permissions(),
            created_at=user.created_at,
        )


class PermissionsUpdate(BaseModel):
    permissions: list[str]


class RefreshTokenRequest(BaseModel):
    refresh_token: str

router = APIRouter(
    prefix="/users",
    tags=["Usuarios"]
)

# ────────────────────────────────────────────────────────────
#  Rate limiter persistido en archivo JSON (Fase 2 — Fix 2.1)
#
#  Mejoras sobre la versión anterior (dict en memoria):
#  - Persiste entre reinicios del servidor
#  - Compartido entre workers de uvicorn (vía filesystem)
#  - Thread-safe con lock
# ────────────────────────────────────────────────────────────
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300
LOGIN_LOCKOUT_SECONDS = 600
_MAX_TRACKED_IPS = 10_000
_lock = threading.Lock()

_login_attempts: dict[str, deque] = {}


def _check_rate_limit(client_ip: str):
    """Lanza HTTPException 429 si el IP excedió los intentos permitidos."""
    with _lock:
        now = time.monotonic()
        window_start = now - LOGIN_WINDOW_SECONDS

        timestamps = _login_attempts.get(client_ip, deque())

        # Limpiar timestamps fuera del lockout
        while timestamps and timestamps[0] < (now - LOGIN_LOCKOUT_SECONDS):
            timestamps.popleft()

        recent = [ts for ts in timestamps if ts > window_start]

        if len(recent) >= LOGIN_MAX_ATTEMPTS:
            oldest = recent[0]
            lockout_until = oldest + LOGIN_LOCKOUT_SECONDS
            if now < lockout_until:
                retry_secs = max(1, int(lockout_until - now))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Demasiados intentos de login. Intente de nuevo en {retry_secs} segundos.",
                    headers={"Retry-After": str(retry_secs)},
                )
            _login_attempts.pop(client_ip, None)


def _record_attempt(client_ip: str):
    """Registra un intento fallido de login."""
    with _lock:
        if client_ip not in _login_attempts:
            _login_attempts[client_ip] = deque()
        _login_attempts[client_ip].append(time.monotonic())

        if len(_login_attempts) > _MAX_TRACKED_IPS:
            sorted_ips = sorted(
                _login_attempts.items(),
                key=lambda x: x[1][-1] if x[1] else 0,
            )
            for ip, _ in sorted_ips[: len(sorted_ips) // 2]:
                del _login_attempts[ip]


def _clear_attempts(client_ip: str):
    """Limpia intentos de un IP (login exitoso)."""
    with _lock:
        _login_attempts.pop(client_ip, None)


# ────────────────────────────────────────────────────────────
#  Registrar usuario — solo admin (Fase 2 — Bug 2.1)
# ────────────────────────────────────────────────────────────
@router.post("/register")
def register_user(
    data: UserRegister,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="El usuario ya existe")

    hashed_pw = hash_password(data.password)
    new_user = User(
        username=data.username,
        password=hashed_pw,
        full_name=data.full_name,
        role=data.role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Usuario creado con éxito", "user": new_user.username}


# ────────────────────────────────────────────────────────────
#  Login con rate limiting (Fase 2 — Bug 2.2)
# ────────────────────────────────────────────────────────────
@router.post("/login")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    user = db.query(User).filter(User.username == form_data.username).first()

    # ── FASE 2 — Fix 2.2: Timing-safe login ──
    # Si el usuario no existe, igual ejecutamos verify_password contra un
    # hash dummy para que el tiempo de respuesta sea idéntico al de un
    # usuario válido con contraseña incorrecta. Esto previene enumeración
    # de usuarios por timing.
    _DUMMY_HASH = "$2b$12$LJ3m4ys3Lg3do11FkN7JpOX5Z5z6ByEpXoMxMKq/MOZV.V8lRS5Dq"
    if not user:
        verify_password(form_data.password, _DUMMY_HASH)
        _record_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    if not verify_password(form_data.password, user.password):
        _record_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    # ── FASE 2 — Fix 2.3: Rechazar usuarios desactivados en login ──
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta desactivada. Contacte al administrador.",
        )

    # Login exitoso: limpiar intentos de este IP
    _clear_attempts(client_ip)

    token = create_access_token({"sub": user.username, "role": user.role})
    refresh = create_refresh_token({"sub": user.username, "role": user.role})
    return {
        "access_token": token,
        "refresh_token": refresh,
        "token_type": "bearer",
    }


# ────────────────────────────────────────────────────────────
#  Refresh token (Fase 2 — Bug 2.3)
# ────────────────────────────────────────────────────────────
@router.post("/refresh")
def refresh_token(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Recibe un refresh_token y devuelve un nuevo access_token."""
    data = _decode_token(payload.refresh_token)
    if not data or data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Refresh token inválido o expirado")

    username = data.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")

    # ── FASE 2 — Fix 2.3: Rechazar refresh si usuario fue desactivado ──
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta desactivada. Contacte al administrador.",
        )

    # ── FASE 3 — Fix 3.3: Verificar que el refresh token no fue revocado ──
    if user.token_revoked_at:
        token_iat = data.get("iat")
        if token_iat:
            from datetime import timezone as _tz
            iat_dt = datetime.fromtimestamp(token_iat, tz=_tz.utc)
            revoked_dt = user.token_revoked_at
            if revoked_dt.tzinfo is None:
                revoked_dt = revoked_dt.replace(tzinfo=_tz.utc)
            if iat_dt < revoked_dt:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token revocado. Inicie sesión nuevamente.",
                )

    new_access = create_access_token({"sub": user.username, "role": user.role})
    return {"access_token": new_access, "token_type": "bearer"}


# ── FASE 3 — Fix 3.1: /me ahora usa get_current_user centralizado ──
@router.get("/me")
def get_profile(current_user: User = Depends(get_current_user)):
    return {
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "permissions": current_user.get_permissions(),
    }


# ════════════════════════════════════════════════════════════
#  CRUD de usuarios — solo admin
# ════════════════════════════════════════════════════════════

@router.get("/")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Lista todos los usuarios del sistema."""
    users = db.query(User).order_by(User.id).all()
    return [UserOut.from_user(u) for u in users]


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Obtiene un usuario por ID."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return UserOut.from_user(user)


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Actualiza un usuario existente."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Validar username único si se está cambiando
    if data.username and data.username != user.username:
        exists = db.query(User).filter(User.username == data.username).first()
        if exists:
            raise HTTPException(status_code=400, detail="Ese nombre de usuario ya existe")
        user.username = data.username

    if data.full_name is not None:
        user.full_name = data.full_name

    if data.role is not None:
        # Protección: no permitir quitarse el rol admin a sí mismo si es el último admin
        if user.id == current_user.id and data.role != "admin":
            admin_count = db.query(User).filter(
                User.role == "admin", User.is_active == True
            ).count()
            if admin_count <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="No se puede quitar el rol admin al único administrador activo",
                )
        user.role = data.role

    if data.is_active is not None:
        # Protección: no desactivarse a sí mismo
        if user.id == current_user.id and not data.is_active:
            raise HTTPException(
                status_code=400,
                detail="No se puede desactivar su propia cuenta",
            )
        user.is_active = data.is_active
        # ── FASE 3 — Fix 3.3: Revocar tokens al desactivar ──
        if not data.is_active:
            from app.utils.dt import utcnow as _utcnow
            user.token_revoked_at = _utcnow()
            logger.info(f"Tokens revocados para usuario '{user.username}' (desactivado)")

    if data.password:
        user.password = hash_password(data.password)
        # ── FASE 3 — Fix 3.3: Revocar tokens al cambiar password ──
        from app.utils.dt import utcnow as _utcnow
        user.token_revoked_at = _utcnow()
        logger.info(f"Tokens revocados para usuario '{user.username}' (cambio de password)")

    db.commit()
    db.refresh(user)
    return UserOut.from_user(user)


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Elimina un usuario del sistema."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # No permitir eliminarse a sí mismo
    if user.id == current_user.id:
        raise HTTPException(
            status_code=400, detail="No se puede eliminar su propia cuenta"
        )

    # No permitir eliminar al último admin activo
    if user.role == "admin":
        admin_count = db.query(User).filter(
            User.role == "admin", User.is_active == True
        ).count()
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="No se puede eliminar al único administrador activo",
            )

    db.delete(user)
    db.commit()
    return {"message": f"Usuario '{user.username}' eliminado"}


# ════════════════════════════════════════════════════════════
#  Permisos granulares
# ════════════════════════════════════════════════════════════

@router.get("/permissions/available")
def get_available_permissions(
    current_user: User = Depends(require_role("admin")),
):
    """Retorna todos los permisos disponibles y los defaults por rol."""
    return {
        "all_permissions": ALL_PERMISSIONS,
        "default_permissions": DEFAULT_PERMISSIONS,
    }


@router.put("/{user_id}/permissions", response_model=UserOut)
def update_user_permissions(
    user_id: int,
    data: PermissionsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Actualiza los permisos de un usuario específico."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if user.role == "admin":
        raise HTTPException(
            status_code=400,
            detail="Los administradores siempre tienen todos los permisos",
        )

    # Validar que todos los permisos sean válidos
    invalid = [p for p in data.permissions if p not in ALL_PERMISSIONS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Permisos inválidos: {', '.join(invalid)}",
        )

    user.set_permissions(data.permissions)
    db.commit()
    db.refresh(user)
    return UserOut.from_user(user)


@router.post("/{user_id}/permissions/reset", response_model=UserOut)
def reset_user_permissions(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Restaura los permisos de un usuario a los defaults de su rol."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    user.permissions = None  # Al ser None, get_permissions() usa los defaults
    db.commit()
    db.refresh(user)
    return UserOut.from_user(user)