# app/schemas/credit.py

from pydantic import BaseModel, field_validator
from typing import Optional
from app.constants.payment_methods import ALL_PAYMENT_METHODS


# ----------- Payment Input -----------
class CreditPaymentCreate(BaseModel):
    amount: float
    payment_method: str = "Efectivo"  # 🆕 Ahora es obligatorio con default

    @field_validator("amount")
    def validate_amount(cls, value):
        if value <= 0:
            raise ValueError("El monto debe ser mayor a cero.")
        return value

    @field_validator("payment_method")
    def validate_method(cls, value):
        if value not in ALL_PAYMENT_METHODS:
            raise ValueError(f"Método de pago inválido. Debe ser uno de: {', '.join(ALL_PAYMENT_METHODS)}")
        return value

    model_config = {"from_attributes": True}


# ----------- Credit Movement Output -----------
class CreditMovement(BaseModel):
    id: int
    amount: float
    type: str
    payment_method: Optional[str] = None  # 🆕
    description: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}


# ----------- Credit Summary Output -----------
class CreditSummary(BaseModel):
    customer: dict
    balance: float
    movements: list
    credit_sales: list

    model_config = {"from_attributes": True}
