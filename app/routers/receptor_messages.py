"""
app/routers/receptor_messages.py — Endpoints para MensajeReceptor v4.4

Permite aceptar o rechazar comprobantes electrónicos recibidos de proveedores.
Genera el XML del MensajeReceptor, lo firma y lo envía a Hacienda.

ENDPOINTS:
    POST /receptor/send-message    → Genera, firma y envía MensajeReceptor
    GET  /receptor/history         → Historial de mensajes enviados
"""
from __future__ import annotations

import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy import desc

from app.db.database import get_db, Base
from app.db.models.issuer_profile import IssuerProfile
from app.core.dependencies import get_current_user
from app.utils.responses import success_response
from app.utils.dt import utcnow

from app.einvoice.xml_builder_mensaje import build_mensaje_receptor
from app.einvoice.sequence import next_sequence_number, build_consecutivo
from app.einvoice.xml_signer import sign_xml
from app.einvoice.hacienda_client import (
    get_hacienda_client,
    HaciendaConfigError,
    HaciendaAuthError,
    HaciendaSendError,
)
from app.core.credentials import hacienda_cert_path, hacienda_cert_pass

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/receptor",
    tags=["MensajeReceptor"]
)


# ═══════════════════════════════════════════════════════════════
# Modelo para historial de mensajes (tabla ligera)
# ═══════════════════════════════════════════════════════════════

class ReceptorMessage(Base):
    """Historial de mensajes de aceptación/rechazo enviados como receptor."""
    __tablename__ = "receptor_messages"

    id = Column(Integer, primary_key=True, index=True)
    clave_comprobante = Column(String(50), nullable=False, index=True)
    cedula_emisor = Column(String(20), nullable=False)
    consecutivo = Column(String(20), nullable=True)
    mensaje = Column(Integer, nullable=False)  # 1, 2, 3
    detalle = Column(String(160), nullable=True)
    condicion_impuesto = Column(String(2), nullable=True)
    total_factura = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING/SENT/ACCEPTED/REJECTED/ERROR
    xml_signed = Column(Text, nullable=True)
    hacienda_response = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    sent_at = Column(DateTime, nullable=True)


# ═══════════════════════════════════════════════════════════════
# Schemas de request
# ═══════════════════════════════════════════════════════════════

class SendMessageRequest(BaseModel):
    """Request para enviar un MensajeReceptor."""
    clave_comprobante: str = Field(..., min_length=50, max_length=50, description="Clave de 50 dígitos del comprobante recibido")
    cedula_emisor: str = Field(..., min_length=9, max_length=20, description="Cédula del proveedor/emisor")
    mensaje: int = Field(..., ge=1, le=3, description="1=Aceptado, 2=Parcial, 3=Rechazado")
    total_factura: float = Field(..., gt=0, description="Total del comprobante")
    detalle_mensaje: str = Field("", max_length=160, description="Motivo (obligatorio si mensaje=2 o 3)")
    monto_total_impuesto: Optional[float] = Field(None, ge=0, description="Monto total de impuesto")
    codigo_actividad: Optional[str] = Field(None, max_length=6, description="Actividad económica del receptor")
    condicion_impuesto: Optional[str] = Field(None, max_length=2, description="Código nota 18: 01-05")
    monto_impuesto_acreditar: Optional[float] = Field(None, ge=0, description="Monto del IVA a acreditar")
    monto_gasto_aplicable: Optional[float] = Field(None, ge=0, description="Monto del gasto aplicable")


# ═══════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════

