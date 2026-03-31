# app/routers/analytics.py
# ── Fase 4: Analytics de compras + Comparador de proveedores ──

from datetime import date, datetime, timedelta, timezone
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.db.database import get_db
from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
from app.db.models.product import Product
from app.db.models.purchase import Purchase, PurchaseStatus
from app.db.models.purchase_detail import PurchaseDetail
from app.db.models.purchase_payment import PurchasePayment
from app.db.models.supplier import Supplier
from app.db.models.category import Category
from app.utils.dt import utcnow, today_cr


router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def api_response(data: Any = None, success: bool = True, message: str = "") -> Dict[str, Any]:
    return {
        "success": success,
        "message": message,
        "data": data,
    }


def parse_date(value: Optional[str], default: Optional[date] = None) -> Optional[date]:
    if not value:
        return default
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return default


# ---------------------------------------------------------------------
# KPI PRINCIPALES
# ---------------------------------------------------------------------

@router.get("/kpis")
def kpis(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    start = parse_date(start_date)
    end = parse_date(end_date)

    # ✅ Usar agregaciones SQL en vez de cargar todo en memoria
    query = db.query(
        func.count(Sale.id).label("total_sales"),
        func.sum(Sale.total).label("total_amount"),
        func.avg(Sale.total).label("avg_ticket")
    )

    if start:
        query = query.filter(Sale.created_at >= start)
    if end:
        query = query.filter(Sale.created_at < end + timedelta(days=1))

    result = query.first()

    # Desglose por método de pago (también optimizado)
    payment_query = db.query(
        Sale.payment_method,
        func.sum(Sale.total).label("total")
    ).group_by(Sale.payment_method)

    if start:
        payment_query = payment_query.filter(Sale.created_at >= start)
    if end:
        payment_query = payment_query.filter(Sale.created_at < end + timedelta(days=1))

    payment_breakdown = {
        row.payment_method: float(row.total)
        for row in payment_query.all()
    }

    return api_response({
        "total_sales": result.total_sales or 0,
        "total_amount": float(result.total_amount or 0),
        "avg_ticket": float(result.avg_ticket or 0),
        "payment_breakdown": payment_breakdown
    })


# ---------------------------------------------------------------------
# VENTAS DIARIAS (PARA GRÁFICO DE LÍNEA)
# ---------------------------------------------------------------------
@router.get("/daily-sales")
def daily_sales(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    start = parse_date(start_date)
    end = parse_date(end_date)

    sale_date = func.date(Sale.created_at).label("sale_date")
    q = db.query(
        sale_date,
        func.sum(Sale.total).label("total"),
    ).group_by(sale_date).order_by(sale_date)

    if start:
        q = q.filter(Sale.created_at >= start)
    if end:
        q = q.filter(Sale.created_at < end + timedelta(days=1))

    data = [
        {"date": str(row.sale_date), "total": float(row.total)}
        for row in q.all()
    ]
    return api_response(data)


# ---------------------------------------------------------------------
# MÉTODOS DE PAGO (PIE CHART)
# ---------------------------------------------------------------------
@router.get("/payment-methods")
def payment_methods(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    start = parse_date(start_date)
    end = parse_date(end_date)

    q = db.query(
        func.coalesce(Sale.payment_method, "otro").label("method"),
        func.sum(Sale.total).label("total"),
    ).group_by(func.coalesce(Sale.payment_method, "otro"))

    if start:
        q = q.filter(Sale.created_at >= start)
    if end:
        q = q.filter(Sale.created_at < end + timedelta(days=1))

    data = [
        {"method": row.method, "total": float(row.total)}
        for row in q.all()
    ]
    return api_response(data)


# ---------------------------------------------------------------------
# COMPARACIÓN CON PERIODO ANTERIOR (KPI COMPARATIVOS)
# ---------------------------------------------------------------------
@router.get("/compare")
def compare_periods(
    current_start: Optional[str] = Query(None),
    current_end: Optional[str] = Query(None),
    previous_start: Optional[str] = Query(None),
    previous_end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    cur_start = parse_date(current_start)
    cur_end = parse_date(current_end)
    prev_start = parse_date(previous_start)
    prev_end = parse_date(previous_end)

    def agg_stats(s: Optional[date], e: Optional[date]) -> Dict[str, float]:
        q = db.query(
            func.count(Sale.id).label("count"),
            func.coalesce(func.sum(Sale.total), 0).label("total_amount"),
            func.coalesce(func.avg(Sale.total), 0).label("avg_ticket"),
        )
        if s:
            q = q.filter(Sale.created_at >= s)
        if e:
            q = q.filter(Sale.created_at < e + timedelta(days=1))
        r = q.first()
        return {
            "count": int(r.count or 0),
            "total_amount": float(r.total_amount or 0),
            "avg_ticket": float(r.avg_ticket or 0),
        }

    data = {
        "current": agg_stats(cur_start, cur_end),
        "previous": agg_stats(prev_start, prev_end),
    }
    return api_response(data)


# ---------------------------------------------------------------------
# VENTAS POR CATEGORÍA
# (ADAPTADO A SaleDetail SIN RELACIÓN product)
# ---------------------------------------------------------------------
@router.get("/by-category")
def sales_by_category(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    start = parse_date(start_date)
    end = parse_date(end_date)

    # Agregación SQL: SaleDetail → Product → Category
    q = (
        db.query(
            Category.name.label("category_name"),
            func.sum(SaleDetail.subtotal).label("total"),
        )
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .join(Product, Product.id == SaleDetail.product_id)
        .join(Category, Category.id == Product.category_id)
    )

    if start:
        q = q.filter(Sale.created_at >= start)
    if end:
        q = q.filter(Sale.created_at < end + timedelta(days=1))

    rows = q.group_by(Category.name).order_by(func.sum(SaleDetail.subtotal).desc()).all()

    data = [
        {"category": row.category_name, "total": float(row.total)}
        for row in rows
    ]

    # Productos sin categoría asignada
    q_no_cat = (
        db.query(func.sum(SaleDetail.subtotal).label("total"))
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .join(Product, Product.id == SaleDetail.product_id)
        .filter(Product.category_id.is_(None))
    )
    if start:
        q_no_cat = q_no_cat.filter(Sale.created_at >= start)
    if end:
        q_no_cat = q_no_cat.filter(Sale.created_at < end + timedelta(days=1))

    no_cat_total = q_no_cat.scalar()
    if no_cat_total:
        data.append({"category": "(Sin categoría)", "total": float(no_cat_total)})

    # ✅ PRODUCTO COMÚN: sumar ventas de productos comunes (sin inventario)
    q_common = (
        db.query(func.sum(SaleDetail.subtotal).label("total"))
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .filter(SaleDetail.is_common == True)
    )
    if start:
        q_common = q_common.filter(Sale.created_at >= start)
    if end:
        q_common = q_common.filter(Sale.created_at < end + timedelta(days=1))

    common_total = q_common.scalar()
    if common_total:
        data.append({"category": "📦 Productos comunes", "total": float(common_total)})

    return api_response(data)


# ---------------------------------------------------------------------
# TOP PRODUCTOS
# ---------------------------------------------------------------------
@router.get("/top-products")
def top_products(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    start = parse_date(start_date)
    end = parse_date(end_date)

    q = (
        db.query(
            SaleDetail.product_id,
            # ✅ PRODUCTO COMÚN: mostrar common_description en vez de "(Producto eliminado)"
            case(
                (SaleDetail.is_common == True, func.coalesce(SaleDetail.common_description, "Producto común")),
                else_=func.coalesce(Product.name, "(Producto eliminado)")
            ).label("name"),
            func.sum(SaleDetail.quantity).label("quantity"),
            func.sum(SaleDetail.subtotal).label("total"),
        )
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .outerjoin(Product, Product.id == SaleDetail.product_id)
        .group_by(SaleDetail.product_id, SaleDetail.is_common, SaleDetail.common_description, Product.name)
    )

    if start:
        q = q.filter(Sale.created_at >= start)
    if end:
        q = q.filter(Sale.created_at < end + timedelta(days=1))

    rows = q.order_by(func.sum(SaleDetail.subtotal).desc()).limit(limit).all()

    data = [
        {
            "product_id": r.product_id,
            "name": r.name,
            "quantity": float(r.quantity or 0),
            "total": float(r.total or 0),
        }
        for r in rows
    ]
    return api_response(data)


# ---------------------------------------------------------------------
# PRODUCTOS SIN ROTACIÓN (INVENTARIO MUERTO)
# ---------------------------------------------------------------------
@router.get("/no-rotation")
def products_no_rotation(
    days: int = Query(30, ge=1, le=365, description="Días sin ventas para considerar sin rotación"),
    db: Session = Depends(get_db),
):
    """
    Retorna productos activos con stock > 0 que no han tenido ventas
    en los últimos N días (30, 60 o 90 por defecto).
    También incluye productos que nunca han sido vendidos.
    """

    cutoff = utcnow() - timedelta(days=days)

    # Subconsulta: última venta por producto
    last_sale_sub = (
        db.query(
            SaleDetail.product_id.label("product_id"),
            func.max(Sale.created_at).label("last_sale_at"),
        )
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .group_by(SaleDetail.product_id)
        .subquery()
    )

    # Query principal: productos activos con stock > 0
    results = (
        db.query(
            Product.id,
            Product.code,
            Product.name,
            Product.stock,
            Product.cost,
            Product.price,
            Category.name.label("category_name"),
            last_sale_sub.c.last_sale_at,
        )
        .outerjoin(last_sale_sub, last_sale_sub.c.product_id == Product.id)
        .outerjoin(Category, Category.id == Product.category_id)
        .filter(Product.is_active == True)
        .filter(Product.stock > 0)
        .filter(
            # Nunca vendido O última venta antes del corte
            (last_sale_sub.c.last_sale_at == None)
            | (last_sale_sub.c.last_sale_at < cutoff)
        )
        .order_by(
            # MySQL no soporta NULLS FIRST — simularlo con CASE
            case(
                (last_sale_sub.c.last_sale_at == None, 0),
                else_=1
            ).asc(),
            last_sale_sub.c.last_sale_at.asc()
        )
        .all()
    )

    now = utcnow()
    data = []
    total_stock_value = 0.0

    for row in results:
        cost = float(row.cost or 0)
        stock = float(row.stock or 0)
        stock_value = cost * stock
        total_stock_value += stock_value

        if row.last_sale_at:
            last_sale = row.last_sale_at if row.last_sale_at.tzinfo else row.last_sale_at.replace(tzinfo=timezone.utc)
            days_without_sale = (now - last_sale).days
            last_sale_str = row.last_sale_at.strftime("%Y-%m-%d")
        else:
            days_without_sale = None   # nunca vendido
            last_sale_str = None

        data.append({
            "product_id": row.id,
            "code": row.code,
            "name": row.name,
            "category": row.category_name or "Sin categoría",
            "stock": stock,
            "cost": cost,
            "price": float(row.price or 0),
            "last_sale_date": last_sale_str,
            "days_without_sale": days_without_sale,
            "stock_value": round(stock_value, 2),
        })

    return api_response({
        "filter_days": days,
        "total_products": len(data),
        "total_stock_value": round(total_stock_value, 2),
        "products": data,
    })


# =====================================================================
#  FASE 4 — ANALYTICS DE COMPRAS
# =====================================================================

# ---------------------------------------------------------------------
# GASTO POR PROVEEDOR (TOP 10)
# ---------------------------------------------------------------------
@router.get("/purchases/spending-by-supplier")
def purchases_spending_by_supplier(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """
    Top N proveedores por gasto total en compras.
    Incluye cantidad de facturas y monto promedio por factura.
    """
    start = parse_date(start_date)
    end = parse_date(end_date)

    q = (
        db.query(
            Supplier.id.label("supplier_id"),
            Supplier.name.label("supplier_name"),
            func.count(Purchase.id).label("invoice_count"),
            func.coalesce(func.sum(Purchase.amount), 0).label("total_spent"),
            func.coalesce(func.avg(Purchase.amount), 0).label("avg_invoice"),
        )
        .join(Purchase, Purchase.supplier_id == Supplier.id)
        .group_by(Supplier.id, Supplier.name)
    )

    if start:
        q = q.filter(Purchase.entry_date >= start)
    if end:
        q = q.filter(Purchase.entry_date <= end)

    rows = q.order_by(func.sum(Purchase.amount).desc()).limit(limit).all()

    data = []
    for r in rows:
        data.append({
            "supplier_id": r.supplier_id,
            "supplier_name": r.supplier_name,
            "invoice_count": int(r.invoice_count),
            "total_spent": round(float(r.total_spent), 2),
            "avg_invoice": round(float(r.avg_invoice), 2),
        })

    grand_total = sum(d["total_spent"] for d in data)

    return api_response({
        "items": data,
        "grand_total": round(grand_total, 2),
    })


# ---------------------------------------------------------------------
# EVOLUCIÓN MENSUAL DE COMPRAS (12 MESES)
# ---------------------------------------------------------------------
@router.get("/purchases/monthly-evolution")
def purchases_monthly_evolution(
    months: int = Query(12, ge=1, le=36),
    db: Session = Depends(get_db),
):
    """
    Monto total de compras agrupado por mes, últimos N meses.
    Ideal para gráfico de barras/línea de tendencia.
    Una sola query con GROUP BY en vez de N queries separadas.
    """
    today = today_cr()
    first_of_current = today.replace(day=1)

    # Calcular el primer día del mes más antiguo que queremos
    # Retroceder (months - 1) meses desde el mes actual
    y = first_of_current.year
    m = first_of_current.month - (months - 1)
    while m <= 0:
        m += 12
        y -= 1
    cutoff = date(y, m, 1)

    year_col = func.year(Purchase.entry_date).label("yr")
    month_col = func.month(Purchase.entry_date).label("mn")

    rows = (
        db.query(
            year_col,
            month_col,
            func.coalesce(func.sum(Purchase.amount), 0).label("total"),
            func.count(Purchase.id).label("count"),
        )
        .filter(Purchase.entry_date >= cutoff)
        .group_by(year_col, month_col)
        .order_by(year_col, month_col)
        .all()
    )

    # Indexar resultados para rellenar meses sin compras con 0
    result_map = {(r.yr, r.mn): (float(r.total), int(r.count)) for r in rows}

    data = []
    cur_y, cur_m = y, m
    for _ in range(months):
        total, count = result_map.get((cur_y, cur_m), (0.0, 0))
        data.append({
            "month": f"{cur_y:04d}-{cur_m:02d}",
            "total": round(total, 2),
            "count": count,
        })
        cur_m += 1
        if cur_m > 12:
            cur_m = 1
            cur_y += 1

    return api_response(data)


# ---------------------------------------------------------------------
# PROMEDIO DE DÍAS DE PAGO (GLOBAL + POR PROVEEDOR)
# ---------------------------------------------------------------------
@router.get("/purchases/avg-payment-days")
def purchases_avg_payment_days(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Promedio de días entre entry_date y paid_at para compras pagadas.
    Retorna el promedio global y desglose por proveedor.
    """
    start = parse_date(start_date)
    end = parse_date(end_date)

    base_filter = [
        Purchase.status == PurchaseStatus.pagado,
        Purchase.paid_at.isnot(None),
    ]
    if start:
        base_filter.append(Purchase.entry_date >= start)
    if end:
        base_filter.append(Purchase.entry_date <= end)

    # Promedio global
    global_avg = (
        db.query(
            func.avg(func.datediff(Purchase.paid_at, Purchase.entry_date)).label("avg_days"),
            func.count(Purchase.id).label("count"),
        )
        .filter(*base_filter)
        .first()
    )

    # Por proveedor
    by_supplier = (
        db.query(
            Supplier.id.label("supplier_id"),
            Supplier.name.label("supplier_name"),
            func.avg(func.datediff(Purchase.paid_at, Purchase.entry_date)).label("avg_days"),
            func.count(Purchase.id).label("count"),
        )
        .join(Purchase, Purchase.supplier_id == Supplier.id)
        .filter(*base_filter)
        .group_by(Supplier.id, Supplier.name)
        .order_by(func.avg(func.datediff(Purchase.paid_at, Purchase.entry_date)).asc())
        .all()
    )

    suppliers_data = []
    for r in by_supplier:
        avg_d = float(r.avg_days) if r.avg_days is not None else None
        suppliers_data.append({
            "supplier_id": r.supplier_id,
            "supplier_name": r.supplier_name,
            "avg_days": round(avg_d, 1) if avg_d is not None else None,
            "paid_count": int(r.count),
        })

    return api_response({
        "global_avg_days": round(float(global_avg.avg_days), 1) if global_avg.avg_days else None,
        "paid_count": int(global_avg.count or 0),
        "by_supplier": suppliers_data,
    })


# ---------------------------------------------------------------------
# PRODUCTOS MÁS COMPRADOS (VÍA PurchaseDetail)
# ---------------------------------------------------------------------
@router.get("/purchases/top-products")
def purchases_top_products(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Top N productos más comprados, usando PurchaseDetail.
    Incluye cantidad total comprada, gasto total, costo unitario promedio
    y nombre del proveedor principal.
    """
    start = parse_date(start_date)
    end = parse_date(end_date)

    q = (
        db.query(
            PurchaseDetail.product_id,
            Product.name.label("product_name"),
            Product.code.label("product_code"),
            func.sum(PurchaseDetail.quantity).label("total_qty"),
            func.sum(PurchaseDetail.subtotal).label("total_spent"),
            func.avg(PurchaseDetail.unit_cost).label("avg_unit_cost"),
            func.count(func.distinct(Purchase.id)).label("purchase_count"),
        )
        .join(Purchase, Purchase.id == PurchaseDetail.purchase_id)
        .join(Product, Product.id == PurchaseDetail.product_id)
        .group_by(PurchaseDetail.product_id, Product.name, Product.code)
    )

    if start:
        q = q.filter(Purchase.entry_date >= start)
    if end:
        q = q.filter(Purchase.entry_date <= end)

    rows = q.order_by(func.sum(PurchaseDetail.subtotal).desc()).limit(limit).all()

    # Resolver proveedor más frecuente para cada producto en UNA sola query
    product_ids = [r.product_id for r in rows]
    top_suppliers: Dict[int, str] = {}
    if product_ids:
        # Subquery: conteo de compras por (producto, proveedor)
        supplier_counts = (
            db.query(
                PurchaseDetail.product_id,
                Supplier.name.label("supplier_name"),
                func.count(PurchaseDetail.id).label("cnt"),
                func.row_number().over(
                    partition_by=PurchaseDetail.product_id,
                    order_by=func.count(PurchaseDetail.id).desc(),
                ).label("rn"),
            )
            .join(Purchase, Purchase.id == PurchaseDetail.purchase_id)
            .join(Supplier, Supplier.id == Purchase.supplier_id)
            .filter(PurchaseDetail.product_id.in_(product_ids))
            .group_by(PurchaseDetail.product_id, Supplier.id, Supplier.name)
            .subquery()
        )

        top_rows = (
            db.query(
                supplier_counts.c.product_id,
                supplier_counts.c.supplier_name,
            )
            .filter(supplier_counts.c.rn == 1)
            .all()
        )
        top_suppliers = {r.product_id: r.supplier_name for r in top_rows}

    data = []
    for r in rows:
        data.append({
            "product_id": r.product_id,
            "product_name": r.product_name,
            "product_code": r.product_code,
            "total_qty": int(r.total_qty or 0),
            "total_spent": round(float(r.total_spent or 0), 2),
            "avg_unit_cost": round(float(r.avg_unit_cost or 0), 2),
            "purchase_count": int(r.purchase_count or 0),
            "top_supplier": top_suppliers.get(r.product_id),
        })

    return api_response(data)


# =====================================================================
#  FASE 4 — COMPARADOR DE PROVEEDORES
# =====================================================================

# ---------------------------------------------------------------------
# COMPARAR PROVEEDORES PARA UN PRODUCTO
# ---------------------------------------------------------------------
@router.get("/purchases/supplier-comparison")
def supplier_comparison(
    product_id: int = Query(..., gt=0, description="ID del producto a comparar"),
    db: Session = Depends(get_db),
):
    """
    Para un producto dado, compara todos los proveedores que lo han vendido:
    - Precio unitario promedio, mínimo, máximo y último
    - Cantidad total comprada
    - Promedio de días de entrega (entry_date → received_at)
    - Última compra
    Requiere PurchaseDetail con unit_cost por producto por proveedor.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return api_response(None, success=False, message="Producto no encontrado")

    # Agregar por proveedor
    rows = (
        db.query(
            Supplier.id.label("supplier_id"),
            Supplier.name.label("supplier_name"),
            func.avg(PurchaseDetail.unit_cost).label("avg_cost"),
            func.min(PurchaseDetail.unit_cost).label("min_cost"),
            func.max(PurchaseDetail.unit_cost).label("max_cost"),
            func.sum(PurchaseDetail.quantity).label("total_qty"),
            func.sum(PurchaseDetail.subtotal).label("total_spent"),
            func.count(func.distinct(Purchase.id)).label("purchase_count"),
            func.max(Purchase.entry_date).label("last_purchase_date"),
        )
        .join(Purchase, Purchase.id == PurchaseDetail.purchase_id)
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .filter(PurchaseDetail.product_id == product_id)
        .group_by(Supplier.id, Supplier.name)
        .order_by(func.avg(PurchaseDetail.unit_cost).asc())
        .all()
    )

    if not rows:
        return api_response({
            "product_id": product_id,
            "product_name": product.name,
            "suppliers": [],
            "message": "No se encontraron compras registradas para este producto.",
        })

    suppliers_data = []

    # Resolver avg_delivery_days para todos los proveedores en UNA query
    delivery_rows = (
        db.query(
            Purchase.supplier_id,
            func.avg(func.datediff(Purchase.received_at, Purchase.entry_date)).label("avg_days"),
        )
        .join(PurchaseDetail, PurchaseDetail.purchase_id == Purchase.id)
        .filter(
            PurchaseDetail.product_id == product_id,
            Purchase.supplier_id.in_([r.supplier_id for r in rows]),
            Purchase.received_at.isnot(None),
        )
        .group_by(Purchase.supplier_id)
        .all()
    )
    delivery_map = {r.supplier_id: float(r.avg_days) if r.avg_days is not None else None for r in delivery_rows}

    # Resolver último costo unitario para todos los proveedores en UNA query
    last_cost_sub = (
        db.query(
            Purchase.supplier_id,
            PurchaseDetail.unit_cost,
            func.row_number().over(
                partition_by=Purchase.supplier_id,
                order_by=Purchase.entry_date.desc(),
            ).label("rn"),
        )
        .join(PurchaseDetail, PurchaseDetail.purchase_id == Purchase.id)
        .filter(
            PurchaseDetail.product_id == product_id,
            Purchase.supplier_id.in_([r.supplier_id for r in rows]),
        )
        .subquery()
    )
    last_cost_rows = (
        db.query(last_cost_sub.c.supplier_id, last_cost_sub.c.unit_cost)
        .filter(last_cost_sub.c.rn == 1)
        .all()
    )
    last_cost_map = {r.supplier_id: float(r.unit_cost) for r in last_cost_rows}

    for r in rows:
        avg_delivery = delivery_map.get(r.supplier_id)
        last_cost = last_cost_map.get(r.supplier_id)

        suppliers_data.append({
            "supplier_id": r.supplier_id,
            "supplier_name": r.supplier_name,
            "avg_cost": round(float(r.avg_cost or 0), 2),
            "min_cost": round(float(r.min_cost or 0), 2),
            "max_cost": round(float(r.max_cost or 0), 2),
            "last_cost": round(last_cost, 2) if last_cost is not None else None,
            "total_qty": int(r.total_qty or 0),
            "total_spent": round(float(r.total_spent or 0), 2),
            "purchase_count": int(r.purchase_count or 0),
            "last_purchase_date": r.last_purchase_date.isoformat() if r.last_purchase_date else None,
            "avg_delivery_days": round(avg_delivery, 1) if avg_delivery is not None else None,
        })

    # Calcular un "score" simple: menor costo promedio + menor tiempo entrega = mejor
    # Normalizar entre 0 y 100 (100 = mejor)
    if len(suppliers_data) > 1:
        costs = [s["avg_cost"] for s in suppliers_data if s["avg_cost"] > 0]
        deliveries = [s["avg_delivery_days"] for s in suppliers_data if s["avg_delivery_days"] is not None]

        min_cost = min(costs) if costs else 1
        max_cost = max(costs) if costs else 1
        min_del = min(deliveries) if deliveries else 0
        max_del = max(deliveries) if deliveries else 1

        for s in suppliers_data:
            cost_score = 0.0
            if max_cost > min_cost and s["avg_cost"] > 0:
                cost_score = 1.0 - (s["avg_cost"] - min_cost) / (max_cost - min_cost)
            elif s["avg_cost"] > 0:
                cost_score = 1.0

            delivery_score = 0.5  # default si no hay datos
            if s["avg_delivery_days"] is not None and max_del > min_del:
                delivery_score = 1.0 - (s["avg_delivery_days"] - min_del) / (max_del - min_del)
            elif s["avg_delivery_days"] is not None:
                delivery_score = 1.0

            # Peso: 60% precio, 40% entrega
            s["score"] = round((cost_score * 0.6 + delivery_score * 0.4) * 100, 1)

        suppliers_data.sort(key=lambda x: x.get("score", 0), reverse=True)
    else:
        for s in suppliers_data:
            s["score"] = 100.0

    return api_response({
        "product_id": product_id,
        "product_name": product.name,
        "product_code": product.code,
        "current_cost": float(product.cost) if product.cost else None,
        "suppliers": suppliers_data,
    })


# ---------------------------------------------------------------------
# LISTADO DE PRODUCTOS CON MÚLTIPLES PROVEEDORES
# (para saber cuáles se pueden comparar)
# ---------------------------------------------------------------------
@router.get("/purchases/multi-supplier-products")
def multi_supplier_products(
    min_suppliers: int = Query(2, ge=2, le=10),
    db: Session = Depends(get_db),
):
    """
    Lista productos que han sido comprados a 2+ proveedores distintos.
    Útil para alimentar el comparador de proveedores.
    """
    rows = (
        db.query(
            PurchaseDetail.product_id,
            Product.name.label("product_name"),
            Product.code.label("product_code"),
            func.count(func.distinct(Purchase.supplier_id)).label("supplier_count"),
        )
        .join(Purchase, Purchase.id == PurchaseDetail.purchase_id)
        .join(Product, Product.id == PurchaseDetail.product_id)
        .group_by(PurchaseDetail.product_id, Product.name, Product.code)
        .having(func.count(func.distinct(Purchase.supplier_id)) >= min_suppliers)
        .order_by(func.count(func.distinct(Purchase.supplier_id)).desc())
        .all()
    )

    data = [
        {
            "product_id": r.product_id,
            "product_name": r.product_name,
            "product_code": r.product_code,
            "supplier_count": int(r.supplier_count),
        }
        for r in rows
    ]

    return api_response(data)