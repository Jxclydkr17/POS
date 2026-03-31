# app/ai/action_intent.py
"""
FASE 3 — Detector de intención para acciones ampliadas.
Detecta cuándo el usuario quiere ejecutar una ACCIÓN (escritura) y extrae
los parámetros necesarios. Las acciones de carrito (vender, agregar al cart)
siguen en chat_handler.py — aquí solo van las acciones NUEVAS.

Acciones:
  - Actualizar precio de producto
  - Actualizar costo de producto
  - Agregar stock a producto
  - Registrar un gasto
  - Crear un cliente rápido
  - Navegar a cualquier sección
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.fuzzy import normalize_text, fix_typos, any_keyword_in_text
from app.ai import action_commands as cmds


# ─────────────────────────────────────────────────────
# Parsers de entidades para acciones
# ─────────────────────────────────────────────────────

def _extract_amount(text: str) -> Optional[float]:
    """Extrae un monto monetario del texto."""
    # "₡5000" / "5000 colones" / "5,000" / "5000.50"
    m = re.search(r"[₡¢]?\s*([\d,]+(?:\.\d{1,2})?)\s*(?:colones)?", text)
    if m:
        try:
            val = m.group(1).replace(",", "")
            return float(val)
        except ValueError:
            pass
    return None


def _extract_number(text: str) -> Optional[float]:
    """Extrae un número del texto (puede ser precio, cantidad, etc)."""
    m = re.search(r"\b(\d+(?:[.,]\d+)?)\b", text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def _extract_integer(text: str) -> Optional[int]:
    """Extrae un entero del texto."""
    m = re.search(r"\b(\d+)\b", text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _extract_expense_category(text: str) -> str:
    """Detecta categoría de gasto del texto."""
    t = normalize_text(text)
    if any_keyword_in_text(["servicio", "luz", "agua", "internet", "telefono", "electricidad"], t, 0.78):
        return "Servicios"
    if any_keyword_in_text(["sueldo", "salario", "planilla", "pago personal", "nomina"], t, 0.78):
        return "Sueldos"
    if any_keyword_in_text(["mantenimiento", "reparacion", "arreglo"], t, 0.78):
        return "Mantenimiento"
    if any_keyword_in_text(["compra", "proveedor", "mercaderia", "mercancia"], t, 0.78):
        return "Compras / Proveedores"
    if any_keyword_in_text(["caja", "caja chica", "gasto caja"], t, 0.78):
        return "Gastos de caja"
    return "Otros"


def _extract_payment_method_for_expense(text: str) -> str:
    """Método de pago para gastos."""
    t = normalize_text(text)
    if any_keyword_in_text(["sinpe", "transferencia"], t, 0.75):
        return "SINPE"
    if any_keyword_in_text(["tarjeta", "card"], t, 0.75):
        return "Tarjeta"
    return "Efectivo"


# ─────────────────────────────────────────────────────
# Detectores de intención específicos
# ─────────────────────────────────────────────────────

def _try_update_price(text: str, db: Session) -> Optional[dict]:
    """
    Detecta: "poné/cambiá/actualizá el precio de X a Y"
    Variantes: "precio de cemento a 5000", "cambiar precio cemento 5000"
    """
    t = normalize_text(text)

    # Patrón: (verbo) precio de <producto> a <monto>
    patterns = [
        # "ponele precio 5000 al cemento" / "pon precio de cemento a 5000"
        r"(?:pon[eé]?(?:le)?|cambi[aá]r?|actualiz[aá]r?|modific[aá]r?|sub[ií]r?|baj[aá]r?)\s+(?:el\s+)?precio\s+(?:de\s+|del\s+)?(.+?)\s+(?:a|en)\s+[₡¢]?\s*([\d,.]+)",
        # "precio de cemento a 5000"
        r"precio\s+(?:de\s+|del\s+)(.+?)\s+(?:a|en)\s+[₡¢]?\s*([\d,.]+)",
        # "cemento a 5000 colones" (con contexto de precio)
        r"(?:pon[eé]?(?:le)?|cambi[aá]r?|actualiz[aá]r?)\s+(.+?)\s+(?:a|en)\s+[₡¢]?\s*([\d,.]+)\s*(?:colones)?",
    ]

    for pattern in patterns:
        m = re.search(pattern, t)
        if m:
            product_name = m.group(1).strip()
            try:
                price = float(m.group(2).replace(",", ""))
            except ValueError:
                continue
            # Limpiar producto de artículos
            product_name = re.sub(r"^(el|la|los|las|un|una|al)\s+", "", product_name).strip()
            if product_name and price > 0:
                return cmds.update_product_price(db, product_name, price)

    return None


def _try_update_cost(text: str, db: Session) -> Optional[dict]:
    """Detecta: "actualizá el costo de X a Y" """
    t = normalize_text(text)

    patterns = [
        r"(?:pon[eé]?(?:le)?|cambi[aá]r?|actualiz[aá]r?|modific[aá]r?)\s+(?:el\s+)?costo\s+(?:de\s+|del\s+)?(.+?)\s+(?:a|en)\s+[₡¢]?\s*([\d,.]+)",
        r"costo\s+(?:de\s+|del\s+)(.+?)\s+(?:a|en)\s+[₡¢]?\s*([\d,.]+)",
    ]

    for pattern in patterns:
        m = re.search(pattern, t)
        if m:
            product_name = m.group(1).strip()
            product_name = re.sub(r"^(el|la|los|las|un|una|al)\s+", "", product_name).strip()
            try:
                cost = float(m.group(2).replace(",", ""))
            except ValueError:
                continue
            if product_name and cost >= 0:
                return cmds.update_product_cost(db, product_name, cost)

    return None


def _try_add_stock(text: str, db: Session) -> Optional[dict]:
    """
    Detecta: "agregá/metele/sumale N unidades a X" o "agrega stock de X: N"
    """
    t = normalize_text(text)

    patterns = [
        # "agrega 50 unidades de cemento" / "agregar 50 cemento al stock"
        r"(?:agrega|agreg[aá]r?|met[eé](?:le)?|sum[aá](?:le)?|pon[eé]?(?:le)?|ingres[aá]r?|entr[aá]r?)\s+(\d+)\s+(?:unidades?\s+)?(?:de\s+|del?\s+|al?\s+)?(?:stock\s+(?:de\s+)?)?(.+?)(?:\s+al\s+stock|\s+al\s+inventario)?$",
        # "stock de cemento 50" / "stock cemento +50"
        r"stock\s+(?:de\s+|del?\s+)?(.+?)\s+\+?(\d+)$",
        # "cemento +50 stock"
        r"(.+?)\s+\+(\d+)\s+(?:stock|unidades?|uds?)$",
        # "agregar stock de cemento: 50"
        r"(?:agregar|agreg[aá]r?)\s+stock\s+(?:de\s+|del?\s+|a\s+)?(.+?)\s*[:=]\s*(\d+)",
    ]

    for pattern in patterns:
        m = re.search(pattern, t)
        if m:
            groups = m.groups()
            # Determinar cuál grupo es el número y cuál el producto
            if groups[0].isdigit():
                qty = int(groups[0])
                product_name = groups[1].strip()
            else:
                product_name = groups[0].strip()
                qty = int(groups[1])

            product_name = re.sub(r"^(el|la|los|las|un|una|al)\s+", "", product_name).strip()
            # Limpiar "al stock" / "al inventario" del nombre
            product_name = re.sub(r"\s+al\s+(?:stock|inventario)$", "", product_name).strip()

            if product_name and qty > 0:
                return cmds.add_product_stock(db, product_name, qty)

    return None


def _try_register_expense(text: str, db: Session) -> Optional[dict]:
    """
    Detecta: "registra gasto de 5000 en servicios" / "gasté 3000 en luz"
    """
    t = normalize_text(text)

    # Debe tener intención de registrar/agregar un gasto
    if not re.search(r"\b(regist[rá]r?(?:a|á)?|agreg[aá]r?|met[eé]r?|anot[aá]r?|gast[eé]|pagu[eé])\s", t):
        # Caso especial: "gasto de 5000 por servicios"
        if not re.search(r"\bgasto\s+(?:de\s+)?[₡¢]?\d", t):
            return None

    patterns = [
        # "registra gasto de 5000 en servicios por luz" 
        r"(?:gasto|registr\w+|anot\w+|agreg\w+)\s+(?:(?:un\s+)?gasto\s+)?(?:de\s+)?[₡¢]?\s*([\d,.]+)\s+(?:en|por|de)\s+(.+?)$",
        # "gasté 5000 en luz"
        r"(?:gast[eé]|pagu[eé])\s+[₡¢]?\s*([\d,.]+)\s+(?:en|por|de)\s+(.+?)$",
        # "gasto 5000 servicios"
        r"gasto\s+[₡¢]?\s*([\d,.]+)\s+(.+?)$",
        # "registra un gasto: descripcion 5000"
        r"(?:registr\w+|anot\w+)\s+(?:un\s+)?gasto\s*:?\s+(.+?)\s+[₡¢]?\s*([\d,.]+)$",
    ]

    for i, pattern in enumerate(patterns):
        m = re.search(pattern, t)
        if m:
            groups = m.groups()
            if i < 3:
                try:
                    amount = float(groups[0].replace(",", ""))
                except ValueError:
                    continue
                description = groups[1].strip()
            else:
                description = groups[0].strip()
                try:
                    amount = float(groups[1].replace(",", ""))
                except ValueError:
                    continue

            if amount > 0:
                category = _extract_expense_category(description)
                payment = _extract_payment_method_for_expense(text)
                return cmds.register_expense(db, amount, description, category, payment)

    return None


def _try_create_customer(text: str, db: Session) -> Optional[dict]:
    """
    Detecta: "crea cliente Juan Pérez" / "nuevo cliente María tel 88887777"
    """
    t = normalize_text(text)

    # Intención de crear
    if not re.search(r"\b(cre[aá]r?|nuevo|registr[aá]r?|agreg[aá]r?)\s+(?:un\s+)?cliente", t):
        return None

    # Extraer nombre
    m = re.search(
        r"(?:cre[aá]r?|nuevo|registr[aá]r?|agreg[aá]r?)\s+(?:un\s+)?(?:el\s+)?cliente\s+(.+?)$",
        t,
    )
    if not m:
        return None

    rest = m.group(1).strip()

    # Extraer teléfono si viene
    phone = None
    phone_m = re.search(r"(?:tel[eé]?fono|tel|cel)\s*:?\s*(\d{8,})", rest)
    if phone_m:
        phone = phone_m.group(1)
        rest = rest[:phone_m.start()].strip()

    # Extraer cédula si viene
    id_number = None
    id_m = re.search(r"(?:c[eé]dula|id|identificaci[oó]n)\s*:?\s*(\d[\d-]+)", rest)
    if id_m:
        id_number = id_m.group(1)
        rest = rest[:id_m.start()].strip()

    # Limpiar
    name = re.sub(r"\s+(?:con|tel|telefono|cedula|id)\b.*$", "", rest, flags=re.I).strip()
    name = re.sub(r"\s+$", "", name).strip()

    if not name or len(name) < 2:
        return None

    # Capitalizar nombre
    name = " ".join(w.capitalize() for w in name.split())

    return cmds.create_customer_quick(db, name, phone=phone, id_number=id_number)


# ─────────────────────────────────────────────────────
# Función principal
# ─────────────────────────────────────────────────────

def try_action_command(text_raw: str, db: Session) -> Optional[dict]:
    """
    Intenta detectar y ejecutar una acción ampliada.

    Retorna dict con:
      - reply_text: respuesta formateada
      - actions: lista de acciones para UI
      - data: datos adicionales
    O None si no es una acción reconocida.
    """
    # Pre-procesar
    text = fix_typos(text_raw.lower()).strip()

    # ── Orden de prioridad ──

    # 1) Navegación (más común, va primero)
    nav = cmds.resolve_navigation(text_raw)
    if nav:
        return nav

    # 2) Actualizar precio
    result = _try_update_price(text, db)
    if result:
        return result

    # 3) Actualizar costo
    result = _try_update_cost(text, db)
    if result:
        return result

    # 4) Agregar stock
    result = _try_add_stock(text, db)
    if result:
        return result

    # 5) Registrar gasto
    result = _try_register_expense(text, db)
    if result:
        return result

    # 6) Crear cliente
    result = _try_create_customer(text, db)
    if result:
        return result

    # 7) Crear proforma / cotización
    result = _try_create_proforma(text, db)
    if result:
        return result

    return None


# ─────────────────────────────────────────────────────
# 7) Detector de intención: CREAR PROFORMA
# ─────────────────────────────────────────────────────

def _try_create_proforma(text: str, db: Session) -> Optional[dict]:
    """
    Detecta:
      - "cotiza 5 bolsas de cemento para Juan"
      - "hazme una proforma de 10 tubos pvc para María"
      - "proforma para Pedro con 3 láminas de zinc"
      - "cotización de 2 martillos"
    """
    t = normalize_text(text)

    # Debe tener intención de cotizar/proforma
    if not re.search(
        r"\b(cotiz[aá]r?|cotiza|cotizaci[oó]n|proforma|"
        r"haz(?:me)?\s+(?:una?\s+)?(?:proforma|cotizaci[oó]n)|"
        r"crea(?:r?)?\s+(?:una?\s+)?(?:proforma|cotizaci[oó]n)|"
        r"generar?\s+(?:una?\s+)?(?:proforma|cotizaci[oó]n))\b",
        t,
    ):
        return None

    # Patrones para extraer qty + producto + cliente
    patterns = [
        # "cotiza 5 bolsas de cemento para Juan"
        r"(?:cotiz[aá]r?|cotiza|proforma|cotizaci[oó]n)\s+(?:de\s+)?(\d+)\s+(?:de\s+)?(.+?)(?:\s+(?:para|a|al?)\s+(.+?))?$",
        # "proforma para Juan con 5 cemento" / "proforma para Juan de 5 cemento"
        r"(?:proforma|cotizaci[oó]n|cotiz[aá]r?)\s+(?:para|a)\s+(.+?)\s+(?:con|de)\s+(\d+)\s+(?:de\s+)?(.+?)$",
        # "hazme una proforma de 10 tubos pvc"
        r"(?:haz(?:me)?|crea(?:r?)?|generar?)\s+(?:una?\s+)?(?:proforma|cotizaci[oó]n)\s+(?:de\s+)?(\d+)\s+(?:de\s+)?(.+?)(?:\s+(?:para|a)\s+(.+?))?$",
        # "cotiza cemento para Juan" (sin cantidad explícita → qty=1)
        r"(?:cotiz[aá]r?|cotiza)\s+(?:de\s+)?(.+?)(?:\s+(?:para|a|al?)\s+(.+?))?$",
    ]

    for pattern in patterns:
        m = re.search(pattern, t)
        if not m:
            continue

        groups = m.groups()

        # Determinar qty, producto, cliente según el patrón
        qty = 1
        product_name = None
        customer_name = None

        if len(groups) == 3:
            g0, g1, g2 = groups
            if g0 and g0.isdigit():
                # Patrón 1/3: qty, producto, cliente
                qty = int(g0)
                product_name = g1
                customer_name = g2
            elif g1 and g1.isdigit():
                # Patrón 2: cliente, qty, producto
                customer_name = g0
                qty = int(g1)
                product_name = g2
            else:
                # fallback
                product_name = g0
                customer_name = g1
        elif len(groups) == 2:
            # Patrón 4: producto, cliente (sin qty)
            product_name = groups[0]
            customer_name = groups[1]
        else:
            continue

        if not product_name:
            continue

        # Limpiar
        product_name = re.sub(r"^(el|la|los|las|un|una|al|del)\s+", "", (product_name or "").strip()).strip()
        if customer_name:
            customer_name = re.sub(r"^(el|la|los|las|un|una|al|del)\s+", "", customer_name.strip()).strip()
            # Limpiar trailing words
            customer_name = re.sub(r"\s+(?:por\s+favor|pls|please|porfa)$", "", customer_name).strip()

        if not product_name or len(product_name) < 2:
            continue

        qty = max(1, min(999, qty))

        return cmds.create_proforma_from_chat(
            db,
            product_query=product_name,
            qty=qty,
            customer_query=customer_name if customer_name else None,
        )

    return None