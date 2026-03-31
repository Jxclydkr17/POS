from datetime import date

def evaluate_purchase_status(purchase):
    """
    Determina el estado real de una compra/factura.
    """
    if purchase.status == "pagado":
        return "pagado"

    today = date.today()
    due = purchase.due_date

    if not due:
        return "pendiente"

    if today > due:
        return "vencido"

    return "pendiente"
