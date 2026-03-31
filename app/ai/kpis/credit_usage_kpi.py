from sqlalchemy.orm import Session
from app.db.models.customer import Customer


def get_top_credit_usage_clients(
    db: Session,
    limit: int = 5
):
    """
    Retorna los clientes con mayor uso porcentual de su crédito.
    """
    customers = (
        db.query(Customer)
        .filter(Customer.credit_limit > 0)
        .filter(Customer.credit_balance > 0)
        .all()
    )

    items = []

    for c in customers:
        credit_limit = float(c.credit_limit or 0)
        credit_balance = float(c.credit_balance or 0)

        if credit_limit <= 0:
            continue

        usage_ratio = credit_balance / credit_limit

        items.append({
            "customer_id": c.id,
            "customer_name": c.name,
            "credit_balance": round(credit_balance, 2),
            "credit_limit": round(credit_limit, 2),
            "usage_ratio": round(usage_ratio, 3),
            "usage_percent": round(usage_ratio * 100, 1),
        })

    # ordenar por mayor uso
    items.sort(key=lambda x: x["usage_ratio"], reverse=True)

    return items[:limit]
