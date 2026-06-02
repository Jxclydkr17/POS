# app/schemas/products.py
from pydantic import BaseModel, Field, ConfigDict
from typing import Annotated, Optional
from decimal import Decimal

# ============================
# 📏 Unidades de medida válidas
# ============================
VALID_UNIT_TYPES = ("Unid", "Kg", "g", "m", "cm", "L", "mL")


# ============================
# BASE
# ============================
class ProductBase(BaseModel):
    # Identificadores básicos
    code: Optional[str] = None
    name: str = Field(min_length=2, max_length=150)
    description: Annotated[Optional[str], Field(max_length=500)] = None

    # Códigos adicionales
    barcode: Optional[str] = None

    # CABYS
    cabys_code: Optional[str] = None
    cabys_name: Optional[str] = None

    # IVA
    tax_type: Optional[str] = None
    tax_rate: Optional[float] = None

    # Relaciones
    category_id: Optional[int] = None
    supplier_id: Optional[int] = None

    # Valores económicos
    price: Decimal = Field(ge=0)
    cost: Annotated[Optional[Decimal], Field(ge=0)] = None

    # 📦 Stock — ahora Decimal para soportar fracciones (kg, metros, litros)
    stock: Decimal = Field(default=Decimal("0"), ge=0)
    min_stock: Decimal = Field(default=Decimal("3"), ge=0)

    # 📏 Unidad de medida — define cómo se vende el producto
    # "Unid" = unidades enteras (comportamiento actual)
    # "Kg", "g", "m", "cm", "L", "mL" = cantidades fraccionarias
    unit_type: str = Field(
        default="Unid",
        pattern="^(Unid|Kg|g|m|cm|L|mL)$",
        description="Unidad de medida: Unid, Kg, g, m, cm, L, mL"
    )

    is_pos_favorite: bool = False

    # Imagen
    image_path: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============================
# CREATE
# ============================
class ProductCreate(ProductBase):
    """Esquema para crear productos.

    Hereda todos los campos de ProductBase.
    """
    pass


# ============================
# UPDATE
# ============================
class ProductUpdate(BaseModel):
    # Identificadores básicos
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None

    # Códigos adicionales
    barcode: Optional[str] = None

    # CABYS
    cabys_code: Optional[str] = None
    cabys_name: Optional[str] = None

    # IVA
    tax_type: Optional[str] = None
    tax_rate: Optional[float] = None

    # Relaciones
    category_id: Optional[int] = None
    supplier_id: Optional[int] = None

    # Valores económicos
    price: Annotated[Optional[Decimal], Field(ge=0)] = None
    cost: Annotated[Optional[Decimal], Field(ge=0)] = None

    # 📦 Stock — ahora Decimal para soportar fracciones
    stock: Annotated[Optional[Decimal], Field(ge=0)] = None
    min_stock: Annotated[Optional[Decimal], Field(ge=0)] = None

    # 📏 Unidad de medida (opcional en update)
    unit_type: Optional[str] = Field(
        default=None,
        pattern="^(Unid|Kg|g|m|cm|L|mL)$",
        description="Unidad de medida: Unid, Kg, g, m, cm, L, mL"
    )

    is_pos_favorite: Optional[bool] = None

    # Imagen
    image_path: Optional[str] = None


# ============================
# OUTPUT
# ============================
class ProductOut(ProductBase):
    id: int
    is_active: bool
    is_pos_favorite: bool

    # Campos enriquecidos sólo de salida
    category_name: Optional[str] = None
    supplier_name: Optional[str] = None
    # Sugerencia de reposición (calculada en el backend)
    # Ahora Decimal porque stock y min_stock son Decimal
    reorder_suggestion: Optional[Decimal] = None