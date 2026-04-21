from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
from decimal import Decimal
from app.utils.dt import today_cr, TZ_CR

from app.db.models.credit import Credit
from app.db.models.credit_sale import CreditSale
from app.db.models.customer import Customer
from app.db.models.sale import Sale
from app.services.cash_movement_service import register_cash_movement
from app.db.crud.cash import get_open_session
from sqlalchemy import func, case


# ---------------------------------------------------------
# 1. Registrar venta a crédito
# ---------------------------------------------------------
def add_credit_sale(db: Session, customer_id: int, sale_id: int):
    """
    Registra una venta a crédito:
    - Busca la Sale por sale_id y obtiene el total desde la DB.
    - Guarda en credit_sales.
    - Agrega un movimiento de tipo 'sale' en credits.
    - Actualiza el saldo del cliente (customer.credit_balance).
    Orden correcto: validar limite → insertar registros → actualizar saldo → commit.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise ValueError(f"Cliente con ID {customer_id} no existe.")

    # ── Obtener total desde la venta real ──────────────────────────────────
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise ValueError(f"Venta con ID {sale_id} no existe.")

    # ── Evitar crédito duplicado para la misma venta (Bug 2.4) ──────────
    existing = db.query(CreditSale).filter(CreditSale.sale_id == sale_id).first()
    if existing:
        raise ValueError(
            f"La venta #{sale_id} ya tiene un crédito registrado (credit_sale #{existing.id})."
        )

    total_amount = Decimal(str(sale.total))

    # ── 1. Validar límite ANTES de tocar nada ─────────────────────────────
    current_balance = Decimal(str(customer.credit_balance or 0))
    limit_ = Decimal(str(customer.credit_limit or 0))

    if customer.has_credit_limit and limit_ > 0 and (current_balance + total_amount) > limit_:
        raise ValueError(
            f"El cliente superaría su límite de crédito. "
            f"Saldo actual: ₡{float(current_balance):,.2f} | "
            f"Límite: ₡{float(limit_):,.2f} | "
            f"Venta: ₡{float(total_amount):,.2f}"
        )

    # ── 2. Crear CreditSale (historial) ───────────────────────────────────
    credit_sale = CreditSale(
        customer_id=customer_id,
        sale_id=sale_id,
        total_amount=total_amount,
    )
    db.add(credit_sale)
    db.flush()  # obtener ID para la descripción

    # ── 3. Crear movimiento de crédito ────────────────────────────────────
    movement = Credit(
        customer_id=customer_id,
        amount=total_amount,
        type="sale",
        payment_method="Crédito",
        description=f"credit_sale_id:{credit_sale.id}"
    )
    db.add(movement)

    # ── 4. Actualizar saldo (UNA sola vez) ───────────────────────────────
    customer.credit_balance = current_balance + total_amount

    # NO commit aquí: lo hace el router al final de la venta
    return credit_sale


# ---------------------------------------------------------
# 2. Registrar pago o abono
# ---------------------------------------------------------
def add_credit_payment(db: Session, customer_id: int, amount: float, payment_method: str = "Efectivo"):
    """
    Registra un abono/cancelación al crédito.
    🆕 Si es Efectivo, registra movimiento de caja.

    ⚠️ NO hace commit: el router/end-point es el dueño de la transacción.
    """
    amount_dec = Decimal(str(amount))

    if amount_dec <= 0:
        raise ValueError("El monto del abono debe ser mayor a cero.")

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise ValueError(f"Cliente con ID {customer_id} no existe.")

    # ── FASE 1 — Fix 1.1: Validar que el abono no exceda el saldo ──
    current_balance = Decimal(str(customer.credit_balance or 0))
    if amount_dec > current_balance:
        raise ValueError(
            f"El abono (₡{float(amount_dec):,.2f}) excede el saldo pendiente "
            f"(₡{float(current_balance):,.2f}). Máximo permitido: ₡{float(current_balance):,.2f}"
        )

    # Crear movimiento de crédito
    payment = Credit(
        customer_id=customer_id,
        amount=amount_dec,
        type="payment",
        payment_method=payment_method,
        description=f"Abono a crédito ({payment_method})"
    )
    db.add(payment)
    db.flush()  # Para obtener el ID (payment.id)

    # 🆕 Si es efectivo, registrar en caja
    if payment_method == "Efectivo":
        cash_session = get_open_session(db)

        if cash_session:
            register_cash_movement(
                db=db,
                cash_session_id=cash_session.id,
                movement_type="IN",
                amount=amount_dec,
                concept=f"Abono de {customer.name}",
                source="CREDIT_PAYMENT",
                description=f"Abono crédito #{payment.id} - {customer.name}",
                reference_id=payment.id
            )

    # Actualizar saldo del cliente
    # ── FASE 1 — Fix 1.1: max(0) como red de seguridad ──
    customer.credit_balance = max(Decimal("0"), current_balance - amount_dec)

    # NO commit aquí: lo hace el router al final
    return payment


# ---------------------------------------------------------
# 3. Obtener resumen del crédito del cliente
# ── FASE 4 — Fix 4.2: Consolidar queries ──
# Antes: ~6 queries separadas. Ahora: 3 queries principales.
# ---------------------------------------------------------

def get_credit_info(
    db: Session,
    customer_id: int,
    mov_skip: int = 0,
    mov_limit: int = 20,
    sales_skip: int = 0,
    sales_limit: int = 50,
    date_from: str = None,
    date_to: str = None,
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return None

    today = today_cr()
    first_of_month = today.replace(day=1)

    # ─────────────────────────────────────────────────────────
    # QUERY 1: Agregados combinados (balance + paid_this_month + last_payment)
    # Antes eran 3 queries separadas, ahora es 1.
    # ─────────────────────────────────────────────────────────
    agg = (
        db.query(
            func.coalesce(
                func.sum(case((Credit.type == "sale", Credit.amount), else_=0)),
                0,
            ).label("total_sales"),
            func.coalesce(
                func.sum(case((Credit.type == "payment", Credit.amount), else_=0)),
                0,
            ).label("total_payments"),
            func.coalesce(
                func.sum(case(
                    (
                        (Credit.type == "payment") &
                        (Credit.created_at >= datetime.combine(first_of_month, datetime.min.time()).replace(tzinfo=TZ_CR)),
                        Credit.amount,
                    ),
                    else_=0,
                )),
                0,
            ).label("paid_this_month"),
            func.max(case(
                (Credit.type == "payment", Credit.created_at),
                else_=None,
            )).label("last_payment_at"),
        )
        .filter(Credit.customer_id == customer_id)
        .first()
    )

    total_sales = float(agg.total_sales or 0)
    total_payments = float(agg.total_payments or 0)
    balance = round(total_sales - total_payments, 2)
    paid_this_month = round(float(agg.paid_this_month or 0), 2)
    last_payment_date = (
        agg.last_payment_at.strftime("%Y-%m-%d %H:%M")
        if agg.last_payment_at else None
    )

    # ── FASE 2 — Fix 2.3: Reconciliación automática ──
    # Detecta drift entre customer.credit_balance (incremental) y
    # el balance real calculado desde la tabla credits.
    # Si divergen, corrige el campo cacheado y registra en log.
    stored_balance = round(float(customer.credit_balance or 0), 2)
    if abs(stored_balance - balance) > 0.01:
        from app.core.logger import logger as _logger
        _logger.warning(
            f"RECONCILIACIÓN CRÉDITO: Cliente #{customer_id} '{customer.name}' — "
            f"credit_balance almacenado: ₡{stored_balance:,.2f}, "
            f"balance real calculado: ₡{balance:,.2f}. "
            f"Corrigiendo automáticamente."
        )
        customer.credit_balance = Decimal(str(max(0, balance)))
        db.flush()

    # ─────────────────────────────────────────────────────────
    # QUERY 2: Movimientos paginados + conteo + aging (sale movements)
    # ─────────────────────────────────────────────────────────

    # 2a. Movimientos paginados (con filtros de fecha)
    movements_query = (
        db.query(Credit)
        .filter(Credit.customer_id == customer_id)
        .order_by(Credit.created_at.desc())
    )

    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=TZ_CR)
            movements_query = movements_query.filter(Credit.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d")
            dt_to = dt_to.replace(hour=23, minute=59, second=59, tzinfo=TZ_CR)
            movements_query = movements_query.filter(Credit.created_at <= dt_to)
        except ValueError:
            pass

    # ── FASE 4 — Fix 4.2: Eliminar COUNT separado con truco limit+1 ──
    movements = movements_query.offset(mov_skip).limit(mov_limit + 1).all()
    movements_has_more = len(movements) > mov_limit
    if movements_has_more:
        movements = movements[:mov_limit]

    # 2b. Aging: movimientos tipo "sale" (FIFO) — necesario para distribución
    # ── FASE 4 — Fix 4.2: Optimización de aging ──
    # - Si balance <= 0, no hay nada que "envejecer" → skip completo.
    # - Limitar a 500 filas: suficiente para cualquier caso real.
    #   Un cliente con >500 ventas a crédito sin pagar tiene problemas
    #   más grandes que la precisión del aging.
    aging = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}

    if balance > 0:
        sale_movement_rows = (
            db.query(Credit.amount, Credit.created_at)
            .filter(Credit.customer_id == customer_id, Credit.type == "sale")
            .order_by(Credit.created_at.asc())
            .limit(500)
            .all()
        )

        remaining_payments = total_payments

        for sm_amount, sm_created_at in sale_movement_rows:
            amount = float(sm_amount or 0)
            if remaining_payments >= amount:
                remaining_payments -= amount
                continue
            unpaid = amount - remaining_payments
            remaining_payments = 0

            days_old = (today - sm_created_at.date()).days if sm_created_at else 0
            if days_old <= 30:
                aging["0_30"] += unpaid
            elif days_old <= 60:
                aging["31_60"] += unpaid
            elif days_old <= 90:
                aging["61_90"] += unpaid
            else:
                aging["90_plus"] += unpaid

        for k in aging:
            aging[k] = round(aging[k], 2)

    # ─────────────────────────────────────────────────────────
    # QUERY 3: Credit sales paginadas + mapa para sale_id
    # Antes: 1 query para TODAS las credit_sales (mapa) + 1 paginada.
    # Ahora: solo 1 query paginada. El mapa se construye de las
    #        credit_sales referenciadas en los movimientos visibles.
    # ─────────────────────────────────────────────────────────
    sales_query = (
        db.query(CreditSale)
        .filter(CreditSale.customer_id == customer_id)
        .order_by(CreditSale.created_at.desc())
    )

    # ── FASE 4 — Fix 4.2: Eliminar COUNT separado con truco limit+1 ──
    credit_sales = sales_query.offset(sales_skip).limit(sales_limit + 1).all()
    credit_sales_has_more = len(credit_sales) > sales_limit
    if credit_sales_has_more:
        credit_sales = credit_sales[:sales_limit]

    # Mapa: solo extraer credit_sale_ids referenciados en movimientos visibles
    referenced_cs_ids = set()
    for m in movements:
        if m.type == "sale" and m.description and "credit_sale_id:" in m.description:
            try:
                cs_id = int(m.description.split("credit_sale_id:")[1].split()[0])
                referenced_cs_ids.add(cs_id)
            except (ValueError, IndexError):
                pass

    # Construir mapa desde credit_sales ya cargadas + query solo los faltantes
    credit_sale_map = {cs.id: cs.sale_id for cs in credit_sales}
    missing_ids = referenced_cs_ids - set(credit_sale_map.keys())
    if missing_ids:
        extra = (
            db.query(CreditSale.id, CreditSale.sale_id)
            .filter(CreditSale.id.in_(missing_ids))
            .all()
        )
        for row in extra:
            credit_sale_map[row.id] = row.sale_id

    # Construir items de movimientos con sale_id
    movement_items = []
    for m in movements:
        item = {
            "id": m.id,
            "amount": float(m.amount or 0),
            "type": m.type,
            "payment_method": m.payment_method or "N/A",
            "description": m.description,
            "created_at": m.created_at.strftime("%Y-%m-%d %H:%M"),
            "sale_id": None
        }

        if m.type == "sale" and m.description and "credit_sale_id:" in m.description:
            try:
                credit_sale_id = int(m.description.split("credit_sale_id:")[1].split()[0])
                item["sale_id"] = credit_sale_map.get(credit_sale_id)
            except (ValueError, IndexError):
                pass

        movement_items.append(item)

    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "phone": customer.phone,
            "id_type": getattr(customer, "id_type", None),
            "id_number": getattr(customer, "id_number", None),
            "credit_balance": float(customer.credit_balance or 0.0),
            "credit_limit": float(customer.credit_limit or 0.0),
            "has_credit_limit": bool(customer.has_credit_limit),
        },
        "balance": balance,

        # Aging
        "aging": aging,
        "paid_this_month": round(paid_this_month, 2),
        "last_payment_date": last_payment_date,

        # 👇 movimientos paginados CON sale_id
        "movements": {
            "items": movement_items,
            "total_estimate": mov_skip + len(movements) + (1 if movements_has_more else 0),
            "has_more": movements_has_more,
        },

        # 👇 ventas a crédito paginadas
        "credit_sales": {
            "items": [
                {
                    "id": cs.id,
                    "sale_id": cs.sale_id,
                    "total_amount": float(cs.total_amount or 0),
                    "created_at": cs.created_at.strftime("%Y-%m-%d %H:%M")
                }
                for cs in credit_sales
            ],
            "total_estimate": sales_skip + len(credit_sales) + (1 if credit_sales_has_more else 0),
            "has_more": credit_sales_has_more,
        }
    }