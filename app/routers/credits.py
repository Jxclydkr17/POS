# app/routers/credits.py
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
# ── FASE 3 — Fix 3.1: Importar de dependencies (fuente única) ──
from app.core.dependencies import get_current_user
# ── FASE 3 — Fix 3.2: Rate limiting en endpoints sensibles ──
from app.core.rate_limiter import rate_limit
from app.services.credit_service import (
    add_credit_sale,
    add_credit_payment,
    get_credit_info,
)
from app.schemas.credit import CreditPaymentCreate
from app.utils.responses import success_response


# ── Schema de validación (Fase 8 — Bug 8.3) ──────────────
class CreditSaleCreate(BaseModel):
    sale_id: int


router = APIRouter(prefix="/credits", tags=["Credits"])


# -----------------------------------------------------------
#   CREAR CRÉDITO 
# -----------------------------------------------------------
@router.post("/{customer_id}/add")
def add_credit(
    customer_id: int,
    payload: CreditSaleCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        result = add_credit_sale(db, customer_id, payload.sale_id)

        # ✅ IMPORTANTE: persistir en DB
        db.commit()
        db.refresh(result)

        return success_response(
            message="Crédito registrado correctamente.",
            data={"credit_id": result.id}
        )

    except ValueError as ve:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))



# -----------------------------------------------------------
#   ABONO / PAGO A CRÉDITO
# -----------------------------------------------------------
@router.post("/{customer_id}/payments", dependencies=[rate_limit("credit_payments", 30, 60)])
def pay_credit(
    customer_id: int,
    payload: CreditPaymentCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    try:
        # ── FASE 1: Decimal(str()) en vez de float() para no perder precisión ──
        amount_dec = Decimal(str(payload.amount))

        payment = add_credit_payment(
            db, 
            customer_id, 
            amount_dec,
            payload.payment_method
        )
        db.commit()
        db.refresh(payment)
        summary = get_credit_info(db, customer_id)

        return success_response(
            message="Abono registrado correctamente.",
            data={
                "payment_id": payment.id,
                "payment_method": payment.payment_method,
                "summary": summary
            }
        )

    except ValueError as ve:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------
#   RESUMEN DE CRÉDITO DEL CLIENTE
# -----------------------------------------------------------
@router.get("/{customer_id}")
def credit_summary(
    customer_id: int,
    mov_skip: int = 0,
    mov_limit: int = 20,
    sales_skip: int = 0,
    sales_limit: int = 50,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    summary = get_credit_info(
        db=db,
        customer_id=customer_id,
        mov_skip=mov_skip,
        mov_limit=mov_limit,
        sales_skip=sales_skip,
        sales_limit=sales_limit,
        date_from=date_from,
        date_to=date_to,
    )

    if not summary:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    return success_response(
        message="Resumen obtenido correctamente.",
        data=summary
    )