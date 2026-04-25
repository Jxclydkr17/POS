# app/db/models/electronic_invoice.py
from datetime import datetime
from app.utils.dt import utcnow
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db.database import Base
from app.constants.status_enums import InvoiceStatus

class ElectronicInvoice(Base):
    __tablename__ = "electronic_invoices"

    id = Column(Integer, primary_key=True, index=True)

    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False, index=True)
    sale = relationship("Sale")

    # '01' Factura electrónica, '04' Tiquete electrónico (por ahora)
    document_type = Column(String(2), nullable=False)

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