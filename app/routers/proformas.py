# app/routers/proformas.py
"""
Router de proformas/cotizaciones.
Delga toda la lógica a proforma_crud. Mismo patrón que sales.py.
"""
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models.user import User
from app.schemas.proforma import (
    ProformaCreate,
    ProformaUpdate,
    ProformaConvertRequest,
)
from app.core.dependencies import get_current_user
from app.core.logger import logger

from app.db.crud import proforma_crud
from app.services.proforma_pdf import generate_proforma_pdf


router = APIRouter(prefix="/proformas", tags=["Proformas"])


# ═══════════════════════════════════════════════════
# POST /proformas/  —  Crear proforma
# ═══════════════════════════════════════════════════
@router.post("/")
def create_proforma(
    data: ProformaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return proforma_crud.create_proforma(db, data, current_user)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al crear proforma: {e}")
        raise HTTPException(status_code=500, detail="Error interno al crear la proforma.")


# ═══════════════════════════════════════════════════
# GET /proformas/  —  Listado paginado
# ═══════════════════════════════════════════════════
@router.get("/", dependencies=[Depends(get_current_user)])
def get_proformas(
    search: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    return proforma_crud.list_proformas(
        db, search=search, status_filter=status,
        page=page, page_size=page_size,
    )


# ═══════════════════════════════════════════════════
# GET /proformas/{proforma_id}  —  Detalle
# ═══════════════════════════════════════════════════
@router.get("/{proforma_id}", dependencies=[Depends(get_current_user)])
def get_proforma(proforma_id: int, db: Session = Depends(get_db)):
    return proforma_crud.get_proforma_detail(db, proforma_id)


# ═══════════════════════════════════════════════════
# PUT /proformas/{proforma_id}  —  Editar proforma
# ═══════════════════════════════════════════════════
@router.put("/{proforma_id}")
def update_proforma(
    proforma_id: int,
    data: ProformaUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return proforma_crud.update_proforma(db, proforma_id, data)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al editar proforma #{proforma_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al editar la proforma.")


# ═══════════════════════════════════════════════════
# DELETE /proformas/{proforma_id}  —  Anular proforma
# ═══════════════════════════════════════════════════
@router.delete("/{proforma_id}")
def delete_proforma(
    proforma_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return proforma_crud.void_proforma(db, proforma_id)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al anular proforma #{proforma_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al anular la proforma.")


# ═══════════════════════════════════════════════════
# GET /proformas/{proforma_id}/validate-conversion
# Pre-validación sin crear nada
# ═══════════════════════════════════════════════════
@router.get("/{proforma_id}/validate-conversion", dependencies=[Depends(get_current_user)])
def validate_conversion(proforma_id: int, db: Session = Depends(get_db)):
    """
    Revisa stock y precios de cada línea SIN convertir.
    Retorna un reporte de discrepancias para que el frontend
    muestre el resumen antes de confirmar.
    """
    try:
        return proforma_crud.validate_conversion(db, proforma_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validando conversión de proforma #{proforma_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al validar la conversión.")


# ═══════════════════════════════════════════════════
# POST /proformas/{proforma_id}/convert  —  Convertir a venta
# ═══════════════════════════════════════════════════
@router.post("/{proforma_id}/convert")
def convert_proforma(
    proforma_id: int,
    body: ProformaConvertRequest = ProformaConvertRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return proforma_crud.convert_to_sale(db, proforma_id, body, current_user)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al convertir proforma #{proforma_id} a venta: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error interno al convertir la proforma a venta.",
        )


# ═══════════════════════════════════════════════════
# GET /proformas/{proforma_id}/pdf  —  Descargar PDF
# ═══════════════════════════════════════════════════
@router.get("/{proforma_id}/pdf", dependencies=[Depends(get_current_user)])
def download_proforma_pdf(proforma_id: int, db: Session = Depends(get_db)):
    """Genera y retorna el PDF de la proforma para descarga."""
    try:
        # Obtener datos completos de la proforma
        proforma_data = proforma_crud.get_proforma_detail(db, proforma_id)

        # Inyectar info del negocio para el PDF
        from app.services.settings_service import get_business_info
        proforma_data["business"] = get_business_info(db)

        # Generar PDF
        pdf_path = generate_proforma_pdf(proforma_data)

        if not os.path.exists(pdf_path):
            raise HTTPException(status_code=500, detail="Error al generar el PDF.")

        number = proforma_data.get("number", f"proforma_{proforma_id}")

        return FileResponse(
            pdf_path,
            filename=f"{number}.pdf",
            media_type="application/pdf",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al generar PDF de proforma #{proforma_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno al generar el PDF.")


# ═══════════════════════════════════════════════════
# POST /proformas/{proforma_id}/send-email  —  Enviar por email
# ═══════════════════════════════════════════════════
@router.post("/{proforma_id}/send-email", dependencies=[Depends(get_current_user)])
def send_proforma_email(proforma_id: int, db: Session = Depends(get_db)):
    """Genera el PDF y lo envía por email al cliente."""
    try:
        # Obtener datos completos
        proforma_data = proforma_crud.get_proforma_detail(db, proforma_id)

        # Inyectar info del negocio para PDF/email
        from app.services.settings_service import get_business_info
        biz = get_business_info(db)
        proforma_data["business"] = biz

        # Verificar que el cliente tenga email
        customer_id = proforma_data.get("customer_id")
        if not customer_id:
            raise HTTPException(
                status_code=400,
                detail="La proforma no tiene cliente asignado.",
            )

        from app.db.models.customer import Customer
        customer = db.query(Customer).filter(Customer.id == customer_id).first()

        if not customer or not customer.email:
            raise HTTPException(
                status_code=400,
                detail="El cliente no tiene correo electrónico registrado.",
            )

        # Generar PDF
        pdf_path = generate_proforma_pdf(proforma_data)

        if not os.path.exists(pdf_path):
            raise HTTPException(status_code=500, detail="Error al generar el PDF.")

        # Enviar email
        number = proforma_data.get("number", f"PRO-{proforma_id}")
        _send_proforma_email(customer.email, pdf_path, number, customer.name, biz)

        return {
            "message": f"Proforma {number} enviada por correo a {customer.email}",
            "proforma_id": proforma_id,
            "email": customer.email,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al enviar email de proforma #{proforma_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error interno al enviar el correo.",
        )


def _send_proforma_email(
    recipient: str, pdf_path: str, number: str, customer_name: str,
    business_info: dict = None,
):
    """Envía el PDF de proforma por correo. Mismo patrón que email_utils.py."""
    import yagmail
    from app.core.config import settings

    if not settings.email_user or not settings.email_pass:
        raise HTTPException(
            status_code=500,
            detail="El correo del sistema no está configurado.",
        )

    biz = business_info or {}
    biz_name = biz.get("name", "Mi Negocio")
    biz_email = biz.get("email", "")
    biz_phone = biz.get("phone", "")

    subject = f"Cotización {number} - {biz_name}"

    contact_lines = []
    if biz_phone:
        contact_lines.append(f"Tel: {biz_phone}")
    if biz_email:
        contact_lines.append(f"Correo: {biz_email}")
    contact_html = "<br>".join(contact_lines)

    body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px;">
        <h2 style="color: #1e40af;">Cotización / Proforma</h2>
        <p>Estimado(a) <b>{customer_name}</b>:</p>
        <p>Adjuntamos la cotización <b>{number}</b> según lo solicitado.</p>
        <p>Los precios indicados están sujetos a disponibilidad de inventario
        al momento de la compra.</p>
        <br>
        <p>Quedamos a su disposición para cualquier consulta.</p>
        <p><b>{biz_name}</b><br>
        {contact_html}</p>
        <hr>
        <small style="color: #999;">
            Este es un mensaje automático, por favor no responder.<br>
            Este documento no tiene validez fiscal.
        </small>
    </div>
    """

    yag = yagmail.SMTP(settings.email_user, settings.email_pass)
    yag.send(
        to=recipient,
        subject=subject,
        contents=[body, pdf_path],
    )

    logger.info(f"Proforma {number} enviada por correo a {recipient}")