from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models.electronic_invoice import ElectronicInvoice
from app.core.dependencies import get_current_user
from app.utils.responses import success_response

from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
from app.db.models.customer import Customer
from app.db.models.issuer_profile import IssuerProfile
from app.einvoice.xml_builder import build_xml_for_sale, build_xml_for_nc, build_xml_for_nd

from app.einvoice.sequence import build_consecutivo, build_clave, next_sequence_number

# FASE 1
from app.einvoice.xsd_validator import validate_xml, get_validation_status
# FASE 2
from app.einvoice.xml_signer import sign_xml, is_signing_available
from app.core.config import settings, get_logo_path
# FASE 3
from app.utils.hacienda_api import send_einvoice_to_hacienda, check_einvoice_status
from app.constants.status_enums import InvoiceStatus
from app.einvoice.hacienda_client import (
    get_connection_status as _get_connection_status,
    HaciendaConfigError,
)
# FASE 4
from app.einvoice.hacienda_poller import get_pending_summary, parse_hacienda_response

import base64
import os
import logging
from app.utils.dt import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/einvoices", tags=["Facturación electrónica"])


def _try_sign_xml(xml: str) -> tuple[str, bool, str | None]:
    from app.core.credentials import hacienda_cert_path, hacienda_cert_pass
    cert_path = hacienda_cert_path()
    cert_pass = hacienda_cert_pass()
    if not cert_path or not cert_pass:
        return xml, False, None
    try:
        return sign_xml(xml, cert_path, cert_pass), True, None
    except FileNotFoundError as e:
        return xml, False, f"Certificado no encontrado: {e}"
    except ValueError as e:
        return xml, False, f"Error de certificado: {e}"
    except Exception as e:
        return xml, False, f"Error firmando XML: {e}"


# Mapa doc_type numerico a label para XSD/log
_DOC_LABELS = {"01": "FE", "02": "ND", "03": "NC", "04": "TE", "10": "REP"}


# -- GET por venta --
@router.get("/by-sale/{sale_id}", dependencies=[Depends(get_current_user)])
def get_einvoice_by_sale(sale_id: int, db: Session = Depends(get_db)):
    einv = (
        db.query(ElectronicInvoice)
        .filter(ElectronicInvoice.sale_id == sale_id)
        .order_by(ElectronicInvoice.id.desc()).first()
    )
    if not einv:
        raise HTTPException(status_code=404, detail="No existe registro electrónico para esta venta.")
    return {
        "id": einv.id, "sale_id": einv.sale_id, "document_type": einv.document_type,
        "status": einv.status, "clave": einv.clave, "consecutivo": einv.consecutivo,
        "tries": einv.tries, "last_error": einv.last_error, "hacienda_status": einv.hacienda_status,
    }


# -- GET batch por múltiples ventas (Fix 1.2) --
@router.post("/by-sales", dependencies=[Depends(get_current_user)])
def get_einvoices_by_sales(payload: dict, db: Session = Depends(get_db)):
    """
    Recibe {"sale_ids": [1, 2, 3, ...]} y retorna un dict {sale_id: einvoice_data}
    en UNA sola query. Reemplaza N requests individuales a /by-sale/{id}.
    """
    sale_ids = payload.get("sale_ids", [])
    if not sale_ids or not isinstance(sale_ids, list):
        return {}

    # Limitar a 500 IDs máx para evitar queries gigantes
    sale_ids = [int(sid) for sid in sale_ids[:500] if isinstance(sid, (int, float, str))]
    if not sale_ids:
        return {}

    # Sub-query: para cada sale_id, tomar el einvoice con id más alto
    from sqlalchemy import func as sa_func

    subq = (
        db.query(
            ElectronicInvoice.sale_id,
            sa_func.max(ElectronicInvoice.id).label("max_id"),
        )
        .filter(ElectronicInvoice.sale_id.in_(sale_ids))
        .group_by(ElectronicInvoice.sale_id)
        .subquery()
    )

    einvoices = (
        db.query(ElectronicInvoice)
        .join(subq, ElectronicInvoice.id == subq.c.max_id)
        .all()
    )

    result = {}
    for einv in einvoices:
        result[einv.sale_id] = {
            "id": einv.id, "sale_id": einv.sale_id,
            "document_type": einv.document_type,
            "status": einv.status, "clave": einv.clave,
            "consecutivo": einv.consecutivo, "tries": einv.tries,
            "last_error": einv.last_error,
            "hacienda_status": einv.hacienda_status,
        }

    return result


