# app/db/crud/purchase.py

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from app.utils.dt import today_cr
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, subqueryload

from app.db.models.purchase import Purchase
from app.db.models.purchase_detail import PurchaseDetail
from app.db.models.purchase_payment import PurchasePayment
from app.db.models.purchase_credit_note import PurchaseCreditNote
from app.db.models.product import Product
from app.db.models.inventory_movement import InventoryMovement, MovementType
from app.schemas.purchase import (
    PurchaseCreate,
    PurchaseUpdate,
    PurchaseStatus,
    PurchaseItemCreate,
    PurchasePaymentCreate,
    PurchaseCreditNoteCreate,
)
from app.services.expense_service import add_expense_service
from app.constants.expense_categories import CAT_COMPRAS_PROVEEDORES

import logging

_logger = logging.getLogger(__name__)

# ── FASE 1 — Fix 1.1: Constantes Decimal para quantize ──
_Q2 = Decimal("0.01")        # 2 decimales (montos)


# ------------------------------------------------------------
# Helpers internos
# ------------------------------------------------------------
_ALLOWED_STATUS = {
    PurchaseStatus.pendiente,
    PurchaseStatus.recibido,
    PurchaseStatus.parcial,
    PurchaseStatus.pagado,
    PurchaseStatus.vencido,
}


def _validate_status(value: Optional[PurchaseStatus]) -> Optional[PurchaseStatus]:
    if value is None:
        return None
    if value not in _ALLOWED_STATUS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Estado de compra invalido: {value}",
        )
    return value


def _sync_supplier_products(db: Session, purchase: Purchase) -> None:
    """
    Fase 5 — Upsert automático en supplier_products.

    Recorre los purchase_details de la compra y para cada producto:
      - Si ya existe (supplier_id, product_id) → actualiza unit_cost y
        last_purchase_date (solo si la compra es más reciente).
      - Si no existe → crea el registro.

    Se ejecuta dentro de la transacción activa (antes del commit final
    del caller), así que NO hace commit propio.
    """
    from app.db.models.supplier_product import SupplierProduct

    if not purchase.details:
        return

    supplier_id = purchase.supplier_id
    purchase_date = purchase.entry_date  # date

    for detail in purchase.details:
        product_id = detail.product_id
        unit_cost = detail.unit_cost

        try:
            existing = (
                db.query(SupplierProduct)
                .filter_by(supplier_id=supplier_id, product_id=product_id)
                .first()
            )

            if existing:
                # Solo actualizar si esta compra es más reciente
                should_update = (
                    existing.last_purchase_date is None
                    or purchase_date >= (
                        existing.last_purchase_date.date()
                        if hasattr(existing.last_purchase_date, "date")
                        else existing.last_purchase_date
                    )
                )
                if should_update:
                    existing.unit_cost = unit_cost
                    existing.last_purchase_date = purchase_date
            else:
                # Determinar si es proveedor preferido (coincide con product.supplier_id)
                product = db.query(Product).filter(Product.id == product_id).first()
                is_preferred = (
                    product is not None
                    and product.supplier_id == supplier_id
                )

                sp = SupplierProduct(
                    supplier_id=supplier_id,
                    product_id=product_id,
                    unit_cost=unit_cost,
                    last_purchase_date=purchase_date,
                    is_preferred=is_preferred,
                )
                db.add(sp)

        except Exception as e:
            # No romper la compra si falla el sync
            _logger.warning(
                "Error sincronizando supplier_products para "
                "supplier=%s product=%s: %s",
                supplier_id, product_id, e,
            )


def _build_details(
    db: Session,
    purchase: Purchase,
    items: List[PurchaseItemCreate],
) -> Decimal:
    """
    Construye los PurchaseDetail y devuelve el total calculado.

    FASE 1 — Fix 1.1: Toda la aritmética usa Decimal para evitar
    errores de redondeo IEEE 754 (ej. 3 × ₡1,333.33 = ₡3,999.99
    exacto, no ₡3,999.98).
    """
    # Prefetch productos en UNA query
    product_ids = [item.product_id for item in items if item.product_id]
    products_map = {}
    if product_ids:
        products = db.query(Product).filter(Product.id.in_(set(product_ids))).all()
        products_map = {p.id: p for p in products}

    total = Decimal("0")
    for item in items:
        product = products_map.get(item.product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto ID {item.product_id} no encontrado.",
            )

        # quantity ya es Decimal (schema); unit_cost puede ser float → convertir
        qty = Decimal(str(item.quantity))
        cost = Decimal(str(item.unit_cost))

        # FASE 3 — Fix 3.3: Validar valores positivos (consistente con sale_crud.py)
        if qty <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cantidad inválida para '{product.name}': {qty}. Debe ser mayor a 0.",
            )
        if cost <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Costo unitario inválido para '{product.name}': {cost}. Debe ser mayor a 0.",
            )

        subtotal = (qty * cost).quantize(_Q2, rounding=ROUND_HALF_UP)
        total += subtotal

        detail = PurchaseDetail(
            purchase_id=purchase.id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit_cost=cost,
            subtotal=subtotal,
        )
        db.add(detail)

    return total.quantize(_Q2, rounding=ROUND_HALF_UP)


