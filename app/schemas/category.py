# app/schemas/category.py

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ============================
# 🟦 BASE
# ============================
class CategoryBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    is_active: bool = True
    icon: str = "📦"
    position: int = 0


# ============================
# 🟩 CREATE
# ============================
class CategoryCreate(CategoryBase):
    pass


# ============================
# 🟧 UPDATE  (parcial: solo viajan los campos que el cliente envía)
# ============================
class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None
    icon: Optional[str] = None
    position: Optional[int] = None


# ============================
# 🟥 OUT  (hereda name, is_active, icon, description, position de Base)
# ============================
class CategoryOut(CategoryBase):
    id: int
    total_products: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)