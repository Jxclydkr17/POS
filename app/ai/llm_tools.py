# app/ai/llm_tools.py
"""
FASE 6 — Definición de herramientas (tools) para el LLM.
Cada tool mapea a una función real del sistema.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session


# ═══════════════════════════════════════════════════════
# Tool schemas para Anthropic function calling
# ═══════════════════════════════════════════════════════

TOOL_DEFINITIONS: list[dict] = [
    # ─── Consultas de datos ───
    {
        "name": "query_sales",
        "description": "Consulta ventas de un periodo. Retorna total vendido, cantidad de transacciones, ticket promedio y desglose por método de pago.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "week", "month", "last_month", "year"],
                    "description": "Periodo a consultar. Default: today",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_top_products",
        "description": "Consulta los productos más vendidos en un periodo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "week", "month", "year"],
                },
                "limit": {"type": "integer", "description": "Cantidad de productos (default 5)"},
            },
            "required": [],
        },
    },
    {
        "name": "query_expenses",
        "description": "Consulta gastos de un periodo con desglose por categoría.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "week", "month", "last_month", "year"],
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_cash_status",
        "description": "Consulta el estado actual de la caja (apertura, entradas, salidas, saldo esperado).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_inventory",
        "description": "Resumen del inventario: productos activos, unidades, valor al costo y a precio venta, alertas de stock.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_low_stock",
        "description": "Lista productos con stock crítico (bajo o agotado).",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Máximo de productos (default 10)"},
            },
            "required": [],
        },
    },
    {
        "name": "query_customers",
        "description": "Resumen de clientes: total activos, con deuda, deuda total.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_debtors",
        "description": "Lista los clientes con mayor deuda pendiente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Máximo (default 5)"},
            },
            "required": [],
        },
    },
    {
        "name": "query_top_customers",
        "description": "Mejores clientes por volumen de compra en un periodo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "enum": ["week", "month", "year"]},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
    },
    {
        "name": "query_purchases",
        "description": "Resumen de compras a proveedores: total, facturas pendientes, vencidas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "enum": ["today", "week", "month", "year"]},
            },
            "required": [],
        },
    },
    {
        "name": "query_supplier_debt",
        "description": "Deuda pendiente desglosada por proveedor.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
            },
            "required": [],
        },
    },
    {
        "name": "query_product_suppliers",
        "description": (
            "Busca qué proveedores venden un producto específico, con comparación de precios. "
            "Dado un nombre o término de producto (ej. 'cemento', 'varilla', 'tornillos'), "
            "retorna la lista de proveedores que lo ofrecen, ordenados por precio de menor a mayor, "
            "con marca del mejor precio y proveedor preferido. "
            "Si el término matchea varios productos, agrupa resultados por producto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_query": {
                    "type": "string",
                    "description": "Nombre, código o término de búsqueda del producto",
                },
                "limit_products": {
                    "type": "integer",
                    "description": "Máximo de productos a incluir si hay varios matches (default 5)",
                },
            },
            "required": ["product_query"],
        },
    },
    {
        "name": "query_profit",
        "description": "Reporte financiero: ventas, costo, ganancia bruta, gastos, ganancia neta, márgenes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "enum": ["today", "yesterday", "week", "month", "last_month", "year"]},
            },
            "required": [],
        },
    },
    {
        "name": "query_daily_overview",
        "description": "Resumen rápido del día: ventas, gastos, caja, stock crítico, crédito pendiente, balance.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },

    # ─── Búsqueda de productos ───
    {
        "name": "search_products",
        "description": "Busca productos por nombre, código o barcode. Retorna lista de coincidencias con precio y stock.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Término de búsqueda"},
            },
            "required": ["query"],
        },
    },

    # ─── Acciones de escritura ───
    {
        "name": "update_price",
        "description": "Actualiza el precio de venta de un producto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_query": {"type": "string", "description": "Nombre o código del producto"},
                "new_price": {"type": "number", "description": "Nuevo precio en colones"},
            },
            "required": ["product_query", "new_price"],
        },
    },
    {
        "name": "update_cost",
        "description": "Actualiza el costo de un producto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_query": {"type": "string", "description": "Nombre o código del producto"},
                "new_cost": {"type": "number", "description": "Nuevo costo en colones"},
            },
            "required": ["product_query", "new_cost"],
        },
    },
    {
        "name": "add_stock",
        "description": "Agrega stock a un producto. Soporta cantidades decimales para productos a granel (kg, m, L).",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_query": {"type": "string", "description": "Nombre o código del producto"},
                "quantity": {"type": "number", "description": "Cantidad a agregar (acepta decimales para kg, m, L)"},
            },
            "required": ["product_query", "quantity"],
        },
    },
    {
        "name": "register_expense",
        "description": "Registra un nuevo gasto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Monto en colones"},
                "description": {"type": "string", "description": "Descripción del gasto"},
                "category": {
                    "type": "string",
                    "enum": ["Servicios", "Gastos de caja", "Sueldos", "Mantenimiento", "Compras / Proveedores", "Otros"],
                    "description": "Categoría del gasto",
                },
            },
            "required": ["amount", "description"],
        },
    },
    {
        "name": "create_customer",
        "description": "Crea un cliente nuevo rápido.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nombre completo del cliente"},
                "phone": {"type": "string", "description": "Teléfono (opcional)"},
                "id_number": {"type": "string", "description": "Cédula (opcional)"},
            },
            "required": ["name"],
        },
    },

    # ─── Navegación ───
    {
        "name": "navigate_to",
        "description": "Navega a una sección del sistema. Usa esto cuando el usuario quiera abrir/ir a una pantalla.",
        "input_schema": {
            "type": "object",
            "properties": {
                "module": {
                    "type": "string",
                    "enum": [
                        "dashboard", "sales", "sales_history", "products",
                        "customers", "expenses", "cash", "daily_report",
                        "suppliers", "purchases", "categories",
                        "financial_reports", "analytics", "settings", "credits",
                    ],
                    "description": "Módulo destino",
                },
            },
            "required": ["module"],
        },
    },
]


# ═══════════════════════════════════════════════════════
# Ejecutor de herramientas
# ═══════════════════════════════════════════════════════

# Mapeo module → section para navegación
_MODULE_SECTION_MAP = {
    "dashboard": "dashboard", "sales": "ventas", "sales_history": "registro_ventas",
    "products": "productos", "customers": "clientes", "expenses": "gastos",
    "cash": "reporte_diario", "daily_report": "reporte_diario",
    "suppliers": "proveedores", "purchases": "compras/facturas",
    "categories": "categorias", "financial_reports": "financiero",
    "analytics": "analytics", "settings": "configuración", "credits": "clientes",
}

_MODULE_LABELS = {
    "dashboard": "Dashboard", "sales": "Punto de venta", "sales_history": "Historial de ventas",
    "products": "Productos", "customers": "Clientes", "expenses": "Gastos",
    "cash": "Caja", "daily_report": "Reporte diario", "suppliers": "Proveedores",
    "purchases": "Compras / Facturas", "categories": "Categorías",
    "financial_reports": "Reportes financieros", "analytics": "Analíticas",
    "settings": "Configuración", "credits": "Créditos",
}


def execute_tool(tool_name: str, tool_input: dict, db: Session) -> dict:
    """
    Ejecuta una herramienta y retorna el resultado.
    Retorna dict con al menos "reply_text" y opcionalmente "actions", "cards".
    """
    from app.ai import data_queries as dq
    from app.ai import action_commands as cmds

    try:
        # ─── Consultas ───
        if tool_name == "query_sales":
            return dq.query_sales_summary(db, period=tool_input.get("period", "today"))

        if tool_name == "query_top_products":
            return dq.query_top_products_sold(
                db, period=tool_input.get("period", "today"),
                limit=tool_input.get("limit", 5),
            )

        if tool_name == "query_expenses":
            return dq.query_expenses_summary(db, period=tool_input.get("period", "today"))

        if tool_name == "query_cash_status":
            return dq.query_cash_status(db)

        if tool_name == "query_inventory":
            return dq.query_inventory_summary(db)

        if tool_name == "query_low_stock":
            return dq.query_low_stock_products(db, limit=tool_input.get("limit", 10))

        if tool_name == "query_customers":
            return dq.query_customers_summary(db)

        if tool_name == "query_debtors":
            return dq.query_top_debtors(db, limit=tool_input.get("limit", 5))

        if tool_name == "query_top_customers":
            return dq.query_top_customers_by_sales(
                db, period=tool_input.get("period", "month"),
                limit=tool_input.get("limit", 5),
            )

        if tool_name == "query_purchases":
            return dq.query_purchases_summary(db, period=tool_input.get("period", "month"))

        if tool_name == "query_supplier_debt":
            return dq.query_supplier_debt(db, limit=tool_input.get("limit", 5))

        if tool_name == "query_product_suppliers":
            return dq.query_product_suppliers(
                db,
                product_query=tool_input.get("product_query", ""),
                limit_products=tool_input.get("limit_products", 5),
            )

        if tool_name == "query_profit":
            return dq.query_profit_summary(db, period=tool_input.get("period", "month"))

        if tool_name == "query_daily_overview":
            return dq.query_daily_overview(db)

        # ─── Búsqueda ───
        if tool_name == "search_products":
            from app.ai.chat_handler import search_products_fuzzy
            results = search_products_fuzzy(db, tool_input.get("query", ""), limit=8)
            if not results:
                return {"reply_text": f"No encontré productos con '{tool_input.get('query', '')}'.", "data": {}}
            lines = [f"Encontré {len(results)} producto(s):"]
            for p in results:
                stock = getattr(p, "stock", "?")
                price = getattr(p, "price", 0)
                lines.append(f"  • {p.name} — ₡{float(price):,.0f} — stock: {stock}")
            return {"reply_text": "\n".join(lines), "data": {"count": len(results)}}

        # ─── Acciones ───
        if tool_name == "update_price":
            return cmds.update_product_price(db, tool_input["product_query"], tool_input["new_price"])

        if tool_name == "update_cost":
            return cmds.update_product_cost(db, tool_input["product_query"], tool_input["new_cost"])

        if tool_name == "add_stock":
            return cmds.add_product_stock(db, tool_input["product_query"], tool_input["quantity"])

        if tool_name == "register_expense":
            return cmds.register_expense(
                db,
                amount=tool_input["amount"],
                description=tool_input.get("description", ""),
                category=tool_input.get("category", "Otros"),
            )

        if tool_name == "create_customer":
            return cmds.create_customer_quick(
                db,
                name=tool_input["name"],
                phone=tool_input.get("phone"),
                id_number=tool_input.get("id_number"),
            )

        # ─── Navegación ───
        if tool_name == "navigate_to":
            module = tool_input.get("module", "dashboard")
            section = _MODULE_SECTION_MAP.get(module, module)
            label = _MODULE_LABELS.get(module, module)
            return {
                "reply_text": f"Listo 👌 te abro **{label}**.",
                "actions": [{"type": "navigate", "module": module, "section": section}],
                "data": {},
            }

        return {"reply_text": f"⚠️ Herramienta '{tool_name}' no reconocida.", "data": {}}

    except Exception as e:
        return {"reply_text": f"❌ Error ejecutando {tool_name}: {e}", "data": {}}