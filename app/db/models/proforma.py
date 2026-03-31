# app/db/models/proforma.py

from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship
from app.db.database import Base
from app.utils.dt import utcnow


class Proforma(Base):
    __tablename__ = "proformas"

    id = Column(Integer, primary_key=True, index=True)

    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    customer = relationship("Customer")

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user = relationship("User")

    # Numeración propia: PRO-000001, PRO-000002, etc.
    number = Column(String(20), unique=True, nullable=False, index=True)

    # VIGENTE | CONVERTIDA | VENCIDA | ANULADA
    status = Column(String(20), nullable=False, default="VIGENTE")

    total = Column(Float, nullable=False, default=0)

    # Notas libres del vendedor
    notes = Column(Text, nullable=True)

    # Vigencia
    validity_days = Column(Integer, nullable=False, default=15)
    valid_until = Column(DateTime, nullable=False)

    # Si se convirtió a venta, referencia a la venta creada
    converted_sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True)
    converted_sale = relationship("Sale")

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relación con líneas de detalle
    details = relationship(
        "ProformaDetail",
        back_populates="proforma",
        cascade="all, delete-orphan",
    )