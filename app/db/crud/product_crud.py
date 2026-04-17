from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.inventory_movement import InventoryMovement, MovementType   # ✅ FASE 7
from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
from app.schemas.products import ProductCreate, ProductUpdate
from decimal import Decimal
from datetime import datetime, timedelta
from app.utils.dt import utcnow


# -----------------------------
# HELPER: Product ORM → dict enriquecido
# -----------------------------
def _product_to_dict(p: Product) -> dict:
    PRECISION_EXPORT = Decimal("0.0001")
    min_stock_val = p.min_stock if p.min_stock is not None else 3

    tax_rate_str = "0.0000"
    if p.tax_rate is not None:
        try:
            rate_decimal = Decimal(str(float(p.tax_rate))).quantize(PRECISION_EXPORT)
            tax_rate_str = f"{rate_decimal:.4f}"
        except Exception:
            tax_rate_str = "0.0000"

    # Sugerencia de reposición: reponer hasta 2× min_stock
    # Si el stock ya supera el objetivo, la sugerencia es 0
    stock_val = p.stock if p.stock is not None else 0
    reorder_target = 2 * min_stock_val
    reorder_suggestion = max(0, reorder_target - stock_val)

    return {
        "id": p.id,
        "code": p.code,
        "barcode": p.barcode,
        "name": p.name,
        "description": p.description,
        "category_id": p.category_id,
        "category_name": p.category.name if p.category else "-",
        "supplier_id": p.supplier_id,
        "supplier_name": p.supplier.name if p.supplier else "-",
        "price": float(p.price) if p.price is not None else 0.0,
        "cost": float(p.cost) if p.cost is not None else 0.0,
        "stock": stock_val,
        "min_stock": min_stock_val,
        "reorder_suggestion": reorder_suggestion,
        "is_active": p.is_active,
        "cabys_code": p.cabys_code,
        "cabys_name": p.cabys_name,
        "tax_type": p.tax_type,
        "tax_rate": tax_rate_str,
        "image_path": p.image_path,
        "is_pos_favorite": p.is_pos_favorite,
        "unit_type": p.unit_type or "Unid",
    }


# -----------------------------
# HELPER INTERNO: obtener ORM activo (solo activos)
# Usado internamente donde el producto DEBE estar activo para operar
# -----------------------------
def _get_product_orm(db: Session, product_id: int) -> Product:
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.is_active == True
    ).first()

    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return product


# ✅ Paso 6 — HELPER: obtener ORM sin importar el estado activo/inactivo
# Usado para: GET by ID, editar, duplicar, toggle favorito, toggle estado
def _get_product_any_status(db: Session, product_id: int) -> Product:
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return product


# -----------------------------
# ✅ FASE 7 — HELPER: Registrar movimiento de inventario
# Llamar SIEMPRE antes de modificar product.stock
# -----------------------------
def log_inventory_movement(
    db: Session,
    product: Product,
    type: MovementType,
    quantity,
    reference: str = None,
    notes: str = None,
):
    """
    Registra un movimiento de inventario.
    IMPORTANTE: llamar ANTES de modificar product.stock para que stock_before sea correcto.
    El stock_after se calcula automáticamente según el tipo de movimiento.
    No hace commit — lo maneja el flujo principal.
    📏 quantity acepta int, float o Decimal (soporta fracciones para kg/m/L).
    """
    if type in (MovementType.venta,):
        stock_after = product.stock - quantity
    else:
        # entrada, devolucion, ajuste → suma
        stock_after = product.stock + quantity

    movement = InventoryMovement(
        product_id   = product.id,
        type         = type,
        quantity     = quantity,
        stock_before = product.stock,
        stock_after  = stock_after,
        reference    = reference,
        notes        = notes,
    )
    db.add(movement)


# =====================================================================
#  FASE 4 — Cálculo inteligente de rotación y predicción de reposición
# =====================================================================

