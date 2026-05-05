# app/utils/pdf_utils.py
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
import os
from app.core.logger import logger  # ✅

def generate_invoice_pdf(sale_data, items, logo_path=None):
    # ── FASE 7 — Fix 7.1: Resolver logo con ruta absoluta portable ──
    if logo_path is None:
        from app.core.config import get_logo_path
        logo_path = get_logo_path()

    output_dir = "generated_pdfs"
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"venta_{sale_data['id']}.pdf")

    logger.info(f"🧾 Generando PDF para venta #{sale_data['id']}")

    doc = SimpleDocTemplate(filename, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    story = []

    if logo_path and os.path.exists(logo_path):
        story.append(Image(logo_path, width=50*mm, height=50*mm))

    biz = sale_data.get("business") or {}
    biz_name = biz.get("name", "Mi Negocio")
    biz_phone = biz.get("phone", "")
    biz_address = biz.get("address", "")

    story.append(Paragraph(f"<b>{biz_name}</b>", styles["Title"]))
    contact_parts = []
    if biz_phone:
        contact_parts.append(f"Tel: {biz_phone}")
    if biz_address:
        contact_parts.append(biz_address)
    if contact_parts:
        story.append(Paragraph(" • ".join(contact_parts), styles["Normal"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"<b>Cliente:</b> {sale_data['customer_name']}", styles["Normal"]))
    story.append(Paragraph(f"<b>Método de pago:</b> {sale_data['payment_method']}", styles["Normal"]))
    story.append(Spacer(1, 10))

    table_data = [["Producto", "Cantidad", "Precio", "Subtotal"]]
    for i in items:
        table_data.append([i["description"], str(i["quantity"]), f"₡{i['price']:,.2f}", f"₡{i['subtotal']:,.2f}"])

    table = Table(table_data, colWidths=[80*mm, 25*mm, 30*mm, 35*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.grey),
        ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),
        ("ALIGN", (1,1), (-1,-1), "RIGHT"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("GRID", (0,0), (-1,-1), 0.25, colors.black),
    ]))
    story.append(table)
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"<b>Total:</b> ₡{sale_data['total']:,.2f}", styles["Normal"]))
    story.append(Paragraph(f"<b>Pago con:</b> ₡{sale_data['amount_paid']:,.2f}", styles["Normal"]))
    story.append(Paragraph(f"<b>Cambio:</b> ₡{sale_data['change']:,.2f}", styles["Normal"]))

    doc.build(story)
    return filename