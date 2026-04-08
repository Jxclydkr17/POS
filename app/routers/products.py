from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.utils.dt import utcnow

from app.db.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
from app.db.models.product import Product
from app.db.models.inventory_movement import InventoryMovement     # ✅ FASE 7
from app.db.crud.product_crud import (
    create_product,
    get_products,
    get_product,
    update_product,
    delete_product,
    add_stock,
    get_product_by_barcode,
    deactivate_product,
    reactivate_product,
    toggle_pos_favorite,
    get_reorder_suggestions,
    _product_to_dict,
    _calc_rotation_data,       # ✅ FASE 4
)
from app.schemas.products import ProductCreate, ProductUpdate, ProductOut
from app.schemas.api_response import APIResponse


router = APIRouter(prefix="/products", tags=["Productos"])


# ==========================================================
# OBTENER PRODUCTO POR CÓDIGO DE BARRAS
# ==========================================================
@router.get("/barcode/{barcode}", response_model=APIResponse[ProductOut])
def get_product_by_barcode_route(
    barcode: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    product = get_product_by_barcode(db, barcode)

    # ✅ FASE 4: enriquecer con datos de rotación
    if product and product.get("id"):
        rotation = _calc_rotation_data(db, product["id"], lookback_days=90)
        product["rotation"] = rotation
        # Si hay rotación real, actualizar sugerencia
        if rotation["total_sold"] > 0 and rotation["smart_reorder"] > 0:
            product["reorder_suggestion"] = rotation["smart_reorder"]

    return APIResponse(message="Producto encontrado", data=product)


# ==========================================================
# LISTAR PRODUCTOS  ✅ Paso 10 — paginación + total
# ==========================================================
@router.get("/", response_model=APIResponse[List[ProductOut]])
def list_products(
    search: Optional[str] = None,
    supplier_id: Optional[int] = None,
    category_id: Optional[int] = None,
    is_active: Optional[bool] = True,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),   # ✅ límite configurable; máximo 500
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # ── FASE 4 — Fix 4.1: Una sola llamada retorna data + total ──
    data, total = get_products(
        db,
        search,
        skip,
        limit,
        supplier_id=supplier_id,
        category_id=category_id,
        is_active=is_active
    )

    return APIResponse(message="Productos cargados", data=data, total=total)


# ==========================================================
# FAVORITOS / PRODUCTOS RÁPIDOS PARA EL POS
# ✅ Paso 5 — primero favoritos manuales, luego completa con más vendidos
# ==========================================================
@router.get("/favorites/quick", response_model=APIResponse[List[ProductOut]])
def get_quick_favorite_products(
    limit: int = Query(6, ge=1, le=20),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Devuelve productos rápidos para el POS con esta prioridad:
    1. Productos marcados manualmente como favorito POS (is_pos_favorite=True), ordenados por nombre.
    2. Si no se llena el cupo, completa con los más vendidos en los últimos N días.
    3. Evita duplicados entre ambas listas.
    Máximo: `limit` productos (default 6).
    """
    result_ids: list[int] = []
    result_products: list[dict] = []

    # --- 1. Favoritos manuales (siempre primero) ---
    manual_favorites = (
        db.query(Product)
        .filter(Product.is_active == True, Product.is_pos_favorite == True)
        .order_by(Product.name.asc())
        .limit(limit)
        .all()
    )

    for p in manual_favorites:
        if p.id not in result_ids:
            result_ids.append(p.id)
            result_products.append(_product_to_dict(p))

    # --- 2. Completar con más vendidos si no se llenó el cupo ---
    remaining = limit - len(result_products)

    if remaining > 0:
        start_date = utcnow() - timedelta(days=days)

        top_rows = (
            db.query(
                SaleDetail.product_id,
                func.sum(SaleDetail.quantity).label("qty_sold")
            )
            .join(Sale, Sale.id == SaleDetail.sale_id)
            .join(Product, Product.id == SaleDetail.product_id)
            .filter(Sale.created_at >= start_date)
            .filter(Product.is_active == True)
            .filter(Product.id.notin_(result_ids))  # excluir ya incluidos
            .group_by(SaleDetail.product_id)
            .order_by(desc("qty_sold"))
            .limit(remaining)
            .all()
        )

        if top_rows:
            top_ids = [row.product_id for row in top_rows]
            extra_products = db.query(Product).filter(Product.id.in_(top_ids)).all()
            product_map = {p.id: p for p in extra_products}

            for pid in top_ids:
                if pid in product_map and pid not in result_ids:
                    result_ids.append(pid)
                    result_products.append(_product_to_dict(product_map[pid]))

        # --- 3. Si aún falta, fallback a stock más alto ---
        remaining = limit - len(result_products)
        if remaining > 0:
            fallback = (
                db.query(Product)
                .filter(Product.is_active == True)
                .filter(Product.id.notin_(result_ids))
                .order_by(Product.stock.desc(), Product.name.asc())
                .limit(remaining)
                .all()
            )
            for p in fallback:
                if p.id not in result_ids:
                    result_ids.append(p.id)
                    result_products.append(_product_to_dict(p))

    return APIResponse(message="Productos rápidos cargados", data=result_products)


# ==========================================================
# MARCAR / DESMARCAR FAVORITO POS
# ==========================================================
@router.patch("/{product_id}/favorite", response_model=APIResponse[ProductOut])
def toggle_favorite(
    product_id: int,
    is_pos_favorite: bool,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    product = toggle_pos_favorite(db, product_id, is_pos_favorite)
    message = (
        "Producto marcado como favorito POS"
        if is_pos_favorite
        else "Producto removido de favoritos POS"
    )
    return APIResponse(message=message, data=product)


# ==========================================================
# SUGERENCIAS DE REPOSICIÓN
# ⚠️ Debe ir ANTES de /{product_id} para que FastAPI no
#    interprete "reorder-suggestions" como un product_id.
# Devuelve solo los productos activos con stock < min_stock,
# ordenados por mayor urgencia (déficit).
# ✅ FASE 4: ahora incluye datos de rotación real
# ==========================================================
@router.get("/reorder-suggestions", response_model=APIResponse[List[dict]])
def reorder_suggestions(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Lista de productos que necesitan reposición.
    Por cada producto incluye:
      - stock_actual, min_stock
      - reorder_suggestion  (cuántas unidades comprar — basado en rotación real)
      - estimated_cost      (reorder_suggestion × costo unitario)
      - supplier_name       (para saber a quién pedirle)
      - rotation            (Fase 4: datos de rotación: daily_avg, days_until_stockout, urgency)
    """
    data = get_reorder_suggestions(db)
    return APIResponse(
        message=f"{len(data)} producto(s) necesitan reposición",
        data=data,
        total=len(data),
    )


# ==========================================================
# ✅ FASE 4 — DATOS DE ROTACIÓN PARA UN PRODUCTO
# ==========================================================
@router.get("/{product_id}/rotation", response_model=APIResponse[dict])
def get_product_rotation(
    product_id: int,
    days: int = Query(90, ge=7, le=365, description="Días de historial a analizar"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Retorna datos de rotación de ventas para un producto:
    - daily_avg, weekly_avg, monthly_avg
    - total_sold en el periodo
    - days_until_stockout
    - smart_reorder (cantidad sugerida basada en rotación)
    - reorder_urgency (critico/alto/medio/bajo)
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    rotation = _calc_rotation_data(db, product_id, lookback_days=days)
    rotation["product_id"] = product_id
    rotation["product_name"] = product.name
    rotation["current_stock"] = product.stock or 0
    rotation["min_stock"] = product.min_stock if product.min_stock is not None else 3

    return APIResponse(
        message=f"Rotación de {product.name}",
        data=rotation,
    )


# ==========================================================
# OBTENER PRODUCTO POR ID
# ✅ Paso 6 — devuelve el producto aunque esté inactivo
# ==========================================================
@router.get("/{product_id}", response_model=APIResponse[ProductOut])
def get_single_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    product = get_product(db, product_id)
    return APIResponse(message="Producto encontrado", data=product)


# ==========================================================
# CREAR PRODUCTO
# ==========================================================
@router.post("/", response_model=APIResponse[ProductOut])
def create(
    data: ProductCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    product = create_product(db, data)
    return APIResponse(message="Producto creado correctamente", data=product)


# ==========================================================
# ACTUALIZAR PRODUCTO
# ==========================================================
@router.put("/{product_id}", response_model=APIResponse[ProductOut])
def update(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    product = update_product(db, product_id, data)
    return APIResponse(message="Producto actualizado correctamente", data=product)


# ==========================================================
# ELIMINAR PRODUCTO (SOFT DELETE)
# ==========================================================
@router.delete("/{product_id}", response_model=APIResponse)
def delete(
    product_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    delete_product(db, product_id)
    return APIResponse(message="Producto eliminado correctamente")


# ==========================================================
# DESACTIVAR PRODUCTO
# ==========================================================
@router.patch("/{product_id}/deactivate", response_model=APIResponse[ProductOut])
def deactivate(
    product_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    product = deactivate_product(db, product_id)
    return APIResponse(message="Producto desactivado correctamente", data=product)


# ==========================================================
# REACTIVAR PRODUCTO
# ==========================================================
@router.patch("/{product_id}/reactivate", response_model=APIResponse[ProductOut])
def reactivate(
    product_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    product = reactivate_product(db, product_id)
    return APIResponse(message="Producto reactivado correctamente", data=product)


# ==========================================================
# AGREGAR STOCK
# ✅ FASE 7 — acepta reference y notes opcionales para el log
# ==========================================================
@router.post("/{product_id}/add-stock", response_model=APIResponse[ProductOut])
def add_product_stock(
    product_id: int,
    quantity: int,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    product = add_stock(db, product_id, quantity, reference=reference, notes=notes)
    return APIResponse(message="Stock agregado correctamente", data=product)


# ==========================================================
# ✅ FASE 7 — HISTORIAL DE MOVIMIENTOS DE INVENTARIO POR PRODUCTO
# ==========================================================
@router.get("/{product_id}/movements")
def get_inventory_movements(
    product_id: int,
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Devuelve el historial completo de movimientos de inventario de un producto.
    Ordenado del más reciente al más antiguo.
    Campos: fecha, tipo, cantidad, stock_antes, stock_despues, referencia.
    """
    # Verificar que el producto existe
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    movements = (
        db.query(InventoryMovement)
        .filter(InventoryMovement.product_id == product_id)
        .order_by(InventoryMovement.created_at.desc())
        .limit(limit)
        .all()
    )

    return APIResponse(
        message=f"Historial de movimientos — {product.name}",
        data=[
            {
                "id":            m.id,
                "fecha":         m.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "tipo":          m.type,
                "cantidad":      float(m.quantity) if m.quantity is not None else 0,
                "stock_antes":   float(m.stock_before) if m.stock_before is not None else 0,
                "stock_despues": float(m.stock_after) if m.stock_after is not None else 0,
                "referencia":    m.reference or "—",
                "notas":         m.notes or "—",
            }
            for m in movements
        ]
    )