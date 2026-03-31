from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models.customer import Customer
from app.db.models.sale import Sale
from app.db.models.credit import Credit


def get_customers_credit_base_data(db: Session):
    """
    Retorna datos base para análisis de riesgo de clientes.
    SOLO datos, sin scoring ni decisiones.

    - last_credit_sale_date: fecha de la última VENTA a crédito (tabla sales)
    - last_payment_date / days_since_last_payment: fecha del último ABONO real
      (tabla credits, type='payment')
    """

    today = date.today()

    # ── Sub-query: último abono real por cliente ──
    last_payment_sq = (
        db.query(
            Credit.customer_id.label("customer_id"),
            func.max(Credit.created_at).label("last_payment_date"),
        )
        .filter(Credit.type == "payment")
        .group_by(Credit.customer_id)
        .subquery()
    )

    # ── Query principal: datos de ventas a crédito + último abono ──
    rows = (
        db.query(
            Customer.id.label("customer_id"),
            Customer.name.label("name"),
            Customer.credit_balance.label("credit_balance"),

            func.max(Sale.created_at).label("last_credit_sale_date"),
            func.count(Sale.id).label("num_credit_sales"),
            func.sum(Sale.total).label("total_credit_sales"),
            func.avg(Sale.total).label("avg_ticket_credit"),

            last_payment_sq.c.last_payment_date,
        )
        .join(Sale, Sale.customer_id == Customer.id)
        .outerjoin(
            last_payment_sq,
            last_payment_sq.c.customer_id == Customer.id,
        )
        .filter(Sale.payment_method == "credit")
        .group_by(Customer.id, last_payment_sq.c.last_payment_date)
        .all()
    )

    results = []

    for r in rows:
        # Fecha de última venta a crédito
        last_sale_date = (
            r.last_credit_sale_date.date()
            if r.last_credit_sale_date else None
        )

        # Fecha del último abono REAL (de la tabla credits)
        last_pay_date = (
            r.last_payment_date.date()
            if r.last_payment_date else None
        )

        days_since_last_payment = (
            (today - last_pay_date).days
            if last_pay_date else None
        )

        results.append({
            "customer_id": r.customer_id,
            "name": r.name,
            "credit_balance": float(r.credit_balance or 0.0),

            "last_credit_sale_date": last_sale_date,
            "last_payment_date": last_pay_date,
            "days_since_last_payment": days_since_last_payment,

            "num_credit_sales": int(r.num_credit_sales or 0),
            "total_credit_sales": float(r.total_credit_sales or 0.0),
            "avg_ticket_credit": float(r.avg_ticket_credit or 0.0),
        })

    return results
