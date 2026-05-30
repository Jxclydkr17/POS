# app/db/models/issuer_profile.py
from app.utils.dt import utcnow
from sqlalchemy import Column, Integer, String, DateTime
from app.db.database import Base

class IssuerProfile(Base):
    __tablename__ = "issuer_profiles"

    id = Column(Integer, primary_key=True, index=True)

    legal_name = Column(String(120), nullable=False, default="Mi Negocio")
    commercial_name = Column(String(120), nullable=True)

    id_type = Column(String(2), nullable=False, default="02")
    id_number = Column(String(20), nullable=False, default="000000000")

    email = Column(String(160), nullable=False, default="facturacion@tudominio.com")
    phone = Column(String(30), nullable=True)

    provider_system_id = Column(String(20), nullable=True)
    economic_activity_code = Column(String(6), nullable=True)

    # Ubicación
    provincia = Column(String(1), nullable=True)
    canton = Column(String(2), nullable=True)
    distrito = Column(String(2), nullable=True)
    barrio = Column(String(50), nullable=True)
    otras_senas = Column(String(250), nullable=True)

    # Sucursal / terminal
    branch_code = Column(String(3), nullable=False, default="001")
    terminal_code = Column(String(5), nullable=False, default="00001")

    # REP
    enable_rep = Column(Integer, nullable=False, default=0)
    rep_default_condicion_venta = Column(String(2), nullable=True)
    rep_default_codigo_referencia = Column(String(2), nullable=True)

    phone_country_code = Column(String(3), nullable=True, default="506")

    created_at = Column(DateTime, default=utcnow)