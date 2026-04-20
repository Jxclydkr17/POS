from datetime import datetime, date, time, timedelta
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.dependencies import get_current_user
from app.db.models.sale import Sale
from app.db.models.expense import Expense
from app.db.models.product import Product
from app.db.models.customer import Customer
from app.db.models.purchase import Purchase, PurchaseStatus
from app.db.models.sale_detail import SaleDetail
from app.db.models.supplier import Supplier
from app.db.crud.cash import get_cash_report
from app.utils.responses import success_response
from app.services.dashboard_snapshot_service import ensure_dashboard_snapshot, get_dashboard_snapshot
from app.utils.dt import today_cr

logger = logging.getLogger(__name__)


# ── FASE 3 — Fix 3.3: Auth a nivel de router ──
# Todos los endpoints heredan protección automáticamente,
# incluyendo los que se agreguen en el futuro.
router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(get_current_user)],
)


# -----------------------------
# Helpers de tendencia
# -----------------------------

def _safe_pct_change(current: float, previous: float) -> float | None:
    current = float(current or 0)
    previous = float(previous or 0)

    if previous == 0:
        if current == 0:
            return 0.0
        return None  # evita % engañoso cuando ayer fue 0

    return round(((current - previous) / previous) * 100, 1)


def _trend_type(current: float, previous: float, inverse_good: bool = False) -> str:
    current = float(current or 0)
    previous = float(previous or 0)

    if current == previous:
        return "neutral"

    went_up = current > previous

    if inverse_good:
        return "positive" if not went_up else "negative"

    return "positive" if went_up else "negative"


def _build_currency_trend(
    current: float,
    previous: float,
    compare_label: str = "vs ayer",
    inverse_good: bool = False
) -> dict:
    current = float(current or 0)
    previous = float(previous or 0)
    diff = round(current - previous, 2)
    pct = _safe_pct_change(current, previous)
    trend_type = _trend_type(current, previous, inverse_good=inverse_good)

    if pct is None:
        if previous == 0 and current > 0:
            text = f"+{current:,.2f} {compare_label}"
        else:
            text = compare_label
    else:
        sign = "+" if pct > 0 else ""
        text = f"{sign}{pct}% {compare_label}"

    return {
        "previous": previous,
        "delta": diff,
        "pct": pct,
        "text": text,
        "type": trend_type,
    }


def _build_count_trend(
    current: int,
    previous: int,
    compare_label: str = "respecto a ayer",
    inverse_good: bool = False
) -> dict:
    current = int(current or 0)
    previous = int(previous or 0)
    diff = current - previous
    trend_type = _trend_type(current, previous, inverse_good=inverse_good)

    if diff == 0:
        text = f"Sin cambios {compare_label}"
        trend_type = "neutral"
    else:
        sign = "+" if diff > 0 else ""
        text = f"{sign}{diff} {compare_label}"

    pct = _safe_pct_change(current, previous)

    return {
        "previous": previous,
        "delta": diff,
        "pct": pct,
        "text": text,
        "type": trend_type,
    }


# ── Fix 3.3: Se quitó dependencies=[Depends(get_current_user)] de cada
# endpoint individual — ahora está a nivel de router arriba. ──

