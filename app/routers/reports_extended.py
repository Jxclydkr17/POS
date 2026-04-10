from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from typing import Optional
from app.db.database import get_db
from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
 
from app.db.models.product import Product
from app.db.models.customer import Customer
from app.db.models.user import User

from app.utils.dt import TZ_CR

# ── FASE 1 — Fix 1.1: Importar dependencia de autenticación ──
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/reports", tags=["Reportes Ext"])

# ----------------------------------------------------------------------

def parse_date(d: Optional[str], default_time: str) -> Optional[datetime]:
    """Parse date string to timezone-aware CR datetime.

    FASE 5 — Fix 5.4: Retorna datetime con TZ_CR. Se eliminó el buffer +6h.
    """
    if not d:
        return None
    dt = datetime.fromisoformat(d + default_time)
    return dt.replace(tzinfo=TZ_CR)

# ----------------------------------------------------------------------

@router.get("/sales/history")
def sales_history(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    payment: Optional[str] = Query(None, description="efectivo|tarjeta|sinpe|crédito"),
    status: Optional[str] = Query(None, description="aprobada|pendiente|anulada"),
    q: Optional[str] = Query(None, description="número de venta o nombre cliente"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    qset = db.query(Sale)

    # 🔹 Filtro de fechas (timezone-aware CR, sin buffer +6h)
    if start_date or end_date:
        sd = parse_date(start_date, " 00:00:00") if start_date else datetime(2000, 1, 1, tzinfo=TZ_CR)
        ed = parse_date(end_date, " 23:59:59") if end_date else datetime(2100, 1, 1, tzinfo=TZ_CR)
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
    # FASE 1 — Fix 1.4: joinedload para eliminar N+1 (antes: 1 query por venta)
    sales = qset.options(joinedload(Sale.customer)).all()

    result = []
    for s in sales:
        cust_name = s.customer.name if s.customer else "Cliente general"
        result.append({
            "id": s.id,
            "created_at": s.created_at.strftime("%Y-%m-%d %H:%M"),
            "customer_name": cust_name,
            "total": float(s.total),
            "payment_method": s.payment_method,
            "status": getattr(s, "status", "aprobada"),
        })

    return {"sales": result}

# ----------------------------------------------------------------------

@router.get("/sales/{sale_id}")
def get_sale_detail(
    sale_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Devuelve el detalle completo de una venta con sus productos"""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()

    if not sale:
        raise HTTPException(status_code=404, detail="Venta no encontrada")

    # 🔹 Cliente
    cust = db.query(Customer).filter(Customer.id == sale.customer_id).first() if sale.customer_id else None
    customer_name = cust.name if cust else "Cliente general"

    # 🔹 Ítems
    items = db.query(SaleDetail).filter(SaleDetail.sale_id == sale_id).all() 

    # FASE 1 — Fix 1.4: Prefetch productos en UNA query
    product_ids = [i.product_id for i in items if i.product_id and not getattr(i, "is_common", False)]
    products_map = {}
    if product_ids:
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        products_map = {p.id: p for p in products}

    item_data = []
    for i in items:
        # ✅ PRODUCTO COMÚN: usar common_description en vez de buscar Product
        if getattr(i, "is_common", False) or i.product_id is None:
            product_name = f"📦 {i.common_description or 'Producto común'}"
        else:
            product = products_map.get(i.product_id)
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