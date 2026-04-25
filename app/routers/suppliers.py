# app/routers/suppliers.py
"""
Router delgado para proveedores.
Toda la lógica de negocio vive en services/supplier_service.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.database import get_db
from app.schemas.supplier import (
    SupplierCreate, SupplierUpdate, SupplierOut, SupplierListResponse,
)
from app.core.dependencies import get_current_user, require_role
from app.services import supplier_service as svc

router = APIRouter(prefix="/suppliers", tags=["Proveedores"])


# ==========================================================
# GET /suppliers → Listar proveedores (paginado + búsqueda)
# ==========================================================
@router.get("/", response_model=SupplierListResponse, dependencies=[Depends(get_current_user)])
def get_suppliers(
    search: Optional[str] = Query(None, description="Buscar por nombre, email, teléfono, contacto o dirección"),
    is_active: Optional[bool] = Query(None, description="Filtrar por estado activo/inactivo"),
    skip: int = Query(0, ge=0, description="Registros a saltar"),
    limit: int = Query(50, ge=1, le=500, description="Máximo de registros"),
    db: Session = Depends(get_db),
):
    return svc.list_suppliers(db, search=search, is_active=is_active, skip=skip, limit=limit)


# ==========================================================
# GET /suppliers/export/csv → Exportar CSV
# ==========================================================
@router.get("/export/csv", dependencies=[Depends(get_current_user)])
def export_csv(
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    csv_data = svc.export_suppliers_csv(db, search=search, is_active=is_active)
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=proveedores.csv"},
    )


# ==========================================================
# GET /suppliers/export/excel → Exportar Excel
# ==========================================================
@router.get("/export/excel", dependencies=[Depends(get_current_user)])
def export_excel(
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    filepath = svc.export_suppliers_excel(db, search=search, is_active=is_active)
    return FileResponse(
        filepath,
        filename="proveedores.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ==========================================================
# POST /suppliers → Crear proveedor
# ==========================================================
@router.post("/", response_model=SupplierOut, dependencies=[Depends(require_role("admin"))])
def create_supplier(data: SupplierCreate, db: Session = Depends(get_db)):
    try:
        supplier = svc.create_supplier(db, **data.model_dump())
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return supplier


# ==========================================================
# GET /suppliers/{id} → Obtener un proveedor
# ==========================================================
@router.get("/{supplier_id}", response_model=SupplierOut, dependencies=[Depends(get_current_user)])
def get_supplier(supplier_id: int, db: Session = Depends(get_db)):
    result = svc.get_supplier_by_id(db, supplier_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    return result


# ==========================================================
# PUT /suppliers/{id} → Actualizar proveedor
# ==========================================================
@router.put("/{supplier_id}", response_model=SupplierOut, dependencies=[Depends(require_role("admin"))])
def update_supplier(supplier_id: int, data: SupplierUpdate, db: Session = Depends(get_db)):
    try:
        supplier = svc.update_supplier(db, supplier_id, data.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if supplier is None:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    db.commit()
    return supplier


# ==========================================================
# PATCH /suppliers/{id}/toggle → Activar/desactivar proveedor
# ==========================================================
@router.patch("/{supplier_id}/toggle", response_model=SupplierOut, dependencies=[Depends(require_role("admin"))])
def toggle_supplier(supplier_id: int, db: Session = Depends(get_db)):
    supplier = svc.toggle_supplier(db, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    db.commit()
    return supplier


# ==========================================================
# DELETE /suppliers/{id} → Eliminar proveedor
# ==========================================================
@router.delete("/{supplier_id}", dependencies=[Depends(require_role("admin"))])
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)):
    try:
        result = svc.delete_supplier(db, supplier_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")
    db.commit()
    return {"message": "Proveedor eliminado correctamente"}