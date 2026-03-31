from app.db.models.cash_movement import CashMovement
from app.db.models.cash_session import CashSession
from app.utils.dt import utcnow
from fastapi import HTTPException

def register_cash_movement(
    db,
    cash_session_id: int,
    movement_type: str,   # "IN" | "OUT"
    amount: float,
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

    movement = CashMovement(
        cash_session_id=cash_session_id,
        type=movement_type.lower(),   # "IN" -> "in"
        concept=concept,
        amount=float(amount),
        source=source,
        description=description,
        reference_id=reference_id,
        created_at=utcnow(),          # Asignar explícitamente para evitar N/A
    )


    db.add(movement)
    db.flush()

    # 🚫 NO tocar cash_session aquí
    return movement