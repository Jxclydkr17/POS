"""
app/utils/hacienda_api.py — Funciones utilitarias para envío a Hacienda

FASE 5 FIX: Integración con cola offline.
Cuando falla por ConnectionError/Timeout, el comprobante se encola
automáticamente para reenvío cuando haya internet.
"""
from __future__ import annotations

import base64
import logging

import requests
from sqlalchemy.orm import Session

from app.db.models.electronic_invoice import ElectronicInvoice
from app.db.models.electronic_rep import ElectronicRep
from app.db.models.issuer_profile import IssuerProfile
from app.db.models.customer import Customer
from app.db.models.sale import Sale
from app.einvoice.hacienda_client import (
    get_hacienda_client,
    HaciendaAuthError,
    HaciendaSendError,
    HaciendaConfigError,
)
from app.utils.dt import utcnow, to_cr_iso
from app.einvoice.xml_builder_v44 import extract_fecha_emision
from app.constants.status_enums import InvoiceStatus

logger = logging.getLogger(__name__)


def _extract_receptor_from_sale(db: Session, sale: Sale) -> tuple[str | None, str | None]:
    """Extrae tipo y número de identificación del receptor desde la venta."""
    if not sale.customer_id:
        return None, None
    customer = db.query(Customer).filter(Customer.id == sale.customer_id).first()
    if not customer:
        return None, None
    return (
        getattr(customer, "id_type", None),
        getattr(customer, "id_number", None),
    )


def _enqueue_offline(db: Session, einvoice_id: int, error: str) -> None:
    """Encola un comprobante para reenvío offline (no falla si el módulo no existe)."""
    try:
        from app.services.offline_queue import enqueue_for_retry
        enqueue_for_retry(db, einvoice_id, error)
    except Exception as e:
        logger.warning(f"No se pudo encolar offline einvoice {einvoice_id}: {e}")


def send_einvoice_to_hacienda(db: Session, einvoice_id: int) -> dict:
    """
    Envía un ElectronicInvoice a Hacienda.

    FASE 5: Si falla por problemas de red (ConnectionError, Timeout),
    encola automáticamente para reenvío cuando haya internet.
    """
    einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.id == einvoice_id).first()
    if not einv:
        raise ValueError(f"ElectronicInvoice {einvoice_id} no existe")

    if einv.status not in ("XML_READY", "SEND_ERROR"):
        raise ValueError(
            f"Solo se puede enviar con status XML_READY o SEND_ERROR. "
            f"Actual: {einv.status}"
        )

    if not einv.xml_signed:
        raise ValueError("No hay XML firmado. Ejecutá build-xml primero.")

    if not einv.clave:
        raise ValueError("No hay clave generada.")

    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise ValueError("No existe IssuerProfile.")

    sale = db.query(Sale).filter(Sale.id == einv.sale_id).first()
    receptor_tipo, receptor_numero = None, None
    if sale:
        receptor_tipo, receptor_numero = _extract_receptor_from_sale(db, sale)

    # FASE 2.1 — Fix 2.1: usar TZ_CR explícita en lugar de la TZ del sistema.
    # Hacienda requiere `fecha` con offset -06:00; `astimezone()` sin argumento
    # devolvía la TZ del SO (problema si la PC estaba mal configurada).
    # Consistencia de fechas: `fecha` debe coincidir con la FechaEmision del
    # comprobante (y con la fecha de su clave). La fuente de verdad es el XML
    # ya firmado, NO sale.created_at (que puede ser de otro día en ventas
    # encoladas o reintentos).
    fecha = extract_fecha_emision(einv.xml_signed)
    if not fecha:
        fecha = to_cr_iso(sale.created_at) if (sale and sale.created_at) else to_cr_iso(None)

    xml_b64 = base64.b64encode(einv.xml_signed.encode("utf-8")).decode("ascii")

    client = get_hacienda_client()

    try:
        result = client.send_document(
            clave=einv.clave,
            fecha=fecha,
            emisor_tipo=issuer.id_type,
            emisor_numero=issuer.id_number,
            receptor_tipo=receptor_tipo,
            receptor_numero=receptor_numero,
            xml_base64=xml_b64,
        )

        einv.status = InvoiceStatus.SENT
        einv.sent_at = utcnow()
        einv.tries = (einv.tries or 0) + 1
        einv.last_error = None
        einv.hacienda_status = result.get("status", "RECIBIDO")
        db.commit()

        logger.info(f"Comprobante enviado OK | id={einv.id} | clave={einv.clave}")
        return {
            "success": True,
            "einvoice_id": einv.id,
            "status": einv.status,
            "hacienda_status": einv.hacienda_status,
            "tries": einv.tries,
        }

    except HaciendaSendError as e:
        # ── FASE 5: Detectar errores de red y encolar offline ──
        is_network_error = (
            "No se pudo conectar" in str(e) or
            "Timeout" in str(e) or
            isinstance(e.__cause__, (requests.ConnectionError, requests.Timeout))
        )

        if is_network_error:
            logger.warning(
                f"Sin conexión a Hacienda, encolando offline | "
                f"id={einv.id} | error={e}"
            )
            _enqueue_offline(db, einv.id, str(e))
            return {
                "success": False,
                "einvoice_id": einv.id,
                "status": InvoiceStatus.QUEUED,
                "error": "Sin conexión. Encolado para reenvío automático.",
                "offline": True,
                "tries": (einv.tries or 0) + 1,
            }

        # Error no de red (rechazo de Hacienda, datos inválidos, etc.)
        einv.tries = (einv.tries or 0) + 1
        einv.last_error = str(e)[:500]
        einv.status = "SEND_ERROR"
        db.commit()

        logger.error(f"Error enviando comprobante | id={einv.id} | error={e}")
        return {
            "success": False,
            "einvoice_id": einv.id,
            "status": einv.status,
            "error": str(e),
            "tries": einv.tries,
        }

    except (HaciendaAuthError, HaciendaConfigError) as e:
        einv.tries = (einv.tries or 0) + 1
        einv.last_error = str(e)[:500]
        einv.status = "SEND_ERROR"
        db.commit()

        logger.error(f"Error enviando comprobante | id={einv.id} | error={e}")
        return {
            "success": False,
            "einvoice_id": einv.id,
            "status": einv.status,
            "error": str(e),
            "tries": einv.tries,
        }


