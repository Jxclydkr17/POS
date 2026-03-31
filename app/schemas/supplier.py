# app/schemas/supplier.py
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Annotated, Optional, List
from datetime import datetime
from datetime import date
from decimal import Decimal


# ============================================================
# 🔹 BASE
# ============================================================
class SupplierBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    email: Optional[EmailStr] = None
    phone: Annotated[Optional[str], Field(min_length=8, max_length=20)] = None
    address: Annotated[Optional[str], Field(max_length=300)] = None
    notes: Annotated[Optional[str], Field(max_length=2000)] = None

    model_config = ConfigDict(from_attributes=True)
    is_active: bool = True
    contact_name: Annotated[Optional[str], Field(max_length=120)] = None
    contact_phone: Annotated[Optional[str], Field(max_length=30)] = None
    contact_position: Annotated[Optional[str], Field(max_length=80)] = None


# ============================================================
# 🔹 CREATE
# ============================================================
class SupplierCreate(SupplierBase):
    pass


# ============================================================
# 🔹 UPDATE
# ============================================================
class SupplierUpdate(BaseModel):
    name: Annotated[Optional[str], Field(min_length=2, max_length=200)] = None
    email: Optional[EmailStr] = None
    phone: Annotated[Optional[str], Field(min_length=8, max_length=20)] = None
    address: Annotated[Optional[str], Field(max_length=300)] = None
    notes: Annotated[Optional[str], Field(max_length=2000)] = None

    model_config = ConfigDict(from_attributes=True)
    is_active: Optional[bool] = None
    contact_name: Annotated[Optional[str], Field(max_length=120)] = None
    contact_phone: Annotated[Optional[str], Field(max_length=30)] = None
    contact_position: Annotated[Optional[str], Field(max_length=80)] = None


# ============================================================
# 🔹 OUT
# ============================================================
class SupplierOut(SupplierBase):
    id: int
    created_at: datetime

     # Métricas
    products_count: int = 0
    critical_products_count: int = 0
    purchases_count: int = 0
    total_purchased: Decimal = Decimal("0")
    last_purchase_date: Optional[date] = None

    days_since_last_purchase: Optional[int] = None
    rotation_units: int = 0
    ranking_score: float = 0.0
    supplier_score: int = 0
    supplier_rank: str = ""

    dependency_pct: float = 0.0
    avg_days_between_purchases: int | None = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 🔹 PAGINATED LIST RESPONSE  (#9)
# ============================================================
class SupplierListResponse(BaseModel):
    items: List[SupplierOut]
    total: int
    skip: int
    limit: int

    model_config = ConfigDict(from_attributes=True)