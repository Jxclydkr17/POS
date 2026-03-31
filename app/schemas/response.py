# app/schemas/response.py

from pydantic import BaseModel
from typing import Optional, Any


class APIResponse(BaseModel):
    """
    Respuesta estándar para toda la API del POS.

    success : bool   → indica si la operación fue exitosa
    message : str    → mensaje amigable para el usuario
    data    : dict   → payload de datos
    error   : dict   → detalles del error (solo si success=False)
    """

    success: bool = True
    message: Optional[str] = None
    data: Optional[Any] = None
    error: Optional[Any] = None

    model_config = {"from_attributes": True}
