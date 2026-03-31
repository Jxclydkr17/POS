# app/db/models/purchase_detail.py

from sqlalchemy import Column, Integer, DECIMAL, ForeignKey
from sqlalchemy.orm import relationship
from app.db.database import Base


class PurchaseDetail(Base):
    __tablename__ = "purchase_details"

    id = Column(Integer, primary_key=True, index=True)

    purchase_id = Column(
        Integer,
        ForeignKey("purchases.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False,
    )

    # 📏 Cantidad — DECIMAL(12,3) para soportar fracciones (0.500 kg, 1.750 m)
    quantity = Column(DECIMAL(12, 3), nullable=False)

    unit_cost = Column(DECIMAL(12, 2), nullable=False)
    subtotal = Column(DECIMAL(12, 2), nullable=False)

    # -- Relaciones --
    purchase = relationship("Purchase", back_populates="details")
    product = relationship("Product")

    @property
    def product_name(self) -> str:
        return self.product.name if self.product else ""

    def __repr__(self):
        return (
            f"<PurchaseDetail(purchase_id={self.purchase_id}, "
            f"product_id={self.product_id}, qty={self.quantity})>"
        )