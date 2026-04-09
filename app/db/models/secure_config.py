# app/db/models/secure_config.py
"""
Almacén clave-valor encriptado para credenciales sensibles.
Reemplaza la necesidad de editar .env manualmente para:
  - Credenciales de Hacienda (usuario, password, cert)
  - Credenciales de email
  - Cualquier secreto futuro
"""
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.db.database import Base
from app.utils.dt import utcnow


class SecureConfig(Base):
    __tablename__ = "secure_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value_encrypted = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)