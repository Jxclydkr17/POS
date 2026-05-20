# app/utils/dt.py
"""
Utilidades de fecha/hora para el sistema.

Costa Rica no observa horario de verano: siempre UTC-6.

═══════════════════════════════════════════════════════════════
CONVENCIÓN DE TIMESTAMPS — FASE 2.2 — Fix 2.2
═══════════════════════════════════════════════════════════════

Después de la migración de Fase 2.2, la convención es UNIFORME:

1. TODOS los timestamps de modelos se guardan en UTC (con `default=utcnow`).
   Esto incluye Sale.created_at, que antes usaba `now_cr` (CR-local).

2. Para queries de rango por "día del negocio CR" (ej. ventas de hoy),
   usar `today_cr_datetime_range()` que retorna el rango UTC equivalente
   al día CR (00:00:00 CR → 06:00:00 UTC).

3. Para mostrar timestamps al usuario, usar:
     - `format_cr(dt, fmt)`        → string CR con formato.
     - `to_cr(dt)`                 → datetime aware en CR.
     - `to_cr_iso(dt)`             → ISO 8601 con offset -06:00 (Hacienda).

REGLA: si creás un modelo nuevo, usá `default=utcnow`. NUNCA `default=now_cr`
para columnas que se vayan a comparar en queries de rango.
═══════════════════════════════════════════════════════════════
"""

from datetime import datetime, timezone, timedelta, date, time

# Zona horaria de Costa Rica (UTC-6, sin DST)
TZ_CR = timezone(timedelta(hours=-6))


def utcnow() -> datetime:
    """Retorna la hora actual en UTC, timezone-aware."""
    return datetime.now(timezone.utc)


def now_cr() -> datetime:
    """Retorna la hora actual en hora de Costa Rica, timezone-aware.

    NOTA (FASE 2.2): NO usar como `default=now_cr` en modelos nuevos.
    Para `default=` siempre usar `utcnow`. Esta función queda solo
    para cálculos locales (ej. `today_cr()`) y display.
    """
    return datetime.now(TZ_CR)


def to_cr(dt: datetime) -> datetime:
    """Convierte un datetime (UTC o naive) a hora de Costa Rica.

    Política para naive: se asume que es UTC (consistente con la
    convención post-Fase 2.2). Si el datetime viene de BD vía
    SQLAlchemy con motor MySQL, generalmente llega naive con valor UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Asumir que naive es UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_CR)


def to_cr_iso(dt: datetime, timespec: str = "seconds") -> str:
    """
    FASE 2.1 — Fix 2.1: Formatea un datetime como ISO 8601 en hora de Costa
    Rica (UTC-6), garantizando que el offset siempre quede como `-06:00`.

    Casos manejados:
      - `None`        → retorna `now_cr().isoformat(...)` (fallback razonable).
      - naive         → asume UTC (igual que `to_cr`) y convierte a CR.
      - aware (cualquier tz) → convierte a TZ_CR.

    Uso típico (para Hacienda):
        fecha = to_cr_iso(sale.created_at)
        # → "2026-05-14T14:30:00-06:00"

    Antes este formato se construía con `dt.astimezone()` sin argumento, que
    usa la TZ del sistema operativo. Si la PC de la ferretería tenía TZ
    distinta de CR (ej. UTC), Hacienda rechazaba la factura por inconsistencia
    entre `FechaEmision` y `FechaEmisionIR`.
    """
    if dt is None:
        return now_cr().isoformat(timespec=timespec)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_CR).isoformat(timespec=timespec)


def format_cr(dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """
    FASE 2.2 — Fix 2.2: Convierte UTC → CR y aplica strftime.

    Helper para todos los puntos donde se muestra un timestamp al usuario
    de la ferretería: debe verse en hora local CR independiente de cómo
    esté guardado en BD.

    Si `dt` es None, retorna string vacío.

    Ejemplos:
        format_cr(sale.created_at)                    → "2026-05-14 14:30"
        format_cr(sale.created_at, "%Y-%m-%d")        → "2026-05-14"
        format_cr(sale.created_at, "%H:%M:%S")        → "14:30:25"
        format_cr(None)                               → ""
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_CR).strftime(fmt)


def today_cr() -> "date":
    """Retorna la fecha actual en Costa Rica (date, no datetime).
    Usar en lugar de date.today() para evitar desfases por zona horaria."""
    return now_cr().date()


def today_cr_datetime_range() -> tuple[datetime, datetime]:
    """
    FASE 2.2 — Fix 2.2: Retorna (inicio, fin) del día CR como datetimes UTC.

    Después de la migración a UTC, las columnas como `Sale.created_at`
    guardan UTC. Para filtrar "ventas del día CR", el rango debe estar
    en UTC también.

    El día CR 2026-05-14 corresponde a:
      - inicio: 2026-05-14T00:00:00-06:00 = 2026-05-14T06:00:00+00:00
      - fin:    2026-05-15T00:00:00-06:00 = 2026-05-15T06:00:00+00:00

    Uso en queries:
        start, end = today_cr_datetime_range()
        db.query(Sale).filter(Sale.created_at >= start,
                              Sale.created_at <  end)

    Retorna datetimes timezone-aware en UTC. Compatible con columnas que
    guarden naive UTC (MySQL strip offset) gracias a la conversión
    automática de SQLAlchemy.
    """
    return cr_day_to_utc_range(today_cr())


def cr_day_to_utc_range(target_date: "date") -> tuple[datetime, datetime]:
    """
    FASE 2.2 — Fix 2.2: Convierte un date CR a su rango UTC.

    Útil para "ventas del día X" cuando X es una fecha CR pero los
    timestamps en BD están en UTC.

    Args:
        target_date: fecha en CR (ej. today_cr() o una fecha del pasado).
    Returns:
        (start_utc, end_utc) — tuple de datetime aware UTC.
    """
    start_cr = datetime.combine(target_date, time.min).replace(tzinfo=TZ_CR)
    end_cr = start_cr + timedelta(days=1)
    return start_cr.astimezone(timezone.utc), end_cr.astimezone(timezone.utc)