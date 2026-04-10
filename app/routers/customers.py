# app/routers/customers.py

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
from datetime import date, datetime, timedelta
from app.utils.dt import today_cr
import io, csv

from app.db.database import get_db
from app.schemas.customer import CustomerCreate, CustomerUpdate, CustomerOut
from app.db.crud.customer_crud import (
    create_customer,
    get_customers,
    get_customer,
    update_customer,
    delete_customer,
    reactivate_customer,
)
from app.core.dependencies import get_current_user
from app.schemas.api_response import APIResponse

from fastapi import HTTPException
from sqlalchemy import func
from app.db.models.customer import Customer
from app.db.models.sale import Sale
from app.db.models.sale_detail import SaleDetail
from app.db.models.credit import Credit
from app.db.models.credit_sale import CreditSale
from app.utils.responses import success_response, error_response


router = APIRouter(prefix="/customers", tags=["Customers"])


# ----------------------------------------------------------
# LISTAR
# ----------------------------------------------------------
@router.get("/", response_model=APIResponse[List[CustomerOut]])
def list_customers(
    search: str = None,
    skip: int = 0,  
    limit: int = 50,
    sort_by: str = None,
    sort_dir: str = "desc",
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    
    if limit > 100:
        limit = 100
    data, total = get_customers(db, search, skip, limit, sort_by, sort_dir)
    
    # Agregar economic_activity_codes a cada cliente
    for c in data:
        c.economic_activity_codes = [a.code for a in (getattr(c, "economic_activities", []) or [])]
    
    return APIResponse(message="Clientes cargados", data=data, total=total)


# ----------------------------------------------------------
# OBTENER UN CLIENTE POR ID
# ----------------------------------------------------------
@router.get("/{customer_id}", response_model=APIResponse[CustomerOut])
def get_customer_by_id(
    customer_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    customer = get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    # Agregar economic_activity_codes al cliente
    customer.economic_activity_codes = [a.code for a in (getattr(customer, "economic_activities", []) or [])]
    
    return APIResponse(message="Cliente obtenido", data=customer)


# ----------------------------------------------------------
# CREAR
# ----------------------------------------------------------
@router.post("/", response_model=APIResponse[CustomerOut])
def create(
    data: CustomerCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    customer = create_customer(db, data)
    return APIResponse(message="Cliente creado correctamente", data=customer)


# ----------------------------------------------------------
# ACTUALIZAR
# ----------------------------------------------------------
@router.put("/{customer_id}", response_model=APIResponse[CustomerOut])
def update(
    customer_id: int,
    data: CustomerUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    customer = update_customer(db, customer_id, data)
    return APIResponse(message="Cliente actualizado", data=customer)


# ----------------------------------------------------------
# ELIMINAR (SOFT DELETE)
# ----------------------------------------------------------

@router.delete("/{customer_id}", response_model=APIResponse)
def delete(
    customer_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id)
        .first()
    )

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Cliente no encontrado."
        )

    # ✅ Validar que no tenga ventas asociadas (ORM)
    sales_count = (
        db.query(func.count(Sale.id))
        .filter(Sale.customer_id == customer_id)
        .scalar()
    )

    if sales_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"No se puede desactivar el cliente. Tiene {sales_count} ventas asociadas."
        )

    # 👉 Soft delete (recomendado)
    customer.is_active = False
    # FASE 4 — Fix 4.1: try/except + rollback
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return APIResponse(message="Cliente desactivado correctamente")


# ----------------------------------------------------------
# REACTIVAR CLIENTE
# ----------------------------------------------------------
@router.post("/{customer_id}/reactivate", response_model=APIResponse[CustomerOut])
def reactivate(
    customer_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    customer = reactivate_customer(db, customer_id)
    customer.economic_activity_codes = [
        a.code for a in (getattr(customer, "economic_activities", []) or [])
    ]
    return APIResponse(message="Cliente reactivado correctamente", data=customer)


# ----------------------------------------------------------
# PERFIL COMPLETO DEL CLIENTE
# ----------------------------------------------------------
@router.get("/{customer_id}/profile")
def customer_profile(
    customer_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    today = today_cr()

    # Ventas totales (cash + crédito)
    sales_data = (
        db.query(
            func.count(Sale.id).label("total_sales"),
            func.sum(Sale.total).label("total_amount"),
            func.avg(Sale.total).label("avg_ticket"),
            func.max(Sale.created_at).label("last_sale_date"),
            func.min(Sale.created_at).label("first_sale_date"),
        )
        .filter(Sale.customer_id == customer_id)
        .first()
    )

    total_sales = int(sales_data.total_sales or 0)
    total_amount = float(sales_data.total_amount or 0)
    avg_ticket = float(sales_data.avg_ticket or 0)
    last_sale = sales_data.last_sale_date
    first_sale = sales_data.first_sale_date

    # Frecuencia (compras por mes)
    if first_sale and total_sales > 1:
        months_active = max(1, (today - first_sale.date()).days / 30)
        frequency = round(total_sales / months_active, 1)
    else:
        frequency = 0

    # Últimas 10 compras
    recent_sales = (
        db.query(Sale)
        .filter(Sale.customer_id == customer_id)
        .order_by(Sale.created_at.desc())
        .limit(10)
        .all()
    )

    # Crédito
    credit_balance = float(customer.credit_balance or 0)
    credit_limit = float(customer.credit_limit or 0)
    has_limit = bool(customer.has_credit_limit)

    # Último pago
    last_payment = (
        db.query(Credit)
        .filter(Credit.customer_id == customer_id, Credit.type == "payment")
        .order_by(Credit.created_at.desc())
        .first()
    )

    return success_response("Perfil cargado", data={
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "phone": customer.phone,
            "secondary_phone": getattr(customer, "secondary_phone", None),
            "address": customer.address,
            "id_type": customer.id_type,
            "id_number": customer.id_number,
            "customer_type": customer.customer_type,
            "province_name": customer.province_name,
            "canton_name": customer.canton_name,
            "district_name": customer.district_name,
            "notes": getattr(customer, "notes", None),
            "birth_date": str(customer.birth_date) if getattr(customer, "birth_date", None) else None,
            "is_active": customer.is_active,
            "created_at": customer.created_at.strftime("%Y-%m-%d") if customer.created_at else None,
        },
        "stats": {
            "total_sales": total_sales,
            "total_amount": round(total_amount, 2),
            "avg_ticket": round(avg_ticket, 2),
            "frequency_per_month": frequency,
            "last_sale_date": last_sale.strftime("%Y-%m-%d %H:%M") if last_sale else None,
            "first_sale_date": first_sale.strftime("%Y-%m-%d") if first_sale else None,
        },
        "credit": {
            "balance": credit_balance,
            "limit": credit_limit,
            "has_limit": has_limit,
            "last_payment_date": last_payment.created_at.strftime("%Y-%m-%d %H:%M") if last_payment else None,
            "last_payment_amount": float(last_payment.amount) if last_payment else None,
        },
        "recent_sales": [
            {
                "id": s.id,
                "total": float(s.total),
                "payment_method": s.payment_method,
                "date": s.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for s in recent_sales
        ],
    })


# ----------------------------------------------------------
# REPORTE DE AGING GLOBAL
# ----------------------------------------------------------
@router.get("/reports/aging")
def aging_report(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    today = today_cr()

    customers_with_debt = (
        db.query(Customer)
        .filter(Customer.is_active == True, Customer.credit_balance > 0)
        .all()
    )

    report = []
    totals = {"0_30": 0, "31_60": 0, "61_90": 0, "90_plus": 0, "total": 0}

    for cust in customers_with_debt:
        # Ventas a crédito del cliente
        sale_movs = (
            db.query(Credit)
            .filter(Credit.customer_id == cust.id, Credit.type == "sale")
            .order_by(Credit.created_at.asc())
            .all()
        )
        pay_movs = (
            db.query(Credit)
            .filter(Credit.customer_id == cust.id, Credit.type == "payment")
            .all()
        )

        remaining_pay = sum(float(m.amount or 0) for m in pay_movs)
        aging = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}

        for sm in sale_movs:
            amt = float(sm.amount or 0)
            if remaining_pay >= amt:
                remaining_pay -= amt
                continue
            unpaid = amt - remaining_pay
            remaining_pay = 0
            days = (today - sm.created_at.date()).days if sm.created_at else 0
            if days <= 30:
                aging["0_30"] += unpaid
            elif days <= 60:
                aging["31_60"] += unpaid
            elif days <= 90:
                aging["61_90"] += unpaid
            else:
                aging["90_plus"] += unpaid

        row_total = sum(aging.values())
        if row_total <= 0:
            continue

        for k in aging:
            aging[k] = round(aging[k], 2)
            totals[k] += aging[k]
        totals["total"] += round(row_total, 2)

        report.append({
            "customer_id": cust.id,
            "name": cust.name,
            "id_number": cust.id_number or "",
            "phone": cust.phone or "",
            "balance": round(float(cust.credit_balance or 0), 2),
            **aging,
        })

    report.sort(key=lambda x: x["balance"], reverse=True)

    return success_response("Reporte de aging", data={
        "items": report,
        "totals": {k: round(v, 2) for k, v in totals.items()},
    })


# ----------------------------------------------------------
# EXPORTAR CLIENTES A CSV
# ----------------------------------------------------------
@router.get("/export/csv")
def export_customers_csv(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    customers = db.query(Customer).filter(Customer.is_active == True).order_by(Customer.id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Nombre", "Correo", "Teléfono", "Tel. Secundario",
        "Dirección", "Tipo ID", "N° Identificación", "Tipo Cliente",
        "Provincia", "Cantón", "Distrito", "Saldo Crédito",
        "Límite Crédito", "Notas",
    ])
    for c in customers:
        writer.writerow([
            c.id, c.name, c.email or "", c.phone or "",
            getattr(c, "secondary_phone", "") or "",
            c.address or "", c.id_type or "", c.id_number or "",
            c.customer_type or "Normal",
            c.province_name or "", c.canton_name or "", c.district_name or "",
            float(c.credit_balance or 0), float(c.credit_limit or 0),
            getattr(c, "notes", "") or "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=clientes.csv"}
    )


# ----------------------------------------------------------
# IMPORTAR CLIENTES DESDE CSV
# ----------------------------------------------------------
@router.post("/import/csv")
async def import_customers_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    created = 0
    errors = []

    for i, row in enumerate(reader, start=2):
        name = (row.get("Nombre") or "").strip()
        if not name:
            errors.append({"row": i, "error": "Nombre es obligatorio"})
            continue

        email = (row.get("Correo") or "").strip() or None
        id_number = (row.get("N° Identificación") or row.get("N° Identificacion") or "").strip() or None

        # Verificar duplicados
        if email and db.query(Customer).filter(Customer.email == email).first():
            errors.append({"row": i, "error": f"Correo duplicado: {email}"})
            continue
        if id_number and db.query(Customer).filter(Customer.id_number == id_number).first():
            errors.append({"row": i, "error": f"Identificación duplicada: {id_number}"})
            continue

        try:
            cust = Customer(
                name=name,
                email=email,
                phone=(row.get("Teléfono") or row.get("Telefono") or "").strip() or None,
                secondary_phone=(row.get("Tel. Secundario") or "").strip() or None,
                address=(row.get("Dirección") or row.get("Direccion") or "").strip() or None,
                id_type=(row.get("Tipo ID") or "").strip() or None,
                id_number=id_number,
                customer_type=(row.get("Tipo Cliente") or "Normal").strip(),
                province_name=(row.get("Provincia") or "").strip() or None,
                canton_name=(row.get("Cantón") or row.get("Canton") or "").strip() or None,
                district_name=(row.get("Distrito") or "").strip() or None,
                notes=(row.get("Notas") or "").strip() or None,
            )
            db.add(cust)
            db.flush()
            created += 1
        except Exception as e:
            errors.append({"row": i, "error": str(e)})

    # FASE 4 — Fix 4.1: try/except + rollback
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error al guardar clientes importados: {e}"
        )

    return success_response(
        f"{created} clientes importados correctamente.",
        data={"created": created, "errors": errors}
    )