def _sync_payment_status(purchase: Purchase):
    """
    Recalcula el estado de pago basado en el saldo pendiente.
    NO toca estados de recepción ni vencimiento — solo el flujo de pago.
    """
    bal = purchase.balance

    if bal <= 0:
        purchase.status = PurchaseStatus.pagado
        if not purchase.paid_at:
            purchase.paid_at = today_cr()
    elif purchase.paid_amount > 0 or purchase.credit_notes_total > 0:
        # Hay abonos o NC pero no se ha saldado completamente
        if purchase.status == PurchaseStatus.pagado:
            pass  # no revertir desde pagado
        elif purchase.status not in (PurchaseStatus.recibido,):
            purchase.status = PurchaseStatus.parcial
        # Si está en recibido y tiene abonos parciales, cambiar a parcial
        elif purchase.status == PurchaseStatus.recibido:
            purchase.status = PurchaseStatus.parcial


def _check_single_purchase_expiry(purchase: Purchase) -> None:
    """
    FASE 1 — Fix 1.2: Verificación on-demand de vencimiento para
    una compra individual.  Barato (solo evalúa un registro en memoria).
    """
    if purchase.due_date is None:
        return
    today = today_cr()
    if (
        purchase.status == PurchaseStatus.pendiente
        and purchase.due_date < today
    ):
        purchase.status = PurchaseStatus.vencido
    elif (
        purchase.status == PurchaseStatus.vencido
        and purchase.due_date >= today
    ):
        purchase.status = PurchaseStatus.pendiente


# ------------------------------------------------------------
# Listar compras
# ------------------------------------------------------------
def get_purchases(
    db: Session,
    status_filter: Optional[PurchaseStatus] = None,
    supplier_id: Optional[int] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
):
    """
    FASE 1 — Fix 1.2: Se eliminó el auto-sync de compras vencidas
    que ejecutaba dos UPDATE masivos en cada GET.  Ahora eso corre
    en un task periódico (main.py) y on-demand en get_purchase().

    FASE 1 — Fix 1.4: Se eliminó el COUNT(*) separado.  Se usa
    window function para obtener (datos, total) en una sola query.
    """
    q = db.query(Purchase).options(
        subqueryload(Purchase.details),
        subqueryload(Purchase.payments),
        subqueryload(Purchase.credit_notes),
    )

    if status_filter:
        q = q.filter(Purchase.status == status_filter)

    if supplier_id:
        q = q.filter(Purchase.supplier_id == supplier_id)

    if search:
        from app.utils.db_compat import escape_like
        safe = escape_like(search)
        q = q.filter(Purchase.invoice_number.ilike(f"%{safe}%"))

    # ── Window function: total sin query separada ──
    rows = (
        q.add_columns(func.count(Purchase.id).over().label("_total"))
        .order_by(Purchase.entry_date.desc(), Purchase.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    if not rows:
        return [], 0

    total = rows[0]._total
    items = [row[0] for row in rows]
    return items, total


# ------------------------------------------------------------
# Obtener una compra
# ------------------------------------------------------------
def get_purchase(db: Session, purchase_id: int) -> Purchase:
    purchase = (
        db.query(Purchase)
        .options(
            subqueryload(Purchase.details),
            subqueryload(Purchase.payments),
            subqueryload(Purchase.credit_notes),
        )
        .filter(Purchase.id == purchase_id)
        .first()
    )
    if not purchase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Compra no encontrada",
        )

    # FASE 1 — Fix 1.2: verificación on-demand al consultar una compra
    _check_single_purchase_expiry(purchase)

    return purchase


# ------------------------------------------------------------
# Crear compra
# ------------------------------------------------------------
def create_purchase(db: Session, data: PurchaseCreate) -> Purchase:
    status_value = _validate_status(data.status) or PurchaseStatus.pendiente

    purchase = Purchase(
        invoice_number=data.invoice_number,
        supplier_id=data.supplier_id,
        entry_date=data.entry_date,
        due_date=data.due_date,
        amount=data.amount,
        status=status_value,
        payment_method=data.payment_method,
        notes=data.notes,
    )

    db.add(purchase)
    db.flush()

    if data.items:
        calculated_total = _build_details(db, purchase, data.items)
        purchase.amount = calculated_total

    # Fase 5: sincronizar supplier_products con los nuevos detalles
    db.flush()  # asegurar que details estén en session
    _sync_supplier_products(db, purchase)

    db.flush()
    db.refresh(purchase)
    return purchase


# ------------------------------------------------------------
# Actualizar compra
# ------------------------------------------------------------
def update_purchase(
    db: Session,
    purchase_id: int,
    data: PurchaseUpdate,
) -> Purchase:
    purchase = get_purchase(db, purchase_id)
    update_data = data.model_dump(exclude_unset=True)

    new_items = update_data.pop("items", None)

    if "status" in update_data:
        update_data["status"] = _validate_status(update_data["status"])

    for field, value in update_data.items():
        setattr(purchase, field, value)

    if new_items is not None:
        if purchase.status in (PurchaseStatus.recibido, PurchaseStatus.pagado, PurchaseStatus.parcial):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se pueden modificar líneas de una compra ya recibida, pagada o con abonos.",
            )

        db.query(PurchaseDetail).filter(
            PurchaseDetail.purchase_id == purchase.id
        ).delete(synchronize_session=False)
        db.flush()

        items_parsed = [
            PurchaseItemCreate(**i) if isinstance(i, dict) else i
            for i in new_items
        ]
        calculated_total = _build_details(db, purchase, items_parsed)
        purchase.amount = calculated_total

    if purchase.status not in (
        PurchaseStatus.pagado, PurchaseStatus.recibido, PurchaseStatus.parcial
    ) and purchase.due_date:
        today = today_cr()
        purchase.status = (
            PurchaseStatus.vencido
            if purchase.due_date < today
            else PurchaseStatus.pendiente
        )

    # Fase 5: re-sincronizar supplier_products si cambiaron ítems o proveedor
    if new_items is not None or "supplier_id" in data.model_dump(exclude_unset=True):
        db.flush()
        _sync_supplier_products(db, purchase)

    db.flush()
    db.refresh(purchase)
    return purchase


