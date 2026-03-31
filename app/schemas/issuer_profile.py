"""
app/schemas/issuer_profile.py — Schemas del perfil de emisor.

Fase 5: Validaciones.
  5.2  id_type validado contra códigos Hacienda (01/02/03/04)
  5.3  id_number validado según id_type
"""

from pydantic import BaseModel, Field, ConfigDict, EmailStr, field_validator
from typing import Annotated, Optional


# 5.2: Códigos oficiales de Hacienda para tipo de identificación
ISSUER_ID_TYPE_VALID = {"01", "02", "03", "04"}

# 5.3: Reglas de longitud por código
ISSUER_ID_NUMBER_RULES = {
    "01": (9, 9,   "Cédula física (01) debe tener exactamente 9 dígitos"),
    "02": (10, 10, "Cédula jurídica (02) debe tener exactamente 10 dígitos"),
    "03": (11, 12, "DIMEX (03) debe tener entre 11 y 12 dígitos"),
    "04": (10, 10, "NITE (04) debe tener exactamente 10 dígitos"),
}


class IssuerProfileOut(BaseModel):
    id: int

    legal_name: str
    commercial_name: Optional[str] = None

    id_type: str
    id_number: str

    email: EmailStr
    phone: Optional[str] = None

    provider_system_id: Annotated[Optional[str], Field(max_length=20)] = None
    economic_activity_code: Annotated[Optional[str], Field(min_length=6, max_length=6)] = None

    provincia: Annotated[Optional[str], Field(min_length=1, max_length=1)] = None
    canton: Annotated[Optional[str], Field(min_length=2, max_length=2)] = None
    distrito: Annotated[Optional[str], Field(min_length=2, max_length=2)] = None
    barrio: Annotated[Optional[str], Field(min_length=5, max_length=50)] = None
    otras_senas: Annotated[Optional[str], Field(min_length=5, max_length=160)] = None

    branch_code: str
    terminal_code: str

    enable_rep: int
    rep_default_condicion_venta: Annotated[Optional[str], Field(max_length=2)] = None
    rep_default_codigo_referencia: Annotated[Optional[str], Field(max_length=2)] = None

    model_config = ConfigDict(from_attributes=True)


class IssuerProfileUpdate(BaseModel):
    legal_name: Annotated[Optional[str], Field(min_length=2, max_length=120)] = None
    commercial_name: Annotated[Optional[str], Field(max_length=120)] = None

    id_type: Annotated[Optional[str], Field(max_length=2)] = None
    id_number: Annotated[Optional[str], Field(max_length=20)] = None

    email: Optional[EmailStr] = None
    phone: Annotated[Optional[str], Field(max_length=30)] = None

    provider_system_id: Annotated[Optional[str], Field(max_length=20)] = None
    economic_activity_code: Annotated[Optional[str], Field(min_length=6, max_length=6)] = None

    provincia: Annotated[Optional[str], Field(min_length=1, max_length=1)] = None
    canton: Annotated[Optional[str], Field(min_length=2, max_length=2)] = None
    distrito: Annotated[Optional[str], Field(min_length=2, max_length=2)] = None
    barrio: Annotated[Optional[str], Field(min_length=5, max_length=50)] = None
    otras_senas: Annotated[Optional[str], Field(min_length=5, max_length=160)] = None

    branch_code: Annotated[Optional[str], Field(max_length=3)] = None
    terminal_code: Annotated[Optional[str], Field(max_length=5)] = None

    enable_rep: Optional[int] = None
    rep_default_condicion_venta: Annotated[Optional[str], Field(max_length=2)] = None
    rep_default_codigo_referencia: Annotated[Optional[str], Field(max_length=2)] = None

    # 5.2: Validar código de tipo de identificación
    @field_validator("id_type")
    @classmethod
    def check_id_type(cls, v):
        if v is not None and v not in ISSUER_ID_TYPE_VALID:
            raise ValueError(
                f"id_type del emisor debe ser uno de: {', '.join(sorted(ISSUER_ID_TYPE_VALID))} "
                f"(01=Física, 02=Jurídica, 03=DIMEX, 04=NITE)"
            )
        return v

    # 5.3: Validar id_number según id_type
    @field_validator("id_number")
    @classmethod
    def check_id_number(cls, v, info):
        if v is None:
            return v

        id_type = info.data.get("id_type")
        if id_type is None:
            return v

        rules = ISSUER_ID_NUMBER_RULES.get(id_type)
        if rules is None:
            return v

        min_len, max_len, msg = rules
        digits = v.replace("-", "").replace(" ", "")
        if not digits.isdigit():
            raise ValueError("El número de identificación solo debe contener dígitos")
        if len(digits) < min_len or len(digits) > max_len:
            raise ValueError(msg)

        return v

    # Validar enable_rep sea 0 o 1
    @field_validator("enable_rep")
    @classmethod
    def check_enable_rep(cls, v):
        if v is not None and v not in (0, 1):
            raise ValueError("enable_rep debe ser 0 o 1")
        return v