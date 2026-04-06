from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models.user import User
from app.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Obtiene el usuario autenticado desde el token JWT"""
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado"
        )

    # ── FASE 1 — Fix 1.2: Rechazar refresh tokens usados como access ──
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tipo de token inválido. Use un access token."
        )

    username = payload.get("sub")
    if username is None:
        raise HTTPException(status_code=401, detail="Token inválido")

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return user

def require_role(role: str):
    """Devuelve una dependencia que permite solo a usuarios con cierto rol"""
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role != role and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permiso denegado. Se requiere rol '{role}' o 'admin'."
            )
        return current_user
    return role_checker


def require_permission(perm: str):
    """Devuelve una dependencia que verifica un permiso granular."""
    def perm_checker(current_user: User = Depends(get_current_user)):
        if not current_user.has_permission(perm):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No tiene el permiso '{perm}'."
            )
        return current_user
    return perm_checker