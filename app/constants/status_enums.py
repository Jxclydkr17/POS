# app/constants/status_enums.py
"""
Enumeraciones de estado centralizadas para ventas, facturación
electrónica y proformas.

Cada enum hereda de (str, enum.Enum) para ser directamente comparable
con strings, compatible con columnas String de SQLAlchemy, y
serializable en JSON sin conversiones adicionales.

USO:
    from app.constants.status_enums import SaleStatus, InvoiceStatus

    if sale.status == SaleStatus.ANULADA:
        ...

    einv = ElectronicInvoice(status=InvoiceStatus.PENDING)
"""
import enum


class SaleStatus(str, enum.Enum):
    """Estados de una venta."""
    ACTIVA = "ACTIVA"
    ANULADA = "ANULADA"


class InvoiceStatus(str, enum.Enum):
    """Estados de factura electrónica (FE) y mensajes receptor.

    Pipeline completo:
    PENDING → XML_READY → XML_UNSIGNED → (SIGN_ERROR)
           → SENT → (SEND_ERROR) → ACCEPTED / REJECTED
           → (FAILED después de MAX reintentos)
    """
    PENDING = "PENDING"
    XML_READY = "XML_READY"
    XML_UNSIGNED = "XML_UNSIGNED"
    SIGN_ERROR = "SIGN_ERROR"
    XSD_ERROR = "XSD_ERROR"
    SENT = "SENT"
    SEND_ERROR = "SEND_ERROR"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"
    QUEUED = "QUEUED"
    FAILED = "FAILED"


class ProformaStatus(str, enum.Enum):
    """Estados de proforma / cotización."""
    VIGENTE = "VIGENTE"
    VENCIDA = "VENCIDA"
    CONVERTIDA = "CONVERTIDA"
    ANULADA = "ANULADA"


class CashMovementType(str, enum.Enum):
    """Tipos de movimiento de caja.

    ── FASE 6 — Fix 6.2 ──
    Centraliza los valores que antes eran strings sueltos ("in"/"out"/"IN"/"OUT")
    repartidos por el código. El service normaliza a lowercase para la BD,
    y las queries deben comparar contra estos valores.

    Uso:
        from app.constants.status_enums import CashMovementType

        # Al registrar:
        register_cash_movement(..., movement_type=CashMovementType.IN, ...)

        # En queries:
        CashMovement.type == CashMovementType.IN
    """
    IN = "in"
    OUT = "out"