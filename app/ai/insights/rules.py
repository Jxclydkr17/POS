"""
Reglas simples y EXPLICABLES.
Aquí NO se consulta la DB.

Incluye helpers para predicción estable (incluyendo días sin ventas).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


# --------------------------------------------------
# 📉 VENTAS
# --------------------------------------------------
def sales_drop_percentage(today: float, average: float) -> float:
    """
    Calcula porcentaje de caída de ventas respecto al promedio.
    """
    today = float(today)
    average = float(average)
    if average <= 0:
        return 0.0
    return round(((average - today) / average) * 100, 2)


def sales_drop_level(today: float, average: float) -> str | None:
    """
    Determina el nivel de alerta por caída de ventas.
    """
    drop = sales_drop_percentage(today, average)

    if drop >= 40:
        return "critical"
    elif drop >= 25:
        return "warning"
    elif drop >= 15:
        return "info"

    return None


# --------------------------------------------------
# 📦 INVENTARIO
# --------------------------------------------------
def stock_level(stock: int, min_stock: int) -> str | None:
    """
    Evalúa severidad del stock.
    """
    if min_stock <= 0:
        return None

    ratio = float(stock) / float(min_stock)

    if stock <= 0:
        return "critical"
    elif ratio <= 0.5:
        return "warning"
    elif ratio <= 1:
        return "info"

    return None


def is_stock_critical(stock: int, min_stock: int) -> bool:
    """
    Verifica si el stock está en nivel crítico.
    """
    return stock <= min_stock


# --------------------------------------------------
# 💳 CRÉDITOS
# --------------------------------------------------
def credit_risk_level(balance: float) -> str | None:
    """
    Evalúa riesgo de crédito según monto adeudado.
    """
    if balance <= 0:
        return None

    if balance >= 200_000:
        return "critical"
    elif balance >= 75_000:
        return "warning"
    elif balance >= 20_000:
        return "info"

    return None


def credit_risk(balance: float) -> bool:
    """
    Verifica si existe riesgo de crédito.
    """
    return balance > 0


# ============================================================
# 🔮 Predicción estable (incluye días sin ventas)
# ============================================================
def build_daily_series(
    rows: Iterable[tuple[date, float]],
    start_day: date,
    end_day: date,
) -> list[float]:
    """
    Convierte filas (fecha, total) en una serie diaria completa [start_day..end_day]
    rellenando días faltantes con 0.0 (incluye días sin ventas).
    """
    if end_day < start_day:
        return []

    by_day: dict[date, float] = {}
    for d, total in rows:
        if d is None:
            continue
        by_day[d] = float(total or 0.0)

    series: list[float] = []
    cur = start_day
    while cur <= end_day:
        series.append(float(by_day.get(cur, 0.0)))
        cur += timedelta(days=1)

    return series


def avg_last_n(series: list[float], n: int) -> float:
    """
    Promedio de los últimos n valores. Si no hay suficientes datos, usa los que existan.
    Si la serie está vacía -> 0.0
    """
    if not series:
        return 0.0

    n = max(1, int(n))
    chunk = series[-n:] if len(series) >= n else series
    return round(sum(chunk) / len(chunk), 2)


def predict_today_sales(
    history_series_excluding_today: list[float],
    window: int = 7,
) -> float:
    """
    Predicción simple = promedio móvil de los últimos `window` días (incluyendo ceros).
    history_series_excluding_today: serie del pasado, SIN el día de hoy.
    """
    return avg_last_n(history_series_excluding_today, window)


def should_raise_sales_prediction_alert(
    today_sales: float,
    predicted_sales: float,
    threshold_pct: float = 25.0,
    min_predicted: float = 0.0,
) -> tuple[bool, float]:
    """
    Decide si crear alerta de predicción.
    - threshold_pct: % mínimo de caída vs predicción para alertar
    - min_predicted: si la predicción es muy baja, no hacemos ruido (opcional)
    Retorna (flag, drop_pct)
    """
    today_sales = float(today_sales or 0.0)
    predicted_sales = float(predicted_sales or 0.0)

    if predicted_sales <= 0:
        return (False, 0.0)

    if predicted_sales < float(min_predicted):
        return (False, 0.0)

    drop_pct = sales_drop_percentage(today_sales, predicted_sales)
    return (drop_pct >= float(threshold_pct), drop_pct)

# ============================================================
# 📦 Predicción de quiebre de stock
# ============================================================
def avg_daily_consumption(
    total_sold: float,
    days: int
) -> float:
    """
    Consumo promedio diario.
    """
    if days <= 0:
        return 0.0
    return round(float(total_sold) / days, 4)


def stock_coverage_days(
    stock: int,
    daily_consumption: float
) -> float:
    """
    Días estimados que dura el stock.
    """
    if daily_consumption <= 0:
        return float("inf")
    return round(float(stock) / float(daily_consumption), 2)


def stock_break_risk_level(
    coverage_days: float,
    critical_days: int = 3,
    warning_days: int = 7
) -> str | None:
    """
    Devuelve nivel de riesgo según cobertura.
    """
    if coverage_days <= critical_days:
        return "critical"
    if coverage_days <= warning_days:
        return "warning"
    return None

# ============================================================
# 💰 Impacto económico
# ============================================================
def estimated_lost_revenue(
    daily_consumption: float,
    avg_price: float,
    days_without_stock: float
) -> float:
    if daily_consumption <= 0 or avg_price <= 0 or days_without_stock <= 0:
        return 0.0

    return round(
        daily_consumption * avg_price * days_without_stock,
        2
    )

# ============================================================
# 🛒 Sugerencia de compra
# ============================================================
def suggested_purchase_quantity(
    daily_consumption: float,
    current_stock: int,
    target_days: int = 7
) -> int:
    """
    Calcula cuántas unidades comprar para cubrir target_days.
    """
    if daily_consumption <= 0 or target_days <= 0:
        return 0

    target_stock = float(daily_consumption) * target_days
    qty = target_stock - float(current_stock)

    if qty <= 0:
        return 0

    return int(round(qty))

def days_until_stockout(stock: int, avg_daily_sales: float) -> int | None:
    if avg_daily_sales <= 0:
        return None
    return int(float(stock) / float(avg_daily_sales))