# -- SEND (Fase 3) --
@router.post("/{einvoice_id}/send", dependencies=[Depends(get_current_user)])
def send_einvoice(einvoice_id: int, db: Session = Depends(get_db)):
    einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.id == einvoice_id).first()
    if not einv:
        raise HTTPException(status_code=404, detail="Registro electrónico no encontrado.")
    if einv.status not in ("XML_READY", "SEND_ERROR"):
        raise HTTPException(status_code=400, detail=f"No se puede enviar con status '{einv.status}'. Debe ser XML_READY o SEND_ERROR.")
    try:
        result = send_einvoice_to_hacienda(db, einvoice_id)
    except HaciendaConfigError as e:
        raise HTTPException(status_code=400, detail=f"Configuración incompleta: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    msg = "Comprobante enviado a Hacienda correctamente." if result.get("success") else f"Error enviando: {result.get('error', 'desconocido')}"
    return success_response(message=msg, data=result)


# -- CHECK STATUS (Fase 3) --
@router.post("/{einvoice_id}/check-status", dependencies=[Depends(get_current_user)])
def check_status(einvoice_id: int, db: Session = Depends(get_db)):
    einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.id == einvoice_id).first()
    if not einv:
        raise HTTPException(status_code=404, detail="Registro electrónico no encontrado.")
    if not einv.clave:
        raise HTTPException(status_code=400, detail="No hay clave para consultar.")
    if einv.status not in (InvoiceStatus.SENT, InvoiceStatus.ACCEPTED, InvoiceStatus.REJECTED):
        raise HTTPException(status_code=400, detail=f"Solo se puede consultar comprobantes enviados. Status: {einv.status}")
    try:
        result = check_einvoice_status(db, einvoice_id)
    except HaciendaConfigError as e:
        raise HTTPException(status_code=400, detail=f"Configuración incompleta: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return success_response(message=f"Estado: {result.get('hacienda_status', 'desconocido')}", data=result)


# -- Callback (Fase 4) --
# FASE 2 — Fix 2.2: Usa Depends(get_db) en vez de SessionLocal() manual.
# Esto garantiza que la sesión se cierra siempre, incluso en errores
# no capturados, y sigue el mismo patrón que todos los demás endpoints.
@router.post("/callback")
async def hacienda_callback(request: Request, db: Session = Depends(get_db)):
    """
    Recibe notificaciones asíncronas de Hacienda sobre el estado de comprobantes.

    AUTENTICACIÓN — FASE 3.6 — Fix 3.6:
      Si `HACIENDA_CALLBACK_SECRET` está configurado en `.env`, el request
      debe incluir el mismo valor en uno de:
        - header `X-Callback-Token: <secret>`
        - query param `?token=<secret>`
      Sin token válido → 401.

      Si NO hay secret configurado:
        - localhost (127.0.0.1, ::1): se permite (compat con instalación local).
        - cualquier otro host: se permite por compat, pero se loguea warning
          recomendando configurar el secret.

      Comparación timing-safe con `hmac.compare_digest` para evitar
      timing attacks que pudieran inferir el secret carácter a carácter.

      Generar el secret con:
        python -c "import secrets; print(secrets.token_urlsafe(32))"
    """
    from app.db.models.electronic_rep import ElectronicRep
    from app.core.credentials import hacienda_callback_secret
    import hmac as _hmac

    # ── FASE 3.6 — Fix 3.6: autenticación del callback ──
    _secret = hacienda_callback_secret()
    _client_host = request.client.host if request.client else ""
    _is_localhost = _client_host in ("127.0.0.1", "::1", "localhost")

    if _secret:
        # Hay secret configurado → exigir token válido SIEMPRE
        provided = (
            request.headers.get("x-callback-token")
            or request.query_params.get("token")
            or ""
        )
        if not provided or not _hmac.compare_digest(provided, _secret):
            logger.warning(
                "Callback Hacienda RECHAZADO: token inválido | "
                "client=%s | provided=%s",
                _client_host or "?",
                "(none)" if not provided else f"...{provided[-4:]}",
            )
            raise HTTPException(status_code=401, detail="Token de callback inválido")
    else:
        # Sin secret configurado → permitir, pero advertir si no es local
        if not _is_localhost:
            logger.warning(
                "Callback Hacienda recibido SIN secret configurado, desde host "
                "no-local (%s). Configure HACIENDA_CALLBACK_SECRET en .env "
                "para proteger este endpoint.",
                _client_host,
            )

    try:
        body = await request.json()
    except Exception:
        return {"status": "ok"}
    clave = body.get("clave", "")
    ind_estado = body.get("indEstado", body.get("ind-estado", ""))
    resp_xml_b64 = body.get("respuestaXml", body.get("respuesta-xml", ""))
    if not clave:
        return {"status": "ok"}
    logger.info(f"Callback Hacienda | clave=...{clave[-8:]} | estado={ind_estado}")
    resp_xml = ""
    if resp_xml_b64:
        try:
            resp_xml = base64.b64decode(resp_xml_b64).decode("utf-8")
        except Exception:
            resp_xml = resp_xml_b64
    try:
        einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.clave == clave).first()
        if einv:
            _apply_callback_status(einv, ind_estado, resp_xml)
            db.commit()
        else:
            rep = db.query(ElectronicRep).filter(ElectronicRep.clave == clave).first()
            if rep:
                _apply_callback_status(rep, ind_estado, resp_xml)
                db.commit()
    except Exception as e:
        logger.error(f"Callback error: {e}")
        db.rollback()
    return {"status": "ok"}