# ------------------------------------------------------------
# Recibir mercadería
# ------------------------------------------------------------
def receive_purchase(db: Session, purchase_id: int) -> Purchase:
    purchase = get_purchase(db, purchase_id)

    if purchase.received_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta compra ya fue recibida.",
        )
    if purchase.status == PurchaseStatus.pagado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta compra ya está pagada.",
        )

    if not purchase.details:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La compra no tiene líneas de detalle.",
        )

    # Prefetch productos en UNA query
    detail_product_ids = [d.product_id for d in purchase.details if d.product_id]
    products_map = {}
    if detail_product_ids:
        products = db.query(Product).filter(Product.id.in_(set(detail_product_ids))).all()
        products_map = {p.id: p for p in products}

    for detail in purchase.details:
        product = products_map.get(detail.product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto ID {detail.product_id} no encontrado.",
            )

        stock_before = product.stock
        qty = detail.quantity

        movement = InventoryMovement(
            product_id=product.id,
            type=MovementType.entrada,
            quantity=qty,
            stock_before=stock_before,
            stock_after=stock_before + qty,
            reference=f"Compra #{purchase.invoice_number}",
            notes=f"Recepción de compra ID {purchase.id}",
        )
        db.add(movement)

        product.stock = stock_before + qty
        # FASE 1 — Fix 1.1: Asignar Decimal directo (columna Numeric(12,2))
        product.cost = detail.unit_cost

    purchase.received_at = today_cr()

    # Estado: si ya tiene abonos parciales → parcial, sino → recibido
    if purchase.paid_amount > 0 and purchase.balance > 0:
        purchase.status = PurchaseStatus.parcial
    elif purchase.balance <= 0:
        purchase.status = PurchaseStatus.pagado
    else:
        purchase.status = PurchaseStatus.recibido

    db.flush()
    db.refresh(purchase)
    return purchase


