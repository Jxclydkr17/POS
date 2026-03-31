from sqlalchemy import Column, Integer, String
from app.db.database import Base

class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, nullable=False)   # Código oficial Hacienda
    name = Column(String(50), nullable=False)                # Ej: Efectivo, Tarjeta, SINPE
