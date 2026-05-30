from sqlalchemy import func, case

from app.db.models.cash_movement import CashMovement
from app.utils.dt import utcnow

# FASE 2 — Fix 2.3: Helper compartido (antes duplicado aquí y en cash crud)
from app.utils.decimal_utils import to_dec


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

    # ── FASE 1: Aritmética en Decimal ──
    opening_dec = to_dec(cash_session.opening_amount)
    totals_dec = to_dec(totals)
    closing_dec = to_dec(closing_amount)

    expected = opening_dec + totals_dec
    difference = closing_dec - expected

    cash_session.expected_closing = expected
    cash_session.closing_amount = closing_dec
    cash_session.difference = difference
    cash_session.status = "closed"
    cash_session.closed_at = utcnow()

    # FASE 1 — Fix 1.2: flush only; router owns commit
    # Esto permite que close_cash + save_dashboard_snapshot
    # sean atómicos en una sola transacción.
    db.flush()
    db.refresh(cash_session)

    # ── float() solo al construir la respuesta JSON ──
    return {
        "opening_amount": float(opening_dec),
        "expected_closing": float(expected),
        "closing_amount": float(closing_dec),
        "difference": float(difference),
        "status": cash_session.status,
    }