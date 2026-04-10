# app/db/crud/proforma_crud.py
"""
Lógica de negocio de proformas/cotizaciones.
NO toca inventario, caja ni facturación electrónica.
Solo al convertir a venta se invoca sale_crud.create_sale() que ya maneja todo.
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models.proforma import Proforma
from app.db.models.proforma_detail import ProformaDetail
from app.db.models.product import Product
from app.db.models.customer import Customer
from app.db.models.user import User
from app.db.models.document_sequence import DocumentSequence

from app.db.crud.sale_crud import calc_line_tax, normalize_tax_rate
from app.schemas.proforma import (
    ProformaCreate,
    ProformaUpdate,
    ProformaConvertRequest,
    ProformaListOut,
    PaginatedProformasResponse,
)
from app.schemas.sale import SaleCreate, SaleItemCreate
from app.core.logger import logger
from app.utils.dt import utcnow


# ─── Helpers ────────────────────────────────────────────────────


def _now_naive():
    """
    Retorna UTC actual SIN timezone para comparar con fechas de MySQL.
    MySQL devuelve datetimes naive (sin tz), así que la comparación
    debe ser naive vs naive para evitar TypeError.
    """
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _next_proforma_number(db: Session) -> str:
    """
    Genera el siguiente número de proforma (PRO-000001, PRO-000002, ...).
    Usa la tabla document_sequences con document_type='PR'.
    ORM puro — compatible con SQLite y MySQL.
    """
    seq = (
        db.query(DocumentSequence)
        .filter(
            DocumentSequence.branch_code == "001",
            DocumentSequence.terminal_code == "00001",
            DocumentSequence.document_type == "PR",
        )
        .first()
    )

    if seq is None:
        seq = DocumentSequence(
            branch_code="001",
            terminal_code="00001",
            document_type="PR",
            next_number=1,
            updated_at=utcnow(),
        )
        db.add(seq)
        db.flush()

    current = seq.next_number
    seq.next_number = current + 1
    seq.updated_at = utcnow()
    db.flush()

    return f"PRO-{str(current).zfill(6)}"


def _process_proforma_lines(db: Session, proforma_id: int, items) -> Decimal:
    """
    Procesa las líneas de una proforma: valida producto (si existe),
    calcula totales con impuestos. NO descuenta stock.
    Retorna el total de la proforma.
    """
    total = Decimal("0")

    # FASE 3 — Fix 3.4: Prefetch todos los productos en UNA query
    product_ids = [
        item.product_id for item in items
        if not getattr(item, "is_common", False) and getattr(item, "product_id", None)
    ]
    products_map = {}
    if product_ids:
        products = db.query(Product).filter(Product.id.in_(set(product_ids))).all()
        products_map = {p.id: p for p in products}

    for item in items:

        # ─── PRODUCTO COMÚN: sin inventario ───
        # FASE 1 — Fix 1.1: Calcular IVA en productos comunes usando
        # calc_line_tax (misma lógica que sale_crud) para que la proforma
        # refleje el total real incluyendo impuestos.
        if getattr(item, "is_common", False):
            unit_price_dec = Decimal(str(item.unit_price))
            discount_pct = Decimal(str(item.discount_percent or 0))
            qty_dec = Decimal(str(item.quantity))
            tax_rate_pct = normalize_tax_rate(getattr(item, "tax_rate", 0))

            subtotal_base, tax_amount, total_linea = calc_line_tax(
                unit_price=unit_price_dec, quantity=qty_dec,
                discount_percent=discount_pct, tax_rate_pct=tax_rate_pct,
            )
            total += total_linea

            db.add(ProformaDetail(
                proforma_id=proforma_id,
                product_id=None,
                quantity=qty_dec,
                unit_price=unit_price_dec,
                discount_percent=discount_pct,
                subtotal=total_linea,
                tax_rate=tax_rate_pct,
                tax_amount=tax_amount,
                is_common=True,
                common_description=(item.common_description or "Producto común").strip(),
            ))
            continue
        # ─── FIN PRODUCTO COMÚN ───

        # Validar que el producto exista (pero NO descontar stock)
        # FASE 3 — Fix 3.4: Lookup desde mapa prefetcheado
        product = products_map.get(item.product_id)
        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Producto ID {item.product_id} no existe.",
            )
        if not product.is_active:
            raise HTTPException(
                status_code=400,
                detail=f"El producto '{product.name}' está desactivado.",
            )

        tax_rate_pct = normalize_tax_rate(product.tax_rate)
        unit_price_dec = Decimal(str(item.unit_price))
        discount_pct = Decimal(str(item.discount_percent or 0))

        # 📏 Convertir cantidad a Decimal
        qty_dec = Decimal(str(item.quantity))

        subtotal_base, tax_amount, total_linea = calc_line_tax(
            unit_price=unit_price_dec,
            quantity=qty_dec,
            discount_percent=discount_pct,
            tax_rate_pct=tax_rate_pct,
        )
        total += total_linea

        db.add(ProformaDetail(
            proforma_id=proforma_id,
            product_id=product.id,
            quantity=item.quantity,
            unit_price=unit_price_dec,
            discount_percent=discount_pct,
            subtotal=total_linea,
            tax_rate=tax_rate_pct,
            tax_amount=tax_amount,
        ))

    return total


# ═════════════════════════════════════════════════════════════
# Funciones principales de negocio
# ═════════════════════════════════════════════════════════════


def create_proforma(db: Session, data: ProformaCreate, current_user: User) -> dict:
    """Crea una proforma/cotización. NO toca stock, caja ni Hacienda."""

    if not data.details:
        raise HTTPException(status_code=400, detail="La proforma debe tener al menos un producto.")

    # Validar cliente si se proporcionó
    if data.customer_id:
        customer = db.query(Customer).filter(Customer.id == data.customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    # Generar número secuencial
    number = _next_proforma_number(db)

    # Calcular fecha de vencimiento
    now = _now_naive()
    valid_until = now + timedelta(days=data.validity_days)

    new_proforma = Proforma(
        customer_id=data.customer_id,
        user_id=current_user.id,
        number=number,
        status="VIGENTE",
        total=Decimal("0"),
        notes=(data.notes or "").strip() or None,
        validity_days=data.validity_days,
        valid_until=valid_until,
    )
    db.add(new_proforma)
    db.flush()

    # Procesar líneas (sin tocar stock)
    total = _process_proforma_lines(db, new_proforma.id, data.details)
    if total <= 0:
        raise HTTPException(status_code=400, detail="Total de proforma inválido.")

    new_proforma.total = total

    # FASE 1 — Fix 1.2: flush only; router owns commit (Unit of Work)
    db.flush()
    db.refresh(new_proforma)

    customer_name = "Cliente General"
    if data.customer_id:
        c = db.query(Customer).filter(Customer.id == data.customer_id).first()
        if c:
            customer_name = c.name

    return {
        "message": "Proforma creada correctamente.",
        "proforma": {
            "id": new_proforma.id,
            "number": new_proforma.number,
            "customer": customer_name,
            "total": float(total),
            "status": new_proforma.status,
            "validity_days": new_proforma.validity_days,
            "valid_until": new_proforma.valid_until.isoformat(),
            "user_id": current_user.id,
            "created_at": new_proforma.created_at.isoformat(),
        },
    }


def list_proformas(
    db: Session,
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> PaginatedProformasResponse:
    """Listado paginado de proformas con filtros opcionales."""
    page = max(1, page)
    page_size = max(1, min(500, page_size))

    # Auto-vencimiento: marcar como VENCIDA las que pasaron su valid_until
    now = _now_naive()
    db.query(Proforma).filter(
        Proforma.status == "VIGENTE",
        Proforma.valid_until < now,
    ).update({"status": "VENCIDA"}, synchronize_session="fetch")
    db.flush()

    query = db.query(Proforma)

    if status_filter:
        query = query.filter(Proforma.status == status_filter.upper())

    if search:
        search_term = f"%{search}%"
        query = query.outerjoin(Customer, Proforma.customer_id == Customer.id).filter(
            (Proforma.number.ilike(search_term)) |
            (Customer.name.ilike(search_term))
        )

    total_count = query.count()
    total_pages = max(1, math.ceil(total_count / page_size))
    offset = (page - 1) * page_size

    proformas = query.order_by(Proforma.created_at.desc()).offset(offset).limit(page_size).all()

    return PaginatedProformasResponse(
        data=[ProformaListOut.model_validate(p) for p in proformas],
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


def get_proforma_detail(db: Session, proforma_id: int) -> dict:
    """Retorna el detalle completo de una proforma."""
    proforma = db.query(Proforma).filter(Proforma.id == proforma_id).first()
    if not proforma:
        raise HTTPException(status_code=404, detail="Proforma no encontrada.")

    # Auto-vencimiento individual
    if proforma.status == "VIGENTE" and proforma.valid_until < _now_naive():
        proforma.status = "VENCIDA"
        # FASE 1 — Fix 1.2: flush only; router owns commit
        db.flush()
        db.refresh(proforma)

    details = db.query(ProformaDetail).filter(
        ProformaDetail.proforma_id == proforma.id
    ).all()

    # FASE 1 — Fix 1.4: Prefetch todos los productos en UNA query
    # para evitar N+1 (antes: 2 queries por línea dentro del loop)
    product_ids = [d.product_id for d in details if d.product_id]
    products_map = {}
    if product_ids:
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        products_map = {p.id: p for p in products}

    # Enriquecer con nombre de producto
    detail_list = []
    for d in details:
        product_name = None
        _ut = "Unid"

        if d.is_common or not d.product_id:
            product_name = d.common_description or "Producto común"
        else:
            prod = products_map.get(d.product_id)
            product_name = prod.name if prod else f"Producto #{d.product_id}"
            if prod:
                _ut = prod.unit_type or "Unid"

        detail_list.append({
            "product_id": d.product_id,
            "product_name": product_name,
            "quantity": d.quantity,
            "unit_price": float(d.unit_price),
            "subtotal": float(d.subtotal),
            "discount_percent": float(d.discount_percent or 0),
            "tax_rate": float(d.tax_rate or 0),
            "tax_amount": float(d.tax_amount or 0),
            "is_common": bool(d.is_common),
            "common_description": d.common_description,
            "unit_type": _ut,
        })

    customer_name = "Cliente General"
    if proforma.customer_id:
        c = db.query(Customer).filter(Customer.id == proforma.customer_id).first()
        if c:
            customer_name = c.name

    return {
        "id": proforma.id,
        "number": proforma.number,
        "customer_id": proforma.customer_id,
        "customer_name": customer_name,
        "user_id": proforma.user_id,
        "status": proforma.status,
        "total": float(proforma.total),
        "notes": proforma.notes,
        "validity_days": proforma.validity_days,
        "valid_until": proforma.valid_until.isoformat() if proforma.valid_until else None,
        "converted_sale_id": proforma.converted_sale_id,
        "created_at": proforma.created_at.isoformat() if proforma.created_at else None,
        "updated_at": proforma.updated_at.isoformat() if proforma.updated_at else None,
        "details": detail_list,
    }


def update_proforma(db: Session, proforma_id: int, data: ProformaUpdate) -> dict:
    """
    Edita una proforma. Libre, sin restricciones de Hacienda.
    Solo se pueden editar proformas VIGENTE o VENCIDA (permite reactivar).
    """
    proforma = db.query(Proforma).filter(Proforma.id == proforma_id).first()
    if not proforma:
        raise HTTPException(status_code=404, detail="Proforma no encontrada.")

    if proforma.status in ("CONVERTIDA", "ANULADA"):
        raise HTTPException(
            status_code=400,
            detail=f"No se puede editar una proforma {proforma.status}.",
        )

    if not data.details:
        raise HTTPException(status_code=400, detail="La proforma debe tener al menos un producto.")

    # Actualizar cliente si se proporcionó
    if data.customer_id is not None:
        if data.customer_id:
            customer = db.query(Customer).filter(Customer.id == data.customer_id).first()
            if not customer:
                raise HTTPException(status_code=404, detail="Cliente no encontrado.")
        proforma.customer_id = data.customer_id

    # Eliminar líneas viejas
    db.query(ProformaDetail).filter(ProformaDetail.proforma_id == proforma.id).delete()
    db.flush()

    # Procesar nuevas líneas
    total = _process_proforma_lines(db, proforma.id, data.details)
    if total <= 0:
        raise HTTPException(status_code=400, detail="Total de proforma inválido.")

    proforma.total = total

    if data.notes is not None:
        proforma.notes = data.notes.strip() or None

    # Si se cambiaron los días de vigencia, recalcular desde ahora
    if data.validity_days is not None:
        proforma.validity_days = data.validity_days
        proforma.valid_until = _now_naive() + timedelta(days=data.validity_days)

    # Reactivar si estaba vencida
    if proforma.status == "VENCIDA":
        proforma.status = "VIGENTE"

    # FASE 1 — Fix 1.2: flush only; router owns commit
    db.flush()
    db.refresh(proforma)

    return {
        "message": f"Proforma {proforma.number} actualizada.",
        "proforma_id": proforma.id,
        "number": proforma.number,
        "total": float(proforma.total),
        "status": proforma.status,
    }


def void_proforma(db: Session, proforma_id: int) -> dict:
    """Anula una proforma (soft-delete)."""
    proforma = db.query(Proforma).filter(Proforma.id == proforma_id).first()
    if not proforma:
        raise HTTPException(status_code=404, detail="Proforma no encontrada.")

    if proforma.status == "ANULADA":
        raise HTTPException(status_code=400, detail="La proforma ya está anulada.")

    if proforma.status == "CONVERTIDA":
        raise HTTPException(
            status_code=400,
            detail="No se puede anular una proforma ya convertida a venta.",
        )

    proforma.status = "ANULADA"
    # FASE 1 — Fix 1.2: flush only; router owns commit
    db.flush()

    return {
        "message": f"Proforma {proforma.number} anulada.",
        "proforma_id": proforma.id,
        "number": proforma.number,
        "status": "ANULADA",
    }


def convert_to_sale(
    db: Session,
    proforma_id: int,
    convert_data: ProformaConvertRequest,
    current_user: User,
) -> dict:
    """
    Convierte una proforma VIGENTE en una venta real.
    Revalida stock y precios al momento de convertir.
    Llama a sale_crud.create_sale() para el flujo completo
    (stock, caja, FE, PDF, email).
    """
    from app.db.crud.sale_crud import create_sale as create_sale_fn

    proforma = db.query(Proforma).filter(Proforma.id == proforma_id).first()
    if not proforma:
        raise HTTPException(status_code=404, detail="Proforma no encontrada.")

    # Auto-vencimiento
    if proforma.status == "VIGENTE" and proforma.valid_until < _now_naive():
        proforma.status = "VENCIDA"
        # FASE 1 — Fix 1.2: flush only; router owns commit
        db.flush()

    if proforma.status != "VIGENTE":
        raise HTTPException(
            status_code=400,
            detail=f"Solo se pueden convertir proformas VIGENTES. Estado actual: {proforma.status}",
        )

    # Cargar líneas de la proforma
    details = db.query(ProformaDetail).filter(
        ProformaDetail.proforma_id == proforma.id
    ).all()

    if not details:
        raise HTTPException(status_code=400, detail="La proforma no tiene líneas.")

    # FASE 3 — Fix 3.4: Prefetch productos para evitar N+1
    # FASE 4 — Fix 4.4: with_for_update() para evitar race condition
    # si dos cajeros convierten proformas del mismo producto al mismo tiempo.
    from app.core.config import is_sqlite
    conv_product_ids = [d.product_id for d in details if d.product_id and not d.is_common]
    conv_products_map = {}
    if conv_product_ids:
        conv_q = db.query(Product).filter(Product.id.in_(set(conv_product_ids)))
        if not is_sqlite():
            conv_q = conv_q.with_for_update()
        conv_products = conv_q.all()
        conv_products_map = {p.id: p for p in conv_products}

    # Revalidar stock y construir items para SaleCreate
    sale_items = []
    warnings = []

    for d in details:
        item_data = {
            "quantity": d.quantity,
            "unit_price": float(d.unit_price),
            "discount_percent": float(d.discount_percent or 0),
            "is_common": bool(d.is_common),
        }

        if d.is_common:
            item_data["product_id"] = None
            item_data["common_description"] = d.common_description or "Producto común"
        else:
            # Revalidar producto (desde mapa prefetcheado)
            product = conv_products_map.get(d.product_id)
            if not product:
                raise HTTPException(
                    status_code=400,
                    detail=f"Producto ID {d.product_id} ya no existe. Edite la proforma.",
                )
            if not product.is_active:
                raise HTTPException(
                    status_code=400,
                    detail=f"El producto '{product.name}' está desactivado.",
                )
            if product.stock < d.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Stock insuficiente para '{product.name}'. "
                        f"Disponible: {product.stock}, requerido: {d.quantity}."
                    ),
                )

            item_data["product_id"] = d.product_id

            # Avisar si el precio cambió (pero no bloquear)
            current_price = float(product.price or 0)
            proforma_price = float(d.unit_price)
            if current_price > 0 and abs(proforma_price - current_price) > 0.50:
                warnings.append(
                    f"'{product.name}': precio en proforma ₡{proforma_price:.2f}, "
                    f"precio actual ₡{current_price:.2f}"
                )

        sale_items.append(SaleItemCreate(**item_data))

    # Construir SaleCreate con los datos de conversión
    sale_create = SaleCreate(
        customer_id=proforma.customer_id,
        payment_method=convert_data.payment_method,
        document_type=convert_data.document_type or "04",
        details=sale_items,
        credit_days=convert_data.credit_days,
        condicion_venta_code=convert_data.condicion_venta_code,
    )

    # Llamar al flujo de venta existente (stock, caja, FE, PDF, email)
    sale_result = create_sale_fn(db, sale_create, current_user)

    # Marcar proforma como convertida
    proforma.status = "CONVERTIDA"
    proforma.converted_sale_id = sale_result["sale"]["id"]
    # FASE 1 — Fix 1.2: flush only; router owns commit
    db.flush()

    logger.info(
        f"Proforma {proforma.number} convertida a Venta #{sale_result['sale']['id']} "
        f"por usuario {current_user.id}"
    )

    result = {
        "message": f"Proforma {proforma.number} convertida a venta exitosamente.",
        "proforma_id": proforma.id,
        "proforma_number": proforma.number,
        "sale": sale_result["sale"],
        "pdf_path": sale_result.get("pdf_path"),
    }

    if warnings:
        result["price_warnings"] = warnings

    return result


def validate_conversion(db: Session, proforma_id: int) -> dict:
    """
    Pre-validación de conversión: revisa stock y precios de cada línea
    SIN crear nada. Retorna un reporte detallado para que el UI muestre
    las discrepancias y el usuario decida.

    Retorna:
        {
            "can_convert": bool,
            "proforma_number": str,
            "status": str,
            "issues": [  # solo si hay problemas
                {
                    "product_id": int,
                    "product_name": str,
                    "type": "stock" | "price" | "inactive" | "not_found",
                    "detail": str,
                    "proforma_qty": int,
                    "available_stock": int | None,
                    "proforma_price": float,
                    "current_price": float | None,
                    "blocking": bool,   # True = impide la conversión
                }
            ],
            "summary": {
                "total_lines": int,
                "ok_lines": int,
                "warning_lines": int,    # precio cambió pero hay stock
                "blocking_lines": int,   # sin stock / inactivo / no existe
            }
        }
    """
    proforma = db.query(Proforma).filter(Proforma.id == proforma_id).first()
    if not proforma:
        raise HTTPException(status_code=404, detail="Proforma no encontrada.")

    # Auto-vencimiento
    if proforma.status == "VIGENTE" and proforma.valid_until < _now_naive():
        proforma.status = "VENCIDA"
        # FASE 1 — Fix 1.2: flush only; router owns commit
        db.flush()
        db.refresh(proforma)

    if proforma.status != "VIGENTE":
        return {
            "can_convert": False,
            "proforma_number": proforma.number,
            "status": proforma.status,
            "issues": [{
                "product_id": None,
                "product_name": "—",
                "type": "status",
                "detail": f"La proforma está {proforma.status}, no se puede convertir.",
                "proforma_qty": 0,
                "available_stock": None,
                "proforma_price": 0,
                "current_price": None,
                "blocking": True,
            }],
            "summary": {"total_lines": 0, "ok_lines": 0, "warning_lines": 0, "blocking_lines": 1},
        }

    details = db.query(ProformaDetail).filter(
        ProformaDetail.proforma_id == proforma.id
    ).all()

    # FASE 1 — Fix 1.4: Prefetch todos los productos en UNA query
    product_ids = [d.product_id for d in details if d.product_id and not d.is_common]
    products_map = {}
    if product_ids:
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        products_map = {p.id: p for p in products}

    issues = []
    ok_lines = 0
    warning_lines = 0
    blocking_lines = 0

    for d in details:
        if d.is_common:
            ok_lines += 1
            continue

        product = products_map.get(d.product_id)

        if not product:
            issues.append({
                "product_id": d.product_id,
                "product_name": f"Producto #{d.product_id} (eliminado)",
                "type": "not_found",
                "detail": f"El producto ID {d.product_id} ya no existe en el sistema.",
                "proforma_qty": d.quantity,
                "available_stock": None,
                "proforma_price": float(d.unit_price),
                "current_price": None,
                "blocking": True,
            })
            blocking_lines += 1
            continue

        if not product.is_active:
            issues.append({
                "product_id": d.product_id,
                "product_name": product.name,
                "type": "inactive",
                "detail": f"'{product.name}' está desactivado.",
                "proforma_qty": d.quantity,
                "available_stock": product.stock,
                "proforma_price": float(d.unit_price),
                "current_price": float(product.price or 0),
                "blocking": True,
            })
            blocking_lines += 1
            continue

        has_issue = False

        # Stock insuficiente → bloqueante
        if product.stock < d.quantity:
            issues.append({
                "product_id": d.product_id,
                "product_name": product.name,
                "type": "stock",
                "detail": (
                    f"Stock insuficiente para '{product.name}': "
                    f"necesita {d.quantity}, disponible {product.stock}."
                ),
                "proforma_qty": d.quantity,
                "available_stock": product.stock,
                "proforma_price": float(d.unit_price),
                "current_price": float(product.price or 0),
                "blocking": True,
            })
            blocking_lines += 1
            has_issue = True

        # Precio cambió → advertencia (no bloquea)
        current_price = float(product.price or 0)
        proforma_price = float(d.unit_price)
        if current_price > 0 and abs(proforma_price - current_price) > 0.50:
            if not has_issue:  # no duplicar si ya tiene issue de stock
                issues.append({
                    "product_id": d.product_id,
                    "product_name": product.name,
                    "type": "price",
                    "detail": (
                        f"'{product.name}': precio en proforma ₡{proforma_price:,.2f}, "
                        f"precio actual ₡{current_price:,.2f}."
                    ),
                    "proforma_qty": d.quantity,
                    "available_stock": product.stock,
                    "proforma_price": proforma_price,
                    "current_price": current_price,
                    "blocking": False,
                })
                warning_lines += 1
            has_issue = True

        if not has_issue:
            ok_lines += 1

    can_convert = blocking_lines == 0

    return {
        "can_convert": can_convert,
        "proforma_number": proforma.number,
        "status": proforma.status,
        "issues": issues,
        "summary": {
            "total_lines": len(details),
            "ok_lines": ok_lines,
            "warning_lines": warning_lines,
            "blocking_lines": blocking_lines,
        },
    }