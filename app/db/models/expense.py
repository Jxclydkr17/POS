from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from app.utils.dt import utcnow
from app.db.database import Base

class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    amount = Column(Numeric(12, 2), nullable=False)
    date = Column(DateTime, default=utcnow)
    payment_method = Column(String(50), nullable=True)

    # Auditoría: quién registró el gasto
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # FASE 3
    user = relationship("User", foreign_keys=[user_id], lazy="joined")