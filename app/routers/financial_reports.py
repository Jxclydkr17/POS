from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from datetime import datetime, timedelta
from app.db.database import get_db
from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
from app.db.models.product import Product
from app.db.models.expense import Expense
from app.db.models.purchase import Purchase, PurchaseStatus
from app.db.models.customer import Customer
from app.core.dependencies import get_current_user
from app.utils.dt import now_cr, format_cr, cr_day_to_utc_range
from app.constants.expense_categories import CAT_COMPRAS_PROVEEDORES
from app.constants.status_enums import SaleStatus

router = APIRouter(prefix="/financial", tags=["Reportes Financieros"])


def _to_float(val) -> float:
    """Convierte Decimal/None a float seguro."""
    if val is None:
        return 0.0
    return float(val)


def _compute_period(db: Session, start_day, end_day):
    """Calcula las métricas financieras para un período dado.
    Retorna un dict con todos los campos del reporte.
    """
    # FASE 1 — Fix 1.2: rango UTC de [start_day, end_day] CR (half-open).
    # Antes se usaba datetime.combine(d, time.min/max) naive, que SQLAlchemy
    # comparaba contra Sale.created_at (UTC) sin offset, desfasando 6h.
    start, _ = cr_day_to_utc_range(start_day)
    _, end = cr_day_to_utc_range(end_day)

    # ------- Ventas (excluir ANULADAS) -------
    sales = (
        db.query(Sale)
        .filter(
            Sale.created_at >= start,
            Sale.created_at < end,
            Sale.status != SaleStatus.ANULADA,
        )
        .all()
    )
    total_sales = sum(float(s.total) for s in sales)
    sale_ids = [s.id for s in sales]

    # ------- COGS y margen bruto -------
    total_cogs = 0.0
    if sale_ids:
        cogs_result = (
            db.query(
                func.sum(SaleDetail.quantity * func.coalesce(Product.cost, 0))
            )
            .join(Product, SaleDetail.product_id == Product.id)
            .filter(SaleDetail.sale_id.in_(sale_ids))
            .scalar()
        )
        total_cogs = _to_float(cogs_result)

    gross_profit = total_sales - total_cogs
    gross_margin_pct = (gross_profit / total_sales * 100) if total_sales > 0 else 0.0

    # ------- IVA recaudado -------
    total_tax = 0.0
    if sale_ids:
        tax_result = (
            db.query(func.sum(func.coalesce(SaleDetail.tax_amount, 0)))
            .filter(SaleDetail.sale_id.in_(sale_ids))
            .scalar()
        )
        total_tax = _to_float(tax_result)

    # ------- Desglose por método de pago -------
    payment_breakdown = {}
    for s in sales:
        pm = (s.payment_method or "Otro").strip()
        payment_breakdown[pm] = payment_breakdown.get(pm, 0.0) + float(s.total)

    # ------- Ventas crédito vs contado -------
    credit_sales_total = 0.0
    cash_sales_total = 0.0
    credit_sales_count = 0
    cash_sales_count = 0
    for s in sales:
        pm = (s.payment_method or "").strip().lower()
        cond = (s.condicion_venta_code or "").strip()
        is_credit = cond in ("02", "10") or pm in ("credito", "crédito")
        if is_credit:
            credit_sales_total += float(s.total)
            credit_sales_count += 1
        else:
            cash_sales_total += float(s.total)
            cash_sales_count += 1

    # ------- Cuentas por cobrar (global) -------
    receivable_result = (
        db.query(func.coalesce(func.sum(Customer.credit_balance), 0))
        .filter(Customer.credit_balance > 0)
        .scalar()
    )
    total_receivables = _to_float(receivable_result)

    # ------- Gastos -------
    expenses = db.query(Expense).filter(Expense.date >= start, Expense.date < end).all()
    total_expenses = sum(float(e.amount) for e in expenses)

    purchase_expenses = sum(
        float(e.amount) for e in expenses
        if (e.category or "").startswith(CAT_COMPRAS_PROVEEDORES)
    )
    operational_expenses = total_expenses - purchase_expenses

    # 4.3: Desglose de gastos operativos por categoría
    expense_by_category = {}
    for e in expenses:
        cat = (e.category or "Otros").strip()
        if cat.startswith(CAT_COMPRAS_PROVEEDORES):
            continue  # ya se cuenta en purchase_expenses
        expense_by_category[cat] = expense_by_category.get(cat, 0.0) + float(e.amount)

    # ------- Compras en el período -------
    purchases_in_period = (
        db.query(Purchase)
        .options(joinedload(Purchase.supplier))
        .filter(Purchase.entry_date >= start_day, Purchase.entry_date <= end_day)
        .all()
    )
    total_purchases_amount = sum(float(p.amount) for p in purchases_in_period)
    purchases_count = len(purchases_in_period)

    # 4.4: Detalle de compras
    purchases_detail = []
    for p in purchases_in_period:
        purchases_detail.append({
            "id": p.id,
            "invoice_number": p.invoice_number,
            "supplier": p.supplier.name if p.supplier else "—",
            "entry_date": p.entry_date.strftime("%Y-%m-%d") if p.entry_date else "",
            "due_date": p.due_date.strftime("%Y-%m-%d") if p.due_date else "",
            "amount": float(p.amount),
            "paid_amount": p.paid_amount,
            "balance": p.balance,
            "status": p.status.value if p.status else "",
        })

    # ------- Cuentas por pagar (global) -------
    pending_purchases = (
        db.query(Purchase)
        .filter(Purchase.status.in_([
            PurchaseStatus.pendiente,
            PurchaseStatus.recibido,
            PurchaseStatus.parcial,
            PurchaseStatus.vencido,
        ]))
        .all()
    )
    total_payables = sum(p.balance for p in pending_purchases)
    overdue_payables = sum(
        p.balance for p in pending_purchases
        if p.status == PurchaseStatus.vencido
    )

    # ------- Utilidad -------
    net_profit = total_sales - total_expenses

    # ------- Datos diarios para gráfico -------
    daily_data = {}
    current_day = start_day
    while current_day <= end_day:
        key = current_day.strftime("%Y-%m-%d")
        daily_data[key] = {
            "ventas": 0.0, "gastos": 0.0,
            "gastos_operativos": 0.0, "pagos_proveedores": 0.0,
        }
        current_day += timedelta(days=1)

    for s in sales:
        # FASE 2.2 — Fix 2.2: agrupar por día CR (no UTC) para que las
        # ventas nocturnas (CR ≥ 18h) no caigan al día siguiente UTC.
        day = format_cr(s.created_at, "%Y-%m-%d")
        if day in daily_data:
            daily_data[day]["ventas"] += float(s.total)

    for e in expenses:
        day = e.date.strftime("%Y-%m-%d")
        if day in daily_data:
            daily_data[day]["gastos"] += float(e.amount)
            if (e.category or "").startswith(CAT_COMPRAS_PROVEEDORES):
                daily_data[day]["pagos_proveedores"] += float(e.amount)
            else:
                daily_data[day]["gastos_operativos"] += float(e.amount)

    days = sorted(daily_data.keys())
    chart_data = [
        {
            "fecha": d,
            "ventas": daily_data[d]["ventas"],
            "gastos": daily_data[d]["gastos"],
            "gastos_operativos": daily_data[d]["gastos_operativos"],
            "pagos_proveedores": daily_data[d]["pagos_proveedores"],
            "utilidad": daily_data[d]["ventas"] - daily_data[d]["gastos"],
        }
        for d in days
    ]

    return {
        "total_sales": total_sales,
        "total_expenses": total_expenses,
        "net_profit": net_profit,
        "chart_data": chart_data,
        "total_cogs": round(total_cogs, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_margin_pct": round(gross_margin_pct, 2),
        "payment_breakdown": payment_breakdown,
        "credit_sales_total": round(credit_sales_total, 2),
        "credit_sales_count": credit_sales_count,
        "cash_sales_total": round(cash_sales_total, 2),
        "cash_sales_count": cash_sales_count,
        "total_receivables": round(total_receivables, 2),
        "total_tax_collected": round(total_tax, 2),
        "operational_expenses": operational_expenses,
        "purchase_expenses": purchase_expenses,
        "expense_by_category": expense_by_category,      # 4.3
        "total_purchases_amount": total_purchases_amount,
        "purchases_count": purchases_count,
        "purchases_detail": purchases_detail,             # 4.4
        "total_payables": total_payables,
        "overdue_payables": overdue_payables,
    }


@router.get("/summary", dependencies=[Depends(get_current_user)])
def financial_summary(
    start_date: str = Query(None, description="YYYY-MM-DD"),
    end_date: str = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    if start_date:
        start_day = datetime.strptime(start_date, "%Y-%m-%d").date()
    else:
        start_day = (now_cr() - timedelta(days=6)).date()

    if end_date:
        end_day = datetime.strptime(end_date, "%Y-%m-%d").date()
    else:
        end_day = now_cr().date()

    # Período actual
    result = _compute_period(db, start_day, end_day)

    # 4.2: Período anterior (misma duración, inmediatamente antes)
    period_days = (end_day - start_day).days + 1
    prev_end = start_day - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    prev = _compute_period(db, prev_start, prev_end)

    result["previous_period"] = {
        "start_date": prev_start.strftime("%Y-%m-%d"),
        "end_date": prev_end.strftime("%Y-%m-%d"),
        "total_sales": prev["total_sales"],
        "total_expenses": prev["total_expenses"],
        "net_profit": prev["net_profit"],
        "gross_profit": prev["gross_profit"],
        "total_cogs": prev["total_cogs"],
        "total_tax_collected": prev["total_tax_collected"],
    }

    return result