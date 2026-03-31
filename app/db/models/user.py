from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from app.utils.dt import utcnow
from app.db.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=True)
    role = Column(String(50), default="vendedor")  # admin, vendedor, cajero
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    def __repr__(self):
        return f"<User(username='{self.username}', role='{self.role}')>"