# ============================================================
# PAGOS PARCIALES (ABONOS)
# ============================================================
def add_payment(
    db: Session,
    purchase_id: int,
    data: PurchasePaymentCreate,
    user_id: int | None = None,   # ── Auditoría: quién registró el abono ──
) -> Purchase:
    purchase = get_purchase(db, purchase_id)

    if purchase.status == PurchaseStatus.pagado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta compra ya está pagada en su totalidad.",
        )

    # ── FASE 4 — Fix 4.6: normalizar amount a Decimal de inmediato ──
    # El schema declara `amount: float` (pydantic v2 lo coacciona). Pero
    # la columna `PurchasePayment.amount` es DECIMAL(12,2). En MySQL el
    # adaptador convierte float→Decimal al persistir; en SQLite NO. Si
    # se agregan ≥2 abonos en la misma sesión, los ya persistidos se
    # recargan como Decimal y el recién creado queda como float en
    # memoria. Cuando `paid_amount` hace `sum(p.amount for p in payments)`
    # se mezclan tipos y lanza TypeError. Convertir vía str() preserva la
    # representación decimal del float sin arrastrar ruido IEEE 754.
    amount_dec = Decimal(str(data.amount))

    current_balance = purchase.balance

    if amount_dec > current_balance + 0.01:  # tolerancia redondeo (Decimal > float OK)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El abono (₡{amount_dec:.2f}) excede el saldo pendiente (₡{current_balance:.2f}).",
        )

    payment = PurchasePayment(
        purchase_id=purchase.id,
        amount=amount_dec,
        payment_method=data.payment_method,
        date=data.date or today_cr(),
        notes=data.notes,
    )
    db.add(payment)
    db.flush()

    # Registrar como gasto operativo
    expense_payload = {
        "category": CAT_COMPRAS_PROVEEDORES,
        "description": f"Abono factura #{purchase.invoice_number}",
        "amount": float(amount_dec),
        "payment_method": data.payment_method,
        "date": (data.date or today_cr()).strftime("%Y-%m-%d"),
    }
    # ── Fix auditoría: el gasto operativo conserva quién registró el abono. ──
    add_expense_service(expense_payload, db, user_id=user_id)

    # Si la compra tiene detalles y NO fue recibida, recibirla automáticamente al saldar
    db.refresh(purchase)
    if purchase.balance <= 0 and purchase.details and not purchase.received_at:
        # Prefetch productos en UNA query
        _pids = [d.product_id for d in purchase.details if d.product_id]
        _pmap = {}
        if _pids:
            _prods = db.query(Product).filter(Product.id.in_(set(_pids))).all()
            _pmap = {p.id: p for p in _prods}

        for detail in purchase.details:
            product = _pmap.get(detail.product_id)
            if product:
                stock_before = product.stock
                qty = detail.quantity
                movement = InventoryMovement(
                    product_id=product.id,
                    type=MovementType.entrada,
                    quantity=qty,
                    stock_before=stock_before,
                    stock_after=stock_before + qty,
                    reference=f"Compra #{purchase.invoice_number}",
                    notes=f"Recepción automática al saldar compra ID {purchase.id}",
                )
                db.add(movement)
                product.stock = stock_before + qty
                # FASE 1 — Fix 1.1: Asignar Decimal directo
                product.cost = detail.unit_cost
        purchase.received_at = today_cr()

    # Sincronizar estado de pago
    _sync_payment_status(purchase)

    db.flush()
    db.refresh(purchase)
    return purchase


def get_payments(db: Session, purchase_id: int) -> List[PurchasePayment]:
    purchase = get_purchase(db, purchase_id)  # valida existencia
    return (
        db.query(PurchasePayment)
        .filter(PurchasePayment.purchase_id == purchase_id)
        .order_by(PurchasePayment.date.desc())
        .all()
    )


