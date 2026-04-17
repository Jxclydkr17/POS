# app/db/crud/sale_crud.py
"""
FASE 4.1 — Lógica de negocio de ventas extraída del router.
El router solo valida entrada, llama a estas funciones y devuelve respuesta.
"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
from app.db.models.product import Product
from app.db.models.customer import Customer
from app.db.models.cash_session import CashSession
from app.db.models.electronic_invoice import ElectronicInvoice
from app.db.models.issuer_profile import IssuerProfile
from app.db.models.inventory_movement import MovementType
from app.db.models.credit_sale import CreditSale
from app.db.models.credit import Credit
from app.db.models.user import User
from app.db.crud.product_crud import log_inventory_movement

from app.schemas.sale import (
    SaleCreate, SaleUpdate, SaleListOut,
    PaginatedSalesResponse, SaleItemCreate,
)
from app.services.credit_service import add_credit_sale
from app.services.pdf_reports import generate_sale_pdf
from app.utils.email_utils import send_sale_email
from app.services.cash_movement_service import register_cash_movement
from app.core.logger import logger
from app.einvoice.sequence import next_sequence_number, build_consecutivo, build_clave
from app.utils.dt import today_cr, utcnow

# 📏 Helper de unidades de medida
from app.utils.unit_helpers import is_unit_based
from app.core.config import is_sqlite


# ── FASE 4 — Fix 4.5: Redondeo para display ──
# Internamente los cálculos usan 5 decimales (requerido por Hacienda CR),
# pero los montos mostrados al usuario deben redondearse a 2 decimales
# para no mostrar cosas como "₡15,234.56789".
_DISPLAY_Q = Decimal("0.01")


def _display(value) -> float:
    """Redondea un monto a 2 decimales para respuestas API / UI."""
    return float(Decimal(str(value)).quantize(_DISPLAY_Q, rounding=ROUND_HALF_UP))


# ── FASE 1 — Fix 1.3: with_for_update() no funciona en SQLite ──
def _lock_for_update(query):
    """Aplica bloqueo pesimista solo si el motor lo soporta (MySQL)."""
    if is_sqlite():
        return query
    return query.with_for_update()


# ─── Helpers ────────────────────────────────────────────────────


def is_efectivo(pm: str) -> bool:
    return (pm or "").strip().lower() == "efectivo"


def is_credit_method(pm: str) -> bool:
    return (pm or "").strip().lower() in ("credito", "crédito")


def normalize_tax_rate(raw_rate) -> Decimal:
    rate = Decimal(str(raw_rate or 0))
    if 0 < rate < 1:
        rate *= Decimal("100")
    return rate


def calc_line_tax(
    unit_price: Decimal,
    quantity: Decimal,
    discount_percent: Decimal,
    tax_rate_pct: Decimal,
):
    """
    Calcula montos de una línea.
    unit_price: precio CON IVA incluido.
    quantity: ahora Decimal para soportar fracciones (kg, m, L).
    Retorna: (subtotal_base, tax_amount, total_linea)
    """
    rate_frac = tax_rate_pct / Decimal("100")
    tax_factor = Decimal("1") + rate_frac

    unit_net = unit_price / tax_factor if rate_frac > 0 else unit_price
    gross = unit_net * Decimal(str(quantity))
    disc_amt = gross * (discount_percent / Decimal("100"))
    subtotal = gross - disc_amt
    tax_amt = subtotal * rate_frac if rate_frac > 0 else Decimal("0")
    total = subtotal + tax_amt

    Q = lambda v: v.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
    return Q(subtotal), Q(tax_amt), Q(total)


def _get_open_cash_session(db: Session) -> CashSession:
    """
    FASE 2 — Fix 2.5: Búsqueda timezone-safe de caja abierta.

    Primero busca la sesión de hoy (caso más común).
    Si no la encuentra (ej: venta a las 00:05 con caja de ayer aún abierta),
    busca CUALQUIER sesión abierta como fallback.
    Esto cubre el edge case de medianoche sin forzar al cajero a cerrar
    y reabrir caja exactamente a las 12:00 AM.
    """
    # Intento 1: sesión de hoy (caso normal, ~99% de las veces)
    cs = (
        db.query(CashSession)
        .filter(CashSession.status == "open", CashSession.date == today_cr())
        .first()
    )
    if cs:
        return cs

    # Intento 2: cualquier sesión abierta (cubre cruce de medianoche)
    cs = (
        db.query(CashSession)
        .filter(CashSession.status == "open")
        .order_by(CashSession.date.desc())
        .first()
    )
    if cs:
        return cs

    raise HTTPException(status_code=400, detail="No hay una caja abierta para registrar la venta.")


def _get_or_create_issuer(db: Session) -> IssuerProfile:
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        issuer = IssuerProfile(
            legal_name="Mi Negocio", id_type="01",
            id_number="000000000", email="facturacion@tudominio.com",
            branch_code="101", terminal_code="00001",
        )
        db.add(issuer)
        db.flush()
    return issuer


def _process_sale_lines(
    db: Session,
    sale_id: int,
    items: List[SaleItemCreate],
    validate_price: bool = True,
) -> Decimal:
    """
    Procesa las líneas de una venta: valida producto, stock, precio,
    descuenta stock, crea SaleDetail. Retorna el total.
    """
    total = Decimal("0")

    for item in items:

        # ─── PRODUCTO COMÚN: no toca inventario ───
        if getattr(item, "is_common", False):
            unit_price_dec = Decimal(str(item.unit_price))
            discount_pct = Decimal(str(item.discount_percent or 0))
            qty_dec = Decimal(str(item.quantity))

            # ── FASE 3 — Fix 3.1: Calcular IVA en productos comunes ──
            # Usa la misma función que productos normales para consistencia
            # fiscal. El frontend envía tax_rate (0 si exento, 13 si IVA general).
            tax_rate_pct = normalize_tax_rate(getattr(item, "tax_rate", 0))
            subtotal_base, tax_amount, total_linea = calc_line_tax(
                unit_price=unit_price_dec, quantity=qty_dec,
                discount_percent=discount_pct, tax_rate_pct=tax_rate_pct,
            )
            total += total_linea

            db.add(SaleDetail(
                sale_id=sale_id,
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

        product = (
            _lock_for_update(
                db.query(Product)
                .filter(Product.id == item.product_id)
            )
            .first()
        )
        if not product:
            raise HTTPException(status_code=404, detail=f"Producto ID {item.product_id} no existe.")
        if not product.is_active:
            raise HTTPException(status_code=400, detail=f"El producto '{product.name}' está desactivado.")

        # 📏 Convertir cantidad a Decimal
        qty_dec = Decimal(str(item.quantity))

        # 📏 VALIDACIÓN: productos tipo "Unid" no aceptan fracciones
        if is_unit_based(product.unit_type or "Unid"):
            if qty_dec != qty_dec.to_integral_value():
                raise HTTPException(
                    status_code=400,
                    detail=f"'{product.name}' se vende por unidad. No se permiten fracciones.",
                )

        if product.stock < qty_dec:
            raise HTTPException(status_code=400, detail=f"Stock insuficiente para '{product.name}'.")

        if validate_price:
            # ── FASE 1 — Fix 1.2: Comparación en Decimal, tolerancia relativa ──
            db_price = Decimal(str(product.price or 0))
            sent_price = Decimal(str(item.unit_price or 0))
            if db_price > 0:
                diff = abs(sent_price - db_price)
                # Tolerancia: 1% del precio o ₡1, lo que sea mayor
                tolerance = max(db_price * Decimal("0.01"), Decimal("1"))
                if diff > tolerance:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Precio de '{product.name}' difiere del registrado. Recargue productos.",
                    )

        log_inventory_movement(
            db, product, type=MovementType.venta,
            quantity=qty_dec, reference=f"Venta #{sale_id}",
        )
        product.stock -= qty_dec

        tax_rate_pct = normalize_tax_rate(product.tax_rate)
        unit_price_dec = Decimal(str(item.unit_price))
        discount_pct = Decimal(str(item.discount_percent or 0))

        # 📏 quantity ya es Decimal — no necesita int()
        subtotal_base, tax_amount, total_linea = calc_line_tax(
            unit_price=unit_price_dec, quantity=qty_dec,
            discount_percent=discount_pct, tax_rate_pct=tax_rate_pct,
        )
        total += total_linea

        db.add(SaleDetail(
            sale_id=sale_id, product_id=product.id,
            quantity=qty_dec, unit_price=unit_price_dec,
            discount_percent=discount_pct, subtotal=total_linea,
            tax_rate=tax_rate_pct, tax_amount=tax_amount,
        ))

    return total


def _restore_stock_from_details(db: Session, sale_id: int, reference_prefix: str = "Anulación"):
    """Restaura stock de todas las líneas de una venta (omite productos comunes)."""
    details = db.query(SaleDetail).filter(SaleDetail.sale_id == sale_id).all()
    for d in details:
        # Producto común → no tiene stock que restaurar
        if d.is_common or d.product_id is None:
            continue
        product = (
            _lock_for_update(
                db.query(Product)
                .filter(Product.id == d.product_id)
            )
            .first()
        )
        if product:
            log_inventory_movement(
                db, product, type=MovementType.anulacion,
                quantity=d.quantity, reference=f"{reference_prefix} Venta #{sale_id}",
            )
            product.stock += d.quantity
    return details


def _revert_cash_movement(db: Session, sale: Sale, concept: str, source: str):
    """Si la venta fue en efectivo, registra salida de caja.
    Bug 4.2: usa el cash_session_id de la venta en vez de buscar por fecha."""
    if not is_efectivo(sale.payment_method):
        return
    # Primero intentar la sesión original de la venta
    target_session = (
        db.query(CashSession)
        .filter(CashSession.id == sale.cash_session_id, CashSession.status == "open")
        .first()
    )
    # Si la sesión original ya se cerró, buscar la sesión abierta actual
    # ── FASE 2 — Fix 2.5: Fallback timezone-safe ──
    if not target_session:
        target_session = (
            db.query(CashSession)
            .filter(CashSession.status == "open", CashSession.date == today_cr())
            .first()
        )
    if not target_session:
        # Cruce de medianoche: buscar cualquier sesión abierta
        target_session = (
            db.query(CashSession)
            .filter(CashSession.status == "open")
            .order_by(CashSession.date.desc())
            .first()
        )
    if target_session:
        register_cash_movement(
            db=db, cash_session_id=target_session.id,
            movement_type="OUT", amount=sale.total,
            concept=concept, source=source,
            description=f"{concept} #{sale.id}",
            reference_id=sale.id,
        )
    else:
        # ── FASE 2 — Fix 2.2: No silenciar pérdida contable ──
        logger.warning(
            f"ALERTA CONTABLE: No se pudo registrar salida de caja para "
            f"anulación de venta #{sale.id} (₡{sale.total}). "
            f"No hay sesión de caja abierta. El movimiento debe registrarse manualmente."
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"No hay una sesión de caja abierta para registrar la salida de "
                f"₡{float(sale.total):,.2f} por la anulación. Abra la caja primero."
            ),
        )


def _revert_credit(db: Session, sale: Sale, payment_method_label: str):
    """Si la venta fue a crédito, revierte saldo del cliente."""
    credit_sale = db.query(CreditSale).filter(CreditSale.sale_id == sale.id).first()
    if not credit_sale:
        return
    customer = db.query(Customer).filter(Customer.id == credit_sale.customer_id).first()
    if customer:
        customer.credit_balance = max(
            Decimal("0"), Decimal(str(customer.credit_balance or 0)) - Decimal(str(credit_sale.total_amount))
        )
        db.add(Credit(
            customer_id=credit_sale.customer_id,
            amount=credit_sale.total_amount,
            type="payment", payment_method=payment_method_label,
            description=f"{payment_method_label} Venta #{sale.id} (credit_sale_id:{credit_sale.id})",
        ))


# ═════════════════════════════════════════════════════════════
# Funciones principales de negocio
# ═════════════════════════════════════════════════════════════


def create_sale(db: Session, sale_in: SaleCreate, current_user: User) -> dict:
    """Crea una venta completa: líneas, stock, crédito, factura, caja, PDF."""
    customer_id = sale_in.customer_id
    payment_method = sale_in.payment_method
    document_type = sale_in.document_type or "04"
    details = sale_in.details or []

    if document_type not in ("01", "04"):
        raise HTTPException(status_code=400, detail="document_type inválido. Use '01' o '04'.")
    if not details:
        raise HTTPException(status_code=400, detail="La venta no tiene productos.")

    cash_session = _get_open_cash_session(db)

    new_sale = Sale(
        customer_id=customer_id,
        user_id=current_user.id,
        cash_session_id=cash_session.id,
        total=Decimal("0"),
        payment_method=payment_method,
        document_type=document_type,
        status="ACTIVA",
    )

    # CondicionVenta
    cond_code = (sale_in.condicion_venta_code or "").strip()
    if cond_code:
        if not cond_code.isdigit() or len(cond_code) > 2:
            raise HTTPException(status_code=400, detail="condicion_venta_code inválido.")
        cond_code = cond_code.zfill(2)
        if cond_code not in ("01", "02", "10"):
            raise HTTPException(status_code=400, detail="condicion_venta_code no soportado.")
        new_sale.condicion_venta_code = cond_code

    effective_cond = new_sale.condicion_venta_code or ("02" if is_credit_method(payment_method) else "01")

    if effective_cond in ("02", "10"):
        if not sale_in.credit_days or int(sale_in.credit_days) <= 0:
            raise HTTPException(status_code=400, detail="credit_days obligatorio y > 0 para crédito.")
        new_sale.credit_days = int(sale_in.credit_days)
        if effective_cond == "10" and new_sale.credit_days > 90:
            raise HTTPException(status_code=400, detail="Plazo máximo 90 días para CondicionVenta=10.")

    _is_credit = effective_cond in ("02", "10") or is_credit_method(payment_method)

    db.add(new_sale)
    db.flush()

    # Procesar líneas
    total = _process_sale_lines(db, new_sale.id, details)
    if total <= 0:
        raise HTTPException(status_code=400, detail="Total de venta inválido.")
    new_sale.total = total

    # Crédito
    if _is_credit:
        if not customer_id or customer_id == 1:
            raise HTTPException(status_code=400, detail="No se puede asignar crédito al Cliente General.")
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Cliente no encontrado.")
        add_credit_sale(db, customer_id, new_sale.id)

    # Factura electrónica
    einv = ElectronicInvoice(sale_id=new_sale.id, document_type=document_type, status="PENDING")
    db.add(einv)
    db.flush()

    issuer = _get_or_create_issuer(db)
    branch = (issuer.branch_code or "101").zfill(3)
    terminal = (issuer.terminal_code or "00001").zfill(5)

    seq_num = next_sequence_number(db, branch, terminal, document_type)
    consecutivo = build_consecutivo(branch, terminal, document_type, seq_num)
    clave = build_clave(issuer.id_number, consecutivo, situation="1")
    einv.consecutivo = consecutivo
    einv.clave = clave

    # Caja
    if is_efectivo(payment_method):
        register_cash_movement(
            db=db, cash_session_id=cash_session.id, movement_type="IN",
            amount=total, concept="Venta en efectivo",
            source="SALE_CASH", description=f"Venta #{new_sale.id}",
            reference_id=new_sale.id,
        )

    # ── FASE 5 — Fix 5.1: flush only; router owns commit ──
    db.flush()
    db.refresh(new_sale)

    # ── FASE 4 — Fix 4.3: PDF/Email en background (no bloquea al cajero) ──
    customer_db = db.query(Customer).filter(Customer.id == customer_id).first() if customer_id else None
    customer_name = customer_db.name if customer_db else "Cliente General"

    # Preparar datos del PDF sincrónicamente (necesita DB)
    sale_data = _build_sale_pdf_data(db, new_sale, customer_name, payment_method, document_type, total)
    customer_email = customer_db.email if customer_db else None
    business_name = sale_data.get("business", {}).get("name", "")

    # Lanzar PDF + email en thread de background
    _generate_pdf_and_email_async(sale_data, customer_email, business_name)

    # ── FASE 5 — Fix 5.5: Informar al frontend ──
    result = {
        "message": "Venta registrada correctamente.",
        "sale": {
            "id": new_sale.id, "customer": customer_name,
            "total": _display(total), "payment_method": payment_method,
            "document_type": document_type, "user_id": current_user.id,
            "created_at": new_sale.created_at.isoformat(),
        },
        "pdf_path": None,
        "pdf_note": "El PDF se está generando en segundo plano.",
    }
    return result


def _build_sale_pdf_data(db, sale, customer_name, payment_method, document_type, total):
    """
    FASE 4 — Fix 4.3: Prepara los datos para el PDF de forma síncrona (necesita DB).
    Retorna un dict puro que se puede pasar a un thread sin sesión DB.

    FASE 2 — Fix 2.3: Carga los detalles con query explícita en vez de
    depender del lazy load de sale.details, que podría fallar con
    DetachedInstanceError si la sesión está en un estado inconsistente
    después de flush+refresh (especialmente en SQLite con WAL).
    """
    from app.services.settings_service import get_business_info
    biz = get_business_info(db)

    sale_data = {
        "id": sale.id,
        "customer": {"name": customer_name},
        "details": [],
        "total": float(total),
        "payment_method": payment_method,
        "document_type": document_type,
        "created_at": sale.created_at.strftime("%Y-%m-%d %H:%M"),
        "business": biz,
    }

    # ── FASE 2 — Fix 2.3: Query explícita en vez de lazy load ──
    # sale.details podría no estar cargado si la sesión no hizo
    # eager load. Consultamos directamente para garantizar datos.
    details = db.query(SaleDetail).filter(SaleDetail.sale_id == sale.id).all()

    # ⚡ Prefetch: cargar todos los productos necesarios en UNA sola query
    product_ids = [d.product_id for d in details if d.product_id and not getattr(d, "is_common", False)]
    products_map = {}
    if product_ids:
        products = db.query(Product).filter(Product.id.in_(product_ids)).all()
        products_map = {p.id: p for p in products}

    for d in details:
        _unit_type = "Unid"
        if getattr(d, "is_common", False) or d.product_id is None:
            prod_name = f"📦 {d.common_description or 'Producto común'}"
        else:
            prod = products_map.get(d.product_id)
            prod_name = prod.name if prod else f"Producto #{d.product_id}"
            if prod:
                _unit_type = prod.unit_type or "Unid"

        sale_data["details"].append({
            "product": prod_name,
            "quantity": float(d.quantity), "unit_price": float(d.unit_price),
            "subtotal": float(d.subtotal),
            "tax_rate": float(d.tax_rate or 0), "tax_amount": float(d.tax_amount or 0),
            "unit_type": _unit_type,
        })

    return sale_data


def _run_pdf_and_email(sale_data: dict, customer_email: str | None, business_name: str) -> str | None:
    """
    Genera PDF y envía email. NO necesita sesión DB.
    Retorna path del PDF o None si falla.
    """
    try:
        pdf_path = generate_sale_pdf(sale_data)
        if customer_email:
            send_sale_email(customer_email, pdf_path, sale_data["id"], business_name=business_name)
        return pdf_path
    except Exception as e:
        logger.warning(f"Error PDF/Email: {e}")
        return None


def _generate_pdf_and_email_async(sale_data: dict, customer_email: str | None, business_name: str):
    """
    FASE 4 — Fix 4.3: Lanza PDF + email en un thread de background.
    El cajero recibe la respuesta de la venta inmediatamente sin esperar
    a que ReportLab genere el PDF o que el SMTP responda.
    """
    import threading

    def _worker():
        try:
            _run_pdf_and_email(sale_data, customer_email, business_name)
        except Exception as e:
            logger.error(f"Error en background PDF/Email para venta #{sale_data.get('id')}: {e}")

    t = threading.Thread(target=_worker, daemon=True, name=f"pdf-sale-{sale_data.get('id')}")
    t.start()


def _generate_pdf_and_email(db, sale, customer_db, customer_name, payment_method, document_type, total):
    """Wrapper síncrono para regenerate_sale_pdf y otros flujos que necesitan el path inmediatamente."""
    sale_data = _build_sale_pdf_data(db, sale, customer_name, payment_method, document_type, total)
    customer_email = customer_db.email if customer_db else None
    business_name = sale_data.get("business", {}).get("name", "")
    return _run_pdf_and_email(sale_data, customer_email, business_name)


def list_sales_paginated(
    db: Session,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> PaginatedSalesResponse:
    page = max(1, page)
    page_size = max(1, min(500, page_size))

    # ── FASE 4 — Fix 4.2: Eliminar COUNT(*) en cada petición ──
    # En vez de SELECT COUNT(*) + SELECT datos (2 queries), hacemos
    # una sola query pidiendo page_size + 1 filas. Si llegan más de
    # page_size, sabemos que hay página siguiente (has_next=True).
    base_filter = [Sale.status != "ANULADA"]
    join_needed = False

    if search:
        from app.utils.db_compat import escape_like
        safe = escape_like(search)
        base_filter.append(Customer.name.ilike(f"%{safe}%"))
        join_needed = True

    offset = (page - 1) * page_size

    data_q = db.query(Sale).filter(*base_filter)
    if join_needed:
        data_q = data_q.join(Customer, isouter=True)

    sales = (
        data_q
        .options(joinedload(Sale.customer))
        .order_by(Sale.created_at.desc())
        .offset(offset).limit(page_size + 1)
        .all()
    )

    has_next = len(sales) > page_size
    if has_next:
        sales = sales[:page_size]

    return PaginatedSalesResponse(
        data=[SaleListOut.model_validate(s) for s in sales],
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


def get_sales_by_range(
    db: Session, start: datetime, end: datetime,
    skip: int = 0, limit: int = 500,
    last_id: int | None = None,
) -> list[dict]:
    """
    FASE 4 — Fix 4.3: Keyset pagination.
    Si se pasa last_id, filtra Sale.id < last_id (O(1) seek)
    en vez de OFFSET que degrada con offsets grandes.
    Si no se pasa, mantiene offset/limit por retrocompatibilidad.
    """
    query = (
        db.query(Sale)
        .options(joinedload(Sale.customer))
        .filter(Sale.created_at >= start, Sale.created_at <= end, Sale.status != "ANULADA")
    )

    if last_id is not None:
        query = query.filter(Sale.id < last_id)
    else:
        query = query.offset(skip)

    sales = query.order_by(Sale.id.desc()).limit(limit).all()

    result = []
    for s in sales:
        cname = s.customer.name if s.customer else "Cliente General"
        result.append({
            "id": s.id, "customer": cname,
            "payment_method": s.payment_method or "Efectivo",
            "total": _display(s.total), "status": s.status,
            "user_id": s.user_id,
            "created_at": s.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })
    return result


def get_sale_detail(db: Session, sale_id: int) -> dict:
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Venta no encontrada")

    details = db.query(SaleDetail).filter(SaleDetail.sale_id == sale.id).all()
    return {
        "id": sale.id, "customer_id": sale.customer_id,
        "user_id": sale.user_id, "total": _display(sale.total),
        "payment_method": sale.payment_method, "status": sale.status,
        "created_at": sale.created_at,
        "details": [
            {
                "product_id": d.product_id, "quantity": float(d.quantity),
                "unit_price": _display(d.unit_price), "subtotal": _display(d.subtotal),
                "discount_percent": _display(d.discount_percent or 0),
                "tax_rate": _display(d.tax_rate or 0),
                "tax_amount": _display(d.tax_amount or 0),
                "is_common": bool(d.is_common),
                "common_description": d.common_description,
            }
            for d in details
        ],
    }


def update_sale(db: Session, sale_id: int, sale_in: SaleUpdate, current_user: User) -> dict:
    """Edita líneas de una venta cuya FE esté en PENDING. Requiere admin."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Venta no encontrada.")
    if sale.status == "ANULADA":
        raise HTTPException(status_code=400, detail="No se puede editar una venta anulada.")

    einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.sale_id == sale_id).first()
    if not einv or einv.status != "PENDING":
        raise HTTPException(status_code=400, detail="Solo se pueden editar ventas con FE en estado PENDING.")

    if not sale_in.details:
        raise HTTPException(status_code=400, detail="La venta debe tener al menos un producto.")

    # Restaurar stock viejo (omite productos comunes)
    old_details = db.query(SaleDetail).filter(SaleDetail.sale_id == sale.id).all()
    for d in old_details:
        if d.is_common or d.product_id is None:
            db.delete(d)
            continue
        product = _lock_for_update(db.query(Product).filter(Product.id == d.product_id)).first()
        if product:
            log_inventory_movement(
                db, product, type=MovementType.ajuste,
                quantity=d.quantity, reference=f"Edición Venta #{sale_id} (restaurar)",
            )
            product.stock += d.quantity
        db.delete(d)
    db.flush()

    # Nuevas líneas
    total = _process_sale_lines(db, sale.id, sale_in.details)
    if total <= 0:
        raise HTTPException(status_code=400, detail="Total de venta inválido.")

    old_total = Decimal(str(sale.total or 0))
    new_total = total
    diff = new_total - old_total
    sale.total = new_total

    # Ajustar caja
    if is_efectivo(sale.payment_method) and abs(diff) > Decimal("0.01"):
        # Bug 4.2: usar la sesión de la venta, fallback a la abierta hoy
        # ── FASE 2 — Fix 2.5: Fallback timezone-safe ──
        current_cash = (
            db.query(CashSession)
            .filter(CashSession.id == sale.cash_session_id, CashSession.status == "open")
            .first()
        )
        if not current_cash:
            current_cash = (
                db.query(CashSession)
                .filter(CashSession.status == "open", CashSession.date == today_cr())
                .first()
            )
        if not current_cash:
            # Cruce de medianoche: cualquier sesión abierta
            current_cash = (
                db.query(CashSession)
                .filter(CashSession.status == "open")
                .order_by(CashSession.date.desc())
                .first()
            )
        if current_cash:
            register_cash_movement(
                db=db, cash_session_id=current_cash.id,
                movement_type="IN" if diff > 0 else "OUT", amount=abs(diff),
                concept="Ajuste por edición de venta", source="SALE_EDIT",
                description=f"Edición Venta #{sale_id} (dif: {float(diff):+.2f})",
                reference_id=sale.id,
            )

    # Ajustar crédito
    cs = db.query(CreditSale).filter(CreditSale.sale_id == sale.id).first()
    if cs and abs(diff) > Decimal("0.01"):
        customer = db.query(Customer).filter(Customer.id == cs.customer_id).first()
        if customer:
            # ── FASE 2 — Fix 2.4: Validar que nuevo total no exceda límite de crédito ──
            if diff > 0 and customer.has_credit_limit:
                current_balance = Decimal(str(customer.credit_balance or 0))
                limit_ = Decimal(str(customer.credit_limit or 0))
                if limit_ > 0 and (current_balance + diff) > limit_:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"El nuevo total excede el límite de crédito del cliente. "
                            f"Saldo actual: ₡{float(current_balance):,.2f}, "
                            f"incremento: ₡{float(diff):,.2f}, "
                            f"límite: ₡{float(limit_):,.2f}."
                        ),
                    )
            customer.credit_balance = Decimal(str(customer.credit_balance or 0)) + diff
            cs.total_amount = new_total

    # ── FASE 2 — Fix 2.4: Re-validar credit_days si es venta a crédito ──
    if cs and sale.credit_days:
        if sale.credit_days <= 0:
            raise HTTPException(status_code=400, detail="credit_days debe ser > 0 para ventas a crédito.")
        cond = sale.condicion_venta_code or "02"
        if cond == "10" and sale.credit_days > 90:
            raise HTTPException(status_code=400, detail="credit_days no puede superar 90 para condición 10.")

    # ── FASE 2 — Fix 2.5: Registrar quién editó y cuándo ──
    sale.updated_by = current_user.id
    sale.updated_at = utcnow()
    logger.info(
        f"Venta #{sale_id} editada por usuario #{current_user.id} "
        f"({current_user.username}). Total: {float(old_total)} → {float(new_total)}"
    )

    # ── FASE 5 — Fix 5.1: flush only; router owns commit ──
    db.flush()
    db.refresh(sale)
    return {"message": f"Venta #{sale_id} actualizada.", "sale_id": sale_id, "total": _display(new_total)}


