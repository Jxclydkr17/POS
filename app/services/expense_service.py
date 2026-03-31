from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException
from app.db.models.expense import Expense
from app.core.logger import logger
from typing import Optional
from app.utils.dt import utcnow



def add_expense_service(expense: dict, db: Session, user_id: int = None):
    """Registra un nuevo gasto en la base de datos"""
    try:
        # Aseguramos que el monto sea float para evitar errores de tipo
        amount_val = float(expense.get("amount", 0))
        
        # Manejo de fecha más seguro
        expense_date = utcnow()
        if expense.get("date"):
            try:
                expense_date = datetime.strptime(expense.get("date"), "%Y-%m-%d")
            except ValueError:
                expense_date = utcnow()

        new_expense = Expense(
            category=expense.get("category"),
            description=expense.get("description"),
            amount=amount_val,
            payment_method=expense.get("payment_method", "Efectivo"),
            date=expense_date,
            user_id=user_id,
        )
        db.add(new_expense)
        db.flush()
        logger.info(f"Gasto preparado: {new_expense.amount:.2f}")
        return new_expense
    except Exception as e:
        logger.error(f"Error en add_expense_service: {e}")
        raise e



def update_expense_service(expense_id: int, updates: dict, db: Session):
    """Actualiza un gasto existente. Solo modifica los campos enviados."""
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")

    for field, value in updates.items():
        if value is not None and hasattr(expense, field):
            setattr(expense, field, value)

    db.flush()
    logger.info(f"Gasto #{expense_id} actualizado")
    return expense



def get_expenses_service(
    db: Session,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
):
    """
    Obtiene gastos con filtros, paginación y totales.
    """
    try:
        query = db.query(Expense)

        # -------------------------------------------------
        # 1️⃣ Filtro de fechas (incluye todo el día)
        # -------------------------------------------------
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(Expense.date >= start_dt)

        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            query = query.filter(Expense.date <= end_dt)

        # -------------------------------------------------
        # 2️⃣ Filtro de categoría
        # -------------------------------------------------
        if category:
            category_clean = category.strip()
            if category_clean.lower() not in ["todos", "todo", ""]:
                query = query.filter(
                    Expense.category == category_clean
                )

        # -------------------------------------------------
        # 3️⃣ Total de registros (SIN paginación) — SQL COUNT
        # -------------------------------------------------
        total_count = query.count()

        # -------------------------------------------------
        # 4️⃣ Total de monto (SIN paginación) — SQL SUM
        #    Usa func.sum() directo en BD en vez de cargar
        #    todos los registros a memoria.
        # -------------------------------------------------
        total_amount_result = (
            query
            .with_entities(func.coalesce(func.sum(Expense.amount), 0))
            .scalar()
        )
        total_amount = float(total_amount_result)

        # -------------------------------------------------
        # 5️⃣ Aplicar paginación
        # -------------------------------------------------
        expenses = (
            query
            .order_by(Expense.date.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        # -------------------------------------------------
        # 6️⃣ Serializar
        # -------------------------------------------------
        return {
            "items": [
                {
                    "id": e.id,
                    "category": e.category,
                    "description": e.description,
                    "amount": float(e.amount),
                    "date": e.date.strftime("%Y-%m-%d") if e.date else None,
                    "payment_method": e.payment_method,
                    "user_id": e.user_id,
                    "created_by": e.user.username if e.user else None,
                }
                for e in expenses
            ],
            "total_count": total_count,
            "total_amount": round(total_amount, 2),
        }

    except Exception as e:
        logger.error(f"Error al obtener gastos: {e}")
        raise HTTPException(status_code=500, detail="Error obteniendo gastos")


def delete_expense_service(expense_id: int, db: Session):
    """Elimina un gasto por ID"""
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Not Found")

    db.delete(expense)
    db.flush()
    return {"expense_id": expense_id}