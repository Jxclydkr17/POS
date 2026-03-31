from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.db.models.customer import Customer
from app.db.models.economic_activity import EconomicActivity
from app.schemas.customer import CustomerCreate, CustomerUpdate
from sqlalchemy import or_



# 🔹 Crear cliente
def create_customer(db: Session, data: CustomerCreate):
    payload = data.dict()
    codes = payload.pop("economic_activity_codes", []) or []
    # last_purchase_date es campo cacheado, no se recibe por API
    payload.pop("last_purchase_date", None)
    
    # customer_type: si viene como enum, extraer el valor string
    ct = payload.get("customer_type")
    if ct and hasattr(ct, "value"):
        payload["customer_type"] = ct.value
    
    # Validar email duplicado
    if payload.get("email"):
        existing_email = db.query(Customer).filter(Customer.email == payload["email"]).first()
        if existing_email:
            raise HTTPException(
                status_code=400, detail="El correo ya está registrado."
            )

    # Validar número de identificación duplicado
    if payload.get("id_number"):
        existing_id = db.query(Customer).filter(Customer.id_number == payload["id_number"]).first()
        if existing_id:
            raise HTTPException(
                status_code=400, detail="Este número de identificación ya está registrado."
            )

    new_customer = Customer(**payload)

    # Asociar actividades económicas si se proporcionaron códigos
    if codes:
        acts = db.query(EconomicActivity).filter(EconomicActivity.code.in_(codes)).all()
        found = {a.code for a in acts}
        missing = [c for c in codes if c not in found]
        if missing:
            raise HTTPException(
                status_code=400, 
                detail=f"Códigos de actividad inválidos: {missing}"
            )
        new_customer.economic_activities = acts

    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)

    return new_customer


# 🔹 Obtener todos

def get_customers(
    db: Session,
    search: str = None,
    skip: int = 0,
    limit: int = 100,
    sort_by: str = None,
    sort_dir: str = "desc",
):
    query = db.query(Customer).filter(Customer.is_active == True)

    if search:
        query = query.filter(
            or_(
                Customer.name.ilike(f"%{search}%"),
                Customer.email.ilike(f"%{search}%"),
                Customer.phone.ilike(f"%{search}%"),
                Customer.id_number.ilike(f"%{search}%")
            )
        )

    # Total ANTES de paginar (para paginación en el frontend)
    total = query.count()

    # Ordenamiento
    sortable_columns = {
        "id": Customer.id,
        "name": Customer.name,
        "customer_type": Customer.customer_type,
        "credit_balance": Customer.credit_balance,
        "created_at": Customer.created_at,
        "last_purchase_date": Customer.last_purchase_date,
        "email": Customer.email,
        "phone": Customer.phone,
    }

    col = sortable_columns.get(sort_by, Customer.id)
    if sort_dir == "asc":
        query = query.order_by(col.asc())
    else:
        query = query.order_by(col.desc())

    customers = (
        query
        .offset(skip)
        .limit(limit)
        .all()
    )

    return customers, total



# 🔹 Obtener por ID
def get_customer(db: Session, customer_id: int):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return customer


# 🔹 Actualizar cliente
def update_customer(db: Session, customer_id: int, data: CustomerUpdate):
    customer = get_customer(db, customer_id)

    updated_data = data.dict(exclude_unset=True)
    codes = updated_data.pop("economic_activity_codes", None)
    # last_purchase_date es campo cacheado, no se recibe por API
    updated_data.pop("last_purchase_date", None)

    # customer_type: si viene como enum, extraer el valor string
    ct = updated_data.get("customer_type")
    if ct and hasattr(ct, "value"):
        updated_data["customer_type"] = ct.value

    # Validar duplicado email
    if "email" in updated_data and updated_data["email"]:
        exists = (
            db.query(Customer)
            .filter(Customer.email == updated_data["email"], Customer.id != customer_id)
            .first()
        )
        if exists:
            raise HTTPException(status_code=400, detail="El correo ya está registrado.")

    # Validar duplicado identificación
    if "id_number" in updated_data and updated_data["id_number"]:
        exists = (
            db.query(Customer)
            .filter(Customer.id_number == updated_data["id_number"], Customer.id != customer_id)
            .first()
        )
        if exists:
            raise HTTPException(
                status_code=400, 
                detail="Este número de identificación ya está registrado."
            )

    for key, value in updated_data.items():
        setattr(customer, key, value)

    # Actualizar actividades económicas si se proporcionaron
    if codes is not None:
        acts = db.query(EconomicActivity).filter(EconomicActivity.code.in_(codes)).all()
        found = {a.code for a in acts}
        missing = [c for c in codes if c not in found]
        if missing:
            raise HTTPException(
                status_code=400, 
                detail=f"Códigos de actividad inválidos: {missing}"
            )
        customer.economic_activities = acts  # reemplaza lista completa

    db.commit()
    db.refresh(customer)

    return customer


# 🔹 Eliminar (soft delete)
def delete_customer(db: Session, customer_id: int):
    customer = get_customer(db, customer_id)
    customer.is_active = False
    db.commit()
    return {"detail": "Cliente desactivado correctamente."}


# 🔹 Reactivar cliente
def reactivate_customer(db: Session, customer_id: int):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    if customer.is_active:
        raise HTTPException(status_code=400, detail="El cliente ya está activo.")
    customer.is_active = True
    db.commit()
    db.refresh(customer)
    return customer