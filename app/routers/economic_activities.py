from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.core.dependencies import get_current_user
from app.db.models.economic_activity import EconomicActivity
from sqlalchemy import or_

router = APIRouter(prefix="/economic-activities", tags=["Economic Activities"])

@router.get("/search")
def search(q: str, limit: int = 25, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    q = (q or "").strip()
    if not q:
        return []

    rows = (db.query(EconomicActivity)
            .filter(or_(
                EconomicActivity.code.ilike(f"%{q}%"),
                EconomicActivity.description.ilike(f"%{q}%")
            ))
            .order_by(EconomicActivity.code.asc())
            .limit(min(limit, 50))
            .all())

    return [{"code": r.code, "description": r.description} for r in rows]
