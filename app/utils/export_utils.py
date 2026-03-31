import pandas as pd
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas
from datetime import datetime
from app.utils.dt import now_cr

def export_sales_history_excel(data, filename=None):
    """Exporta lista de ventas a Excel"""
    if not filename:
        filename = f"historial_ventas_{now_cr().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df = pd.DataFrame(data)
    df.to_excel(filename, index=False)
    return filename

def export_sales_history_pdf(data, start_date, end_date, filename=None, business_name="Mi Negocio"):
    """Exporta lista de ventas a PDF"""
    if not filename:
        filename = f"historial_ventas_{now_cr().strftime('%Y%m%d_%H%M%S')}.pdf"

    c = canvas.Canvas(filename, pagesize=landscape(letter))
    width, height = landscape(letter)
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(260, y, f"Histórico de Ventas - {business_name}")
    y -= 30
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Rango: {start_date} al {end_date}")
    y -= 15
    c.drawString(50, y, f"Generado: {now_cr().strftime('%d/%m/%Y %H:%M')}")
    y -= 30

    headers = ["#Venta", "Fecha", "Cliente", "Pago", "Total (₡)"]
    col_widths = [70, 120, 220, 100, 100]

    c.setFont("Helvetica-Bold", 10)
    x = 50
    for i, h in enumerate(headers):
        c.drawString(x, y, h)
        x += col_widths[i]
    y -= 15
    c.line(50, y + 5, width - 50, y + 5)

    c.setFont("Helvetica", 9)
    for row in data:
        if y < 50:
            c.showPage()
            y = height - 50
        x = 50
        vals = [row["id"], row["created_at"], row["customer_name"], row["payment_method"], f"₡{row['total']:,.2f}"]
        for i, v in enumerate(vals):
            c.drawString(x, y, str(v))
            x += col_widths[i]
        y -= 15

    c.showPage()
    c.save()
    return filename

def export_expenses_excel(data, filename=None):
    """Exporta lista de gastos a Excel"""
    if not filename:
        filename = f"reporte_gastos_{now_cr().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df = pd.DataFrame(data)
    df.to_excel(filename, index=False)
    return filename


def export_expenses_pdf(data, start_date, end_date, total, filename=None, business_name="Mi Negocio"):
    """Exporta lista de gastos a PDF"""
    if not filename:
        filename = f"reporte_gastos_{now_cr().strftime('%Y%m%d_%H%M%S')}.pdf"

    c = canvas.Canvas(filename, pagesize=landscape(letter))
    width, height = landscape(letter)
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(250, y, f"Reporte de Gastos - {business_name}")
    y -= 30
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Rango: {start_date} al {end_date}")
    y -= 15
    c.drawString(50, y, f"Generado: {now_cr().strftime('%d/%m/%Y %H:%M')}")
    y -= 30

    headers = ["Fecha", "Categoría", "Descripción", "Monto (₡)", "Método"]
    col_widths = [90, 120, 250, 100, 100]

    c.setFont("Helvetica-Bold", 10)
    x = 50
    for i, h in enumerate(headers):
        c.drawString(x, y, h)
        x += col_widths[i]
    y -= 15
    c.line(50, y + 5, width - 50, y + 5)

    c.setFont("Helvetica", 9)
    for row in data:
        if y < 50:
            c.showPage()
            y = height - 50
        x = 50
        vals = [
            row["date"], row["category"], row["description"] or "—",
            f"₡{row['amount']:,.2f}", row["payment_method"] or "—"
        ]
        for i, v in enumerate(vals):
            c.drawString(x, y, str(v))
            x += col_widths[i]
        y -= 15

    y -= 20
    c.setFont("Helvetica-Bold", 11)
    c.drawString(400, y, f"Total de gastos: ₡{total:,.2f}")

    c.showPage()
    c.save()
    return filename


# ============================================================
# COMPRAS — Exportaciones
# ============================================================

def export_purchases_excel(data, filename=None):
    """Exporta lista de compras/facturas a Excel."""
    if not filename:
        filename = f"reporte_compras_{now_cr().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df = pd.DataFrame(data)
    df.to_excel(filename, index=False)
    return filename


