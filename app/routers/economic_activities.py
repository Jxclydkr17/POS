"""
app/routers/economic_activities.py — Endpoints de actividades económicas

Endpoints:
  GET  /economic-activities/search?q=  → Búsqueda por código o descripción
  POST /economic-activities/import     → Reimportar desde CSV (solo admin)

AUDITORÍA FIX 2.2: Agregado escape_like en búsqueda.
AUDITORÍA FIX 5.1: Agregado endpoint de reimportación.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.db.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.db.models.economic_activity import EconomicActivity
from app.schemas.api_response import APIResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/economic-activities", tags=["Economic Activities"])


@router.get("/search")
def search(
    q: str,
    limit: int = 25,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    q = (q or "").strip()
    if not q:
        return []

    from app.utils.db_compat import escape_like
    safe = escape_like(q)

    rows = (
        db.query(EconomicActivity)
        .filter(or_(
            EconomicActivity.code.ilike(f"%{safe}%"),
            EconomicActivity.description.ilike(f"%{safe}%"),
        ))
        .order_by(EconomicActivity.code.asc())
        .limit(min(limit, 50))
        .all()
    )

    return [{"code": r.code, "description": r.description} for r in rows]


@router.post("/import", response_model=APIResponse)
def import_economic_activities(
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    """
    Reimporta las actividades económicas desde el CSV de Hacienda.
    Útil si se actualiza el catálogo o si la tabla quedó vacía.
    Solo accesible para administradores.
    """
    try:
        from app.scripts.import_economic_activities import run as import_activities
        import_activities(db=db)

        total = db.query(EconomicActivity).count()
        return APIResponse(
            message=f"Actividades económicas importadas correctamente ({total} registros).",
        )

    except Exception as e:
        logger.error(f"Error importando actividades económicas: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al importar actividades económicas: {str(e)}",
        )