def _apply_callback_status(record, ind_estado: str, resp_xml: str):
    ind = (ind_estado or "").upper().strip()
    if ind in ("ACEPTADO", "1"):
        record.status = InvoiceStatus.ACCEPTED
        record.hacienda_status = "ACEPTADO"
    elif ind in ("RECHAZADO", "3"):
        record.status = InvoiceStatus.REJECTED
        record.hacienda_status = "RECHAZADO"
        record.last_error = "Rechazado por Hacienda"
    elif ind in ("PROCESANDO", "RECIBIDO"):
        record.hacienda_status = ind
    else:
        record.hacienda_status = ind_estado or "DESCONOCIDO"
    if resp_xml:
        record.hacienda_response = resp_xml
    if record.status in (InvoiceStatus.ACCEPTED, InvoiceStatus.REJECTED):
        record.resolved_at = utcnow()
        if resp_xml and record.status == InvoiceStatus.REJECTED:
            parsed = parse_hacienda_response(resp_xml)
            if parsed.get("detalle_mensaje"):
                record.last_error = f"Rechazado: {parsed['detalle_mensaje'][:400]}"


# -- Pendientes (Fase 4) --
@router.get("/pending-summary", dependencies=[Depends(get_current_user)])
def pending_summary():
    return get_pending_summary()


# -- Detalle respuesta Hacienda (Fase 4) --
@router.get("/{einvoice_id}/hacienda-response", dependencies=[Depends(get_current_user)])
def get_hacienda_response(einvoice_id: int, db: Session = Depends(get_db)):
    einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.id == einvoice_id).first()
    if not einv:
        raise HTTPException(status_code=404, detail="ElectronicInvoice no existe")
    result = {
        "einvoice_id": einv.id, "status": einv.status,
        "hacienda_status": einv.hacienda_status,
        "has_response": bool(einv.hacienda_response),
        "response_xml": einv.hacienda_response, "parsed": None,
    }
    if einv.hacienda_response:
        result["parsed"] = parse_hacienda_response(einv.hacienda_response)
    return result


