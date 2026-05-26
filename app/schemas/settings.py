"""
app/schemas/settings.py — Schemas de configuración general.

Fase 5: Validaciones y seguridad.
Fase 6: 6.2 Moneda configurable.
Fix 2.5 (cerrado): Campos USB + perfil + ancho de papel para ESC/POS real.
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

# Fix 2.5 (cerrado): el enum sigue como estaba a propósito.
# Antes "network"/"usb" eran placeholders sin implementación; ahora
# están implementados. NO removemos valores para no romper configs
# existentes en producción (cualquier user con printer_type='network'
# guardado seguiría siendo válido). Si en un futuro se decide retirar
# alguno, hay que hacer migración Alembic con default seguro.
PRINTER_TYPES_VALID = {"network", "usb", "none"}

# Anchos de papel típicos. 58 → POS pequeño, 80 → más común.
PRINTER_PAPER_WIDTHS = {58, 80}

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


def _validate_printer_paper_width(v):
    if v is not None and v not in PRINTER_PAPER_WIDTHS:
        raise ValueError(
            f"printer_paper_width_mm debe ser uno de: {', '.join(map(str, sorted(PRINTER_PAPER_WIDTHS)))}"
        )
    return v


def _validate_usb_id(v):
    """
    Acepta vendor_id/product_id en hex (e.g. '0x04b8', '04b8', '0x4B8').
    Convierte mayúsculas y normaliza al formato '0xXXXX'. Vacío → None.
    """
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    # Acepta con o sin prefijo 0x. int(v, 16) parsea ambos siempre que
    # le quitemos el 0x manualmente.
    raw = v.lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    try:
        n = int(raw, 16)
    except ValueError:
        raise ValueError(
            f"USB ID inválido '{v}'. Use formato hex (e.g. '0x04b8' o '04b8')."
        )
    # USB IDs caben en 16 bits.
    if not (0 <= n <= 0xFFFF):
        raise ValueError(f"USB ID '{v}' fuera de rango (debe ser 0x0000–0xFFFF).")
    return f"0x{n:04x}"


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
    # Fix 2.5 (cerrado): nuevos campos para ESC/POS USB
    printer_usb_vendor_id: Optional[str] = None
    printer_usb_product_id: Optional[str] = None
    printer_profile: Annotated[Optional[str], Field(max_length=40)] = None
    printer_paper_width_mm: Optional[int] = None

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

    @field_validator("printer_paper_width_mm")
    @classmethod
    def check_printer_paper_width(cls, v):
        return _validate_printer_paper_width(v)


# ─────────────────────────────────────────────────────────
# SettingsOut
# ─────────────────────────────────────────────────────────

class SettingsOut(SettingsBase):
    id: int
    supplier_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────
# SettingsUpdate (5.1 + 5.6 + 6.2 + Fix 2.5 cerrado)
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
    # Fix 2.5 (cerrado): nuevos campos USB + perfil + ancho papel
    printer_usb_vendor_id: Annotated[Optional[str], Field(max_length=10)] = None
    printer_usb_product_id: Annotated[Optional[str], Field(max_length=10)] = None
    printer_profile: Annotated[Optional[str], Field(max_length=40)] = None
    printer_paper_width_mm: Optional[int] = None

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

    @field_validator("printer_paper_width_mm")
    @classmethod
    def check_printer_paper_width(cls, v):
        return _validate_printer_paper_width(v)

    @field_validator("printer_usb_vendor_id")
    @classmethod
    def check_usb_vendor(cls, v):
        return _validate_usb_id(v)

    @field_validator("printer_usb_product_id")
    @classmethod
    def check_usb_product(cls, v):
        return _validate_usb_id(v)

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