import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import cm
from app.utils.dt import now_cr

# 📂 Carpeta donde se guardarán los PDF generados
PDF_DIR = "generated_pdfs"
LOGO_PATH = "ui/assets/logoferre.jpg"  # ⚠️ Asegúrate de colocar aquí tu logo
os.makedirs(PDF_DIR, exist_ok=True)


def generate_invoice_pdf(sale_data, items):
    """
    Genera un comprobante tipo factura profesional A4.
    Usa sale_data["business"] para datos del negocio (dinámico).
    """
    biz = sale_data.get("business") or {}
    biz_name = biz.get("name", "Mi Negocio")
    biz_email = biz.get("email", "")
    biz_phone = biz.get("phone", "")
    biz_address = biz.get("address", "")

    # -------------------------------
    # 📄 CONFIGURACIÓN INICIAL
    # -------------------------------
    sale_id = sale_data.get("id", "N/A")
    filename = os.path.join(PDF_DIR, f"venta_{sale_id}.pdf")
    pdf = canvas.Canvas(filename, pagesize=A4)
    width, height = A4

    # Margen inicial
    x_margin = 2 * cm
    y = height - 3 * cm

    # -------------------------------
    # 🏪 ENCABEZADO
    # -------------------------------
    if os.path.exists(LOGO_PATH):
        pdf.drawImage(LOGO_PATH, width - 6 * cm, y - 1.5 * cm, width=4.5 * cm, preserveAspectRatio=True, mask="auto")

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(x_margin, y, biz_name)
    pdf.setFont("Helvetica", 10)
    contact_parts = []
    if biz_phone:
        contact_parts.append(f"Tel: {biz_phone}")
    if biz_email:
        contact_parts.append(biz_email)
    pdf.drawString(x_margin, y - 15, "  |  ".join(contact_parts) if contact_parts else "")
    if biz_address:
        pdf.drawString(x_margin, y - 30, biz_address)

    y -= 70
    pdf.setFont("Helvetica", 10)
    pdf.drawString(x_margin, y, f"Fecha y hora: {now_cr().strftime('%d/%m/%Y - %I:%M %p')}")
    pdf.drawString(x_margin, y - 15, f"N° de documento: {sale_id}")
    y -= 40

    # -------------------------------
    # 👤 DATOS DEL CLIENTE
    # -------------------------------
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(x_margin, y, "Cliente:")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(x_margin + 60, y, sale_data.get("customer_name", "Cliente General"))
    pdf.drawString(x_margin, y - 15, f"Medio de pago: {sale_data.get('payment_method', 'Efectivo')}")
    y -= 35

    # -------------------------------
    # 🧱 ENCABEZADO DE TABLA
    # -------------------------------
    pdf.setFillColorRGB(0.2, 0.5, 0.3)
    pdf.rect(x_margin, y - 18, width - 2 * x_margin, 18, fill=True, stroke=False)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(x_margin + 5, y - 12, "Descripción")
    pdf.drawRightString(width - 9.5 * cm, y - 12, "Cant.")
    pdf.drawRightString(width - 6.5 * cm, y - 12, "Precio")
    pdf.drawRightString(width - 3 * cm, y - 12, "Subtotal")

    y -= 25
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica", 10)

    # -------------------------------
    # 🧾 LISTA DE PRODUCTOS
    # -------------------------------
    for item in items:
        name = item.get("name", "Producto")
        qty = item.get("quantity", 1)
        price = item.get("price", 0.0)
        subtotal = item.get("subtotal", qty * price)

        pdf.drawString(x_margin + 5, y, str(name)[:40])
        pdf.drawRightString(width - 9.5 * cm, y, str(qty))
        pdf.drawRightString(width - 6.5 * cm, y, f"₡{price:,.2f}")
        pdf.drawRightString(width - 3 * cm, y, f"₡{subtotal:,.2f}")

        y -= 18
        if y < 100:  # Nueva página si se llena
            pdf.showPage()
            y = height - 100
            pdf.setFont("Helvetica", 10)

    # Línea de separación
    pdf.line(x_margin, y - 5, width - x_margin, y - 5)
    y -= 25

    # -------------------------------
    # 💰 TOTALES
    # -------------------------------
    total = sale_data.get("total", 0.0)
    amount_paid = sale_data.get("amount_paid", 0.0)
    change = sale_data.get("change", 0.0)

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(width - 3 * cm, y, f"Total: ₡{total:,.2f}")
    y -= 20
    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(width - 3 * cm, y, f"Pago con: ₡{amount_paid:,.2f}")
    y -= 20
    pdf.drawRightString(width - 3 * cm, y, f"Cambio: ₡{change:,.2f}")
    y -= 40

    # -------------------------------
    # ✅ PIE DE PÁGINA
    # -------------------------------
    pdf.setFont("Helvetica-Oblique", 10)
    pdf.drawCentredString(width / 2, y, f"¡Gracias por su compra en {biz_name}!")
    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(colors.gray)
    pdf.drawCentredString(width / 2, y - 12, "Documento generado automáticamente - Violette POS")

    pdf.showPage()
    pdf.save()
    return filename