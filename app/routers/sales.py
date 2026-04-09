# app/routers/sales.py
"""
FASE 4.1 — Router delgado: solo valida entrada, llama al servicio y devuelve respuesta.
Toda la lógica de negocio vive en app.db.crud.sale_crud.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models.user import User
from app.schemas.sale import SaleCreate, SaleUpdate, SaleCancelRequest
from app.core.dependencies import get_current_user, require_role
from app.core.logger import logger
# ── FASE 3 — Fix 3.2: Rate limiting en endpoints sensibles ──
from app.core.rate_limiter import rate_limit
from app.utils.dt import today_cr
from app.utils.responses import success_response

from app.db.crud import sale_crud


router = APIRouter(prefix="/sales", tags=["Ventas"])


# ═══════════════════════════════════════════════════
# POST /sales/  —  Crear venta
# ═══════════════════════════════════════════════════
@router.post("/", dependencies=[rate_limit("sales_create", 60, 60)])
def create_sale(
    sale_in: SaleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        # ── FASE 5 — Fix 5.1: Router es dueño del commit (Unit of Work) ──
        result = sale_crud.create_sale(db, sale_in, current_user)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al registrar venta: {e}")
        raise HTTPException(status_code=500, detail="Error interno al registrar la venta.")


# ═══════════════════════════════════════════════════
# GET /sales/  —  Listado paginado
# ═══════════════════════════════════════════════════
@router.get("/", dependencies=[Depends(get_current_user)])
def get_sales(
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    return sale_crud.list_sales_paginated(db, search=search, page=page, page_size=page_size)


# ═══════════════════════════════════════════════════
# GET /sales/today
# ═══════════════════════════════════════════════════
@router.get("/today", dependencies=[Depends(get_current_user)])
def get_today_sales(skip: int = 0, limit: int = 100, last_id: int = None, db: Session = Depends(get_db)):
    today = today_cr()
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today, datetime.max.time()) + timedelta(hours=6)  # buffer legacy UTC
    data = sale_crud.get_sales_by_range(db, start, end, skip=skip, limit=min(limit, 500), last_id=last_id)
    return success_response(message="Ventas del día", data=data)


# ═══════════════════════════════════════════════════
# GET /sales/date/{report_date}
# ═══════════════════════════════════════════════════
@router.get("/date/{report_date}", dependencies=[Depends(get_current_user)])
def get_sales_by_date(report_date: str, skip: int = 0, limit: int = 100, last_id: int = None, db: Session = Depends(get_db)):
    try:
        target_date = date.fromisoformat(report_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato inválido. Usa YYYY-MM-DD.")

    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date, datetime.max.time()) + timedelta(hours=6)  # buffer legacy UTC
    data = sale_crud.get_sales_by_range(db, start, end, skip=skip, limit=min(limit, 500), last_id=last_id)
    return success_response(message=f"Ventas del {report_date}", data=data)


# ═══════════════════════════════════════════════════
# GET /sales/{sale_id}
# ═══════════════════════════════════════════════════
@router.get("/{sale_id}", dependencies=[Depends(get_current_user)])
def get_sale(sale_id: int, db: Session = Depends(get_db)):
    return sale_crud.get_sale_detail(db, sale_id)


# ═══════════════════════════════════════════════════
# PUT /sales/{sale_id}  —  Editar venta en PENDING
# ── FASE 2 — Fix 2.5: Requiere admin + registra quién editó ──
# ═══════════════════════════════════════════════════
@router.put("/{sale_id}", dependencies=[Depends(require_role("admin")), rate_limit("sales_edit", 20, 60)])
def update_sale(
    sale_id: int,
    sale_in: SaleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = sale_crud.update_sale(db, sale_id, sale_in, current_user)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al editar venta #{sale_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al editar la venta.")


# ═══════════════════════════════════════════════════
# POST /sales/{sale_id}/cancel  —  Nota de Crédito
# ═══════════════════════════════════════════════════
@router.post("/{sale_id}/cancel", dependencies=[Depends(require_role("admin"))])
def cancel_sale(
    sale_id: int,
    body: SaleCancelRequest = SaleCancelRequest(),
    db: Session = Depends(get_db),
):
    try:
        result = sale_crud.cancel_sale_with_nc(db, sale_id, razon=body.razon)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al generar NC para venta #{sale_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al generar la Nota de Crédito.")


# ═══════════════════════════════════════════════════
# DELETE /sales/{sale_id}  —  Anulación simple
# ═══════════════════════════════════════════════════
@router.delete("/{sale_id}", dependencies=[Depends(require_role("admin"))])
def delete_sale(sale_id: int, db: Session = Depends(get_db)):
    try:
        result = sale_crud.void_sale_simple(db, sale_id)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al anular venta #{sale_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al anular la venta.")


# ═══════════════════════════════════════════════════
# POST /sales/{sale_id}/regenerate-pdf
# ═══════════════════════════════════════════════════
@router.post("/{sale_id}/regenerate-pdf", dependencies=[Depends(get_current_user)])
def regenerate_pdf(sale_id: int, db: Session = Depends(get_db)):
    try:
        return sale_crud.regenerate_sale_pdf(db, sale_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al regenerar PDF de venta #{sale_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al regenerar el PDF.")