def check_einvoice_status(db: Session, einvoice_id: int) -> dict:
    """Consulta el estado de un comprobante en Hacienda y actualiza la BD."""
    einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.id == einvoice_id).first()
    if not einv:
        raise ValueError(f"ElectronicInvoice {einvoice_id} no existe")

    if not einv.clave:
        raise ValueError("No hay clave para consultar.")

    if einv.status in (InvoiceStatus.ACCEPTED, InvoiceStatus.REJECTED):
        return {
            "einvoice_id": einv.id,
            "status": einv.status,
            "hacienda_status": einv.hacienda_status,
            "already_resolved": True,
        }

    client = get_hacienda_client()

    try:
        result = client.check_status(einv.clave)
    except (HaciendaAuthError, HaciendaSendError, HaciendaConfigError) as e:
        logger.error(f"Error consultando estado | id={einv.id} | error={e}")
        return {
            "einvoice_id": einv.id,
            "status": einv.status,
            "error": str(e),
        }

    ind_estado = result.get("ind_estado", "DESCONOCIDO")
    resp_xml_b64 = result.get("respuesta_xml", "")

    resp_xml = ""
    if resp_xml_b64:
        try:
            resp_xml = base64.b64decode(resp_xml_b64).decode("utf-8")
        except Exception:
            resp_xml = resp_xml_b64

    if ind_estado in ("aceptado", "ACEPTADO", "1"):
        einv.status = InvoiceStatus.ACCEPTED
        einv.hacienda_status = "ACEPTADO"
        einv.hacienda_response = resp_xml
        einv.resolved_at = utcnow()

    elif ind_estado in ("rechazado", "RECHAZADO", "3"):
        einv.status = InvoiceStatus.REJECTED
        einv.hacienda_status = "RECHAZADO"
        einv.hacienda_response = resp_xml
        einv.resolved_at = utcnow()
        einv.last_error = "Rechazado por Hacienda"

    elif ind_estado in ("procesando", "PROCESANDO", "recibido", "RECIBIDO"):
        einv.hacienda_status = ind_estado.upper()

    elif ind_estado == "NO_ENCONTRADO":
        einv.hacienda_status = "NO_ENCONTRADO"
        einv.last_error = "Comprobante no encontrado en Hacienda"

    else:
        einv.hacienda_status = ind_estado

    db.commit()

    logger.info(f"Estado actualizado | id={einv.id} | hacienda={einv.hacienda_status}")

    return {
        "einvoice_id": einv.id,
        "status": einv.status,
        "hacienda_status": einv.hacienda_status,
        "resolved": einv.status in (InvoiceStatus.ACCEPTED, InvoiceStatus.REJECTED),
        "has_response": bool(resp_xml),
    }


