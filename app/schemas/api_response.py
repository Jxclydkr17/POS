from pydantic import BaseModel, ConfigDict
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    message: str
    data: Optional[T] = None
    # ✅ Paso 10 — total de registros para paginación (None = endpoint sin paginación)
    total: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)