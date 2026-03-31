from sqlalchemy.orm import Session
from app.db.models.customer import Customer


def get_customers_near_credit_limit(
    db: Session,
    warning_threshold: float = 0.8
):
    """
    Retorna clientes cuyo uso de crédito está cerca o excede su límite.
    """
    customers = (
        db.query(Customer)
        .filter(Customer.has_credit_limit == True)
        .filter(Customer.credit_limit > 0)
        .filter(Customer.credit_balance > 0)
        .all()
    )

    alerts = []

    for c in customers:
        limit_ = float(c.credit_limit or 0)
        balance = float(c.credit_balance or 0)

        if limit_ <= 0:
            continue

        usage = balance / limit_

        if usage >= 1:
            level = "critical"
        elif usage >= warning_threshold:
            level = "warning"
        else:
            continue

        alerts.append({
            "type": "credit_limit",
            "level": level,                     # warning | critical
            "customer_id": c.id,
            "customer_name": c.name,
            "credit_balance": round(balance, 2),
            "credit_limit": round(limit_, 2),
            "usage_ratio": round(usage, 2),
            "usage_percent": round(usage * 100, 1),
            "message": (
                f"{c.name} ha usado el {usage*100:.1f}% "
                f"de su límite de crédito"
            )
        })

    return alerts