# ============================================================
# NOTAS DE CRÉDITO / DEVOLUCIONES
# ============================================================
def add_credit_note(
    db: Session,
    purchase_id: int,
    data: PurchaseCreditNoteCreate,
) -> Purchase:
    purchase = get_purchase(db, purchase_id)

    # ── FASE 4 — Fix 4.6: normalizar amount a Decimal de inmediato ──
    # Mismo motivo que en add_payment: el schema es float, la columna es
    # DECIMAL(12,2), y SQLite no coacciona al insertar como sí lo hace
    # MySQL. Sin esta normalización, sumar credit_notes mezcladas
    # (existentes en Decimal, recién creada en float) lanza TypeError.
    amount_dec = Decimal(str(data.amount))

    # ── FASE 3 — Fix 3.1: validar el AGREGADO de NCs, no solo la NC individual ──
    # Bug previo: `if data.amount > float(purchase.amount)` validaba cada NC
    # contra el total bruto, pero NO contra el conjunto de NCs ya emitidas.
    # Ej.: una compra de ₡100,000 podía recibir 3 NCs de ₡40,000 cada una
    # (₡120,000 totales) porque cada una individualmente "no excede" el total,
    # y el balance quedaba en ₡-20,000.
    #
    # Regla contable: la suma de NCs nunca debe superar lo que aún se le debe
    # al proveedor "antes de abonos en efectivo":
    #     sum(NCs) + paid_amount  ≤  amount
    #   ⇔  nueva_NC  ≤  amount − paid_amount − existing_NCs   (= balance actual)
    purchase_amount = float(purchase.amount)
    existing_cn_total = purchase.credit_notes_total
    paid_amount = purchase.paid_amount
    max_allowed = purchase_amount - paid_amount - existing_cn_total

    # Tolerancia de redondeo (mismo criterio que add_payment, ver línea ~492).
    # `Decimal > float` funciona en Python 3 sin coacción; lo que NO funciona
    # es `Decimal + float`, por eso `0.01` y `max_allowed` se mantienen como
    # float (la suma queda en float y la comparación es Decimal vs float, OK).
    if amount_dec > max_allowed + 0.01:
        available = max(max_allowed, 0.0)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"La nota de crédito (₡{amount_dec:.2f}) excede el saldo "
                f"disponible para notas de crédito (₡{available:.2f}). "
                f"Total compra: ₡{purchase_amount:.2f} · "
                f"abonos: ₡{paid_amount:.2f} · "
                f"NCs previas: ₡{existing_cn_total:.2f}."
            ),
        )

    cn = PurchaseCreditNote(
        purchase_id=purchase.id,
        amount=amount_dec,
        reason=data.reason,
        date=data.date or today_cr(),
        product_id=data.product_id,
        quantity_returned=data.quantity_returned or 0,
        stock_reverted=False,
    )
    db.add(cn)
    db.flush()

    # Si hay devolución de producto → revertir stock
    if data.product_id and data.quantity_returned and data.quantity_returned > 0:
        product = db.query(Product).filter(Product.id == data.product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Producto ID {data.product_id} no encontrado.",
            )

        stock_before = product.stock

        if data.quantity_returned > stock_before:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No hay suficiente stock para devolver {data.quantity_returned} unidades "
                       f"(stock actual: {stock_before}).",
            )

        # Movimiento de inventario tipo devolución a proveedor (resta stock)
        movement = InventoryMovement(
            product_id=product.id,
            type=MovementType.devolucion_proveedor,
            quantity=data.quantity_returned,
            stock_before=stock_before,
            stock_after=stock_before - data.quantity_returned,
            reference=f"NC Compra #{purchase.invoice_number}",
            notes=f"Devolución a proveedor - {data.reason}",
        )
        db.add(movement)

        product.stock = stock_before - data.quantity_returned
        cn.stock_reverted = True

    # Sincronizar estado
    db.refresh(purchase)
    _sync_payment_status(purchase)

    db.flush()
    db.refresh(purchase)
    return purchase


def get_credit_notes(db: Session, purchase_id: int) -> List[PurchaseCreditNote]:
    get_purchase(db, purchase_id)  # valida existencia
    return (
        db.query(PurchaseCreditNote)
        .filter(PurchaseCreditNote.purchase_id == purchase_id)
        .order_by(PurchaseCreditNote.date.desc())
        .all()
    )


# ------------------------------------------------------------
# Marcar como pagada (legacy — ahora registra pago por saldo completo)
# ------------------------------------------------------------
def mark_as_paid(
    db: Session,
    purchase_id: int,
    payment_method: Optional[str] = None,
    user_id: int | None = None,   # ── Auditoría: quién marca la compra como pagada ──
) -> Purchase:
    purchase = get_purchase(db, purchase_id)

    if purchase.status == PurchaseStatus.pagado:
        return purchase

    remaining = purchase.balance
    if remaining <= 0:
        # Ya saldada por abonos/NC
        purchase.status = PurchaseStatus.pagado
        purchase.paid_at = today_cr()
        db.flush()
        db.refresh(purchase)
        return purchase

    # Registrar pago por el saldo completo
    payment_data = PurchasePaymentCreate(
        amount=remaining,
        payment_method=payment_method or "Efectivo",
        date=today_cr(),
        notes="Pago total del saldo restante",
    )

    return add_payment(db, purchase_id, payment_data, user_id=user_id)


# ------------------------------------------------------------
# Eliminar compra
# ------------------------------------------------------------
def delete_purchase(db: Session, purchase_id: int) -> None:
    purchase = get_purchase(db, purchase_id)
    db.delete(purchase)
    db.flush()