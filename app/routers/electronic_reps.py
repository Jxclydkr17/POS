import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

logger = logging.getLogger(__name__)

from app.db.database import get_db
from app.core.dependencies import get_current_user

from app.db.models.credit import Credit
from app.db.models.customer import Customer
from app.db.models.issuer_profile import IssuerProfile
from app.db.models.electronic_invoice import ElectronicInvoice
from app.db.models.sale import Sale

# ✅ SOLO ventas a crédito (para filtrar pendientes REP)
from app.db.models.credit_sale import CreditSale

from app.db.models.electronic_rep import ElectronicRep
from app.db.models.electronic_rep_reference import ElectronicRepReference

from app.schemas.electronic_rep import CreateRepFromPaymentIn, SuggestRepAllocationsIn
from app.einvoice.sequence import next_sequence_number, build_consecutivo, build_clave
from app.einvoice.xml_builder import build_xml_for_rep

from app.utils.responses import success_response


router = APIRouter(prefix="/ereps", tags=["Recibo Electrónico de Pago"])


def _z2(s: str) -> str:
    s = (s or "").strip()
    if not s.isdigit() or len(s) > 2:
        raise ValueError("Código inválido")
    return s.zfill(2)


@router.post("/from-payment/{payment_id}", dependencies=[Depends(get_current_user)])
def create_rep_from_payment(
    payment_id: int,
    body: CreateRepFromPaymentIn,
    db: Session = Depends(get_db),
):
    # 1) Configuración emisor
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise HTTPException(status_code=400, detail="No existe IssuerProfile (emisor).")
    if not int(getattr(issuer, "enable_rep", 0) or 0):
        raise HTTPException(status_code=400, detail="REP está deshabilitado en issuer_profiles.enable_rep.")

    # Defaults vendibles
    condicion = _z2(body.condicion_venta_rep or (issuer.rep_default_condicion_venta or "11"))
    if condicion not in ("09", "11"):
        raise HTTPException(status_code=400, detail="En REP, condicion_venta_rep solo puede ser '09' o '11'.")

    codigo_ref = _z2(body.codigo_referencia or (issuer.rep_default_codigo_referencia or "01"))
    razon_ref = (body.razon_referencia or "Pago registrado").strip()

    # 2) Validar payment
    payment = db.query(Credit).filter(Credit.id == payment_id).first()
    if not payment or payment.type != "payment":
        raise HTTPException(status_code=404, detail="Payment no encontrado o no es tipo 'payment'.")

    # 3) Customer
    customer = db.query(Customer).filter(Customer.id == payment.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    # 4) Cargar einvoices y validar existencia
    ref_ids = [r.electronic_invoice_id for r in body.references]
    einvoices = db.query(ElectronicInvoice).filter(ElectronicInvoice.id.in_(ref_ids)).all()
    if len(einvoices) != len(ref_ids):
        raise HTTPException(status_code=400, detail="Alguna referencia no existe.")

    # 5) Crear REP base
    rep = ElectronicRep(
        credit_payment_id=payment.id,
        customer_id=customer.id,
        document_type="10",
        status="PENDING",
    )
    db.add(rep)
    db.flush()

    # 6) Determinar amounts: explícitos vs FIFO real por saldo pendiente
    total_payment = float(payment.amount or 0.0)
    if total_payment <= 0:
        raise HTTPException(status_code=400, detail="El monto del pago debe ser > 0.")

    explicit = {
        r.electronic_invoice_id: (None if r.amount_applied is None else float(r.amount_applied))
        for r in body.references
    }
    any_explicit = any(v is not None for v in explicit.values())

    # Orden FIFO: por created_at de la venta asociada (más vieja primero)
    def sort_key(einv):
        sale = getattr(einv, "sale", None)
        dt = getattr(sale, "created_at", None)
        return (dt is None, dt, einv.id)

    einvoices_sorted = sorted(einvoices, key=sort_key)

    # --- Calcular aplicado acumulado por invoice (excluyendo REPs rechazados) ---
    applied_rows = (
        db.query(
            ElectronicRepReference.electronic_invoice_id.label("eid"),
            func.coalesce(func.sum(ElectronicRepReference.amount_applied), 0).label("applied")
        )
        .join(ElectronicRep, ElectronicRep.id == ElectronicRepReference.rep_id)
        .filter(ElectronicRepReference.electronic_invoice_id.in_(ref_ids))
        .filter(ElectronicRep.status != "REJECTED")
        .group_by(ElectronicRepReference.electronic_invoice_id)
        .all()
    )
    applied_map = {int(r.eid): float(r.applied or 0.0) for r in applied_rows}

    # --- Calcular pendiente por invoice ---
    pending_map = {}
    for einv in einvoices_sorted:
        sale = getattr(einv, "sale", None)
        if not sale:
            raise HTTPException(status_code=400, detail=f"ElectronicInvoice {einv.id} no tiene sale asociado.")
        total_doc = float(getattr(sale, "total", 0) or 0)
        already = float(applied_map.get(einv.id, 0.0))
        pending = round(total_doc - already, 2)
        if pending < 0:
            pending = 0.0
        pending_map[einv.id] = pending

    allocations = []  # (einv, amount_applied)

    if any_explicit:
        # Validar montos explícitos: no exceder pendiente por invoice y suma <= pago
        sum_exp = 0.0
        for einv in einvoices_sorted:
            amt = explicit.get(einv.id)
            if amt is None:
                continue
            if amt <= 0:
                raise HTTPException(status_code=400, detail="amount_applied debe ser > 0.")
            pending = pending_map.get(einv.id, 0.0)
            if amt - pending > 0.0001:
                raise HTTPException(
                    status_code=400,
                    detail=f"amount_applied excede el saldo pendiente de invoice {einv.id}. "
                           f"Pendiente: {pending:.2f}, solicitado: {amt:.2f}"
                )
            sum_exp += amt
            allocations.append((einv, amt))

        if sum_exp - total_payment > 0.0001:
            raise HTTPException(status_code=400, detail="La suma de amount_applied excede el monto del pago.")

    else:
        # FIFO real: distribuye por pendiente hasta agotar el pago
        remaining = total_payment
        for einv in einvoices_sorted:
            if remaining <= 0:
                break
            pending = pending_map.get(einv.id, 0.0)
            if pending <= 0:
                continue
            use = pending if pending <= remaining else remaining
            use = round(use, 2)
            if use > 0:
                allocations.append((einv, use))
                remaining = round(remaining - use, 2)

    if not allocations:
        raise HTTPException(status_code=400, detail="No hay saldo pendiente aplicable para generar REP (todo ya está pagado).")

    # 7) Guardar referencias en DB
    for einv, amt in allocations:
        db.add(ElectronicRepReference(
            rep_id=rep.id,
            electronic_invoice_id=einv.id,
            amount_applied=amt
        ))

    # 8) Consecutivo/clave doc_type 10
    branch = (issuer.branch_code or "001").zfill(3)
    terminal = (issuer.terminal_code or "00001").zfill(5)
    seq_num = next_sequence_number(db, branch, terminal, "10")
    consecutivo = build_consecutivo(branch, terminal, "10", seq_num)
    clave = build_clave(issuer.id_number, consecutivo, situation="1")

    rep.consecutivo = consecutivo
    rep.clave = clave

    # 9) XML (usa las einvoices referenciadas, aunque allocations sea parcial)
    xml = build_xml_for_rep(
        db,
        payment=payment,
        customer=customer,
        referenced_einvoices=[a[0] for a in allocations],
        clave=clave,
        consecutivo=consecutivo,
        condicion_venta_rep=condicion,
        codigo_referencia=codigo_ref,
        razon_referencia=razon_ref,
    )

    rep.xml_signed = xml
    rep.status = "XML_READY"

    try:
        db.commit()
        db.refresh(rep)
    except Exception as e:
        db.rollback()
        logger.error(f"Error al guardar REP: {e}")
        raise HTTPException(status_code=500, detail="Error interno al generar REP.")

    return success_response(
        message="REP generado correctamente",
        data={
            "rep_id": rep.id,
            "status": rep.status,
            "clave": rep.clave,
            "consecutivo": rep.consecutivo,
            "allocations": [
                {"electronic_invoice_id": einv.id, "amount_applied": amt}
                for einv, amt in allocations
            ]
        }
    )


@router.get("/pending-by-customer/{customer_id}", dependencies=[Depends(get_current_user)])
def get_pending_docs_by_customer(
    customer_id: int,
    db: Session = Depends(get_db),
):
    """
    Devuelve lista de FE/TE pendientes del cliente con:
    total, aplicado (sum REP refs), pendiente, fecha y metadata útil para UI.
    """

    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise HTTPException(status_code=400, detail="No existe IssuerProfile (emisor).")
    if not int(getattr(issuer, "enable_rep", 0) or 0):
        raise HTTPException(status_code=400, detail="REP está deshabilitado en issuer_profiles.enable_rep.")

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    # 1) Traer einvoices del cliente (SOLO ventas a crédito)
    q = (
        db.query(ElectronicInvoice, Sale)
        .join(Sale, Sale.id == ElectronicInvoice.sale_id)
        .join(CreditSale, CreditSale.sale_id == Sale.id)   # ✅ SOLO ventas a crédito
        .filter(Sale.customer_id == customer_id)
    )

    rows = q.all()
    if not rows:
        return success_response(message="Sin comprobantes", data={"customer_id": customer_id, "items": []})

    einv_ids = [einv.id for einv, _sale in rows]

    # 2) Calcular aplicado acumulado por invoice (excluye REPs rechazados)
    applied_rows = (
        db.query(
            ElectronicRepReference.electronic_invoice_id.label("eid"),
            func.coalesce(func.sum(ElectronicRepReference.amount_applied), 0).label("applied")
        )
        .join(ElectronicRep, ElectronicRep.id == ElectronicRepReference.rep_id)
        .filter(ElectronicRepReference.electronic_invoice_id.in_(einv_ids))
        .filter(ElectronicRep.status != "REJECTED")
        .group_by(ElectronicRepReference.electronic_invoice_id)
        .all()
    )
    applied_map = {int(r.eid): float(r.applied or 0.0) for r in applied_rows}

    # 3) Construir items + saldo pendiente
    items = []
    for einv, sale in rows:
        total_doc = float(getattr(sale, "total", 0) or 0.0)
        applied = float(applied_map.get(einv.id, 0.0))
        pending = round(total_doc - applied, 2)
        if pending < 0:
            pending = 0.0

        # Solo mostrar pendientes reales (esto es lo que la UI quiere)
        if pending <= 0:
            continue

        # Tipo de doc para UI (FE/TE) desde tu invoice
        doc_type = (getattr(einv, "document_type", None) or "").zfill(2)

        items.append({
            "electronic_invoice_id": einv.id,
            "sale_id": sale.id,
            "document_type": doc_type,  # 01 FE, 04 TE, etc (según tu tabla)
            "clave": getattr(einv, "clave", None),
            "consecutivo": getattr(einv, "consecutivo", None),
            "sale_date": sale.created_at.strftime("%Y-%m-%d %H:%M") if getattr(sale, "created_at", None) else None,
            "total": round(total_doc, 2),
            "applied": round(applied, 2),
            "pending": pending,
        })

    # 4) Orden FIFO (más viejo primero)
    def _fifo_key(it):
        return (it["sale_date"] or "9999-99-99 99:99", it["sale_id"])

    items.sort(key=_fifo_key)

    return success_response(
        message="Pendientes calculados correctamente",
        data={
            "customer": {"id": customer.id, "name": customer.name},
            "items": items
        }
    )


@router.post("/suggest-allocations/{customer_id}", dependencies=[Depends(get_current_user)])
def suggest_allocations(
    customer_id: int,
    body: SuggestRepAllocationsIn,
    db: Session = Depends(get_db),
):
    issuer = db.query(IssuerProfile).order_by(IssuerProfile.id.asc()).first()
    if not issuer:
        raise HTTPException(status_code=400, detail="No existe IssuerProfile (emisor).")
    if not int(getattr(issuer, "enable_rep", 0) or 0):
        raise HTTPException(status_code=400, detail="REP está deshabilitado en issuer_profiles.enable_rep.")

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    amount = float(body.amount)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount debe ser > 0.")

    # 1) Traer einvoices del cliente (SOLO ventas a crédito) (o subset)
    q = (
        db.query(ElectronicInvoice, Sale)
        .join(Sale, Sale.id == ElectronicInvoice.sale_id)
        .join(CreditSale, CreditSale.sale_id == Sale.id)   # ✅ SOLO ventas a crédito
        .filter(Sale.customer_id == customer_id)
    )

    if body.electronic_invoice_ids:
        q = q.filter(ElectronicInvoice.id.in_(body.electronic_invoice_ids))

    rows = q.all()
    if not rows:
        return success_response(message="Sin comprobantes", data={"items": [], "unallocated": amount})

    einv_ids = [einv.id for einv, _sale in rows]

    # 2) aplicado acumulado (excluye REPs rechazados)
    applied_rows = (
        db.query(
            ElectronicRepReference.electronic_invoice_id.label("eid"),
            func.coalesce(func.sum(ElectronicRepReference.amount_applied), 0).label("applied")
        )
        .join(ElectronicRep, ElectronicRep.id == ElectronicRepReference.rep_id)
        .filter(ElectronicRepReference.electronic_invoice_id.in_(einv_ids))
        .filter(ElectronicRep.status != "REJECTED")
        .group_by(ElectronicRepReference.electronic_invoice_id)
        .all()
    )
    applied_map = {int(r.eid): float(r.applied or 0.0) for r in applied_rows}

    # 3) FIFO por sale.created_at (más viejo primero)
    def fifo_key(row):
        einv, sale = row
        dt = getattr(sale, "created_at", None)
        return (dt is None, dt, einv.id)

    rows_sorted = sorted(rows, key=fifo_key)

    allocations = []
    remaining = round(amount, 2)

    for einv, sale in rows_sorted:
        if remaining <= 0:
            break

        total_doc = float(getattr(sale, "total", 0) or 0.0)
        applied = float(applied_map.get(einv.id, 0.0))
        pending = round(total_doc - applied, 2)
        if pending <= 0:
            continue

        use = pending if pending <= remaining else remaining
        use = round(use, 2)
        if use <= 0:
            continue

        allocations.append({
            "electronic_invoice_id": einv.id,
            "sale_id": sale.id,
            "clave": getattr(einv, "clave", None),
            "consecutivo": getattr(einv, "consecutivo", None),
            "total": round(total_doc, 2),
            "applied": round(applied, 2),
            "pending_before": pending,
            "amount_applied": use,
            "pending_after": round(pending - use, 2),
            "sale_date": sale.created_at.strftime("%Y-%m-%d %H:%M") if getattr(sale, "created_at", None) else None,
        })

        remaining = round(remaining - use, 2)

    return success_response(
        message="Sugerencia FIFO calculada",
        data={
            "customer": {"id": customer.id, "name": customer.name},
            "amount": round(amount, 2),
            "allocated": round(amount - remaining, 2),
            "unallocated": remaining,
            "items": allocations
        }
    )