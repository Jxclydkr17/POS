# app/db/models/category.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.database import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    icon = Column(String(10), nullable=True)
    position = Column(Integer, nullable=False, default=0, server_default="0")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relación inversa
    # AUDITORÍA FIX 3.2: lazy="select" (default) evita cargar todos los
    # productos de cada categoría al listar categorías.
    # category_crud.py ya hace su propio count(Product.id) con query explícita.
    products = relationship("Product", back_populates="category", lazy="select")