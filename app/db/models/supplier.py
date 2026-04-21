from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.database import Base
from sqlalchemy import Boolean

class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    phone = Column(String(50))
    email = Column(String(255))
    address = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relación con productos (legacy 1-a-1, se mantiene por compatibilidad)
    # AUDITORÍA FIX 3.1: lazy="select" (default) evita cargar todos los
    # productos de cada proveedor en el listado /suppliers/.
    products = relationship("Product", back_populates="supplier", lazy="select")

    # Relación M2M con productos vía supplier_products
    supplier_products = relationship(
        "SupplierProduct",
        back_populates="supplier",
        cascade="all, delete-orphan",
        lazy="select",
    )

    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    contact_name = Column(String(120), nullable=True)
    contact_phone = Column(String(30), nullable=True)
    contact_position = Column(String(80), nullable=True)

    # ═══════════════════════════════════════════════════════════
    # FASE 2.1 — Campos para Factura Electrónica de Compra (FEC)
    # En la FEC, el proveedor es el "Emisor" del XML.
    # Necesita tipo/número de identificación y ubicación.
    #
    # Tipos de identificación (nota 4):
    #   01 = Cédula Física
    #   02 = Cédula Jurídica
    #   03 = DIMEX
    #   04 = NITE
    #   05 = Extranjero No Domiciliado (solo FEC)
    #   06 = No Contribuyente (solo FEC, con condición 13)
    # ═══════════════════════════════════════════════════════════

    # Identificación tributaria
    id_type = Column(String(2), nullable=True)     # Código nota 4: 01-06
    id_number = Column(String(20), nullable=True)  # Hasta 20 chars para tipo 05/06

    # Nombre comercial (opcional)
    commercial_name = Column(String(80), nullable=True)

    # Ubicación (obligatoria excepto para tipos 05 y 06)
    provincia = Column(String(1), nullable=True)
    canton = Column(String(2), nullable=True)
    distrito = Column(String(2), nullable=True)
    barrio = Column(String(50), nullable=True)
    otras_senas = Column(String(250), nullable=True)

    # Dirección extranjero (uso exclusivo tipo 05 en FEC)
    otras_senas_extranjero = Column(String(300), nullable=True)

    # Código de país para teléfono
    phone_country_code = Column(String(3), nullable=True)

    # Código de actividad económica (opcional en FEC para emisor)
    economic_activity_code = Column(String(6), nullable=True)