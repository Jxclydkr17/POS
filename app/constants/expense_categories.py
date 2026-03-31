# app/constants/expense_categories.py

# ---------------------------------------------------------------
# Fuente única de verdad para categorías de gastos operativos.
# Cualquier combo, filtro o lógica que necesite categorías
# debe importar de aquí.
# ---------------------------------------------------------------

CAT_SERVICIOS = "Servicios"
CAT_GASTOS_CAJA = "Gastos de caja"
CAT_SUELDOS = "Sueldos"
CAT_MANTENIMIENTO = "Mantenimiento"
CAT_COMPRAS_PROVEEDORES = "Compras / Proveedores"
CAT_OTROS = "Otros"

# Categorías que el usuario puede seleccionar al registrar un gasto manual
EXPENSE_CATEGORIES = [
    CAT_SERVICIOS,
    CAT_GASTOS_CAJA,
    CAT_SUELDOS,
    CAT_MANTENIMIENTO,
    CAT_COMPRAS_PROVEEDORES,
    CAT_OTROS,
]

# Misma lista con "Todos" al inicio, para combos de filtro
EXPENSE_CATEGORIES_FILTER = ["Todos"] + EXPENSE_CATEGORIES