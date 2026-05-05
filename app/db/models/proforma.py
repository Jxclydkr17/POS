# app/db/models/proforma.py

from sqlalchemy import Column, Integer, DateTime, ForeignKey, String, Text, Numeric
from sqlalchemy.orm import relationship
from app.db.database import Base
from app.utils.dt import utcnow
from app.constants.status_enums import ProformaStatus


class Proforma(Base):
    __tablename__ = "proformas"

    id = Column(Integer, primary_key=True, index=True)

    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    customer = relationship("Customer")

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user = relationship("User")

    # Numeración propia: PRO-000001, PRO-000002, etc.
    number = Column(String(20), unique=True, nullable=False, index=True)

    # VIGENTE | CONVERTIDA | VENCIDA | ANULADA
    status = Column(String(20), nullable=False, default=ProformaStatus.VIGENTE)

    # ── FASE 3 — Fix 3.5: Numeric(18, 5) para consistencia con Sale.total ──
    # Sale.total y SaleDetail.subtotal usan (18, 5) para mantener precisión
    # en cálculos de impuestos. Proforma.total debe coincidir para que
    # la conversión proforma→venta no pierda centavos.
    total = Column(Numeric(18, 5), nullable=False, default=0)

    # Notas libres del vendedor
    notes = Column(Text, nullable=True)

    # Vigencia
    validity_days = Column(Integer, nullable=False, default=15)
    valid_until = Column(DateTime, nullable=False)

    # Si se convirtió a venta, referencia a la venta creada
    converted_sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True, index=True)
    converted_sale = relationship("Sale")

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relación con líneas de detalle
    details = relationship(
        "ProformaDetail",
        back_populates="proforma",
        cascade="all, delete-orphan",
    )