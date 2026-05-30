from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.utils.dt import utcnow
from app.db.database import Base
import enum


class MovementType(str, enum.Enum):
    venta                = "venta"
    devolucion           = "devolucion"            # cliente devuelve → suma stock
    devolucion_proveedor = "devolucion_proveedor"  # devuelve a proveedor → resta stock
    entrada              = "entrada"
    ajuste               = "ajuste"
    anulacion            = "anulacion"


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id           = Column(Integer, primary_key=True, index=True)
    # FASE 1 — Fix 1.3: índice para JOINs de rotación de inventario
    product_id   = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    type         = Column(Enum(MovementType), nullable=False)

    # 📏 Cantidad y stock — Numeric(12,3) para soportar fracciones (kg, metros, litros)
    quantity     = Column(Numeric(12, 3), nullable=False)
    stock_before = Column(Numeric(12, 3), nullable=False)
    stock_after  = Column(Numeric(12, 3), nullable=False)

    reference    = Column(String(100), nullable=True)   # Ej: "Venta #45"
    notes        = Column(String(255), nullable=True)
    created_at   = Column(DateTime, default=utcnow)

    product = relationship("Product")

    def __repr__(self):
        return f"<InventoryMovement(product_id={self.product_id}, type={self.type}, qty={self.quantity})>"