# app/schemas/secure_config.py
"""
Schemas para configuración de Hacienda y Email desde la UI.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ── Hacienda ──────────────────────────────────────────

class HaciendaConfigOut(BaseModel):
    """GET: nunca expone credenciales completas."""
    hacienda_env: str = "sandbox"
    hacienda_api: str = ""
    hacienda_user_hint: str = ""       # "usr...xyz"
    has_hacienda_user: bool = False
    has_hacienda_password: bool = False
    hacienda_cert_filename: str = ""   # "firma.p12"
    has_cert: bool = False
    cert_file_exists: bool = False


class HaciendaConfigUpdate(BaseModel):
    """PUT: campos opcionales, solo se actualizan los enviados."""
    hacienda_env: Optional[str] = Field(None, max_length=20)
    hacienda_api: Optional[str] = Field(None, max_length=500)
    hacienda_user: Optional[str] = Field(None, max_length=200)
    hacienda_password: Optional[str] = Field(None, max_length=500)


# ── Email ─────────────────────────────────────────────

class EmailConfigOut(BaseModel):
    """GET: nunca expone contraseña."""
    email_user_hint: str = ""
    has_email_user: bool = False
    has_email_pass: bool = False


class EmailConfigUpdate(BaseModel):
    """PUT: campos opcionales."""
    email_user: Optional[str] = Field(None, max_length=200)
    email_pass: Optional[str] = Field(None, max_length=500)