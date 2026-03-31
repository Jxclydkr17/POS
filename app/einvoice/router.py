from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import ElectronicInvoice, IssuerProfile, Sale, SaleDetail, Product, Customer
from app.einvoice.xml_builder_v43 import build_xml_for_sale

router = APIRouter(prefix="/einvoices", tags=["Electronic Invoices"])


@router.post("/{einvoice_id}/build-xml")
def build_xml(einvoice_id: int, db: Session = Depends(get_db)):
    einv = db.query(ElectronicInvoice).filter(ElectronicInvoice.id == einvoice_id).first()
    if not einv:
        raise HTTPException(status_code=404, detail="ElectronicInvoice no existe")

    sale = db.query(Sale).filter(Sale.id == einv.sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale no existe")

    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise HTTPException(status_code=400, detail="No existe issuer_profile (configuración del emisor)")

    customer = None
    if sale.customer_id:
        customer = db.query(Customer).filter(Customer.id == sale.customer_id).first()

    details = db.query(SaleDetail).filter(SaleDetail.sale_id == sale.id).all()

    # Construir líneas con CABYS + impuesto desde Product
    lines = []
    for d in details:
        p = db.query(Product).filter(Product.id == d.product_id).first()
        if not p:
            continue
        lines.append({
            "quantity": d.quantity,
            "unit_price": d.unit_price,
            "discount_percent": d.discount_percent,
            "cabys_code": p.cabys_code,
            "name": p.name,
            "tax_rate": p.tax_rate or 0,
            "unit_type": p.unit_type or "Unid",
        })

    xml = build_xml_for_sale(
        document_type=einv.document_type,
        clave=einv.clave,
        consecutivo=einv.consecutivo,
        issuer={
            "legal_name": issuer.legal_name,
            "commercial_name": issuer.commercial_name,
            "id_type": issuer.id_type,
            "id_number": issuer.id_number,
            "email": issuer.email,
            "phone": issuer.phone,
            "provincia": issuer.provincia,
            "canton": issuer.canton,
            "distrito": issuer.distrito,
            "barrio": issuer.barrio,
            "otras_senas": issuer.otras_senas,
            "branch_code": issuer.branch_code,
            "terminal_code": issuer.terminal_code,
        },
        customer=(None if not customer else {
            "name": customer.name,
            "id_type": customer.id_type,
            "id_number": customer.id_number,
            "email": customer.email,
            "phone": customer.phone,
            "address": customer.address,
        }),
        sale={
            "id": sale.id,
            "total": sale.total,
            "payment_method": sale.payment_method,
        },
        lines=lines,
    )

    einv.xml_signed = xml  # por ahora aquí (aunque no esté firmado)
    einv.status = "XML_READY"
    db.commit()

    return {"ok": True, "einvoice_id": einv.id, "status": einv.status}