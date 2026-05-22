# app/routers/customers.py

import logging
import time
import threading
from fastapi import APIRouter, Depends, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date, datetime, timedelta
from app.utils.dt import today_cr, format_cr  # FASE 2.2 — Fix 2.2: display CR
import io, csv
import requests as http_requests

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
from app.db.models.economic_activity import EconomicActivity
from app.utils.responses import success_response, error_response

logger = logging.getLogger(__name__)


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
# LOOKUP CÉDULA VÍA API DE HACIENDA
# ----------------------------------------------------------
# ── FASE 5: Consulta contribuyente por cédula ──
# API pública de Hacienda: https://api.hacienda.go.cr/fe/ae
# Rate limits: 20 req/seg burst, bloqueo de IP por 10 min.
# Caché local 24h (el estado tributario no cambia en tiempo real).

_HACIENDA_AE_URL = "https://api.hacienda.go.cr/fe/ae"

# ── FASE 3.7 — Fix 3.7: caché LRU con tope ──
# Antes era un `dict` sin límite. En una ferretería real es marginal
# (5000 entradas × ~1KB ≈ 5MB), pero un OrderedDict acotado lo hace
# constante: ~1MB en memoria como peor caso, sin riesgo si en algún
# momento alguien empieza a consultar cédulas en bucle.
from collections import OrderedDict
_CEDULA_CACHE_MAX_ENTRIES = 1000
_cedula_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_cedula_cache_lock = threading.Lock()
_CEDULA_CACHE_TTL = 86400  # 24 horas


def _cedula_cache_set(cedula: str, now: float, data: dict) -> None:
    """Inserción LRU: si llegamos al tope, descartamos la entrada más vieja."""
    with _cedula_cache_lock:
        if cedula in _cedula_cache:
            _cedula_cache.move_to_end(cedula)
        _cedula_cache[cedula] = (now, data)
        while len(_cedula_cache) > _CEDULA_CACHE_MAX_ENTRIES:
            _cedula_cache.popitem(last=False)


def _cedula_cache_get(cedula: str, now: float) -> Optional[dict]:
    """Lookup LRU con TTL. Si está vigente, lo mueve al final (más reciente)."""
    with _cedula_cache_lock:
        entry = _cedula_cache.get(cedula)
        if entry is None:
            return None
        cached_at, cached_data = entry
        if (now - cached_at) >= _CEDULA_CACHE_TTL:
            # Vencido: limpiar y reportar miss
            _cedula_cache.pop(cedula, None)
            return None
        _cedula_cache.move_to_end(cedula)
        return cached_data

# Mapeo de tipo de identificación Hacienda → display name
_ID_TYPE_MAP = {"01": "Física", "02": "Jurídica", "03": "DIMEX", "04": "NITE"}


