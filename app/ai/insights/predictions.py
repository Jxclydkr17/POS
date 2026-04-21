from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.utils.dt import today_cr
from app.db.models.sale import Sale


@dataclass
class SalesPrediction:
    avg_last_7: float
    avg_prev_7: float
    trend_pct: float
    forecast_avg_next_7: float
    days_used: int


def _safe_float(x) -> float:
    try:
        return float(x or 0.0)
    except Exception:
        return 0.0


def _pct_change(current: float, previous: float) -> float:
    if previous <= 0:
        return 0.0
    return round(((current - previous) / previous) * 100.0, 2)


def get_daily_sales_totals(
    db: Session,
    start_dt: datetime,
    end_dt: datetime,
) -> List[Tuple[date, float]]:
    """
    Retorna lista de (fecha, total_del_dia) ordenada por fecha.
    OJO: end_dt es inclusivo si lo pasas con datetime.max.time().
    """
    rows = (
        db.query(func.date(Sale.created_at).label("d"), func.sum(Sale.total).label("t"))
        .filter(Sale.created_at >= start_dt)
        .filter(Sale.created_at <= end_dt)
        .group_by(func.date(Sale.created_at))
        .order_by(func.date(Sale.created_at))
        .all()
    )

    return [(r[0], _safe_float(r[1])) for r in rows]


def predict_sales_next_7_days_avg(db: Session) -> SalesPrediction | None:
    """
    Predicción simple:
    - Usa 14 días COMPLETOS anteriores (excluye HOY).
    - Calcula avg últimos 7 vs avg 7 previos.
    - trend_pct = % cambio entre semanas.
    - forecast = avg_last_7 + (avg_last_7 - avg_prev_7)   (proyección lineal simple)
      (clamp a >= 0)
    """
    today = today_cr()

    # Ventana: [today-14, today-1]
    start_day = today - timedelta(days=14)
    end_day = today - timedelta(days=1)

    start_dt = datetime.combine(start_day, datetime.min.time())
    end_dt = datetime.combine(end_day, datetime.max.time())

    daily = get_daily_sales_totals(db, start_dt, end_dt)

    # Necesitamos al menos 7 días con data para que tenga sentido
    if len(daily) < 7:
        return None

    totals = [t for _, t in daily]

    # Tomamos los últimos 14 registros disponibles (si hubo días sin ventas, no aparecen;
    # igual sirve, pero es mejor si hay continuidad)
    totals = totals[-14:]

    # Partimos en 7 y 7 (si hay menos de 14, igual calculamos con lo que hay)
    last_7 = totals[-7:]
    prev_7 = totals[:-7]  # puede ser <7

    avg_last_7 = round(sum(last_7) / len(last_7), 2) if last_7 else 0.0
    avg_prev_7 = round(sum(prev_7) / len(prev_7), 2) if prev_7 else 0.0

    trend_pct = _pct_change(avg_last_7, avg_prev_7)

    # Proyección lineal simple basada en diferencia entre semanas
    delta = avg_last_7 - avg_prev_7
    forecast = avg_last_7 + delta
    if forecast < 0:
        forecast = 0.0
    forecast = round(forecast, 2)

    return SalesPrediction(
        avg_last_7=avg_last_7,
        avg_prev_7=avg_prev_7,
        trend_pct=trend_pct,
        forecast_avg_next_7=forecast,
        days_used=len(totals),
    )