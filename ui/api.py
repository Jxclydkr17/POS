# pos/ui/api.py
import os

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

API = {
    "login": f"{BASE_URL}/users/login",
    "products": f"{BASE_URL}/products",
    "product_by_id": lambda product_id: f"{BASE_URL}/products/{product_id}",
    "customers": f"{BASE_URL}/customers",
    "customer_by_id": lambda customer_id: f"{BASE_URL}/customers/{customer_id}",
    "sales": f"{BASE_URL}/sales",
    "sale_by_id": lambda sale_id: f"{BASE_URL}/sales/{sale_id}",
    "delete_sale": lambda sale_id: f"{BASE_URL}/sales/{sale_id}",
    "credits": lambda customer_id: f"{BASE_URL}/credits/{customer_id}",
    "create_credit": lambda customer_id: f"{BASE_URL}/credits/{customer_id}/create",
    "add_credit_sale": lambda customer_id: f"{BASE_URL}/credits/{customer_id}/add",
    "add_credit_payment": lambda credit_id: f"{BASE_URL}/credits/{credit_id}/payments",
    "expenses": f"{BASE_URL}/expenses",
    "delete_expense": lambda expense_id: f"{BASE_URL}/expenses/{expense_id}",
    "payment_methods": f"{BASE_URL}/payment-methods",
    "users": f"{BASE_URL}/users",
    "provinces": f"{BASE_URL}/locations/provinces",
    "cantons": lambda province_id: f"{BASE_URL}/locations/provinces/{province_id}/cantons",
    "districts": lambda province_id, canton_id: f"{BASE_URL}/locations/provinces/{province_id}/cantons/{canton_id}/districts",
    "economic_activity_search": lambda q: f"{BASE_URL}/economic-activities/search?q={q}",
    "product_movements": lambda product_id: f"{BASE_URL}/products/{product_id}/movements",
    "reorder_suggestions": f"{BASE_URL}/products/reorder-suggestions",
    # 🕳️ Productos sin rotación
    "no_rotation": f"{BASE_URL}/analytics/no-rotation",

    # ── Fase 4: Analytics de compras ──
    "purchases_spending_by_supplier": f"{BASE_URL}/analytics/purchases/spending-by-supplier",
    "purchases_monthly_evolution": f"{BASE_URL}/analytics/purchases/monthly-evolution",
    "purchases_avg_payment_days": f"{BASE_URL}/analytics/purchases/avg-payment-days",
    "purchases_top_products": f"{BASE_URL}/analytics/purchases/top-products",

    # ── Fase 4: Comparador de proveedores ──
    "supplier_comparison": lambda product_id: f"{BASE_URL}/analytics/purchases/supplier-comparison?product_id={product_id}",
    "multi_supplier_products": f"{BASE_URL}/analytics/purchases/multi-supplier-products",
}