# ================================================================
# BUILD XML — FASE 1.1 (Fix 1.1): Asignación atómica de consecutivo
# ================================================================
#
# Antes: este endpoint asignaba el consecutivo de DocumentSequence al
# inicio, construía el XML, y si la construcción fallaba, el consecutivo
# quedaba gastado para siempre, generando huecos en la secuencia.
#
# Ahora: el flujo es atómico. Se construye el XML con un consecutivo
# placeholder (NO se incrementa DocumentSequence aún). Se valida XSD.
# Solo si todo pasa, se reserva el consecutivo real con
# `next_sequence_number()` y se reconstruye el XML con él. Esto
# garantiza que cada incremento en DocumentSequence corresponde a un
# XML válido que se va a firmar y enviar.
#
# Caso de reintento: si el einv YA tiene consecutivo/clave (por ejemplo,
# pasó XSD/sign en un intento previo pero falló al enviar), se reutiliza
# en lugar de reservar uno nuevo. Esto preserva el consecutivo gastado.
# ================================================================
@router.post("/{einvoice_id}/build-xml", dependencies=[Depends(get_current_user)])
def build_xml(einvoice_id: int, db: Session = Depends(get_db)):
    einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.id == einvoice_id).first()
    if not einv:
        raise HTTPException(status_code=404, detail="ElectronicInvoice no existe")

    sale = db.query(Sale).filter(Sale.id == einv.sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale no existe")

    details = db.query(SaleDetail).filter(SaleDetail.sale_id == sale.id).all()
    if not details:
        raise HTTPException(status_code=400, detail="La venta no tiene detalles")

    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise HTTPException(status_code=400, detail="No existe issuer_profile")

    # El document_type viene del ElectronicInvoice, no del Sale
    # "01"=FE, "02"=ND, "03"=NC, "04"=TE
    doc_type = einv.document_type
    doc_label = _DOC_LABELS.get(doc_type, "FE")

    branch = (issuer.branch_code or "001").zfill(3)
    terminal = (issuer.terminal_code or "00001").zfill(5)

    customer = getattr(sale, "customer", None)

    # Para NC/ND, ubicamos el documento original UNA vez (se usa en ambas
    # construcciones: dry-run y real).
    original_einv = None
    if doc_type == "03":
        original_einv = _find_original_einv(db, sale.id, einv.id)
    elif doc_type == "02":
        original_einv = _find_original_einv(db, sale.id, einv.id)
    elif doc_type not in ("01", "04"):
        raise HTTPException(status_code=400, detail=f"Tipo de documento no soportado para build-xml: {doc_type}")

    # Helper interno: construye el XML para este einv con el consecutivo
    # y clave dados. Se invoca dos veces: una en dry-run, otra con el
    # consecutivo real reservado.
    def _build_with(_clave: str, _consecutivo: str) -> str:
        if doc_type in ("01", "04"):
            return build_xml_for_sale(
                db, sale=sale, sale_details=details,
                clave=_clave, consecutivo=_consecutivo, customer=customer,
            )
        elif doc_type == "03":
            return build_xml_for_nc(
                db, sale=sale, sale_details=details,
                clave=_clave, consecutivo=_consecutivo, customer=customer,
                original_einv=original_einv,
            )
        elif doc_type == "02":
            return build_xml_for_nd(
                db, sale=sale, sale_details=details,
                clave=_clave, consecutivo=_consecutivo, customer=customer,
                original_einv=original_einv,
            )
        else:
            # Defensivo; ya validamos arriba
            raise HTTPException(status_code=400, detail=f"Tipo de documento no soportado: {doc_type}")

    # ── Caso reintento: einv ya tiene consecutivo asignado ──
    # Si llegamos aquí con consecutivo/clave ya asignados (intento
    # previo que pasó XSD pero falló en otro paso), reutilizamos los
    # mismos en lugar de reservar uno nuevo.
    if einv.consecutivo and einv.clave:
        consecutivo = einv.consecutivo
        clave = einv.clave
        try:
            xml = _build_with(clave, consecutivo)
        except Exception as e:
            # El XML ya no se puede construir aunque tengamos consecutivo
            # (probablemente bug nuevo o datos corruptos). Marcar error
            # SIN tocar el consecutivo (ya está en BD).
            einv.status = "ERROR"
            einv.last_error = f"Reintento de build-xml falló: {e}"[:500]
            db.commit()
            raise HTTPException(
                status_code=422,
                detail={"message": "Error reconstruyendo XML", "error": str(e), "einvoice_id": einv.id},
            )

        xsd_errors = validate_xml(xml, doc_label)
        if xsd_errors:
            einv.xml_signed = xml
            einv.status = "XSD_ERROR"
            einv.last_error = "; ".join(xsd_errors[:5])
            db.commit()
            raise HTTPException(
                status_code=422,
                detail={"message": "XML no paso XSD", "errors": xsd_errors[:10], "einvoice_id": einv.id},
            )

        # Firmar
        xml_final, was_signed, sign_error = _try_sign_xml(xml)
        einv.xml_signed = xml_final
        einv.last_error = sign_error
        if sign_error:
            einv.status = "SIGN_ERROR"
        elif was_signed:
            einv.status = "XML_READY"
        else:
            einv.status = "XML_UNSIGNED"
        db.commit()

        return success_response(
            message=("XML generado y firmado correctamente" if was_signed
                     else "XML generado (sin firma)" if not sign_error
                     else f"Firma fallo: {sign_error}"),
            data={
                "id": einv.id, "status": einv.status, "clave": clave,
                "consecutivo": consecutivo, "doc_type": doc_label,
                "xsd_validated": True, "signed": was_signed,
                "sign_error": sign_error,
            },
        )

    # ── Primer intento: dry-run con consecutivo placeholder ──
    # Construimos el XML con un consecutivo "candidato" SIN reservar
    # número real en DocumentSequence. Si la construcción o el XSD
    # fallan, el consecutivo real nunca se incrementa.
    placeholder_seq = 1  # valor irrelevante; el XML se reconstruirá si pasa todo
    placeholder_consecutivo = build_consecutivo(branch, terminal, doc_type, placeholder_seq)
    placeholder_clave = build_clave(issuer.id_number, placeholder_consecutivo)

    try:
        xml_dry = _build_with(placeholder_clave, placeholder_consecutivo)
    except HTTPException:
        raise
    except Exception as e:
        # Error de construcción del XML — NO gastar consecutivo.
        einv.status = "ERROR"
        einv.last_error = f"Construcción XML falló: {e}"[:500]
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={"message": "No se pudo construir el XML", "error": str(e), "einvoice_id": einv.id},
        )

    # XSD del dry-run: detecta errores estructurales antes de gastar consecutivo
    xsd_errors = validate_xml(xml_dry, doc_label)
    if xsd_errors:
        einv.status = "XSD_ERROR"
        einv.last_error = "; ".join(xsd_errors[:5])
        # Guardamos el XML de dry-run como referencia diagnóstica.
        # NOTA: tiene consecutivo placeholder, NO sirve para enviar.
        einv.xml_signed = xml_dry
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={"message": "XML no paso XSD", "errors": xsd_errors[:10], "einvoice_id": einv.id},
        )

    # ── Todo OK: AHORA SÍ reservar consecutivo real ──
    # `next_sequence_number` incrementa DocumentSequence (con lock pesimista
    # en MySQL). El commit final del db garantiza la persistencia atómica
    # junto con el resto de cambios al einv.
    seq = next_sequence_number(db, branch, terminal, doc_type)
    consecutivo = build_consecutivo(branch, terminal, doc_type, seq)
    clave = build_clave(issuer.id_number, consecutivo)

    # Reconstruir XML con consecutivo real (rápido: ~10ms)
    xml = _build_with(clave, consecutivo)

    # Firmar
    xml_final, was_signed, sign_error = _try_sign_xml(xml)

    einv.consecutivo = consecutivo
    einv.clave = clave
    einv.xml_signed = xml_final
    einv.last_error = sign_error
    if sign_error:
        einv.status = "SIGN_ERROR"
    elif was_signed:
        einv.status = "XML_READY"
    else:
        einv.status = "XML_UNSIGNED"
    db.commit()

    return success_response(
        message=("XML generado y firmado correctamente" if was_signed
                 else "XML generado (sin firma)" if not sign_error
                 else f"Firma fallo: {sign_error}"),
        data={
            "id": einv.id, "status": einv.status, "clave": clave,
            "consecutivo": consecutivo, "doc_type": doc_label,
            "xsd_validated": True, "signed": was_signed,
            "sign_error": sign_error,
        },
    )


