from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func as sa_func, or_
from datetime import datetime
from typing import Optional
from app.db.database import get_db
from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
from app.db.models.electronic_invoice import ElectronicInvoice

from app.db.models.product import Product
from app.db.models.customer import Customer
from app.db.models.user import User

from app.utils.dt import TZ_CR, format_cr  # FASE 2.2 — Fix 2.2: display CR
from app.utils.db_compat import escape_like

# ── FASE 1 — Fix 1.1: Importar dependencia de autenticación ──
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/reports", tags=["Reportes Ext"])


# ----------------------------------------------------------------------
# Helper: dado una lista de sale_ids, retorna un dict
#   {sale_id: {"einvoice_id", "hacienda_status", "invoice_status", "clave"}}
# usando el ElectronicInvoice más reciente por venta. Una sola query.
# ----------------------------------------------------------------------
def _latest_einvoices_for_sales(db: Session, sale_ids: list) -> dict:
    if not sale_ids:
        return {}

    subq = (
        db.query(
            ElectronicInvoice.sale_id,
            sa_func.max(ElectronicInvoice.id).label("max_id"),
        )
        # Solo nos interesa el comprobante "fuente" (FE/Tiquete), no NC/ND
        .filter(
            ElectronicInvoice.sale_id.in_(sale_ids),
            ElectronicInvoice.document_type.in_(["01", "04"]),
        )
        .group_by(ElectronicInvoice.sale_id)
        .subquery()
    )

    einvs = (
        db.query(ElectronicInvoice)
        .join(subq, ElectronicInvoice.id == subq.c.max_id)
        .all()
    )

    return {
        e.sale_id: {
            "einvoice_id": e.id,
            "hacienda_status": e.hacienda_status,
            "invoice_status": e.status,
            "clave": e.clave,
            "document_type": e.document_type,
        }
        for e in einvs
    }


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
    status: Optional[str] = Query(
        None,
        description=(
            "Filtro combinado:\n"
            "  - 'anulada' → ventas con Sale.status=ANULADA\n"
            "  - 'aceptado' → ventas con hacienda_status=ACEPTADO\n"
            "  - 'rechazado' → ventas con hacienda_status=RECHAZADO\n"
            "  - 'pendiente' → ventas activas sin respuesta final de Hacienda\n"
            "  - cualquier otro valor: se aplica como Sale.status ILIKE (compat)"
        ),
    ),
    q: Optional[str] = Query(None, description="número de venta o nombre cliente"),
    limit: int = Query(500, ge=1, le=2000, description="Máximo de resultados"),
    skip: int = Query(0, ge=0, description="Registros a saltar (paginación)"),
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
        p = escape_like(payment.lower())
        if "sinpe" in p:
            qset = qset.filter(Sale.payment_method.ilike(f"%{p}%"))
        else:
            qset = qset.filter(Sale.payment_method.ilike(p))

    # 🔹 Estado combinado (Sale.status + hacienda_status)
    if status:
        st = status.strip().lower()

        if st in ("anulada", "anulado"):
            qset = qset.filter(Sale.status.ilike("ANULADA"))

        elif st in ("aceptado", "aceptada", "accepted"):
            # Subquery: sale_ids cuyo último EI (FE/Tiq) tiene hacienda_status=ACEPTADO
            sub_accepted = (
                db.query(ElectronicInvoice.sale_id)
                .filter(
                    ElectronicInvoice.document_type.in_(["01", "04"]),
                    ElectronicInvoice.hacienda_status.ilike("aceptado"),
                )
                .subquery()
            )
            qset = qset.filter(Sale.id.in_(sub_accepted))

        elif st in ("rechazado", "rechazada", "rejected"):
            sub_rejected = (
                db.query(ElectronicInvoice.sale_id)
                .filter(
                    ElectronicInvoice.document_type.in_(["01", "04"]),
                    ElectronicInvoice.hacienda_status.ilike("rechazado"),
                )
                .subquery()
            )
            qset = qset.filter(Sale.id.in_(sub_rejected))

        elif st in ("pendiente", "pending", "procesando"):
            # Ventas ACTIVAS cuyo EI no esté ACEPTADO ni RECHAZADO (incluye sin EI).
            sub_resolved = (
                db.query(ElectronicInvoice.sale_id)
                .filter(
                    ElectronicInvoice.document_type.in_(["01", "04"]),
                    or_(
                        ElectronicInvoice.hacienda_status.ilike("aceptado"),
                        ElectronicInvoice.hacienda_status.ilike("rechazado"),
                    ),
                )
                .subquery()
            )
            qset = qset.filter(
                Sale.status.ilike("ACTIVA"),
                ~Sale.id.in_(sub_resolved),
            )

        else:
            # Compat con la API anterior: tratar 'status' como Sale.status ilike
            qset = qset.filter(Sale.status.ilike(escape_like(status)))

    # 🔹 Buscar por ID o nombre de cliente
    if q:
        try:
            qset = qset.filter(Sale.customer_id == int(q))
        except ValueError:
            safe_q = escape_like(q)
            qset = qset.join(Customer, isouter=True).filter(Customer.name.ilike(f"%{safe_q}%"))

    # ── FASE 2 — Fix 2.4: Paginación con limit/skip ──
    qset = qset.order_by(Sale.created_at.desc())
    # FASE 1 — Fix 1.4: joinedload para eliminar N+1 (antes: 1 query por venta)
    sales = qset.options(joinedload(Sale.customer)).offset(skip).limit(limit).all()

    # 🔹 Batch: traer último ElectronicInvoice de TODAS las ventas en una sola query
    sale_ids = [s.id for s in sales]
    einv_map = _latest_einvoices_for_sales(db, sale_ids)

    result = []
    for s in sales:
        cust_name = s.customer.name if s.customer else "Cliente general"
        einv = einv_map.get(s.id, {})

        result.append({
            "id": s.id,
            "created_at": format_cr(s.created_at, "%Y-%m-%d %H:%M"),  # FASE 2.2
            "customer_name": cust_name,
            "total": float(s.total),
            "payment_method": s.payment_method,
            "status": s.status,                           # estado interno de la venta
            "hacienda_status": einv.get("hacienda_status"),  # respuesta de Hacienda (o None)
            "einvoice_id": einv.get("einvoice_id"),       # para el botón "Consultar Hacienda"
            "invoice_status": einv.get("invoice_status"), # estado interno del EI
            "document_type": einv.get("document_type"),   # "01" FE, "04" Tiquete
        })

    return {"sales": result}


