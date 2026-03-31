# app/schemas/customer.py

from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator
from typing import Annotated, Optional
from datetime import datetime, date
from typing import Annotated, List
from enum import Enum

from app.schemas.economic_activity import EconomicActivityOut


# ============================================================
# 🔹 Enum de tipos de cliente
# ============================================================
class CustomerTypeEnum(str, Enum):
    normal = "Normal"
    mayorista = "Mayorista"
    vip = "VIP"
    exento = "Exento"
    corporativo = "Corporativo"


# ============================================================
# 🟦 BASE
# ============================================================
class CustomerBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    phone: Annotated[Optional[str], Field(max_length=20)] = None
    secondary_phone: Annotated[Optional[str], Field(max_length=20)] = None
    address: Annotated[Optional[str], Field(max_length=200)] = None

    id_type: Optional[str] = Field(default="Física")  
    id_number: Optional[str] = None

    customer_type: CustomerTypeEnum = Field(default=CustomerTypeEnum.normal)
    
    credit_limit: float = Field(default=0.0, ge=0)
    has_credit_limit: bool = Field(default=False)

    notes: Annotated[Optional[str], Field(max_length=2000)] = None
    birth_date: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)
    
    province_id: Optional[str] = None
    province_name: Optional[str] = None
    canton_id: Optional[str] = None
    canton_name: Optional[str] = None
    district_id: Optional[str] = None
    district_name: Optional[str] = None
    neighborhood: Optional[str] = None

    # actividades (múltiples)
    economic_activity_codes: List[str] = Field(default_factory=list)


# ============================================================
# 🟩 CREATE
# ============================================================
class CustomerCreate(CustomerBase):
    pass


# ============================================================
# 🟧 UPDATE
# ============================================================
class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    secondary_phone: Optional[str] = None
    address: Optional[str] = None

    id_type: Optional[str] = None
    id_number: Optional[str] = None
    customer_type: Optional[CustomerTypeEnum] = None
    credit_limit: Optional[float] = None
    has_credit_limit: Optional[bool] = None

    notes: Optional[str] = None
    birth_date: Optional[date] = None
    
    economic_activity_codes: Optional[List[str]] = None
    province_id: Optional[str] = None
    province_name: Optional[str] = None
    canton_id: Optional[str] = None
    canton_name: Optional[str] = None
    district_id: Optional[str] = None
    district_name: Optional[str] = None
    neighborhood: Optional[str] = None


# ============================================================
# 🟥 OUT
# ============================================================
class CustomerOut(CustomerBase):
    id: int
    credit_balance: float = 0.0
    is_active: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime] = None
    credit_limit: float = 0.0
    has_credit_limit: bool = False
    last_purchase_date: Optional[datetime] = None

    # ✅ relación que sí existe en el ORM: customer.economic_activities
    economic_activities: List[EconomicActivityOut] = Field(default_factory=list)
