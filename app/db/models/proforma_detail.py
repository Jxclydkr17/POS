# app/db/models/proforma_detail.py

from sqlalchemy import Column, Integer, Numeric, Float, ForeignKey, Boolean, String
from sqlalchemy.orm import relationship
from app.db.database import Base


class ProformaDetail(Base):
    __tablename__ = "proforma_details"

    id = Column(Integer, primary_key=True, index=True)
    proforma_id = Column(Integer, ForeignKey("proformas.id", ondelete="CASCADE"))
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)

    # 📏 Cantidad — Numeric(12,3) para soportar fracciones (0.500 kg, 1.750 m)
    quantity = Column(Numeric(12, 3), nullable=False)

    unit_price = Column(Numeric(18, 5), nullable=False)
    discount_percent = Column(Numeric(5, 2), nullable=False, default=0)
    subtotal = Column(Numeric(18, 5), nullable=False)

    # Impuesto por línea (mismo esquema que SaleDetail)
    tax_rate = Column(Float, nullable=True, default=0)
    tax_amount = Column(Numeric(18, 5), nullable=True, default=0)

    # Producto común (línea sin inventario)
    is_common = Column(Boolean, default=False, nullable=False)
    common_description = Column(String(200), nullable=True)

    # Relación con Proforma
    proforma = relationship("Proforma", back_populates="details")