def _calc_rotation_data_batch(
    db: Session,
    product_ids: list[int],
    lookback_days: int = 90,
) -> dict[int, dict]:
    """
    Calcula datos de rotación para MÚLTIPLES productos en UNA sola query.
    Retorna: {product_id: {daily_avg, weekly_avg, monthly_avg, total_sold, ...}}

    Optimización Fase 4 — Fix 4.5: Evita el patrón N+1 en get_reorder_suggestions.
    Antes: 1 query por producto. Ahora: 1 query para todos.
    """
    if not product_ids:
        return {}

    cutoff = utcnow() - timedelta(days=lookback_days)
    now = utcnow()

    # UNA query con GROUP BY para todos los productos
    rows = (
        db.query(
            SaleDetail.product_id,
            func.sum(SaleDetail.quantity).label("total_sold"),
            func.count(func.distinct(func.date(Sale.created_at))).label("days_with_sales"),
            func.min(Sale.created_at).label("first_sale"),
        )
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .filter(
            SaleDetail.product_id.in_(product_ids),
            Sale.created_at >= cutoff,
        )
        .group_by(SaleDetail.product_id)
        .all()
    )

    # Mapear resultados
    sales_data = {}
    for row in rows:
        sales_data[row.product_id] = {
            "total_sold": float(row.total_sold or 0),
            "days_with_sales": int(row.days_with_sales or 0),
            "first_sale": row.first_sale,
        }

    return sales_data


def _build_rotation_result(
    sales_info: dict,
    stock: float,
    min_stock_val: float,
    lookback_days: int = 90,
) -> dict:
    """
    Construye el dict de rotación a partir de los datos de ventas agregados.
    Separado de la query para reutilizar tanto en batch como individual.
    """
    total_sold = sales_info.get("total_sold", 0)
    first_sale = sales_info.get("first_sale")

    if total_sold == 0:
        return {
            "daily_avg": 0.0,
            "weekly_avg": 0.0,
            "monthly_avg": 0.0,
            "total_sold": 0,
            "days_analyzed": lookback_days,
            "days_until_stockout": None,
            "smart_reorder": 0,
            "reorder_urgency": "bajo",
        }

    now = utcnow()
    if first_sale:
        if first_sale.tzinfo is None:
            from datetime import timezone
            first_sale = first_sale.replace(tzinfo=timezone.utc)
        actual_days = max((now - first_sale).days, 1)
        effective_days = min(actual_days, lookback_days)
    else:
        effective_days = lookback_days

    effective_days = max(effective_days, 1)

    daily_avg = total_sold / effective_days
    weekly_avg = daily_avg * 7
    monthly_avg = daily_avg * 30

    days_until_stockout = None
    if daily_avg > 0:
        days_until_stockout = round(stock / daily_avg, 1)

    coverage_days = 30
    safety_days = 7
    projected_need = daily_avg * (coverage_days + safety_days)
    smart_reorder = max(0, int(projected_need - stock + 0.5))

    classic_reorder = max(0, 2 * min_stock_val - stock)
    smart_reorder = max(smart_reorder, classic_reorder)

    if days_until_stockout is not None and days_until_stockout <= 3:
        urgency = "critico"
    elif days_until_stockout is not None and days_until_stockout <= 7:
        urgency = "alto"
    elif stock <= min_stock_val:
        urgency = "medio"
    else:
        urgency = "bajo"

    return {
        "daily_avg": round(daily_avg, 2),
        "weekly_avg": round(weekly_avg, 2),
        "monthly_avg": round(monthly_avg, 2),
        "total_sold": total_sold,
        "days_analyzed": effective_days,
        "days_until_stockout": days_until_stockout,
        "smart_reorder": smart_reorder,
        "reorder_urgency": urgency,
    }