def _find_original_einv(db: Session, sale_id: int, current_einv_id: int):
    """
    Busca el ElectronicInvoice original (FE/TE) para una NC o ND.
    El original es el que tiene document_type 01 o 04 para la misma venta.
    """
    original = (
        db.query(ElectronicInvoice)
        .filter(
            ElectronicInvoice.sale_id == sale_id,
            ElectronicInvoice.document_type.in_(["01", "04"]),
            ElectronicInvoice.id != current_einv_id,
        )
        .order_by(ElectronicInvoice.id.asc())
        .first()
    )
    if not original:
        raise HTTPException(
            status_code=400,
            detail="No se encontro el comprobante original (FE/TE) para esta venta. "
                   "La NC/ND necesita un documento de referencia."
        )
    return original


# -- BUILD + SEND (Fase 3) --
@router.post("/{einvoice_id}/build-and-send", dependencies=[Depends(get_current_user)])
def build_and_send(einvoice_id: int, db: Session = Depends(get_db)):
    build_result = build_xml(einvoice_id, db)
    einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.id == einvoice_id).first()
    if einv.status != "XML_READY":
        return success_response(message=f"XML generado pero no enviable (status: {einv.status})", data={"build_status": einv.status, "sent": False, "sign_error": einv.last_error})
    try:
        send_result = send_einvoice_to_hacienda(db, einvoice_id)
    except HaciendaConfigError as e:
        return success_response(message=f"XML listo pero sin enviar: {e}", data={"build_status": "XML_READY", "sent": False, "error": str(e)})
    return success_response(
        message="Comprobante generado, firmado y enviado" if send_result.get("success") else f"Error: {send_result.get('error', '')}",
        data={"build_status": "XML_READY", "sent": send_result.get("success", False), **send_result}
    )


