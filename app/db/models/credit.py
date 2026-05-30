from app.utils.dt import utcnow
from sqlalchemy import Column, Integer, DateTime, ForeignKey, String, Numeric, Index
from sqlalchemy.orm import relationship
from app.db.database import Base


class Credit(Base):
    __tablename__ = "credits"

    # ── FASE 4 — Fix 4.1: Índices compuestos para get_credit_info() y aging ──
    __table_args__ = (
        Index("ix_credits_customer_type", "customer_id", "type"),
        Index("ix_credits_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)

    amount = Column(Numeric(12, 2), nullable=False)
    type = Column(String(20), nullable=False)  # "sale", "payment"
    payment_method = Column(String(20), nullable=True, default="Efectivo")
    description = Column(String(200), nullable=True)

    created_at = Column(DateTime, default=utcnow)

    customer = relationship(
        "Customer",
        back_populates="credit_movements"
    )

    # ✅ FIX: relación bidireccional correcta
    electronic_reps = relationship(
        "ElectronicRep",
        back_populates="credit_payment",
        cascade="all, delete-orphan"
    )