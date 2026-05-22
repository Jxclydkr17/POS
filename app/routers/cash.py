from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date
from app.utils.dt import today_cr, format_cr  # FASE 2.2 — Fix 2.2: display CR

from app.db.database import get_db
from app.db.models.cash_session import CashSession
from app.db.models.cash_movement import CashMovement
from app.db.models.user import User
from app.services.cash_movement_service import register_cash_movement
from app.schemas.cash import CashCloseSchema
from app.services.cash_close_service import close_cash_session
from app.services.dashboard_snapshot_service import save_dashboard_snapshot

from app.db.crud.cash import (
    get_today_session,
    get_today_open_session,
    get_open_session,
    open_session,
    add_movement,
    get_cash_report,
)

from app.schemas.cash import (
    CashSessionCreate,
    CashSessionOut,
    CashMovementCreate,
)

from app.utils.responses import success_response, error_response

# ── FASE 1 — Fix 1.1: Importar dependencia de autenticación ──
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/cash", tags=["Caja"])


# ==========================================================
# 🟦 Sesión de hoy
# ==========================================================
@router.get("/today")
def get_today(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = get_today_session(db)

    if not session:
        return success_response(
            message="No hay caja abierta hoy.",
            data=None
        )

    return success_response(
        message="Sesión de caja del día.",
        data=CashSessionOut.model_validate(session).model_dump()
    )


# ==========================================================
# 🟩 Abrir caja
# ==========================================================
@router.post("/open")
def open_cash(
    data: CashSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        session = open_session(db, data.opening_amount, terminal_id=data.terminal_id)
        # FASE 1 — Fix 1.2: Router es dueño del commit
        db.commit()

        return success_response(
            message="Caja abierta correctamente.",
            data=CashSessionOut.model_validate(session).model_dump()
        )

    except Exception as e:
        db.rollback()
        return error_response(f"No se pudo abrir la caja: {e}", 400)


# ==========================================================
# 🟨 Registrar movimiento
# ==========================================================
@router.post("/movements")
def create_movement(
    data: CashMovementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = get_today_session(db)

    if not session:
        return error_response("No hay caja abierta hoy.", 400)

    if session.status != "open":
        return error_response("La caja ya está cerrada.", 400)

    try:
        mov = add_movement(db, cash_session_id=session.id, data=data)
        # FASE 1 — Fix 1.2: Router es dueño del commit
        db.commit()

        return success_response(
            message="Movimiento registrado correctamente.",
            data={
                "movement_id": mov.id,
                "session_id": session.id
            }
        )

    except Exception as e:
        db.rollback()
        return error_response(f"Error creando movimiento: {e}", 400)


# ==========================================================
# 🟥 Cerrar caja
# ==========================================================
@router.post("/close")
def close_cash(
    data: CashCloseSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = get_today_session(db)

    if not session:
        return error_response("No hay caja abierta hoy.", 400)

    if session.status != "open":
        return error_response("La caja ya está cerrada.", 400)

    try:
        result = close_cash_session(
            db=db,
            cash_session=session,
            closing_amount=data.closing_amount
        )

        # Guardar snapshot del día ya cerrado
        save_dashboard_snapshot(db, today_cr())

        # FASE 1 — Fix 1.2: Commit explícito tras ambas operaciones
        db.commit()

        return success_response(
            message="Caja cerrada correctamente.",
            data=result
        )

    except Exception as e:
        db.rollback()
        return error_response(f"Error cerrando la caja: {e}", 400)


# ==========================================================
# 🟧 Reporte de hoy (SIMPLIFICADO - USA EL CRUD)
# ==========================================================
@router.get("/report/today")
def cash_report_today(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Obtiene el reporte completo del día.
    Funciona tanto si la caja está abierta como cerrada.
    """
    today = today_cr()
    data = get_cash_report(db, today)

    if not data:
        return success_response("No hay datos de caja para hoy.", data=None)

    return success_response(
        message="Reporte del día.",
        data=data
    )


# ==========================================================
# 🟪 Movimientos del día
# ==========================================================
@router.get("/movements/today")
def get_today_movements(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if limit > 100:
        limit = 100

    today = today_cr()

    session = (
        db.query(CashSession)
        .filter(CashSession.date == today)
        .first()
    )

    if not session:
        return success_response(message="Sin movimientos hoy.", data=[])

    movements = (
        db.query(CashMovement)
        .filter(CashMovement.cash_session_id == session.id)
        .order_by(CashMovement.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    result = [
        {
            "type": "Entrada" if m.type == "in" else "Salida",
            "amount": float(m.amount),
            "description": m.description or "",
            "time": format_cr(m.created_at, "%H:%M:%S") if m.created_at else "N/A",  # FASE 2.2
        }
        for m in movements
    ]

    return success_response(
        message="Movimientos del día.",
        data=result
    )

# ==========================================================
# 🆕 Movimientos por fecha específica
# ==========================================================
@router.get("/movements/date/{report_date}")
def get_movements_by_date(
    report_date: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if limit > 100:
        limit = 100

    try:
        target_date = date.fromisoformat(report_date)
    except ValueError:
        return error_response("Formato inválido. Usa YYYY-MM-DD.", 400)

    session = (
        db.query(CashSession)
        .filter(CashSession.date == target_date)
        .first()
    )

    if not session:
        return success_response(
            message=f"Sin movimientos para {report_date}.",
            data=[]
        )

    movements = (
        db.query(CashMovement)
        .filter(CashMovement.cash_session_id == session.id)
        .order_by(CashMovement.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    result = [
        {
            "type": "Entrada" if m.type == "in" else "Salida",
            "amount": float(m.amount),
            "description": m.description or "",
            "source": m.source,
            "time": format_cr(m.created_at, "%H:%M:%S") if m.created_at else "N/A",  # FASE 2.2
        }
        for m in movements
    ]

    return success_response(
        message=f"Movimientos del {report_date}.",
        data=result
    )


# ==========================================================
# 🟫 Reporte por fecha
# ==========================================================
@router.get("/report/{report_date}")
def cash_report(
    report_date: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        d = date.fromisoformat(report_date)
    except ValueError:
        return error_response("Formato inválido. Usa YYYY-MM-DD.", 400)

    data = get_cash_report(db, d)

    if not data:
        return success_response("No hay datos para esa fecha.", data=None)

    return success_response(
        message="Reporte de caja por fecha.",
        data=data
    )


@router.get("/current")
def get_current_cash(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ── HOTFIX: Usar get_today_open_session para el check de la UI ──
    # get_open_session (con fallback) es para REGISTRAR movimientos.
    # Para decidir si mostrar el prompt de apertura, solo importa HOY.
    session = get_today_open_session(db)

    if not session:
        # Verificar si hay una sesión stale de días anteriores sin cerrar
        stale = get_open_session(db)
        stale_info = None
        if stale:
            stale_info = {
                "date": str(stale.date),
                "opening_amount": float(stale.opening_amount),
            }

        return success_response(
            message="No hay caja abierta hoy.",
            data={
                "is_open": False,
                "stale_session": stale_info,
            }
        )

    return success_response(
        message="Caja abierta.",
        data={
            "is_open": True,
            "session": CashSessionOut.model_validate(session).model_dump()
        }
    )


# ==========================================================
# 🟨 Retiro de efectivo (WITHDRAW)
# ==========================================================
@router.post("/withdraw")
def withdraw_cash(
    amount: float,
    reason: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = get_open_session(db)

    if not session:
        error_response("No hay caja abierta.", 400)

    if session.status != "open":
        error_response("La caja ya está cerrada.", 400)

    try:
        register_cash_movement(
            db=db,
            cash_session_id=session.id,
            movement_type="OUT",
            amount=amount,
            concept="Retiro de efectivo",
            source="WITHDRAW",
            description=reason
        )

        db.commit()

        return success_response(
            message="Retiro de efectivo registrado correctamente.",
            data={
                "amount": amount,
                "reason": reason
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        error_response(f"Error registrando retiro: {e}", 500)


# ==========================================================
# 🟪 Ajuste manual de caja (ADJUSTMENT)
# ==========================================================
@router.post("/adjust")
def adjust_cash(
    amount: float,
    reason: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    amount:
      > 0  => sobrante (IN)
      < 0  => faltante (OUT)
    """
    session = get_open_session(db)

    if not session:
        error_response("No hay caja abierta.", 400)

    if session.status != "open":
        error_response("La caja ya está cerrada.", 400)

    try:
        movement_type = "IN" if amount > 0 else "OUT"

        register_cash_movement(
            db=db,
            cash_session_id=session.id,
            movement_type=movement_type,
            amount=abs(amount),
            concept="Ajuste de caja",
            source="ADJUSTMENT",
            description=reason
        )

        db.commit()

        return success_response(
            message="Ajuste de caja registrado correctamente.",
            data={
                "movement_type": movement_type,
                "amount": abs(amount),
                "reason": reason
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        error_response(f"Error registrando ajuste: {e}", 500)


@router.get("/report/session/{cash_session_id}")
def get_cash_session_report(
    cash_session_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if limit > 100:
        limit = 100

    cash_session = (
        db.query(CashSession)
        .filter(CashSession.id == cash_session_id)
        .first()
    )

    if not cash_session:
        raise HTTPException(status_code=404, detail="Caja no encontrada")

    movements = (
        db.query(CashMovement)
        .filter(CashMovement.cash_session_id == cash_session.id)
        .order_by(CashMovement.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "date": cash_session.date,
        "status": cash_session.status,
        "opening_amount": float(cash_session.opening_amount),
        "closing_amount": float(cash_session.closing_amount or 0),
        "difference": float(cash_session.difference or 0),
        "movements": [
            {
                "type": m.type,
                "amount": float(m.amount),
                "source": m.source,
                "description": m.description,
                "created_at": m.created_at
            }
            for m in movements
        ]
    }


@router.get("/history")
def cash_history(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if limit > 50:
        limit = 50

    sessions = (
        db.query(CashSession)
        .order_by(CashSession.date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return success_response(
        message="Historial de cajas.",
        data=[
            {
                "id": s.id,
                "date": s.date,
                "status": s.status,
                "opening_amount": float(s.opening_amount),
                "closing_amount": float(s.closing_amount or 0),
                "difference": float(s.difference or 0),
            }
            for s in sessions
        ]
    )