# -- PREVIEW V44 --
@router.get("/preview-v44/{sale_id}", dependencies=[Depends(get_current_user)])
def preview_v44(sale_id: int, db: Session = Depends(get_db)):
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale no existe")
    details = db.query(SaleDetail).filter(SaleDetail.sale_id == sale_id).all()
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer or not details:
        raise HTTPException(status_code=400, detail="Faltan datos para preview")
    doc_type = sale.document_type
    consecutivo = build_consecutivo(issuer.branch_code, issuer.terminal_code, doc_type, 9999999999)
    clave = build_clave(issuer.id_number, consecutivo)
    customer = getattr(sale, "customer", None)
    xml = build_xml_for_sale(db, sale=sale, sale_details=details, clave=clave, consecutivo=consecutivo, customer=customer)
    doc_label = _DOC_LABELS.get(doc_type, "FE")
    xsd_errors = validate_xml(xml, doc_label)
    return {"ok": True, "doc": doc_label, "xml": xml, "xsd_valid": len(xsd_errors) == 0, "xsd_errors": xsd_errors[:10] if xsd_errors else []}


# -- DIAGNOSTICO --
@router.get("/xsd-status", dependencies=[Depends(get_current_user)])
def xsd_status():
    return get_validation_status()

@router.get("/signing-status", dependencies=[Depends(get_current_user)])
def signing_status():
    from app.core.credentials import hacienda_cert_path, hacienda_cert_pass
    return is_signing_available(hacienda_cert_path(), hacienda_cert_pass())

@router.get("/connection-status", dependencies=[Depends(get_current_user)])
def connection_status():
    return _get_connection_status()


