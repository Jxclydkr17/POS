# app/db/models/electronic_rep_reference.py
from datetime import datetime
from app.utils.dt import utcnow
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.db.database import Base

class ElectronicRepReference(Base):
    __tablename__ = "electronic_rep_references"

    id = Column(Integer, primary_key=True, index=True)

    rep_id = Column(Integer, ForeignKey("electronic_reps.id", ondelete="CASCADE"), nullable=False, index=True)
    electronic_invoice_id = Column(Integer, ForeignKey("electronic_invoices.id"), nullable=False, index=True)

    amount_applied = Column(Numeric(18, 2), nullable=False, default=0)

    created_at = Column(DateTime, default=utcnow)

    rep = relationship("ElectronicRep", back_populates="references")
    electronic_invoice = relationship("ElectronicInvoice")