@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    today = today_cr()
    start = datetime.combine(today, time.min)
    end = datetime.combine(today, time.max)

    yesterday = today - timedelta(days=1)
    y_start = datetime.combine(yesterday, time.min)
    y_end = datetime.combine(yesterday, time.max)

    # respaldo: aseguramos snapshot de ayer
    yesterday_snapshot = ensure_dashboard_snapshot(db, yesterday)
    # FASE 2 — Fix 2.3: Commit protegido con rollback.
    # Si falla (BD llena, lock, etc.), el dashboard sigue funcionando
    # con datos en vivo; solo pierde el snapshot persistido.
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("No se pudo persistir el snapshot del dashboard, continuando con datos en vivo")
        yesterday_snapshot = get_dashboard_snapshot(db, yesterday)

    # hoy normalmente lo dejamos dinámico para mostrar tiempo real,
    # pero también podés guardar snapshot si querés.
    today_snapshot = get_dashboard_snapshot(db, today)

    # -----------------------------
    # Ventas de hoy
    # -----------------------------
    sales_total = (
        db.query(func.coalesce(func.sum(Sale.total), 0))
        .filter(Sale.created_at >= start, Sale.created_at <= end)
        .scalar()
    )

    sales_total_yesterday = (
        db.query(func.coalesce(func.sum(Sale.total), 0))
        .filter(Sale.created_at >= y_start, Sale.created_at <= y_end)
        .scalar()
    )

    # -----------------------------
    # Gastos de hoy
    # -----------------------------
    expenses_total = (
        db.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.date >= start, Expense.date <= end)
        .scalar()
    )

    expenses_total_yesterday = (
        db.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.date >= y_start, Expense.date <= y_end)
        .scalar()
    )

    # -----------------------------
    # Utilidad estimada de hoy
    # -----------------------------
    estimated_profit = float(sales_total or 0) - float(expenses_total or 0)
    estimated_profit_yesterday = float(sales_total_yesterday or 0) - float(expenses_total_yesterday or 0)

    # -----------------------------
    # Productos críticos
    # stock <= min_stock y activos
    # -----------------------------
    critical_products = (
        db.query(func.count(Product.id))
        .filter(
            Product.is_active == True,
            Product.stock <= func.coalesce(Product.min_stock, 0)
        )
        .scalar()
    )

    # -----------------------------
    # Créditos por cobrar
    # suma de saldos pendientes
    # -----------------------------
    credits_receivable = (
        db.query(func.coalesce(func.sum(Customer.credit_balance), 0))
        .filter(Customer.credit_balance > 0)
        .scalar()
    )

    # -----------------------------
    # Compras pendientes
    # -----------------------------
    pending_purchases = (
        db.query(
            func.coalesce(
                func.sum(
                    case(
                        (
                            Purchase.status.in_(
                                [PurchaseStatus.pendiente, PurchaseStatus.recibido, PurchaseStatus.vencido]
                            ),
                            Purchase.amount
                        ),
                        else_=0
                    )
                ),
                0
            )
        )
        .scalar()
    )

    # -----------------------------
    # Caja actual / diferencia
    # -----------------------------
    cash_report = get_cash_report(db, today) or {}

    cash_current = float(cash_report.get("expected", 0) or 0)
    cash_difference = float(cash_report.get("difference", 0) or 0)
    cash_status = cash_report.get("status", "no_session")

    cash_report_yesterday = get_cash_report(db, yesterday) or {}
    cash_current_yesterday = float(getattr(yesterday_snapshot, "cash_expected", 0) or 0)

    # -----------------------------
    # Construir trends
    # -----------------------------
    sales_trend = _build_currency_trend(
        current=float(sales_total or 0),
        previous=float(sales_total_yesterday or 0),
        compare_label="vs ayer"
    )

    profit_trend = _build_currency_trend(
        current=float(estimated_profit or 0),
        previous=float(estimated_profit_yesterday or 0),
        compare_label="vs ayer"
    )

    cash_trend = _build_currency_trend(
        current=float(cash_current or 0),
        previous=float(cash_current_yesterday or 0),
        compare_label="vs ayer"
    )

    critical_trend = _build_count_trend(
        current=int(critical_products or 0),
        previous=int(getattr(yesterday_snapshot, "critical_products", 0) or 0),
        compare_label="respecto a ayer",
        inverse_good=True
    )

    credits_trend = _build_currency_trend(
        current=float(credits_receivable or 0),
        previous=float(getattr(yesterday_snapshot, "credits_receivable", 0) or 0),
        compare_label="vs ayer",
        inverse_good=True
    )

    pending_purchases_trend = _build_currency_trend(
        current=float(pending_purchases or 0),
        previous=float(getattr(yesterday_snapshot, "pending_purchases", 0) or 0),
        compare_label="vs ayer",
        inverse_good=True
    )

    return success_response(
        message="Resumen del dashboard obtenido correctamente.",
        data={
            "sales_today": float(sales_total or 0),
            "estimated_profit_today": float(estimated_profit or 0),
            "critical_products": int(critical_products or 0),
            "credits_receivable": float(credits_receivable or 0),
            "cash_current": cash_current,
            "cash_difference": cash_difference,
            "cash_status": cash_status,
            "pending_purchases": float(pending_purchases or 0),

            "trends": {
                "sales_today": sales_trend,
                "estimated_profit_today": profit_trend,
                "critical_products": critical_trend,
                "credits_receivable": credits_trend,
                "cash_current": cash_trend,
                "pending_purchases": pending_purchases_trend,
            }
        }
    )


