# app/db/models/supplier_product.py
"""
Tabla puente proveedor ↔ producto (muchos-a-muchos).

Consolida qué proveedores venden qué producto y a qué precio.
Se alimenta automáticamente desde las compras registradas,
y también puede editarse manualmente desde el UI.
"""

from sqlalchemy import (
    Column, Integer, Boolean, DateTime, ForeignKey,
    Numeric, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base


class SupplierProduct(Base):
    __tablename__ = "supplier_products"

    id = Column(Integer, primary_key=True, index=True)

    supplier_id = Column(
        Integer,
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Último costo unitario registrado para esta combinación
    unit_cost = Column(Numeric(12, 2), nullable=False, default=0)

    # Fecha de la última compra que actualizó este registro
    last_purchase_date = Column(DateTime(timezone=True), nullable=True)

    # ¿Es el proveedor preferido para este producto?
    is_preferred = Column(Boolean, nullable=False, default=False, server_default="0")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Relaciones ──
    supplier = relationship("Supplier", back_populates="supplier_products")
    product = relationship("Product", back_populates="supplier_products")

    # ── Restricción única: un solo registro por par proveedor-producto ──
    __table_args__ = (
        UniqueConstraint(
            "supplier_id", "product_id",
            name="uq_supplier_product",
        ),
    )

    def __repr__(self):
        return (
            f"<SupplierProduct(supplier_id={self.supplier_id}, "
            f"product_id={self.product_id}, cost={self.unit_cost})>"
        )