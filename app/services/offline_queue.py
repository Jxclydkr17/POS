"""
app/services/offline_queue.py — Cola offline para comprobantes electrónicos

Cuando no hay conexión a internet, los comprobantes se guardan en cola local
y se reenvían automáticamente cuando la conexión se restaura.

Flujo:
  1. El envío a Hacienda falla por ConnectionError/Timeout
  2. El comprobante se marca como QUEUED (en cola)
  3. Un background task revisa cada 2 minutos si hay conexión
  4. Si hay conexión, reenvía los comprobantes en cola (FIFO)
  5. Notifica al usuario cuando se procesan

USO:
    from app.services.offline_queue import enqueue_for_retry, get_queue_status

    # Encolar un comprobante que falló por red
    enqueue_for_retry(db, einvoice_id=123, error="ConnectionError")

    # Ver estado de la cola
    status = get_queue_status(db)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import requests
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from app.db.models.electronic_invoice import ElectronicInvoice
from app.utils.dt import utcnow

logger = logging.getLogger(__name__)

# ── Configuración ──
RETRY_INTERVAL = 120        # Segundos entre intentos (2 min)
MAX_RETRY_PER_CYCLE = 10    # Máximo de comprobantes a procesar por ciclo
CONNECTIVITY_URL = "https://api.comprobanteselectronicos.go.cr"
CONNECTIVITY_TIMEOUT = 5    # Segundos

# Status que indican "en cola offline"
OFFLINE_STATUSES = ("QUEUED", "OFFLINE_RETRY")

# ── FASE 2.3 — Fix 2.3: Recovery de orphans ──
# Si un einv está en XML_READY pero nunca pasó a SENT (sent_at IS NULL)
# y es viejo (created_at < utcnow - ORPHAN_THRESHOLD_MINUTES), es casi
# seguro huérfano de un crash previo a la corrección de Fase 2.3 o de
# un escenario edge (ej. servidor reiniciado durante envío).
#
# El flujo normal de XML_READY → SENT toma < 30s. 10 minutos es un margen
# generoso para evitar falsos positivos.
ORPHAN_THRESHOLD_MINUTES = 10
ORPHAN_STATUSES = ("XML_READY",)


def _orphan_filter():
    """
    Filtro SQLAlchemy para detectar einv huérfanos.
    Un huérfano es XML_READY con sent_at NULL y created_at viejo.
    """
    threshold = utcnow() - timedelta(minutes=ORPHAN_THRESHOLD_MINUTES)
    return and_(
        ElectronicInvoice.status.in_(ORPHAN_STATUSES),
        ElectronicInvoice.sent_at.is_(None),
        ElectronicInvoice.created_at < threshold,
    )


_processor_task = None


# ══════════════════════════════════════════════════════════════
# Verificación de conectividad
# ══════════════════════════════════════════════════════════════

def check_internet(url: str = CONNECTIVITY_URL, timeout: int = CONNECTIVITY_TIMEOUT) -> bool:
    """Verifica si hay conexión a internet intentando alcanzar Hacienda."""
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        return resp.status_code < 500
    except (requests.ConnectionError, requests.Timeout):
        return False
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
# Encolar comprobantes
# ══════════════════════════════════════════════════════════════

def enqueue_for_retry(db: Session, einvoice_id: int, error: str = "") -> None:
    """
    Marca un comprobante como QUEUED para reenvío cuando haya internet.

    Args:
        db: Sesión de BD
        einvoice_id: ID del ElectronicInvoice
        error: Descripción del error de red
    """
    einv = db.query(ElectronicInvoice).filter(
        ElectronicInvoice.id == einvoice_id
    ).first()

    if not einv:
        logger.warning(f"Cola offline: einvoice {einvoice_id} no encontrado")
        return

    einv.status = "QUEUED"
    einv.last_error = f"En cola offline: {error}"[:500]
    db.flush()

    logger.info(f"Cola offline: einvoice {einvoice_id} encolado | error={error[:100]}")


def get_queue_status(db: Session) -> dict:
    """Retorna el estado actual de la cola offline."""
    queued = (
        db.query(ElectronicInvoice)
        .filter(ElectronicInvoice.status.in_(OFFLINE_STATUSES))
        .count()
    )

    # FASE 2.3: contar orphans separadamente para visibilidad
    orphans = (
        db.query(ElectronicInvoice)
        .filter(_orphan_filter())
        .count()
    )

    has_internet = check_internet()

    return {
        "queued_count": queued,
        "orphan_count": orphans,  # FASE 2.3 — Fix 2.3: visibilidad de orphans
        "has_internet": has_internet,
        "retry_interval_seconds": RETRY_INTERVAL,
        "processor_running": _processor_task is not None and not _processor_task.done(),
    }


def get_queued_invoices(db: Session, limit: int = 50) -> list[dict]:
    """Lista los comprobantes en cola offline (incluye orphans XML_READY)."""
    records = (
        db.query(ElectronicInvoice)
        # FASE 2.3 — Fix 2.3: incluir orphans en el listado.
        .filter(or_(
            ElectronicInvoice.status.in_(OFFLINE_STATUSES),
            _orphan_filter(),
        ))
        .order_by(ElectronicInvoice.created_at.asc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": r.id,
            "sale_id": r.sale_id,
            "clave": r.clave,
            "consecutivo": r.consecutivo,
            "document_type": r.document_type,
            "status": r.status,
            "last_error": r.last_error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "tries": r.tries,
            # FASE 2.3 — indicador para que el UI muestre advertencia visual
            "is_orphan": r.status == "XML_READY",
        }
        for r in records
    ]


# ══════════════════════════════════════════════════════════════
# Procesador de cola (background task)
# ══════════════════════════════════════════════════════════════

def _process_queue_cycle() -> int:
    """
    Procesa un ciclo de la cola offline.
    Retorna la cantidad de comprobantes procesados exitosamente.
    """
    from app.db.database import safe_session
    from app.utils.hacienda_api import send_einvoice_to_hacienda

    # Primero verificar internet
    if not check_internet():
        return 0

    processed = 0

    try:
        with safe_session() as db:
            # Obtener comprobantes en cola (FIFO).
            # FASE 2.3 — Fix 2.3: además de QUEUED, también recuperamos
            # XML_READY huérfanos antiguos (sent_at NULL, created_at > 10min).
            # Estos son comprobantes que quedaron en estado intermedio por
            # un crash de la app antes del fix de Fase 2.3, o por un
            # escenario edge (servidor reiniciado durante el envío).
            queued = (
                db.query(ElectronicInvoice)
                .filter(or_(
                    ElectronicInvoice.status.in_(OFFLINE_STATUSES),
                    _orphan_filter(),
                ))
                .order_by(ElectronicInvoice.created_at.asc())
                .limit(MAX_RETRY_PER_CYCLE)
                .all()
            )

            if not queued:
                return 0

            logger.info(f"Cola offline: procesando {len(queued)} comprobante(s)...")

            for einv in queued:
                try:
                    # ── FASE 2.3 — Fix 2.3: NO commitear status intermedio ──
                    # Antes: `einv.status = "XML_READY"; db.commit()` antes
                    # del envío. Si la app crasheaba entre ese commit y el
                    # commit final del envío, el comprobante quedaba en
                    # XML_READY permanentemente (la cola solo recogía
                    # QUEUED/SEND_ERROR). Auditoría detectaba el orphan
                    # meses después.
                    #
                    # Ahora: solo cambiamos en memoria. Si la app crashea,
                    # el rollback automático de la sesión SQLAlchemy devuelve
                    # el einv a `QUEUED` (su estado en BD), y la próxima
                    # vuelta de la cola lo reintenta naturalmente.
                    #
                    # `send_einvoice_to_hacienda` internamente hace su propio
                    # `db.commit()` con el estado final (SENT/SEND_ERROR/QUEUED).
                    # La validación interna `status in ("XML_READY", "SEND_ERROR")`
                    # se hace sobre el objeto en memoria, así que el cambio
                    # local le basta para pasar.
                    einv.status = "XML_READY"

                    # Intentar enviar
                    result = send_einvoice_to_hacienda(db, einv.id)

                    if result.get("success"):
                        processed += 1
                        logger.info(
                            f"Cola offline: einvoice {einv.id} enviado OK | "
                            f"clave=...{einv.clave[-8:] if einv.clave else '?'}"
                        )
                    else:
                        # Si falló pero no por red, dejarlo como SEND_ERROR
                        logger.warning(
                            f"Cola offline: einvoice {einv.id} falló envío | "
                            f"error={result.get('error', '?')}"
                        )

                except (requests.ConnectionError, requests.Timeout) as e:
                    # Sigue sin internet, re-encolar
                    einv.status = "QUEUED"
                    einv.last_error = f"Re-encolado: {str(e)[:200]}"
                    db.commit()
                    logger.info(f"Cola offline: einvoice {einv.id} re-encolado (sin conexión)")
                    break  # No seguir intentando si no hay red

                except Exception as e:
                    # Error no relacionado a red
                    einv.status = "SEND_ERROR"
                    einv.last_error = f"Error en cola: {str(e)[:400]}"
                    einv.tries = (einv.tries or 0) + 1
                    db.commit()
                    logger.error(f"Cola offline: error procesando einvoice {einv.id}: {e}")

    except Exception as e:
        logger.error(f"Cola offline: error en ciclo de procesamiento: {e}")

    if processed > 0:
        logger.info(f"Cola offline: {processed} comprobante(s) enviados exitosamente")

    return processed


# ══════════════════════════════════════════════════════════════
# Background task management
# ══════════════════════════════════════════════════════════════

def start_offline_processor() -> None:
    """Inicia el background task que procesa la cola offline."""
    global _processor_task

    async def _processor_loop():
        while True:
            await asyncio.sleep(RETRY_INTERVAL)
            try:
                # Ejecutar en thread para no bloquear el event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _process_queue_cycle)
            except Exception as e:
                logger.error(f"Cola offline: error en loop: {e}")

    _processor_task = asyncio.ensure_future(_processor_loop())
    logger.info(
        f"Cola offline: procesador iniciado (cada {RETRY_INTERVAL}s)"
    )


def stop_offline_processor() -> None:
    """Detiene el background task de la cola offline."""
    global _processor_task
    if _processor_task and not _processor_task.done():
        _processor_task.cancel()
        logger.info("Cola offline: procesador detenido")


def force_process_queue() -> int:
    """
    Fuerza un ciclo de procesamiento inmediato (para uso manual).
    Retorna cantidad de comprobantes procesados.
    """
    return _process_queue_cycle()