# -- Re-firmar (Fase 2) --
@router.post("/{einvoice_id}/re-sign", dependencies=[Depends(get_current_user)])
def re_sign(einvoice_id: int, db: Session = Depends(get_db)):
    einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.id == einvoice_id).first()
    if not einv:
        raise HTTPException(status_code=404, detail="ElectronicInvoice no existe")
    if einv.status not in ("SIGN_ERROR", "XML_UNSIGNED", "XSD_ERROR"):
        raise HTTPException(status_code=400, detail=f"Solo refirmar SIGN_ERROR/XML_UNSIGNED/XSD_ERROR. Actual: {einv.status}")
    if not einv.xml_signed:
        raise HTTPException(status_code=400, detail="No hay XML. Usa build-xml primero.")
    xml_to_sign = einv.xml_signed
    if "<ds:Signature" in xml_to_sign or "<Signature" in xml_to_sign:
        try:
            from lxml import etree
            doc = etree.fromstring(xml_to_sign.encode("utf-8"))
            for sig in doc.findall(".//{http://www.w3.org/2000/09/xmldsig#}Signature"):
                sig.getparent().remove(sig)
            xml_to_sign = etree.tostring(doc, encoding="utf-8", xml_declaration=True).decode("utf-8")
        except Exception:
            pass
    xml_final, was_signed, sign_error = _try_sign_xml(xml_to_sign)
    if sign_error:
        einv.last_error = sign_error
        einv.status = "SIGN_ERROR"
        db.commit()
        raise HTTPException(status_code=422, detail=f"Error firmando: {sign_error}")
    if not was_signed:
        raise HTTPException(status_code=400, detail="No hay certificado configurado.")
    einv.xml_signed = xml_final
    einv.status = "XML_READY"
    einv.last_error = None
    db.commit()
    return success_response(message="XML refirmado correctamente", data={"id": einv.id, "status": einv.status, "signed": True})


