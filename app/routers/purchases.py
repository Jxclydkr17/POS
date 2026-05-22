# app/routers/purchases.py

from __future__ import annotations

import logging
import os
import shutil
from datetime import date, timedelta
from app.utils.dt import today_cr
from app.utils.db_compat import sql_datediff
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, case, extract
from sqlalchemy.orm import Session, subqueryload

from app.db.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.config import DATA_DIR  # FASE 2 — Fix 2.2: DATA_DIR persiste updates
from app.schemas.api_response import APIResponse
from app.db.models.purchase import Purchase, PurchaseStatus
from app.db.models.supplier import Supplier
from app.schemas.purchase import (
    PurchaseCreate,
    PurchaseUpdate,
    PurchaseOut,
    PurchaseListPageOut,
    PurchaseStatus,
    PurchasePayIn,
    PurchaseRecentOut,
    PurchasePaymentCreate,
    PurchasePaymentOut,
    PurchaseCreditNoteCreate,
    PurchaseCreditNoteOut,
)
from app.db.crud.purchase import (
    get_purchases,
    get_purchase,
    create_purchase,
    update_purchase,
    delete_purchase,
    mark_as_paid,
    receive_purchase,
    add_payment,
    get_payments,
    add_credit_note,
    get_credit_notes,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/purchases",
    tags=["Purchases"],
)


