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
    # FASE 1 — Fix 1.3: índice para JOIN con suppliers
    default_supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)
    rounding_enabled = Column(Boolean, default=False)

    # Fase 6.2: Moneda
    default_currency = Column(String(3), nullable=False, default="CRC")  # CRC | USD
    exchange_rate = Column(Numeric(10, 2), nullable=False, default=1.00)

    supplier = relationship("Supplier", lazy="joined")

    # ── Fase 4.3 + Fix 2.5 cerrado: Configuración de impresora térmica ──
    # printer_type sigue siendo {"network", "usb", "none"} para no forzar
    # migración de configs existentes (ver schemas/settings.py).
    # - "network": ESC/POS por TCP/IP — usa printer_ip + printer_port.
    # - "usb":     ESC/POS por USB — usa printer_usb_vendor_id + _product_id.
    # - "none":    desactivado (el botón "Imprimir" muestra mensaje).
    printer_type = Column(String(20), nullable=True, default="network")
    printer_ip = Column(String(45), nullable=True, default="192.168.0.120")
    printer_port = Column(Integer, nullable=True, default=9100)

    # Fix 2.5 cerrado: USB requiere vendor/product IDs.
    # Almacenados como strings hex ("0x04b8") para que el usuario pueda
    # copiarlos textualmente de `lsusb` / Administrador de dispositivos.
    # El parser de runtime los convierte a int con int(value, 0).
    printer_usb_vendor_id = Column(String(10), nullable=True)
    printer_usb_product_id = Column(String(10), nullable=True)

    # Perfil python-escpos opcional (e.g. "TM-T20II", "TM-T88III").
    # NULL → la librería usa "default", que funciona en la mayoría de
    # impresoras Epson y compatibles.
    printer_profile = Column(String(40), nullable=True)

    # Ancho de papel en mm (58 o 80). El default 80 es el más común en
    # ferreterías/comercios; 58 se ve en POS de cafetería.
    printer_paper_width_mm = Column(Integer, nullable=True, default=80)

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