from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date
from app.utils.dt import today_cr

from app.db.database import get_db
from app.schemas.expense import ExpenseCreate, ExpenseUpdate
from app.services.expense_service import (
    add_expense_service,
    get_expenses_service,
    delete_expense_service,
    update_expense_service,
)
from app.services.cash_movement_service import register_cash_movement
from app.db.models.cash_session import CashSession
from app.db.models.cash_movement import CashMovement
from app.db.models.expense import Expense
from app.db.models.user import User
from app.utils.responses import success_response, error_response
from app.constants.expense_categories import CAT_GASTOS_CAJA
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/expenses", tags=["Gastos"])


# ============================================================
# 🟦 Registrar gasto
# ============================================================
@router.post("/")
def add_expense(
    expense: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        # -------------------------------------------------
        # 1️⃣ Guardar el gasto (con user_id de auditoría)
        # -------------------------------------------------
        expense_obj = add_expense_service(
            expense.model_dump(), db, user_id=current_user.id
        )

        # -------------------------------------------------
        # 2️⃣ Solo crear movimiento de caja si es "Gastos de caja"
        # -------------------------------------------------
        if expense.category == CAT_GASTOS_CAJA:
            # Buscar caja abierta
            cash_session = (
                db.query(CashSession)
                .filter(
                    CashSession.status == "open",
                    CashSession.date == today_cr()
                )
                .first()
            )

            if not cash_session:
                # Si no hay caja abierta, revertir el gasto
                db.rollback()
                return error_response(
                    message="No hay una caja abierta para registrar un gasto de caja.",
                    status_code=400
                )

            # Registrar salida de caja
            register_cash_movement(
                db=db,
                cash_session_id=cash_session.id,
                movement_type="OUT",
                amount=expense_obj.amount,
                source="EXPENSE",
                description=expense_obj.description,
                reference_id=expense_obj.id
            )

        # -------------------------------------------------
        # 3️⃣ Confirmar transacción
        # -------------------------------------------------
        db.commit()

        return success_response(
            message="Gasto registrado correctamente.",
            data={
                "expense_id": expense_obj.id,
                "category": expense.category,
                "amount": float(expense.amount),
                "payment_method": expense.payment_method,
                "created_cash_movement": expense.category == CAT_GASTOS_CAJA
            }
        )

    except Exception as e:
        db.rollback()
        return error_response(
            message="Error registrando el gasto.",
            status_code=500,
            error_details={"detail": str(e)}
        )

# ============================================================
# 🟩 Obtener gastos con filtros
# ============================================================
@router.get("/")
def get_expenses(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    if limit > 100:
        limit = 100

    data = get_expenses_service(
        db=db,
        start_date=start_date,
        end_date=end_date,
        category=category,
        skip=skip,
        limit=limit
    )

    return success_response(
        message="Listado de gastos obtenido correctamente.",
        data=data
    )

# ============================================================
# 🟨 Editar gasto por ID
# ============================================================
@router.put("/{expense_id}")
def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        # Solo enviar campos que realmente vinieron con valor
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            return error_response(
                message="No se enviaron campos para actualizar.",
                status_code=400
            )

        updated = update_expense_service(expense_id, updates, db)

        # Si cambió el monto y es "Gastos de caja", actualizar movimiento de caja
        if updated.category == CAT_GASTOS_CAJA and "amount" in updates:
            cash_movement = (
                db.query(CashMovement)
                .filter(
                    CashMovement.source == "EXPENSE",
                    CashMovement.reference_id == expense_id
                )
                .first()
            )
            if cash_movement:
                cash_movement.amount = float(updated.amount)

        db.commit()

        return success_response(
            message="Gasto actualizado correctamente.",
            data={
                "expense_id": updated.id,
                "category": updated.category,
                "amount": float(updated.amount),
                "payment_method": updated.payment_method,
            }
        )
    except Exception as e:
        db.rollback()
        return error_response(
            message="Error actualizando el gasto.",
            status_code=500,
            error_details={"detail": str(e)}
        )

# ============================================================
# 🟥 Eliminar gasto por ID (con reversión de movimiento de caja)
# ============================================================
@router.delete("/{expense_id}")
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    try:
        # -------------------------------------------------
        # 1️⃣ Buscar el gasto antes de eliminar
        # -------------------------------------------------
        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if not expense:
            return error_response(
                message="Gasto no encontrado.",
                status_code=404
            )

        # -------------------------------------------------
        # 2️⃣ Si era "Gastos de caja", eliminar el movimiento de caja asociado
        # -------------------------------------------------
        if expense.category == CAT_GASTOS_CAJA:
            cash_movement = (
                db.query(CashMovement)
                .filter(
                    CashMovement.source == "EXPENSE",
                    CashMovement.reference_id == expense_id
                )
                .first()
            )
            if cash_movement:
                db.delete(cash_movement)

        # -------------------------------------------------
        # 3️⃣ Eliminar el gasto
        # -------------------------------------------------
        deleted = delete_expense_service(expense_id=expense_id, db=db)
        db.commit()

        return success_response(
            message="Gasto eliminado correctamente.",
            data={"expense_id": deleted["expense_id"]}
        )
    except Exception as e:
        db.rollback()
        return error_response(
            message="Error eliminando el gasto.",
            status_code=500,
            error_details={"detail": str(e)}
        )