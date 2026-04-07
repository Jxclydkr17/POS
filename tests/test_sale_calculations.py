# tests/test_sale_calculations.py
"""
FASE 5 — Tests para la lógica de cálculo de ventas.

Estos tests cubren las funciones puras de cálculo que determinan
cuánto cobra la ferretería y cuánto reporta a Hacienda.
Un error aquí significa cobrar de más/menos o reportar IVA incorrecto.

No necesitan base de datos — son funciones puras con Decimal.
"""

import pytest
from decimal import Decimal

from app.db.crud.sale_crud import calc_line_tax, normalize_tax_rate


# ═══════════════════════════════════════════════════════════════
# normalize_tax_rate: convierte tasas decimales a porcentaje
# ═══════════════════════════════════════════════════════════════

class TestNormalizeTaxRate:
    """Garantiza que la tasa de IVA siempre quede como porcentaje (ej: 13, no 0.13)."""

    def test_already_percentage(self):
        assert normalize_tax_rate(13) == Decimal("13")

    def test_decimal_fraction_to_percentage(self):
        """0.13 → 13 (frontend antiguo podría enviar así)."""
        assert normalize_tax_rate(0.13) == Decimal("13")

    def test_zero(self):
        assert normalize_tax_rate(0) == Decimal("0")

    def test_none(self):
        assert normalize_tax_rate(None) == Decimal("0")

    def test_iva_reduced_1(self):
        """IVA reducido 1% (canasta básica)."""
        assert normalize_tax_rate(1) == Decimal("1")

    def test_iva_reduced_2(self):
        """IVA reducido 2% (salud privada)."""
        assert normalize_tax_rate(2) == Decimal("2")

    def test_iva_reduced_4(self):
        """IVA reducido 4% (boletos aéreos)."""
        assert normalize_tax_rate(4) == Decimal("4")

    def test_decimal_fraction_small(self):
        """0.04 → 4."""
        assert normalize_tax_rate(0.04) == Decimal("4")


# ═══════════════════════════════════════════════════════════════
# calc_line_tax: cálculo de subtotal, IVA y total por línea
# ═══════════════════════════════════════════════════════════════

class TestCalcLineTax:
    """
    Verifica que los montos de cada línea de venta sean correctos.
    El precio incluye IVA (precio final al consumidor).
    """

    def test_basic_sale_13_percent(self):
        """Producto a ₡1,130 con IVA 13%, qty 1, sin descuento."""
        subtotal, tax, total = calc_line_tax(
            unit_price=Decimal("1130"),
            quantity=Decimal("1"),
            discount_percent=Decimal("0"),
            tax_rate_pct=Decimal("13"),
        )
        # Precio neto: 1130 / 1.13 = 1000
        # IVA: 1000 * 0.13 = 130
        # Total: 1000 + 130 = 1130
        assert abs(total - Decimal("1130")) < Decimal("0.01")
        assert abs(tax - Decimal("130")) < Decimal("0.01")
        assert abs(subtotal - Decimal("1000")) < Decimal("0.01")

    def test_exempt_product(self):
        """Producto exento (IVA 0%)."""
        subtotal, tax, total = calc_line_tax(
            unit_price=Decimal("5000"),
            quantity=Decimal("3"),
            discount_percent=Decimal("0"),
            tax_rate_pct=Decimal("0"),
        )
        assert total == Decimal("15000")
        assert tax == Decimal("0")
        assert subtotal == Decimal("15000")

    def test_discount_applied(self):
        """10% de descuento sobre producto con IVA 13%."""
        subtotal, tax, total = calc_line_tax(
            unit_price=Decimal("1130"),
            quantity=Decimal("1"),
            discount_percent=Decimal("10"),
            tax_rate_pct=Decimal("13"),
        )
        # Neto: 1130/1.13 = 1000, desc 10% → 900
        # IVA: 900 * 0.13 = 117
        # Total: 900 + 117 = 1017
        assert abs(total - Decimal("1017")) < Decimal("0.01")

    def test_fractional_quantity_kg(self):
        """2.5 kg de producto a ₡1,130/kg con IVA 13%."""
        subtotal, tax, total = calc_line_tax(
            unit_price=Decimal("1130"),
            quantity=Decimal("2.5"),
            discount_percent=Decimal("0"),
            tax_rate_pct=Decimal("13"),
        )
        # Neto: 1130/1.13 * 2.5 = 2500
        # IVA: 2500 * 0.13 = 325
        # Total: 2825
        assert abs(total - Decimal("2825")) < Decimal("0.01")

    def test_iva_reduced_1_percent(self):
        """Canasta básica: IVA 1%."""
        subtotal, tax, total = calc_line_tax(
            unit_price=Decimal("1010"),
            quantity=Decimal("1"),
            discount_percent=Decimal("0"),
            tax_rate_pct=Decimal("1"),
        )
        # Neto: 1010/1.01 = 1000
        # IVA: 1000 * 0.01 = 10
        assert abs(total - Decimal("1010")) < Decimal("0.01")
        assert abs(tax - Decimal("10")) < Decimal("0.01")

    def test_precision_no_float_drift(self):
        """
        Verifica que no hay drift de IEEE 754.
        Ejemplo clásico: 0.1 + 0.2 != 0.3 en float.
        Con Decimal debe ser exacto.
        """
        subtotal, tax, total = calc_line_tax(
            unit_price=Decimal("1130"),
            quantity=Decimal("3"),
            discount_percent=Decimal("0"),
            tax_rate_pct=Decimal("13"),
        )
        # 3 unidades a 1130 = 3390 exacto
        assert abs(total - Decimal("3390")) < Decimal("0.01")

    def test_large_quantity_precision(self):
        """100 unidades — verifica que la suma no acumule error."""
        subtotal, tax, total = calc_line_tax(
            unit_price=Decimal("565"),
            quantity=Decimal("100"),
            discount_percent=Decimal("0"),
            tax_rate_pct=Decimal("13"),
        )
        # 100 × 565 = 56500 total
        assert abs(total - Decimal("56500")) < Decimal("0.01")

    def test_total_equals_subtotal_plus_tax(self):
        """Invariante: total = subtotal + tax_amount siempre."""
        subtotal, tax, total = calc_line_tax(
            unit_price=Decimal("7345.50"),
            quantity=Decimal("2.75"),
            discount_percent=Decimal("5"),
            tax_rate_pct=Decimal("13"),
        )
        assert abs(total - (subtotal + tax)) < Decimal("0.00001")

    def test_full_discount(self):
        """100% de descuento = total cero."""
        subtotal, tax, total = calc_line_tax(
            unit_price=Decimal("5000"),
            quantity=Decimal("1"),
            discount_percent=Decimal("100"),
            tax_rate_pct=Decimal("13"),
        )
        assert total == Decimal("0")
        assert tax == Decimal("0")