def _calc_rotation_data(db: Session, product_id: int, lookback_days: int = 90) -> dict:
    """
    Calcula datos de rotación reales basados en el historial de ventas.
    Retorna:
      - daily_avg: promedio de unidades vendidas por día
      - weekly_avg: promedio semanal
      - monthly_avg: promedio mensual (30 días)
      - total_sold: total vendido en el periodo
      - days_analyzed: días reales con datos
      - days_until_stockout: estimación de días hasta agotarse
      - smart_reorder: cantidad sugerida basada en rotación real
      - reorder_urgency: 'critico' | 'alto' | 'medio' | 'bajo'
    """
    cutoff = utcnow() - timedelta(days=lookback_days)

    # Ventas del producto en el periodo
    rows = (
        db.query(
            func.sum(SaleDetail.quantity).label("total_sold"),
            func.count(func.distinct(func.date(Sale.created_at))).label("days_with_sales"),
            func.min(Sale.created_at).label("first_sale"),
            func.max(Sale.created_at).label("last_sale"),
        )
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .filter(
            SaleDetail.product_id == product_id,
            Sale.created_at >= cutoff,
        )
        .first()
    )

    total_sold = float(rows.total_sold or 0)
    days_with_sales = int(rows.days_with_sales or 0)

    if total_sold == 0 or days_with_sales == 0:
        return {
            "daily_avg": 0.0,
            "weekly_avg": 0.0,
            "monthly_avg": 0.0,
            "total_sold": 0,
            "days_analyzed": lookback_days,
            "days_until_stockout": None,
            "smart_reorder": 0,
            "reorder_urgency": "bajo",
        }

    # Calcular rango real de días (first_sale a hoy)
    first_sale = rows.first_sale
    if first_sale:
        # Asegurar que first_sale sea timezone-aware (MySQL puede devolver naive)
        if first_sale.tzinfo is None:
            from datetime import timezone
            first_sale = first_sale.replace(tzinfo=timezone.utc)
        actual_days = max((utcnow() - first_sale).days, 1)
        # Tomar el menor entre actual_days y lookback_days
        effective_days = min(actual_days, lookback_days)
    else:
        effective_days = lookback_days

    effective_days = max(effective_days, 1)

    daily_avg = total_sold / effective_days
    weekly_avg = daily_avg * 7
    monthly_avg = daily_avg * 30

    # Obtener stock actual (convertir a float para evitar Decimal vs float)
    product = db.query(Product).filter(Product.id == product_id).first()
    stock = float(product.stock) if product and product.stock is not None else 0.0
    min_stock_val = float(product.min_stock) if product and product.min_stock is not None else 3.0

    # Días hasta agotamiento
    days_until_stockout = None
    if daily_avg > 0:
        days_until_stockout = round(stock / daily_avg, 1)

    # Smart reorder: cubrir ventas de los próximos 30 días + buffer de seguridad (7 días)
    # Mínimo: el valor clásico (2 × min_stock - stock)
    coverage_days = 30
    safety_days = 7
    projected_need = daily_avg * (coverage_days + safety_days)
    smart_reorder = max(0, int(projected_need - stock + 0.5))

    # Garantizar al menos el cálculo clásico
    classic_reorder = max(0, 2 * min_stock_val - stock)
    smart_reorder = max(smart_reorder, classic_reorder)

    # Urgencia
    if days_until_stockout is not None and days_until_stockout <= 3:
        urgency = "critico"
    elif days_until_stockout is not None and days_until_stockout <= 7:
        urgency = "alto"
    elif stock <= min_stock_val:
        urgency = "medio"
    else:
        urgency = "bajo"

    return {
        "daily_avg": round(daily_avg, 2),
        "weekly_avg": round(weekly_avg, 2),
        "monthly_avg": round(monthly_avg, 2),
        "total_sold": total_sold,
        "days_analyzed": effective_days,
        "days_until_stockout": days_until_stockout,
        "smart_reorder": smart_reorder,
        "reorder_urgency": urgency,
    }


# -----------------------------
# CREATE
# -----------------------------
def create_product(db: Session, data: ProductCreate):
    if data.supplier_id:
        supplier = db.query(Supplier).filter(Supplier.id == data.supplier_id).first()

        if supplier and not supplier.is_active:
            raise HTTPException(
                status_code=400,
                detail="No se puede usar un proveedor inactivo."
            )

    product = Product(**data.model_dump())
    db.add(product)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        error_msg = str(e.orig).lower() if e.orig else ""
        if "code" in error_msg and "barcode" not in error_msg:
            raise HTTPException(status_code=409, detail=f"Ya existe un producto con el código '{data.code}'.")
        elif "barcode" in error_msg:
            raise HTTPException(status_code=409, detail=f"Ya existe un producto con el código de barras '{data.barcode}'.")
        else:
            raise HTTPException(status_code=409, detail="Ya existe un producto con esos datos (código o código de barras duplicado).")
    db.refresh(product)
    return _product_to_dict(product)


