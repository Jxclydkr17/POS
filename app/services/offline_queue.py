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
import threading
from datetime import datetime

import requests
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

    has_internet = check_internet()

    return {
        "queued_count": queued,
        "has_internet": has_internet,
        "retry_interval_seconds": RETRY_INTERVAL,
        "processor_running": _processor_task is not None and not _processor_task.done(),
    }


def get_queued_invoices(db: Session, limit: int = 50) -> list[dict]:
    """Lista los comprobantes en cola offline."""
    records = (
        db.query(ElectronicInvoice)
        .filter(ElectronicInvoice.status.in_(OFFLINE_STATUSES))
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
            # Obtener comprobantes en cola (FIFO)
            queued = (
                db.query(ElectronicInvoice)
                .filter(ElectronicInvoice.status.in_(OFFLINE_STATUSES))
                .order_by(ElectronicInvoice.created_at.asc())
                .limit(MAX_RETRY_PER_CYCLE)
                .all()
            )

            if not queued:
                return 0

            logger.info(f"Cola offline: procesando {len(queued)} comprobante(s)...")

            for einv in queued:
                try:
                    # Cambiar status para evitar procesamiento duplicado
                    einv.status = "XML_READY"
                    db.commit()

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