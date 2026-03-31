# app/schemas/economic_activity.py
from typing import Optional
from pydantic import BaseModel, ConfigDict

class EconomicActivityOut(BaseModel):
    code: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
