# app/utils/decimal_utils.py
"""
FASE 2 — Fix 2.3: Helper compartido para conversión segura a Decimal.

Antes estaba duplicado en:
  - app/db/crud/cash.py (_to_dec)
  - app/services/cash_close_service.py (_to_dec)

Centralizado aquí para garantizar consistencia en cálculos monetarios.
"""

from decimal import Decimal


def to_dec(value) -> Decimal:
    """Convierte float/int/str/Decimal a Decimal sin pérdida IEEE 754."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))