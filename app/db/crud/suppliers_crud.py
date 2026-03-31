# app/routers/suppliers.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.schemas.supplier import SupplierCreate, SupplierUpdate, SupplierOut
from app.db.crud.suppliers_crud import (
    get_suppliers,
    get_supplier,
    create_supplier,
    update_supplier,
    delete_supplier
)
from app.core.dependencies import get_current_user, require_role
from app.schemas.api_response import APIResponse

router = APIRouter(prefix="/suppliers", tags=["Proveedores"])


# ==========================================================
# LISTAR
# ==========================================================
@router.get("/", response_model=APIResponse[List[SupplierOut]])
def list_suppliers(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    data = get_suppliers(db)
    return APIResponse(message="Proveedores cargados", data=data)


# ==========================================================
# CREAR
# ==========================================================
@router.post("/", response_model=APIResponse[SupplierOut])
def create(
    data: SupplierCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin"))
):
    supplier = create_supplier(db, data)
    return APIResponse(message="Proveedor creado correctamente", data=supplier)


# ==========================================================
# OBTENER UNO
# ==========================================================
@router.get("/{supplier_id}", response_model=APIResponse[SupplierOut])
def get_one(
    supplier_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    supplier = get_supplier(db, supplier_id)
    return APIResponse(message="Proveedor cargado", data=supplier)


# ==========================================================
# ACTUALIZAR
# ==========================================================
@router.put("/{supplier_id}", response_model=APIResponse[SupplierOut])
def update(
    supplier_id: int,
    data: SupplierUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin"))
):
    supplier = update_supplier(db, supplier_id, data)
    return APIResponse(message="Proveedor actualizado", data=supplier)


# ==========================================================
# ELIMINAR
# ==========================================================
@router.delete("/{supplier_id}", response_model=APIResponse)
def delete(
    supplier_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_role("admin"))
):
    delete_supplier(db, supplier_id)
    return APIResponse(message="Proveedor eliminado correctamente")
