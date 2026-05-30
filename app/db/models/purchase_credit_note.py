# app/db/models/purchase_credit_note.py

from sqlalchemy import Column, Integer, Date, DateTime, DECIMAL, Text, ForeignKey, Boolean, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class PurchaseCreditNote(Base):
    __tablename__ = "purchase_credit_notes"

    id = Column(Integer, primary_key=True, index=True)

    purchase_id = Column(
        Integer,
        ForeignKey("purchases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount = Column(DECIMAL(12, 2), nullable=False)
    reason = Column(Text, nullable=False)
    date = Column(Date, nullable=False)

    # Si aplica devolución de productos al proveedor
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)

    # 📏 Cantidad devuelta — DECIMAL(12,3) para soportar fracciones (kg, metros, litros)
    quantity_returned = Column(DECIMAL(12, 3), nullable=True, default=0)

    stock_reverted = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=func.now())

    purchase = relationship("Purchase", back_populates="credit_notes")
    product = relationship("Product")

    def __repr__(self):
        return f"<PurchaseCreditNote(purchase_id={self.purchase_id}, amount={self.amount})>"