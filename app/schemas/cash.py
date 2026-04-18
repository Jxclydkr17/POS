# app/schemas/cash.py

from pydantic import BaseModel, Field, field_validator
from datetime import date
from typing import Optional, Literal


# ============================================================
# 🟦 CASH SESSION - INPUT
# ============================================================

class CashSessionCreate(BaseModel):
    opening_amount: float = Field(gt=0, description="Monto inicial en caja")
    terminal_id: str = Field(default="T1", max_length=10, description="Identificador de terminal/caja")

    @field_validator("opening_amount")
    def validate_opening(cls, value):
        if value < 0:
            raise ValueError("El monto de apertura no puede ser negativo.")
        return value


# ============================================================
# 🟩 CASH SESSION - OUTPUT
# ============================================================

class CashSessionOut(BaseModel):
    id: int
    date: date
    terminal_id: str = "T1"
    opening_amount: float
    closing_amount: Optional[float] = None
    expected_closing: Optional[float] = None
    difference: Optional[float] = None
    status: str

    model_config = {"from_attributes": True}


# ============================================================
# 🟨 CASH MOVEMENT - INPUT (UNIFICADO)
# ============================================================

class CashMovementCreate(BaseModel):
    type: Literal["in", "out"]
    concept: str = Field(min_length=3, max_length=100)
    amount: float = Field(gt=0)
    source: str = "manual"  # ✅ Campo obligatorio con valor por defecto
    description: Optional[str] = Field(None, max_length=500)
    reference_id: Optional[int] = None
    
    create_expense: bool = False
    expense_category: Optional[str] = Field(None, max_length=100)

    @field_validator("concept")
    def validate_concept(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("El concepto debe tener al menos 3 caracteres.")
        return value

    @field_validator("expense_category")
    def validate_expense_category(cls, value, values):
        if values.data.get("create_expense") and not value:
            raise ValueError("Debe indicar categoría si create_expense=True.")
        return value


# ============================================================
# 🟥 CASH CLOSE - INPUT
# ============================================================

class CashCloseSchema(BaseModel):
    closing_amount: float = Field(gt=0, description="Efectivo contado al cierre")

    @field_validator("closing_amount")
    def validate_closing(cls, value):
        if value < 0:
            raise ValueError("El monto de cierre no puede ser negativo.")
        return value