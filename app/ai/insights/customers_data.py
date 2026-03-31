from datetime import date
from app.utils.dt import today_cr
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models.customer import Customer
from app.db.models.sale import Sale
from app.db.models.credit import Credit


def get_customers_credit_base_data(db: Session):
    """
    Retorna datos base para análisis de riesgo de clientes.
    Incluye: aging real (desde último abono), valor total (cash+crédito),
    y métricas para segmentación automática.
    """

    today = today_cr()

    # ── Sub-query: último abono real por cliente ──
    last_payment_sq = (
        db.query(
            Credit.customer_id.label("customer_id"),
            func.max(Credit.created_at).label("last_payment_date"),
            func.count(Credit.id).label("num_payments"),
        )
        .filter(Credit.type == "payment")
        .group_by(Credit.customer_id)
        .subquery()
    )

    # ── Sub-query: ventas totales (cash + crédito) por cliente ──
    total_sales_sq = (
        db.query(
            Sale.customer_id.label("customer_id"),
            func.count(Sale.id).label("total_all_sales"),
            func.sum(Sale.total).label("total_all_amount"),
            func.avg(Sale.total).label("avg_all_ticket"),
            func.max(Sale.created_at).label("last_sale_date"),
        )
        .filter(Sale.customer_id.isnot(None))
        .group_by(Sale.customer_id)
        .subquery()
    )

    # ── Query principal: crédito + valor total ──
    rows = (
        db.query(
            Customer.id.label("customer_id"),
            Customer.name.label("name"),
            Customer.credit_balance.label("credit_balance"),
            Customer.credit_limit.label("credit_limit"),
            Customer.has_credit_limit.label("has_credit_limit"),
            Customer.customer_type.label("customer_type"),

            func.max(Sale.created_at).label("last_credit_sale_date"),
            func.count(Sale.id).label("num_credit_sales"),
            func.sum(Sale.total).label("total_credit_sales"),

            last_payment_sq.c.last_payment_date,
            last_payment_sq.c.num_payments,

            total_sales_sq.c.total_all_sales,
            total_sales_sq.c.total_all_amount,
            total_sales_sq.c.avg_all_ticket,
            total_sales_sq.c.last_sale_date,
        )
        .outerjoin(Sale, (Sale.customer_id == Customer.id) & (Sale.payment_method == "credit"))
        .outerjoin(last_payment_sq, last_payment_sq.c.customer_id == Customer.id)
        .outerjoin(total_sales_sq, total_sales_sq.c.customer_id == Customer.id)
        .filter(Customer.is_active == True)
        .group_by(
            Customer.id,
            last_payment_sq.c.last_payment_date,
            last_payment_sq.c.num_payments,
            total_sales_sq.c.total_all_sales,
            total_sales_sq.c.total_all_amount,
            total_sales_sq.c.avg_all_ticket,
            total_sales_sq.c.last_sale_date,
        )
        .all()
    )

    results = []

    for r in rows:
        last_pay_date = r.last_payment_date.date() if r.last_payment_date else None
        days_since_last_payment = (today - last_pay_date).days if last_pay_date else None

        last_sale_any = r.last_sale_date.date() if r.last_sale_date else None
        days_since_last_sale = (today - last_sale_any).days if last_sale_any else None

        credit_balance = float(r.credit_balance or 0)
        total_all_amount = float(r.total_all_amount or 0)
        total_all_sales = int(r.total_all_sales or 0)

        # ── Segmentación automática ──
        auto_tags = []

        # VIP: alto volumen (>500k total o >50 compras)
        if total_all_amount >= 500_000 or total_all_sales >= 50:
            auto_tags.append("VIP")

        # Mayorista: frecuencia alta (>10 compras/mes)
        if last_sale_any and total_all_sales > 0:
            months = max(1, days_since_last_sale / 30) if days_since_last_sale else 1
            freq = total_all_sales / months if months > 0 else 0
            if freq >= 10:
                auto_tags.append("Mayorista")

        # Moroso: deuda vencida > 60 días sin pago
        if credit_balance > 0 and days_since_last_payment is not None and days_since_last_payment > 60:
            auto_tags.append("Moroso")
        elif credit_balance > 0 and days_since_last_payment is None:
            auto_tags.append("Moroso")  # nunca ha pagado

        # Inactivo: sin compras en > 60 días
        if days_since_last_sale is not None and days_since_last_sale > 60:
            auto_tags.append("Inactivo")

        results.append({
            "customer_id": r.customer_id,
            "name": r.name,
            "customer_type": r.customer_type or "Normal",
            "credit_balance": credit_balance,
            "credit_limit": float(r.credit_limit or 0),
            "has_credit_limit": bool(r.has_credit_limit),

            "last_payment_date": last_pay_date,
            "days_since_last_payment": days_since_last_payment,
            "num_payments": int(r.num_payments or 0),

            "num_credit_sales": int(r.num_credit_sales or 0),
            "total_credit_sales": float(r.total_credit_sales or 0),

            # Valor total del cliente (cash + crédito)
            "total_all_sales": total_all_sales,
            "total_all_amount": total_all_amount,
            "avg_all_ticket": float(r.avg_all_ticket or 0),

            "last_sale_date": last_sale_any,
            "days_since_last_sale": days_since_last_sale,

            # Segmentación automática
            "auto_tags": auto_tags,
        })

    return results