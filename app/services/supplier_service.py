# app/services/supplier_service.py
"""
Service layer para proveedores.
Toda la lógica de negocio, subqueries y scoring vive aquí.
El router solo se encarga de HTTP y dependencias FastAPI.
"""

import io
import csv
import math
from datetime import date
from itertools import groupby
from operator import itemgetter
from typing import Optional

from sqlalchemy import func, case, or_
from sqlalchemy.orm import Session

from app.db.models.supplier import Supplier
from app.db.models.product import Product
from app.db.models.purchase import Purchase
from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail


# ------------------------------------------------------------------
# Helpers internos
# ------------------------------------------------------------------

def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _avg_days_between_dates(dates: list[date]) -> Optional[int]:
    """
    Dada una lista de fechas ordenada asc, calcula el promedio
    de días entre fechas consecutivas. Retorna None si < 2 fechas.
    """
    if len(dates) < 2:
        return None
    diffs = [
        (dates[i] - dates[i - 1]).days
        for i in range(1, len(dates))
        if (dates[i] - dates[i - 1]).days >= 0
    ]
    if not diffs:
        return None
    return round(sum(diffs) / len(diffs))


def _build_product_subquery(db: Session):
    """Subquery: products_count y critical_products_count por supplier."""
    return (
        db.query(
            Product.supplier_id.label("supplier_id"),
            func.count(Product.id).label("products_count"),
            func.coalesce(
                func.sum(
                    case(
                        (Product.stock <= func.coalesce(Product.min_stock, 0), 1),
                        else_=0,
                    )
                ),
                0,
            ).label("critical_products_count"),
        )
        .filter(Product.supplier_id.isnot(None))
        .group_by(Product.supplier_id)
        .subquery()
    )


def _build_purchase_subquery(db: Session):
    """Subquery: purchases_count, total_purchased, last_purchase_date por supplier."""
    return (
        db.query(
            Purchase.supplier_id.label("supplier_id"),
            func.count(Purchase.id).label("purchases_count"),
            func.coalesce(func.sum(Purchase.amount), 0).label("total_purchased"),
            func.max(Purchase.entry_date).label("last_purchase_date"),
        )
        .group_by(Purchase.supplier_id)
        .subquery()
    )


def _build_sales_subquery(db: Session):
    """Subquery: rotation_units por supplier."""
    return (
        db.query(
            Product.supplier_id.label("supplier_id"),
            func.coalesce(func.sum(SaleDetail.quantity), 0).label("rotation_units"),
        )
        .join(Product, Product.id == SaleDetail.product_id)
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .group_by(Product.supplier_id)
        .subquery()
    )


def _compute_avg_days_map(db: Session) -> dict[int, Optional[int]]:
    """
    Calcula el promedio de días entre compras para TODOS los proveedores.
    Usa SQLAlchemy puro (sin DATEDIFF/LAG) → portable a SQLite, PostgreSQL, etc.
    """
    rows = (
        db.query(Purchase.supplier_id, Purchase.entry_date)
        .order_by(Purchase.supplier_id, Purchase.entry_date)
        .all()
    )

    result: dict[int, Optional[int]] = {}
    for sid, group in groupby(rows, key=itemgetter(0)):
        dates = [r[1] for r in group]
        result[sid] = _avg_days_between_dates(dates)

    return result


def _compute_avg_days_single(db: Session, supplier_id: int) -> Optional[int]:
    """Promedio de días entre compras para UN solo proveedor."""
    rows = (
        db.query(Purchase.entry_date)
        .filter(Purchase.supplier_id == supplier_id)
        .order_by(Purchase.entry_date)
        .all()
    )
    dates = [r[0] for r in rows]
    return _avg_days_between_dates(dates)


def _supplier_to_dict(
    supplier: Supplier,
    products_count: int,
    critical_products_count: int,
    purchases_count: int,
    total_purchased,
    last_purchase_date: Optional[date],
    rotation_units: int,
    dependency_pct: float,
    avg_days_between_purchases: Optional[int],
) -> dict:
    """Convierte un Supplier ORM + métricas en el dict que espera SupplierOut."""
    days_since = None
    if last_purchase_date:
        days_since = (date.today() - last_purchase_date).days

    return {
        "id": supplier.id,
        "name": supplier.name,
        "phone": supplier.phone,
        "email": supplier.email,
        "address": supplier.address,
        "notes": supplier.notes,
        "created_at": supplier.created_at,
        "is_active": bool(getattr(supplier, "is_active", True)),
        "contact_name": supplier.contact_name,
        "contact_phone": supplier.contact_phone,
        "contact_position": supplier.contact_position,
        "products_count": products_count,
        "critical_products_count": critical_products_count,
        "purchases_count": purchases_count,
        "total_purchased": total_purchased or 0,
        "last_purchase_date": last_purchase_date,
        "days_since_last_purchase": days_since,
        "rotation_units": rotation_units,
        "ranking_score": 0.0,
        "supplier_score": 0,
        "supplier_rank": "",
        "dependency_pct": dependency_pct,
        "avg_days_between_purchases": avg_days_between_purchases,
    }


