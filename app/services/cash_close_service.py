from sqlalchemy import func, case
from datetime import datetime

from app.db.models.cash_movement import CashMovement
from app.utils.dt import utcnow


def close_cash_session(db, cash_session, closing_amount: float):
    """
    Cierra la sesión de caja calculando el total esperado
    basándose en los movimientos registrados.
    """
    
    # 🔥 FIX: Cambiar session_id por cash_session_id
    totals = (
        db.query(
            func.sum(
                case(
                    (CashMovement.type == "in", CashMovement.amount),
                    else_=-CashMovement.amount
                )
            )
        )
        .filter(CashMovement.cash_session_id == cash_session.id)
        .scalar()
        or 0
    )

    expected = float(cash_session.opening_amount) + float(totals)
    difference = float(closing_amount) - expected

    cash_session.expected_closing = expected
    cash_session.closing_amount = float(closing_amount)
    cash_session.difference = difference
    cash_session.status = "closed"
    cash_session.closed_at = utcnow()

    db.commit()
    db.refresh(cash_session)

    return {
        "opening_amount": float(cash_session.opening_amount),
        "expected_closing": expected,
        "closing_amount": float(closing_amount),
        "difference": difference,
        "status": cash_session.status,
    }