# ═══════════════════════════════════════════════════════════════
# ElectronicRep (REP)
# ═══════════════════════════════════════════════════════════════

def send_rep_to_hacienda(db: Session, rep_id: int) -> dict:
    """Envía un ElectronicRep a Hacienda."""
    rep = db.query(ElectronicRep).filter(ElectronicRep.id == rep_id).first()
    if not rep:
        raise ValueError(f"ElectronicRep {rep_id} no existe")

    if rep.status not in ("XML_READY", "SEND_ERROR"):
        raise ValueError(f"Solo se puede enviar con status XML_READY o SEND_ERROR. Actual: {rep.status}")

    if not rep.xml_signed or not rep.clave:
        raise ValueError("No hay XML firmado o clave generada.")

    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise ValueError("No existe IssuerProfile.")

    customer = db.query(Customer).filter(Customer.id == rep.customer_id).first()
    receptor_tipo = getattr(customer, "id_type", None) if customer else None
    receptor_numero = getattr(customer, "id_number", None) if customer else None

    # FASE 2.1 — Fix 2.1: garantizar offset -06:00 también para REPs.
    # Consistencia: `fecha` se toma de la FechaEmision del XML firmado (fuente
    # de verdad), no de rep.created_at.
    fecha = extract_fecha_emision(rep.xml_signed) or to_cr_iso(rep.created_at)
    xml_b64 = base64.b64encode(rep.xml_signed.encode("utf-8")).decode("ascii")

    client = get_hacienda_client()

    try:
        result = client.send_document(
            clave=rep.clave,
            fecha=fecha,
            emisor_tipo=issuer.id_type,
            emisor_numero=issuer.id_number,
            receptor_tipo=receptor_tipo,
            receptor_numero=receptor_numero,
            xml_base64=xml_b64,
        )

        rep.status = InvoiceStatus.SENT
        rep.sent_at = utcnow()
        rep.tries = (rep.tries or 0) + 1
        rep.last_error = None
        rep.hacienda_status = result.get("status", "RECIBIDO")
        db.commit()

        return {"success": True, "rep_id": rep.id, "status": rep.status}

    except (HaciendaAuthError, HaciendaSendError, HaciendaConfigError) as e:
        rep.tries = (rep.tries or 0) + 1
        rep.last_error = str(e)[:500]
        rep.status = "SEND_ERROR"
        db.commit()

        return {"success": False, "rep_id": rep.id, "error": str(e)}


def check_rep_status(db: Session, rep_id: int) -> dict:
    """Consulta el estado de un REP en Hacienda."""
    rep = db.query(ElectronicRep).filter(ElectronicRep.id == rep_id).first()
    if not rep:
        raise ValueError(f"ElectronicRep {rep_id} no existe")

    if not rep.clave:
        raise ValueError("No hay clave para consultar.")

    if rep.status in (InvoiceStatus.ACCEPTED, InvoiceStatus.REJECTED):
        return {"rep_id": rep.id, "status": rep.status, "already_resolved": True}

    client = get_hacienda_client()

    try:
        result = client.check_status(rep.clave)
    except Exception as e:
        return {"rep_id": rep.id, "status": rep.status, "error": str(e)}

    ind_estado = result.get("ind_estado", "DESCONOCIDO")
    resp_xml_b64 = result.get("respuesta_xml", "")

    resp_xml = ""
    if resp_xml_b64:
        try:
            resp_xml = base64.b64decode(resp_xml_b64).decode("utf-8")
        except Exception:
            resp_xml = resp_xml_b64

    if ind_estado in ("aceptado", "ACEPTADO", "1"):
        rep.status = InvoiceStatus.ACCEPTED
        rep.hacienda_status = "ACEPTADO"
        rep.hacienda_response = resp_xml
        rep.resolved_at = utcnow()
    elif ind_estado in ("rechazado", "RECHAZADO", "3"):
        rep.status = InvoiceStatus.REJECTED
        rep.hacienda_status = "RECHAZADO"
        rep.hacienda_response = resp_xml
        rep.resolved_at = utcnow()
    elif ind_estado in ("procesando", "PROCESANDO", "recibido", "RECIBIDO"):
        rep.hacienda_status = ind_estado.upper()

    db.commit()
    return {"rep_id": rep.id, "status": rep.status, "hacienda_status": rep.hacienda_status}