# ------------------------------------------------------------------
# #7  Ranking por percentiles dinámicos
# ------------------------------------------------------------------

def _apply_scores_and_ranks(suppliers: list[dict]) -> list[dict]:
    """
    Calcula supplier_score (0–100) normalizado entre todos los proveedores
    y asigna ranking por percentiles dinámicos:
      - Top 10%  → 🥇 Principal
      - 10-40%   → 🥈 Alternativo
      - 40-100%  → 🥉 Ocasional
    """
    if not suppliers:
        return suppliers

    max_purchases = max((x["purchases_count"] for x in suppliers), default=0)
    max_rotation = max((x["rotation_units"] for x in suppliers), default=0)

    for x in suppliers:
        freq = (x["purchases_count"] / max_purchases) if max_purchases > 0 else 0.0
        rot = (x["rotation_units"] / max_rotation) if max_rotation > 0 else 0.0

        prod = x["products_count"]
        crit = x["critical_products_count"]
        stock_ok = _clamp01(1.0 - (crit / prod)) if prod > 0 else 0.0

        score = int(round(100 * (0.40 * freq + 0.40 * rot + 0.20 * stock_ok)))
        x["supplier_score"] = score
        x["ranking_score"] = float(score)

    suppliers.sort(key=lambda x: x.get("supplier_score", 0), reverse=True)

    n = len(suppliers)
    top10_idx = max(1, math.ceil(n * 0.10))   # al menos 1
    top40_idx = max(top10_idx + 1, math.ceil(n * 0.40))

    for i, s in enumerate(suppliers):
        if i < top10_idx:
            s["supplier_rank"] = "🥇 Principal"
        elif i < top40_idx:
            s["supplier_rank"] = "🥈 Alternativo"
        else:
            s["supplier_rank"] = "🥉 Ocasional"

    return suppliers


def _compute_individual_score(
    products_count: int,
    critical_count: int,
    purchases_count: int,
    rotation: int,
) -> int:
    """Score para un proveedor individual (sin normalización relativa)."""
    stock_ok = _clamp01(1.0 - (critical_count / products_count)) if products_count > 0 else 0.0
    freq = 1.0 if purchases_count > 0 else 0.0
    rot = 1.0 if rotation > 0 else 0.0
    return int(round(100 * (0.40 * freq + 0.40 * rot + 0.20 * stock_ok)))


# ------------------------------------------------------------------
# Funciones públicas (las que llama el router)
# ------------------------------------------------------------------

