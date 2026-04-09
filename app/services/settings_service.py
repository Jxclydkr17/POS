# app/services/settings_service.py
"""
Servicio centralizado de configuración de negocio.

Fase 6: 6.2 currency helper, 6.4 audit logging.
"""

import os
import json
import logging
import requests
from decimal import Decimal
from sqlalchemy.orm import Session

from app.db.models.settings import Settings
from app.db.models.settings_audit import SettingsAuditLog
from app.schemas.settings import SettingsOut, SettingsUpdate


logger = logging.getLogger(__name__)

_FALLBACK_BUSINESS_NAME = "Mi Negocio"
_FALLBACK_TAX = "13"

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")


def _headers() -> dict:
    """Headers por defecto para llamadas internas a la API."""
    token = os.getenv("API_TOKEN", "")
    h = {"Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def get_settings(db: Session) -> Settings:
    """Obtiene la configuración actual (fila id=1). La crea si no existe."""
    settings = db.query(Settings).filter(Settings.id == 1).first()
    if not settings:
        settings = Settings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def get_settings_out(db: Session) -> SettingsOut:
    """Obtiene la configuración como schema Pydantic con supplier_name computado."""
    settings = get_settings(db)
    data = SettingsOut.model_validate(settings)
    data.supplier_name = settings.supplier.name if settings.supplier else None
    return data


def update_settings(db: Session, data: SettingsUpdate, user_id: int = None, username: str = None) -> SettingsOut:
    """Actualiza la configuración y retorna el schema actualizado."""
    settings = get_settings(db)
    update_data = data.model_dump(exclude_unset=True)

    # 6.4: Registrar qué cambió
    changes = {}
    for key, new_value in update_data.items():
        old_value = getattr(settings, key, None)
        if isinstance(new_value, Decimal):
            new_cmp = float(new_value)
            old_cmp = float(old_value) if old_value is not None else None
        else:
            new_cmp = new_value
            old_cmp = old_value
        if new_cmp != old_cmp:
            changes[key] = {"old": str(old_value), "new": str(new_value)}

    for key, value in update_data.items():
        setattr(settings, key, value)

    db.commit()
    db.refresh(settings)

    if changes:
        log_audit(db, "update_settings", changes, user_id=user_id, username=username)

    out = SettingsOut.model_validate(settings)
    out.supplier_name = settings.supplier.name if settings.supplier else None
    return out


# ─────────────────────────────────────────────────────────
# Helpers rápidos
# ─────────────────────────────────────────────────────────

def get_business_name(db: Session) -> str:
    settings = get_settings(db)
    return settings.business_name or _FALLBACK_BUSINESS_NAME


def get_business_info(db: Session) -> dict:
    """Retorna info del negocio desde IssuerProfile (con fallback a Settings)."""
    from app.db.models.issuer_profile import IssuerProfile
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    settings = get_settings(db)
    name = (
        (issuer.commercial_name or issuer.legal_name) if issuer
        else (settings.business_name or _FALLBACK_BUSINESS_NAME)
    )
    return {
        "name": name,
        "email": issuer.email if issuer else "facturacion@tudominio.com",
        "phone": issuer.phone if issuer else "",
        "address": issuer.otras_senas if issuer else "",
    }


def get_default_tax(db: Session) -> str:
    settings = get_settings(db)
    return settings.default_tax or _FALLBACK_TAX


def get_currency_info(db: Session) -> dict:
    """6.2: Retorna código de moneda y tipo de cambio para XML/facturación."""
    settings = get_settings(db)
    return {
        "currency_code": settings.default_currency or "CRC",
        "exchange_rate": str(settings.exchange_rate or Decimal("1.00")),
    }


# ─────────────────────────────────────────────────────────
# 6.4: Auditoría
# ─────────────────────────────────────────────────────────

def log_audit(db: Session, action: str, changes: dict = None,
              user_id: int = None, username: str = None):
    """Registra una entrada en el log de auditoría de settings."""
    try:
        entry = SettingsAuditLog(
            user_id=user_id,
            username=username,
            action=action,
            changes=json.dumps(changes, ensure_ascii=False, default=str) if changes else None,
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        logger.error(f"Error registrando auditoría: {e}")
        db.rollback()


def get_audit_log(db: Session, limit: int = 50) -> list:
    """Retorna las últimas N entradas del log de auditoría."""
    rows = (
        db.query(SettingsAuditLog)
        .order_by(SettingsAuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "username": r.username,
            "action": r.action,
            "changes": r.changes,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
        }
        for r in rows
    ]


# ─────────────────────────────────────────────────────────
# CONFIG-UI: Hacienda y Email (configuración desde la UI)
# ─────────────────────────────────────────────────────────

API_URL_HACIENDA_CONFIG = f"{BASE_URL}/settings/hacienda-config"
API_URL_HACIENDA_CERT = f"{BASE_URL}/settings/hacienda-cert"
API_URL_EMAIL_CONFIG = f"{BASE_URL}/settings/email-config"


def fetch_hacienda_config() -> dict:
    r = requests.get(API_URL_HACIENDA_CONFIG, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})


def save_hacienda_config(payload: dict) -> dict:
    headers = _headers()
    headers["Content-Type"] = "application/json"
    r = requests.put(API_URL_HACIENDA_CONFIG, headers=headers, json=payload, timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})


def upload_hacienda_cert(filepath: str, cert_password: str) -> dict:
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        files = {"file": (filename, f, "application/x-pkcs12")}
        data = {"cert_password": cert_password}
        r = requests.post(
            API_URL_HACIENDA_CERT, headers=_headers(),
            files=files, data=data, timeout=30,
        )
    r.raise_for_status()
    return r.json()


def fetch_email_config() -> dict:
    r = requests.get(API_URL_EMAIL_CONFIG, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})


def save_email_config(payload: dict) -> dict:
    headers = _headers()
    headers["Content-Type"] = "application/json"
    r = requests.put(API_URL_EMAIL_CONFIG, headers=headers, json=payload, timeout=10)
    r.raise_for_status()
    return r.json().get("data", {})