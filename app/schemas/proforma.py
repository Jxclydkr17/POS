# app/schemas/proforma.py
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime
from decimal import Decimal

from app.schemas.sale import SaleItemCreate


# ============================================================
# 🟧 Crear proforma
# ============================================================
class ProformaCreate(BaseModel):
    customer_id: Optional[int] = Field(
        None,
        description="ID del cliente (opcional)"
    )
    details: List[SaleItemCreate] = Field(
        ...,
        description="Lista de productos cotizados (mismo formato que venta)"
    )
    notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Notas libres del vendedor"
    )
    validity_days: int = Field(
        default=15,
        ge=1,
        le=365,
        description="Días de vigencia de la proforma"
    )


# ============================================================
# 🟦 Editar proforma (libre, sin restricciones de Hacienda)
# ============================================================
class ProformaUpdate(BaseModel):
    customer_id: Optional[int] = Field(
        None,
        description="ID del cliente (opcional)"
    )
    details: List[SaleItemCreate] = Field(
        ...,
        description="Nueva lista de productos (reemplaza líneas existentes)"
    )
    notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Notas libres del vendedor"
    )
    validity_days: Optional[int] = Field(
        None,
        ge=1,
        le=365,
        description="Nuevos días de vigencia (recalcula valid_until desde hoy)"
    )


# ============================================================
# 🟨 Respuesta: Detalle de línea
# ============================================================
class ProformaDetailOut(BaseModel):
    product_id: Optional[int] = None

    # 📏 Cantidad — ahora Decimal para reflejar fracciones (kg, m, L)
    quantity: Decimal

    unit_price: float
    subtotal: float
    discount_percent: float
    tax_rate: Optional[float] = 0
    tax_amount: Optional[float] = 0
    is_common: bool = False
    common_description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 🟥 Respuesta: Proforma completa
# ============================================================
class ProformaOut(BaseModel):
    id: int
    customer_id: Optional[int]
    user_id: Optional[int] = None
    number: str
    status: str
    total: float
    notes: Optional[str] = None
    validity_days: int
    valid_until: datetime
    converted_sale_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    details: List[ProformaDetailOut]

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 🟪 Respuesta para listados
# ============================================================
class ProformaListOut(BaseModel):
    id: int
    customer_id: Optional[int]
    user_id: Optional[int] = None
    number: str
    status: str
    total: float
    notes: Optional[str] = None
    validity_days: int
    valid_until: datetime
    converted_sale_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 📄 Respuesta paginada
# ============================================================
class PaginatedProformasResponse(BaseModel):
    data: List[ProformaListOut]
    total_count: int
    page: int
    page_size: int
    total_pages: int


# ============================================================
# 🔄 Solicitud de conversión a venta
# ============================================================
class ProformaConvertRequest(BaseModel):
    payment_method: str = Field(
        default="Efectivo",
        description="Método de pago para la venta resultante"
    )
    document_type: str = Field(
        default="04",
        description="Tipo de documento: '04' Tiquete, '01' Factura"
    )
    credit_days: Optional[int] = Field(
        None,
        description="Días de crédito (solo si pago es Crédito)"
    )
    condicion_venta_code: Optional[str] = Field(
        None,
        description="Código CondicionVenta (ej: '01' contado, '02' crédito)"
    )