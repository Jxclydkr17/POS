from sqlalchemy import Column, String, Integer
from app.db.database import Base

class Cabys(Base):
    __tablename__ = "cabys"

    code = Column(String(20), primary_key=True, index=True)
    description = Column(String(1500))
    iva = Column(Integer)
