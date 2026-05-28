# app/schemas/purchase.py

from datetime import date as _Date, datetime as _DateTime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Optional, List

from pydantic import BaseModel, Field, ConfigDict


# ============================================================
# 🔹 Estados de la compra
# ============================================================
class PurchaseStatus(str, Enum):
    pendiente = "pendiente"
    recibido  = "recibido"
    parcial   = "parcial"
    pagado    = "pagado"
    vencido   = "vencido"


# ============================================================
# 🔹 Línea de detalle — entrada
# ============================================================
class PurchaseItemCreate(BaseModel):
    product_id: int = Field(..., gt=0)

    # 📏 Cantidad — Decimal para soportar fracciones (kg, m, L)
    quantity: Decimal = Field(..., gt=0)

    unit_cost: float = Field(..., ge=0)

    # ── Descuento por línea (facturación electrónica CR V4.4) ──
    # Se aplica sobre el subtotal bruto ANTES de calcular el IVA.
    # El backend recalcula los montos para garantizar consistencia.
    discount_pct:    float = Field(default=0.0, ge=0.0, le=100.0,
                                   description="Porcentaje de descuento (0–100)")
    discount_amount: float = Field(default=0.0, ge=0.0,
                                   description="Monto del descuento en colones")

    # ── IVA por línea ──
    iva_pct:    int   = Field(default=13, ge=0, le=100,
                              description="Tarifa de IVA aplicada (0, 1, 2, 4, 8 ó 13)")
    iva_amount: float = Field(default=0.0, ge=0.0,
                              description="Monto de IVA calculado en colones")

    # Total de la línea (neto + IVA) — se almacena para auditoría
    total_line: float = Field(default=0.0, ge=0.0,
                               description="Total de la línea: subtotal_neto + iva_amount")


# ============================================================
# 🔹 Línea de detalle — salida
# ============================================================
class PurchaseItemOut(BaseModel):
    id:          int
    product_id:  int

    # 📏 Cantidad — ahora Decimal
    quantity:    Decimal

    unit_cost:       float
    subtotal:        float        # subtotal_neto (base imponible)
    discount_pct:    float = 0.0
    discount_amount: float = 0.0
    iva_pct:         int   = 13
    iva_amount:      float = 0.0
    total_line:      float = 0.0
    product_name:    Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 🔹 Pago parcial / abono — entrada
# ============================================================
class PurchasePaymentCreate(BaseModel):
    amount: float = Field(..., gt=0, description="Monto del abono")
    payment_method: str = Field(default="Efectivo", max_length=50)
    date: Optional[_Date] = None  # Fecha del pago (default: hoy)
    notes: Optional[str] = None


# ============================================================
# 🔹 Pago parcial / abono — salida
# ============================================================
class PurchasePaymentOut(BaseModel):
    id:             int
    purchase_id:    int
    amount:         float
    payment_method: str
    date:           _Date
    notes:          Optional[str] = None
    created_at:     Optional[_DateTime] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 🔹 Nota de crédito — entrada
# ============================================================
class PurchaseCreditNoteCreate(BaseModel):
    amount: float  = Field(..., gt=0, description="Monto de la nota de crédito")
    reason: str    = Field(..., max_length=500, description="Motivo de la nota de crédito")
    date:   Optional[_Date] = None
    product_id: Optional[int] = None  # Producto a devolver (opcional)

    # 📏 Cantidad devuelta — ahora Decimal para soportar fracciones
    quantity_returned: Decimal = Field(0, ge=0, description="Cantidad devuelta al proveedor")


# ============================================================
# 🔹 Nota de crédito — salida
# ============================================================
class PurchaseCreditNoteOut(BaseModel):
    id:          int
    purchase_id: int
    amount:      float
    reason:      str
    date:        _Date
    product_id:  Optional[int] = None
    product_name: Optional[str] = None

    # 📏 Cantidad devuelta — ahora Decimal
    quantity_returned: Decimal = 0

    stock_reverted: bool = False

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 🔹 BASE
# ============================================================
class PurchaseBase(BaseModel):
    invoice_number: str  = Field(..., max_length=50)
    supplier_id:    int  = Field(..., gt=0)
    entry_date:     _Date
    due_date:       _Date
    amount:         float = Field(..., ge=0)
    status:         Optional[PurchaseStatus] = None
    payment_method: Annotated[Optional[str], Field(max_length=50)]   = None
    notes:          Annotated[Optional[str], Field(max_length=1000)]  = None


# ============================================================
# 🔹 CREATE
# ============================================================
class PurchaseCreate(PurchaseBase):
    items: Optional[List[PurchaseItemCreate]] = None


# ============================================================
# 🔹 UPDATE
# ============================================================
class PurchaseUpdate(BaseModel):
    invoice_number: Annotated[Optional[str],   Field(max_length=50)]  = None
    supplier_id:    Annotated[Optional[int],   Field(gt=0)]           = None
    entry_date:     Optional[_Date]  = None
    due_date:       Optional[_Date]  = None
    amount:         Annotated[Optional[float], Field(ge=0)]           = None
    status:         Optional[PurchaseStatus]   = None
    payment_method: Annotated[Optional[str],   Field(max_length=50)]  = None
    notes:          Annotated[Optional[str],   Field(max_length=1000)] = None
    items:          Optional[List[PurchaseItemCreate]] = None


# ============================================================
# 🔹 UPDATE SOLO ESTADO (legacy — mantener por compatibilidad)
# ============================================================
class PurchasePayIn(BaseModel):
    payment_method: Annotated[Optional[str], Field(max_length=50)] = None


# ============================================================
# 🔹 OUT: detalle completo
# ============================================================
class PurchaseOut(PurchaseBase):
    id:                  int
    status:              PurchaseStatus
    pdf_path:            Optional[str]  = None
    supplier_name:       Optional[str]  = None
    paid_at:             Optional[_Date] = None
    received_at:         Optional[_Date] = None
    items:               List[PurchaseItemOut]        = []
    payments:            List[PurchasePaymentOut]     = []
    credit_notes:        List[PurchaseCreditNoteOut]  = []
    paid_amount:         float = 0.0
    credit_notes_total:  float = 0.0
    balance:             float = 0.0
    notes:               Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 🔹 OUT: listados (tabla)
# ============================================================
class PurchaseListOut(BaseModel):
    id:                  int
    invoice_number:      str
    supplier_id:         int
    supplier_name:       Optional[str]  = None
    amount:              float
    status:              PurchaseStatus
    due_date:            _Date
    entry_date:          _Date
    payment_method:      Optional[str]  = None
    paid_at:             Optional[_Date] = None
    received_at:         Optional[_Date] = None
    items_count:         int   = 0
    paid_amount:         float = 0.0
    credit_notes_total:  float = 0.0
    balance:             float = 0.0
    notes:               Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 🔹 OUT: listado paginado
# ============================================================
class PurchaseListPageOut(BaseModel):
    items: List[PurchaseListOut]
    total: int  = Field(..., ge=0)
    skip:  int  = Field(..., ge=0)
    limit: int  = Field(..., gt=0)


# ============================================================
# 🔹 OUT: últimas compras por proveedor
# ============================================================
class PurchaseRecentOut(BaseModel):
    entry_date: _Date
    amount:     float