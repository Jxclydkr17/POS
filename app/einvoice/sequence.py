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
from sqlalchemy.orm import Session
from app.db.models.document_sequence import DocumentSequence
from app.utils.dt import now_cr, utcnow
from app.utils.db_compat import lock_for_update


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
    Incremento seguro usando SQLAlchemy ORM + bloqueo pesimista.
    Compatible con SQLite y MySQL.

    En MySQL: aplica SELECT ... FOR UPDATE para evitar que dos cajeros
    lean el mismo consecutivo simultáneamente.
    En SQLite: el bloqueo es no-op (SQLite serializa escrituras a nivel
    de archivo, así que no hay race condition real).

    Guarda secuencia por (branch_code, terminal_code, document_type).
    """
    doc = normalize_document_type(document_type)

    # Buscar fila existente CON bloqueo pesimista
    # lock_for_update() aplica WITH FOR UPDATE en MySQL, no-op en SQLite
    seq = lock_for_update(
        db.query(DocumentSequence)
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
        db.add(seq)
        db.flush()

    current = seq.next_number
    seq.next_number = current + 1
    seq.updated_at = utcnow()
    db.flush()

    return current