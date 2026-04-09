import yagmail
import os
from app.core.credentials import email_user, email_pass
from app.core.logger import logger

_DEFAULT_BUSINESS = "Mi Negocio"


def send_sale_email(recipient: str, pdf_path: str, sale_id: int, business_name: str = None):
    """
    Envía el comprobante PDF por correo al cliente con formato HTML.
    """
    biz = business_name or _DEFAULT_BUSINESS
    try:
        subject = f"Comprobante de Venta #{sale_id} - {biz}"

        body = f"""
        <b>Estimado cliente:</b><br><br>
        Adjuntamos el comprobante de su compra <b>#{sale_id}</b>.<br><br>
        Gracias por preferirnos 🧱<br>
        <b>{biz}</b><br><br>
        <hr>
        <small>Este es un mensaje automático, por favor no responder.</small>
        """

        yag = yagmail.SMTP(email_user(), email_pass())
        yag.send(
            to=recipient,
            subject=subject,
            contents=[body, pdf_path]
        )

        logger.info(f"Correo enviado exitosamente a {recipient}")
        return True

    except Exception as e:
        logger.error(f"Error al enviar correo: {e}")
        return False


def send_purchase_expiry_alert(recipient: str, purchases_data: list, business_name: str = None):
    """
    Envía alerta por correo de facturas a punto de vencer o ya vencidas.
    """
    biz = business_name or _DEFAULT_BUSINESS
    if not purchases_data:
        return False

    if not email_user() or not email_pass():
        logger.warning("No se puede enviar alerta de compras: email no configurado.")
        return False

    try:
        count = len(purchases_data)
        subject = f"⚠️ Alerta: {count} factura(s) por vencer/vencidas - {biz}"

        rows_html = ""
        for p in purchases_data:
            status_label = p.get("status", "pendiente")
            status_color = "#DC3545" if status_label == "vencido" else "#F7C331"

            rows_html += f"""
            <tr>
                <td style="padding:6px; border-bottom:1px solid #eee;">{p.get('invoice_number', '-')}</td>
                <td style="padding:6px; border-bottom:1px solid #eee;">{p.get('supplier_name', '-')}</td>
                <td style="padding:6px; border-bottom:1px solid #eee;">{str(p.get('due_date', '-'))[:10]}</td>
                <td style="padding:6px; border-bottom:1px solid #eee;">₡{float(p.get('amount', 0)):,.2f}</td>
                <td style="padding:6px; border-bottom:1px solid #eee;">₡{float(p.get('balance', 0)):,.2f}</td>
                <td style="padding:6px; border-bottom:1px solid #eee; color:{status_color}; font-weight:bold;">{status_label}</td>
            </tr>
            """

        body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 700px;">
            <h2 style="color: #DC3545;">⚠️ Alerta de facturas por pagar</h2>
            <p>Hay <b>{count}</b> factura(s) que requieren atención:</p>

            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <thead>
                    <tr style="background-color:#5B9BD5; color:white;">
                        <th style="padding:8px; text-align:left;">Factura</th>
                        <th style="padding:8px; text-align:left;">Proveedor</th>
                        <th style="padding:8px; text-align:left;">Vencimiento</th>
                        <th style="padding:8px; text-align:left;">Monto</th>
                        <th style="padding:8px; text-align:left;">Saldo</th>
                        <th style="padding:8px; text-align:left;">Estado</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>

            <br>
            <p style="color:#888; font-size:12px;">
                Este es un mensaje automático generado por el sistema POS.<br>
                {biz}
            </p>
        </div>
        """

        yag = yagmail.SMTP(email_user(), email_pass())
        yag.send(
            to=recipient,
            subject=subject,
            contents=[body],
        )

        logger.info(f"Alerta de compras enviada a {recipient} ({count} facturas)")
        return True

    except Exception as e:
        logger.error(f"Error al enviar alerta de compras: {e}")
        return False