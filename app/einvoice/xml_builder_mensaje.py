"""
app/einvoice/xml_builder_mensaje.py — Generador de MensajeReceptor v4.4

Genera el XML para la confirmación (aceptación/rechazo) de comprobantes
electrónicos recibidos de proveedores, según la estructura definida en
Anexos y Estructuras v4.4, sección III "Mensajes".

USO:
    from app.einvoice.xml_builder_mensaje import build_mensaje_receptor

    xml = build_mensaje_receptor(
        clave_comprobante="506...",
        cedula_emisor="3101123456",
        fecha_emision="2025-03-26T14:30:00-06:00",
        mensaje=1,  # 1=Aceptado, 2=Parcial, 3=Rechazado
        cedula_receptor="3102654321",
        consecutivo_receptor="00100001050000000001",
        codigo_actividad="523400",
        condicion_impuesto="01",
        monto_total_impuesto=130.00,
        total_factura=1130.00,
        detalle_mensaje="Comprobante aceptado",
        monto_impuesto_acreditar=130.00,
        monto_gasto_aplicable=0,
    )

Nota 11 (Mensajes):
    1 = Aceptado
    2 = Aceptación parcial
    3 = Rechazado

Nota 18 (CondicionImpuesto):
    01 = Genera crédito IVA
    02 = Genera Crédito parcial del IVA
    03 = Bienes de Capital
    04 = Gasto corriente no genera crédito
    05 = Proporcionalidad

FASE 3 FIX:
    - Namespace aplicado correctamente al root y todos los sub-elementos
      para que el XML pase validación XSD v4.4.
    - Antes el root tag era "MensajeReceptor" sin namespace, lo que
      causaba que lxml rechazara el XML por no coincidir con el schema.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.utils.dt import now_cr

# Namespace del MensajeReceptor (v4.4)
NS_MR = "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/mensajeReceptor"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

SCHEMA_LOCATION_MR = (
    "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/mensajeReceptor "
    "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/mensajeReceptor.xsd"
)

# Códigos válidos para Mensaje (nota 11)
MENSAJE_ACEPTADO = 1
MENSAJE_PARCIAL = 2
MENSAJE_RECHAZADO = 3
MENSAJES_VALIDOS = {MENSAJE_ACEPTADO, MENSAJE_PARCIAL, MENSAJE_RECHAZADO}

# Códigos válidos para CondicionImpuesto (nota 18)
CONDICIONES_IMPUESTO_VALIDAS = {"01", "02", "03", "04", "05"}


def _q5(v) -> str:
    """Formatea un decimal a 5 decimales."""
    d = Decimal(str(v)).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
    return str(d)


def _add(parent: ET.Element, tag: str, text: Optional[str] = None) -> ET.Element:
    """Agrega sub-elemento con namespace del MensajeReceptor."""
    el = ET.SubElement(parent, f"{{{NS_MR}}}{tag}")
    if text is not None:
        el.text = str(text)
    return el


def build_mensaje_receptor(
    *,
    clave_comprobante: str,
    cedula_emisor: str,
    fecha_emision: Optional[str] = None,
    mensaje: int,
    cedula_receptor: str,
    consecutivo_receptor: str,
    total_factura: float | Decimal,
    # Campos condicionales
    detalle_mensaje: str = "",
    monto_total_impuesto: Optional[float | Decimal] = None,
    codigo_actividad: Optional[str] = None,
    condicion_impuesto: Optional[str] = None,
    monto_impuesto_acreditar: Optional[float | Decimal] = None,
    monto_gasto_aplicable: Optional[float | Decimal] = None,
) -> str:
    """
    Genera el XML de MensajeReceptor para confirmar un comprobante recibido.

    Args:
        clave_comprobante: Clave de 50 dígitos del comprobante que se confirma
        cedula_emisor: Número de cédula del emisor (vendedor/proveedor)
        fecha_emision: Fecha RFC3339 de la confirmación (default: ahora)
        mensaje: 1=Aceptado, 2=Parcial, 3=Rechazado
        cedula_receptor: Número de cédula del receptor (quien confirma)
        consecutivo_receptor: Consecutivo del mensaje (20 dígitos, tipo 05/06/07)
        total_factura: Total del comprobante que se confirma
        detalle_mensaje: Motivo (obligatorio si mensaje=2 o 3)
        monto_total_impuesto: Monto de impuesto (si tiene)
        codigo_actividad: Actividad económica del receptor para crédito
        condicion_impuesto: Código nota 18 (01-05)
        monto_impuesto_acreditar: Monto que se acreditará
        monto_gasto_aplicable: Monto que se aplicará como gasto

    Returns:
        XML string del MensajeReceptor
    """
    # ── Validaciones ──
    if mensaje not in MENSAJES_VALIDOS:
        raise ValueError(f"Mensaje debe ser 1, 2 o 3. Recibido: {mensaje}")

    if not clave_comprobante or len(clave_comprobante) != 50:
        raise ValueError(f"Clave debe tener 50 dígitos. Recibida: {len(clave_comprobante) if clave_comprobante else 0}")

    if mensaje in (MENSAJE_PARCIAL, MENSAJE_RECHAZADO) and not detalle_mensaje:
        raise ValueError("DetalleMensaje es obligatorio cuando se rechaza o acepta parcialmente.")

    if condicion_impuesto and condicion_impuesto not in CONDICIONES_IMPUESTO_VALIDAS:
        raise ValueError(f"CondicionImpuesto inválida: {condicion_impuesto}. Válidos: {CONDICIONES_IMPUESTO_VALIDAS}")

    if not consecutivo_receptor or len(consecutivo_receptor) != 20:
        raise ValueError(f"Consecutivo del receptor debe tener 20 dígitos. Recibido: {len(consecutivo_receptor) if consecutivo_receptor else 0}")

    # ── Construir XML con namespace correcto ──
    ET.register_namespace("", NS_MR)
    ET.register_namespace("xsi", NS_XSI)

    # FASE 3 FIX: Root element DEBE tener el namespace para que valide con XSD
    root = ET.Element(f"{{{NS_MR}}}MensajeReceptor", {
        f"{{{NS_XSI}}}schemaLocation": SCHEMA_LOCATION_MR,
    })

    # Clave del comprobante que se confirma
    _add(root, "Clave", clave_comprobante)

    # Cédula del emisor (vendedor)
    _add(root, "NumeroCedulaEmisor", cedula_emisor)

    # Fecha de la confirmación
    fecha = fecha_emision or now_cr().isoformat(timespec="seconds")
    _add(root, "FechaEmisionDoc", fecha)

    # Mensaje (1/2/3)
    _add(root, "Mensaje", str(mensaje))

    # Detalle: obligatorio en rechazo/parcial, opcional en aceptación
    if detalle_mensaje:
        _add(root, "DetalleMensaje", detalle_mensaje[:160])

    # Monto total impuesto (condicional: cuando hay impuesto)
    if monto_total_impuesto is not None and float(monto_total_impuesto) > 0:
        _add(root, "MontoTotalImpuesto", _q5(monto_total_impuesto))

    # ── Campos v4.4 (DEBEN ir ANTES de TotalFactura según XSD) ──

    # Código de actividad económica del receptor
    if codigo_actividad:
        _add(root, "CodigoActividad", codigo_actividad.zfill(6))

    # Condición del impuesto (nota 18)
    if condicion_impuesto:
        _add(root, "CondicionImpuesto", condicion_impuesto)

    # Monto del impuesto a acreditar (no aplica para proporcionalidad - código 05)
    if monto_impuesto_acreditar is not None and condicion_impuesto != "05":
        _add(root, "MontoTotalImpuestoAcreditar", _q5(monto_impuesto_acreditar))

    # Monto total del gasto a aplicar (no aplica para proporcionalidad - código 05)
    if monto_gasto_aplicable is not None and condicion_impuesto != "05":
        _add(root, "MontoTotalDeGastoAplicable", _q5(monto_gasto_aplicable))

    # TotalFactura va DESPUÉS de los campos de impuesto según XSD v4.4
    _add(root, "TotalFactura", _q5(total_factura))

    # Cédula del receptor (quien confirma)
    _add(root, "NumeroCedulaReceptor", cedula_receptor)

    # Consecutivo del mensaje de confirmación
    _add(root, "NumeroConsecutivoReceptor", consecutivo_receptor)

    # Nota: ds:Signature se agrega después con xml_signer.sign_xml()

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")