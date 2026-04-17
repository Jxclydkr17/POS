# app/utils/db_compat.py
"""
Helpers portables para funciones SQL que difieren entre MySQL y SQLite.

MySQL tiene funciones nativas (DATEDIFF, YEAR, MONTH) que no existen
en SQLite.  Este módulo expone wrappers que generan la expresión
SQLAlchemy correcta según el motor configurado.

Uso:
    from app.utils.db_compat import sql_datediff, sql_year, sql_month

    # En vez de  func.datediff(a, b)
    sql_datediff(Purchase.paid_at, Purchase.entry_date)

    # En vez de  func.year(col)  /  func.month(col)
    sql_year(Purchase.entry_date)
    sql_month(Purchase.entry_date)
"""

from __future__ import annotations

from sqlalchemy import func, cast, Integer

from app.core.config import is_sqlite


# ------------------------------------------------------------------
# DATEDIFF  (date_a − date_b  →  días enteros)
# ------------------------------------------------------------------
def sql_datediff(date_a, date_b):
    """
    Diferencia en días entre *date_a* y *date_b*  (date_a − date_b).

    - MySQL:  DATEDIFF(date_a, date_b)          → int
    - SQLite: julianday(date_a) − julianday(date_b)  → float
              (se deja sin cast para que func.avg() trabaje con precisión;
               si necesitas entero, envuélvelo en cast(..., Integer)).
    """
    if is_sqlite():
        return func.julianday(date_a) - func.julianday(date_b)
    return func.datediff(date_a, date_b)


# ------------------------------------------------------------------
# YEAR  /  MONTH  (extraer componente de una fecha)
# ------------------------------------------------------------------
def sql_year(col):
    """
    Extrae el año de una columna de fecha.

    - MySQL:  YEAR(col)                → int
    - SQLite: CAST(strftime('%Y', col) AS INTEGER)  → int

    Se castea a Integer para que los valores resultantes
    sean comparables con enteros de Python (ej. en dict keys).
    """
    if is_sqlite():
        return cast(func.strftime('%Y', col), Integer)
    return func.year(col)


def sql_month(col):
    """
    Extrae el mes de una columna de fecha.

    - MySQL:  MONTH(col)               → int
    - SQLite: CAST(strftime('%m', col) AS INTEGER)  → int

    El cast elimina ceros a la izquierda ("03" → 3) y garantiza
    que el tipo coincida con los enteros de Python.
    """
    if is_sqlite():
        return cast(func.strftime('%m', col), Integer)
    return func.month(col)


# ------------------------------------------------------------------
# LOCK FOR UPDATE  (bloqueo pesimista portable)
# ------------------------------------------------------------------
def lock_for_update(query):
    """
    Aplica WITH FOR UPDATE solo si el motor lo soporta (MySQL).
    SQLite no soporta bloqueos pesimistas — retorna la query sin cambios.

    Uso:
        from app.utils.db_compat import lock_for_update

        product = lock_for_update(
            db.query(Product).filter(Product.id == pid)
        ).first()
    """
    if is_sqlite():
        return query
    return query.with_for_update()


# ------------------------------------------------------------------
# ESCAPE LIKE  (sanitizar wildcards en búsquedas)
# ------------------------------------------------------------------
def escape_like(value: str) -> str:
    """
    Escapa los caracteres comodín de SQL LIKE en el input del usuario.

    Sin esto, si alguien busca '%' o '_', SQLAlchemy los interpreta
    como wildcards y retorna resultados inesperados.
    No es SQL injection (SQLAlchemy parametriza), pero sí
    comportamiento inesperado.

    Uso:
        from app.utils.db_compat import escape_like

        # En vez de  Product.name.ilike(f"%{search}%")
        safe = escape_like(search)
        Product.name.ilike(f"%{safe}%")
    """
    if not value:
        return value
    return (
        value
        .replace("\\", "\\\\")  # escape backslash primero
        .replace("%", "\\%")
        .replace("_", "\\_")
    )