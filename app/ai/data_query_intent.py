# app/ai/data_query_intent.py
"""
FASE 2 — Detector de intención para consultas de datos.
Ahora usa el clasificador por capas en vez de regex sueltos.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.ai import data_queries as dq
from app.ai.classifier import classify, ClassificationResult
from app.ai.date_parser import extract_period_or_default


# ─────────────────────────────────────────────────────
# Mapeo: (dominio, sub-intención) → función de consulta
# ─────────────────────────────────────────────────────

def _route_data_query(cls: ClassificationResult, db: Session) -> Optional[dict]:
    """
    Dado un ClassificationResult con intent="consultar",
    ejecuta la consulta correcta y retorna el resultado.
    """
    domain = cls.domain
    period = cls.entities.get("period", "today")
    text = cls.entities.get("raw_text", "")

    # ─── VENTAS ───
    if domain == "ventas":
        # Sub-detección: ¿top productos o resumen de ventas?
        if _mentions_top_products(text):
            return dq.query_top_products_sold(db, period=period)
        return dq.query_sales_summary(db, period=period)

    # ─── GASTOS ───
    if domain == "gastos":
        return dq.query_expenses_summary(db, period=period)

    # ─── CAJA ───
    if domain == "caja":
        return dq.query_cash_status(db)

    # ─── INVENTARIO / PRODUCTOS ───
    if domain in ("inventario", "productos"):
        # Sub-detección: ¿busca proveedores de un producto?
        product_query = cls.entities.get("product_query")
        if product_query or _mentions_product_suppliers(text):
            pq = product_query or _extract_product_term_fallback(text)
            if pq:
                return dq.query_product_suppliers(db, product_query=pq)
        if _mentions_low_stock(text):
            return dq.query_low_stock_products(db)
        return dq.query_inventory_summary(db)

    # ─── CLIENTES ───
    if domain == "clientes":
        if _mentions_top_customers(text):
            return dq.query_top_customers_by_sales(db, period=period)
        return dq.query_customers_summary(db)

    # ─── CRÉDITO / DEUDAS ───
    if domain == "credito":
        return dq.query_top_debtors(db)

    # ─── COMPRAS / PROVEEDORES ───
    if domain == "compras":
        # Sub-detección: ¿busca proveedores de un producto específico?
        product_query = cls.entities.get("product_query")
        if product_query or _mentions_product_suppliers(text):
            pq = product_query or _extract_product_term_fallback(text)
            if pq:
                return dq.query_product_suppliers(db, product_query=pq)
        if _mentions_supplier_debt(text):
            return dq.query_supplier_debt(db)
        return dq.query_purchases_summary(db, period=period)

    # ─── FINANCIERO ───
    if domain == "financiero":
        return dq.query_profit_summary(db, period=period)

    return None


# ─────────────────────────────────────────────────────
# Sub-detecciones (ligeras, dentro de un dominio)
# ─────────────────────────────────────────────────────

def _mentions_top_products(text: str) -> bool:
    """¿Pregunta por productos más vendidos?"""
    import re
    return bool(re.search(
        r"(mas\s+vendid|top\s+producto|que\s+se\s+vende\s+mas|lo\s+que\s+mas\s+se\s+vende)",
        text,
    ))


def _mentions_low_stock(text: str) -> bool:
    """¿Pregunta por stock bajo/agotados?"""
    import re
    return bool(re.search(
        r"(sin\s+stock|stock\s+bajo|stock\s+critico|agotad|critico|bajo\s+stock|por\s+agotarse)",
        text,
    ))


def _mentions_top_customers(text: str) -> bool:
    """¿Pregunta por mejores clientes?"""
    import re
    return bool(re.search(
        r"(mejor|top\s+cliente|mas\s+compra|mas\s+frecuente|mas\s+importante|quien\s+compra\s+mas)",
        text,
    ))


def _mentions_supplier_debt(text: str) -> bool:
    """¿Pregunta por deuda con proveedores?"""
    import re
    return bool(re.search(
        r"(deuda\s+(?:con|de)\s+proveedor|debo\s+a\s+proveedor|a\s+quien\s+debo|proveedor.*(?:deuda|saldo|pendiente))",
        text,
    ))


def _mentions_product_suppliers(text: str) -> bool:
    """¿Pregunta quién vende / proveedores de un producto?"""
    import re
    return bool(re.search(
        r"("
        r"quien\s+(?:me\s+)?vende"
        r"|a\s+quien\s+le\s+compro"
        r"|donde\s+(?:puedo\s+)?compr[oa]"
        r"|proveedore?s?\s+(?:de|del|para|que\s+vend)"
        r"|quien\s+(?:me\s+)?(?:tiene|ofrece|maneja|distribuye|trae)"
        r"|que\s+proveedor(?:es)?\s+(?:tiene|vende|ofrece|maneja)"
        r"|a\s+quien\s+(?:le\s+)?(?:puedo\s+)?(?:comprar|pedir|encargar)"
        r"|comparar?\s+precios?\s+.*proveedor"
        r"|precios?\s+(?:por|de|del|para)\s+.*proveedor"
        r")",
        text,
    ))


def _extract_product_term_fallback(text: str) -> Optional[str]:
    """
    Fallback: extrae el término de producto del texto crudo
    cuando el clasificador no lo capturó en entities['product_query'].
    """
    import re
    patterns = [
        r"proveedore?s?\s+(?:de|del|para)\s+(.+?)$",
        r"quien\s+(?:me\s+)?vende\s+(.+?)$",
        r"quien\s+(?:me\s+)?(?:tiene|ofrece|maneja|distribuye|trae)\s+(.+?)$",
        r"a\s+quien\s+le\s+(?:puedo\s+)?(?:compro|comprar?|pedir|encargar)\s+(.+?)$",
        r"donde\s+(?:puedo\s+)?compr[oa]r?\s+(.+?)$",
        r"que\s+proveedor(?:es)?\s+(?:tienen?|venden?|ofrecen?|manejan?)\s+(.+?)$",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            term = m.group(1).strip()
            term = re.sub(r"^(el|la|los|las|un|una)\s+", "", term, flags=re.I)
            term = re.sub(r"[\?\!\.\,;]+$", "", term).strip()
            return term or None
    return None


# ─────────────────────────────────────────────────────
# Detección de "resumen del día" / overview
# ─────────────────────────────────────────────────────

def _is_daily_overview(text: str) -> bool:
    """¿Pide un resumen general del día / negocio?"""
    import re
    return bool(re.search(
        r"("
        r"resumen\s+del\s+dia"
        r"|como\s+(?:va|esta|estuvo|anda)\s+(?:el\s+)?(?:dia|negocio|todo)"
        r"|como\s+(?:vamos|andamos|estamos)"
        r"|dame\s+(?:un\s+)?resumen"
        r"|que\s+tal\s+(?:va|todo|el\s+dia)"
        r"|overview"
        r"|panorama"
        r"|situacion\s+actual"
        r")",
        text,
    ))


def _is_period_overview(text: str) -> bool:
    """¿Pide un resumen general con periodo? (mes, semana, año, etc.)"""
    import re
    return bool(re.search(
        r"("
        r"resumen\s+(del?\s*)?(mes|semana|la\s*semana|este\s*mes|esta\s*semana|año|este\s*año|ayer|la\s*semana\s*pasada|el\s*mes\s*pasado|mensual|semanal)"
        r"|reporte\s+(del?\s*)?(mes|semana|la\s*semana|este\s*mes|esta\s*semana)"
        r"|como\s+(va|fue|estuvo|anduvo)\s+(el\s*)?(mes|la\s*semana)"
        r")",
        text,
    ))


# ─────────────────────────────────────────────────────
# Función principal
# ─────────────────────────────────────────────────────

def try_data_query(text_raw: str, db: Session) -> Optional[dict]:
    """
    Intenta detectar y ejecutar una consulta de datos.

    Retorna dict con:
      - reply_text: respuesta formateada
      - data: datos crudos
    O None si no es una consulta de datos.
    """
    cls = classify(text_raw)

    raw = cls.entities.get("raw_text", "")
    period = cls.entities.get("period", "today")

    # ── Resumen con periodo específico (mes, semana, etc.) ──
    if _is_period_overview(raw):
        return dq.query_period_overview(db, period=period)

    # ── Resumen diario: caso especial (multi-dominio) ──
    if _is_daily_overview(raw):
        return dq.query_daily_overview(db)

    # ── Solo procesar si el clasificador dice "consultar" ──
    if not cls.is_data_query:
        return None

    # ── Excluir si quiere navegar explícitamente ──
    if cls.is_navigation:
        return None

    # ── Routing por dominio ──
    return _route_data_query(cls, db)