# app/db/models/customer.py

from datetime import datetime
from app.utils.dt import utcnow
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, Numeric
from sqlalchemy.orm import relationship
from app.db.database import Base
from app.db.models.economic_activity import customer_economic_activity, EconomicActivity

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), nullable=True, index=True)
    phone = Column(String(20), nullable=True, index=True)
    secondary_phone = Column(String(20), nullable=True)
    address = Column(String(200), nullable=True)

    id_type = Column(String(20), nullable=True)
    id_number = Column(String(50), nullable=True, index=True)
    customer_type = Column(String(20), nullable=True, default="Normal")

    # ubicación CR
    province_id = Column(String(2), nullable=True)
    province_name = Column(String(50), nullable=True)

    canton_id = Column(String(2), nullable=True)
    canton_name = Column(String(80), nullable=True)

    district_id = Column(String(2), nullable=True)
    district_name = Column(String(80), nullable=True)

    neighborhood = Column(String(80), nullable=True)

    credit_balance = Column(Numeric(12, 2), default=0)
    credit_limit = Column(Numeric(12, 2), default=0)
    has_credit_limit = Column(Boolean, default=False)

    # Notas internas (uso interno del negocio)
    notes = Column(Text, nullable=True)

    # Fecha de nacimiento (personas físicas)
    birth_date = Column(Date, nullable=True)

    # Última compra (cacheado para consultas rápidas)
    last_purchase_date = Column(DateTime, nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # ventas normales
    sales = relationship("Sale", back_populates="customer")

    # ventas a crédito
    # ── FASE 3 — Fix 3.4: Sin cascade delete para datos financieros ──
    # delete_customer() es soft-delete (is_active=False), pero si alguien
    # hiciera db.delete(customer) por error, NO debe borrar el historial
    # financiero (créditos, pagos). Esos datos son necesarios para
    # auditoría, reportes fiscales y conciliación.
    credit_sales = relationship(
        "CreditSale",
        back_populates="customer",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    # movimientos de crédito
    credit_movements = relationship(
        "Credit",
        back_populates="customer",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    # ── FASE 4 — Fix 4.1: lazy="select" en vez de "joined" ──
    # "joined" forzaba un LEFT JOIN en cada carga de cliente, incluso en
    # listados donde no se necesitan las actividades económicas.
    # Los endpoints que las necesiten pueden usar .options(joinedload(...)).
    economic_activities = relationship(
        "EconomicActivity",
        secondary=customer_economic_activity,
        lazy="select",
    )

        # 🆕 REPs electrónicos del cliente
    electronic_reps = relationship(
        "ElectronicRep",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    # ═══════════════════════════════════════════════════════════
    # FASE 4 — Campos para XML del receptor
    # ═══════════════════════════════════════════════════════════

    # 4.3: Nombre comercial del receptor (opcional, hasta 80 chars)
    commercial_name = Column(String(80), nullable=True)

    # 4.2: Dirección en el extranjero para tipo identificación 05
    #      (Extranjero No Domiciliado). Hasta 300 chars.
    otras_senas_extranjero = Column(String(300), nullable=True)

    # 4.4: Código de país para teléfono (default 506 = Costa Rica)
    phone_country_code = Column(String(3), nullable=True, default="506")

    # 4.1: OtrasSenas específicas para XML (hasta 160 chars).
    #      Si NULL, se usa el campo `address` como fallback.
    otras_senas = Column(String(160), nullable=True)