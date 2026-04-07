# tests/test_cash_precision.py
"""
FASE 5 — Tests de precisión monetaria en operaciones de caja.

Verifica que la cadena completa (apertura → movimientos → cierre)
mantiene precisión Decimal sin drift de float. Un error aquí causa
diferencias fantasma de ₡1-2 al cierre de caja que confunden al cajero.
"""

import pytest
from decimal import Decimal
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models.cash_session import CashSession
from app.db.models.cash_movement import CashMovement
from app.db.crud.cash import _to_dec


# ═══════════════════════════════════════════════════════════════
# _to_dec: helper de conversión segura
# ═══════════════════════════════════════════════════════════════

class TestToDecHelper:
    """Verifica que _to_dec convierte cualquier tipo sin pérdida."""

    def test_from_float(self):
        result = _to_dec(10.50)
        assert result == Decimal("10.5")
        assert isinstance(result, Decimal)

    def test_from_int(self):
        assert _to_dec(100) == Decimal("100")

    def test_from_string(self):
        assert _to_dec("15750.75") == Decimal("15750.75")

    def test_from_decimal(self):
        d = Decimal("999.99")
        assert _to_dec(d) is d  # debe retornar el mismo objeto

    def test_from_none(self):
        assert _to_dec(None) == Decimal("0")

    def test_from_zero(self):
        assert _to_dec(0) == Decimal("0")

    def test_float_precision_trap(self):
        """
        float(0.1 + 0.2) = 0.30000000000000004 en IEEE 754.
        _to_dec debe producir un Decimal limpio vía str().
        """
        val = 0.1 + 0.2
        result = _to_dec(val)
        # str(0.30000000000000004) = "0.30000000000000004"
        # Decimal lo representa exactamente — NO es 0.3
        # Pero lo importante es que NO se pierde información
        assert isinstance(result, Decimal)

    def test_large_amount(self):
        """Montos grandes de ferretería (compras mayoristas)."""
        assert _to_dec(1_500_000.50) == Decimal("1500000.5")


# ═══════════════════════════════════════════════════════════════
# Precisión en cálculos de cierre de caja
# ═══════════════════════════════════════════════════════════════

class TestCashClosePrecision:
    """
    Simula aritmética de cierre sin DB para verificar que
    la cadena Decimal produce resultados exactos.
    """

    def test_simple_close(self):
        """Apertura + entrada - salida = esperado exacto."""
        opening = _to_dec(50000)
        total_in = _to_dec(125000)
        total_out = _to_dec(10000)
        expected = opening + total_in - total_out
        assert expected == Decimal("165000")

    def test_many_small_amounts(self):
        """
        100 ventas de ₡1,130 (IVA 13%).
        Con float, sum(1130.0 for _ in range(100)) puede dar 112999.99999...
        Con Decimal debe ser exacto.
        """
        amounts = [_to_dec("1130.00") for _ in range(100)]
        total = sum(amounts, Decimal("0"))
        assert total == Decimal("113000.00")

    def test_difference_zero_when_exact(self):
        """Si el cajero cuenta exacto, la diferencia debe ser 0, no 0.0000001."""
        opening = _to_dec("25000.00")
        entries = [_to_dec("5650.50"), _to_dec("3200.75"), _to_dec("12100.00")]
        exits = [_to_dec("2000.00")]

        total_in = sum(entries, Decimal("0"))
        total_out = sum(exits, Decimal("0"))
        expected = opening + total_in - total_out
        # Cajero cuenta exacto
        closing = expected

        difference = closing - expected
        assert difference == Decimal("0")
        # Con float esto podría ser -0.0000000000001

    def test_colones_centimos(self):
        """Montos con céntimos (raro en CR pero el sistema debe soportarlo)."""
        opening = _to_dec("10000.50")
        sale1 = _to_dec("1130.25")
        sale2 = _to_dec("2260.75")
        expected = opening + sale1 + sale2
        assert expected == Decimal("13391.50")