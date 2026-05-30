"""
app/services/einvoice_pdf.py — PDF de representación gráfica del comprobante electrónico

Genera un PDF imprimible que cumple con el requisito de Hacienda de
representación gráfica, incluyendo:
  - Datos del emisor
  - Datos del receptor/cliente
  - Detalle de líneas
  - Resumen de impuestos y totales
  - Clave numérica de 50 dígitos
  - QR con URL de verificación de Hacienda
  - Consecutivo

USO:
    from app.services.einvoice_pdf import generate_einvoice_pdf
    path = generate_einvoice_pdf(db, einvoice_id=123)
"""

from __future__ import annotations

import io
import os
import logging
from decimal import Decimal

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, Image, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

from sqlalchemy.orm import Session

from app.db.models.electronic_invoice import ElectronicInvoice
from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
from app.db.models.customer import Customer
from app.db.models.product import Product
from app.db.models.issuer_profile import IssuerProfile
from app.utils.dt import now_cr, format_cr  # FASE 2.2 — Fix 2.2: display CR
from app.core.config import get_pdf_dir

logger = logging.getLogger(__name__)

# ── FASE 5 — Fix 5.2: PDFs en directorio externo configurable ──
PDF_DIR = get_pdf_dir()

# URL de verificación de Hacienda
HACIENDA_VERIFY_URL = "https://www.hacienda.go.cr/fe/comprobantes?clave={clave}"

# Tipo de documento labels
DOC_TYPE_LABELS = {
    "01": "Factura Electrónica",
    "02": "Nota de Débito Electrónica",
    "03": "Nota de Crédito Electrónica",
    "04": "Tiquete Electrónico",
    "05": "Confirmación Aceptación",
    "06": "Confirmación Aceptación Parcial",
    "07": "Confirmación Rechazo",
    "08": "Factura Electrónica de Compra",
    "09": "Factura Electrónica de Exportación",
    "10": "Recibo Electrónico de Pago",
}

STATUS_LABELS = {
    "ACCEPTED": "ACEPTADO por Hacienda",
    "REJECTED": "RECHAZADO por Hacienda",
    "SENT": "Enviado (pendiente respuesta)",
    "XML_READY": "XML listo (no enviado)",
    "PENDING": "Pendiente",
}


def _generate_qr_image(data: str, size: int = 120) -> Image | None:
    """Genera un QR como imagen de ReportLab. Retorna None si qrcode no está instalado."""
    try:
        import qrcode
        # noqa: F401 abajo — import de DISPONIBILIDAD: si el backend PIL de
        # qrcode no está instalado, este import falla y el try retorna None
        # (en vez de reventar luego en make_image). No es código muerto.
        from qrcode.image.pil import PilImage  # noqa: F401

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        return Image(buf, width=size, height=size)

    except ImportError:
        logger.warning("qrcode no instalado. pip install qrcode[pil] para generar QR en PDFs.")
        return None
    except Exception as e:
        logger.error(f"Error generando QR: {e}")
        return None


def _fmt(value, decimals: int = 2) -> str:
    """Formatea un número para visualización."""
    try:
        v = float(value or 0)
        return f"{v:,.{decimals}f}"
    except (TypeError, ValueError):
        return "0.00"