@router.get("/lookup-cedula")
def lookup_cedula(
    identificacion: str = Query(..., min_length=9, max_length=12),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Consulta datos de un contribuyente en el API público de Hacienda CR.

    Retorna nombre, tipo de identificación y actividades económicas.
    Los códigos de actividad se insertan/actualizan automáticamente
    en la tabla economic_activities (upsert).

    Caché local de 24h para respetar los rate limits de Hacienda.
    """
    # Validar que sea numérico
    cedula = identificacion.strip()
    if not cedula.isdigit():
        raise HTTPException(status_code=400, detail="La identificación debe contener solo dígitos.")

    # ── Verificar caché (FASE 3.7 — Fix 3.7: helper LRU) ──
    now = time.monotonic()
    cached_data = _cedula_cache_get(cedula, now)
    if cached_data is not None:
        return success_response("Contribuyente encontrado (caché)", data=cached_data)

    # ── Consultar API de Hacienda ──
    try:
        resp = http_requests.get(
            _HACIENDA_AE_URL,
            params={"identificacion": cedula},
            timeout=10,
        )
    except http_requests.ConnectionError:
        raise HTTPException(
            status_code=502,
            detail="No se pudo conectar al API de Hacienda. Verifique la conexión a internet.",
        )
    except http_requests.Timeout:
        raise HTTPException(
            status_code=504,
            detail="El API de Hacienda no respondió a tiempo. Intente de nuevo.",
        )

    if resp.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail="Identificación no encontrada en los registros de Hacienda.",
        )
    if resp.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="Límite de consultas a Hacienda alcanzado. Espere unos minutos e intente de nuevo.",
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Error del API de Hacienda (HTTP {resp.status_code}).",
        )

    hacienda_data = resp.json()

    # ── Parsear respuesta ──
    tipo_id_code = hacienda_data.get("tipoIdentificacion", "")
    tipo_id_name = _ID_TYPE_MAP.get(tipo_id_code, tipo_id_code)

    actividades_raw = hacienda_data.get("actividades", [])
    actividades = []
    for act in actividades_raw:
        code = str(act.get("codigo", "")).zfill(6)
        desc = act.get("descripcion", "").strip()
        estado = act.get("estado", "")
        if code and desc:
            actividades.append({"code": code, "description": desc, "estado": estado})

    result = {
        "nombre": hacienda_data.get("nombre", ""),
        "tipoIdentificacion": tipo_id_code,
        "tipoIdentificacionNombre": tipo_id_name,
        "regimen": hacienda_data.get("regimen", {}),
        "actividades": actividades,
    }

    # ── Upsert actividades en la tabla local ──
    # Esto hace que el CSV sea innecesario a largo plazo:
    # la tabla se llena orgánicamente conforme se consultan cédulas.
    if actividades:
        try:
            for act in actividades:
                existing = db.query(EconomicActivity).filter_by(code=act["code"]).first()
                if existing:
                    if existing.description != act["description"]:
                        existing.description = act["description"]
                else:
                    db.add(EconomicActivity(code=act["code"], description=act["description"]))
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"No se pudieron guardar actividades económicas: {e}")

    # ── Guardar en caché (FASE 3.7 — Fix 3.7: helper LRU acotado) ──
    _cedula_cache_set(cedula, now, result)

    return success_response("Contribuyente encontrado", data=result)


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
    try:
        customer = create_customer(db, data)
        db.commit()
        return APIResponse(message="Cliente creado correctamente", data=customer)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al crear cliente: {e}")
        raise HTTPException(status_code=500, detail="Error interno al crear cliente.")


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
    try:
        customer = update_customer(db, customer_id, data)
        db.commit()
        return APIResponse(message="Cliente actualizado", data=customer)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al actualizar cliente: {e}")
        raise HTTPException(status_code=500, detail="Error interno al actualizar cliente.")


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
    try:
        customer = reactivate_customer(db, customer_id)
        db.commit()
        customer.economic_activity_codes = [
            a.code for a in (getattr(customer, "economic_activities", []) or [])
        ]
        return APIResponse(message="Cliente reactivado correctamente", data=customer)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error al reactivar cliente: {e}")
        raise HTTPException(status_code=500, detail="Error interno al reactivar cliente.")


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
            "created_at": format_cr(customer.created_at, "%Y-%m-%d") if customer.created_at else None,  # FASE 2.2
        },
        "stats": {
            "total_sales": total_sales,
            "total_amount": round(total_amount, 2),
            "avg_ticket": round(avg_ticket, 2),
            "frequency_per_month": frequency,
            "last_sale_date": format_cr(last_sale, "%Y-%m-%d %H:%M") if last_sale else None,  # FASE 2.2
            "first_sale_date": format_cr(first_sale, "%Y-%m-%d") if first_sale else None,  # FASE 2.2
        },
        "credit": {
            "balance": credit_balance,
            "limit": credit_limit,
            "has_limit": has_limit,
            "last_payment_date": format_cr(last_payment.created_at, "%Y-%m-%d %H:%M") if last_payment else None,  # FASE 2.2
            "last_payment_amount": float(last_payment.amount) if last_payment else None,
        },
        "recent_sales": [
            {
                "id": s.id,
                "total": float(s.total),
                "payment_method": s.payment_method,
                "date": format_cr(s.created_at, "%Y-%m-%d %H:%M"),  # FASE 2.2
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

    if not customers_with_debt:
        return success_response("Reporte de aging", data={
            "items": [],
            "totals": {"0_30": 0, "31_60": 0, "61_90": 0, "90_plus": 0, "total": 0},
        })

    # ── FASE 2 — Fix 2.2: Cargar TODOS los movimientos en 2 queries ──
    # Antes: 2 queries por cada cliente (N+1). Con 50 clientes = 100 queries.
    # Ahora: 2 queries totales sin importar cuántos clientes haya.
    customer_ids = [c.id for c in customers_with_debt]

    all_sale_movs = (
        db.query(Credit)
        .filter(Credit.customer_id.in_(customer_ids), Credit.type == "sale")
        .order_by(Credit.customer_id, Credit.created_at.asc())
        .all()
    )
    all_pay_movs = (
        db.query(Credit)
        .filter(Credit.customer_id.in_(customer_ids), Credit.type == "payment")
        .all()
    )

    # Agrupar por customer_id en Python
    from collections import defaultdict
    sales_by_cust = defaultdict(list)
    for m in all_sale_movs:
        sales_by_cust[m.customer_id].append(m)

    payments_by_cust = defaultdict(float)
    for m in all_pay_movs:
        payments_by_cust[m.customer_id] += float(m.amount or 0)

    report = []
    totals = {"0_30": 0, "31_60": 0, "61_90": 0, "90_plus": 0, "total": 0}

    for cust in customers_with_debt:
        sale_movs = sales_by_cust.get(cust.id, [])
        remaining_pay = payments_by_cust.get(cust.id, 0.0)
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