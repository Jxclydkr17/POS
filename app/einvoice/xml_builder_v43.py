from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import xml.etree.ElementTree as ET
from app.utils.dt import now_cr
# FASE 4.2 — Fix 4.2: declaración XML estándar (comillas dobles)
from app.einvoice._xml_emit import xml_to_bytes


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _money(v) -> str:
    return str(_d(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _text(s: str | None, default: str = "") -> str:
    s = (s or "").strip()
    return s if s else default


def _digits_only(s: str | None) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _id_type_code(v: str | None) -> str:
    """
    01 Física
    02 Jurídica
    03 DIMEX
    04 NITE
    """
    s = (v or "").strip()

    if s in {"01", "02", "03", "04"}:
        return s

    up = s.upper()

    if "JUR" in up:
        return "02"
    if "DIMEX" in up:
        return "03"
    if "NITE" in up:
        return "04"
    if "FIS" in up:
        return "01"

    return "01"


def _tax_percent(v) -> Decimal:
    """
    Si viene 0.13 → 13
    Si viene 13 → 13
    """
    r = _d(v)
    if r <= 0:
        return Decimal("0")

    if r <= 1:
        return r * Decimal("100")

    return r


def _codigo_tarifa_iva(tasa_pct: Decimal) -> str:
    """
    Devuelve CodigoTarifa para IVA según la tasa.
    Nota: 13% -> "08" te lo confirmo porque ya lo estás usando y es el más común.
    Para otras tasas, dejé un mapeo típico; si Hacienda te lo marca, lo ajustamos.
    """
    t = tasa_pct.quantize(Decimal("0.01"))
    if t == Decimal("13.00"):
        return "08"
    if t == Decimal("8.00"):
        return "07"
    if t == Decimal("4.00"):
        return "06"
    if t == Decimal("2.00"):
        return "05"
    if t == Decimal("1.00"):
        return "04"
    if t == Decimal("0.00"):
        return "01"  # exento / sin tarifa
    return "08"


def build_xml_for_sale(
    *,
    document_type: str,
    clave: str,
    consecutivo: str,
    issuer: dict,
    customer: dict | None,
    sale: dict,
    lines: list[dict],
) -> str:

    if document_type == "01":
        root_name = "FacturaElectronica"
    elif document_type == "04":
        root_name = "TiqueteElectronico"
    else:
        raise ValueError(f"document_type inválido: {document_type}")

    root = ET.Element(root_name)

    # ---------------- ENCABEZADO ----------------

    ET.SubElement(root, "Clave").text = clave
    ET.SubElement(root, "NumeroConsecutivo").text = consecutivo
    ET.SubElement(root, "FechaEmision").text = now_cr().isoformat(timespec="seconds")

    # ---------------- EMISOR ----------------

    emisor = ET.SubElement(root, "Emisor")
    ET.SubElement(emisor, "Nombre").text = _text(issuer.get("legal_name"))

    identificacion = ET.SubElement(emisor, "Identificacion")
    ET.SubElement(identificacion, "Tipo").text = _id_type_code(issuer.get("id_type"))
    ET.SubElement(identificacion, "Numero").text = _digits_only(issuer.get("id_number"))

    if issuer.get("commercial_name"):
        ET.SubElement(emisor, "NombreComercial").text = issuer["commercial_name"]

    # Teléfono (si existe)
    phone_digits = _digits_only(issuer.get("phone"))
    if phone_digits:
        tel = ET.SubElement(emisor, "Telefono")
        ET.SubElement(tel, "CodigoPais").text = "506"
        ET.SubElement(tel, "NumTelefono").text = phone_digits[-8:]

    ET.SubElement(emisor, "CorreoElectronico").text = _text(issuer.get("email"))

    # ---------------- RECEPTOR ----------------

    if customer and (_text(customer.get("id_number")) or _text(customer.get("email"))):

        receptor = ET.SubElement(root, "Receptor")
        ET.SubElement(receptor, "Nombre").text = _text(customer.get("name"))

        if _text(customer.get("id_number")):
            rid = ET.SubElement(receptor, "Identificacion")
            ET.SubElement(rid, "Tipo").text = _id_type_code(customer.get("id_type"))
            ET.SubElement(rid, "Numero").text = _digits_only(customer.get("id_number"))

        if _text(customer.get("email")):
            ET.SubElement(receptor, "CorreoElectronico").text = _text(customer.get("email"))

    # ---------------- CONDICIÓN / PAGO ----------------

    ET.SubElement(root, "CondicionVenta").text = "01"  # Contado
    ET.SubElement(root, "MedioPago").text = "01"       # Efectivo

    # ---------------- DETALLE ----------------

    detalle = ET.SubElement(root, "DetalleServicio")

    total_gravado = Decimal("0")
    total_exento = Decimal("0")
    total_impuesto = Decimal("0")
    total_descuento = Decimal("0")

    for i, ln in enumerate(lines, start=1):

        qty = _d(ln["quantity"])
        unit = _d(ln["unit_price"])
        discount_pct = _d(ln.get("discount_percent", 0))
        cabys = _text(ln.get("cabys_code"))
        name = _text(ln.get("name"))

        line_sub = qty * unit
        line_disc = (line_sub * discount_pct / Decimal("100")) if discount_pct else Decimal("0")
        line_net = line_sub - line_disc

        tax_rate_pct = _tax_percent(ln.get("tax_rate", 0))
        tax_amt = (line_net * tax_rate_pct / Decimal("100")) if tax_rate_pct else Decimal("0")

        if tax_rate_pct > 0:
            total_gravado += line_net
        else:
            total_exento += line_net

        total_impuesto += tax_amt
        total_descuento += line_disc

        linea = ET.SubElement(detalle, "LineaDetalle")

        ET.SubElement(linea, "NumeroLinea").text = str(i)

        # CABYS correcto
        codigo = ET.SubElement(linea, "Codigo")
        ET.SubElement(codigo, "Tipo").text = "04"
        ET.SubElement(codigo, "Codigo").text = cabys

        ET.SubElement(linea, "Cantidad").text = _money(qty)
        ET.SubElement(linea, "UnidadMedida").text = ln.get("unit_type", "Unid") or "Unid"
        ET.SubElement(linea, "Detalle").text = name
        ET.SubElement(linea, "PrecioUnitario").text = _money(unit)
        ET.SubElement(linea, "MontoTotal").text = _money(line_sub)

        if line_disc > 0:
            desc = ET.SubElement(linea, "Descuento")
            ET.SubElement(desc, "MontoDescuento").text = _money(line_disc)
            ET.SubElement(desc, "NaturalezaDescuento").text = "Descuento"

        ET.SubElement(linea, "SubTotal").text = _money(line_net)

        if tax_amt > 0:
            imp = ET.SubElement(linea, "Impuesto")
            ET.SubElement(imp, "Codigo").text = "01"  # IVA
            ET.SubElement(imp, "CodigoTarifa").text = _codigo_tarifa_iva(tax_rate_pct)
            ET.SubElement(imp, "Tarifa").text = _money(tax_rate_pct)
            ET.SubElement(imp, "Monto").text = _money(tax_amt)

        ET.SubElement(linea, "MontoTotalLinea").text = _money(line_net + tax_amt)

    # ---------------- RESUMEN ----------------

    resumen = ET.SubElement(root, "ResumenFactura")
    ET.SubElement(resumen, "TotalGravado").text = _money(total_gravado)
    ET.SubElement(resumen, "TotalExento").text = _money(total_exento)
    ET.SubElement(resumen, "TotalVenta").text = _money(total_gravado + total_exento)
    ET.SubElement(resumen, "TotalDescuentos").text = _money(total_descuento)
    ET.SubElement(resumen, "TotalVentaNeta").text = _money((total_gravado + total_exento) - total_descuento)
    ET.SubElement(resumen, "TotalImpuesto").text = _money(total_impuesto)
    ET.SubElement(resumen, "TotalComprobante").text = _money(((total_gravado + total_exento) - total_descuento) + total_impuesto)

    xml_bytes = xml_to_bytes(root)
    return xml_bytes.decode("utf-8")