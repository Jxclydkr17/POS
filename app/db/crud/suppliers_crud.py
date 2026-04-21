"""
app/db/crud/suppliers_crud.py — DEPRECADO

Este módulo NO contiene funciones CRUD de proveedores.
Toda la lógica de proveedores está en:

    app/services/supplier_service.py

El router real es:

    app/routers/suppliers.py

Este archivo se mantiene vacío para evitar que un import
accidental cause errores. Si necesita funciones CRUD de
proveedores, use supplier_service directamente.

AUDITORÍA FIX 1.3: Archivo original contenía una copia del router
de proveedores con import circular de sí mismo, lo que causaría
ImportError si alguien lo importaba.
"""

# No exportar nada — todo vive en supplier_service.py