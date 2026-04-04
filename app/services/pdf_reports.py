# -*- coding: utf-8 -*-
"""
Generación de comprobantes PDF para ventas de AGROMATINA.

Este módulo crea un PDF sencillo pero bonito con:
- Logo de la ferretería
- Datos del negocio
- Datos de la venta
- Tabla de productos
- Total de la venta
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
from app.utils.dt import now_cr
from app.utils.unit_helpers import format_quantity
from app.core.config import get_pdf_dir

# ---------------------------------------------------------
# RUTAS BÁSICAS
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # carpeta app/
STATIC_DIR = os.path.join(BASE_DIR, "static")
# ── FASE 5 — Fix 5.2: PDFs en directorio externo configurable ──
PDF_DIR = str(get_pdf_dir())

# Logo (ajusta el nombre/ruta si lo guardás distinto)
LOGO_PATH = os.path.join(STATIC_DIR, "agromatina_logo.png")

# get_pdf_dir() ya crea la carpeta automáticamente


def _format_currency(value: float) -> str:
    """Formatea montos en colones."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.0
    # ₡ 12,345.67
    return f"₡ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def generate_sale_pdf(sale_data: dict, logo_path: str | None = None) -> str:
    """
    Genera el comprobante PDF de una venta.

    Espera un diccionario con la forma:
        {
            "id": int,
            "customer": {"name": str},
            "details": [
                {"product": str, "quantity": int, "unit_price": float, "subtotal": float},
                ...
            ],
            "total": float,
            "payment_method": str,
            "created_at": "YYYY-MM-DD HH:MM"
        }

    Devuelve la ruta absoluta del PDF generado.
    """
    if not sale_data:
        raise ValueError("sale_data está vacío")

    if logo_path is None and os.path.exists(LOGO_PATH):
        logo_path = LOGO_PATH

    sale_id = sale_data.get("id", "N/A")
    customer_name = (sale_data.get("customer") or {}).get("name", "Cliente General")
    created_at = sale_data.get("created_at") or now_cr().strftime("%Y-%m-%d %H:%M")
    payment_method = sale_data.get("payment_method", "Efectivo")
    total = sale_data.get("total", 0.0)
    details = sale_data.get("details", [])

    filename = f"venta_{sale_id}.pdf"
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
        title=f"Comprobante de venta #{sale_id}",
    )

    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="TitleCenter",
            parent=styles["Heading1"],
            fontSize=16,
            leading=18,
            alignment=1,  # centrado
            spaceAfter=10,
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

    story = []

    # -----------------------------------------------------
    # ENCABEZADO: Logo + Datos del negocio (dinámico)
    # -----------------------------------------------------
    biz = sale_data.get("business") or {}
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

    # Columna 1: Logo (si existe)
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=35 * mm, height=35 * mm)
            header_cells.append(logo)
        except Exception:
            header_cells.append(Paragraph(biz_name.upper(), styles["TitleCenter"]))
    else:
        header_cells.append(Paragraph(biz_name.upper(), styles["TitleCenter"]))

    # Columna 2: Datos de la empresa
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
    # TÍTULO DEL COMPROBANTE
    # -----------------------------------------------------
    story.append(Paragraph("COMPROBANTE DE VENTA", styles["TitleCenter"]))
    story.append(Spacer(1, 2 * mm))

    # -----------------------------------------------------
    # DATOS GENERALES DE LA VENTA
    # -----------------------------------------------------
    info_data = [
        [
            Paragraph("<b>Factura N°:</b>", styles["Small"]),
            Paragraph(str(sale_id), styles["Small"]),
            Paragraph("<b>Fecha/Hora:</b>", styles["Small"]),
            Paragraph(str(created_at), styles["Small"]),
        ],
        [
            Paragraph("<b>Cliente:</b>", styles["Small"]),
            Paragraph(customer_name, styles["Small"]),
            Paragraph("<b>Método de pago:</b>", styles["Small"]),
            Paragraph(payment_method, styles["Small"]),
        ],
    ]

    info_table = Table(info_data, colWidths=[25 * mm, 60 * mm, 30 * mm, 60 * mm])
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
            Paragraph("<b>Subtotal</b>", styles["Small"]),
        ]
    ]

    for item in details:
        qty = item.get("quantity", 0)
        name = item.get("product", "")
        unit_price = item.get("unit_price", 0.0)
        subtotal = item.get("subtotal", qty * unit_price)

        # 📏 Formatear cantidad con unidad de medida
        unit_type = item.get("unit_type", "Unid") or "Unid"
        qty_display = format_quantity(qty, unit_type)

        detail_rows.append(
            [
                Paragraph(qty_display, styles["Small"]),
                Paragraph(name, styles["Small"]),
                Paragraph(_format_currency(unit_price), styles["Small"]),
                Paragraph(_format_currency(subtotal), styles["Small"]),
            ]
        )

    detail_table = Table(
        detail_rows,
        colWidths=[24 * mm, 86 * mm, 30 * mm, 30 * mm],
        hAlign="LEFT",
    )

    detail_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),  # Cantidad
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),  # Precios
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
                Paragraph(_format_currency(total), styles["SmallBold"]),
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
    story.append(Spacer(1, 10 * mm))

    # -----------------------------------------------------
    # MENSAJE FINAL
    # -----------------------------------------------------
    story.append(
        Paragraph(
            "¡Gracias por su compra!<br/>"
            "Conserve este comprobante para cualquier consulta.",
            styles["Small"],
        )
    )

    # Construir PDF
    doc.build(story)

    return pdf_path