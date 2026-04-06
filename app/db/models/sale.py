# app/db/models/sale.py

from sqlalchemy import Column, Integer, DateTime, ForeignKey, String, Numeric
from sqlalchemy.orm import relationship
from app.db.database import Base
from app.utils.dt import now_cr


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)

    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    customer = relationship("Customer", back_populates="sales")

    # Vendedor que registró la venta
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user = relationship("User")

    cash_session_id = Column(Integer, ForeignKey("cash_sessions.id"), nullable=False)
    cash_session = relationship("CashSession")

    # ── FASE 1 — Fix 1.2: Numeric(18,5) para igualar precisión de SaleDetail ──
    total = Column(Numeric(18, 5), nullable=False)
    payment_method = Column(String(20), nullable=False)
    condicion_venta_code = Column(String(2), nullable=True)
    document_type = Column(String(2), nullable=False, default='04')
    status = Column(String(20), nullable=False, default='ACTIVA')

    created_at = Column(DateTime, default=now_cr)

    details = relationship("SaleDetail", back_populates="sale", cascade="all, delete-orphan")
    credit_sale = relationship("CreditSale", back_populates="sale", uselist=False)
    credit_days = Column(Integer, nullable=True)

    # ═══════════════════════════════════════════════════════════
    # FASE 5.3 — Soporte multi-moneda
    # moneda_code: código ISO 4217 (CRC, USD, EUR, etc.)
    #   NULL o "CRC" = colones (tipo_cambio = 1)
    # tipo_cambio: tipo de cambio respecto a colones.
    #   Para USD: tipo de cambio de venta del BCCR.
    #   Para CRC: siempre "1".
    # ═══════════════════════════════════════════════════════════
    moneda_code = Column(String(3), nullable=True)
    tipo_cambio = Column(String(20), nullable=True)

    # FASE 3.2: Detalle para condición de venta código 99
    condicion_venta_otros = Column(String(100), nullable=True)