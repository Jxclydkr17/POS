from pydantic import BaseModel, field_validator, Field
from typing import Annotated, Optional
from datetime import date
from app.constants.payment_methods import ALL_PAYMENT_METHODS


class ExpenseCreate(BaseModel):
    category: str = Field(min_length=2, max_length=100)
    description: Annotated[Optional[str], Field(max_length=300)] = None
    amount: float = Field(gt=0)
    payment_method: str
    date: Optional[date] = None

    @field_validator("payment_method")
    def validate_payment_method(cls, value):
        if value not in ALL_PAYMENT_METHODS:
            raise ValueError(
                f"Método de pago inválido. Debe ser uno de: {', '.join(ALL_PAYMENT_METHODS)}"
            )
        return value

    @field_validator("category")
    def category_not_empty(cls, value):
        if not value.strip():
            raise ValueError("La categoría no puede estar vacía.")
        return value


class ExpenseUpdate(BaseModel):
    """Schema para editar un gasto existente. Todos los campos son opcionales."""
    category: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Annotated[Optional[str], Field(max_length=300)] = None
    amount: Optional[float] = Field(None, gt=0)
    payment_method: Optional[str] = None

    @field_validator("payment_method")
    def validate_payment_method(cls, value):
        if value is not None and value not in ALL_PAYMENT_METHODS:
            raise ValueError(
                f"Método de pago inválido. Debe ser uno de: {', '.join(ALL_PAYMENT_METHODS)}"
            )
        return value

    @field_validator("category")
    def category_not_empty(cls, value):
        if value is not None and not value.strip():
            raise ValueError("La categoría no puede estar vacía.")
        return value