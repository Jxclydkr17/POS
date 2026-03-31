# app/ai/proactive_alerts.py
"""
FASE 7 — Alertas proactivas para el chat.
Consulta el estado del negocio y genera alertas relevantes
que se muestran automáticamente al abrir el chat.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from app.utils.dt import today_cr
from typing import List, Dict, Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.sale import Sale
from app.db.models.product import Product
from app.db.models.customer import Customer
from app.db.models.cash_session import CashSession
from app.db.models.expense import Expense


def _fmt(val) -> str:
    try:
        return f"₡{float(val):,.0f}"
    except Exception:
        return "—"


def get_proactive_alerts(db: Session) -> List[Dict[str, Any]]:
    """
    Genera alertas proactivas basadas en el estado actual del negocio.
    Cada alerta: {"level": "info|warning|critical", "icon": str, "text": str}
    Máximo 4 alertas (las más importantes).
    """
    alerts: list[dict] = []
    today = today_cr()
    start_dt = datetime.combine(today, time.min)
    end_dt = datetime.combine(today, time.max)

    try:
        # ── 1) Caja no abierta ──
        cash = db.query(CashSession).filter(CashSession.date == today).first()
        if not cash:
            alerts.append({
                "level": "warning",
                "icon": "🏦",
                "text": "La **caja no está abierta** hoy. Abrí caja para empezar.",
            })
        elif cash.status == "closed":
            alerts.append({
                "level": "info",
                "icon": "🔒",
                "text": "La caja ya fue **cerrada** hoy.",
            })

        # ── 2) Ventas del día (resumen rápido) ──
        sales_result = (
            db.query(
                func.coalesce(func.sum(Sale.total), 0),
                func.count(Sale.id),
            )
            .filter(Sale.created_at >= start_dt, Sale.created_at <= end_dt, Sale.status != "ANULADA")
            .first()
        )
        sales_total = float(sales_result[0] or 0)
        sales_count = int(sales_result[1] or 0)

        if sales_count > 0:
            alerts.append({
                "level": "info",
                "icon": "💰",
                "text": f"Hoy llevás **{_fmt(sales_total)}** en **{sales_count}** ventas.",
            })
        else:
            alerts.append({
                "level": "info",
                "icon": "📊",
                "text": "Aún no hay ventas registradas hoy.",
            })

        # ── 3) Productos sin stock ──
        out_of_stock = (
            db.query(func.count(Product.id))
            .filter(Product.is_active == True, Product.stock <= 0)
            .scalar()
        ) or 0

        if out_of_stock > 0:
            lvl = "critical" if out_of_stock >= 5 else "warning"
            alerts.append({
                "level": lvl,
                "icon": "📦",
                "text": f"**{out_of_stock}** producto{'s' if out_of_stock != 1 else ''} **sin stock**.",
            })

        # ── 4) Productos con stock bajo (>0 pero <= min_stock) ──
        low_stock = (
            db.query(func.count(Product.id))
            .filter(Product.is_active == True, Product.stock > 0, Product.stock <= Product.min_stock)
            .scalar()
        ) or 0

        if low_stock > 0 and out_of_stock == 0:  # No duplicar con el anterior
            alerts.append({
                "level": "warning",
                "icon": "⚠️",
                "text": f"**{low_stock}** producto{'s' if low_stock != 1 else ''} con **stock bajo**.",
            })

        # ── 5) Clientes morosos (deuda > 30 días sin abono) ──
        debtors_count = (
            db.query(func.count(Customer.id))
            .filter(Customer.credit_balance > 0, Customer.is_active == True)
            .scalar()
        ) or 0

        total_debt = float(
            db.query(func.coalesce(func.sum(Customer.credit_balance), 0))
            .filter(Customer.credit_balance > 0)
            .scalar() or 0
        )

        if total_debt > 0:
            alerts.append({
                "level": "warning" if total_debt > 50000 else "info",
                "icon": "💳",
                "text": f"**{debtors_count}** clientes deben **{_fmt(total_debt)}** en total.",
            })

        # ── 6) Gastos del día ──
        expenses_total = float(
            db.query(func.coalesce(func.sum(Expense.amount), 0))
            .filter(Expense.date >= start_dt, Expense.date <= end_dt)
            .scalar() or 0
        )

        if expenses_total > 0:
            alerts.append({
                "level": "info",
                "icon": "📤",
                "text": f"Gastos de hoy: **{_fmt(expenses_total)}**.",
            })

    except Exception:
        # Si falla la consulta, no bloquear el chat
        pass

    # Ordenar: critical > warning > info, max 4
    level_order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: level_order.get(a.get("level", "info"), 9))
    return alerts[:4]


def format_alerts_as_message(alerts: List[Dict[str, Any]]) -> str:
    """Formatea alertas como un mensaje de bienvenida del chat."""
    if not alerts:
        return "✅ Todo tranquilo hoy. ¿En qué te ayudo?"

    lines = ["📋 **Estado rápido del negocio:**"]
    for a in alerts:
        lines.append(f"  {a['icon']} {a['text']}")

    lines.append("\n¿En qué te puedo ayudar?")
    return "\n".join(lines)