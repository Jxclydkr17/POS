"""
app/einvoice/sequence.py — Generación de consecutivos y claves

FASE 4 FIX: Reescrito con SQLAlchemy ORM puro para compatibilidad
con SQLite (standalone .exe) y MySQL.

Antes usaba SQL crudo con ON DUPLICATE KEY UPDATE (MySQL-only)
y SELECT ... FOR UPDATE (no soportado en SQLite).

AUDITORÍA FIX 1.1: Agregado bloqueo pesimista (lock_for_update) en
next_sequence_number() para evitar race condition de consecutivos
duplicados cuando dos cajeros facturan simultáneamente.
"""
from __future__ import annotations

from datetime import datetime
import random
import threading
from sqlalchemy.orm import Session
from app.db.models.document_sequence import DocumentSequence
from app.db.database import SessionLocal
from app.utils.dt import now_cr, utcnow
from app.utils.db_compat import lock_for_update


# ── FASE 3 — Lock de proceso para la reserva de consecutivos ──
# Serializa la asignación de consecutivos entre los hilos del worker. En el
# .exe (SQLite, un solo proceso) esto es lo que de verdad evita duplicados,
# porque en SQLite el FOR UPDATE es no-op y un flush SIN commit no es visible
# desde otra conexión. En MySQL multi-proceso, además, el FOR UPDATE de la
# transacción aislada (abajo) serializa entre procesos distintos.
_seq_lock = threading.Lock()


def _digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def normalize_document_type(document_type: str) -> str:
    """
    Asegura document_type de 2 dígitos numéricos ("01", "04", "10", etc.)
    """
    if document_type is None:
        raise ValueError("document_type es None")

    dt = str(document_type).strip()
    if not dt.isdigit():
        raise ValueError(f"document_type inválido (no numérico): {document_type!r}")

    if len(dt) > 2:
        raise ValueError(f"document_type inválido (más de 2 dígitos): {document_type!r}")

    return dt.zfill(2)


def build_consecutivo(branch_code: str, terminal_code: str, document_type: str, seq_number: int) -> str:
    """
    BBB + TTTTT + TT + NNNNNNNNNN = 20
    - branch_code: 3 dígitos
    - terminal_code: 5 dígitos
    - document_type: 2 dígitos (01 FE, 04 TE, 10 REP, etc.)
    - seq_number: 10 dígitos
    """
    doc = normalize_document_type(document_type)
    return f"{branch_code.zfill(3)}{terminal_code.zfill(5)}{doc}{str(seq_number).zfill(10)}"


def build_clave(issuer_id_number: str, consecutivo: str, dt: datetime | None = None, situation: str = "1") -> str:
    """
    Clave 50 dígitos (formato usual CR):
    506 + DDMMYY + ID(12) + CONSECUTIVO(20) + SITUACION(1) + SEGURIDAD(8)
    """
    dt = dt or now_cr()
    date_part = dt.strftime("%d%m%y")  # DDMMYY
    issuer12 = _digits_only(issuer_id_number).zfill(12)[:12]
    security = str(random.randint(0, 99_999_999)).zfill(8)
    clave = f"506{date_part}{issuer12}{consecutivo}{situation}{security}"
    if len(clave) != 50 or not clave.isdigit():
        raise ValueError(f"Clave inválida generada: {clave} (len={len(clave)})")
    return clave


def next_sequence_number(db: Session, branch_code: str, terminal_code: str, document_type: str) -> int:
    """
    Reserva atómica del siguiente consecutivo, segura ante concurrencia.

    Estrategia (cubre SQLite del .exe y MySQL multi-terminal):
      - Lock de proceso (_seq_lock) → serializa la reserva entre los hilos
        del worker.
      - Transacción AISLADA de commit inmediato (sesión propia) → el número
        queda "consumido" y visible a las demás conexiones al instante. Esto
        es lo que cierra el race en SQLite, donde el FOR UPDATE es no-op y un
        flush sin commit no se ve desde otra conexión.
      - FOR UPDATE (lock_for_update) dentro de esa transacción → serializa
        también entre procesos en MySQL.

    Importante:
      - El número se consume de forma DURABLE aquí mismo. Si el documento que
        lo usa falla después, queda un HUECO en la numeración, algo que
        Hacienda permite. Lo que NO se permite —y esto lo evita— es DUPLICAR
        un consecutivo.
      - Se usa una sesión propia (no `db`) para no arrastrar ni comitear los
        cambios pendientes del caller. `db` se conserva en la firma por
        compatibilidad con los llamadores existentes.
      - Con autoflush=False, ningún caller tiene el write-lock de SQLite
        tomado en este punto (solo han "staged" objetos), por lo que la
        sesión aislada puede tomar el lock de escritura sin conflicto.
    """
    doc = normalize_document_type(document_type)

    with _seq_lock:
        alloc = SessionLocal()
        try:
            # Buscar fila existente CON bloqueo pesimista.
            # lock_for_update() aplica WITH FOR UPDATE en MySQL, no-op en SQLite.
            seq = lock_for_update(
                alloc.query(DocumentSequence)
                .filter(
                    DocumentSequence.branch_code == branch_code,
                    DocumentSequence.terminal_code == terminal_code,
                    DocumentSequence.document_type == doc,
                )
            ).first()

            if seq is None:
                # Crear nueva secuencia
                seq = DocumentSequence(
                    branch_code=branch_code,
                    terminal_code=terminal_code,
                    document_type=doc,
                    next_number=1,
                    updated_at=utcnow(),
                )
                alloc.add(seq)
                alloc.flush()

            current = seq.next_number
            seq.next_number = current + 1
            seq.updated_at = utcnow()
            alloc.commit()
            return current
        except Exception:
            alloc.rollback()
            raise
        finally:
            alloc.close()