def cancel_sale_with_nc(db: Session, sale_id: int, razon: str = "Anulación de comprobante") -> dict:
    """Anula venta con Nota de Crédito (solo si FE fue ACEPTADA)."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Venta no encontrada.")
    if sale.status == "ANULADA":
        raise HTTPException(status_code=400, detail="Ya fue anulada.")

    original_einv = (
        db.query(ElectronicInvoice)
        .filter(ElectronicInvoice.sale_id == sale_id, ElectronicInvoice.document_type.in_(["01", "04"]))
        .first()
    )
    if not original_einv:
        raise HTTPException(status_code=400, detail="No hay factura electrónica para esta venta.")
    if original_einv.status != "ACCEPTED":
        raise HTTPException(
            status_code=400,
            detail=f"Solo se puede emitir NC sobre facturas ACEPTADAS. Estado: {original_einv.status}",
        )

    _restore_stock_from_details(db, sale_id, "NC")
    _revert_cash_movement(db, sale, "Nota de Crédito (anulación)", "SALE_NC")
    _revert_credit(db, sale, "Nota de Crédito")

    # Generar NC
    issuer = _get_or_create_issuer(db)
    branch = (issuer.branch_code or "101").zfill(3)
    terminal = (issuer.terminal_code or "00001").zfill(5)

    seq_num = next_sequence_number(db, branch, terminal, "03")
    consecutivo = build_consecutivo(branch, terminal, "03", seq_num)
    clave = build_clave(issuer.id_number, consecutivo, situation="1")

    nc_einv = ElectronicInvoice(
        sale_id=sale.id, document_type="03", status="PENDING",
        consecutivo=consecutivo, clave=clave,
    )
    db.add(nc_einv)

    sale.status = "ANULADA"
    # ── FASE 5 — Fix 5.1: flush only; router owns commit ──
    db.flush()

    return {
        "message": f"Nota de Crédito generada para Venta #{sale_id}.",
        "sale_id": sale_id, "status": "ANULADA",
        "nc": {"document_type": "03", "clave": clave, "consecutivo": consecutivo, "status": "PENDING"},
    }


def void_sale_simple(db: Session, sale_id: int) -> dict:
    """Soft-delete sin NC (solo si FE no fue ACEPTADA)."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    if sale.status == "ANULADA":
        raise HTTPException(status_code=400, detail="Ya fue anulada.")

    einv = (
        db.query(ElectronicInvoice)
        .filter(ElectronicInvoice.sale_id == sale_id, ElectronicInvoice.document_type.in_(["01", "04"]))
        .first()
    )
    if einv and einv.status == "ACCEPTED":
        raise HTTPException(
            status_code=400,
            detail="Factura aceptada por Hacienda. Use POST /sales/{id}/cancel para NC.",
        )

    _restore_stock_from_details(db, sale_id, "Anulación")
    _revert_cash_movement(db, sale, "Anulación de venta en efectivo", "SALE_VOID")
    _revert_credit(db, sale, "Anulación")

    sale.status = "ANULADA"
    # ── FASE 5 — Fix 5.1: flush only; router owns commit ──
    db.flush()

    return {"message": f"Venta #{sale_id} anulada.", "sale_id": sale_id, "status": "ANULADA"}


# ═══════════════════════════════════════════════════
# Regenerar PDF de una venta existente
# ═══════════════════════════════════════════════════
def regenerate_sale_pdf(db: Session, sale_id: int) -> dict:
    """Regenera el PDF de una venta existente."""
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail=f"Venta #{sale_id} no encontrada.")

    customer_db = db.query(Customer).filter(Customer.id == sale.customer_id).first() if sale.customer_id else None
    customer_name = customer_db.name if customer_db else "Cliente general"

    pdf_path = _generate_pdf_and_email(
        db, sale, customer_db, customer_name,
        sale.payment_method, sale.document_type, sale.total,
    )

    if not pdf_path:
        raise HTTPException(status_code=500, detail="No se pudo generar el PDF.")

    return {"message": "PDF regenerado", "pdf_path": pdf_path}