from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
from app.db.database import get_db
from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
 
from app.db.models.product import Product
from app.db.models.customer import Customer

from app.utils.dt import TZ_CR

router = APIRouter(prefix="/reports", tags=["Reportes Ext"])

# ----------------------------------------------------------------------

def parse_date(d: Optional[str], default_time: str) -> Optional[datetime]:
    """Parse date string, adjusting for Costa Rica timezone.
    
    Since Sale.created_at now stores CR local time, filters use CR dates directly.
    The +6h buffer on end_date catches any legacy records still in UTC.
    """
    if not d:
        return None
    return datetime.fromisoformat(d + default_time)

# ----------------------------------------------------------------------

@router.get("/sales/history")
def sales_history(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    payment: Optional[str] = Query(None, description="efectivo|tarjeta|sinpe|crédito"),
    status: Optional[str] = Query(None, description="aprobada|pendiente|anulada"),
    q: Optional[str] = Query(None, description="número de venta o nombre cliente"),
    db: Session = Depends(get_db)
):
    qset = db.query(Sale)

    # 🔹 Filtro de fechas
    #   created_at ahora se almacena en hora CR.
    #   El margen de +6h en ed atrapa registros viejos que quedaron en UTC.
    if start_date or end_date:
        sd = parse_date(start_date, " 00:00:00") if start_date else datetime(2000, 1, 1)
        ed = parse_date(end_date, " 23:59:59") if end_date else datetime(2100, 1, 1)
        from datetime import timedelta
        ed = ed + timedelta(hours=6)          # buffer para registros legacy en UTC
        qset = qset.filter(Sale.created_at >= sd, Sale.created_at <= ed)

    # 🔹 Método de pago
    if payment:
        p = payment.lower()
        if p == "sinpe":
            qset = qset.filter(Sale.payment_method.ilike("%sinpe%"))
        else:
            qset = qset.filter(Sale.payment_method.ilike(p))

    # 🔹 Estado (si existe campo status en Sale)
    # Nota: El modelo Sale no tiene 'status', asumo que lo agregaste o lo estás simulando.
    # Usando getattr para evitar errores si no existe.
    if status:
        qset = qset.filter(getattr(Sale, "status", None).ilike(status))

    # 🔹 Buscar por ID o nombre de cliente
    if q:
        try:
            qset = qset.filter(Sale.customer_id == int(q))
        except ValueError:
            qset = qset.join(Customer, isouter=True).filter(Customer.name.ilike(f"%{q}%"))


    qset = qset.order_by(Sale.created_at.desc())
    sales = qset.all()

    result = []
    for s in sales:
        cust = db.query(Customer).filter(Customer.id == s.customer_id).first() if s.customer_id else None
        result.append({
            "id": s.id,
            "created_at": s.created_at.strftime("%Y-%m-%d %H:%M"),
            "customer_name": cust.name if cust else "Cliente general",
            "total": float(s.total),
            "payment_method": s.payment_method,
            "status": getattr(s, "status", "aprobada"),
        })

    return {"sales": result}

# ----------------------------------------------------------------------

@router.get("/sales/{sale_id}")
def get_sale_detail(sale_id: int, db: Session = Depends(get_db)):
    """Devuelve el detalle completo de una venta con sus productos"""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()

    if not sale:
        raise HTTPException(status_code=404, detail="Venta no encontrada")

    # 🔹 Cliente
    cust = db.query(Customer).filter(Customer.id == sale.customer_id).first() if sale.customer_id else None
    customer_name = cust.name if cust else "Cliente general"

    # 🔹 Ítems
    items = db.query(SaleDetail).filter(SaleDetail.sale_id == sale_id).all() 

    item_data = []
    for i in items:
        # ✅ PRODUCTO COMÚN: usar common_description en vez de buscar Product
        if getattr(i, "is_common", False) or i.product_id is None:
            product_name = f"📦 {i.common_description or 'Producto común'}"
        else:
            product = db.query(Product).filter(Product.id == i.product_id).first()
            product_name = product.name if product else "(Producto eliminado)"
        
        item_data.append({
            "product_name": product_name,
            "quantity": i.quantity,
            "price": i.unit_price, 
            "subtotal": i.subtotal,
            "is_common": bool(getattr(i, "is_common", False)),
        })

    return {
        "id": sale.id,
        "created_at": sale.created_at.strftime("%Y-%m-%d %H:%M"),
        "customer_name": customer_name,
        "payment_method": sale.payment_method,
        "status": getattr(sale, "status", "aprobada"),
        "total": sale.total,
        "items": item_data,
    }