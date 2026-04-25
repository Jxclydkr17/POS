"""
app/einvoice/hacienda_poller.py — Polling y reintentos automáticos para Hacienda

Background tasks que corren mientras la app está encendida:

1. POLLER (cada 60s): Revisa comprobantes con status SENT y consulta
   su estado en Hacienda. Si Hacienda responde ACEPTADO o RECHAZADO,
   actualiza la BD.

2. RETRY QUEUE (cada 5min): Reintenta enviar comprobantes con status
   SEND_ERROR que tengan tries < 3. Después de 3 intentos, marca como
   FAILED.

USO:
    # En main.py, dentro del startup event:
    from app.einvoice.hacienda_poller import start_background_tasks
    start_background_tasks()

DEPENDENCIAS:
    - app.utils.hacienda_api (send_einvoice_to_hacienda, check_einvoice_status)
    - app.einvoice.hacienda_client (HaciendaConfigError)
    - app.db.database (SessionLocal)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from app.constants.status_enums import InvoiceStatus

# ═══════════════════════════════════════════════════════════════
# Configuración
# ═══════════════════════════════════════════════════════════════

POLL_INTERVAL_SECONDS = 60       # cada 60s revisar comprobantes SENT
RETRY_INTERVAL_SECONDS = 300     # cada 5min reintentar SEND_ERROR
MAX_RETRY_ATTEMPTS = 3           # después de 3 intentos → FAILED
BATCH_SIZE = 20                  # máximo de comprobantes por ciclo

# Flag para detener los tasks limpiamente
_running = True


# ═══════════════════════════════════════════════════════════════
# Polling: consultar estado de comprobantes enviados
# ═══════════════════════════════════════════════════════════════

def _poll_sent_invoices():
    """
    Busca ElectronicInvoice con status SENT y consulta su estado en Hacienda.
    También busca ElectronicRep con status SENT.
    """
    from app.db.database import SessionLocal
    from app.db.models.electronic_invoice import ElectronicInvoice
    from app.db.models.electronic_rep import ElectronicRep
    from app.utils.hacienda_api import check_einvoice_status, check_rep_status
    from app.einvoice.hacienda_client import HaciendaConfigError

    db = SessionLocal()
    try:
        # ── Invoices (FE, TE, NC, ND) ──
        pending = (
            db.query(ElectronicInvoice)
            .filter(ElectronicInvoice.status == InvoiceStatus.SENT)
            .order_by(ElectronicInvoice.sent_at.asc())
            .limit(BATCH_SIZE)
            .all()
        )

        if pending:
            logger.info(f"Poller: revisando {len(pending)} comprobante(s) SENT...")

        resolved = 0
        for einv in pending:
            try:
                result = check_einvoice_status(db, einv.id)
                if result.get("resolved"):
                    resolved += 1
                    logger.info(
                        f"Poller: einvoice #{einv.id} → {result.get('hacienda_status')} "
                        f"(clave: ...{einv.clave[-8:] if einv.clave else '?'})"
                    )
            except HaciendaConfigError:
                logger.debug("Poller: credenciales no configuradas, saltando ciclo")
                return  # sin credenciales no tiene sentido seguir
            except Exception as e:
                logger.warning(f"Poller: error consultando einvoice #{einv.id}: {e}")

        if resolved:
            logger.info(f"Poller: {resolved} comprobante(s) resueltos en este ciclo")

        # ── REPs ──
        pending_reps = (
            db.query(ElectronicRep)
            .filter(ElectronicRep.status == InvoiceStatus.SENT)
            .order_by(ElectronicRep.sent_at.asc())
            .limit(BATCH_SIZE)
            .all()
        )

        for rep in pending_reps:
            try:
                check_rep_status(db, rep.id)
            except HaciendaConfigError:
                return
            except Exception as e:
                logger.warning(f"Poller: error consultando REP #{rep.id}: {e}")

    except Exception as e:
        logger.error(f"Poller: error general: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# Retry Queue: reintentar envíos fallidos
# ═══════════════════════════════════════════════════════════════

def _retry_failed_sends():
    """
    Busca comprobantes con status SEND_ERROR y tries < MAX_RETRY_ATTEMPTS,
    y reintenta enviarlos. Después de MAX_RETRY_ATTEMPTS, marca como FAILED.
    """
    from app.db.database import SessionLocal
    from app.db.models.electronic_invoice import ElectronicInvoice
    from app.db.models.electronic_rep import ElectronicRep
    from app.utils.hacienda_api import send_einvoice_to_hacienda, send_rep_to_hacienda
    from app.einvoice.hacienda_client import HaciendaConfigError

    db = SessionLocal()
    try:
        # ── Invoices con SEND_ERROR y reintentos disponibles ──
        retriable = (
            db.query(ElectronicInvoice)
            .filter(
                ElectronicInvoice.status == "SEND_ERROR",
                ElectronicInvoice.tries < MAX_RETRY_ATTEMPTS,
            )
            .order_by(ElectronicInvoice.tries.asc(), ElectronicInvoice.id.asc())
            .limit(BATCH_SIZE)
            .all()
        )

        if retriable:
            logger.info(f"Retry: reintentando {len(retriable)} comprobante(s) fallidos...")

        for einv in retriable:
            try:
                result = send_einvoice_to_hacienda(db, einv.id)
                if result.get("success"):
                    logger.info(
                        f"Retry: einvoice #{einv.id} reenviado OK "
                        f"(intento {einv.tries})"
                    )
                else:
                    logger.warning(
                        f"Retry: einvoice #{einv.id} falló de nuevo "
                        f"(intento {einv.tries}): {result.get('error', '')[:100]}"
                    )
            except HaciendaConfigError:
                logger.debug("Retry: credenciales no configuradas, saltando ciclo")
                return
            except Exception as e:
                logger.warning(f"Retry: error reenviando einvoice #{einv.id}: {e}")

        # ── Marcar como FAILED los que ya agotaron reintentos ──
        exhausted = (
            db.query(ElectronicInvoice)
            .filter(
                ElectronicInvoice.status == "SEND_ERROR",
                ElectronicInvoice.tries >= MAX_RETRY_ATTEMPTS,
            )
            .all()
        )

        for einv in exhausted:
            einv.status = "FAILED"
            einv.last_error = (
                f"Agotados {MAX_RETRY_ATTEMPTS} reintentos automáticos. "
                f"Último error: {(einv.last_error or '')[:200]}"
            )
            logger.warning(
                f"Retry: einvoice #{einv.id} marcado como FAILED "
                f"(clave: ...{einv.clave[-8:] if einv.clave else '?'})"
            )

        if exhausted:
            db.commit()

        # ── REPs con SEND_ERROR ──
        retriable_reps = (
            db.query(ElectronicRep)
            .filter(
                ElectronicRep.status == "SEND_ERROR",
                ElectronicRep.tries < MAX_RETRY_ATTEMPTS,
            )
            .limit(BATCH_SIZE)
            .all()
        )

        for rep in retriable_reps:
            try:
                send_rep_to_hacienda(db, rep.id)
            except HaciendaConfigError:
                return
            except Exception as e:
                logger.warning(f"Retry: error reenviando REP #{rep.id}: {e}")

        # Marcar REPs agotados
        exhausted_reps = (
            db.query(ElectronicRep)
            .filter(
                ElectronicRep.status == "SEND_ERROR",
                ElectronicRep.tries >= MAX_RETRY_ATTEMPTS,
            )
            .all()
        )

        for rep in exhausted_reps:
            rep.status = "FAILED"
            rep.last_error = f"Agotados {MAX_RETRY_ATTEMPTS} reintentos. {(rep.last_error or '')[:200]}"

        if exhausted_reps:
            db.commit()

    except Exception as e:
        logger.error(f"Retry: error general: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# Parseo de MensajeHacienda (XML de respuesta)
# ═══════════════════════════════════════════════════════════════

def parse_hacienda_response(xml_response: str) -> dict:
    """
    Parsea el XML de MensajeHacienda para extraer campos clave.

    Returns:
        dict con: mensaje (1/2/3), detalle_mensaje, clave, fecha, etc.
    """
    result = {
        "mensaje": None,
        "detalle_mensaje": "",
        "clave": "",
        "fecha": "",
        "monto_total_impuesto": "",
        "total_factura": "",
    }

    if not xml_response or not xml_response.strip():
        return result

    try:
        from lxml import etree
        doc = etree.fromstring(xml_response.encode("utf-8"))

        # El namespace varía, buscar sin namespace
        def _find_text(tag: str) -> str:
            # Buscar sin namespace
            el = doc.find(f".//{tag}")
            if el is None and doc.nsmap:
                # Intentar con namespace default
                default_ns = doc.nsmap.get(None, "")
                if default_ns:
                    el = doc.find(".//{%s}%s" % (default_ns, tag))
            if el is None and doc.nsmap:
                # Buscar en todos los namespaces
                for ns in doc.nsmap.values():
                    el = doc.find(".//{%s}%s" % (ns, tag))
                    if el is not None:
                        break
            return (el.text or "").strip() if el is not None else ""

        result["clave"] = _find_text("Clave")
        result["mensaje"] = _find_text("Mensaje")
        result["detalle_mensaje"] = _find_text("DetalleMensaje")
        result["fecha"] = _find_text("Fecha") or _find_text("FechaEmisionDoc")
        result["monto_total_impuesto"] = _find_text("MontoTotalImpuesto")
        result["total_factura"] = _find_text("TotalFactura")

    except Exception as e:
        logger.warning(f"Error parseando MensajeHacienda: {e}")
        result["detalle_mensaje"] = f"Error parseando respuesta: {e}"

    return result


# ═══════════════════════════════════════════════════════════════
# Resumen de comprobantes pendientes
# ═══════════════════════════════════════════════════════════════

def get_pending_summary() -> dict:
    """
    Retorna un resumen de comprobantes por estado.
    Útil para mostrar badges/alertas en la UI.
    """
    from app.db.database import SessionLocal
    from app.db.models.electronic_invoice import ElectronicInvoice
    from app.db.models.electronic_rep import ElectronicRep
    from sqlalchemy import func

    db = SessionLocal()
    try:
        # Contar por status
        inv_counts = dict(
            db.query(ElectronicInvoice.status, func.count(ElectronicInvoice.id))
            .group_by(ElectronicInvoice.status)
            .all()
        )

        rep_counts = dict(
            db.query(ElectronicRep.status, func.count(ElectronicRep.id))
            .group_by(ElectronicRep.status)
            .all()
        )

        return {
            "invoices": {
                "pending": inv_counts.get(InvoiceStatus.PENDING, 0),
                "xml_ready": inv_counts.get(InvoiceStatus.XML_READY, 0),
                "xml_unsigned": inv_counts.get(InvoiceStatus.XML_UNSIGNED, 0),
                "sign_error": inv_counts.get(InvoiceStatus.SIGN_ERROR, 0),
                "xsd_error": inv_counts.get(InvoiceStatus.XSD_ERROR, 0),
                "sent": inv_counts.get(InvoiceStatus.SENT, 0),
                "send_error": inv_counts.get(InvoiceStatus.SEND_ERROR, 0),
                "accepted": inv_counts.get(InvoiceStatus.ACCEPTED, 0),
                "rejected": inv_counts.get(InvoiceStatus.REJECTED, 0),
                "failed": inv_counts.get(InvoiceStatus.FAILED, 0),
                "total": sum(inv_counts.values()),
            },
            "reps": {
                "sent": rep_counts.get(InvoiceStatus.SENT, 0),
                "send_error": rep_counts.get(InvoiceStatus.SEND_ERROR, 0),
                "accepted": rep_counts.get(InvoiceStatus.ACCEPTED, 0),
                "rejected": rep_counts.get(InvoiceStatus.REJECTED, 0),
                "failed": rep_counts.get(InvoiceStatus.FAILED, 0),
                "total": sum(rep_counts.values()),
            },
            "needs_attention": (
                inv_counts.get(InvoiceStatus.REJECTED, 0)
                + inv_counts.get(InvoiceStatus.FAILED, 0)
                + inv_counts.get(InvoiceStatus.SEND_ERROR, 0)
                + rep_counts.get(InvoiceStatus.REJECTED, 0)
                + rep_counts.get(InvoiceStatus.FAILED, 0)
            ),
        }
    except Exception as e:
        logger.error(f"Error obteniendo resumen pendientes: {e}")
        return {"error": str(e)}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# Inicio / parada de background tasks
# ═══════════════════════════════════════════════════════════════

async def _poller_loop():
    """Loop asíncrono que ejecuta el polling cada POLL_INTERVAL_SECONDS."""
    # Esperar 30s al arrancar para no saturar al inicio
    await asyncio.sleep(30)
    logger.info(f"Hacienda Poller iniciado (cada {POLL_INTERVAL_SECONDS}s)")

    while _running:
        try:
            # Ejecutar en thread para no bloquear el event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _poll_sent_invoices)
        except Exception as e:
            logger.error(f"Poller loop error: {e}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _retry_loop():
    """Loop asíncrono que ejecuta reintentos cada RETRY_INTERVAL_SECONDS."""
    # Esperar 60s al arrancar
    await asyncio.sleep(60)
    logger.info(f"Hacienda Retry Queue iniciada (cada {RETRY_INTERVAL_SECONDS}s, max {MAX_RETRY_ATTEMPTS} intentos)")

    while _running:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _retry_failed_sends)
        except Exception as e:
            logger.error(f"Retry loop error: {e}")

        await asyncio.sleep(RETRY_INTERVAL_SECONDS)


def start_background_tasks():
    """
    Inicia los background tasks de polling y reintentos.
    Llamar desde main.py en el evento startup.

    Ejemplo:
        @app.on_event("startup")
        async def _startup():
            from app.einvoice.hacienda_poller import start_background_tasks
            start_background_tasks()
    """
    global _running
    _running = True

    asyncio.create_task(_poller_loop())
    asyncio.create_task(_retry_loop())
    logger.info("Background tasks de Hacienda iniciados")


def stop_background_tasks():
    """Señaliza a los loops que se detengan."""
    global _running
    _running = False
    logger.info("Background tasks de Hacienda detenidos")