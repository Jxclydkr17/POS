# app/db/crud/category_crud.py

from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException

from app.db.models.category import Category
from app.db.models.product import Product
from app.schemas.category import CategoryCreate, CategoryUpdate


# ----------------------------------------------------------
# LISTAR  (ORM puro, sin vista SQL)
# ----------------------------------------------------------
def list_categories(db: Session) -> list[dict]:
    rows = (
        db.query(
            Category.id,
            Category.name,
            Category.description,
            Category.icon,
            Category.is_active,
            Category.position,
            Category.created_at,
            Category.updated_at,
            func.count(Product.id).label("total_products"),
        )
        .outerjoin(Product, Product.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.position, Category.name)
        .all()
    )
    return [row._asdict() for row in rows]


# ----------------------------------------------------------
# OBTENER UNA
# ----------------------------------------------------------
def get_category(db: Session, category_id: int) -> dict:
    row = (
        db.query(
            Category.id,
            Category.name,
            Category.description,
            Category.icon,
            Category.is_active,
            Category.position,
            Category.created_at,
            Category.updated_at,
            func.count(Product.id).label("total_products"),
        )
        .outerjoin(Product, Product.category_id == Category.id)
        .filter(Category.id == category_id)
        .group_by(Category.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Categoría no encontrada.")
    return row._asdict()


# ----------------------------------------------------------
# CREAR
# ----------------------------------------------------------
def create_category(db: Session, data: CategoryCreate) -> Category:
    existing = db.query(Category).filter(Category.name == data.name).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Ya existe una categoría con ese nombre.",
        )

    new_cat = Category(
        name=data.name.strip(),
        description=data.description,
        icon=data.icon or "📦",
        is_active=data.is_active,
        position=data.position,
    )
    db.add(new_cat)
    # FASE 1 — Fix 1.2: flush only; router owns commit
    db.flush()
    db.refresh(new_cat)
    return new_cat


# ----------------------------------------------------------
# ACTUALIZAR (parcial — solo toca los campos enviados)
# ----------------------------------------------------------
def update_category(
    db: Session, category_id: int, data: CategoryUpdate
) -> Category:
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada.")

    fields = data.model_dump(exclude_unset=True)

    if "name" in fields:
        duplicate = (
            db.query(Category)
            .filter(Category.name == fields["name"], Category.id != category_id)
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=400,
                detail="Ya existe otra categoría con ese nombre.",
            )
        cat.name = fields["name"].strip()

    if "description" in fields:
        cat.description = fields["description"]

    if "icon" in fields:
        cat.icon = fields["icon"] or "📦"

    if "is_active" in fields:
        cat.is_active = fields["is_active"]

    if "position" in fields:
        cat.position = fields["position"]

    # FASE 1 — Fix 1.2: flush only; router owns commit
    db.flush()
    db.refresh(cat)
    return cat


# ----------------------------------------------------------
# TOGGLE ACTIVO / INACTIVO
# ----------------------------------------------------------
def toggle_category(db: Session, category_id: int) -> Category:
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada.")

    cat.is_active = not bool(cat.is_active)
    # FASE 1 — Fix 1.2: flush only; router owns commit
    db.flush()
    db.refresh(cat)
    return cat


# ----------------------------------------------------------
# ELIMINAR (smart delete: desactiva si tiene productos)
# ----------------------------------------------------------
def delete_category(db: Session, category_id: int) -> dict:
    """Devuelve {'message': ..., 'soft': bool}"""
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Categoría no encontrada.")

    product_count = (
        db.query(func.count(Product.id))
        .filter(Product.category_id == category_id)
        .scalar()
    )

    if product_count > 0:
        cat.is_active = False
        # FASE 1 — Fix 1.2: flush only; router owns commit
        db.flush()
        db.refresh(cat)
        return {
            "message": "Categoría desactivada (tiene productos asociados).",
            "soft": True,
        }

    db.delete(cat)
    # FASE 1 — Fix 1.2: flush only; router owns commit
    db.flush()
    return {"message": "Categoría eliminada correctamente", "soft": False}