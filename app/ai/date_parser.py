# app/ai/date_parser.py
"""
FASE 2 — Parser de fechas mejorado.
Soporta expresiones naturales en español:
  - Periodos: hoy, ayer, esta semana, este mes, este año
  - Relativos: hace 3 días, la semana pasada, el mes pasado
  - Fechas específicas: 15 de marzo, 15/03, 15-03-2025
  - Rangos: del 1 al 15, entre lunes y viernes
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional, Tuple

from app.ai.fuzzy import normalize_text


# ─────────────────────────────────────────────────────
# Meses en español
# ─────────────────────────────────────────────────────

_MONTH_NAMES = {
    "enero": 1, "ene": 1,
    "febrero": 2, "feb": 2,
    "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6,
    "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "septiembre": 9, "sep": 9, "sept": 9,
    "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}

_DAY_NAMES = {
    "lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2,
    "jueves": 3, "viernes": 4, "sabado": 5, "sábado": 5,
    "domingo": 6,
}


# ─────────────────────────────────────────────────────
# Parser de periodo (keyword-based)
# ─────────────────────────────────────────────────────

def parse_period(text: str) -> Optional[str]:
    """
    Extrae un periodo nombrado del texto.
    Retorna: "today", "yesterday", "week", "last_week",
             "month", "last_month", "year", o None.

    Más robusto que el anterior: soporta variantes como
    "esta semana", "la semana pasada", "semana anterior", etc.
    """
    t = normalize_text(text)

    # ── Orden: más específico primero ──

    # "anteayer" / "hace 2 días"
    if re.search(r"\b(anteayer|antier)\b", t):
        return "day_before_yesterday"

    # "ayer"
    if re.search(r"\bayer\b", t):
        return "yesterday"

    # "hoy" / "del día" / "diario"
    if re.search(r"\b(hoy|del dia|diario|de hoy)\b", t):
        return "today"

    # "semana pasada" / "semana anterior" / "la semana pasada"
    if re.search(r"\bsemana\s+(pasada|anterior|que\s+paso)\b", t):
        return "last_week"

    # "esta semana" / "semana" / "semanal" / "semanales"
    if re.search(r"\b(esta\s+semana|semana|semanal\w*)\b", t):
        return "week"

    # "mes pasado" / "mes anterior" / "el mes pasado"
    if re.search(r"\bmes\s+(pasado|anterior|que\s+paso)\b", t):
        return "last_month"

    # "este mes" / "mes" / "mensual" / "mensuales"
    if re.search(r"\b(este\s+mes|mes|mensual\w*)\b", t):
        return "month"

    # "año pasado" / "año anterior"
    if re.search(r"\ba[ñn]o\s+(pasado|anterior)\b", t):
        return "last_year"

    # "este año" / "año" / "anual"
    if re.search(r"\b(este\s+a[ñn]o|a[ñn]o|anual)\b", t):
        return "year"

    return None


# ─────────────────────────────────────────────────────
# Parser de fecha relativa
# ─────────────────────────────────────────────────────

def _parse_relative_date(text: str) -> Optional[Tuple[date, date]]:
    """
    Parsea expresiones relativas:
    - "hace N días/semanas/meses"
    - "últimos N días"
    - "anteayer"
    """
    t = normalize_text(text)
    today = date.today()

    # "anteayer" / "antier"
    if re.search(r"\b(anteayer|antier)\b", t):
        d = today - timedelta(days=2)
        return d, d

    # "hace N días"
    m = re.search(r"\bhace\s+(\d+)\s+dias?\b", t)
    if m:
        n = int(m.group(1))
        d = today - timedelta(days=n)
        return d, d

    # "hace N semanas"
    m = re.search(r"\bhace\s+(\d+)\s+semanas?\b", t)
    if m:
        n = int(m.group(1))
        end = today - timedelta(days=n * 7)
        start = end - timedelta(days=6)
        return start, end

    # "hace N meses"
    m = re.search(r"\bhace\s+(\d+)\s+meses?\b", t)
    if m:
        n = int(m.group(1))
        # Retroceder N meses (simple: 30 días por mes)
        d = today - timedelta(days=n * 30)
        return d.replace(day=1), today

    # "últimos N días"
    m = re.search(r"\b(ultimos?|los\s+ultimos?)\s+(\d+)\s+dias?\b", t)
    if m:
        n = int(m.group(2))
        return today - timedelta(days=n - 1), today

    # "última semana" (sin "la") / "la última semana"
    if re.search(r"\b(ultima|la\s+ultima)\s+semana\b", t):
        return today - timedelta(days=6), today

    # "último mes" / "el último mes"
    if re.search(r"\b(ultimo|el\s+ultimo)\s+mes\b", t):
        return today - timedelta(days=29), today

    return None


# ─────────────────────────────────────────────────────
# Parser de fecha específica
# ─────────────────────────────────────────────────────

def _parse_specific_date(text: str) -> Optional[Tuple[date, date]]:
    """
    Parsea fechas específicas:
    - "15 de marzo"
    - "15/03" o "15-03"
    - "15/03/2025" o "15-03-2025"
    - "marzo 15"
    - "el lunes" (el más reciente)
    """
    t = normalize_text(text)
    today = date.today()

    # "DD de MONTH" o "DD MONTH"
    for month_name, month_num in _MONTH_NAMES.items():
        m = re.search(
            rf"\b(\d{{1,2}})\s+(?:de\s+)?{month_name}\b",
            t,
        )
        if m:
            day = int(m.group(1))
            year = today.year
            try:
                d = date(year, month_num, day)
                if d > today:
                    d = date(year - 1, month_num, day)
                return d, d
            except ValueError:
                continue

    # "MONTH DD"
    for month_name, month_num in _MONTH_NAMES.items():
        m = re.search(
            rf"\b{month_name}\s+(\d{{1,2}})\b",
            t,
        )
        if m:
            day = int(m.group(1))
            year = today.year
            try:
                d = date(year, month_num, day)
                if d > today:
                    d = date(year - 1, month_num, day)
                return d, d
            except ValueError:
                continue

    # "DD/MM/YYYY" o "DD-MM-YYYY"
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", t)
    if m:
        try:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return d, d
        except ValueError:
            pass

    # "DD/MM" o "DD-MM" (año actual)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", t)
    if m:
        try:
            d = date(today.year, int(m.group(2)), int(m.group(1)))
            if d > today:
                d = date(today.year - 1, int(m.group(2)), int(m.group(1)))
            return d, d
        except ValueError:
            pass

    # "el lunes" / "el martes" etc. (el más reciente)
    for day_name, weekday in _DAY_NAMES.items():
        day_norm = normalize_text(day_name)
        if re.search(rf"\b(?:el\s+)?{day_norm}\b", t):
            days_back = (today.weekday() - weekday) % 7
            if days_back == 0:
                days_back = 0  # hoy mismo
            d = today - timedelta(days=days_back)
            return d, d

    return None


# ─────────────────────────────────────────────────────
# Parser de rango de fechas
# ─────────────────────────────────────────────────────

def _parse_date_range(text: str) -> Optional[Tuple[date, date]]:
    """
    Parsea rangos:
    - "del 1 al 15"
    - "del 1 al 15 de marzo"
    - "entre el 5 y el 20"
    """
    t = normalize_text(text)
    today = date.today()

    # "del DD al DD (de MONTH)"
    m = re.search(
        r"\bdel?\s+(\d{1,2})\s+al?\s+(\d{1,2})(?:\s+de\s+(\w+))?\b",
        t,
    )
    if m:
        d1 = int(m.group(1))
        d2 = int(m.group(2))
        month_str = m.group(3)
        month = today.month
        if month_str:
            month = _MONTH_NAMES.get(month_str, today.month)
        try:
            start = date(today.year, month, d1)
            end = date(today.year, month, d2)
            return start, end
        except ValueError:
            pass

    # "entre el DD y el DD"
    m = re.search(
        r"\bentre\s+(?:el\s+)?(\d{1,2})\s+y\s+(?:el\s+)?(\d{1,2})\b",
        t,
    )
    if m:
        d1 = int(m.group(1))
        d2 = int(m.group(2))
        try:
            start = date(today.year, today.month, d1)
            end = date(today.year, today.month, d2)
            return start, end
        except ValueError:
            pass

    return None


# ─────────────────────────────────────────────────────
# Función principal: extraer fechas del texto
# ─────────────────────────────────────────────────────

def extract_date_range(text: str) -> Optional[Tuple[date, date]]:
    """
    Intenta extraer un rango de fechas del texto usando todos los parsers.
    Orden de prioridad:
      1. Rango explícito ("del 1 al 15")
      2. Fecha específica ("15 de marzo")
      3. Fecha relativa ("hace 3 días")
      4. Periodo nombrado ("esta semana")

    Retorna (start_date, end_date) o None.
    """
    # 1) Rango
    result = _parse_date_range(text)
    if result:
        return result

    # 2) Fecha específica
    result = _parse_specific_date(text)
    if result:
        return result

    # 3) Relativo
    result = _parse_relative_date(text)
    if result:
        return result

    # 4) Periodo nombrado -> convertir a rango
    period = parse_period(text)
    if period:
        return period_to_range(period)

    return None


def period_to_range(period: str) -> Tuple[date, date]:
    """Convierte un periodo nombrado a (start, end)."""
    today = date.today()

    if period == "today":
        return today, today
    elif period == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    elif period == "day_before_yesterday":
        d = today - timedelta(days=2)
        return d, d
    elif period == "week":
        start = today - timedelta(days=today.weekday())  # lunes
        return start, today
    elif period == "last_week":
        end = today - timedelta(days=today.weekday() + 1)  # domingo pasado
        start = end - timedelta(days=6)
        return start, end
    elif period == "month":
        return today.replace(day=1), today
    elif period == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    elif period == "year":
        return today.replace(month=1, day=1), today
    elif period == "last_year":
        ly = today.year - 1
        return date(ly, 1, 1), date(ly, 12, 31)

    return today, today


def extract_period_or_default(text: str, default: str = "today") -> str:
    """
    Extrae el periodo del texto, con fallback a default.
    Versión mejorada: soporta más variantes.
    """
    p = parse_period(text)
    if p:
        # Convertir periodos especiales a los que data_queries entiende
        mapping = {
            "day_before_yesterday": "yesterday",  # approx
            "last_week": "week",       # approx
            "last_year": "year",       # approx
        }
        return mapping.get(p, p)
    return default