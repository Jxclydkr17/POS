from datetime import date

from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.db.models.sale import Sale
from app.db.models.expense import Expense
from app.db.models.product import Product
from app.db.models.customer import Customer
from app.db.models.purchase import Purchase, PurchaseStatus
from app.db.models.dashboard_snapshot import DashboardSnapshot
from app.db.crud.cash import get_cash_report
from app.utils.dt import cr_day_to_utc_range


def build_dashboard_snapshot_data(db: Session, target_date: date) -> dict:
    # FASE 1 — Fix 1.2: rango UTC del día CR (half-open: [start, end)).
    # Antes se usaba datetime.combine(d, time.min/max) naive, que SQLAlchemy
    # comparaba contra Sale.created_at (UTC) sin offset, desfasando 6h.
    start, end = cr_day_to_utc_range(target_date)

    sales_total = (
        db.query(func.coalesce(func.sum(Sale.total), 0))
        .filter(Sale.created_at >= start, Sale.created_at < end)
        .scalar()
    )

    expenses_total = (
        db.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.date >= start, Expense.date < end)
        .scalar()
    )

    estimated_profit = float(sales_total or 0) - float(expenses_total or 0)

    critical_products = (
        db.query(func.count(Product.id))
        .filter(
            Product.is_active == True,
            Product.stock <= func.coalesce(Product.min_stock, 0)
        )
        .scalar()
    )

    credits_receivable = (
        db.query(func.coalesce(func.sum(Customer.credit_balance), 0))
        .filter(Customer.credit_balance > 0)
        .scalar()
    )

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

    cash_report = get_cash_report(db, target_date) or {}
    cash_expected = float(cash_report.get("expected", 0) or 0)
    cash_difference = float(cash_report.get("difference", 0) or 0)

    return {
        "snapshot_date": target_date,
        "sales_today": float(sales_total or 0),
        "estimated_profit_today": float(estimated_profit or 0),
        "critical_products": int(critical_products or 0),
        "credits_receivable": float(credits_receivable or 0),
        "pending_purchases": float(pending_purchases or 0),
        "cash_expected": cash_expected,
        "cash_difference": cash_difference,
    }


def get_dashboard_snapshot(db: Session, target_date: date) -> DashboardSnapshot | None:
    return (
        db.query(DashboardSnapshot)
        .filter(DashboardSnapshot.snapshot_date == target_date)
        .first()
    )


def save_dashboard_snapshot(db: Session, target_date: date) -> DashboardSnapshot:
    data = build_dashboard_snapshot_data(db, target_date)
    snapshot = get_dashboard_snapshot(db, target_date)

    if snapshot:
        snapshot.sales_today = data["sales_today"]
        snapshot.estimated_profit_today = data["estimated_profit_today"]
        snapshot.critical_products = data["critical_products"]
        snapshot.credits_receivable = data["credits_receivable"]
        snapshot.pending_purchases = data["pending_purchases"]
        snapshot.cash_expected = data["cash_expected"]
        snapshot.cash_difference = data["cash_difference"]
    else:
        snapshot = DashboardSnapshot(**data)
        db.add(snapshot)

    # FASE 2 — Fix: flush only; el router (cash.close) es dueño del commit.
    # Esto hace que cierre de caja + snapshot sean atómicos.
    db.flush()
    db.refresh(snapshot)
    return snapshot


def ensure_dashboard_snapshot(db: Session, target_date: date) -> DashboardSnapshot:
    snapshot = get_dashboard_snapshot(db, target_date)
    if snapshot:
        return snapshot
    return save_dashboard_snapshot(db, target_date)