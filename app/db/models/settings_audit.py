# app/db/models/settings_audit.py
"""
Fase 6.4 — Log de auditoría de cambios en configuración.
Registra quién cambió qué y cuándo.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.db.database import Base
from app.utils.dt import utcnow


class SettingsAuditLog(Base):
    __tablename__ = "settings_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(100), nullable=True)
    action = Column(String(50), nullable=False)       # update_settings | update_issuer | update_cabys | upload_logo | backup | restore | import_config
    changes = Column(Text, nullable=True)              # JSON con los campos que cambiaron
    created_at = Column(DateTime, default=utcnow)