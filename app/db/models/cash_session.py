from sqlalchemy import Column, Integer, Date, DateTime, Numeric, String
from datetime import datetime
from app.utils.dt import utcnow
from app.db.database import Base
from sqlalchemy.orm import relationship

class CashSession(Base):
    __tablename__ = "cash_sessions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True)  # 1 sesión por día

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