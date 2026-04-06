from datetime import datetime
from app.utils.dt import utcnow
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from app.db.database import Base


class CreditSale(Base):
    __tablename__ = "credit_sales"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False, unique=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)

    total_amount = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    sale = relationship("Sale", back_populates="credit_sale")

    customer = relationship(
        "Customer",
        back_populates="credit_sales"
    )