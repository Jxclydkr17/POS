from sqlalchemy import Column, Integer, Date, DateTime, Numeric, String, UniqueConstraint
from app.utils.dt import utcnow
from app.db.database import Base
from sqlalchemy.orm import relationship

class CashSession(Base):
    __tablename__ = "cash_sessions"

    # ── FASE 2 — Fix 2.1: UniqueConstraint(date, terminal_id) ──
    # Antes: date unique=True impedía 2 cajas/turnos el mismo día.
    # Ahora: cada terminal puede tener su propia sesión diaria.
    __table_args__ = (
        UniqueConstraint("date", "terminal_id", name="uq_cash_date_terminal"),
    )

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)

    # ── FASE 2 — Fix 2.1: Identificador de terminal/caja ──
    # Default "T1" para compatibilidad con instalaciones single-terminal.
    terminal_id = Column(String(10), nullable=False, default="T1")

    opening_amount = Column(Numeric(12, 2), nullable=False)
    closing_amount = Column(Numeric(12, 2), nullable=True)

    expected_closing = Column(Numeric(12, 2), nullable=True)
    difference = Column(Numeric(12, 2), nullable=True)

    status = Column(String(20), default="open")  # open / closed

    created_at = Column(DateTime, default=utcnow)
    closed_at = Column(DateTime, nullable=True)

    movements = relationship(
        "CashMovement",
        back_populates="cash_session",
        cascade="all, delete-orphan"
    )