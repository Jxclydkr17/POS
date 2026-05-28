# app/db/models/purchase_detail.py

from sqlalchemy import Column, Integer, DECIMAL, ForeignKey
from sqlalchemy.orm import relationship
from app.db.database import Base


class PurchaseDetail(Base):
    __tablename__ = "purchase_details"

    id = Column(Integer, primary_key=True, index=True)

    purchase_id = Column(
        Integer,
        ForeignKey("purchases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # FASE 3: índice para JOINs de detalle de compra
    )
    product_id = Column(
        Integer,
        ForeignKey("products.id"),
        nullable=False,
    )

    # 📏 Cantidad — DECIMAL(12,3) para soportar fracciones (0.500 kg, 1.750 m)
    quantity  = Column(DECIMAL(12, 3), nullable=False)
    unit_cost = Column(DECIMAL(12, 2), nullable=False)

    # subtotal almacena el subtotal_neto (base imponible = subtotal_bruto − descuento)
    subtotal  = Column(DECIMAL(12, 2), nullable=False)

    # ── Descuento por línea (facturación electrónica CR V4.4) ──
    # Valores por defecto 0 para mantener compatibilidad con registros anteriores.
    discount_pct    = Column(DECIMAL(5, 2),  nullable=False, server_default="0.00")
    discount_amount = Column(DECIMAL(12, 2), nullable=False, server_default="0.00")

    # ── IVA por línea ──
    iva_pct    = Column(DECIMAL(5, 2),  nullable=False, server_default="13.00")
    iva_amount = Column(DECIMAL(12, 2), nullable=False, server_default="0.00")

    # Total de la línea (subtotal_neto + iva_amount) — auditabilidad
    total_line = Column(DECIMAL(12, 2), nullable=False, server_default="0.00")

    # -- Relaciones --
    purchase = relationship("Purchase", back_populates="details")
    product  = relationship("Product")

    @property
    def product_name(self) -> str:
        return self.product.name if self.product else ""

    def __repr__(self):
        return (
            f"<PurchaseDetail(purchase_id={self.purchase_id}, "
            f"product_id={self.product_id}, qty={self.quantity}, "
            f"disc={self.discount_pct}%, total={self.total_line})>"
        )