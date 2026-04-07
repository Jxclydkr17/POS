# app/schemas/sale.py
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import List, Optional, Generic, TypeVar
from datetime import datetime
from decimal import Decimal

from app.constants.payment_methods import ALL_PAYMENT_METHODS


# ─── Helper: set normalizado para validación case-insensitive ───
_VALID_PM_LOWER = {m.strip().lower() for m in ALL_PAYMENT_METHODS}


# ============================================================
# 🟦 BASE: Item de venta (producto dentro del carrito)
# ============================================================
class SaleItemBase(BaseModel):
    product_id: Optional[int] = Field(
        default=None,
        description="ID del producto vendido (None si es producto común)"
    )

    # 📏 Cantidad — ahora Decimal para soportar fracciones (0.5 kg, 1.75 m)
    quantity: Decimal = Field(..., gt=0, description="Cantidad vendida (acepta decimales para kg, m, L)")

    unit_price: float = Field(..., gt=0, description="Precio unitario del producto")
    discount_percent: Optional[float] = Field(
        default=0,
        ge=0,
        le=100,
        description="Descuento aplicado al ítem (%)"
    )

    # ✅ PRODUCTO COMÚN: línea sin inventario
    is_common: bool = Field(
        default=False,
        description="True si es producto común (no toca inventario)"
    )
    common_description: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Descripción libre del producto común"
    )

    # ── FASE 3 — Fix 3.1: IVA para productos comunes ──
    # Para productos normales se toma del catálogo (Product.tax_rate).
    # Para productos comunes, el frontend DEBE enviar la tasa de IVA.
    tax_rate: Optional[float] = Field(
        default=0,
        ge=0,
        le=100,
        description="Tasa de IVA (%). Obligatorio para productos comunes con impuesto."
    )

    @model_validator(mode="after")
    def validate_common_vs_product(self):
        """Si NO es común, product_id es obligatorio. Si ES común, common_description es obligatoria."""
        if self.is_common:
            if not self.common_description or not self.common_description.strip():
                raise ValueError("common_description es obligatoria para productos comunes.")
        else:
            if self.product_id is None:
                raise ValueError("product_id es obligatorio para productos normales.")
        return self


# ============================================================
# 🟩 Crear ítem (entrada proveniente del frontend)
# ============================================================
class SaleItemCreate(SaleItemBase):
    pass


# ============================================================
# 🟧 Crear venta completa
# ============================================================
class SaleCreate(BaseModel):
    customer_id: Optional[int] = Field(
        None,
        description="ID del cliente (opcional si es venta general)"
    )
    payment_method: str = Field(
        default="Efectivo",
        description="Método de pago (Efectivo, Tarjeta, Transferencia, SINPE, Crédito)"
    )
    document_type: str = Field(
        default="04",
        description="Tipo de documento: '04' Tiquete Electrónico, '01' Factura Electrónica"
    )
    details: List[SaleItemCreate] = Field(
        ...,
        description="Lista de productos vendidos"
    )
    credit_days: Optional[int] = None
    condicion_venta_code: Optional[str] = Field(
        default=None,
        description="Código CondicionVenta (opcional). Ej: '01' contado, '02' crédito, '10' crédito IVA 90 días."
    )

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, v: str) -> str:
        normalized = (v or "").strip()
        if not normalized:
            raise ValueError("payment_method no puede estar vacío.")
        if normalized.lower() not in _VALID_PM_LOWER:
            allowed = ", ".join(ALL_PAYMENT_METHODS)
            raise ValueError(
                f"Método de pago '{normalized}' no es válido. "
                f"Valores permitidos: {allowed}"
            )
        for canonical in ALL_PAYMENT_METHODS:
            if canonical.strip().lower() == normalized.lower():
                return canonical
        return normalized


# ============================================================
# ✅ FASE 3.3: Edición de venta (solo en estado PENDING)
# ============================================================
class SaleUpdate(BaseModel):
    """
    Payload para editar una venta antes de envío a Hacienda.
    Solo se pueden modificar los detalles (líneas).
    """
    details: List[SaleItemCreate] = Field(
        ...,
        description="Nueva lista de productos vendidos (reemplaza las líneas existentes)"
    )


# ============================================================
# ✅ FASE 3.1: Solicitud de anulación / nota de crédito
# ============================================================
class SaleCancelRequest(BaseModel):
    razon: str = Field(
        default="Anulación de comprobante",
        max_length=180,
        description="Razón de la anulación (se incluye en la nota de crédito)"
    )


# ============================================================
# 🟨 Respuesta: Detalle de venta para GET /sales/{id}
# ============================================================
class SaleDetailOut(BaseModel):
    product_id: Optional[int] = None

    # 📏 Cantidad — ahora Decimal para reflejar fracciones
    quantity: Decimal

    unit_price: float
    subtotal: float
    discount_percent: float
    tax_rate: Optional[float] = 0
    tax_amount: Optional[float] = 0

    # ✅ PRODUCTO COMÚN
    is_common: bool = False
    common_description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 🟥 Respuesta: Venta completa para GET /sales/{id}
# ============================================================
class SaleOut(BaseModel):
    id: int
    customer_id: Optional[int]
    user_id: Optional[int] = None       # ✅ FASE 3.2
    total: float
    payment_method: str
    document_type: str
    status: str
    created_at: datetime
    details: List[SaleDetailOut]

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 🟪 Respuesta para listados (GET /sales)
# ============================================================
class SaleListOut(BaseModel):
    id: int
    customer_id: Optional[int]
    user_id: Optional[int] = None       # ✅ FASE 3.2
    total: float
    payment_method: str
    document_type: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# ✅ FASE 3.4: Respuesta paginada genérica
# ── FASE 4 — Fix 4.2: has_next en vez de COUNT(*) obligatorio ──
# total_count y total_pages ahora son opcionales. El frontend puede
# paginar con has_next sin necesidad de un COUNT en cada request.
# ============================================================
class PaginatedSalesResponse(BaseModel):
    """Wrapper de respuesta paginada para GET /sales/."""
    data: List[SaleListOut]
    page: int
    page_size: int
    has_next: bool = False
    total_count: Optional[int] = None
    total_pages: Optional[int] = None