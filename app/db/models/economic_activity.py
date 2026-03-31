from sqlalchemy import Table, Column, String, Text, ForeignKey, Integer
from app.db.database import Base

class EconomicActivity(Base):
    __tablename__ = "economic_activities"

    code = Column(String(10), primary_key=True, index=True)  # ej: "011101"
    description = Column(Text, nullable=False)

customer_economic_activity = Table(
    "customer_economic_activity",
    Base.metadata,
    Column("customer_id", Integer, ForeignKey("customers.id"), primary_key=True),
    Column("activity_code", String(10), ForeignKey("economic_activities.code"), primary_key=True),
)
