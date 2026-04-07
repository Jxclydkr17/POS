from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.db.models.cash_session import CashSession
from app.db.models.cash_movement import CashMovement
from app.services.expense_service import add_expense_service

from app.db.models.sale import Sale
from app.db.models.customer import Customer
from app.constants.payment_methods import ALL_PAYMENT_METHODS
from app.utils.dt import utcnow, today_cr
from app.services.settings_service import get_business_name


# ── Helper: convierte cualquier valor numérico a Decimal de forma segura ──
def _to_dec(value) -> Decimal:
    """Convierte float/int/str/Decimal a Decimal sin pérdida IEEE 754."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


# ==========================================================
# 🟦 Obtener sesión de caja del día
# ==========================================================
def get_today_session(db: Session) -> CashSession | None:
    today = today_cr()
    return db.query(CashSession).filter(CashSession.date == today).first()


# ==========================================================
# 🟩 Obtener sesión abierta
# ==========================================================
def get_open_session(db: Session) -> CashSession | None:
    today = today_cr()
    return (
        db.query(CashSession)
        .filter(
            CashSession.date == today,
            CashSession.status == "open"
        )
        .first()
    )


# ==========================================================
# 🟩 Abrir caja
# ==========================================================
def open_session(db: Session, opening_amount: float) -> CashSession:
    today = today_cr()
    session = get_today_session(db)

    if session:
        if session.status == "open":
            return session
        raise ValueError("La caja de hoy ya fue cerrada.")

    # ── FASE 1: Decimal para almacenamiento ──
    session = CashSession(
        date=today,
        opening_amount=_to_dec(opening_amount),
        status="open",
        created_at=utcnow()
    )

    db.add(session)
    db.commit()
    db.refresh(session)
    return session


# ==========================================================
# 🟨 Agregar movimiento de caja
# ==========================================================
def add_movement(db: Session, cash_session_id: int, data) -> CashMovement:
    # ── FASE 1: Decimal para almacenamiento ──
    amount_dec = _to_dec(data.amount)

    movement = CashMovement(
        cash_session_id=cash_session_id,   
        type=data.type.lower(),             
        concept=data.concept,
        amount=amount_dec,
        source=data.source or "MANUAL",     
        description=data.concept,
        created_at=utcnow()
    )

    db.add(movement)

    # 🔥 Si es salida y se pidió crear gasto
    if data.type.lower() == "out" and data.create_expense:
        expense_payload = {
            "category": data.expense_category or "Gastos de caja",
            "description": data.concept,
            "amount": float(amount_dec),  # expense_service aún usa float
            "payment_method": "Efectivo",
            "date": today_cr().strftime("%Y-%m-%d"),
        }
        add_expense_service(expense_payload, db)

    db.commit()
    db.refresh(movement)
    return movement


# ==========================================================
# 🟪 Reporte completo del día (LECTURA)
# ==========================================================
def get_cash_report(db: Session, report_date: date) -> dict:
    """
    Genera el reporte completo del día, independientemente del estado de la caja.
    Funciona tanto para cajas abiertas como cerradas.
    Incluye ventas y movimientos para evitar múltiples llamadas HTTP.
    """
    session = db.query(CashSession).filter(CashSession.date == report_date).first()
    if not session:
        return {}

    start = datetime.combine(report_date, datetime.min.time())
    end = start + timedelta(days=1)

    # FIX #8: Obtener solo ventas ACTIVAS (excluir anuladas)
    sales = (
        db.query(Sale)
        .filter(
            Sale.created_at >= start,
            Sale.created_at < end,
            Sale.status != "ANULADA",
        )
        .all()
    )

    # ── FASE 1: Aritmética en Decimal ──
    total_sales = sum((_to_dec(s.total) for s in sales), Decimal("0"))

    # Desglose por método de pago
    payment_breakdown = {}
    for method in ALL_PAYMENT_METHODS:
        method_total = sum(
            (_to_dec(s.total) for s in sales if s.payment_method == method),
            Decimal("0"),
        )
        if method_total > 0:  # Solo incluir métodos con ventas
            payment_breakdown[method] = float(method_total)

    # Obtener movimientos de caja
    movements = (
        db.query(CashMovement)
        .filter(CashMovement.cash_session_id == session.id)
        .order_by(CashMovement.created_at.desc())
        .all()
    )

    # Calcular entradas y salidas en Decimal
    total_in = sum(
        (_to_dec(m.amount) for m in movements if m.type == "in"),
        Decimal("0"),
    )
    
    total_out = sum(
        (_to_dec(m.amount) for m in movements if m.type == "out"),
        Decimal("0"),
    )

    # 🔥 CÁLCULO CORRECTO DEL ESPERADO
    # Esperado = Apertura + Entradas - Salidas
    # NO sumamos total_sales porque las ventas en efectivo ya están en "Entradas"
    # Las ventas con otros métodos (Tarjeta, Crédito, SINPE) no entran a la caja física
    expected_closing = _to_dec(session.opening_amount) + total_in - total_out

    # Si la caja está cerrada, usar los valores registrados
    # Si está abierta, calcular en tiempo real
    if session.status == "closed":
        closing_amount = _to_dec(session.closing_amount)
        difference = _to_dec(session.difference)
        status = "closed"
    else:
        closing_amount = Decimal("0")
        difference = Decimal("0")
        status = "open"

    # ─────────────────────────────────────────────────────────
    # FIX #9: Incluir ventas y movimientos en la respuesta
    # para evitar 3 llamadas HTTP separadas desde la UI
    # ─────────────────────────────────────────────────────────
    sales_list = []
    for s in sales:
        cname = "Cliente General"
        if s.customer_id:
            c = db.query(Customer).filter(Customer.id == s.customer_id).first()
            if c:
                cname = c.name
        sales_list.append({
            "id": s.id,
            "customer": cname,
            "payment_method": s.payment_method or "Efectivo",
            "total": float(_to_dec(s.total)),
            "status": s.status,
            "created_at": s.created_at.strftime("%Y-%m-%d %H:%M:%S") if s.created_at else "",
        })

    movements_list = [
        {
            "type": "Entrada" if m.type == "in" else "Salida",
            "amount": float(_to_dec(m.amount)),
            "description": m.description or "",
            "source": m.source,
            "time": m.created_at.strftime("%H:%M:%S") if m.created_at else "N/A",
        }
        for m in movements
    ]

    # FIX 2.1: Nombre de empresa desde la tabla settings (DB),
    # reemplaza el legacy load_settings() de app/config/settings.py
    empresa_nombre = get_business_name(db)

    # ── FASE 1: float() solo aquí, al construir el JSON de respuesta ──
    return {
        "date": str(report_date),
        "status": status,
        "opening_amount": float(_to_dec(session.opening_amount)),
        "entries": float(total_in),
        "exits": float(total_out),
        "total_sales": float(total_sales),
        "expected": float(expected_closing),
        "expected_closing": float(expected_closing),  # Mantener compatibilidad
        "closing_amount": float(closing_amount),
        "difference": float(difference),
        "payment_breakdown": payment_breakdown,
        "sales": sales_list,               # FIX #9: nuevo
        "movements": movements_list,       # FIX #9: nuevo
        "empresa_nombre": empresa_nombre,  # FIX #19: nuevo
    }