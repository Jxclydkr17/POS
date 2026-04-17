from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Numeric
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, validates

from app.db.database import Base


class CashMovement(Base):
    __tablename__ = "cash_movements"

    id = Column(Integer, primary_key=True, index=True)

    cash_session_id = Column(
        Integer,
        ForeignKey("cash_sessions.id"),
        nullable=False,
        index=True,  # ── FASE 4 — Fix 4.1: índice para cierre de caja ──
    )

    # IN = entrada | OUT = salida
    type = Column(String(3), nullable=False)
    
    concept = Column(String(255), nullable=False)

    amount = Column(Numeric(12, 2), nullable=False)

    # Ej: "Venta #62", "Gasto operativo", "Retiro de efectivo"
    description = Column(String(255), nullable=True)

    # SALE | EXPENSE | MANUAL | ADJUSTMENT
    source = Column(String(50), default="manual")

    # ID relacionado (sale_id, expense_id, etc.)
    reference_id = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # relaciones
    cash_session = relationship("CashSession", back_populates="movements")

    @validates("type")
    def _normalize_type(self, key, value):
        """Normaliza el tipo a lowercase ('in'/'out') para evitar
        inconsistencias si alguien inserta 'IN' o 'Out' directamente."""
        if value is not None:
            return value.lower()
        return value