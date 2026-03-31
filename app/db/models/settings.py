from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from datetime import datetime
from app.utils.dt import utcnow

from app.db.database import Base


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, default=1)

    # Datos de la empresa
    business_name = Column(String(200))
    legal_name = Column(String(200))
    id_type = Column(String(20))
    id_number = Column(String(50))
    phone = Column(String(50))
    email = Column(String(200))
    address = Column(String(500))
    logo_path = Column(String(300))

    # Preferencias del POS
    default_tax = Column(String(10))
    default_supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    rounding_enabled = Column(Boolean, default=False)

    # Fase 6.2: Moneda
    default_currency = Column(String(3), nullable=False, default="CRC")  # CRC | USD
    exchange_rate = Column(Numeric(10, 2), nullable=False, default=1.00)

    supplier = relationship("Supplier", lazy="joined")

    # Fase 4.3: Configuración de impresora térmica
    printer_type = Column(String(20), nullable=True, default="network")
    printer_ip = Column(String(45), nullable=True, default="192.168.0.120")
    printer_port = Column(Integer, nullable=True, default=9100)

    # Información del CABYS
    cabys_last_update = Column(DateTime, nullable=True)
    cabys_records = Column(Integer, default=0)

    # Auditoría
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(
        DateTime,
        default=utcnow,
        onupdate=utcnow
    )