def list_suppliers(
    db: Session,
    *,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
) -> dict:
    """
    Lista proveedores con métricas, scores, ranking.
    Soporta búsqueda multi-campo (#8), filtro activos (#8) y paginación (#9).
    Retorna {"items": [...], "total": int, "skip": int, "limit": int}.
    """
    prod_sq = _build_product_subquery(db)
    purch_sq = _build_purchase_subquery(db)
    sales_sq = _build_sales_subquery(db)

    base_q = (
        db.query(
            Supplier,
            func.coalesce(prod_sq.c.products_count, 0),
            func.coalesce(prod_sq.c.critical_products_count, 0),
            func.coalesce(purch_sq.c.purchases_count, 0),
            func.coalesce(purch_sq.c.total_purchased, 0),
            purch_sq.c.last_purchase_date,
            func.coalesce(sales_sq.c.rotation_units, 0),
        )
        .outerjoin(prod_sq, prod_sq.c.supplier_id == Supplier.id)
        .outerjoin(purch_sq, purch_sq.c.supplier_id == Supplier.id)
        .outerjoin(sales_sq, sales_sq.c.supplier_id == Supplier.id)
    )

    # --- #8  Filtro activos/inactivos ---
    if is_active is not None:
        base_q = base_q.filter(Supplier.is_active == is_active)

    # --- #8  Búsqueda multi-campo ---
    if search:
        term = f"%{search}%"
        base_q = base_q.filter(
            or_(
                Supplier.name.ilike(term),
                Supplier.email.ilike(term),
                Supplier.phone.ilike(term),
                Supplier.contact_name.ilike(term),
                Supplier.contact_phone.ilike(term),
                Supplier.address.ilike(term),
            )
        )

    rows = base_q.order_by(Supplier.name).all()

    avg_days_map = _compute_avg_days_map(db)
    total_products = db.query(func.count(Product.id)).scalar() or 0

    out = []
    for s, pcount, ccount, purch_count, total_purch, last_date, rot_units in rows:
        supplier_products = int(pcount or 0)
        dependency_pct = (
            round((supplier_products / total_products) * 100, 1)
            if total_products > 0
            else 0.0
        )

        out.append(
            _supplier_to_dict(
                supplier=s,
                products_count=supplier_products,
                critical_products_count=int(ccount or 0),
                purchases_count=int(purch_count or 0),
                total_purchased=total_purch,
                last_purchase_date=last_date,
                rotation_units=int(rot_units or 0),
                dependency_pct=dependency_pct,
                avg_days_between_purchases=avg_days_map.get(s.id),
            )
        )

    scored = _apply_scores_and_ranks(out)

    total = len(scored)
    page = scored[skip : skip + limit]

    return {"items": page, "total": total, "skip": skip, "limit": limit}


def get_supplier_by_id(db: Session, supplier_id: int) -> Optional[dict]:
    """
    Retorna un proveedor con todas sus métricas, o None si no existe.
    """
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        return None

    # Métricas de productos
    prod_row = (
        db.query(
            func.count(Product.id).label("products_count"),
            func.coalesce(
                func.sum(
                    case(
                        (Product.stock <= func.coalesce(Product.min_stock, 0), 1),
                        else_=0,
                    )
                ),
                0,
            ).label("critical_products_count"),
        )
        .filter(Product.supplier_id == supplier_id)
        .first()
    )
    supplier_products = int(prod_row.products_count or 0)
    critical_i = int(prod_row.critical_products_count or 0)

    # Métricas de compras
    purch_row = (
        db.query(
            func.count(Purchase.id).label("purchases_count"),
            func.coalesce(func.sum(Purchase.amount), 0).label("total_purchased"),
            func.max(Purchase.entry_date).label("last_purchase_date"),
        )
        .filter(Purchase.supplier_id == supplier_id)
        .first()
    )
    purch_count_i = int(purch_row.purchases_count or 0)
    total_purch = purch_row.total_purchased or 0
    last_date = purch_row.last_purchase_date

    # Rotación de ventas
    rotation = int(
        db.query(func.coalesce(func.sum(SaleDetail.quantity), 0))
        .join(Product, Product.id == SaleDetail.product_id)
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .filter(Product.supplier_id == supplier_id)
        .scalar()
        or 0
    )

    # Dependencia
    total_products = db.query(func.count(Product.id)).scalar() or 0
    dependency_pct = (
        round((supplier_products / total_products) * 100, 1)
        if total_products > 0
        else 0.0
    )

    # Avg days (SQLAlchemy puro)
    avg_days = _compute_avg_days_single(db, supplier_id)

    # Score individual
    score = _compute_individual_score(supplier_products, critical_i, purch_count_i, rotation)

    result = _supplier_to_dict(
        supplier=supplier,
        products_count=supplier_products,
        critical_products_count=critical_i,
        purchases_count=purch_count_i,
        total_purchased=total_purch,
        last_purchase_date=last_date,
        rotation_units=rotation,
        dependency_pct=dependency_pct,
        avg_days_between_purchases=avg_days,
    )
    result["supplier_score"] = score
    result["ranking_score"] = float(score)

    return result


def create_supplier(db: Session, name: str, **kwargs) -> Supplier:
    """Crea un proveedor. Lanza ValueError si el nombre ya existe."""
    existing = db.query(Supplier).filter(Supplier.name == name).first()
    if existing:
        raise ValueError("El proveedor ya existe")

    supplier = Supplier(name=name, **kwargs)
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


def update_supplier(db: Session, supplier_id: int, data: dict) -> Optional[Supplier]:
    """
    Actualiza un proveedor. Retorna None si no existe.
    Lanza ValueError si el nombre duplica otro proveedor.
    """
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        return None

    if "name" in data:
        exists = (
            db.query(Supplier)
            .filter(Supplier.name == data["name"], Supplier.id != supplier_id)
            .first()
        )
        if exists:
            raise ValueError("Ya existe otro proveedor con ese nombre.")

    for k, v in data.items():
        setattr(supplier, k, v)

    db.commit()
    db.refresh(supplier)
    return supplier


