from pydantic import BaseModel, Field
from typing import List, Optional

class RepReferenceIn(BaseModel):
    electronic_invoice_id: int = Field(..., description="ID de electronic_invoices")
    amount_applied: Optional[float] = Field(
        default=None,
        gt=0,
        description="Monto aplicado a esta referencia. Si no viene, el backend hace FIFO."
    )

class CreateRepFromPaymentIn(BaseModel):
    references: List[RepReferenceIn] = Field(..., min_length=1)

    condicion_venta_rep: str = Field(default="11", max_length=2, description="REP: solo '09' o '11'")
    codigo_referencia: str = Field(default="01", max_length=2, description="Código de referencia (2 chars)")
    razon_referencia: str = Field(default="Pago registrado", max_length=180, description="Razón de la referencia")

class SuggestRepAllocationsIn(BaseModel):
    amount: float = Field(..., gt=0, description="Monto del abono a distribuir")
    electronic_invoice_ids: Optional[List[int]] = Field(
        default=None,
        description="Opcional: limitar el FIFO a estas facturas/tiquetes (por selección UI). Si no viene, usa todos los pendientes."
    )