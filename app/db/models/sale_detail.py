from sqlalchemy import Column, Integer, Numeric, Float, ForeignKey, Boolean, String, DateTime
from sqlalchemy.orm import relationship
from app.db.database import Base

class SaleDetail(Base):
    __tablename__ = "sale_details"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id", ondelete="CASCADE"))
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)

    # 📏 Cantidad
    quantity = Column(Numeric(12, 3), nullable=False)

    unit_price = Column(Numeric, nullable=False)
    discount_percent = Column(Numeric(5, 2), nullable=False, default=0)
    subtotal = Column(Numeric, nullable=False)

    # Impuesto por línea
    tax_rate = Column(Numeric(5, 2), nullable=True, default=0)
    tax_amount = Column(Numeric(18, 5), nullable=True, default=0)

    # PRODUCTO COMÚN: línea sin inventario
    is_common = Column(Boolean, default=False, nullable=False)
    common_description = Column(String(200), nullable=True)

    # Relación con Sale
    sale = relationship("Sale", back_populates="details")

    # ═══════════════════════════════════════════════════════════
    # FASE 3.3 — Descuento dinámico por línea (nota 20)
    # Si NULL, se usa el default del producto o "07" (Comercial).
    # ═══════════════════════════════════════════════════════════
    discount_code = Column(String(2), nullable=True)
    # Obligatorio si discount_code = "99"
    discount_code_otro = Column(String(100), nullable=True)
    # Obligatorio si discount_code = "99" (NaturalezaDescuento)
    discount_description = Column(String(80), nullable=True)

    # ═══════════════════════════════════════════════════════════
    # FASE 3.1 — Campos v4.4 por línea (overrides del producto)
    # ═══════════════════════════════════════════════════════════

    # TipoTransaccion (nota 22) — override por línea
    tipo_transaccion = Column(String(2), nullable=True)

    # IVA cobrado a nivel de fábrica (nota 21) — override por línea
    iva_cobrado_fabrica = Column(String(2), nullable=True)

    # Número VIN/Serie — override por línea (venta de varios vehículos)
    numero_vin_serie = Column(String(17), nullable=True)

    # Código de impuesto — override por línea (default "01" = IVA)
    impuesto_code = Column(String(2), nullable=True)

    # Factor cálculo IVA — override para bienes usados (código 08)
    factor_calculo_iva = Column(Numeric(5, 4), nullable=True)

    # ═══════════════════════════════════════════════════════════
    # FASE 3.4 — Exoneración por línea
    # Condicional: solo cuando la venta tiene exoneración.
    # ═══════════════════════════════════════════════════════════
    exon_tipo_doc = Column(String(2), nullable=True)         # nota 10.1
    exon_tipo_doc_otro = Column(String(100), nullable=True)  # si código 99
    exon_numero_doc = Column(String(40), nullable=True)
    exon_articulo = Column(Integer, nullable=True)           # artículo de ley
    exon_inciso = Column(Integer, nullable=True)             # inciso de ley
    exon_institucion = Column(String(2), nullable=True)      # nota 23
    exon_institucion_otro = Column(String(160), nullable=True)  # si código 99
    exon_fecha = Column(DateTime, nullable=True)
    exon_tarifa = Column(Numeric(5, 2), nullable=True)               # % exonerado (ej: 13)