# app/db/models/purchase_payment.py

from sqlalchemy import Column, Integer, String, Date, DateTime, DECIMAL, Text, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class PurchasePayment(Base):
    __tablename__ = "purchase_payments"

    id = Column(Integer, primary_key=True, index=True)

    purchase_id = Column(
        Integer,
        ForeignKey("purchases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount = Column(DECIMAL(12, 2), nullable=False)
    payment_method = Column(String(50), nullable=False, default="Efectivo")
    date = Column(Date, nullable=False)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=func.now())

    purchase = relationship("Purchase", back_populates="payments")

    def __repr__(self):
        return f"<PurchasePayment(purchase_id={self.purchase_id}, amount={self.amount})>"