# ================================================================
# FASE 3: PDF de representación gráfica con QR
# ================================================================
@router.get("/{einvoice_id}/pdf", dependencies=[Depends(get_current_user)])
def generate_pdf(einvoice_id: int, db: Session = Depends(get_db)):
    """
    Genera y retorna el PDF de representación gráfica del comprobante.
    Incluye QR con URL de verificación de Hacienda.
    """
    try:
        from app.services.einvoice_pdf import generate_einvoice_pdf

        # Buscar logo del emisor (ruta absoluta portable para .exe)
        logo = get_logo_path()

        pdf_path = generate_einvoice_pdf(db, einvoice_id, logo_path=logo)
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=os.path.basename(pdf_path),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generando PDF para einvoice {einvoice_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al generar el PDF del comprobante.")


# ================================================================
# FASE 3: Impresión de ticket térmico conectada al flujo electrónico
# ================================================================
@router.post("/{einvoice_id}/print-ticket", dependencies=[Depends(get_current_user)])
def print_einvoice_ticket_endpoint(einvoice_id: int, db: Session = Depends(get_db)):
    """
    Imprime un comprobante electrónico respetando la configuración de
    impresora del usuario (Settings → Impresora).

    Modos según `printer_type`:
      - "network": ESC/POS por TCP a printer_ip:printer_port.
      - "usb":     ESC/POS por USB a printer_usb_vendor_id/_product_id.
      - "none":    no imprime, solo retorna el path del PDF para que
                   el frontend lo muestre o lo abra manualmente.
      - cualquier otro / NULL: fallback a PDF via SO (universal).

    Siempre se genera el PDF (sirve de respaldo y para visualizar
    desde la UI), aunque se imprima por térmica directa.

    Fix 2.5 (cerrado): antes este endpoint mandaba el PDF al spool del
    SO sin distinguir el tipo de impresora configurado. Ahora cumple
    la promesa que la UI hacía (vista de Settings) y SÍ usa la térmica
    cuando está configurada.
    """
    # NOTA: renombrado de print_einvoice_ticket → print_einvoice_ticket_endpoint
    # para evitar colisión de nombre con la función homónima de
    # app.utils.print_ticket que importamos abajo. El path de FastAPI
    # /einvoices/{id}/print-ticket no cambia (lo controla @router.post).
    try:
        from app.utils.print_ticket import print_einvoice_ticket as _print
        from app.services.einvoice_pdf import generate_einvoice_pdf
        from app.services.settings_service import get_settings

        settings = get_settings(db)
        printer_type = (settings.printer_type or "").lower() if settings else ""

        # Modo "none" → no imprimimos, solo generamos el PDF.
        if printer_type == "none":
            logo = get_logo_path()
            pdf_path = generate_einvoice_pdf(db, einvoice_id, logo_path=logo)
            return success_response(
                message="Impresión deshabilitada en Configuración (PDF generado)",
                data={"einvoice_id": einvoice_id, "pdf_path": pdf_path, "printed": False}
            )

        # Térmica directa (ESC/POS) vs PDF via SO
        use_thermal = printer_type in ("network", "usb")

        # Parser de USB IDs: vienen como hex string "0x04b8" → int.
        def _parse_usb_id(v):
            if not v:
                return None
            s = str(v).strip().lower()
            if s.startswith("0x"):
                s = s[2:]
            try:
                return int(s, 16)
            except ValueError:
                return None

        kwargs = dict(
            use_thermal=use_thermal,
            thermal_kind=printer_type if use_thermal else "network",
        )
        if use_thermal and printer_type == "network":
            kwargs["thermal_ip"] = settings.printer_ip if settings else None
            kwargs["thermal_port"] = settings.printer_port if settings else None
        elif use_thermal and printer_type == "usb":
            kwargs["thermal_usb_vendor_id"] = _parse_usb_id(
                getattr(settings, "printer_usb_vendor_id", None)
            )
            kwargs["thermal_usb_product_id"] = _parse_usb_id(
                getattr(settings, "printer_usb_product_id", None)
            )

        if use_thermal:
            kwargs["paper_width_mm"] = getattr(settings, "printer_paper_width_mm", None) or 80
            kwargs["profile"] = getattr(settings, "printer_profile", None)

        pdf_path = _print(db, einvoice_id, **kwargs)

        return success_response(
            message="Ticket enviado a impresora",
            data={
                "einvoice_id": einvoice_id,
                "pdf_path": pdf_path,
                "printed": True,
                "mode": printer_type or "system",
            },
        )
    except ValueError as e:
        # Configuración faltante (e.g. USB sin vendor_id) o einvoice
        # inexistente — 400 es el código correcto.
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConnectionError as e:
        # Térmica de red caída / USB no encontrada.
        logger.error(f"Conectividad de impresora para einvoice {einvoice_id}: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except RuntimeError as e:
        logger.error(f"Error de impresión para einvoice {einvoice_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al enviar a impresora.")


# ================================================================
# FASE 3: Build + Send + PDF en un solo flujo
# ================================================================
@router.post("/{einvoice_id}/full-flow", dependencies=[Depends(get_current_user)])
def full_einvoice_flow(einvoice_id: int, db: Session = Depends(get_db)):
    """
    Flujo completo: Build XML → Firma → Envío → Genera PDF.
    Retorna el estado final y la ruta del PDF generado.
    """
    # Paso 1: Build + Send
    build_send_result = build_and_send(einvoice_id, db)

    # Paso 2: Generar PDF (independientemente del resultado de envío)
    pdf_path = None
    try:
        from app.services.einvoice_pdf import generate_einvoice_pdf
        logo = get_logo_path()
        pdf_path = generate_einvoice_pdf(db, einvoice_id, logo_path=logo)
    except Exception as e:
        logger.warning(f"PDF no generado para einvoice {einvoice_id}: {e}")

    return success_response(
    message="Flujo completo ejecutado",
    data={
        "einvoice_id": einvoice_id,
        "pdf_path": pdf_path,
        "pdf_generated": pdf_path is not None,
        # Agregamos paréntesis aquí:
        **(build_send_result.get("data", {}) or {}),
    }
)