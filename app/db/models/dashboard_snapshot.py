from app.utils.dt import utcnow

from sqlalchemy import Column, Integer, Date, DateTime, Numeric
from app.db.database import Base


class DashboardSnapshot(Base):
    __tablename__ = "dashboard_daily_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_date = Column(Date, nullable=False, unique=True, index=True)

    sales_today = Column(Numeric(14, 2), nullable=False, default=0)
    estimated_profit_today = Column(Numeric(14, 2), nullable=False, default=0)

    critical_products = Column(Integer, nullable=False, default=0)
    credits_receivable = Column(Numeric(14, 2), nullable=False, default=0)
    pending_purchases = Column(Numeric(14, 2), nullable=False, default=0)

    cash_expected = Column(Numeric(14, 2), nullable=False, default=0)
    cash_difference = Column(Numeric(14, 2), nullable=False, default=0)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)