def toggle_supplier(db: Session, supplier_id: int) -> Optional[Supplier]:
    """Alterna is_active. Retorna None si no existe."""
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        return None

    supplier.is_active = not bool(supplier.is_active)
    db.commit()
    db.refresh(supplier)
    return supplier


def delete_supplier(db: Session, supplier_id: int) -> Optional[bool]:
    """
    Elimina un proveedor.  Retorna None si no existe,
    lanza ValueError si tiene productos asociados.
    """
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        return None

    if supplier.products:
        raise ValueError("No se puede eliminar un proveedor con productos asociados.")

    db.delete(supplier)
    db.commit()
    return True


# ------------------------------------------------------------------
# #10  Export CSV / Excel
# ------------------------------------------------------------------

def export_suppliers_csv(db: Session, *, search: Optional[str] = None, is_active: Optional[bool] = None) -> str:
    """Genera CSV de proveedores con métricas y retorna el string completo."""
    result = list_suppliers(db, search=search, is_active=is_active, skip=0, limit=999999)
    items = result["items"]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Nombre", "Teléfono", "Email", "Dirección",
        "Contacto", "Tel. Contacto", "Cargo Contacto",
        "Productos", "Críticos", "Compras", "Total Comprado",
        "Última Compra", "Días sin Comprar", "Rotación (uds)",
        "Score", "Rank", "Dependencia %", "Promedio Días Compra",
        "Estado", "Notas",
    ])
    for s in items:
        writer.writerow([
            s["id"],
            s["name"],
            s.get("phone") or "",
            s.get("email") or "",
            s.get("address") or "",
            s.get("contact_name") or "",
            s.get("contact_phone") or "",
            s.get("contact_position") or "",
            s["products_count"],
            s["critical_products_count"],
            s["purchases_count"],
            float(s.get("total_purchased", 0) or 0),
            str(s["last_purchase_date"]) if s.get("last_purchase_date") else "",
            s.get("days_since_last_purchase") if s.get("days_since_last_purchase") is not None else "",
            s["rotation_units"],
            s.get("supplier_score", 0),
            s.get("supplier_rank", ""),
            s.get("dependency_pct", 0),
            s.get("avg_days_between_purchases") if s.get("avg_days_between_purchases") is not None else "",
            "Activo" if s.get("is_active") else "Inactivo",
            s.get("notes") or "",
        ])

    return output.getvalue()


def export_suppliers_excel(db: Session, *, search: Optional[str] = None, is_active: Optional[bool] = None) -> str:
    """Genera Excel de proveedores y retorna la ruta del archivo temporal."""
    import pandas as pd
    import os
    from datetime import datetime as _dt

    result = list_suppliers(db, search=search, is_active=is_active, skip=0, limit=999999)
    items = result["items"]

    rows = []
    for s in items:
        rows.append({
            "ID": s["id"],
            "Nombre": s["name"],
            "Teléfono": s.get("phone") or "",
            "Email": s.get("email") or "",
            "Dirección": s.get("address") or "",
            "Contacto": s.get("contact_name") or "",
            "Tel. Contacto": s.get("contact_phone") or "",
            "Cargo Contacto": s.get("contact_position") or "",
            "Productos": s["products_count"],
            "Críticos": s["critical_products_count"],
            "Compras": s["purchases_count"],
            "Total Comprado": float(s.get("total_purchased", 0) or 0),
            "Última Compra": str(s["last_purchase_date"]) if s.get("last_purchase_date") else "",
            "Días sin Comprar": s.get("days_since_last_purchase") if s.get("days_since_last_purchase") is not None else "",
            "Rotación (uds)": s["rotation_units"],
            "Score": s.get("supplier_score", 0),
            "Rank": s.get("supplier_rank", ""),
            "Dependencia %": s.get("dependency_pct", 0),
            "Prom. Días Compra": s.get("avg_days_between_purchases") if s.get("avg_days_between_purchases") is not None else "",
            "Estado": "Activo" if s.get("is_active") else "Inactivo",
            "Notas": s.get("notes") or "",
        })

    os.makedirs("exports", exist_ok=True)
    filepath = f"exports/proveedores_{_dt.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df = pd.DataFrame(rows)
    df.to_excel(filepath, index=False)
    return filepath
