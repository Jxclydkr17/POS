# app/routers/categories.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.category import CategoryCreate, CategoryUpdate, CategoryOut
from app.schemas.api_response import APIResponse
from app.core.dependencies import get_current_user
from app.db.crud.category_crud import (
    list_categories as crud_list,
    get_category as crud_get,
    create_category as crud_create,
    update_category as crud_update,
    toggle_category as crud_toggle,
    delete_category as crud_delete,
)


router = APIRouter(prefix="/categories", tags=["Categories"])


# ----------------------------------------------------------
# ✅ LISTAR
# ----------------------------------------------------------
@router.get("/", response_model=APIResponse[list[CategoryOut]])
def list_categories(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    data = crud_list(db)
    return APIResponse(message="Categorías cargadas", data=data)


# ----------------------------------------------------------
# ✅ OBTENER UNA
# ----------------------------------------------------------
@router.get("/{category_id}", response_model=APIResponse[CategoryOut])
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    data = crud_get(db, category_id)
    return APIResponse(message="Categoría cargada", data=data)


# ----------------------------------------------------------
# ✅ CREAR
# FASE 1 — Fix 1.2: Router es dueño del commit
# ----------------------------------------------------------
@router.post("/", response_model=APIResponse[CategoryOut])
def create_category(
    data: CategoryCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        cat = crud_create(db, data)
        db.commit()
        return APIResponse(message="Categoría creada correctamente", data=cat)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al crear categoría: {e}")


# ----------------------------------------------------------
# ✅ ACTUALIZAR
# ----------------------------------------------------------
@router.put("/{category_id}", response_model=APIResponse[CategoryOut])
def update_category(
    category_id: int,
    data: CategoryUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        cat = crud_update(db, category_id, data)
        db.commit()
        return APIResponse(message="Categoría actualizada", data=cat)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar categoría: {e}")


# ----------------------------------------------------------
# ✅ TOGGLE ACTIVO / INACTIVO
# ----------------------------------------------------------
@router.patch("/{category_id}/toggle", response_model=APIResponse[CategoryOut])
def toggle_category_active(
    category_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        cat = crud_toggle(db, category_id)
        db.commit()
        return APIResponse(message="Estado actualizado", data=cat)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al cambiar estado: {e}")


# ----------------------------------------------------------
# ✅ ELIMINAR CON VALIDACIÓN DE PRODUCTOS
# ----------------------------------------------------------
@router.delete("/{category_id}", response_model=APIResponse)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        result = crud_delete(db, category_id)
        db.commit()
        return APIResponse(message=result["message"])
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar categoría: {e}")