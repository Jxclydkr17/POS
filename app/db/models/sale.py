# app/db/models/sale.py

from sqlalchemy import Column, Integer, DateTime, ForeignKey, String, Numeric, Index, Boolean
from sqlalchemy.orm import relationship
from app.db.database import Base
# FASE 2.2 — Fix 2.2: cambio de now_cr a utcnow.
# Antes Sale.created_at usaba `default=now_cr` (CR aware), lo que generaba
# inconsistencia con el resto de modelos (que usan utcnow). En SQLite el
# offset se preservaba pero en MySQL se truncaba silenciosamente, causando
# comparaciones de rango con resultados distintos entre motores.
# Migración Alembic relacionada: alembic/versions/f6a7b8c9d0e1_normalize_sale_created_at_to_utc.py
from app.utils.dt import utcnow
from app.constants.status_enums import SaleStatus


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)

    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)  # FASE 3
    customer = relationship("Customer", back_populates="sales")

    # ── FIX: Especificamos que 'user' usa 'user_id' ──
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # FASE 3
    user = relationship("User", foreign_keys=[user_id])

    cash_session_id = Column(Integer, ForeignKey("cash_sessions.id"), nullable=False, index=True)  # FASE 3
    cash_session = relationship("CashSession")

    total = Column(Numeric(18, 5), nullable=False)
    payment_method = Column(String(20), nullable=False)
    condicion_venta_code = Column(String(2), nullable=True)
    document_type = Column(String(2), nullable=False, default='04')
    status = Column(String(20), nullable=False, default=SaleStatus.ACTIVA)

    created_at = Column(DateTime, default=utcnow, index=True)

    # ── FASE 2 — Auditoría de ediciones ──
    updated_at = Column(DateTime, nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    
    # OPCIONAL: Si quieres acceder al objeto usuario que editó, añade esto:
    editor = relationship("User", foreign_keys=[updated_by])

    details = relationship("SaleDetail", back_populates="sale", cascade="all, delete-orphan")
    credit_sale = relationship("CreditSale", back_populates="sale", uselist=False)
    credit_days = Column(Integer, nullable=True)

    # FASE 5.3 — Soporte multi-moneda
    moneda_code = Column(String(3), nullable=True)
    tipo_cambio = Column(String(20), nullable=True)

    # FASE 3.2: Detalle para condición de venta código 99
    condicion_venta_otros = Column(String(100), nullable=True)

    # ── FASE C — Fix C.3: Estado de generación de PDF ──
    # None = no intentado, True = generado OK, False = falló
    pdf_generated = Column(Boolean, nullable=True, default=None)

    # ── FASE 4 — Índices compuestos ──
    __table_args__ = (
        Index("ix_sales_status", "status"),
        Index("ix_sales_created_status", "created_at", "status"),
    )