@router.post("/send-message", dependencies=[Depends(get_current_user)])
def send_receptor_message(req: SendMessageRequest, db: Session = Depends(get_db)):
    """
    Genera, firma y envía un MensajeReceptor a Hacienda.

    Flujo:
    1. Genera consecutivo tipo 05 (aceptación), 06 (parcial) o 07 (rechazo)
    2. Genera XML del MensajeReceptor
    3. Firma con XAdES-EPES
    4. Envía a Hacienda via POST /recepcion
    5. Guarda historial en receptor_messages
    """
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise HTTPException(status_code=400, detail="No existe IssuerProfile (emisor).")

    # Tipo de consecutivo según el mensaje
    # 05 = Confirmación de aceptación
    # 06 = Confirmación de aceptación parcial
    # 07 = Confirmación de rechazo
    tipo_consecutivo_map = {1: "05", 2: "06", 3: "07"}
    tipo_consecutivo = tipo_consecutivo_map[req.mensaje]

    branch = (issuer.branch_code or "001").zfill(3)
    terminal = (issuer.terminal_code or "00001").zfill(5)

    seq_num = next_sequence_number(db, branch, terminal, tipo_consecutivo)
    consecutivo = build_consecutivo(branch, terminal, tipo_consecutivo, seq_num)

    # ── Paso 1: Generar XML ──
    try:
        xml = build_mensaje_receptor(
            clave_comprobante=req.clave_comprobante,
            cedula_emisor=req.cedula_emisor,
            mensaje=req.mensaje,
            cedula_receptor=issuer.id_number,
            consecutivo_receptor=consecutivo,
            total_factura=req.total_factura,
            detalle_mensaje=req.detalle_mensaje,
            monto_total_impuesto=req.monto_total_impuesto,
            codigo_actividad=req.codigo_actividad or issuer.economic_activity_code,
            condicion_impuesto=req.condicion_impuesto,
            monto_impuesto_acreditar=req.monto_impuesto_acreditar,
            monto_gasto_aplicable=req.monto_gasto_aplicable,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Guardar registro
    record = ReceptorMessage(
        clave_comprobante=req.clave_comprobante,
        cedula_emisor=req.cedula_emisor,
        consecutivo=consecutivo,
        mensaje=req.mensaje,
        detalle=req.detalle_mensaje[:160] if req.detalle_mensaje else None,
        condicion_impuesto=req.condicion_impuesto,
        total_factura=str(req.total_factura),
        status="PENDING",
    )
    db.add(record)
    db.flush()
    record_id = record.id  # FASE 4: capturar antes de posibles rollbacks

    # ── Paso 2: Firmar ──
    cert_path = hacienda_cert_path()
    cert_pass = hacienda_cert_pass()
    was_signed = False

    if cert_path and cert_pass:
        try:
            xml = sign_xml(xml, cert_path, cert_pass)
            was_signed = True
        except Exception as e:
            record.last_error = f"Error firmando: {e}"
            record.status = "SIGN_ERROR"
            # FASE 4 — Fix 4.1: commit protegido
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.error("No se pudo persistir estado SIGN_ERROR del MensajeReceptor")
            raise HTTPException(status_code=422, detail=f"Error firmando MensajeReceptor: {e}")
    else:
        record.status = "XML_UNSIGNED"
        record.xml_signed = xml
        # FASE 4 — Fix 4.1: commit protegido
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.error("No se pudo persistir estado XML_UNSIGNED del MensajeReceptor")
        return success_response(
            message="MensajeReceptor generado pero sin firma (configurá HACIENDA_CERT_PATH en .env)",
            data={"id": record_id, "status": "XML_UNSIGNED", "signed": False}
        )

    record.xml_signed = xml

    # ── Paso 3: Enviar a Hacienda ──
    try:
        client = get_hacienda_client()

        xml_b64 = base64.b64encode(xml.encode("utf-8")).decode("ascii")

        result = client.send_document(
            clave=req.clave_comprobante,
            fecha=utcnow().isoformat(),
            emisor_tipo=_detect_id_type(req.cedula_emisor),
            emisor_numero=req.cedula_emisor,
            receptor_tipo=issuer.id_type,
            receptor_numero=issuer.id_number,
            xml_base64=xml_b64,
        )

        record.status = "SENT"
        record.sent_at = utcnow()
        # FASE 4 — Fix 4.1: commit protegido
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.error("No se pudo persistir estado SENT del MensajeReceptor")

        mensaje_labels = {1: "ACEPTADO", 2: "ACEPTADO PARCIAL", 3: "RECHAZADO"}
        return success_response(
            message=f"MensajeReceptor enviado: {mensaje_labels.get(req.mensaje, '?')}",
            data={
                "id": record_id,
                "status": "SENT",
                "consecutivo": consecutivo,
                "mensaje": req.mensaje,
                "signed": was_signed,
            }
        )

    except HaciendaConfigError as e:
        record.status = "XML_READY"
        record.last_error = f"Sin credenciales Hacienda: {e}"
        # FASE 4 — Fix 4.1: commit protegido
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.error("No se pudo persistir estado XML_READY del MensajeReceptor")
        return success_response(
            message=f"MensajeReceptor firmado pero no enviado: {e}",
            data={"id": record_id, "status": "XML_READY", "signed": True, "sent": False}
        )

    except (HaciendaAuthError, HaciendaSendError) as e:
        record.status = "SEND_ERROR"
        record.last_error = str(e)[:500]
        # FASE 4 — Fix 4.1: commit protegido
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.error("No se pudo persistir estado SEND_ERROR del MensajeReceptor")
        return success_response(
            message=f"Error enviando MensajeReceptor: {e}",
            data={"id": record_id, "status": "SEND_ERROR", "error": str(e)}
        )


@router.get("/history", dependencies=[Depends(get_current_user)])
def receptor_history(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Historial de mensajes de confirmación enviados como receptor."""
    records = (
        db.query(ReceptorMessage)
        .order_by(desc(ReceptorMessage.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    mensaje_labels = {1: "Aceptado", 2: "Aceptación parcial", 3: "Rechazado"}

    return [
        {
            "id": r.id,
            "clave_comprobante": r.clave_comprobante,
            "cedula_emisor": r.cedula_emisor,
            "consecutivo": r.consecutivo,
            "mensaje": r.mensaje,
            "mensaje_label": mensaje_labels.get(r.mensaje, "?"),
            "detalle": r.detalle,
            "condicion_impuesto": r.condicion_impuesto,
            "total_factura": r.total_factura,
            "status": r.status,
            "last_error": r.last_error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        }
        for r in records
    ]


# ═══════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════

def _detect_id_type(cedula: str) -> str:
    """Detecta tipo de identificación por la longitud de la cédula."""
    clean = cedula.strip()
    if len(clean) == 9:
        return "01"  # Física
    elif len(clean) == 10:
        return "02"  # Jurídica
    elif len(clean) in (11, 12):
        return "03"  # DIMEX
    else:
        return "01"  # Default