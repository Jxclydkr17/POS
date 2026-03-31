# app/utils/dt.py
"""
Utilidades de fecha/hora para el sistema.

Costa Rica no observa horario de verano: siempre UTC-6.
Estrategia: almacenar en UTC (timezone-aware), mostrar en hora local al consultar.
"""

from datetime import datetime, timezone, timedelta, date

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