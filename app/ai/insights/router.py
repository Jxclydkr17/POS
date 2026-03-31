from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.dependencies import get_current_user

from .service import get_today_insights
from .schemas import InsightsResponse

router = APIRouter(
    prefix="/ai/insights",
    tags=["IA - Insights"]
)


@router.get("/today", response_model=InsightsResponse)
def insights_today(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    return get_today_insights(db)
