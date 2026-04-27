from decimal import Decimal

from app.db.models.cash_movement import CashMovement
from app.db.models.cash_session import CashSession
from app.utils.dt import utcnow
from app.constants.status_enums import CashMovementType
from fastapi import HTTPException


def register_cash_movement(
    db,
    cash_session_id: int,
    movement_type: str,   # "IN" | "OUT" | "in" | "out" | CashMovementType
    amount,               # acepta float, int, str o Decimal
    concept: str,
    source: str,
    description: str = "",
    reference_id: int | None = None,
):
    cash_session = (
        db.query(CashSession)
        .filter(CashSession.id == cash_session_id)
        .first()
    )

    if not cash_session:
        raise HTTPException(404, "Caja no encontrada")

    if cash_session.status != "open":
        raise HTTPException(400, "La caja está cerrada")

    # ── FASE 6 — Fix 6.2: Normalizar y validar movement_type ──
    # Acepta "IN", "in", CashMovementType.IN → siempre almacena "in"/"out"
    normalized = str(movement_type).lower()
    if normalized not in (CashMovementType.IN, CashMovementType.OUT):
        raise HTTPException(400, f"Tipo de movimiento inválido: '{movement_type}'. Use 'IN' o 'OUT'.")

    # ── FASE 1: Decimal para almacenamiento — sin pérdida IEEE 754 ──
    amount_dec = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount

    movement = CashMovement(
        cash_session_id=cash_session_id,
        type=normalized,
        concept=concept,
        amount=amount_dec,
        source=source,
        description=description,
        reference_id=reference_id,
        created_at=utcnow(),          # Asignar explícitamente para evitar N/A
    )


    db.add(movement)
    db.flush()

    # 🚫 NO tocar cash_session aquí
    return movement