# -----------------------------
# Helpers para top-lists
# -----------------------------

def _get_top_sold_products_today(db: Session, start: datetime, end: datetime, limit: int = 5):
    rows = (
        db.query(
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            func.coalesce(func.sum(SaleDetail.quantity), 0).label("total_qty"),
            func.coalesce(func.sum(SaleDetail.subtotal), 0).label("total_amount"),
        )
        .join(SaleDetail, SaleDetail.product_id == Product.id)
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .filter(Sale.created_at >= start, Sale.created_at <= end)
        .group_by(Product.id, Product.name)
        .order_by(func.sum(SaleDetail.quantity).desc(), func.sum(SaleDetail.subtotal).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "product_id": r.product_id,
            "name": r.product_name,
            "quantity": int(r.total_qty or 0),
            "amount": float(r.total_amount or 0),
        }
        for r in rows
    ]


def _get_top_risk_products(db: Session, limit: int = 5):
    products = (
        db.query(Product)
        .filter(Product.is_active == True)
        .filter(Product.stock <= func.coalesce(Product.min_stock, 0))
        .all()
    )

    items = []
    for p in products:
        stock = int(p.stock or 0)
        min_stock = int(p.min_stock or 0)
        shortage = max(min_stock - stock, 0)

        risk_score = shortage
        if stock <= 0:
            risk_score += 1000

        items.append({
            "product_id": p.id,
            "name": p.name,
            "stock": stock,
            "min_stock": min_stock,
            "shortage": shortage,
            "risk_score": risk_score,
        })

    items.sort(key=lambda x: (x["risk_score"], x["shortage"]), reverse=True)
    return items[:limit]


def _get_top_customers_with_balance(db: Session, limit: int = 5):
    rows = (
        db.query(Customer)
        .filter(Customer.credit_balance > 0)
        .order_by(Customer.credit_balance.desc(), Customer.name.asc())
        .limit(limit)
        .all()
    )

    return [
        {
            "customer_id": c.id,
            "name": c.name,
            "credit_balance": float(c.credit_balance or 0),
            "credit_limit": float(c.credit_limit or 0),
        }
        for c in rows
    ]


def _get_top_suppliers_with_critical_products(db: Session, limit: int = 5):
    rows = (
        db.query(
            Supplier.id.label("supplier_id"),
            Supplier.name.label("supplier_name"),
            func.count(Product.id).label("critical_products"),
        )
        .join(Product, Product.supplier_id == Supplier.id)
        .filter(Product.is_active == True)
        .filter(Product.stock <= func.coalesce(Product.min_stock, 0))
        .group_by(Supplier.id, Supplier.name)
        .order_by(func.count(Product.id).desc(), Supplier.name.asc())
        .limit(limit)
        .all()
    )

    return [
        {
            "supplier_id": r.supplier_id,
            "name": r.supplier_name,
            "critical_products": int(r.critical_products or 0),
        }
        for r in rows
    ]


# -----------------------------
# Endpoint: GET /dashboard/top-lists
# -----------------------------

@router.get("/top-lists")
def dashboard_top_lists(db: Session = Depends(get_db)):
    today = today_cr()
    start = datetime.combine(today, time.min)
    end = datetime.combine(today, time.max)

    return success_response(
        message="Top lists del dashboard obtenidas correctamente.",
        data={
            "top_sold_products_today": _get_top_sold_products_today(db, start, end, limit=5),
            "top_risk_products": _get_top_risk_products(db, limit=5),
            "top_customers_with_balance": _get_top_customers_with_balance(db, limit=5),
            "top_suppliers_with_critical_products": _get_top_suppliers_with_critical_products(db, limit=5),
        }
    )