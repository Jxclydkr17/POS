"""
app/schemas/settings.py — Schemas de configuración general.

Fase 5: Validaciones y seguridad.
Fase 6: 6.2 Moneda configurable.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
from typing import Annotated, Optional
from datetime import datetime
from decimal import Decimal


# ─────────────────────────────────────────────────────────
# Constantes de validación
# ─────────────────────────────────────────────────────────
ID_TYPE_VALID = {"Física", "Jurídica", "DIMEX"}
ID_TYPE_TO_CODE = {"Física": "01", "Jurídica": "02", "DIMEX": "03"}
CODE_TO_ID_TYPE = {v: k for k, v in ID_TYPE_TO_CODE.items()}

ALLOWED_TAX_VALUES = {"0", "1", "2", "4", "8", "13"}

ID_NUMBER_RULES = {
    "Física":  (9, 9,   "Cédula física debe tener exactamente 9 dígitos"),
    "Jurídica": (10, 10, "Cédula jurídica debe tener exactamente 10 dígitos"),
    "DIMEX":   (11, 12,  "DIMEX debe tener entre 11 y 12 dígitos"),
}

PRINTER_TYPES_VALID = {"network", "usb", "none"}

# 6.2: Monedas soportadas
CURRENCY_VALID = {"CRC", "USD"}


# ─────────────────────────────────────────────────────────
# Validadores reutilizables
# ─────────────────────────────────────────────────────────

def _validate_id_type(v):
    if v is not None and v not in ID_TYPE_VALID:
        raise ValueError(f"id_type debe ser uno de: {', '.join(ID_TYPE_VALID)}")
    return v


def _validate_default_tax(v):
    if v is not None and v not in ALLOWED_TAX_VALUES:
        raise ValueError(f"default_tax debe ser uno de: {', '.join(sorted(ALLOWED_TAX_VALUES))}")
    return v


def _validate_printer_type(v):
    if v is not None and v not in PRINTER_TYPES_VALID:
        raise ValueError(f"printer_type debe ser uno de: {', '.join(PRINTER_TYPES_VALID)}")
    return v


def _validate_currency(v):
    if v is not None and v not in CURRENCY_VALID:
        raise ValueError(f"default_currency debe ser uno de: {', '.join(sorted(CURRENCY_VALID))}")
    return v


# ─────────────────────────────────────────────────────────
# SettingsBase
# ─────────────────────────────────────────────────────────

class SettingsBase(BaseModel):
    business_name: Annotated[Optional[str], Field(min_length=2, max_length=200)] = None
    legal_name: Annotated[Optional[str], Field(min_length=2, max_length=200)] = None

    id_type: Optional[str] = None
    id_number: Annotated[Optional[str], Field(min_length=5, max_length=50)] = None

    phone: Annotated[Optional[str], Field(min_length=8, max_length=20)] = None
    email: Optional[EmailStr] = None
    address: Annotated[Optional[str], Field(max_length=500)] = None
    logo_path: Optional[str] = None

    default_tax: Optional[str] = None
    default_supplier_id: Optional[int] = None
    rounding_enabled: Optional[bool] = False

    # 6.2: Moneda
    default_currency: Optional[str] = "CRC"
    exchange_rate: Optional[Decimal] = Decimal("1.00")

    # Impresora
    printer_type: Optional[str] = None
    printer_ip: Optional[str] = None
    printer_port: Optional[int] = None

    # Solo lectura
    cabys_last_update: Optional[datetime] = None
    cabys_records: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id_type")
    @classmethod
    def check_id_type(cls, v):
        return _validate_id_type(v)

    @field_validator("default_tax")
    @classmethod
    def check_default_tax(cls, v):
        return _validate_default_tax(v)

    @field_validator("printer_type")
    @classmethod
    def check_printer_type(cls, v):
        return _validate_printer_type(v)

    @field_validator("default_currency")
    @classmethod
    def check_currency(cls, v):
        return _validate_currency(v)


# ─────────────────────────────────────────────────────────
# SettingsOut
# ─────────────────────────────────────────────────────────

class SettingsOut(SettingsBase):
    id: int
    supplier_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────
# SettingsUpdate (5.1 + 5.6 + 6.2)
# ─────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    business_name: Annotated[Optional[str], Field(min_length=2, max_length=200)] = None
    legal_name: Annotated[Optional[str], Field(min_length=2, max_length=200)] = None

    id_type: Optional[str] = None
    id_number: Annotated[Optional[str], Field(min_length=5, max_length=50)] = None

    phone: Annotated[Optional[str], Field(min_length=8, max_length=20)] = None
    email: Optional[EmailStr] = None
    address: Annotated[Optional[str], Field(max_length=500)] = None
    logo_path: Optional[str] = None

    default_tax: Optional[str] = None
    default_supplier_id: Optional[int] = None
    rounding_enabled: Optional[bool] = None

    # 6.2: Moneda
    default_currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = Field(default=None, gt=0, le=99999)

    # Impresora
    printer_type: Optional[str] = None
    printer_ip: Annotated[Optional[str], Field(max_length=45)] = None
    printer_port: Optional[int] = Field(default=None, ge=1, le=65535)

    @field_validator("id_type")
    @classmethod
    def check_id_type(cls, v):
        return _validate_id_type(v)

    @field_validator("default_tax")
    @classmethod
    def check_default_tax(cls, v):
        return _validate_default_tax(v)

    @field_validator("printer_type")
    @classmethod
    def check_printer_type(cls, v):
        return _validate_printer_type(v)

    @field_validator("default_currency")
    @classmethod
    def check_currency(cls, v):
        return _validate_currency(v)

    @field_validator("id_number")
    @classmethod
    def check_id_number_format(cls, v, info):
        if v is None:
            return v
        id_type = info.data.get("id_type")
        if id_type is None:
            return v
        rules = ID_NUMBER_RULES.get(id_type)
        if rules is None:
            return v
        min_len, max_len, msg = rules
        digits = v.replace("-", "").replace(" ", "")
        if not digits.isdigit():
            raise ValueError("El número de identificación solo debe contener dígitos")
        if len(digits) < min_len or len(digits) > max_len:
            raise ValueError(msg)
        return v