"""
app/utils/escpos_ticket.py — Generación de comandos ESC/POS para tickets.

Cierra la deuda del Fix 2.5 (Fase 2): convierte datos de venta o de
comprobante electrónico en una secuencia de bytes ESC/POS lista para
enviar a una impresora térmica POS (típicamente 58mm o 80mm de papel).

Backend: python-escpos (clase `Dummy`), que acumula los comandos
emitidos sin abrir ningún dispositivo y los entrega como `bytes`. El
envío físico (TCP/IP, USB) lo hace `app.utils.print_ticket`. Esta
separación permite testear el generador sin impresora y compartir un
solo pipeline de bytes entre los distintos transportes.

NO incluye lógica de red ni de USB. Solo bytes.

USO:
    from app.utils.escpos_ticket import build_sale_ticket_bytes
    data = build_sale_ticket_bytes(sale_data, business_name="Mi Negocio")
    # data es bytes — entregar a print_to_thermal() o equivalente.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

# python-escpos es dependencia obligatoria desde Fase 2.5++.
# Si no está instalada, las funciones de este módulo levantan ImportError
# en runtime (el caller decide cómo manejarlo). NO importamos de manera
# perezosa porque sin la librería el módulo no puede cumplir su contrato.
from escpos.printer import Dummy

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Configuración de papel
# ─────────────────────────────────────────────────────────
# Caracteres por línea para distintos anchos físicos comunes.
# 58mm rinde ~32 caracteres con fuente A normal.
# 80mm rinde ~48 caracteres con fuente A normal.
# El usuario puede pasar el ancho deseado; la fuente y la lógica de
# alineado se ajustan en consecuencia.
_COLS_BY_WIDTH = {
    58: 32,
    80: 48,
}

DEFAULT_PAPER_WIDTH_MM = 80


def _cols(paper_width_mm: int) -> int:
    return _COLS_BY_WIDTH.get(paper_width_mm, _COLS_BY_WIDTH[DEFAULT_PAPER_WIDTH_MM])


def _hr(paper_width_mm: int, char: str = "-") -> str:
    """Línea horizontal del ancho del papel."""
    return char * _cols(paper_width_mm) + "\n"


def _two_col(left: str, right: str, paper_width_mm: int) -> str:
    """
    Imprime `left` a la izquierda y `right` a la derecha, padding con
    espacios al medio. Si la suma excede el ancho, recorta `left`.
    """
    cols = _cols(paper_width_mm)
    right = str(right)
    left = str(left)
    space = cols - len(right)
    if space < 1:
        # right ya ocupa toda la línea — dejamos solo right truncado
        return right[:cols] + "\n"
    if len(left) > space - 1:
        left = left[: max(0, space - 2)] + "…"
    pad = cols - len(left) - len(right)
    return left + " " * max(1, pad) + right + "\n"


def _fmt_money(value: Any) -> str:
    """Formatea un valor monetario con dos decimales y separador de miles."""
    if value is None:
        return "0.00"
    try:
        d = Decimal(str(value))
    except Exception:
        return str(value)
    # f-string con coma como separador de miles (estilo CR-friendly).
    # No agregamos símbolo aquí para no duplicarlo cuando ya viene en el
    # caller — los métodos que arman el ticket lo prefijan si hace falta.
    return f"{d:,.2f}"


def _safe_text(p: Dummy, text: str) -> None:
    """
    Envía texto a la Dummy aplicando 'magic encode' (la propia librería
    elige la code page). Si el texto trae caracteres que la code page
    activa no soporta, python-escpos los maneja vía replace por default.
    """
    if text is None:
        return
    p.text(text)


# ─────────────────────────────────────────────────────────
# Ticket de venta (genérico)
# ─────────────────────────────────────────────────────────

def build_sale_ticket_bytes(
    sale_data: dict,
    business_name: str = "Mi Negocio",
    business_id: str | None = None,
    business_address: str | None = None,
    business_phone: str | None = None,
    paper_width_mm: int = DEFAULT_PAPER_WIDTH_MM,
    cut: bool = True,
    profile: str | None = None,
) -> bytes:
    """
    Genera bytes ESC/POS para un ticket de venta a partir del dict
    `sale_data` que usa `ui.dialogs.sale_ticket_dialog`.

    sale_data esperado (campos):
        sale_id (int|str)
        customer_name (str, opcional)
        payment_method (str)
        items (list[dict]) — cada uno con: name, quantity, subtotal
        total (Decimal/float/str)
        amount_paid (opcional)
        change (opcional)
        created_at (str, opcional)

    Args:
        business_name / business_id / business_address / business_phone:
            Cabecera de la empresa. Llenar desde Settings/IssuerProfile.
        paper_width_mm: 58 o 80. Otros valores caen al default (80).
        cut: si True, agrega comando de corte al final.
        profile: nombre del perfil de python-escpos (e.g. "TM-T20II").
            Si la impresora destino no soporta corte total, el profile
            ayuda a que la librería emita el variante correcto.

    Returns:
        bytes con la secuencia ESC/POS completa.
    """
    if profile:
        p = Dummy(profile=profile)
    else:
        p = Dummy()

    # ── Cabecera ──
    p.set(align="center", bold=True, double_height=True, double_width=True)
    _safe_text(p, (business_name or "Mi Negocio") + "\n")
    p.set(align="center", bold=False, double_height=False, double_width=False)

    if business_id:
        _safe_text(p, f"Céd: {business_id}\n")
    if business_address:
        _safe_text(p, business_address + "\n")
    if business_phone:
        _safe_text(p, f"Tel: {business_phone}\n")

    created_at = sale_data.get("created_at") or ""
    if created_at:
        _safe_text(p, str(created_at) + "\n")

    _safe_text(p, _hr(paper_width_mm))

    # ── Datos de la venta ──
    p.set(align="left")
    sale_id = sale_data.get("sale_id", "")
    _safe_text(p, f"Tiquete #: {sale_id}\n")

    customer = sale_data.get("customer_name") or "Cliente general"
    _safe_text(p, f"Cliente : {customer}\n")

    payment_method = sale_data.get("payment_method") or ""
    if payment_method:
        _safe_text(p, f"Pago    : {payment_method}\n")

    _safe_text(p, _hr(paper_width_mm))

    # ── Items ──
    p.set(align="left", bold=True)
    _safe_text(p, "Detalle:\n")
    p.set(align="left", bold=False)

    items = sale_data.get("items") or []
    for item in items:
        name = str(item.get("name", "—"))
        qty = item.get("quantity", 1)
        subtotal = item.get("subtotal", 0)

        # Línea 1: nombre del producto. Si es largo, lo envolvemos.
        # python-escpos no envuelve texto solo — recortamos manualmente
        # al ancho del papel para evitar saltos de línea raros.
        cols = _cols(paper_width_mm)
        if len(name) > cols:
            # Imprimir en varias líneas
            for i in range(0, len(name), cols):
                _safe_text(p, name[i:i + cols] + "\n")
        else:
            _safe_text(p, name + "\n")

        # Línea 2: cantidad x precio   subtotal
        try:
            qty_fmt = f"x{Decimal(str(qty)).normalize()}" if qty else "x1"
        except Exception:
            qty_fmt = f"x{qty}"

        _safe_text(p, _two_col(f"  {qty_fmt}", _fmt_money(subtotal), paper_width_mm))

    _safe_text(p, _hr(paper_width_mm))

    # ── Totales ──
    p.set(align="left", bold=True, double_height=False, double_width=False)
    total = sale_data.get("total", 0)
    _safe_text(p, _two_col("TOTAL", _fmt_money(total), paper_width_mm))
    p.set(bold=False)

    if "amount_paid" in sale_data and sale_data["amount_paid"] is not None:
        _safe_text(p, _two_col("Pagó con", _fmt_money(sale_data["amount_paid"]), paper_width_mm))
    if "change" in sale_data and sale_data["change"] is not None:
        _safe_text(p, _two_col("Cambio", _fmt_money(sale_data["change"]), paper_width_mm))

    _safe_text(p, _hr(paper_width_mm))

    # ── Pie ──
    p.set(align="center")
    _safe_text(p, "¡Gracias por su compra!\n")
    p.set(align="left")

    # Salto de papel antes del corte para que el texto no quede pegado
    # al peine — algunas impresoras (Epson TM-T20) cortan en la línea
    # actual y se "comen" la última fila si no hay feed extra.
    p.text("\n\n\n")

    if cut:
        # cut() prueba full → partial → none según el perfil.
        try:
            p.cut()
        except Exception as e:
            # No es fatal; algunos perfiles no soportan corte. Solo se
            # pierde el corte automático — el usuario rasga manual.
            logger.warning(f"ESC/POS cut no soportado por el perfil: {e}")

    return p.output


# ─────────────────────────────────────────────────────────
# Ticket de comprobante electrónico (Hacienda CR)
# ─────────────────────────────────────────────────────────

def build_einvoice_ticket_bytes(
    db,
    einvoice_id: int,
    paper_width_mm: int = DEFAULT_PAPER_WIDTH_MM,
    cut: bool = True,
    profile: str | None = None,
) -> bytes:
    """
    Genera bytes ESC/POS para un comprobante electrónico (Tiquete o
    Factura electrónica) leyendo desde la base de datos.

    Incluye:
      - Datos del emisor (IssuerProfile / Settings)
      - Tipo de documento + consecutivo + clave numérica
      - Cliente (si existe)
      - Detalle de líneas (productos / descripciones)
      - Total
      - QR con URL de verificación de Hacienda
      - Estado ante Hacienda (ACEPTADO/RECHAZADO/PENDIENTE)

    Args:
        db: Sesión de SQLAlchemy
        einvoice_id: ID del ElectronicInvoice a imprimir
        paper_width_mm: 58 o 80
        cut: True para cortar al final
        profile: perfil python-escpos opcional (e.g. "TM-T20II")

    Returns:
        bytes ESC/POS.

    Raises:
        ValueError: si no se encuentra el einvoice.
    """
    from app.db.models.electronic_invoice import ElectronicInvoice
    from app.db.models.sale import Sale
    from app.db.models.sale_detail import SaleDetail
    from app.db.models.customer import Customer
    from app.db.models.product import Product
    from app.db.models.issuer_profile import IssuerProfile
    from app.db.models.settings import Settings

    ei = db.query(ElectronicInvoice).filter(ElectronicInvoice.id == einvoice_id).first()
    if not ei:
        raise ValueError(f"ElectronicInvoice {einvoice_id} no existe")

    sale = db.query(Sale).filter(Sale.id == ei.sale_id).first()
    if not sale:
        raise ValueError(f"Sale {ei.sale_id} (de einvoice {einvoice_id}) no existe")

    issuer = db.query(IssuerProfile).filter(IssuerProfile.id == 1).first()
    settings = db.query(Settings).filter(Settings.id == 1).first()

    # Nombre y datos del emisor: priorizar IssuerProfile, fallback a Settings.
    business_name = (
        (issuer.commercial_name if issuer else None)
        or (issuer.legal_name if issuer else None)
        or (settings.business_name if settings else None)
        or "Mi Negocio"
    )
    business_id = (issuer.id_number if issuer else None) or (settings.id_number if settings else None)
    business_phone = (issuer.phone if issuer else None) or (settings.phone if settings else None)
    business_address = settings.address if settings else None

    # Tipo de documento (label)
    DOC_TYPE_LABELS = {
        "01": "FACTURA ELECTRÓNICA",
        "02": "NOTA DÉBITO ELECTRÓNICA",
        "03": "NOTA CRÉDITO ELECTRÓNICA",
        "04": "TIQUETE ELECTRÓNICO",
        "05": "CONFIRMACIÓN ACEPTACIÓN",
        "06": "CONFIRMACIÓN ACEPTACIÓN PARCIAL",
        "07": "CONFIRMACIÓN RECHAZO",
        "08": "FACTURA ELECTRÓNICA DE COMPRA",
        "09": "FACTURA ELECTRÓNICA DE EXPORTACIÓN",
        "10": "RECIBO ELECTRÓNICO DE PAGO",
    }
    doc_label = DOC_TYPE_LABELS.get(ei.document_type, "COMPROBANTE ELECTRÓNICO")

    STATUS_LABELS = {
        "ACCEPTED": "ACEPTADO por Hacienda",
        "REJECTED": "RECHAZADO por Hacienda",
        "SENT": "Enviado (pendiente respuesta)",
        "XML_READY": "XML listo (no enviado)",
        "PENDING": "Pendiente",
    }
    status_label = STATUS_LABELS.get(ei.status, ei.status or "")

    customer_name = None
    if sale.customer_id:
        cust = db.query(Customer).filter(Customer.id == sale.customer_id).first()
        if cust:
            customer_name = cust.name

    # Líneas
    details = db.query(SaleDetail).filter(SaleDetail.sale_id == sale.id).all()

    # ── Generación ESC/POS ──
    p = Dummy(profile=profile) if profile else Dummy()

    # Cabecera empresa
    p.set(align="center", bold=True, double_height=True, double_width=True)
    _safe_text(p, business_name + "\n")
    p.set(align="center", bold=False, double_height=False, double_width=False)
    if business_id:
        _safe_text(p, f"Céd: {business_id}\n")
    if business_address:
        _safe_text(p, business_address + "\n")
    if business_phone:
        _safe_text(p, f"Tel: {business_phone}\n")
    _safe_text(p, _hr(paper_width_mm))

    # Tipo de documento
    p.set(align="center", bold=True)
    _safe_text(p, doc_label + "\n")
    p.set(align="center", bold=False)

    if ei.consecutivo:
        _safe_text(p, f"Consec: {ei.consecutivo}\n")
    _safe_text(p, _hr(paper_width_mm))

    # Datos de venta
    p.set(align="left")
    created = sale.created_at.strftime("%Y-%m-%d %H:%M") if sale.created_at else ""
    if created:
        _safe_text(p, f"Fecha   : {created}\n")
    _safe_text(p, f"Tiquete : {sale.id}\n")
    if customer_name:
        _safe_text(p, f"Cliente : {customer_name}\n")
    if sale.payment_method:
        _safe_text(p, f"Pago    : {sale.payment_method}\n")
    _safe_text(p, _hr(paper_width_mm))

    # Items
    p.set(align="left", bold=True)
    _safe_text(p, "Detalle:\n")
    p.set(align="left", bold=False)

    cols = _cols(paper_width_mm)
    for d in details:
        # Nombre del producto
        if d.is_common:
            name = d.common_description or "Producto"
        elif d.product_id:
            prod = db.query(Product).filter(Product.id == d.product_id).first()
            name = prod.name if prod else f"Producto #{d.product_id}"
        else:
            name = "Producto"

        if len(name) > cols:
            for i in range(0, len(name), cols):
                _safe_text(p, name[i:i + cols] + "\n")
        else:
            _safe_text(p, name + "\n")

        try:
            qty_fmt = f"x{Decimal(str(d.quantity)).normalize()}"
        except Exception:
            qty_fmt = f"x{d.quantity}"

        _safe_text(p, _two_col(f"  {qty_fmt}", _fmt_money(d.subtotal), paper_width_mm))

    _safe_text(p, _hr(paper_width_mm))

    # Total
    p.set(align="left", bold=True)
    _safe_text(p, _two_col("TOTAL", _fmt_money(sale.total), paper_width_mm))
    p.set(bold=False)

    _safe_text(p, _hr(paper_width_mm))

    # Clave
    if ei.clave:
        p.set(align="center", bold=False)
        _safe_text(p, "Clave numérica:\n")
        # Imprimir en bloques para que sea legible en 80mm/58mm
        clave = ei.clave
        block_size = cols
        for i in range(0, len(clave), block_size):
            _safe_text(p, clave[i:i + block_size] + "\n")
        _safe_text(p, _hr(paper_width_mm))

    # QR de verificación
    if ei.clave:
        try:
            verify_url = f"https://www.hacienda.go.cr/fe/comprobantes?clave={ei.clave}"
            p.set(align="center")
            # qr(...) usa el comando nativo cuando está disponible; en
            # impresoras antiguas (sin soporte nativo) python-escpos
            # fabrica un raster bitmap del QR — funciona igual.
            p.qr(verify_url, size=6, native=True)
            _safe_text(p, "Verifique en hacienda.go.cr\n")
        except Exception as e:
            # No es fatal — solo se omite el QR. La clave numérica ya
            # se imprimió arriba, que es lo que Hacienda exige.
            logger.warning(f"No se pudo generar QR ESC/POS: {e}")

    # Estado
    if status_label:
        p.set(align="center", bold=True)
        _safe_text(p, status_label + "\n")
        p.set(align="center", bold=False)

    p.text("\n\n\n")
    if cut:
        try:
            p.cut()
        except Exception as e:
            logger.warning(f"ESC/POS cut no soportado por el perfil: {e}")

    return p.output