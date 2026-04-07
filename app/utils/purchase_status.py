from app.utils.dt import today_cr


def evaluate_purchase_status(purchase):
    """
    Determina el estado real de una compra/factura.
    """
    if purchase.status == "pagado":
        return "pagado"

    # ── FASE 3 — Fix 3.2: today_cr() en vez de date.today() ──
    today = today_cr()
    due = purchase.due_date

    if not due:
        return "pendiente"

    if today > due:
        return "vencido"

    return "pendiente"