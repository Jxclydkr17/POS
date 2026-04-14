# ui/api.py
"""
FASE 5 — Fix 5.1: API URLs como clase con métodos tipados.

Antes: dict con mezcla de strings y lambdas, sin autocompletado.
Ahora: clase ApiUrls con propiedades y métodos, con backward
       compatibility vía __getitem__ para no romper el código existente.

Uso nuevo (preferido):
    from ui.api import api
    url = api.products                    # string fijo
    url = api.product_by_id(42)          # método con parámetro
    url = api.districts("1", "01")       # método con múltiples parámetros

Uso legacy (sigue funcionando):
    from ui.api import API, BASE_URL
    url = API["products"]                # string fijo
    url = API["product_by_id"](42)       # lambda
"""
import os

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


class ApiUrls:
    """URLs del backend organizadas como propiedades y métodos."""

    def __init__(self, base: str = BASE_URL):
        self._base = base

    # ── Auth ──
    @property
    def login(self) -> str:
        return f"{self._base}/users/login"

    # ── Productos ──
    @property
    def products(self) -> str:
        return f"{self._base}/products"

    def product_by_id(self, product_id: int) -> str:
        return f"{self._base}/products/{product_id}"

    def product_movements(self, product_id: int) -> str:
        return f"{self._base}/products/{product_id}/movements"

    @property
    def reorder_suggestions(self) -> str:
        return f"{self._base}/products/reorder-suggestions"

    # ── Clientes ──
    @property
    def customers(self) -> str:
        return f"{self._base}/customers"

    def customer_by_id(self, customer_id: int) -> str:
        return f"{self._base}/customers/{customer_id}"

    # ── Ventas ──
    @property
    def sales(self) -> str:
        return f"{self._base}/sales"

    def sale_by_id(self, sale_id: int) -> str:
        return f"{self._base}/sales/{sale_id}"

    def delete_sale(self, sale_id: int) -> str:
        return f"{self._base}/sales/{sale_id}"

    # ── Créditos ──
    def credits(self, customer_id: int) -> str:
        return f"{self._base}/credits/{customer_id}"

    def create_credit(self, customer_id: int) -> str:
        return f"{self._base}/credits/{customer_id}/create"

    def add_credit_sale(self, customer_id: int) -> str:
        return f"{self._base}/credits/{customer_id}/add"

    def add_credit_payment(self, credit_id: int) -> str:
        return f"{self._base}/credits/{credit_id}/payments"

    # ── Gastos ──
    @property
    def expenses(self) -> str:
        return f"{self._base}/expenses"

    def delete_expense(self, expense_id: int) -> str:
        return f"{self._base}/expenses/{expense_id}"

    # ── Métodos de pago ──
    @property
    def payment_methods(self) -> str:
        return f"{self._base}/payment-methods"

    # ── Usuarios ──
    @property
    def users(self) -> str:
        return f"{self._base}/users"

    # ── Ubicaciones ──
    @property
    def provinces(self) -> str:
        return f"{self._base}/locations/provinces"

    def cantons(self, province_id: str) -> str:
        return f"{self._base}/locations/provinces/{province_id}/cantons"

    def districts(self, province_id: str, canton_id: str) -> str:
        return f"{self._base}/locations/provinces/{province_id}/cantons/{canton_id}/districts"

    # ── Actividades económicas ──
    def economic_activity_search(self, q: str) -> str:
        return f"{self._base}/economic-activities/search?q={q}"

    # ── Analytics ──
    @property
    def no_rotation(self) -> str:
        return f"{self._base}/analytics/no-rotation"

    @property
    def purchases_spending_by_supplier(self) -> str:
        return f"{self._base}/analytics/purchases/spending-by-supplier"

    @property
    def purchases_monthly_evolution(self) -> str:
        return f"{self._base}/analytics/purchases/monthly-evolution"

    @property
    def purchases_avg_payment_days(self) -> str:
        return f"{self._base}/analytics/purchases/avg-payment-days"

    @property
    def purchases_top_products(self) -> str:
        return f"{self._base}/analytics/purchases/top-products"

    def supplier_comparison(self, product_id: int) -> str:
        return f"{self._base}/analytics/purchases/supplier-comparison?product_id={product_id}"

    @property
    def multi_supplier_products(self) -> str:
        return f"{self._base}/analytics/purchases/multi-supplier-products"

    # ── Backward compatibility ──────────────────────────────
    # Permite seguir usando API["key"] y API["key"](args)
    # sin romper el código existente en dialogs.
    def __getitem__(self, key: str):
        """Acceso tipo dict para backward compatibility."""
        attr = getattr(self, key, None)
        if attr is None:
            raise KeyError(f"API endpoint '{key}' no existe")
        # Si es una property (string), retornarlo directamente
        if isinstance(attr, str):
            return attr
        # Si es un método, retornar el callable
        return attr


# ── Instancia global ──
api = ApiUrls()

# ── Backward compatibility: API dict-like ──
# El código existente usa `from ui.api import API, BASE_URL`
# Esto sigue funcionando sin cambiar nada.
API = api