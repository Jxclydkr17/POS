# app/ai/data_queries.py
"""
FASE 1 — Consultas de datos reales desde el chat.
Módulos que consultan la BD y devuelven datos formateados.
Cubre: ventas, gastos, caja, inventario, clientes, compras y financiero.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from app.utils.dt import today_cr
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, case, desc
from sqlalchemy.orm import Session

from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
from app.db.models.product import Product
from app.db.models.expense import Expense
from app.db.models.customer import Customer
from app.db.models.cash_session import CashSession
from app.db.models.cash_movement import CashMovement
from app.db.models.purchase import Purchase, PurchaseStatus
from app.db.models.purchase_detail import PurchaseDetail
from app.db.models.credit import Credit
from app.db.models.credit_sale import CreditSale
from app.db.models.supplier import Supplier
from app.db.models.supplier_product import SupplierProduct

from app.utils.unit_helpers import format_quantity


# ─────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────

def _f(val) -> float:
    """Safe float conversion."""
    if val is None:
        return 0.0
    return round(float(val), 2)


def _fmt(val) -> str:
    """Format as CRC currency."""
    return f"₡{_f(val):,.2f}"


def _pct(val) -> str:
    return f"{_f(val):.1f}%"


def _period_range(period: str) -> tuple[date, date]:
    """Returns (start_date, end_date) for common periods."""
    today = today_cr()
    if period == "today":
        return today, today
    elif period == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    elif period == "week":
        start = today - timedelta(days=today.weekday())  # lunes
        return start, today
    elif period == "month":
        return today.replace(day=1), today
    elif period == "last_month":
        first_this = today.replace(day=1)
        last_day_prev = first_this - timedelta(days=1)
        first_prev = last_day_prev.replace(day=1)
        return first_prev, last_day_prev
    elif period == "year":
        return today.replace(month=1, day=1), today
    return today, today


def _dt_range(start_d: date, end_d: date) -> tuple[datetime, datetime]:
    return datetime.combine(start_d, time.min), datetime.combine(end_d, time.max)


def _period_label(period: str) -> str:
    labels = {
        "today": "hoy",
        "yesterday": "ayer",
        "week": "esta semana",
        "month": "este mes",
        "last_month": "el mes pasado",
        "year": "este año",
    }
    return labels.get(period, period)


# ═════════════════════════════════════════════════════
# 1) VENTAS
# ═════════════════════════════════════════════════════

def query_sales_summary(db: Session, period: str = "today") -> dict:
    """
    Resumen de ventas para un periodo.
    Retorna dict con reply_text y data.
    """
    start_d, end_d = _period_range(period)
    start_dt, end_dt = _dt_range(start_d, end_d)
    label = _period_label(period)

    # Total y conteo (excluir ANULADAS)
    result = (
        db.query(
            func.coalesce(func.sum(Sale.total), 0),
            func.count(Sale.id),
        )
        .filter(
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            Sale.status != "ANULADA",
        )
        .first()
    )
    total = _f(result[0])
    count = int(result[1] or 0)

    # Desglose por método de pago
    payment_rows = (
        db.query(
            Sale.payment_method,
            func.sum(Sale.total),
            func.count(Sale.id),
        )
        .filter(
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            Sale.status != "ANULADA",
        )
        .group_by(Sale.payment_method)
        .all()
    )
    breakdown = []
    for pm, pm_total, pm_count in payment_rows:
        pm_name = (pm or "Otro").strip()
        breakdown.append(f"  • {pm_name}: {_fmt(pm_total)} ({pm_count})")

    # Ticket promedio
    avg_ticket = total / count if count > 0 else 0

    # Comparar con periodo anterior (solo para today)
    compare_text = ""
    if period == "today":
        yesterday = today_cr() - timedelta(days=1)
        y_start, y_end = _dt_range(yesterday, yesterday)
        y_result = (
            db.query(func.coalesce(func.sum(Sale.total), 0))
            .filter(
                Sale.created_at >= y_start,
                Sale.created_at <= y_end,
                Sale.status != "ANULADA",
            )
            .scalar()
        )
        y_total = _f(y_result)
        if y_total > 0:
            diff_pct = ((total - y_total) / y_total) * 100
            arrow = "📈" if diff_pct >= 0 else "📉"
            compare_text = f"\n{arrow} vs ayer ({_fmt(y_total)}): {'+' if diff_pct >= 0 else ''}{diff_pct:.1f}%"

    # Construir respuesta
    if count == 0:
        reply = f"No hay ventas registradas {label}."
    else:
        lines = [
            f"💰 **Ventas {label}:** {_fmt(total)} en **{count}** transacciones.",
            f"🧾 Ticket promedio: {_fmt(avg_ticket)}",
        ]
        if breakdown:
            lines.append("💳 Desglose:")
            lines.extend(breakdown)
        if compare_text:
            lines.append(compare_text)
        reply = "\n".join(lines)

    return {
        "reply_text": reply,
        "data": {
            "total": total,
            "count": count,
            "avg_ticket": avg_ticket,
            "period": period,
        }
    }


def query_top_products_sold(db: Session, period: str = "today", limit: int = 5) -> dict:
    """Productos más vendidos en un periodo."""
    start_d, end_d = _period_range(period)
    start_dt, end_dt = _dt_range(start_d, end_d)
    label = _period_label(period)

    rows = (
        db.query(
            Product.name,
            func.sum(SaleDetail.quantity).label("qty"),
            func.sum(SaleDetail.subtotal).label("revenue"),
            Product.unit_type,
        )
        .join(SaleDetail, SaleDetail.product_id == Product.id)
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .filter(
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            Sale.status != "ANULADA",
        )
        .group_by(Product.id, Product.name, Product.unit_type)
        .order_by(desc("revenue"))
        .limit(limit)
        .all()
    )

    if not rows:
        return {"reply_text": f"No hay datos de productos vendidos {label}.", "data": {}}

    lines = [f"🏆 **Top {len(rows)} productos {label}:**"]
    for i, (name, qty, revenue, unit_type) in enumerate(rows, 1):
        qty_display = format_quantity(float(qty), unit_type or "Unid")
        lines.append(f"  {i}. {name} — {qty_display} — {_fmt(revenue)}")

    return {"reply_text": "\n".join(lines), "data": {"rows": [(r[0], float(r[1]), _f(r[2])) for r in rows]}}


# ═════════════════════════════════════════════════════
# 2) GASTOS
# ═════════════════════════════════════════════════════

def query_expenses_summary(db: Session, period: str = "today") -> dict:
    """Resumen de gastos para un periodo."""
    start_d, end_d = _period_range(period)
    start_dt, end_dt = _dt_range(start_d, end_d)
    label = _period_label(period)

    result = (
        db.query(
            func.coalesce(func.sum(Expense.amount), 0),
            func.count(Expense.id),
        )
        .filter(
            Expense.date >= start_dt,
            Expense.date <= end_dt,
        )
        .first()
    )
    total = _f(result[0])
    count = int(result[1] or 0)

    # Desglose por categoría
    cat_rows = (
        db.query(
            Expense.category,
            func.sum(Expense.amount),
            func.count(Expense.id),
        )
        .filter(
            Expense.date >= start_dt,
            Expense.date <= end_dt,
        )
        .group_by(Expense.category)
        .order_by(desc(func.sum(Expense.amount)))
        .limit(8)
        .all()
    )

    if count == 0:
        return {"reply_text": f"No hay gastos registrados {label}.", "data": {}}

    lines = [f"📤 **Gastos {label}:** {_fmt(total)} en **{count}** registros."]
    if cat_rows:
        lines.append("📊 Por categoría:")
        for cat, cat_total, cat_count in cat_rows:
            lines.append(f"  • {cat or 'Sin categoría'}: {_fmt(cat_total)} ({cat_count})")

    return {
        "reply_text": "\n".join(lines),
        "data": {"total": total, "count": count}
    }


# ═════════════════════════════════════════════════════
# 3) CAJA
# ═════════════════════════════════════════════════════

def query_cash_status(db: Session) -> dict:
    """Estado actual de la caja."""
    today = today_cr()
    session = (
        db.query(CashSession)
        .filter(CashSession.date == today)
        .first()
    )

    if not session:
        return {"reply_text": "⚠️ No hay caja abierta hoy. Necesitás abrir caja primero.", "data": {}}

    opening = _f(session.opening_amount)

    # Movimientos
    movements = (
        db.query(CashMovement)
        .filter(CashMovement.cash_session_id == session.id)
        .all()
    )
    total_in = sum(_f(m.amount) for m in movements if m.type == "in")
    total_out = sum(_f(m.amount) for m in movements if m.type == "out")
    expected = opening + total_in - total_out

    status_emoji = "🟢" if session.status == "open" else "🔴"
    status_text = "Abierta" if session.status == "open" else "Cerrada"

    lines = [
        f"🏦 **Caja de hoy** — {status_emoji} {status_text}",
        f"💵 Apertura: {_fmt(opening)}",
        f"📥 Entradas: {_fmt(total_in)}",
        f"📤 Salidas: {_fmt(total_out)}",
        f"💰 **Saldo esperado: {_fmt(expected)}**",
    ]

    if session.status == "closed":
        closing = _f(session.closing_amount)
        diff = _f(session.difference)
        lines.append(f"🔒 Cierre real: {_fmt(closing)}")
        if diff != 0:
            emoji = "⚠️" if diff < 0 else "✅"
            lines.append(f"{emoji} Diferencia: {_fmt(diff)}")

    return {
        "reply_text": "\n".join(lines),
        "data": {
            "status": session.status,
            "opening": opening,
            "entries": total_in,
            "exits": total_out,
            "expected": expected,
        }
    }


# ═════════════════════════════════════════════════════
# 4) INVENTARIO
# ═════════════════════════════════════════════════════

def query_inventory_summary(db: Session) -> dict:
    """Resumen general de inventario."""
    total_products = (
        db.query(func.count(Product.id))
        .filter(Product.is_active == True)
        .scalar()
    ) or 0

    total_stock = (
        db.query(func.coalesce(func.sum(Product.stock), 0))
        .filter(Product.is_active == True)
        .scalar()
    ) or 0

    # Valor del inventario (stock × cost)
    inventory_value = (
        db.query(
            func.coalesce(
                func.sum(Product.stock * func.coalesce(Product.cost, 0)),
                0
            )
        )
        .filter(Product.is_active == True, Product.stock > 0)
        .scalar()
    ) or 0

    # Valor a precio de venta
    retail_value = (
        db.query(
            func.coalesce(
                func.sum(Product.stock * Product.price),
                0
            )
        )
        .filter(Product.is_active == True, Product.stock > 0)
        .scalar()
    ) or 0

    # Sin stock
    out_of_stock = (
        db.query(func.count(Product.id))
        .filter(Product.is_active == True, Product.stock <= 0)
        .scalar()
    ) or 0

    # Stock bajo (stock <= min_stock y > 0)
    low_stock = (
        db.query(func.count(Product.id))
        .filter(
            Product.is_active == True,
            Product.stock > 0,
            Product.stock <= Product.min_stock,
        )
        .scalar()
    ) or 0

    lines = [
        f"📦 **Resumen de inventario:**",
        f"  • Productos activos: **{total_products}**",
        f"  • Total en stock: **{float(total_stock):,.2f}** (unidades/kg/m mixto)",
        f"  • Valor al costo: {_fmt(inventory_value)}",
        f"  • Valor a precio venta: {_fmt(retail_value)}",
    ]

    alerts = []
    if out_of_stock > 0:
        alerts.append(f"❌ **{out_of_stock}** sin stock")
    if low_stock > 0:
        alerts.append(f"⚠️ **{low_stock}** con stock bajo")
    if alerts:
        lines.append("🚨 Alertas: " + " | ".join(alerts))

    return {
        "reply_text": "\n".join(lines),
        "data": {
            "total_products": total_products,
            "total_stock": float(total_stock),
            "inventory_value": _f(inventory_value),
            "retail_value": _f(retail_value),
            "out_of_stock": out_of_stock,
            "low_stock": low_stock,
        }
    }


def query_low_stock_products(db: Session, limit: int = 10) -> dict:
    """Productos con stock crítico."""
    products = (
        db.query(Product)
        .filter(
            Product.is_active == True,
            Product.stock <= Product.min_stock,
        )
        .order_by(Product.stock.asc())
        .limit(limit)
        .all()
    )

    if not products:
        return {"reply_text": "✅ No hay productos con stock crítico. ¡Todo bien!", "data": {}}

    lines = [f"🚨 **{len(products)} productos con stock crítico:**"]
    for p in products:
        stock_emoji = "❌" if p.stock <= 0 else "⚠️"
        stock_display = format_quantity(float(p.stock), p.unit_type or "Unid")
        min_display = format_quantity(float(p.min_stock), p.unit_type or "Unid")
        lines.append(f"  {stock_emoji} {p.name} — stock: **{stock_display}** (mín: {min_display})")

    return {"reply_text": "\n".join(lines), "data": {"count": len(products)}}


# ═════════════════════════════════════════════════════
# 5) CLIENTES
# ═════════════════════════════════════════════════════

def query_customers_summary(db: Session) -> dict:
    """Resumen general de clientes."""
    total = (
        db.query(func.count(Customer.id))
        .filter(Customer.is_active == True)
        .scalar()
    ) or 0

    with_debt = (
        db.query(func.count(Customer.id))
        .filter(Customer.is_active == True, Customer.credit_balance > 0)
        .scalar()
    ) or 0

    total_debt = (
        db.query(func.coalesce(func.sum(Customer.credit_balance), 0))
        .filter(Customer.is_active == True, Customer.credit_balance > 0)
        .scalar()
    ) or 0

    lines = [
        f"👥 **Resumen de clientes:**",
        f"  • Total activos: **{total}**",
        f"  • Con saldo pendiente: **{with_debt}**",
        f"  • Deuda total: **{_fmt(total_debt)}**",
    ]

    return {
        "reply_text": "\n".join(lines),
        "data": {
            "total": total,
            "with_debt": with_debt,
            "total_debt": _f(total_debt),
        }
    }


def query_top_debtors(db: Session, limit: int = 5) -> dict:
    """Clientes con mayor deuda."""
    customers = (
        db.query(Customer)
        .filter(Customer.is_active == True, Customer.credit_balance > 0)
        .order_by(desc(Customer.credit_balance))
        .limit(limit)
        .all()
    )

    if not customers:
        return {"reply_text": "✅ No hay clientes con saldo pendiente.", "data": {}}

    total = sum(_f(c.credit_balance) for c in customers)
    lines = [f"💳 **Top {len(customers)} deudores** (total: {_fmt(total)}):"]
    for i, c in enumerate(customers, 1):
        lines.append(f"  {i}. {c.name} — **{_fmt(c.credit_balance)}**")

    return {"reply_text": "\n".join(lines), "data": {"count": len(customers), "total": _f(total)}}


def query_top_customers_by_sales(db: Session, period: str = "month", limit: int = 5) -> dict:
    """Mejores clientes por volumen de compra."""
    start_d, end_d = _period_range(period)
    start_dt, end_dt = _dt_range(start_d, end_d)
    label = _period_label(period)

    rows = (
        db.query(
            Customer.name,
            func.sum(Sale.total).label("total"),
            func.count(Sale.id).label("count"),
        )
        .join(Sale, Sale.customer_id == Customer.id)
        .filter(
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            Sale.status != "ANULADA",
        )
        .group_by(Customer.id, Customer.name)
        .order_by(desc("total"))
        .limit(limit)
        .all()
    )

    if not rows:
        return {"reply_text": f"No hay ventas con cliente asignado {label}.", "data": {}}

    lines = [f"🏅 **Mejores clientes {label}:**"]
    for i, (name, total, count) in enumerate(rows, 1):
        lines.append(f"  {i}. {name} — {_fmt(total)} ({int(count)} compras)")

    return {"reply_text": "\n".join(lines), "data": {}}


# ═════════════════════════════════════════════════════
# 6) COMPRAS / PROVEEDORES
# ═════════════════════════════════════════════════════

def query_purchases_summary(db: Session, period: str = "month") -> dict:
    """Resumen de compras a proveedores."""
    start_d, end_d = _period_range(period)
    label = _period_label(period)

    result = (
        db.query(
            func.coalesce(func.sum(Purchase.amount), 0),
            func.count(Purchase.id),
        )
        .filter(
            Purchase.entry_date >= start_d,
            Purchase.entry_date <= end_d,
        )
        .first()
    )
    total = _f(result[0])
    count = int(result[1] or 0)

    # Pendientes de pago (todas las fechas)
    pending = (
        db.query(
            func.coalesce(func.sum(Purchase.amount), 0),
            func.count(Purchase.id),
        )
        .filter(Purchase.status.in_([PurchaseStatus.pendiente, PurchaseStatus.parcial]))
        .first()
    )
    pending_total = _f(pending[0])
    pending_count = int(pending[1] or 0)

    # Vencidas
    overdue = (
        db.query(func.count(Purchase.id))
        .filter(
            Purchase.status.in_([PurchaseStatus.pendiente, PurchaseStatus.parcial]),
            Purchase.due_date < today_cr(),
        )
        .scalar()
    ) or 0

    lines = [
        f"🛒 **Compras {label}:** {_fmt(total)} en **{count}** facturas.",
    ]

    if pending_count > 0:
        lines.append(f"⏳ Pendientes de pago: **{pending_count}** por {_fmt(pending_total)}")
    else:
        lines.append("✅ Sin facturas pendientes de pago.")

    if overdue > 0:
        lines.append(f"🔴 **{overdue}** factura(s) vencida(s)")

    return {
        "reply_text": "\n".join(lines),
        "data": {
            "total": total,
            "count": count,
            "pending_total": pending_total,
            "pending_count": pending_count,
            "overdue": overdue,
        }
    }


def query_supplier_debt(db: Session, limit: int = 5) -> dict:
    """Deuda por proveedor."""
    rows = (
        db.query(
            Supplier.name,
            func.sum(Purchase.amount).label("total_amount"),
            func.count(Purchase.id).label("invoice_count"),
        )
        .join(Supplier, Purchase.supplier_id == Supplier.id)
        .filter(Purchase.status.in_([PurchaseStatus.pendiente, PurchaseStatus.parcial]))
        .group_by(Supplier.id, Supplier.name)
        .order_by(desc("total_amount"))
        .limit(limit)
        .all()
    )

    if not rows:
        return {"reply_text": "✅ No hay deudas pendientes con proveedores.", "data": {}}

    total = sum(_f(r[1]) for r in rows)
    lines = [f"🏭 **Deuda con proveedores** (total: {_fmt(total)}):"]
    for i, (name, amount, inv_count) in enumerate(rows, 1):
        lines.append(f"  {i}. {name} — {_fmt(amount)} ({int(inv_count)} facturas)")

    return {"reply_text": "\n".join(lines), "data": {"total": _f(total)}}


# ═════════════════════════════════════════════════════
# 7) FINANCIERO / GANANCIAS
# ═════════════════════════════════════════════════════

def query_profit_summary(db: Session, period: str = "month") -> dict:
    """Resumen de rentabilidad."""
    start_d, end_d = _period_range(period)
    start_dt, end_dt = _dt_range(start_d, end_d)
    label = _period_label(period)

    # Ventas activas
    sales = (
        db.query(Sale)
        .filter(
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            Sale.status != "ANULADA",
        )
        .all()
    )
    total_sales = sum(float(s.total) for s in sales)
    sale_ids = [s.id for s in sales]

    # COGS
    total_cogs = 0.0
    if sale_ids:
        cogs_result = (
            db.query(
                func.sum(SaleDetail.quantity * func.coalesce(Product.cost, 0))
            )
            .join(Product, SaleDetail.product_id == Product.id)
            .filter(SaleDetail.sale_id.in_(sale_ids))
            .scalar()
        )
        total_cogs = _f(cogs_result)

    gross_profit = total_sales - total_cogs
    gross_margin = (gross_profit / total_sales * 100) if total_sales > 0 else 0

    # Gastos del periodo
    total_expenses = _f(
        db.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.date >= start_dt, Expense.date <= end_dt)
        .scalar()
    )

    net_profit = gross_profit - total_expenses
    net_margin = (net_profit / total_sales * 100) if total_sales > 0 else 0

    # IVA recaudado
    total_tax = 0.0
    if sale_ids:
        total_tax = _f(
            db.query(func.sum(func.coalesce(SaleDetail.tax_amount, 0)))
            .filter(SaleDetail.sale_id.in_(sale_ids))
            .scalar()
        )

    if total_sales == 0:
        return {"reply_text": f"No hay ventas {label} para calcular rentabilidad.", "data": {}}

    net_emoji = "📈" if net_profit >= 0 else "📉"

    lines = [
        f"📊 **Reporte financiero {label}:**",
        f"  💰 Ventas: {_fmt(total_sales)}",
        f"  📦 Costo de lo vendido: {_fmt(total_cogs)}",
        f"  📈 Ganancia bruta: {_fmt(gross_profit)} ({_pct(gross_margin)} margen)",
        f"  📤 Gastos operativos: {_fmt(total_expenses)}",
        f"  {net_emoji} **Ganancia neta: {_fmt(net_profit)}** ({_pct(net_margin)} margen)",
    ]

    if total_tax > 0:
        lines.append(f"  🧾 IVA recaudado: {_fmt(total_tax)}")

    return {
        "reply_text": "\n".join(lines),
        "data": {
            "total_sales": total_sales,
            "total_cogs": total_cogs,
            "gross_profit": gross_profit,
            "gross_margin": gross_margin,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
            "net_margin": net_margin,
            "total_tax": total_tax,
        }
    }


# ═════════════════════════════════════════════════════
# 8) RESUMEN RÁPIDO DEL DÍA (combo)
# ═════════════════════════════════════════════════════

def query_daily_overview(db: Session) -> dict:
    """Vista rápida del día: ventas, gastos, caja, alertas."""
    today = today_cr()
    start_dt, end_dt = _dt_range(today, today)

    # Ventas hoy
    sales_result = (
        db.query(
            func.coalesce(func.sum(Sale.total), 0),
            func.count(Sale.id),
        )
        .filter(
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            Sale.status != "ANULADA",
        )
        .first()
    )
    sales_total = _f(sales_result[0])
    sales_count = int(sales_result[1] or 0)

    # Gastos hoy
    expenses_total = _f(
        db.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.date >= start_dt, Expense.date <= end_dt)
        .scalar()
    )

    # Caja
    cash_session = db.query(CashSession).filter(CashSession.date == today).first()
    cash_status = "Sin abrir"
    if cash_session:
        cash_status = "Abierta" if cash_session.status == "open" else "Cerrada"

    # Stock crítico
    critical_stock = (
        db.query(func.count(Product.id))
        .filter(Product.is_active == True, Product.stock <= 0)
        .scalar()
    ) or 0

    # Créditos pendientes
    total_debt = _f(
        db.query(func.coalesce(func.sum(Customer.credit_balance), 0))
        .filter(Customer.credit_balance > 0)
        .scalar()
    )

    lines = [
        f"📋 **Resumen del día ({today.strftime('%d/%m/%Y')}):**",
        f"  💰 Ventas: {_fmt(sales_total)} ({sales_count} transacciones)",
        f"  📤 Gastos: {_fmt(expenses_total)}",
        f"  🏦 Caja: {cash_status}",
    ]

    if critical_stock > 0:
        lines.append(f"  ❌ Productos sin stock: {critical_stock}")
    if total_debt > 0:
        lines.append(f"  💳 Crédito pendiente total: {_fmt(total_debt)}")

    balance = sales_total - expenses_total
    balance_emoji = "✅" if balance >= 0 else "⚠️"
    lines.append(f"  {balance_emoji} **Balance del día: {_fmt(balance)}**")

    return {
        "reply_text": "\n".join(lines),
        "data": {
            "sales_total": sales_total,
            "sales_count": sales_count,
            "expenses_total": expenses_total,
            "cash_status": cash_status,
            "critical_stock": critical_stock,
            "total_debt": total_debt,
        }
    }


# ═════════════════════════════════════════════════════
# 9) RESUMEN POR PERIODO (semana / mes / año)
# ═════════════════════════════════════════════════════

def query_period_overview(db: Session, period: str = "week") -> dict:
    """
    Resumen general para un periodo: ventas, gastos, utilidad,
    top productos vendidos y créditos pendientes.
    Se usa cuando el usuario pide "resumen del mes", "resumen de la semana", etc.
    """
    start_d, end_d = _period_range(period)
    start_dt, end_dt = _dt_range(start_d, end_d)
    label = _period_label(period)

    # ── Ventas ──
    sales_result = (
        db.query(
            func.coalesce(func.sum(Sale.total), 0),
            func.count(Sale.id),
        )
        .filter(
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            Sale.status != "ANULADA",
        )
        .first()
    )
    sales_total = _f(sales_result[0])
    sales_count = int(sales_result[1] or 0)

    # Ticket promedio
    avg_ticket = sales_total / sales_count if sales_count > 0 else 0

    # ── Gastos ──
    expenses_total = _f(
        db.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.date >= start_dt, Expense.date <= end_dt)
        .scalar()
    )

    # ── Utilidad bruta ──
    profit = sales_total - expenses_total

    # ── Top 5 productos vendidos ──
    top_products = (
        db.query(
            Product.name,
            func.sum(SaleDetail.quantity).label("qty"),
            func.sum(SaleDetail.subtotal).label("revenue"),
            Product.unit_type,
        )
        .join(SaleDetail, SaleDetail.product_id == Product.id)
        .join(Sale, Sale.id == SaleDetail.sale_id)
        .filter(
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            Sale.status != "ANULADA",
        )
        .group_by(Product.id, Product.name, Product.unit_type)
        .order_by(desc("revenue"))
        .limit(5)
        .all()
    )

    # ── Desglose por método de pago ──
    payment_rows = (
        db.query(
            Sale.payment_method,
            func.sum(Sale.total),
            func.count(Sale.id),
        )
        .filter(
            Sale.created_at >= start_dt,
            Sale.created_at <= end_dt,
            Sale.status != "ANULADA",
        )
        .group_by(Sale.payment_method)
        .all()
    )

    # ── Créditos pendientes ──
    debtors_count = (
        db.query(func.count(Customer.id))
        .filter(Customer.credit_balance > 0)
        .scalar()
    ) or 0

    total_debt = _f(
        db.query(func.coalesce(func.sum(Customer.credit_balance), 0))
        .filter(Customer.credit_balance > 0)
        .scalar()
    )

    # ── Construir respuesta ──
    profit_emoji = "📈" if profit >= 0 else "📉"

    lines = [
        f"📋 **Resumen {label}:**",
        f"",
        f"💰 **Ventas:** {_fmt(sales_total)} en **{sales_count}** transacciones",
    ]

    if sales_count > 0:
        lines.append(f"🧾 Ticket promedio: {_fmt(avg_ticket)}")

    # Desglose pagos
    if payment_rows:
        breakdown = []
        for pm, pm_total, pm_count in payment_rows:
            pm_name = (pm or "Otro").strip()
            breakdown.append(f"  • {pm_name}: {_fmt(pm_total)} ({pm_count})")
        lines.append("💳 Desglose por pago:")
        lines.extend(breakdown)

    lines.append(f"📤 **Gastos:** {_fmt(expenses_total)}")
    lines.append(f"{profit_emoji} **Utilidad: {_fmt(profit)}**")

    # Top productos
    if top_products:
        lines.append("")
        lines.append(f"🏆 **Top productos {label}:**")
        for i, (name, qty, revenue, unit_type) in enumerate(top_products, 1):
            qty_display = format_quantity(float(qty), unit_type or "Unid")
            lines.append(f"  {i}. {name} — {qty_display} — {_fmt(revenue)}")

    # Créditos
    if total_debt > 0:
        lines.append("")
        lines.append(f"💳 **Créditos pendientes:** {_fmt(total_debt)} ({debtors_count} cliente{'s' if debtors_count != 1 else ''})")

    return {
        "reply_text": "\n".join(lines),
        "data": {
            "sales_total": sales_total,
            "sales_count": sales_count,
            "avg_ticket": avg_ticket,
            "expenses_total": expenses_total,
            "profit": profit,
            "total_debt": total_debt,
            "debtors_count": debtors_count,
            "period": period,
        }
    }


# ─────────────────────────────────────────────────────
# Proveedores por producto (Fase 2 — supplier_products)
# ─────────────────────────────────────────────────────

def query_product_suppliers(
    db: Session,
    product_query: str,
    limit_products: int = 5,
) -> dict:
    """
    Fase 6 — Búsqueda enriquecida de proveedores por producto.

    Dado un término de búsqueda, encuentra los productos que matchean
    y para cada uno lista los proveedores con:
      - Precio actual y % de diferencia vs el más barato
      - Contacto del proveedor más barato
      - Historial de variación de precio (últimas compras)
      - Alerta si un proveedor lleva mucho sin comprarle
    """
    from app.ai.chat_handler import search_products_fuzzy

    q = (product_query or "").strip()
    if not q:
        return {
            "reply_text": "⚠️ Necesito un nombre o término de producto para buscar proveedores.",
            "data": {"query": q, "products": []},
        }

    # ── 1. Buscar productos con fuzzy matching ──
    matched_products = search_products_fuzzy(db, q, limit=limit_products)

    if not matched_products:
        return {
            "reply_text": f"🔍 No encontré productos que coincidan con **\"{q}\"**.",
            "data": {"query": q, "products": []},
        }

    STALE_DAYS = 90  # umbral para considerar proveedor inactivo
    today = today_cr()

    # ── 2. Para cada producto, consultar y enriquecer ──
    results = []

    for prod in matched_products:
        sp_rows = (
            db.query(SupplierProduct, Supplier)
            .join(Supplier, SupplierProduct.supplier_id == Supplier.id)
            .filter(SupplierProduct.product_id == prod.id)
            .order_by(SupplierProduct.unit_cost.asc())
            .all()
        )

        if not sp_rows:
            # Fallback: supplier_id legacy
            suppliers_list = []
            if prod.supplier_id and prod.supplier:
                sup = prod.supplier
                suppliers_list.append({
                    "supplier_id": prod.supplier_id,
                    "supplier_name": sup.name,
                    "unit_cost": _f(prod.cost),
                    "last_purchase_date": None,
                    "is_preferred": True,
                    "is_cheapest": True,
                    "pct_vs_cheapest": 0.0,
                    "contact": _build_supplier_contact(sup),
                    "price_history": [],
                    "is_stale": False,
                    "source": "legacy",
                })
            results.append({
                "product_id": prod.id,
                "product_name": prod.name,
                "product_code": prod.code,
                "suppliers": suppliers_list,
            })
            continue

        min_cost = float(sp_rows[0][0].unit_cost) if sp_rows else 0
        suppliers_list = []

        for sp, supplier in sp_rows:
            cost = _f(sp.unit_cost)

            # ── % diferencia vs el más barato ──
            pct_diff = (
                round((cost - min_cost) / min_cost * 100, 1)
                if min_cost > 0 else 0.0
            )

            # ── Fecha última compra ──
            lp_date = None
            lp_date_raw = sp.last_purchase_date
            if lp_date_raw:
                lp_date = (
                    lp_date_raw.strftime("%d/%m/%Y")
                    if hasattr(lp_date_raw, "strftime")
                    else str(lp_date_raw)
                )

            # ── ¿Proveedor inactivo? ──
            is_stale = False
            days_since = None
            if lp_date_raw:
                lp_as_date = (
                    lp_date_raw.date()
                    if hasattr(lp_date_raw, "date")
                    else lp_date_raw
                )
                days_since = (today - lp_as_date).days
                is_stale = days_since > STALE_DAYS

            # ── Historial de precios (últimas 5 compras) ──
            price_history = _get_price_history(
                db, supplier.id, prod.id, limit=5,
            )

            suppliers_list.append({
                "supplier_id": supplier.id,
                "supplier_name": supplier.name,
                "unit_cost": cost,
                "last_purchase_date": lp_date,
                "days_since_last": days_since,
                "is_preferred": bool(sp.is_preferred),
                "is_cheapest": cost == _f(min_cost),
                "pct_vs_cheapest": pct_diff,
                "contact": _build_supplier_contact(supplier),
                "price_history": price_history,
                "is_stale": is_stale,
            })

        results.append({
            "product_id": prod.id,
            "product_name": prod.name,
            "product_code": prod.code,
            "suppliers": suppliers_list,
        })

    # ── 3. Formatear texto enriquecido para el chat ──
    lines = _format_product_suppliers_response(results, q)

    return {
        "reply_text": "\n".join(lines),
        "data": {
            "query": q,
            "products": results,
        },
    }


# ─────────────────────────────────────────────────────
# Helpers internos para query_product_suppliers
# ─────────────────────────────────────────────────────

def _build_supplier_contact(supplier) -> dict:
    """Extrae info de contacto del proveedor."""
    phone = supplier.phone or ""
    contact_name = getattr(supplier, "contact_name", None) or ""
    contact_phone = getattr(supplier, "contact_phone", None) or ""
    email = supplier.email or ""

    # Teléfono principal: preferir contact_phone si existe
    best_phone = contact_phone or phone

    return {
        "phone": best_phone,
        "contact_name": contact_name,
        "email": email,
    }


def _get_price_history(
    db: Session,
    supplier_id: int,
    product_id: int,
    limit: int = 5,
) -> list[dict]:
    """
    Retorna las últimas N compras de este (proveedor, producto)
    con fecha y precio, ordenadas de más reciente a más antigua.
    """
    rows = (
        db.query(
            Purchase.entry_date,
            PurchaseDetail.unit_cost,
        )
        .join(PurchaseDetail, PurchaseDetail.purchase_id == Purchase.id)
        .filter(
            Purchase.supplier_id == supplier_id,
            PurchaseDetail.product_id == product_id,
        )
        .order_by(Purchase.entry_date.desc(), Purchase.id.desc())
        .limit(limit)
        .all()
    )

    history = []
    for entry_date, unit_cost in rows:
        history.append({
            "date": (
                entry_date.strftime("%d/%m/%Y")
                if hasattr(entry_date, "strftime")
                else str(entry_date)
            ),
            "unit_cost": _f(unit_cost),
        })

    return history


def _format_price_trend(history: list[dict]) -> str:
    """
    Genera un mini-indicador de tendencia de precio.
    Compara el precio más reciente con el anterior.
    """
    if len(history) < 2:
        return ""

    current = history[0]["unit_cost"]
    previous = history[1]["unit_cost"]

    if previous == 0:
        return ""

    change_pct = round((current - previous) / previous * 100, 1)

    if change_pct > 1:
        return f" 📈+{change_pct}%"
    elif change_pct < -1:
        return f" 📉{change_pct}%"
    return ""


def _format_product_suppliers_response(results: list[dict], query: str) -> list[str]:
    """Formatea la respuesta enriquecida para el chat."""
    lines = []

    single = len(results) == 1

    if not single:
        lines.append(f"🔍 Encontré **{len(results)} productos** para \"{query}\":\n")

    for p in results:
        lines.append(f"📦 **{p['product_name']}** ({p['product_code']})")

        if not p["suppliers"]:
            lines.append("  ⚠️ No tiene proveedores registrados.\n")
            continue

        n_sup = len(p["suppliers"])
        if single:
            lines.append(f"  🚚 {n_sup} proveedor{'es' if n_sup > 1 else ''}:")
            lines.append("")

        for i, s in enumerate(p["suppliers"], 1):
            # ── Línea principal: nombre + precio ──
            marks = []
            if s.get("is_cheapest"):
                marks.append("💰 Mejor precio")
            if s.get("is_preferred"):
                marks.append("⭐ Preferido")
            mark_str = f"  ({', '.join(marks)})" if marks else ""

            # % diferencia
            pct = s.get("pct_vs_cheapest", 0)
            pct_str = f" (+{pct}%)" if pct > 0 else ""

            # Tendencia de precio
            trend = _format_price_trend(s.get("price_history", []))

            # Fecha
            date_str = ""
            if s.get("last_purchase_date"):
                date_str = f" — {s['last_purchase_date']}"

            if single:
                lines.append(
                    f"  {i}. **{s['supplier_name']}** — "
                    f"{_fmt(s['unit_cost'])}{pct_str}{trend}{date_str}{mark_str}"
                )
            else:
                lines.append(
                    f"  {i}. {s['supplier_name']} — "
                    f"{_fmt(s['unit_cost'])}{pct_str}{trend}{date_str}"
                    f"{' 💰' if s.get('is_cheapest') else ''}"
                    f"{' ⭐' if s.get('is_preferred') else ''}"
                )

            # ── Contacto (solo para el más barato en vista detallada) ──
            if single and s.get("is_cheapest"):
                contact = s.get("contact", {})
                contact_parts = []
                if contact.get("phone"):
                    contact_parts.append(f"📞 {contact['phone']}")
                if contact.get("contact_name"):
                    contact_parts.append(f"👤 {contact['contact_name']}")
                if contact.get("email"):
                    contact_parts.append(f"✉️ {contact['email']}")
                if contact_parts:
                    lines.append(f"     {' — '.join(contact_parts)}")

            # ── Historial de precios (solo vista detallada, si hay variación) ──
            if single and len(s.get("price_history", [])) >= 2:
                hist = s["price_history"]
                # Solo mostrar si hay cambio de precio
                prices_unique = set(h["unit_cost"] for h in hist)
                if len(prices_unique) > 1:
                    hist_parts = [f"{h['date']}: {_fmt(h['unit_cost'])}" for h in hist[:4]]
                    lines.append(f"     📊 Historial: {' → '.join(hist_parts)}")

            # ── Alerta de proveedor inactivo ──
            if s.get("is_stale") and s.get("days_since_last"):
                days = s["days_since_last"]
                lines.append(
                    f"     ⚠️ Sin compras hace {days} días"
                    f" — considerar verificar disponibilidad/precios"
                )

        # Separador entre productos (vista múltiple)
        if not single:
            lines.append("")

    # ── Resumen comparativo (solo si hay 2+ proveedores en un producto) ──
    if single and len(results) == 1:
        sups = results[0]["suppliers"]
        if len(sups) >= 2:
            cheapest = sups[0]
            most_expensive = sups[-1]
            if cheapest["unit_cost"] > 0 and most_expensive["unit_cost"] > cheapest["unit_cost"]:
                savings = _f(most_expensive["unit_cost"] - cheapest["unit_cost"])
                lines.append("")
                lines.append(
                    f"💡 Comprando a **{cheapest['supplier_name']}** "
                    f"ahorrás {_fmt(savings)} por unidad vs {most_expensive['supplier_name']}."
                )

    return lines