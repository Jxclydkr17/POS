# -*- coding: utf-8 -*-
"""
Generación de PDF de proformas/cotizaciones para AGROMATINA.

Reutiliza la misma estructura visual de pdf_reports.py con diferencias clave:
- Marca de agua "PROFORMA" en diagonal
- Encabezado: "PROFORMA / COTIZACIÓN"
- Muestra número PRO-XXXXXX y fecha de vencimiento
- Incluye notas del vendedor
- Pie: "Este documento no tiene validez fiscal"
"""

import os
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from app.utils.dt import now_cr, to_cr
from app.utils.unit_helpers import format_quantity

# ---------------------------------------------------------
# RUTAS BÁSICAS (mismas que pdf_reports.py)
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # carpeta app/
STATIC_DIR = os.path.join(BASE_DIR, "static")
PDF_DIR = os.path.join(BASE_DIR, "pdfs")

LOGO_PATH = os.path.join(STATIC_DIR, "agromatina_logo.png")

os.makedirs(PDF_DIR, exist_ok=True)


def _format_currency(value: float) -> str:
    """Formatea montos en colones: ₡ 12.345,67"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.0
    return f"₡ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _format_date(iso_str: str | None) -> str:
    """Convierte ISO string a formato legible CR."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso_str))
        dt_cr = to_cr(dt)
        return dt_cr.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(iso_str)[:16]


def _format_date_short(iso_str: str | None) -> str:
    """Convierte ISO string a formato fecha corta."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso_str))
        dt_cr = to_cr(dt)
        return dt_cr.strftime("%d/%m/%Y")
    except Exception:
        return str(iso_str)[:10]


# ---------------------------------------------------------
# MARCA DE AGUA "PROFORMA"
# ---------------------------------------------------------
class _WatermarkCanvas(canvas.Canvas):
    """Canvas personalizado que dibuja marca de agua en cada página."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        super().showPage()

    def save(self):
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_watermark()
            super().showPage()
        super().save()

    def _draw_watermark(self):
        """Dibuja 'PROFORMA' en diagonal semitransparente."""
        self.saveState()
        self.setFont("Helvetica-Bold", 72)
        self.setFillColor(colors.Color(0, 0, 0, alpha=0.06))
        # Centrar en la página (letter = 612 x 792 points)
        self.translate(306, 396)
        self.rotate(35)
        self.drawCentredString(0, 0, "PROFORMA")
        self.restoreState()


