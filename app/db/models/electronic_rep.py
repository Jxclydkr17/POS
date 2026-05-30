# app/db/models/electronic_rep.py
from app.utils.dt import utcnow
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db.database import Base
from app.constants.status_enums import InvoiceStatus

class ElectronicRep(Base):
    __tablename__ = "electronic_reps"

    id = Column(Integer, primary_key=True, index=True)

    credit_payment_id = Column(Integer, ForeignKey("credits.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)

    # REP = 10
    document_type = Column(String(2), nullable=False, default="10")

    clave = Column(String(50), nullable=True, unique=True, index=True)
    consecutivo = Column(String(20), nullable=True, unique=True, index=True)

    status = Column(String(20), nullable=False, default=InvoiceStatus.PENDING)

    xml_signed = Column(Text, nullable=True)
    hacienda_response = Column(Text, nullable=True)
    hacienda_status = Column(String(30), nullable=True)

    tries = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)
    sent_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    # ✅ Relaciones bien definidas
    credit_payment = relationship(
        "Credit",
        back_populates="electronic_reps"
    )

    customer = relationship(
        "Customer",
        back_populates="electronic_reps"
    )

    references = relationship(
        "ElectronicRepReference",
        back_populates="rep",
        cascade="all, delete-orphan",
        lazy="selectin",
    )