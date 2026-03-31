# app/utils/unit_helpers.py
"""
Helpers para unidades de medida.
Centraliza etiquetas, códigos de Hacienda y formateo de cantidades.
"""
from decimal import Decimal


# ─── Etiquetas para UI ──────────────────────────────────────
UNIT_LABELS = {
    "Unid": "unidades",
    "Kg":   "kg",
    "g":    "g",
    "m":    "m",
    "cm":   "cm",
    "L":    "L",
    "mL":   "mL",
}

# ─── Códigos válidos para UnidadMedida en FE de Hacienda ────
# Ref: Anexo de la Resolución DGT-R-033-2019 (Costa Rica)
HACIENDA_UNIT_CODES = {
    "Unid": "Unid",
    "Kg":   "Kg",
    "g":    "g",
    "m":    "m",
    "cm":   "cm",
    "L":    "L",
    "mL":   "mL",
}

# ─── Todas las unidades válidas ─────────────────────────────
VALID_UNIT_TYPES = tuple(UNIT_LABELS.keys())


def is_unit_based(unit_type: str) -> bool:
    """True si el producto se vende por unidades enteras (sin fracciones)."""
    return unit_type in ("Unid",)


def format_quantity(qty, unit_type: str) -> str:
    """Formatea la cantidad según el tipo de unidad.

    Ejemplos:
        format_quantity(5, "Unid")  → "5"
        format_quantity(0.5, "Kg")  → "0.5 kg"
        format_quantity(1.750, "m") → "1.75 m"
        format_quantity(2.0, "Kg")  → "2 kg"

    Args:
        qty: Cantidad (int, float o Decimal)
        unit_type: Tipo de unidad ("Unid", "Kg", "m", etc.)

    Returns:
        String formateado para mostrar en UI/PDF
    """
    qty_dec = Decimal(str(qty))

    if is_unit_based(unit_type):
        # Unidades enteras: mostrar sin decimales
        return str(int(qty_dec))

    label = UNIT_LABELS.get(unit_type, unit_type)

    # Mostrar hasta 3 decimales, quitando ceros innecesarios
    formatted = f"{qty_dec:.3f}".rstrip("0").rstrip(".")
    return f"{formatted} {label}"


def get_hacienda_unit_code(unit_type: str) -> str:
    """Devuelve el código de UnidadMedida para la factura electrónica.

    Args:
        unit_type: Tipo de unidad del producto

    Returns:
        Código válido para el XML de Hacienda (default: "Unid")
    """
    return HACIENDA_UNIT_CODES.get(unit_type, "Unid")