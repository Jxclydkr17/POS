#!/usr/bin/env python3
"""
scripts/backfill_supplier_products.py

Fase 1 — Backfill: puebla la tabla `supplier_products` a partir de los
datos existentes en `purchase_details` + `purchases`.

Para cada combinación única (supplier_id, product_id) encontrada en las
compras históricas, inserta un registro con:
  - unit_cost         → costo unitario de la compra MÁS RECIENTE
  - last_purchase_date → fecha de esa compra más reciente
  - is_preferred      → True si es el proveedor asignado actualmente
                         en product.supplier_id

Uso:
    cd /ruta/del/proyecto
    python -m scripts.backfill_supplier_products

    # O bien:
    python scripts/backfill_supplier_products.py

Es idempotente: si el registro ya existe, lo actualiza (upsert lógico).
"""

import sys
from pathlib import Path
from decimal import Decimal

# Asegurar que el proyecto esté en el path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import func, and_
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models.purchase import Purchase
from app.db.models.purchase_detail import PurchaseDetail
from app.db.models.product import Product
from app.db.models.supplier_product import SupplierProduct


def backfill(db: Session) -> dict:
    """
    Recorre purchase_details → purchases para extraer las combinaciones
    únicas (supplier_id, product_id), toma el costo más reciente, y
    las inserta/actualiza en supplier_products.

    Retorna un dict con contadores: {"created": N, "updated": M, "skipped": K}
    """
    stats = {"created": 0, "updated": 0, "skipped": 0}

    # ─── Subconsulta: para cada (supplier_id, product_id), la compra
    #     más reciente (por entry_date, luego por purchase.id como desempate) ───
    #
    # SELECT p.supplier_id, pd.product_id,
    #        pd.unit_cost, p.entry_date,
    #        ROW_NUMBER() OVER (
    #            PARTITION BY p.supplier_id, pd.product_id
    #            ORDER BY p.entry_date DESC, p.id DESC
    #        ) as rn
    # FROM purchase_details pd
    # JOIN purchases p ON pd.purchase_id = p.id

    from sqlalchemy import case, literal_column
    from sqlalchemy.sql import expression

    # Obtenemos todos los pares con la compra más reciente
    # Agrupamos por (supplier_id, product_id) y tomamos el max entry_date
    latest_subq = (
        db.query(
            Purchase.supplier_id,
            PurchaseDetail.product_id,
            func.max(Purchase.entry_date).label("max_date"),
        )
        .join(PurchaseDetail, PurchaseDetail.purchase_id == Purchase.id)
        .group_by(Purchase.supplier_id, PurchaseDetail.product_id)
        .subquery("latest")
    )

    # Ahora obtenemos el unit_cost de esa compra más reciente
    # (si hay varias compras en la misma fecha, tomamos la de mayor id)
    rows = (
        db.query(
            Purchase.supplier_id,
            PurchaseDetail.product_id,
            PurchaseDetail.unit_cost,
            Purchase.entry_date,
        )
        .join(PurchaseDetail, PurchaseDetail.purchase_id == Purchase.id)
        .join(
            latest_subq,
            and_(
                Purchase.supplier_id == latest_subq.c.supplier_id,
                PurchaseDetail.product_id == latest_subq.c.product_id,
                Purchase.entry_date == latest_subq.c.max_date,
            ),
        )
        .order_by(
            Purchase.supplier_id,
            PurchaseDetail.product_id,
            Purchase.id.desc(),  # desempate: compra más reciente por id
        )
        .all()
    )

    # Deduplicar: quedarnos con la primera fila de cada (supplier, product)
    seen = set()
    unique_rows = []
    for row in rows:
        key = (row.supplier_id, row.product_id)
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    # Cargar un set de (product_id → supplier_id) actual para marcar is_preferred
    preferred_map = {
        pid: sid
        for pid, sid in db.query(Product.id, Product.supplier_id)
        .filter(Product.supplier_id.isnot(None))
        .all()
    }

    # ─── Insertar o actualizar ───
    for row in unique_rows:
        supplier_id = row.supplier_id
        product_id = row.product_id
        unit_cost = Decimal(str(row.unit_cost)) if row.unit_cost else Decimal("0")
        last_date = row.entry_date

        is_preferred = preferred_map.get(product_id) == supplier_id

        existing = (
            db.query(SupplierProduct)
            .filter_by(supplier_id=supplier_id, product_id=product_id)
            .first()
        )

        if existing:
            # Solo actualizar si el dato nuevo es más reciente
            if existing.last_purchase_date is None or (
                last_date and last_date > existing.last_purchase_date.date()
                if hasattr(existing.last_purchase_date, "date")
                else last_date > existing.last_purchase_date
            ):
                existing.unit_cost = unit_cost
                existing.last_purchase_date = last_date
                existing.is_preferred = is_preferred
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        else:
            sp = SupplierProduct(
                supplier_id=supplier_id,
                product_id=product_id,
                unit_cost=unit_cost,
                last_purchase_date=last_date,
                is_preferred=is_preferred,
            )
            db.add(sp)
            stats["created"] += 1

    db.commit()
    return stats


def main():
    print("=" * 60)
    print("  Backfill: supplier_products")
    print("  Fuente: purchase_details + purchases")
    print("=" * 60)

    db = SessionLocal()
    try:
        stats = backfill(db)
        print(f"\n✅ Backfill completado:")
        print(f"   Creados:      {stats['created']}")
        print(f"   Actualizados: {stats['updated']}")
        print(f"   Sin cambio:   {stats['skipped']}")
        total = stats["created"] + stats["updated"] + stats["skipped"]
        print(f"   Total pares:  {total}")
    except Exception as e:
        db.rollback()
        print(f"\n❌ Error durante el backfill: {e}")
        raise
    finally:
        db.close()

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()