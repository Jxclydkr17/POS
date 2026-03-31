from pydantic import BaseModel
from typing import List, Optional, Literal, Dict, Any


InsightLevel = Literal["info", "warning", "critical"]
InsightType = Literal["sales", "stock", "cash", "credit", "kpi", "supplier"]


class Insight(BaseModel):
    type: InsightType
    level: InsightLevel
    message: str
    reference: Optional[str] = None  # ej: product_id, customer_id
    meta: Optional[Dict[str, Any]] = None  # 🆕 datos adicionales (ej: suggested_qty)

class InsightsResponse(BaseModel):
    summary: str
    alerts: List[Insight]
