# ui/utils/cart_manager.py
"""
FASE 3 — Fix 3.1: Lógica de carrito extraída de sales_view.py.

CartManager es un módulo puro de datos (sin Qt, sin HTTP, sin UI).
Gestiona el estado del carrito de ventas: productos, cantidades,
descuentos, cálculos de impuestos y totales.

DISEÑO:
  - CartManager NO importa nada de PySide6 ni de requests
  - Se puede testear con pytest sin dependencias de UI
  - sales_view.py usa CartManager como su fuente de verdad
    para el estado del carrito, y se encarga de actualizar la UI

USO EN SALES_VIEW:
    from ui.utils.cart_manager import CartManager

    class SalesView(QWidget):
        def __init__(self):
            self.cart_mgr = CartManager()
            ...

        def add_to_cart_from_card(self, product, quantity=1):
            result = self.cart_mgr.add_product(product, quantity)
            if result.ok:
                self.refresh_cart_table()
                show_toast(result.message, ...)
            else:
                show_toast(result.message, success=False, ...)

MIGRACIÓN GRADUAL:
  Cada método de sales_view que manipula self.cart puede migrarse
  uno a uno para usar self.cart_mgr en su lugar. Los métodos que
  leen self.cart para construir la tabla o el payload de la API
  usan cart_mgr.get_items() y cart_mgr.to_sale_payload().
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Resultado de operaciones del carrito
# ═══════════════════════════════════════════════════════════════

@dataclass
class CartResult:
    """Resultado de una operación del carrito."""
    ok: bool
    message: str
    item_key: Optional[str] = None  # key del item afectado


# ═══════════════════════════════════════════════════════════════
# Item del carrito
# ═══════════════════════════════════════════════════════════════

@dataclass
class CartItem:
    """Un producto en el carrito."""
    key: str                    # product_id como str, o "common_N" para comunes
    product_id: Optional[int]   # None para productos comunes
    name: str
    unit_price: Decimal         # precio con IVA incluido
    quantity: Decimal
    tax_rate: Decimal           # porcentaje (ej: 13.00)
    discount_percent: Decimal   # porcentaje de descuento
    unit_type: str              # "Unid", "Kg", "m", etc.
    stock: Decimal              # stock disponible (0 para comunes)
    is_common: bool             # True = producto común (sin inventario)
    common_description: str     # descripción del producto común

    # Campos de imagen/extra para la UI (opcionales)
    image_path: Optional[str] = None
    code: Optional[str] = None
    barcode: Optional[str] = None
    cabys_code: Optional[str] = None

    @property
    def is_unit_based(self) -> bool:
        """True si el producto se vende por unidad (no permite fracciones)."""
        return (self.unit_type or "Unid").lower() in ("unid", "unid.", "und", "und.", "pieza", "pz")

    @property
    def subtotal_net(self) -> Decimal:
        """Subtotal neto (sin IVA, con descuento aplicado)."""
        rate_frac = self.tax_rate / Decimal("100")
        tax_factor = Decimal("1") + rate_frac
        unit_net = self.unit_price / tax_factor if rate_frac > 0 else self.unit_price
        gross = unit_net * self.quantity
        disc = gross * (self.discount_percent / Decimal("100"))
        return (gross - disc).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)

    @property
    def tax_amount(self) -> Decimal:
        """Monto de impuesto."""
        rate_frac = self.tax_rate / Decimal("100")
        if rate_frac <= 0:
            return Decimal("0")
        return (self.subtotal_net * rate_frac).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)

    @property
    def total_line(self) -> Decimal:
        """Total de la línea (subtotal + impuesto)."""
        return self.subtotal_net + self.tax_amount

    def to_dict(self) -> dict:
        """Convierte a dict para construir la tabla de la UI."""
        return {
            "key": self.key,
            "product_id": self.product_id,
            "name": self.name,
            "unit_price": float(self.unit_price),
            "quantity": float(self.quantity),
            "tax_rate": float(self.tax_rate),
            "discount_percent": float(self.discount_percent),
            "unit_type": self.unit_type,
            "stock": float(self.stock),
            "is_common": self.is_common,
            "common_description": self.common_description,
            "subtotal": float(self.total_line),
            "tax_amount": float(self.tax_amount),
            "image_path": self.image_path,
            "code": self.code,
            "barcode": self.barcode,
        }

    def to_api_item(self) -> dict:
        """Convierte al formato que espera POST /sales/ (SaleItemCreate)."""
        item = {
            "quantity": float(self.quantity),
            "unit_price": float(self.unit_price),
            "discount_percent": float(self.discount_percent),
            "tax_rate": float(self.tax_rate),
        }
        if self.is_common:
            item["is_common"] = True
            item["common_description"] = self.common_description
            item["product_id"] = None
        else:
            item["product_id"] = self.product_id
            item["is_common"] = False
        return item


# ═══════════════════════════════════════════════════════════════
# CartManager
# ═══════════════════════════════════════════════════════════════

class CartManager:
    """
    Gestor de carrito de ventas. Puro datos, sin UI ni HTTP.

    El carrito almacena CartItem indexados por key:
      - Para productos normales: key = str(product_id)
      - Para productos comunes: key = "common_N" (N autoincremental)
    """

    def __init__(self):
        self._items: dict[str, CartItem] = {}
        self._common_counter: int = 0

    # ── Propiedades ──────────────────────────────────────

    @property
    def items(self) -> dict[str, CartItem]:
        return self._items

    @property
    def is_empty(self) -> bool:
        return len(self._items) == 0

    @property
    def item_count(self) -> int:
        """Cantidad total de unidades en el carrito."""
        return sum(int(item.quantity) for item in self._items.values())

    @property
    def line_count(self) -> int:
        """Cantidad de líneas (productos distintos) en el carrito."""
        return len(self._items)

    # ── Agregar productos ────────────────────────────────

    def add_product(self, product: dict, quantity: int = 1) -> CartResult:
        """
        Agrega un producto al carrito o incrementa su cantidad.

        Args:
            product: dict con campos del producto (id, name, price, stock, etc.)
            quantity: cantidad a agregar

        Returns:
            CartResult con ok=True si se agregó, ok=False si hay error
        """
        product_id = product.get("id")
        if product_id is None:
            return CartResult(ok=False, message="Producto sin ID.")

        key = str(product_id)
        stock = Decimal(str(product.get("stock", 0)))
        unit_type = product.get("unit_type") or "Unid"
        qty_dec = Decimal(str(quantity))

        # Validar fracción en productos de unidad
        if self._is_unit_type(unit_type) and qty_dec != qty_dec.to_integral_value():
            return CartResult(
                ok=False,
                message=f"'{product.get('name', '')}' se vende por unidad. No se permiten fracciones.",
            )

        if key in self._items:
            # Incrementar
            item = self._items[key]
            new_qty = item.quantity + qty_dec
            if new_qty > stock:
                return CartResult(
                    ok=False,
                    message=f"Stock insuficiente para '{item.name}'. Disponible: {stock}",
                )
            item.quantity = new_qty
            return CartResult(
                ok=True,
                message=f"{item.name} x{int(new_qty)}",
                item_key=key,
            )
        else:
            # Nuevo item
            if qty_dec > stock:
                return CartResult(
                    ok=False,
                    message=f"Stock insuficiente para '{product.get('name', '')}'. Disponible: {stock}",
                )
            tax_rate_raw = product.get("tax_rate", 0)
            tax_rate = self._normalize_tax_rate(tax_rate_raw)

            item = CartItem(
                key=key,
                product_id=product_id,
                name=product.get("name", ""),
                unit_price=Decimal(str(product.get("price", 0))),
                quantity=qty_dec,
                tax_rate=tax_rate,
                discount_percent=Decimal("0"),
                unit_type=unit_type,
                stock=stock,
                is_common=False,
                common_description="",
                image_path=product.get("image_path"),
                code=product.get("code"),
                barcode=product.get("barcode"),
                cabys_code=product.get("cabys_code"),
            )
            self._items[key] = item
            return CartResult(
                ok=True,
                message=f"{item.name} agregado",
                item_key=key,
            )

    def add_common(
        self,
        description: str,
        quantity: int,
        unit_price: float,
        tax_rate: float = 0,
    ) -> CartResult:
        """Agrega un producto común (sin inventario) al carrito."""
        self._common_counter += 1
        key = f"common_{self._common_counter}"

        item = CartItem(
            key=key,
            product_id=None,
            name=f"📦 {description}",
            unit_price=Decimal(str(unit_price)),
            quantity=Decimal(str(quantity)),
            tax_rate=Decimal(str(tax_rate)),
            discount_percent=Decimal("0"),
            unit_type="Unid",
            stock=Decimal("999999"),
            is_common=True,
            common_description=description,
        )
        self._items[key] = item
        return CartResult(ok=True, message=f"Producto común '{description}' agregado", item_key=key)

    # ── Modificar cantidades ─────────────────────────────

    def increment(self, key: str, amount: int = 1) -> CartResult:
        """Incrementa la cantidad de un item."""
        item = self._items.get(key)
        if not item:
            return CartResult(ok=False, message="Item no encontrado en el carrito.")

        new_qty = item.quantity + Decimal(str(amount))
        if not item.is_common and new_qty > item.stock:
            return CartResult(
                ok=False,
                message=f"Stock insuficiente para '{item.name}'. Máximo: {item.stock}",
            )
        item.quantity = new_qty
        return CartResult(ok=True, message=f"{item.name} x{int(new_qty)}", item_key=key)

    def decrement(self, key: str, amount: int = 1) -> CartResult:
        """Decrementa la cantidad. Si llega a 0, elimina el item."""
        item = self._items.get(key)
        if not item:
            return CartResult(ok=False, message="Item no encontrado en el carrito.")

        new_qty = item.quantity - Decimal(str(amount))
        if new_qty <= 0:
            del self._items[key]
            return CartResult(ok=True, message=f"{item.name} eliminado del carrito", item_key=key)

        item.quantity = new_qty
        return CartResult(ok=True, message=f"{item.name} x{int(new_qty)}", item_key=key)

    def set_quantity(self, key: str, quantity: int) -> CartResult:
        """Establece una cantidad exacta para un item."""
        item = self._items.get(key)
        if not item:
            return CartResult(ok=False, message="Item no encontrado.")

        qty_dec = Decimal(str(quantity))
        if qty_dec <= 0:
            del self._items[key]
            return CartResult(ok=True, message=f"{item.name} eliminado", item_key=key)

        if not item.is_common and qty_dec > item.stock:
            return CartResult(ok=False, message=f"Stock máximo: {item.stock}")

        item.quantity = qty_dec
        return CartResult(ok=True, message=f"{item.name} x{int(qty_dec)}", item_key=key)

    def set_discount(self, key: str, discount_percent: float) -> CartResult:
        """Aplica descuento a un item."""
        item = self._items.get(key)
        if not item:
            return CartResult(ok=False, message="Item no encontrado.")

        if discount_percent < 0 or discount_percent > 100:
            return CartResult(ok=False, message="Descuento debe estar entre 0% y 100%.")

        item.discount_percent = Decimal(str(discount_percent))
        return CartResult(
            ok=True,
            message=f"Descuento de {discount_percent}% aplicado a {item.name}",
            item_key=key,
        )

    # ── Eliminar ─────────────────────────────────────────

    def remove(self, key: str) -> CartResult:
        """Elimina un item del carrito."""
        item = self._items.pop(key, None)
        if not item:
            return CartResult(ok=False, message="Item no encontrado.")
        return CartResult(ok=True, message=f"{item.name} eliminado", item_key=key)

    def clear(self) -> CartResult:
        """Vacía el carrito completamente."""
        count = len(self._items)
        self._items.clear()
        return CartResult(ok=True, message=f"Carrito vaciado ({count} items)")

    # ── Búsqueda ─────────────────────────────────────────

    def find_by_name(self, name_query: str) -> Optional[CartItem]:
        """Busca un item por nombre parcial (case-insensitive)."""
        query = name_query.strip().lower()
        for item in self._items.values():
            if query in item.name.lower():
                return item
        return None

    def find_by_product_id(self, product_id: int) -> Optional[CartItem]:
        """Busca un item por product_id."""
        key = str(product_id)
        return self._items.get(key)

    # ── Totales ──────────────────────────────────────────

    def get_totals(self) -> dict:
        """
        Calcula y retorna los totales del carrito.

        Returns:
            {
                "subtotal": float,     # suma neta (sin IVA)
                "tax_total": float,    # suma de impuestos
                "total": float,        # subtotal + tax
                "discount_total": float,  # descuentos totales
                "line_count": int,     # líneas distintas
                "item_count": int,     # unidades totales
            }
        """
        subtotal = Decimal("0")
        tax_total = Decimal("0")

        for item in self._items.values():
            subtotal += item.subtotal_net
            tax_total += item.tax_amount

        total = subtotal + tax_total

        return {
            "subtotal": float(subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "tax_total": float(tax_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total": float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "line_count": self.line_count,
            "item_count": self.item_count,
        }

    # ── Serialización ────────────────────────────────────

    def get_items_list(self) -> list[dict]:
        """Retorna la lista de items como dicts (para la tabla de la UI)."""
        return [item.to_dict() for item in self._items.values()]

    def to_sale_payload(
        self,
        customer_id: Optional[int],
        payment_method: str,
        document_type: str = "04",
        condicion_venta_code: Optional[str] = None,
        credit_days: Optional[int] = None,
    ) -> dict:
        """
        Construye el payload JSON para POST /sales/.

        Returns:
            dict listo para enviar como json=payload
        """
        details = [item.to_api_item() for item in self._items.values()]

        payload = {
            "customer_id": customer_id,
            "payment_method": payment_method,
            "document_type": document_type,
            "details": details,
        }

        if condicion_venta_code:
            payload["condicion_venta_code"] = condicion_venta_code
        if credit_days:
            payload["credit_days"] = credit_days

        return payload

    def snapshot(self) -> dict:
        """
        Crea una copia completa del estado del carrito.
        Útil para pausar/restaurar ventas.
        """
        return {
            "items": {k: copy.deepcopy(v) for k, v in self._items.items()},
            "common_counter": self._common_counter,
        }

    def restore(self, snapshot: dict) -> None:
        """Restaura el carrito desde un snapshot."""
        self._items = snapshot.get("items", {})
        self._common_counter = snapshot.get("common_counter", 0)

    # ── Helpers internos ─────────────────────────────────

    @staticmethod
    def _normalize_tax_rate(raw_rate) -> Decimal:
        """Normaliza tasa de impuesto: 0.13 → 13, 13 → 13."""
        rate = Decimal(str(raw_rate or 0))
        if Decimal("0") < rate < Decimal("1"):
            rate *= Decimal("100")
        return rate

    @staticmethod
    def _is_unit_type(unit_type: str) -> bool:
        """True si el tipo de unidad es por unidad (no acepta fracciones)."""
        return (unit_type or "Unid").lower() in ("unid", "unid.", "und", "und.", "pieza", "pz")