# ---------------------------------------------------------
# GENERADOR PRINCIPAL
# ---------------------------------------------------------
def generate_proforma_pdf(proforma_data: dict, logo_path: str | None = None) -> str:
    """
    Genera el PDF de una proforma/cotización.

    Espera un diccionario con la forma que retorna proforma_crud.get_proforma_detail():
        {
            "id": int,
            "number": "PRO-000001",
            "customer_name": str,
            "status": str,
            "total": float,
            "notes": str | None,
            "validity_days": int,
            "valid_until": "ISO datetime",
            "created_at": "ISO datetime",
            "details": [
                {
                    "product_name": str,
                    "quantity": int,
                    "unit_price": float,
                    "subtotal": float,
                    "discount_percent": float,
                    "tax_rate": float,
                    "tax_amount": float,
                    "is_common": bool,
                },
                ...
            ],
        }

    Devuelve la ruta absoluta del PDF generado.
    """
    if not proforma_data:
        raise ValueError("proforma_data está vacío")

    if logo_path is None and os.path.exists(LOGO_PATH):
        logo_path = LOGO_PATH

    proforma_id = proforma_data.get("id", "N/A")
    number = proforma_data.get("number", f"PRO-{proforma_id}")
    customer_name = proforma_data.get("customer_name", "Cliente General")
    status = proforma_data.get("status", "VIGENTE")
    total = proforma_data.get("total", 0.0)
    notes = proforma_data.get("notes", None)
    validity_days = proforma_data.get("validity_days", 15)
    valid_until = proforma_data.get("valid_until", None)
    created_at = proforma_data.get("created_at", None)
    details = proforma_data.get("details", [])

    filename = f"proforma_{number}.pdf"
    pdf_path = os.path.join(PDF_DIR, filename)

    # -----------------------------------------------------
    # CONFIGURACIÓN DEL DOCUMENTO
    # -----------------------------------------------------
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Proforma {number}",
    )

    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="TitleCenter",
            parent=styles["Heading1"],
            fontSize=16,
            leading=18,
            alignment=1,
            spaceAfter=10,
        )
    )

    styles.add(
        ParagraphStyle(
            name="SubtitleCenter",
            parent=styles["Normal"],
            fontSize=11,
            leading=13,
            alignment=1,
            spaceAfter=4,
            textColor=colors.HexColor("#555555"),
        )
    )

    styles.add(
        ParagraphStyle(
            name="Small",
            parent=styles["Normal"],
            fontSize=9,
            leading=11,
        )
    )

    styles.add(
        ParagraphStyle(
            name="SmallBold",
            parent=styles["Normal"],
            fontSize=9,
            leading=11,
            spaceAfter=0,
            spaceBefore=0,
            textColor=colors.black,
        )
    )

    styles.add(
        ParagraphStyle(
            name="Notes",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#333333"),
            leftIndent=8,
            rightIndent=8,
            spaceBefore=4,
            spaceAfter=4,
        )
    )

    styles.add(
        ParagraphStyle(
            name="Disclaimer",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            alignment=1,
            textColor=colors.HexColor("#999999"),
            spaceBefore=6,
        )
    )

    story = []

    # -----------------------------------------------------
    # ENCABEZADO: Logo + Datos del negocio (dinámico)
    # -----------------------------------------------------
    biz = proforma_data.get("business") or {}
    biz_name = biz.get("name", "Mi Negocio")
    biz_email = biz.get("email", "")
    biz_phone = biz.get("phone", "")
    biz_address = biz.get("address", "")

    company_lines = [f"<b>{biz_name.upper()}</b>"]
    if biz_address:
        company_lines.append(biz_address)
    if biz_phone:
        company_lines.append(f"Tel: {biz_phone}")
    if biz_email:
        company_lines.append(f"Correo: {biz_email}")
    company_text = "<br/>".join(company_lines)

    header_cells = []

    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=35 * mm, height=35 * mm)
            header_cells.append(logo)
        except Exception:
            header_cells.append(Paragraph(biz_name.upper(), styles["TitleCenter"]))
    else:
        header_cells.append(Paragraph(biz_name.upper(), styles["TitleCenter"]))

    header_cells.append(Paragraph(company_text, styles["Small"]))

    header_table = Table(
        [header_cells],
        colWidths=[45 * mm, 120 * mm],
        hAlign="LEFT",
    )

    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    story.append(header_table)
    story.append(Spacer(1, 6 * mm))

    # -----------------------------------------------------
    # TÍTULO: PROFORMA / COTIZACIÓN
    # -----------------------------------------------------
    story.append(Paragraph("PROFORMA / COTIZACIÓN", styles["TitleCenter"]))

    # Estado como subtítulo con color según estado
    status_colors = {
        "VIGENTE": "#16a34a",
        "VENCIDA": "#dc2626",
        "CONVERTIDA": "#2563eb",
        "ANULADA": "#6b7280",
    }
    status_color = status_colors.get(status, "#333333")
    story.append(
        Paragraph(
            f'<font color="{status_color}"><b>Estado: {status}</b></font>',
            styles["SubtitleCenter"],
        )
    )
    story.append(Spacer(1, 2 * mm))

    # -----------------------------------------------------
    # DATOS GENERALES DE LA PROFORMA
    # -----------------------------------------------------
    info_data = [
        [
            Paragraph("<b>Proforma N°:</b>", styles["Small"]),
            Paragraph(f"<b>{number}</b>", styles["Small"]),
            Paragraph("<b>Fecha emisión:</b>", styles["Small"]),
            Paragraph(_format_date(created_at), styles["Small"]),
        ],
        [
            Paragraph("<b>Cliente:</b>", styles["Small"]),
            Paragraph(customer_name, styles["Small"]),
            Paragraph("<b>Vigencia:</b>", styles["Small"]),
            Paragraph(f"{validity_days} días", styles["Small"]),
        ],
        [
            Paragraph("", styles["Small"]),
            Paragraph("", styles["Small"]),
            Paragraph("<b>Válida hasta:</b>", styles["Small"]),
            Paragraph(
                f'<font color="{status_color}"><b>{_format_date_short(valid_until)}</b></font>',
                styles["Small"],
            ),
        ],
    ]

    info_table = Table(info_data, colWidths=[28 * mm, 57 * mm, 30 * mm, 60 * mm])
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    story.append(info_table)
    story.append(Spacer(1, 4 * mm))

    # -----------------------------------------------------
    # DETALLE DE PRODUCTOS
    # -----------------------------------------------------
    detail_rows = [
        [
            Paragraph("<b>Cant.</b>", styles["Small"]),
            Paragraph("<b>Descripción</b>", styles["Small"]),
            Paragraph("<b>P. Unitario</b>", styles["Small"]),
            Paragraph("<b>Desc. %</b>", styles["Small"]),
            Paragraph("<b>Subtotal</b>", styles["Small"]),
        ]
    ]

    for item in details:
        qty = item.get("quantity", 0)
        product_name = item.get("product_name", "")

        # Producto común: prefijar con 📦
        if item.get("is_common"):
            product_name = f"* {item.get('common_description', product_name)}"

        unit_price = item.get("unit_price", 0.0)
        discount_pct = item.get("discount_percent", 0.0)
        subtotal = item.get("subtotal", qty * unit_price)

        # 📏 Formatear cantidad con unidad de medida
        unit_type = item.get("unit_type", "Unid") or "Unid"
        qty_display = format_quantity(qty, unit_type)

        discount_str = f"{discount_pct:.1f}%" if discount_pct > 0 else "—"

        detail_rows.append(
            [
                Paragraph(qty_display, styles["Small"]),
                Paragraph(product_name, styles["Small"]),
                Paragraph(_format_currency(unit_price), styles["Small"]),
                Paragraph(discount_str, styles["Small"]),
                Paragraph(_format_currency(subtotal), styles["Small"]),
            ]
        )

    detail_table = Table(
        detail_rows,
        colWidths=[20 * mm, 78 * mm, 28 * mm, 18 * mm, 28 * mm],
        hAlign="LEFT",
    )

    detail_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),   # Cantidad centrada
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),    # Precio derecha
                ("ALIGN", (3, 0), (3, -1), "CENTER"),   # Descuento centrado
                ("ALIGN", (4, 1), (4, -1), "RIGHT"),    # Subtotal derecha
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    story.append(detail_table)
    story.append(Spacer(1, 4 * mm))

    # -----------------------------------------------------
    # TOTAL
    # -----------------------------------------------------
    total_table = Table(
        [
            [
                "",
                Paragraph("<b>TOTAL:</b>", styles["Small"]),
                Paragraph(
                    f"<b>{_format_currency(total)}</b>",
                    styles["SmallBold"],
                ),
            ]
        ],
        colWidths=[110 * mm, 30 * mm, 30 * mm],
        hAlign="RIGHT",
    )

    total_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (2, 0), "RIGHT"),
                ("LINEABOVE", (1, 0), (2, 0), 0.5, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    story.append(total_table)
    story.append(Spacer(1, 6 * mm))

    # -----------------------------------------------------
    # NOTAS DEL VENDEDOR (si las hay)
    # -----------------------------------------------------
    if notes and notes.strip():
        story.append(Paragraph("<b>Notas:</b>", styles["Small"]))

        notes_table = Table(
            [[Paragraph(notes.strip().replace("\n", "<br/>"), styles["Notes"])]],
            colWidths=[170 * mm],
            hAlign="LEFT",
        )
        notes_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f9f9f9")),
                    ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(notes_table)
        story.append(Spacer(1, 6 * mm))

    # -----------------------------------------------------
    # PIE: DISCLAIMER
    # -----------------------------------------------------
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            "Este documento es una cotización/proforma y <b>no tiene validez fiscal</b>.<br/>"
            "Los precios están sujetos a disponibilidad de inventario al momento de la compra.<br/>"
            f"Válida por {validity_days} días a partir de la fecha de emisión.",
            styles["Disclaimer"],
        )
    )

    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            f"{biz_name} — ¡Gracias por su preferencia!",
            styles["Disclaimer"],
        )
    )

    # Construir PDF con marca de agua
    doc.build(story, canvasmaker=_WatermarkCanvas)

    return pdf_path