def export_purchases_pdf(data, title_extra="", filename=None, business_name="Mi Negocio"):
    """Exporta lista de compras/facturas a PDF."""
    if not filename:
        filename = f"reporte_compras_{now_cr().strftime('%Y%m%d_%H%M%S')}.pdf"

    c = canvas.Canvas(filename, pagesize=landscape(letter))
    width, height = landscape(letter)
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(200, y, f"Reporte de Compras - {business_name}")
    y -= 25
    if title_extra:
        c.setFont("Helvetica", 10)
        c.drawString(50, y, title_extra)
        y -= 15
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Generado: {now_cr().strftime('%d/%m/%Y %H:%M')}")
    y -= 30

    headers = ["#", "Factura", "Proveedor", "F.Entrada", "F.Venc.", "Monto", "Abonado", "Saldo", "Estado"]
    col_widths = [40, 80, 140, 80, 80, 80, 80, 80, 70]

    c.setFont("Helvetica-Bold", 9)
    x = 40
    for i, h in enumerate(headers):
        c.drawString(x, y, h)
        x += col_widths[i]
    y -= 12
    c.line(40, y + 5, width - 40, y + 5)

    c.setFont("Helvetica", 8)
    total_amount = 0.0
    total_balance = 0.0

    for row in data:
        if y < 50:
            c.showPage()
            y = height - 50

        amount = float(row.get("amount", 0))
        paid = float(row.get("paid_amount", 0))
        balance = float(row.get("balance", amount))
        total_amount += amount
        total_balance += balance

        x = 40
        vals = [
            row.get("id", ""),
            row.get("invoice_number", ""),
            str(row.get("supplier_name", row.get("supplier_id", "")))[:22],
            str(row.get("entry_date", ""))[:10],
            str(row.get("due_date", ""))[:10],
            f"₡{amount:,.2f}",
            f"₡{paid:,.2f}",
            f"₡{balance:,.2f}",
            row.get("status", ""),
        ]
        for i, v in enumerate(vals):
            c.drawString(x, y, str(v))
            x += col_widths[i]
        y -= 12

    y -= 20
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, f"Total facturado: ₡{total_amount:,.2f}    |    Saldo pendiente: ₡{total_balance:,.2f}")

    c.showPage()
    c.save()
    return filename


# ============================================================
# ANALÍTICA DE VENTAS — Exportaciones
# ============================================================

def export_sales_analytics_excel(data, filename=None):
    """Exporta analítica de ventas a Excel (múltiples hojas)."""
    if not filename:
        filename = f"analitica_ventas_{now_cr().strftime('%Y%m%d_%H%M%S')}.xlsx"

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        kpis = data.get("kpis") or {}
        compare = data.get("compare") or {}
        previous = compare.get("previous", {})
        kpi_rows = [
            {"Indicador": "Ventas totales", "Actual": kpis.get("total_sales", 0),
             "Periodo anterior": previous.get("count", "")},
            {"Indicador": "Monto total (₡)", "Actual": kpis.get("total_amount", 0),
             "Periodo anterior": previous.get("total_amount", "")},
            {"Indicador": "Ticket promedio (₡)", "Actual": kpis.get("avg_ticket", 0),
             "Periodo anterior": previous.get("avg_ticket", "")},
        ]
        pd.DataFrame(kpi_rows).to_excel(writer, sheet_name="KPIs", index=False)

        daily = data.get("daily") or []
        if daily:
            pd.DataFrame(daily).to_excel(writer, sheet_name="Ventas diarias", index=False)

        cats = data.get("categories") or []
        if cats:
            pd.DataFrame(cats).to_excel(writer, sheet_name="Por categoría", index=False)

        top = data.get("top_products") or []
        if top:
            pd.DataFrame(top).to_excel(writer, sheet_name="Top productos", index=False)

        payments = data.get("payments") or []
        if payments:
            pd.DataFrame(payments).to_excel(writer, sheet_name="Métodos de pago", index=False)

    return filename


def export_sales_analytics_pdf(data, filename=None, business_name="Mi Negocio"):
    """Exporta analítica de ventas a PDF."""
    if not filename:
        filename = f"analitica_ventas_{now_cr().strftime('%Y%m%d_%H%M%S')}.pdf"

    c = canvas.Canvas(filename, pagesize=landscape(letter))
    width, height = landscape(letter)
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(200, y, f"Analítica de Ventas - {business_name}")
    y -= 25
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Periodo: {data.get('start_date', '')} al {data.get('end_date', '')}")
    y -= 15
    c.drawString(50, y, f"Generado: {now_cr().strftime('%d/%m/%Y %H:%M')}")
    y -= 30

    kpis = data.get("kpis") or {}
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Indicadores Clave")
    y -= 20
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Ventas totales: {kpis.get('total_sales', 0)}")
    y -= 15
    c.drawString(50, y, f"Monto total: ₡{kpis.get('total_amount', 0):,.2f}")
    y -= 15
    c.drawString(50, y, f"Ticket promedio: ₡{kpis.get('avg_ticket', 0):,.2f}")
    y -= 30

    top = data.get("top_products") or []
    if top:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Top Productos")
        y -= 20
        headers = ["#", "Producto", "Cantidad", "Total (₡)"]
        col_widths = [30, 300, 80, 100]
        c.setFont("Helvetica-Bold", 9)
        x = 50
        for i, h in enumerate(headers):
            c.drawString(x, y, h)
            x += col_widths[i]
        y -= 15
        c.line(50, y + 5, width - 50, y + 5)
        c.setFont("Helvetica", 9)
        for idx, p in enumerate(top):
            if y < 50:
                c.showPage()
                y = height - 50
            x = 50
            vals = [str(idx + 1), p.get("name", ""), str(p.get("quantity", 0)),
                    f"₡{p.get('total', 0):,.2f}"]
            for i, v in enumerate(vals):
                c.drawString(x, y, str(v)[:50])
                x += col_widths[i]
            y -= 13

    cats = data.get("categories") or []
    if cats:
        y -= 20
        if y < 100:
            c.showPage()
            y = height - 50
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Ventas por Categoría")
        y -= 20
        c.setFont("Helvetica", 9)
        for cat in cats:
            if y < 50:
                c.showPage()
                y = height - 50
            c.drawString(50, y, f"{cat.get('category', '')}: ₡{cat.get('total', 0):,.2f}")
            y -= 13

    c.showPage()
    c.save()
    return filename


