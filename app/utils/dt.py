# app/utils/dt.py
"""
Utilidades de fecha/hora para el sistema.

Costa Rica no observa horario de verano: siempre UTC-6.

═══════════════════════════════════════════════════════════════
CONVENCIÓN DE TIMESTAMPS — FASE 5 — Fix 5.5
═══════════════════════════════════════════════════════════════

1. Sale.created_at usa `now_cr` (hora local CR, timezone-aware).
   → Las queries de rango sobre ventas DEBEN usar `today_cr()` o
     `today_cr_datetime_range()` para que coincidan.

2. La mayoría de los demás modelos (Credit, CashSession, Customer,
   Product, etc.) usan `utcnow` para created_at/updated_at.
   → CashSession.date es un campo Date (sin hora), se compara con
     `today_cr()` → correcto.
   → Credit queries usan aggregates (SUM/MAX), no rangos horarios
     directos → no hay riesgo de desfase.

3. Para queries de rango que crucen modelos con distinta convención,
   usar `today_cr_datetime_range()` que retorna start/end en CR
   timezone, compatible con ambas convenciones.

REGLA: si creás un modelo nuevo, usá `default=now_cr` si el timestamp
va a compararse con rangos de fecha del negocio (ventas, caja, reportes).
Usá `default=utcnow` para timestamps técnicos (auditoría, logs, tokens).
═══════════════════════════════════════════════════════════════
"""

from datetime import datetime, timezone, timedelta, date, time

# Zona horaria de Costa Rica (UTC-6, sin DST)
TZ_CR = timezone(timedelta(hours=-6))


def utcnow() -> datetime:
    """Retorna la hora actual en UTC, timezone-aware."""
    return datetime.now(timezone.utc)


def now_cr() -> datetime:
    """Retorna la hora actual en hora de Costa Rica, timezone-aware."""
    return datetime.now(TZ_CR)


def to_cr(dt: datetime) -> datetime:
    """Convierte un datetime (UTC o naive) a hora de Costa Rica."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Asumir que naive es UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_CR)


def today_cr() -> "date":
    """Retorna la fecha actual en Costa Rica (date, no datetime).
    Usar en lugar de date.today() para evitar desfases por zona horaria."""
    return now_cr().date()


def today_cr_datetime_range() -> tuple[datetime, datetime]:
    """
    FASE 5 — Fix 5.5: Retorna (inicio, fin) del día actual en CR como datetimes.

    Uso en queries de rango:
        start, end = today_cr_datetime_range()
        db.query(Sale).filter(Sale.created_at >= start, Sale.created_at < end)

    Retorna datetimes timezone-aware en TZ_CR, compatibles con columnas
    que usen tanto `now_cr` como `utcnow` (SQLAlchemy/MySQL convierten).
    """
    today = today_cr()
    start = datetime.combine(today, time.min).replace(tzinfo=TZ_CR)
    end = start + timedelta(days=1)
    return start, end