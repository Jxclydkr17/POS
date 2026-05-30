# app/ai/ui_context.py
"""
FASE 5 — Modelo de contexto UI.
Define la información contextual que el frontend envía al chat
para que el asistente sepa dónde está el usuario y qué tiene activo.
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class CartItem(BaseModel):
    """Un ítem del carrito real del POS."""
    product_id: int
    product_name: str = ""
    quantity: int = 1
    unit_price: float = 0.0
    discount_percent: float = 0.0
    subtotal: float = 0.0


class UIContext(BaseModel):
    """
    Contexto completo del estado de la UI.
    Se envía con cada mensaje para que el backend sepa:
    - En qué pantalla está el usuario
    - Qué tiene en el carrito
    - Qué cliente/pago está seleccionado
    """

    # ── Pantalla actual ──
    current_screen: str = ""
    # Valores: dashboard, ventas, productos, clientes, gastos,
    #          proveedores, compras/facturas, configuración, etc.

    # ── Carrito real (del POS) ──
    cart_items: List[CartItem] = Field(default_factory=list)
    cart_total: float = 0.0
    cart_count: int = 0

    # ── Selecciones activas en POS ──
    selected_customer_name: Optional[str] = None
    selected_customer_id: Optional[int] = None
    selected_payment_method: Optional[str] = None

    # ── Caja ──
    cash_session_open: Optional[bool] = None

    def has_cart(self) -> bool:
        return self.cart_count > 0

    def cart_summary_text(self) -> str:
        """Resumen legible del carrito."""
        if not self.cart_items:
            return "Carrito vacío"
        lines = []
        for item in self.cart_items:
            lines.append(f"{item.quantity}× {item.product_name} (₡{item.unit_price:,.0f})")
        total = f"₡{self.cart_total:,.2f}" if self.cart_total else ""
        parts = [f"{self.cart_count} productos"]
        if total:
            parts.append(f"total {total}")
        if self.selected_customer_name:
            parts.append(f"cliente: {self.selected_customer_name}")
        if self.selected_payment_method:
            parts.append(f"pago: {self.selected_payment_method}")
        return " | ".join(parts)

    def screen_label(self) -> str:
        """Nombre legible de la pantalla actual."""
        _labels = {
            "dashboard": "Dashboard",
            "ventas": "Punto de venta",
            "productos": "Productos",
            "clientes": "Clientes",
            "gastos": "Gastos",
            "proveedores": "Proveedores",
            "compras/facturas": "Compras",
            "configuración": "Configuración",
            "registro_ventas": "Historial de ventas",
            "reporte_diario": "Reporte diario",
            "financiero": "Reportes financieros",
            "analytics": "Analíticas",
            "categorias": "Categorías",
        }
        return _labels.get(self.current_screen, self.current_screen or "—")


def build_context_prompt(ctx: UIContext) -> str:
    """
    Construye un prompt de contexto para inyectar en el sistema de chat.
    Solo incluye info relevante (no vacía).
    """
    parts = []

    # Pantalla
    if ctx.current_screen:
        parts.append(f"[Pantalla: {ctx.screen_label()}]")

    # Carrito
    if ctx.has_cart():
        parts.append(f"[Carrito: {ctx.cart_summary_text()}]")
    elif ctx.current_screen == "ventas":
        parts.append("[Carrito: vacío]")

    # Caja
    if ctx.cash_session_open is not None:
        estado = "abierta" if ctx.cash_session_open else "cerrada"
        parts.append(f"[Caja: {estado}]")

    if not parts:
        return ""

    return " ".join(parts)


def generate_contextual_suggestions(ctx: UIContext) -> list[str]:
    """
    Genera sugerencias inteligentes basadas en el contexto actual.
    """
    screen = ctx.current_screen or ""
    suggestions = []

    if screen == "ventas":
        if ctx.has_cart():
            suggestions.append("Confirmar venta")
            if not ctx.selected_customer_name:
                suggestions.append("Cliente Randall")
            if not ctx.selected_payment_method:
                suggestions.append("Pagar con sinpe")
            suggestions.append("¿Cuánto vendí hoy?")
        else:
            suggestions.append("Busca cemento")
            suggestions.append("Ventas hoy")

    elif screen == "dashboard":
        suggestions = ["Resumen del día", "¿Quién me debe?", "Stock bajo", "Ganancia del mes"]

    elif screen == "productos":
        suggestions = ["¿Cuántos sin stock?", "Resumen inventario", "Top productos vendidos"]

    elif screen == "clientes":
        suggestions = ["¿Quién me debe?", "Mejores clientes", "Crear cliente nuevo"]

    elif screen == "gastos":
        suggestions = ["Gastos de hoy", "Gastos del mes", "Ganancia del mes"]

    elif screen in ("proveedores", "compras/facturas"):
        suggestions = ["Compras del mes", "Deuda con proveedores", "Facturas pendientes"]

    elif screen == "reporte_diario":
        suggestions = ["Ventas hoy", "Gastos hoy", "¿Cómo está la caja?"]

    elif screen == "financiero":
        suggestions = ["Ganancia del mes", "Ventas vs gastos", "Ganancia de hoy"]

    elif screen == "analytics":
        suggestions = ["Top productos vendidos", "Ventas del mes", "Ventas de la semana"]

    else:
        suggestions = ["Ventas hoy", "Resumen del día", "¿Cómo está la caja?", "¿Quién me debe?"]

    return suggestions[:4]