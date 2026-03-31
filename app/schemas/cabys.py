from pydantic import BaseModel, Field, ConfigDict

class CabysOut(BaseModel):
    code: str = Field(..., description="Código CABYS")
    description: str = Field(..., description="Descripción del bien o servicio")
    iva: int = Field(..., description="IVA aplicado")

    model_config = ConfigDict(from_attributes=True)
