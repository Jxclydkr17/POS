from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List

from app.db.database import get_db
from app.db.models.cabys import Cabys
from app.schemas.cabys import CabysOut
from app.schemas.api_response import APIResponse
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/cabys", tags=["CABYS"])


# -------------------------------------------------------
# 🔍 Buscar CABYS por texto (nombre o código)
# -------------------------------------------------------
@router.get("/search", response_model=APIResponse[List[CabysOut]])
def search_cabys(
    q: str = Query(..., min_length=3),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    from app.utils.db_compat import escape_like
    safe = escape_like(q)
    results = (
        db.query(Cabys)
        .filter(
            or_(
                Cabys.description.ilike(f"%{safe}%"),
                Cabys.code.ilike(f"%{safe}%")
            )
        )
        .limit(20)
        .all()
    )

    return APIResponse(
        message="Resultados CABYS cargados correctamente",
        data=results
    )