# ============================================================
# ANALÍTICA DE COMPRAS — Exportaciones
# ============================================================

def export_purchases_analytics_excel(data, filename=None):
    """Exporta analítica de compras a Excel (múltiples hojas)."""
    if not filename:
        filename = f"analitica_compras_{now_cr().strftime('%Y%m%d_%H%M%S')}.xlsx"

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        suppliers = data.get("suppliers") or []
        if suppliers:
            pd.DataFrame(suppliers).to_excel(writer, sheet_name="Gasto por proveedor", index=False)

        evolution = data.get("evolution") or []
        if evolution:
            pd.DataFrame(evolution).to_excel(writer, sheet_name="Evolución mensual", index=False)

        days_data = data.get("payment_days") or {}
        by_supplier = days_data.get("by_supplier") or []
        if by_supplier:
            pd.DataFrame(by_supplier).to_excel(writer, sheet_name="Días de pago", index=False)

        products = data.get("top_products") or []
        if products:
            pd.DataFrame(products).to_excel(writer, sheet_name="Top productos", index=False)

    return filename


def export_purchases_analytics_pdf(data, filename=None, business_name="Mi Negocio"):
    """Exporta analítica de compras a PDF."""
    if not filename:
        filename = f"analitica_compras_{now_cr().strftime('%Y%m%d_%H%M%S')}.pdf"

    c = canvas.Canvas(filename, pagesize=landscape(letter))
    width, height = landscape(letter)
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(200, y, f"Analítica de Compras - {business_name}")
    y -= 25
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Periodo: {data.get('start_date', '')} al {data.get('end_date', '')}")
    y -= 15
    c.drawString(50, y, f"Generado: {now_cr().strftime('%d/%m/%Y %H:%M')}")
    y -= 30

    suppliers = data.get("suppliers") or []
    if suppliers:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Gasto por Proveedor")
        y -= 20
        headers = ["Proveedor", "Facturas", "Gasto total (₡)", "Promedio (₡)"]
        col_w = [200, 80, 120, 120]
        c.setFont("Helvetica-Bold", 9)
        x = 50
        for i, h in enumerate(headers):
            c.drawString(x, y, h)
            x += col_w[i]
        y -= 15
        c.line(50, y + 5, width - 50, y + 5)
        c.setFont("Helvetica", 9)
        for s in suppliers:
            if y < 50:
                c.showPage()
                y = height - 50
            x = 50
            vals = [s.get("supplier_name", "")[:30], str(s.get("invoice_count", 0)),
                    f"₡{s.get('total_spent', 0):,.2f}", f"₡{s.get('avg_invoice', 0):,.2f}"]
            for i, v in enumerate(vals):
                c.drawString(x, y, v)
                x += col_w[i]
            y -= 13

    products = data.get("top_products") or []
    if products:
        y -= 20
        if y < 100:
            c.showPage()
            y = height - 50
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Top Productos Comprados")
        y -= 20
        headers = ["Producto", "Cantidad", "Gasto (₡)", "Proveedor"]
        col_w = [200, 80, 120, 200]
        c.setFont("Helvetica-Bold", 9)
        x = 50
        for i, h in enumerate(headers):
            c.drawString(x, y, h)
            x += col_w[i]
        y -= 15
        c.line(50, y + 5, width - 50, y + 5)
        c.setFont("Helvetica", 9)
        for p in products:
            if y < 50:
                c.showPage()
                y = height - 50
            x = 50
            vals = [p.get("product_name", "")[:30], str(p.get("total_qty", 0)),
                    f"₡{p.get('total_spent', 0):,.2f}", (p.get("top_supplier") or "—")[:30]]
            for i, v in enumerate(vals):
                c.drawString(x, y, v)
                x += col_w[i]
            y -= 13

    c.showPage()
    c.save()
    return filename