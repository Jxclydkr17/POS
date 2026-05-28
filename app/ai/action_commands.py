# app/ai/action_commands.py
"""
FASE 3 — Acciones ampliadas desde el chat.
Ejecuta operaciones de escritura contra la BD y devuelve confirmación.

Cubre:
  - Actualizar precios
  - Agregar stock
  - Registrar gastos
  - Crear clientes
  - Navegación a todas las secciones
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.utils.dt import today_cr

from app.ai.fuzzy import normalize_text, fix_typos, keyword_in_text, any_keyword_in_text


# ─────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────

def _fmt(val) -> str:
    try:
        return f"₡{float(val):,.2f}"
    except Exception:
        return "—"


def _find_product_by_query(db: Session, query: str):
    """Busca un producto por nombre, código o barcode. Retorna (product, match_count)."""
    from app.db.models.product import Product
    from sqlalchemy import or_ as sa_or
    from app.utils.db_compat import escape_like

    q = (query or "").strip()
    if not q:
        return None, 0

    # Exact by code/barcode
    exact = (
        db.query(Product)
        .filter(sa_or(Product.code == q, Product.barcode == q))
        .first()
    )
    if exact:
        return exact, 1

    # ILIKE name/code
    safe_q = escape_like(q)
    rows = (
        db.query(Product)
        .filter(
            sa_or(
                Product.name.ilike(f"%{safe_q}%"),
                Product.code.ilike(f"%{safe_q}%"),
            )
        )
        .filter(Product.is_active == True)
        .order_by(Product.name.asc())
        .limit(5)
        .all()
    )
    if not rows:
        return None, 0
    if len(rows) == 1:
        return rows[0], 1
    return rows, len(rows)


# ═════════════════════════════════════════════════════
# 1) ACTUALIZAR PRECIO
# ═════════════════════════════════════════════════════

def update_product_price(db: Session, product_query: str, new_price: float) -> dict:
    """
    Actualiza el precio de un producto.
    Retorna dict con reply_text, actions, data.
    """
    if new_price <= 0:
        return {
            "reply_text": "⚠️ El precio debe ser mayor a cero.",
            "actions": [],
            "data": {},
        }

    result, count = _find_product_by_query(db, product_query)

    if result is None:
        return {
            "reply_text": f"No encontré el producto **{product_query}**. Verificá el nombre o código.",
            "actions": [],
            "data": {},
        }

    if isinstance(result, list):
        lines = [f"Encontré **{count}** productos con **{product_query}**. ¿Cuál querés actualizar?"]
        for i, p in enumerate(result, 1):
            lines.append(f"  {i}. {p.name} — {_fmt(p.price)} — código: {p.code or '—'}")
        lines.append("\nSé más específico con el nombre o usá el código.")
        return {
            "reply_text": "\n".join(lines),
            "actions": [],
            "data": {"ambiguous": True, "count": count},
        }

    product = result
    old_price = float(product.price or 0)

    try:
        product.price = new_price
        db.commit()
        db.refresh(product)
    except Exception as e:
        db.rollback()
        return {
            "reply_text": f"❌ Error actualizando precio: {e}",
            "actions": [],
            "data": {},
        }

    return {
        "reply_text": (
            f"✅ Precio actualizado: **{product.name}**\n"
            f"  Antes: {_fmt(old_price)} → Ahora: **{_fmt(new_price)}**"
        ),
        "actions": [],
        "data": {
            "product_id": product.id,
            "product_name": product.name,
            "old_price": old_price,
            "new_price": new_price,
        },
    }


# ═════════════════════════════════════════════════════
# 2) AGREGAR STOCK
# ═════════════════════════════════════════════════════

def add_product_stock(db: Session, product_query: str, quantity) -> dict:
    """
    Agrega stock a un producto.
    📏 quantity acepta int, float o Decimal para soportar productos a granel.
    """
    from app.utils.unit_helpers import format_quantity

    if quantity <= 0:
        return {
            "reply_text": "⚠️ La cantidad debe ser mayor a cero.",
            "actions": [],
            "data": {},
        }

    result, count = _find_product_by_query(db, product_query)

    if result is None:
        return {
            "reply_text": f"No encontré el producto **{product_query}**.",
            "actions": [],
            "data": {},
        }

    if isinstance(result, list):
        lines = [f"Encontré **{count}** productos con **{product_query}**. ¿A cuál le agrego stock?"]
        for i, p in enumerate(result, 1):
            unit_type = p.unit_type or "Unid"
            stock_display = format_quantity(float(p.stock or 0), unit_type)
            lines.append(f"  {i}. {p.name} — stock: {stock_display} — código: {p.code or '—'}")
        lines.append("\nSé más específico con el nombre o usá el código.")
        return {
            "reply_text": "\n".join(lines),
            "actions": [],
            "data": {"ambiguous": True},
        }

    product = result
    unit_type = product.unit_type or "Unid"
    old_stock = float(product.stock or 0)

    try:
        from app.db.crud.product_crud import add_stock
        add_stock(db, product.id, quantity, reference="Chat AI", notes="Entrada desde chat inteligente")
        db.refresh(product)
    except Exception as e:
        db.rollback()
        return {
            "reply_text": f"❌ Error agregando stock: {e}",
            "actions": [],
            "data": {},
        }

    new_stock = float(product.stock or 0)
    old_display = format_quantity(old_stock, unit_type)
    new_display = format_quantity(new_stock, unit_type)
    qty_display = format_quantity(float(quantity), unit_type)

    return {
        "reply_text": (
            f"✅ Stock actualizado: **{product.name}**\n"
            f"  Antes: {old_display} → Ahora: **{new_display}** (+{qty_display})"
        ),
        "actions": [],
        "data": {
            "product_id": product.id,
            "product_name": product.name,
            "old_stock": old_stock,
            "new_stock": new_stock,
            "added": float(quantity),
        },
    }


# ═════════════════════════════════════════════════════
# 3) REGISTRAR GASTO
# ═════════════════════════════════════════════════════

def register_expense(db: Session, amount: float, description: str,
                     category: str = "Otros", payment_method: str = "Efectivo",
                     user_id: int | None = None) -> dict:
    """
    Registra un gasto desde el chat.

    `user_id` — opcional, identifica al usuario que ejecutó el comando desde
    el asistente. Si llega `None` el gasto queda sin auditoría (compatibilidad
    hacia atrás con llamadores antiguos).
    """
    if amount <= 0:
        return {
            "reply_text": "⚠️ El monto del gasto debe ser mayor a cero.",
            "actions": [],
            "data": {},
        }

    try:
        from app.services.expense_service import add_expense_service

        expense_data = {
            "category": category,
            "description": description or "Gasto registrado desde chat",
            "amount": amount,
            "payment_method": payment_method,
            "date": today_cr().strftime("%Y-%m-%d"),
        }

        new_expense = add_expense_service(expense_data, db, user_id=user_id)
        db.commit()

        return {
            "reply_text": (
                f"✅ Gasto registrado exitosamente:\n"
                f"  📤 Monto: **{_fmt(amount)}**\n"
                f"  📁 Categoría: {category}\n"
                f"  📝 Descripción: {description or '—'}\n"
                f"  💳 Pago: {payment_method}"
            ),
            "actions": [],
            "data": {
                "expense_id": getattr(new_expense, "id", None),
                "amount": amount,
                "category": category,
            },
        }
    except Exception as e:
        db.rollback()
        return {
            "reply_text": f"❌ Error registrando gasto: {e}",
            "actions": [],
            "data": {},
        }


# ═════════════════════════════════════════════════════
# 4) CREAR CLIENTE
# ═════════════════════════════════════════════════════

def create_customer_quick(db: Session, name: str, phone: str = None,
                          id_number: str = None) -> dict:
    """
    Crea un cliente rápido desde el chat (solo nombre, opcionalmente teléfono y cédula).
    """
    if not name or len(name.strip()) < 2:
        return {
            "reply_text": "⚠️ El nombre del cliente debe tener al menos 2 caracteres.",
            "actions": [],
            "data": {},
        }

    from app.db.models.customer import Customer
    from app.utils.db_compat import escape_like

    # Check duplicado
    existing = (
        db.query(Customer)
        .filter(Customer.name.ilike(escape_like(name.strip())))
        .first()
    )
    if existing:
        return {
            "reply_text": (
                f"⚠️ Ya existe un cliente con nombre **{existing.name}** (ID: {existing.id}).\n"
                f"¿Querés que te lo abra? Decí: *abre clientes*"
            ),
            "actions": [],
            "data": {"existing_id": existing.id},
        }

    try:
        new_customer = Customer(
            name=name.strip(),
            phone=phone,
            id_number=id_number,
            customer_type="Normal",
            is_active=True,
        )
        db.add(new_customer)
        db.commit()
        db.refresh(new_customer)

        parts = [
            f"✅ Cliente creado: **{new_customer.name}** (ID: {new_customer.id})",
        ]
        if phone:
            parts.append(f"  📞 Teléfono: {phone}")
        if id_number:
            parts.append(f"  🆔 Cédula: {id_number}")

        return {
            "reply_text": "\n".join(parts),
            "actions": [],
            "data": {
                "customer_id": new_customer.id,
                "customer_name": new_customer.name,
            },
        }
    except Exception as e:
        db.rollback()
        return {
            "reply_text": f"❌ Error creando cliente: {e}",
            "actions": [],
            "data": {},
        }


# ═════════════════════════════════════════════════════
# 5) ACTUALIZAR COSTO
# ═════════════════════════════════════════════════════

def update_product_cost(db: Session, product_query: str, new_cost: float) -> dict:
    """Actualiza el costo de un producto."""
    if new_cost < 0:
        return {
            "reply_text": "⚠️ El costo no puede ser negativo.",
            "actions": [],
            "data": {},
        }

    result, count = _find_product_by_query(db, product_query)

    if result is None:
        return {
            "reply_text": f"No encontré el producto **{product_query}**.",
            "actions": [],
            "data": {},
        }

    if isinstance(result, list):
        lines = [f"Encontré **{count}** productos. Sé más específico:"]
        for i, p in enumerate(result, 1):
            lines.append(f"  {i}. {p.name} — costo: {_fmt(p.cost)} — código: {p.code or '—'}")
        return {"reply_text": "\n".join(lines), "actions": [], "data": {}}

    product = result
    old_cost = float(product.cost or 0)

    try:
        product.cost = new_cost
        db.commit()
        db.refresh(product)
    except Exception as e:
        db.rollback()
        return {"reply_text": f"❌ Error actualizando costo: {e}", "actions": [], "data": {}}

    return {
        "reply_text": (
            f"✅ Costo actualizado: **{product.name}**\n"
            f"  Antes: {_fmt(old_cost)} → Ahora: **{_fmt(new_cost)}**"
        ),
        "actions": [],
        "data": {"product_id": product.id, "old_cost": old_cost, "new_cost": new_cost},
    }


# ═════════════════════════════════════════════════════
# 6) NAVEGACIÓN COMPLETA
# ═════════════════════════════════════════════════════

# Mapeo exhaustivo keyword → módulo UI
_NAV_MAP: dict[str, dict] = {
    # Dashboard
    "dashboard":        {"module": "dashboard",         "section": "dashboard",         "label": "Dashboard"},
    "panel":            {"module": "dashboard",         "section": "dashboard",         "label": "Dashboard"},
    "tablero":          {"module": "dashboard",         "section": "dashboard",         "label": "Dashboard"},
    "inicio":           {"module": "dashboard",         "section": "dashboard",         "label": "Dashboard"},
    # Ventas
    "ventas":           {"module": "sales",             "section": "ventas",            "label": "Punto de venta"},
    "punto de venta":   {"module": "sales",             "section": "ventas",            "label": "Punto de venta"},
    "pos":              {"module": "sales",             "section": "ventas",            "label": "Punto de venta"},
    "caja registradora":{"module": "sales",             "section": "ventas",            "label": "Punto de venta"},
    # Historial de ventas
    "historial":        {"module": "sales_history",     "section": "registro_ventas",   "label": "Historial de ventas"},
    "registro ventas":  {"module": "sales_history",     "section": "registro_ventas",   "label": "Historial de ventas"},
    "historial ventas": {"module": "sales_history",     "section": "registro_ventas",   "label": "Historial de ventas"},
    # Productos
    "productos":        {"module": "products",          "section": "productos",         "label": "Productos"},
    "inventario":       {"module": "products",          "section": "productos",         "label": "Productos"},
    "artículos":        {"module": "products",          "section": "productos",         "label": "Productos"},
    "articulos":        {"module": "products",          "section": "productos",         "label": "Productos"},
    # Clientes
    "clientes":         {"module": "customers",         "section": "clientes",          "label": "Clientes"},
    # Gastos
    "gastos":           {"module": "expenses",          "section": "gastos",            "label": "Gastos"},
    # Caja
    "caja":             {"module": "cash",              "section": "reporte_diario",    "label": "Caja / Reporte diario"},
    "arqueo":           {"module": "cash",              "section": "reporte_diario",    "label": "Caja"},
    "reporte diario":   {"module": "daily_report",      "section": "reporte_diario",    "label": "Reporte del día"},
    "reporte del dia":  {"module": "daily_report",      "section": "reporte_diario",    "label": "Reporte del día"},
    # Proveedores
    "proveedores":      {"module": "suppliers",         "section": "proveedores",       "label": "Proveedores"},
    # Compras
    "compras":          {"module": "purchases",         "section": "compras/facturas",  "label": "Compras / Facturas"},
    "facturas":         {"module": "purchases",         "section": "compras/facturas",  "label": "Facturas proveedor"},
    # Categorías
    "categorias":       {"module": "categories",        "section": "categorias",        "label": "Categorías"},
    "categorías":       {"module": "categories",        "section": "categorias",        "label": "Categorías"},
    # Financiero
    "financiero":       {"module": "financial_reports",  "section": "financiero",       "label": "Reportes financieros"},
    "reporte financiero":{"module": "financial_reports", "section": "financiero",       "label": "Reportes financieros"},
    "estado resultados": {"module": "financial_reports", "section": "financiero",       "label": "Reportes financieros"},
    # Analytics
    "analytics":        {"module": "analytics",         "section": "analytics",         "label": "Analíticas de ventas"},
    "analiticas":       {"module": "analytics",         "section": "analytics",         "label": "Analíticas de ventas"},
    "analíticas":       {"module": "analytics",         "section": "analytics",         "label": "Analíticas de ventas"},
    "analytics compras":{"module": "purchases_analytics","section": "purchases_analytics","label": "Analíticas de compras"},
    # Configuración
    "configuracion":    {"module": "settings",          "section": "configuración",     "label": "Configuración"},
    "configuración":    {"module": "settings",          "section": "configuración",     "label": "Configuración"},
    "config":           {"module": "settings",          "section": "configuración",     "label": "Configuración"},
    "ajustes":          {"module": "settings",          "section": "configuración",     "label": "Configuración"},
    # Créditos
    "creditos":         {"module": "credits",           "section": "clientes",          "label": "Créditos"},
    "créditos":         {"module": "credits",           "section": "clientes",          "label": "Créditos"},
    # Sin rotación
    "sin rotacion":     {"module": "no_rotation",       "section": "sin_rotacion",      "label": "Productos sin rotación"},
    "sin rotación":     {"module": "no_rotation",       "section": "sin_rotacion",      "label": "Productos sin rotación"},
    # Proformas / Cotizaciones
    "proformas":        {"module": "proformas",         "section": "proformas",         "label": "Proformas"},
    "proforma":         {"module": "proformas",         "section": "proformas",         "label": "Proformas"},
    "cotizaciones":     {"module": "proformas",         "section": "proformas",         "label": "Proformas / Cotizaciones"},
    "cotizacion":       {"module": "proformas",         "section": "proformas",         "label": "Proformas / Cotizaciones"},
    "cotización":       {"module": "proformas",         "section": "proformas",         "label": "Proformas / Cotizaciones"},
}


def resolve_navigation(text: str) -> Optional[dict]:
    """
    Detecta intención de navegación y resuelve el módulo destino.
    Retorna dict con reply_text y actions, o None si no es navegación.
    """
    t = normalize_text(text)

    # Detectar verbo de navegación
    nav_verbs = r"\b(abr[ií]r?|abre|abrime|abr[ií]me|llev[aá]me|ir\s+a|ir\s+al?|muestr[aá]me|enseñ[aá]me|ve\s+a|ve\s+al?|quiero\s+ver|abrí)\b"
    if not re.search(nav_verbs, t):
        return None

    # Buscar el módulo destino en el mapa (fuzzy)
    best_match = None
    best_score = 0.0

    for keyword, nav_info in _NAV_MAP.items():
        kw_norm = normalize_text(keyword)
        # Check directo primero
        if kw_norm in t:
            score = len(kw_norm) / max(len(t), 1) + 0.5
            if score > best_score:
                best_score = score
                best_match = nav_info
        else:
            # Fuzzy check palabra por palabra
            for word in t.split():
                if len(word) >= 4 and keyword_in_text(kw_norm, word, threshold=0.78):
                    score = 0.4
                    if score > best_score:
                        best_score = score
                        best_match = nav_info

    if not best_match:
        return None

    return {
        "reply_text": f"Listo 👌 te abro **{best_match['label']}**.",
        "actions": [{"type": "navigate", "module": best_match["module"], "section": best_match["section"]}],
        "data": {"module": best_match["module"]},
    }


# ═════════════════════════════════════════════════════
# 7) CREAR PROFORMA DESDE CHAT
# ═════════════════════════════════════════════════════

def _find_customer_by_query(db: Session, query: str):
    """Busca un cliente por nombre (ILIKE). Retorna (customer, match_count)."""
    from app.db.models.customer import Customer
    from app.utils.db_compat import escape_like

    q = (query or "").strip()
    if not q:
        return None, 0

    safe_q = escape_like(q)
    rows = (
        db.query(Customer)
        .filter(Customer.name.ilike(f"%{safe_q}%"))
        .filter(Customer.is_active == True)
        .order_by(Customer.name.asc())
        .limit(5)
        .all()
    )
    if not rows:
        return None, 0
    if len(rows) == 1:
        return rows[0], 1
    return rows, len(rows)


def create_proforma_from_chat(
    db: Session,
    product_query: str,
    qty: int,
    customer_query: str | None = None,
    notes: str | None = None,
    validity_days: int = 15,
) -> dict:
    """
    Crea una proforma desde el chat con un producto, cantidad, y cliente opcional.
    Busca producto y cliente por nombre fuzzy, construye el payload y llama al CRUD.
    """
    from app.db.crud.proforma_crud import create_proforma as crud_create
    from app.schemas.proforma import ProformaCreate
    from app.schemas.sale import SaleItemCreate
    from app.db.models.user import User

    # Buscar producto
    product, p_count = _find_product_by_query(db, product_query)

    if product is None:
        return {
            "reply_text": f"No encontré el producto **{product_query}**. Verificá el nombre.",
            "actions": [],
            "data": {},
        }

    if isinstance(product, list):
        lines = [f"Encontré **{p_count}** productos con **{product_query}**. Sé más específico:"]
        for i, p in enumerate(product, 1):
            lines.append(f"  {i}. {p.name} — {_fmt(p.price)} — stock: {p.stock}")
        return {"reply_text": "\n".join(lines), "actions": [], "data": {}}

    if qty <= 0:
        qty = 1

    # Buscar cliente (opcional)
    customer_id = None
    customer_name = "Cliente General"
    if customer_query:
        cust, c_count = _find_customer_by_query(db, customer_query)
        if cust is None:
            return {
                "reply_text": (
                    f"No encontré al cliente **{customer_query}**.\n"
                    f"Podés crearlo con: *crear cliente {customer_query}*"
                ),
                "actions": [],
                "data": {},
            }
        if isinstance(cust, list):
            lines = [f"Encontré **{c_count}** clientes con **{customer_query}**. Sé más específico:"]
            for i, c in enumerate(cust, 1):
                lines.append(f"  {i}. {c.name} — {c.phone or 'sin tel'}")
            return {"reply_text": "\n".join(lines), "actions": [], "data": {}}
        customer_id = cust.id
        customer_name = cust.name

    # Obtener usuario del sistema (primer admin) para el user_id
    system_user = db.query(User).filter(User.role == "admin").first()
    if not system_user:
        system_user = db.query(User).first()
    if not system_user:
        return {
            "reply_text": "❌ No hay usuarios registrados en el sistema.",
            "actions": [],
            "data": {},
        }

    # Construir ProformaCreate
    item = SaleItemCreate(
        product_id=product.id,
        quantity=qty,
        unit_price=float(product.price or 0),
        discount_percent=0,
        is_common=False,
    )

    proforma_data = ProformaCreate(
        customer_id=customer_id,
        details=[item],
        notes=notes,
        validity_days=validity_days,
    )

    try:
        result = crud_create(db, proforma_data, system_user)
        pro = result.get("proforma", {})
        number = pro.get("number", "?")
        total = pro.get("total", 0)

        reply = (
            f"📋 Proforma **{number}** creada:\n"
            f"  {qty}× **{product.name}** — {_fmt(float(product.price or 0))} c/u\n"
            f"  Cliente: **{customer_name}**\n"
            f"  Total: **{_fmt(total)}**\n"
            f"  Vigencia: {validity_days} días"
        )
        if notes:
            reply += f"\n  Notas: {notes}"

        return {
            "reply_text": reply,
            "actions": [{"type": "navigate", "module": "proformas", "section": "proformas"}],
            "data": {"proforma_id": pro.get("id"), "proforma_number": number},
        }

    except Exception as e:
        db.rollback()
        return {
            "reply_text": f"❌ Error creando proforma: {e}",
            "actions": [],
            "data": {},
        }