def generate_einvoice_pdf(
    db: Session,
    einvoice_id: int,
    *,
    logo_path: str | None = None,
) -> str:
    """
    Genera el PDF de representación gráfica de un comprobante electrónico.

    Args:
        db: Sesión de base de datos
        einvoice_id: ID del ElectronicInvoice
        logo_path: Ruta opcional al logo del emisor

    Returns:
        Ruta absoluta del PDF generado.

    Raises:
        ValueError: Si no se encuentra el comprobante o datos incompletos.
    """
    # ── Cargar datos ──
    einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.id == einvoice_id).first()
    if not einv:
        raise ValueError(f"ElectronicInvoice {einvoice_id} no encontrado.")

    sale = db.query(Sale).filter(Sale.id == einv.sale_id).first()
    if not sale:
        raise ValueError(f"Sale {einv.sale_id} no encontrada.")

    details = db.query(SaleDetail).filter(SaleDetail.sale_id == sale.id).all()
    customer = db.query(Customer).filter(Customer.id == sale.customer_id).first() if sale.customer_id else None
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()

    if not issuer:
        raise ValueError("No existe IssuerProfile (datos del emisor).")

    # ── Nombres de archivo ──
    clave = einv.clave or "SIN_CLAVE"
    doc_type = einv.document_type or "04"
    doc_label = DOC_TYPE_LABELS.get(doc_type, "Comprobante Electrónico")
    filename = f"einvoice_{einv.id}_{clave[-8:]}.pdf"
    filepath = PDF_DIR / filename

    # ── Estilos ──
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallCenter", parent=styles["Normal"], fontSize=7, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="DocTitle", parent=styles["Title"], fontSize=14, spaceAfter=4))
    styles.add(ParagraphStyle(name="FieldLabel", parent=styles["Normal"], fontSize=8, textColor=colors.grey))
    styles.add(ParagraphStyle(name="FieldValue", parent=styles["Normal"], fontSize=9, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="SmallRight", parent=styles["Normal"], fontSize=8, alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="Footer", parent=styles["Normal"], fontSize=7, alignment=TA_CENTER, textColor=colors.grey))

    # ── Construir contenido ──
    story = []

    # --- Logo + encabezado ---
    header_data = []
    logo_cell = ""
    if logo_path and os.path.exists(logo_path):
        try:
            logo_cell = Image(logo_path, width=35 * mm, height=35 * mm)
        except Exception:
            logo_cell = ""

    emitter_info = (
        f"<b>{issuer.legal_name or 'Emisor'}</b><br/>"
        f"{issuer.commercial_name or ''}<br/>"
        f"Cédula: {issuer.id_number or 'N/A'}<br/>"
        f"Tel: {issuer.phone or 'N/A'}  |  {issuer.email or ''}<br/>"
        f"{issuer.otras_senas or ''}"
    )

    doc_info = (
        f"<b>{doc_label}</b><br/>"
        f"Consecutivo: {einv.consecutivo or 'N/A'}<br/>"
        f"Estado: {STATUS_LABELS.get(einv.status, einv.status)}"
    )

    header_table = Table(
        [[logo_cell, Paragraph(emitter_info, styles["Normal"]), Paragraph(doc_info, styles["Normal"])]],
        colWidths=[40 * mm, 80 * mm, 60 * mm],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4 * mm))

    # --- Clave ---
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"<b>Clave:</b> {clave}", styles["Normal"]))
    story.append(Spacer(1, 1 * mm))

    # FASE 2.2 — Fix 2.2: fecha siempre en CR (UTC en BD → CR para mostrar).
    fecha_str = format_cr(sale.created_at, "%d/%m/%Y %H:%M:%S") if sale.created_at else now_cr().strftime("%d/%m/%Y %H:%M:%S")
    story.append(Paragraph(f"<b>Fecha emisión:</b> {fecha_str}", styles["Normal"]))
    story.append(Spacer(1, 3 * mm))

    # --- Receptor/Cliente ---
    if customer:
        receptor_info = (
            f"<b>Receptor:</b> {customer.name or 'N/A'}<br/>"
            f"Identificación: {customer.id_type or ''} {customer.id_number or 'N/A'}<br/>"
            f"Email: {customer.email or 'N/A'}  |  Tel: {customer.phone or 'N/A'}"
        )
    else:
        receptor_info = "<b>Receptor:</b> Cliente general (sin identificación)"

    story.append(Paragraph(receptor_info, styles["Normal"]))
    story.append(Spacer(1, 4 * mm))

    # --- Condición de venta y medio de pago ---
    condicion_labels = {
        "01": "Contado", "02": "Crédito", "03": "Consignación",
        "04": "Apartado", "05": "Arrendamiento opción compra",
        "06": "Arrendamiento función financiera", "07": "Cobro a favor tercero",
        "08": "Servicios prestados al Estado", "09": "Pago Factura de Servicios Públicos",
        "10": "Pago servicio público a tercero", "11": "Créditos fiscales",
        "99": "Otros",
    }
    cond_code = sale.condicion_venta_code or "01"
    cond_label = condicion_labels.get(cond_code, cond_code)
    story.append(Paragraph(
        f"<b>Condición de venta:</b> {cond_label}  |  "
        f"<b>Medio de pago:</b> {sale.payment_method or 'N/A'}  |  "
        f"<b>Moneda:</b> {sale.moneda_code or 'CRC'}",
        styles["Normal"]
    ))
    story.append(Spacer(1, 4 * mm))

    # --- Tabla de detalle ---
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 2 * mm))

    table_header = ["#", "Descripción", "Cant.", "P. Unit.", "Desc%", "IVA%", "Subtotal"]
    table_data = [table_header]

    total_gravado = Decimal("0")
    total_exento = Decimal("0")
    total_impuesto = Decimal("0")
    total_descuento = Decimal("0")
    total_venta = Decimal("0")

    for idx, det in enumerate(details, 1):
        # Obtener nombre del producto
        prod_name = det.common_description if det.is_common else None
        if not prod_name and det.product_id:
            prod = db.query(Product).filter(Product.id == det.product_id).first()
            prod_name = prod.name if prod else f"Producto #{det.product_id}"
        prod_name = prod_name or "Artículo"

        qty = float(det.quantity or 0)
        unit_price = float(det.unit_price or 0)
        disc_pct = float(det.discount_percent or 0)
        tax_rate = float(det.tax_rate or 0)
        subtotal = float(det.subtotal or 0)
        tax_amount = float(det.tax_amount or 0)

        line_bruto = qty * unit_price
        line_desc = line_bruto * disc_pct / 100
        line_neto = line_bruto - line_desc

        total_descuento += Decimal(str(line_desc))
        total_impuesto += Decimal(str(tax_amount))
        total_venta += Decimal(str(line_neto))

        if tax_rate > 0:
            total_gravado += Decimal(str(line_neto))
        else:
            total_exento += Decimal(str(line_neto))

        table_data.append([
            str(idx),
            prod_name[:45],
            _fmt(qty, 3),
            _fmt(unit_price),
            f"{disc_pct:.1f}%" if disc_pct else "-",
            f"{tax_rate:.0f}%" if tax_rate else "Exento",
            _fmt(subtotal),
        ])

    col_widths = [8 * mm, 58 * mm, 18 * mm, 25 * mm, 16 * mm, 16 * mm, 28 * mm]
    detail_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d5f3e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(detail_table)
    story.append(Spacer(1, 4 * mm))

    # --- Resumen de totales ---
    total_comprobante = total_venta + total_impuesto

    resumen_data = [
        ["Total Venta Gravada:", f"₡ {_fmt(total_gravado)}"],
        ["Total Venta Exenta:", f"₡ {_fmt(total_exento)}"],
        ["Total Descuentos:", f"₡ {_fmt(total_descuento)}"],
        ["Total Impuesto:", f"₡ {_fmt(total_impuesto)}"],
        ["TOTAL COMPROBANTE:", f"₡ {_fmt(total_comprobante)}"],
    ]

    resumen_table = Table(resumen_data, colWidths=[120 * mm, 50 * mm], hAlign="RIGHT")
    resumen_table.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.append(resumen_table)
    story.append(Spacer(1, 6 * mm))

    # --- QR + clave visual ---
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 3 * mm))

    verify_url = HACIENDA_VERIFY_URL.format(clave=clave)
    qr_img = _generate_qr_image(verify_url, size=80)

    if qr_img:
        qr_table = Table(
            [[
                qr_img,
                Paragraph(
                    f"<b>Verificación electrónica</b><br/>"
                    f"<font size='7'>Escanee el código QR o visite:</font><br/>"
                    f"<font size='6' color='blue'>{verify_url}</font>",
                    styles["Normal"]
                ),
            ]],
            colWidths=[30 * mm, 140 * mm],
        )
        qr_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (1, 0), (1, 0), 5 * mm),
        ]))
        story.append(qr_table)
    else:
        story.append(Paragraph(
            f"<b>URL de verificación:</b> <font color='blue'>{verify_url}</font>",
            styles["Normal"]
        ))

    story.append(Spacer(1, 4 * mm))

    # --- Pie de página ---
    story.append(HRFlowable(width="100%", thickness=0.3, color=colors.lightgrey))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "Documento generado electrónicamente — Violette POS  |  "
        "Autorizado mediante resolución DGT-R-033-2019",
        styles["Footer"]
    ))

    # ── Generar PDF ──
    doc = SimpleDocTemplate(
        str(filepath),
        pagesize=letter,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    doc.build(story)

    logger.info(f"PDF generado: {filepath} ({filepath.stat().st_size:,} bytes)")
    return str(filepath)