# ============================================================
# 🔹 DASHBOARD DE COMPRAS (mini-dashboard del módulo)
# ============================================================
@router.get("/dashboard", response_model=APIResponse[dict])
def purchases_dashboard(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    today = today_cr()
    week_end = today + timedelta(days=7)
    three_days = today + timedelta(days=3)
    month_start = today.replace(day=1)

    # --- Total por pagar esta semana (vencen esta semana y no pagadas) ---
    payable_this_week = (
        db.query(Purchase)
        .options(subqueryload(Purchase.payments), subqueryload(Purchase.credit_notes))
        .filter(
            Purchase.status.notin_([PurchaseStatus.pagado]),
            Purchase.due_date >= today,
            Purchase.due_date <= week_end,
        )
        .all()
    )
    total_payable_week = sum(p.balance for p in payable_this_week)
    count_payable_week = len(payable_this_week)

    # --- Facturas que vencen en 3 días (urgentes) ---
    expiring_soon = (
        db.query(Purchase)
        .options(subqueryload(Purchase.payments), subqueryload(Purchase.credit_notes))
        .filter(
            Purchase.status.notin_([PurchaseStatus.pagado]),
            Purchase.due_date >= today,
            Purchase.due_date <= three_days,
        )
        .all()
    )
    urgent_invoices = []
    for p in expiring_soon:
        days_left = (p.due_date - today).days
        urgent_invoices.append({
            "id": p.id,
            "invoice_number": p.invoice_number,
            "supplier_id": p.supplier_id,
            "due_date": p.due_date.isoformat(),
            "amount": float(p.amount),
            "balance": p.balance,
            "days_left": days_left,
            "status": p.status.value if p.status else "pendiente",
        })

    # --- Facturas ya vencidas ---
    overdue = (
        db.query(Purchase)
        .options(subqueryload(Purchase.payments), subqueryload(Purchase.credit_notes))
        .filter(
            Purchase.status.notin_([PurchaseStatus.pagado]),
            Purchase.due_date < today,
        )
        .all()
    )
    total_overdue = sum(p.balance for p in overdue)
    count_overdue = len(overdue)

    # --- Gasto acumulado del mes por proveedor ---
    monthly_rows = (
        db.query(
            Supplier.id,
            Supplier.name,
            func.coalesce(func.sum(Purchase.amount), 0).label("total"),
            func.count(Purchase.id).label("count"),
        )
        .join(Purchase, Purchase.supplier_id == Supplier.id)
        .filter(Purchase.entry_date >= month_start, Purchase.entry_date <= today)
        .group_by(Supplier.id, Supplier.name)
        .order_by(func.sum(Purchase.amount).desc())
        .all()
    )
    monthly_by_supplier = [
        {
            "supplier_id": r[0],
            "supplier_name": r[1],
            "total": float(r[2]),
            "count": int(r[3]),
        }
        for r in monthly_rows
    ]
    total_month = sum(s["total"] for s in monthly_by_supplier)

    # --- Tendencia últimos 6 meses ---
    trend_data = []
    for i in range(5, -1, -1):
        m_date = today.replace(day=1) - timedelta(days=i * 30)
        m_start = m_date.replace(day=1)
        if m_start.month == 12:
            m_end = m_start.replace(year=m_start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            m_end = m_start.replace(month=m_start.month + 1, day=1) - timedelta(days=1)

        total_m = (
            db.query(func.coalesce(func.sum(Purchase.amount), 0))
            .filter(Purchase.entry_date >= m_start, Purchase.entry_date <= m_end)
            .scalar()
        )
        trend_data.append({
            "month": m_start.strftime("%Y-%m"),
            "total": float(total_m or 0),
        })

    return APIResponse(
        message="Dashboard de compras",
        data={
            "payable_this_week": total_payable_week,
            "count_payable_week": count_payable_week,
            "urgent_invoices": urgent_invoices,
            "count_urgent": len(urgent_invoices),
            "total_overdue": total_overdue,
            "count_overdue": count_overdue,
            "monthly_by_supplier": monthly_by_supplier,
            "total_month": total_month,
            "trend_6_months": trend_data,
        },
    )


# ============================================================
# 🔹 EXPORTAR compras filtradas (Excel o PDF)
# ============================================================
@router.get("/export")
def export_purchases(
    format: str = Query("excel", description="excel o pdf"),
    status_filter: Optional[str] = Query(None),
    supplier_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # FASE 2 — Fix 2.1: Carga por lotes en vez de limit=10000 en memoria.
    # Itera en batches de 500 para no saturar RAM con años de compras.
    BATCH_SIZE = 500
    MAX_ROWS = 5000  # Tope de seguridad para exports

    all_items = []
    offset = 0
    while offset < MAX_ROWS:
        items, total = get_purchases(
            db=db,
            status_filter=status_filter,
            supplier_id=supplier_id,
            search=search,
            skip=offset,
            limit=BATCH_SIZE,
        )
        if not items:
            break
        all_items.extend(items)
        offset += BATCH_SIZE
        if len(items) < BATCH_SIZE:
            break  # No hay más datos

    suppliers_map = {s.id: s.name for s in db.query(Supplier).all()}

    data = []
    for p in all_items:
        data.append({
            "id": p.id,
            "invoice_number": p.invoice_number,
            "supplier_name": suppliers_map.get(p.supplier_id, str(p.supplier_id)),
            "supplier_id": p.supplier_id,
            "entry_date": str(p.entry_date),
            "due_date": str(p.due_date),
            "amount": float(p.amount),
            "paid_amount": p.paid_amount,
            "balance": p.balance,
            "status": p.status.value if p.status else "",
            "payment_method": p.payment_method or "",
            "received_at": str(p.received_at) if p.received_at else "",
            "paid_at": str(p.paid_at) if p.paid_at else "",
            "notes": p.notes or "",
        })

    # FASE 2 — Fix 2.3: ya no necesitamos os.makedirs("exports", ...).
    # export_utils._resolve_export_filename() crea DATA_DIR/exports/ y resuelve
    # rutas relativas contra ese directorio absoluto. Pasamos basenames simples.

    if format.lower() == "pdf":
        from app.utils.export_utils import export_purchases_pdf

        title_extra = ""
        if status_filter:
            title_extra += f"Estado: {status_filter}  "
        if supplier_id:
            title_extra += f"Proveedor ID: {supplier_id}"

        filepath = export_purchases_pdf(
            data,
            title_extra=title_extra,
            filename="compras_export.pdf",  # FASE 2.3: basename → DATA_DIR/exports/...
        )
        return FileResponse(filepath, filename="reporte_compras.pdf", media_type="application/pdf")
    else:
        from app.utils.export_utils import export_purchases_excel

        filepath = export_purchases_excel(
            data, filename="compras_export.xlsx"  # FASE 2.3: basename → DATA_DIR/exports/...
        )
        return FileResponse(
            filepath,
            filename="reporte_compras.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ============================================================
# 🔹 NOTIFICAR facturas por vencer (por correo)
# ============================================================
@router.post("/notify-expiring", response_model=APIResponse[dict])
def notify_expiring_purchases(
    recipient: str = Query(..., description="Correo destino"),
    days_ahead: int = Query(3, ge=1, le=30),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    today = today_cr()
    limit_date = today + timedelta(days=days_ahead)

    suppliers_map = {s.id: s.name for s in db.query(Supplier).all()}

    # Facturas que vencen pronto o ya vencidas (no pagadas)
    purchases = (
        db.query(Purchase)
        .filter(
            Purchase.status.notin_([PurchaseStatus.pagado]),
            Purchase.due_date <= limit_date,
        )
        .order_by(Purchase.due_date.asc())
        .all()
    )

    if not purchases:
        return APIResponse(
            message="No hay facturas por vencer en ese rango.",
            data={"sent": False, "count": 0},
        )

    alert_data = []
    for p in purchases:
        alert_data.append({
            "invoice_number": p.invoice_number,
            "supplier_name": suppliers_map.get(p.supplier_id, str(p.supplier_id)),
            "due_date": str(p.due_date),
            "amount": float(p.amount),
            "balance": p.balance,
            "status": "vencido" if p.due_date < today else p.status.value,
        })

    from app.utils.email_utils import send_purchase_expiry_alert

    sent = send_purchase_expiry_alert(recipient, alert_data)

    return APIResponse(
        message=f"Alerta enviada a {recipient}" if sent else "No se pudo enviar la alerta (verificar configuración de correo).",
        data={"sent": sent, "count": len(alert_data)},
    )


# ------------------------------------------------------------
# 🔹 Resumen de compras por proveedor
# ------------------------------------------------------------
@router.get("/summary", response_model=APIResponse[dict])
def purchases_summary(
    supplier_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    pending_total = db.query(
        func.coalesce(
            func.sum(
                case(
                    (Purchase.status.in_([
                        PurchaseStatus.pendiente,
                        PurchaseStatus.vencido,
                        PurchaseStatus.recibido,
                        PurchaseStatus.parcial,
                    ]), Purchase.amount),
                    else_=0
                )
            ),
            0
        )
    ).filter(Purchase.supplier_id == supplier_id).scalar()

    paid_avg_days = db.query(
        func.avg(sql_datediff(Purchase.paid_at, Purchase.entry_date))
    ).filter(
        Purchase.supplier_id == supplier_id,
        Purchase.status == PurchaseStatus.pagado,
        Purchase.paid_at.isnot(None),
    ).scalar()

    return APIResponse(
        message="Resumen de compras",
        data={
            "pending_total": float(pending_total or 0),
            "paid_avg_days": float(paid_avg_days) if paid_avg_days is not None else None,
        }
    )


# ------------------------------------------------------------
# 🔹 Últimas compras por proveedor
# ------------------------------------------------------------
@router.get("/recent", response_model=APIResponse[List[PurchaseRecentOut]])
def recent_purchases(
    supplier_id: int = Query(..., gt=0),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    rows = (
        db.query(Purchase.entry_date, Purchase.amount)
        .filter(Purchase.supplier_id == supplier_id)
        .order_by(Purchase.entry_date.desc())
        .limit(limit)
        .all()
    )
    data = [{"entry_date": r[0], "amount": float(r[1] or 0)} for r in rows]
    return APIResponse(message="Últimas compras del proveedor", data=data)


# ------------------------------------------------------------
# 🔹 Listar compras
# ------------------------------------------------------------
@router.get("/", response_model=APIResponse[PurchaseListPageOut])
def list_purchases(
    status_filter: Optional[PurchaseStatus] = Query(None),
    supplier_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        items, total = get_purchases(
            db=db, status_filter=status_filter, supplier_id=supplier_id,
            search=search, skip=skip, limit=limit,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return APIResponse(
        message="Compras cargadas correctamente",
        data={"items": items, "total": total, "skip": skip, "limit": limit},
    )


# ------------------------------------------------------------
# 🔹 Detalle de compra
# ------------------------------------------------------------
@router.get("/{purchase_id}", response_model=APIResponse[PurchaseOut])
def get_purchase_detail(
    purchase_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    purchase = get_purchase(db, purchase_id)
    return APIResponse(message="Compra encontrada", data=purchase)


# ------------------------------------------------------------
# 🔹 Crear compra
# ------------------------------------------------------------
@router.post("/", response_model=APIResponse[PurchaseOut])
def create(
    payload: PurchaseCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        purchase = create_purchase(db, payload)
        db.commit()
        return APIResponse(message="Compra registrada correctamente", data=purchase)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al crear compra: {e}")
        raise HTTPException(status_code=500, detail="Error interno al registrar compra.")


# ------------------------------------------------------------
# 🔹 Actualizar compra
# ------------------------------------------------------------
@router.put("/{purchase_id}", response_model=APIResponse[PurchaseOut])
def update(
    purchase_id: int,
    payload: PurchaseUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        purchase = update_purchase(db, purchase_id, payload)
        db.commit()
        return APIResponse(message="Compra actualizada correctamente", data=purchase)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al actualizar compra: {e}")
        raise HTTPException(status_code=500, detail="Error interno al actualizar compra.")


# ------------------------------------------------------------
# 🔹 Recibir mercadería
# ------------------------------------------------------------
@router.put("/{purchase_id}/receive", response_model=APIResponse[PurchaseOut])
def receive(
    purchase_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        purchase = receive_purchase(db, purchase_id)
        db.commit()
        return APIResponse(message="Mercadería recibida correctamente", data=purchase)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al recibir mercadería: {e}")
        raise HTTPException(status_code=500, detail="Error interno al recibir mercadería.")


# ------------------------------------------------------------
# 🔹 Registrar abono / pago parcial
# ------------------------------------------------------------
@router.post("/{purchase_id}/payments", response_model=APIResponse[PurchaseOut])
def register_payment(
    purchase_id: int,
    payload: PurchasePaymentCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        purchase = add_payment(db, purchase_id, payload)
        db.commit()
        return APIResponse(message="Abono registrado correctamente", data=purchase)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al registrar abono: {e}")
        raise HTTPException(status_code=500, detail="Error interno al registrar abono.")


# ------------------------------------------------------------
# 🔹 Listar pagos de una compra
# ------------------------------------------------------------
@router.get("/{purchase_id}/payments", response_model=APIResponse[List[PurchasePaymentOut]])
def list_payments(
    purchase_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    payments = get_payments(db, purchase_id)
    return APIResponse(message="Pagos de la compra", data=payments)


# ------------------------------------------------------------
# 🔹 Registrar nota de crédito / devolución
# ------------------------------------------------------------
@router.post("/{purchase_id}/credit-notes", response_model=APIResponse[PurchaseOut])
def register_credit_note(
    purchase_id: int,
    payload: PurchaseCreditNoteCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        purchase = add_credit_note(db, purchase_id, payload)
        db.commit()
        return APIResponse(message="Nota de crédito registrada correctamente", data=purchase)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al registrar nota de crédito: {e}")
        raise HTTPException(status_code=500, detail="Error interno al registrar nota de crédito.")


# ------------------------------------------------------------
# 🔹 Listar notas de crédito de una compra
# ------------------------------------------------------------
@router.get("/{purchase_id}/credit-notes", response_model=APIResponse[List[PurchaseCreditNoteOut]])
def list_credit_notes(
    purchase_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    notes = get_credit_notes(db, purchase_id)
    return APIResponse(message="Notas de crédito de la compra", data=notes)


# ------------------------------------------------------------
# 🔹 Marcar como pagada (legacy — paga saldo completo)
# ------------------------------------------------------------
@router.put("/{purchase_id}/pay", response_model=APIResponse[PurchaseOut])
def pay_purchase(
    purchase_id: int,
    payload: PurchasePayIn,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        purchase = mark_as_paid(db, purchase_id, payment_method=payload.payment_method)
        db.commit()
        return APIResponse(message="Compra marcada como pagada", data=purchase)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al marcar compra como pagada: {e}")
        raise HTTPException(status_code=500, detail="Error interno al marcar como pagada.")


# ------------------------------------------------------------
# 🔹 Subir PDF
# ------------------------------------------------------------
# ── FASE 2 — Fix 2.2: uploads persistentes en DATA_DIR ──
# Antes: {project}/uploads/purchases (→ _internal/uploads/purchases en .exe),
# borrado en cada update del installer. DATA_DIR/uploads/purchases persiste.
UPLOAD_DIR = DATA_DIR / "uploads" / "purchases"


@router.post("/{purchase_id}/upload-pdf", response_model=APIResponse[PurchaseOut])
async def upload_purchase_pdf(
    purchase_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    purchase = get_purchase(db, purchase_id)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos PDF.")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = f"purchase_{purchase_id}_{os.path.basename(file.filename)}"
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    purchase.pdf_path = dest_path
    try:
        db.commit()
        db.refresh(purchase)
    except Exception:
        db.rollback()
        raise
    return APIResponse(message="PDF subido correctamente", data=purchase)


# ------------------------------------------------------------
# 🔹 Eliminar compra
# ------------------------------------------------------------
@router.delete("/{purchase_id}", response_model=APIResponse, dependencies=[Depends(require_role("admin"))])
def delete(
    purchase_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        delete_purchase(db, purchase_id)
        db.commit()
        return APIResponse(message="Compra eliminada correctamente")
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al eliminar compra: {e}")
        raise HTTPException(status_code=500, detail="Error interno al eliminar compra.")