from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models.user import User
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token as _decode_token
# ── FASE 3 — Fix 3.1: Fuente única para auth ──
from app.core.dependencies import get_current_user, require_role
from fastapi.security import OAuth2PasswordRequestForm
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional


# ── Schemas de validación (Fase 8 — Bug 8.2) ─────────────
class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    # ── FASE 1 — Fix 1.3: Password mínimo 8 caracteres ──
    password: str = Field(..., min_length=8, max_length=255)
    full_name: Optional[str] = Field(None, max_length=150)
    role: str = Field("vendedor", pattern=r"^(admin|vendedor|cajero)$")


class RefreshTokenRequest(BaseModel):
    refresh_token: str

router = APIRouter(
    prefix="/users",
    tags=["Usuarios"]
)

# ────────────────────────────────────────────────────────────
#  Rate limiter en memoria para login (Fase 2 — Bug 2.2)
# ── FASE 4 — Fix 4.3: Limpieza periódica + tope de IPs ──
# ────────────────────────────────────────────────────────────
_login_attempts: dict[str, list[datetime]] = defaultdict(list)
LOGIN_MAX_ATTEMPTS = 5          # intentos permitidos
LOGIN_WINDOW_SECONDS = 300      # ventana de 5 minutos
LOGIN_LOCKOUT_SECONDS = 600     # bloqueo de 10 minutos tras exceder
_MAX_TRACKED_IPS = 10_000       # tope de IPs en memoria
_last_cleanup = datetime.utcnow()
_CLEANUP_INTERVAL_SECONDS = 600  # limpiar cada 10 minutos


def _cleanup_stale_entries():
    """Elimina IPs cuyos intentos ya expiraron. Se invoca periódicamente."""
    global _last_cleanup
    now = datetime.utcnow()
    if (now - _last_cleanup).total_seconds() < _CLEANUP_INTERVAL_SECONDS:
        return
    _last_cleanup = now

    cutoff = now - timedelta(seconds=LOGIN_LOCKOUT_SECONDS)
    stale_ips = [
        ip for ip, timestamps in _login_attempts.items()
        if not timestamps or timestamps[-1] < cutoff
    ]
    for ip in stale_ips:
        del _login_attempts[ip]


def _check_rate_limit(client_ip: str):
    """Lanza HTTPException 429 si el IP excedió los intentos permitidos."""
    # Limpieza periódica para evitar memory leak
    _cleanup_stale_entries()

    now = datetime.utcnow()
    window_start = now - timedelta(seconds=LOGIN_WINDOW_SECONDS)

    # Limpiar intentos viejos de este IP
    _login_attempts[client_ip] = [
        ts for ts in _login_attempts[client_ip] if ts > window_start
    ]

    if len(_login_attempts[client_ip]) >= LOGIN_MAX_ATTEMPTS:
        oldest_in_window = _login_attempts[client_ip][0]
        lockout_until = oldest_in_window + timedelta(seconds=LOGIN_LOCKOUT_SECONDS)
        if now < lockout_until:
            retry_secs = int((lockout_until - now).total_seconds())
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Demasiados intentos de login. Intente de nuevo en {retry_secs} segundos.",
                headers={"Retry-After": str(retry_secs)},
            )
        _login_attempts[client_ip].clear()


def _record_attempt(client_ip: str):
    """Registra un intento fallido."""
    # Si llegamos al tope de IPs, forzar limpieza agresiva
    if len(_login_attempts) >= _MAX_TRACKED_IPS:
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=LOGIN_LOCKOUT_SECONDS)
        stale_ips = [
            ip for ip, timestamps in _login_attempts.items()
            if not timestamps or timestamps[-1] < cutoff
        ]
        for ip in stale_ips:
            del _login_attempts[ip]

        # Si aún estamos llenos, descartar la mitad más vieja
        if len(_login_attempts) >= _MAX_TRACKED_IPS:
            sorted_ips = sorted(
                _login_attempts.items(),
                key=lambda x: x[1][-1] if x[1] else datetime.min
            )
            for ip, _ in sorted_ips[:len(sorted_ips) // 2]:
                del _login_attempts[ip]

    _login_attempts[client_ip].append(datetime.utcnow())


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
    if not user or not verify_password(form_data.password, user.password):
        _record_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    # Login exitoso: limpiar intentos de este IP
    _login_attempts.pop(client_ip, None)

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

    new_access = create_access_token({"sub": user.username, "role": user.role})
    return {"access_token": new_access, "token_type": "bearer"}


# ── FASE 3 — Fix 3.1: /me ahora usa get_current_user centralizado ──
@router.get("/me")
def get_profile(current_user: User = Depends(get_current_user)):
    return {
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role,
    }