# -----------------------------
# LIST + COUNT (query única)
# ── FASE 4 — Fix 4.1: Construir filtros UNA sola vez ──
# Antes: get_products() y count_products() construían los mismos
# filtros independientemente (doble trabajo en Python y 2 queries
# con WHERE idéntico). Ahora una sola función retorna (data, total).
# -----------------------------
def _build_product_query(
    db: Session,
    search: str = None,
    supplier_id: int = None,
    category_id: int = None,
    is_active: bool | None = True,
):
    """Construye la query base con filtros aplicados (reutilizable)."""
    query = db.query(Product)

    if is_active is not None:
        query = query.filter(Product.is_active == is_active)

    if supplier_id:
        query = query.filter(Product.supplier_id == supplier_id)

    if category_id:
        query = query.filter(Product.category_id == category_id)

    if search:
        from app.utils.db_compat import escape_like
        safe = escape_like(search)
        query = query.filter(
            or_(
                Product.name.ilike(f"%{safe}%"),
                Product.code.ilike(f"%{safe}%"),
                Product.barcode.ilike(f"%{safe}%")
            )
        )

    return query


def get_products(
    db: Session,
    search: str = None,
    skip: int = 0,
    limit: int = 100,
    supplier_id: int = None,
    category_id: int = None,
    is_active: bool | None = True,
) -> tuple[list[dict], int]:
    """Retorna (lista_productos, total) en UNA sola query (window count)."""
    base = _build_product_query(db, search, supplier_id, category_id, is_active)

    # ── FASE 4 — Fix 4.1: window function evita el COUNT separado ──
    rows = (
        base
        .add_columns(func.count(Product.id).over().label("_total"))
        .order_by(Product.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    if not rows:
        return [], 0

    total = rows[0]._total
    return [_product_to_dict(p) for p, _ in rows], total


# Mantener count_products por compatibilidad (usa la misma query base)
def count_products(
    db: Session,
    search: str = None,
    supplier_id: int = None,
    category_id: int = None,
    is_active: bool | None = True,
) -> int:
    return _build_product_query(db, search, supplier_id, category_id, is_active).count()


# -----------------------------
# GET BY ID
# ✅ Paso 6 — ahora devuelve el producto aunque esté inactivo
# Simplifica editar, duplicar, favorito y stock desde contexto
# -----------------------------
def get_product(db: Session, product_id: int):
    product = _get_product_any_status(db, product_id)
    return _product_to_dict(product)


# -----------------------------
# UPDATE
# ✅ Paso 6 — permite editar aunque esté inactivo
# -----------------------------
def update_product(db: Session, product_id: int, data: ProductUpdate):
    product = _get_product_any_status(db, product_id)

    if data.supplier_id:
        supplier = db.query(Supplier).filter(Supplier.id == data.supplier_id).first()

        if supplier and not supplier.is_active:
            raise HTTPException(
                status_code=400,
                detail="No se puede asignar un proveedor inactivo."
            )

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(product, key, value)

    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        error_msg = str(e.orig).lower() if e.orig else ""
        if "code" in error_msg and "barcode" not in error_msg:
            raise HTTPException(status_code=409, detail=f"Ya existe otro producto con el código '{data.code}'.")
        elif "barcode" in error_msg:
            raise HTTPException(status_code=409, detail=f"Ya existe otro producto con el código de barras '{data.barcode}'.")
        else:
            raise HTTPException(status_code=409, detail="Ya existe otro producto con esos datos (código o código de barras duplicado).")
    db.refresh(product)
    return _product_to_dict(product)


# -----------------------------
# SOFT DELETE
# -----------------------------
def delete_product(db: Session, product_id: int):
    product = _get_product_orm(db, product_id)
    product.is_active = False
    db.flush()
    db.refresh(product)
    return _product_to_dict(product)


# -----------------------------
# DESACTIVAR PRODUCTO
# -----------------------------
def deactivate_product(db: Session, product_id: int):
    product = _get_product_any_status(db, product_id)
    product.is_active = False
    db.flush()
    db.refresh(product)
    return _product_to_dict(product)


# -----------------------------
# REACTIVAR PRODUCTO
# -----------------------------
def reactivate_product(db: Session, product_id: int):
    product = _get_product_any_status(db, product_id)
    product.is_active = True
    db.flush()
    db.refresh(product)
    return _product_to_dict(product)


# -----------------------------
# MARCAR / DESMARCAR FAVORITO POS
# ✅ Paso 6 — funciona sobre cualquier estado
# -----------------------------
def toggle_pos_favorite(db: Session, product_id: int, is_pos_favorite: bool):
    product = _get_product_any_status(db, product_id)
    product.is_pos_favorite = is_pos_favorite
    db.flush()
    db.refresh(product)
    return _product_to_dict(product)


# -----------------------------
# ADD STOCK
# ✅ FASE 7 — registra movimiento antes de sumar
# (solo activos: no tiene sentido agregar stock a un inactivo)
# -----------------------------
def add_stock(db: Session, product_id: int, quantity, reference: str = None, notes: str = None):
    """📏 quantity acepta int, float o Decimal (soporta fracciones para kg/m/L)."""
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a cero")

    # FASE 1 — Fix 1.3: Bloqueo pesimista para evitar race condition
    # cuando dos usuarios agregan stock al mismo tiempo.
    from app.utils.db_compat import lock_for_update
    query = db.query(Product).filter(
        Product.id == product_id,
        Product.is_active == True
    )
    product = lock_for_update(query).first()

    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    # ✅ FASE 7: log ANTES de modificar stock
    log_inventory_movement(
        db, product,
        type=MovementType.entrada,
        quantity=quantity,
        reference=reference or "Entrada manual",
        notes=notes,
    )

    product.stock += quantity

    # FASE 1 — Fix 1.2: flush only; router owns commit
    db.flush()
    db.refresh(product)
    return _product_to_dict(product)


# -----------------------------
# SUGERENCIAS DE REPOSICIÓN
# ✅ FASE 4: ahora incluye datos de rotación real + predicción inteligente
# Devuelve solo productos activos con stock < min_stock,
# con la cantidad sugerida a comprar basada en historial de ventas.
# -----------------------------
def get_reorder_suggestions(db: Session):
    """
    Retorna productos activos cuyo stock está por debajo del mínimo,
    ordenados por urgencia (mayor déficit primero).
    Cada item incluye: stock_actual, min_stock, reorder_suggestion,
    supplier_name, costo estimado de reposición, y datos de rotación.

    FASE 4 — Fix 4.5: Usa _calc_rotation_data_batch para evitar N+1 queries.
    Antes: 1 query individual por producto. Ahora: 1 query batch para todos.
    """
    products = (
        db.query(Product)
        .filter(
            Product.is_active == True,
            Product.stock < Product.min_stock,
        )
        .order_by((Product.min_stock - Product.stock).desc())
        .all()
    )

    if not products:
        return []

    # UNA query batch para todos los datos de rotación
    product_ids = [p.id for p in products]
    sales_batch = _calc_rotation_data_batch(db, product_ids, lookback_days=90)

    result = []
    for p in products:
        d = _product_to_dict(p)

        stock = float(p.stock) if p.stock is not None else 0.0
        min_stock_val = float(p.min_stock) if p.min_stock is not None else 3.0

        # Construir rotación desde datos batch (sin query adicional)
        sales_info = sales_batch.get(p.id, {})
        rotation = _build_rotation_result(sales_info, stock, min_stock_val)

        # Si hay datos de rotación, usar smart_reorder en lugar del clásico
        if rotation["total_sold"] > 0:
            d["reorder_suggestion"] = rotation["smart_reorder"]

        # Costo estimado = suggestion × cost (si tiene cost)
        cost_val = float(p.cost) if p.cost else 0.0
        d["estimated_cost"] = round(d["reorder_suggestion"] * cost_val, 2)

        # Agregar datos de rotación al resultado
        d["rotation"] = rotation

        result.append(d)

    # Re-ordenar por urgencia: critico > alto > medio > bajo
    urgency_order = {"critico": 0, "alto": 1, "medio": 2, "bajo": 3}
    result.sort(key=lambda x: (
        urgency_order.get(x.get("rotation", {}).get("reorder_urgency", "bajo"), 3),
        -(x.get("reorder_suggestion", 0)),
    ))

    return result


# -----------------------------
# GET BY BARCODE
# -----------------------------
def get_product_by_barcode(db: Session, barcode: str):
    product = (
        db.query(Product)
        .filter(
            Product.barcode == barcode,
            Product.is_active == True
        )
        .first()
    )

    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return _product_to_dict(product)