# ----------------------------------------------------------------------

@router.get("/sales/{sale_id}")
def get_sale_detail(
    sale_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Devuelve el detalle completo de una venta con sus productos."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()

    if not sale:
        raise HTTPException(status_code=404, detail="Venta no encontrada")

    # 🔹 Cliente — ahora incluye id_number / id_type para mostrar la cédula
    cust = db.query(Customer).filter(Customer.id == sale.customer_id).first() if sale.customer_id else None
    customer_name = cust.name if cust else "Cliente general"
    customer_id_number = cust.id_number if cust else None
    customer_id_type = cust.id_type if cust else None
    customer_email = cust.email if cust else None

    # 🔹 Ítems
    items = db.query(SaleDetail).filter(SaleDetail.sale_id == sale_id).all()

    # FASE 1 — Fix 1.4: Prefetch productos en UNA query
    product_ids = [i.product_id for i in items if i.product_id and not getattr(i, "is_common", False)]
    products_map = {}
    if product_ids:
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        products_map = {p.id: p for p in products}

    item_data = []
    subtotal_acc = 0.0
    tax_acc = 0.0

    for i in items:
        # ✅ PRODUCTO COMÚN: usar common_description en vez de buscar Product
        if getattr(i, "is_common", False) or i.product_id is None:
            product_name = f"📦 {i.common_description or 'Producto común'}"
        else:
            product = products_map.get(i.product_id)
            product_name = product.name if product else "(Producto eliminado)"

        # Acumular totales para mostrar subtotal/IVA en el panel
        try:
            subtotal_acc += float(i.subtotal or 0)
        except (TypeError, ValueError):
            pass
        try:
            tax_acc += float(i.tax_amount or 0)
        except (TypeError, ValueError):
            pass

        item_data.append({
            "product_name": product_name,
            "quantity": i.quantity,
            "price": i.unit_price,
            "subtotal": i.subtotal,
            "tax_amount": float(i.tax_amount or 0),
            "is_common": bool(getattr(i, "is_common", False)),
        })

    # 🔹 Estado en Hacienda: último ElectronicInvoice (FE/Tiq) asociado
    einv_map = _latest_einvoices_for_sales(db, [sale_id])
    einv = einv_map.get(sale_id, {})

    return {
        "id": sale.id,
        "created_at": format_cr(sale.created_at, "%Y-%m-%d %H:%M"),  # FASE 2.2
        "customer_name": customer_name,
        "customer_id_number": customer_id_number,
        "customer_id_type": customer_id_type,
        "customer_email": customer_email,
        "payment_method": sale.payment_method,
        "status": sale.status,
        "total": float(sale.total),
        "subtotal": round(subtotal_acc, 2),
        "tax": round(tax_acc, 2),
        "items": item_data,

        # ── Información de Hacienda ──
        "hacienda_status": einv.get("hacienda_status"),
        "einvoice_id": einv.get("einvoice_id"),
        "einvoice_status": einv.get("invoice_status"),
        "einvoice_clave": einv.get("clave"),
        "document_type": einv.get("document_type") or sale.document_type,
    }