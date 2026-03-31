# tests/test_sales.py
"""
FASE 4.2 — Tests del módulo de ventas.
Cubre: venta exitosa, sin caja, crédito, stock insuficiente,
producto desactivado, anulación con reversión.
"""
import pytest
from datetime import date
from app.db.models.product import Product
from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.cash_session import CashSession


# ─── Fixtures de datos de prueba ───────────────────────────────


@pytest.fixture
def seed_category(db_session):
    """Crea una categoría de prueba."""
    cat = db_session.query(Category).filter(Category.name == "Test Cat").first()
    if not cat:
        cat = Category(name="Test Cat", is_active=True)
        db_session.add(cat)
        db_session.commit()
        db_session.refresh(cat)
    return cat


@pytest.fixture
def seed_product(db_session, seed_category):
    """Crea un producto activo con stock=50 y precio=1000."""
    prod = db_session.query(Product).filter(Product.code == "TEST-001").first()
    if prod:
        prod.stock = 50
        prod.price = 1000.0
        prod.is_active = True
        db_session.commit()
        db_session.refresh(prod)
        return prod

    prod = Product(
        code="TEST-001",
        name="Producto Test",
        price=1000.0,
        cost=500.0,
        stock=50,
        min_stock=5,
        is_active=True,
        category_id=seed_category.id,
        tax_rate=13.0,
        tax_type="IVA",
    )
    db_session.add(prod)
    db_session.commit()
    db_session.refresh(prod)
    return prod


@pytest.fixture
def seed_inactive_product(db_session, seed_category):
    """Crea un producto desactivado."""
    prod = db_session.query(Product).filter(Product.code == "TEST-INACTIVE").first()
    if prod:
        prod.is_active = False
        db_session.commit()
        db_session.refresh(prod)
        return prod

    prod = Product(
        code="TEST-INACTIVE",
        name="Producto Inactivo",
        price=500.0,
        cost=200.0,
        stock=10,
        is_active=False,
        category_id=seed_category.id,
    )
    db_session.add(prod)
    db_session.commit()
    db_session.refresh(prod)
    return prod


@pytest.fixture
def seed_customer(db_session):
    """Crea un cliente con crédito habilitado."""
    cust = db_session.query(Customer).filter(Customer.name == "Cliente Test").first()
    if not cust:
        cust = Customer(
            name="Cliente Test",
            id_type="01",
            id_number="123456789",
            email="test@test.com",
            phone="88887777",
            credit_balance=0.0,
            credit_limit=500000.0,
            has_credit_limit=True,
        )
        db_session.add(cust)
        db_session.commit()
        db_session.refresh(cust)
    return cust


@pytest.fixture
def open_cash_session(db_session):
    """Abre una sesión de caja para hoy."""
    # Cerrar cualquier sesión abierta previa
    existing = (
        db_session.query(CashSession)
        .filter(CashSession.status == "open", CashSession.date == date.today())
        .first()
    )
    if existing:
        return existing

    cs = CashSession(
        date=date.today(),
        status="open",
        opening_amount=0.0,
    )
    db_session.add(cs)
    db_session.commit()
    db_session.refresh(cs)
    return cs


@pytest.fixture
def closed_cash_session(db_session):
    """Asegura que NO haya caja abierta hoy."""
    sessions = (
        db_session.query(CashSession)
        .filter(CashSession.status == "open", CashSession.date == date.today())
        .all()
    )
    for s in sessions:
        s.status = "closed"
    db_session.commit()


def _sale_payload(product_id: int, quantity: int = 2, **overrides):
    """Helper para generar un payload de venta válido."""
    payload = {
        "payment_method": "Efectivo",
        "document_type": "04",
        "details": [
            {
                "product_id": product_id,
                "quantity": quantity,
                "unit_price": 1000.0,
                "discount_percent": 0,
            }
        ],
    }
    payload.update(overrides)
    return payload


# ═══════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════


class TestCreateSale:
    """Tests para POST /sales/"""

    def test_create_sale_success(self, test_client, auth_headers, seed_product, open_cash_session):
        """Venta exitosa con stock suficiente."""
        payload = _sale_payload(seed_product.id, quantity=2)
        resp = test_client.post("/sales/", json=payload, headers=auth_headers)

        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["message"] == "Venta registrada correctamente."
        assert data["sale"]["id"] > 0
        assert data["sale"]["total"] > 0
        assert data["sale"]["user_id"] is not None   # FASE 3.2: vendedor registrado

    def test_create_sale_no_cash_session(self, test_client, auth_headers, seed_product, closed_cash_session):
        """Falla si no hay caja abierta."""
        payload = _sale_payload(seed_product.id)
        resp = test_client.post("/sales/", json=payload, headers=auth_headers)

        assert resp.status_code == 400
        assert "caja" in resp.json()["detail"].lower()

    def test_create_sale_insufficient_stock(self, test_client, auth_headers, seed_product, open_cash_session):
        """Falla si el stock es insuficiente."""
        payload = _sale_payload(seed_product.id, quantity=99999)
        resp = test_client.post("/sales/", json=payload, headers=auth_headers)

        assert resp.status_code == 400
        assert "stock" in resp.json()["detail"].lower()

    def test_create_sale_inactive_product(self, test_client, auth_headers, seed_inactive_product, open_cash_session):
        """Falla si el producto está desactivado."""
        payload = _sale_payload(seed_inactive_product.id, quantity=1)
        payload["details"][0]["unit_price"] = 500.0
        resp = test_client.post("/sales/", json=payload, headers=auth_headers)

        assert resp.status_code == 400
        assert "desactivado" in resp.json()["detail"].lower()

    def test_create_sale_empty_details(self, test_client, auth_headers, open_cash_session):
        """Falla si no hay productos en el carrito."""
        payload = {"payment_method": "Efectivo", "details": []}
        resp = test_client.post("/sales/", json=payload, headers=auth_headers)

        assert resp.status_code == 400

    def test_create_sale_invalid_payment_method(self, test_client, auth_headers, seed_product, open_cash_session):
        """Falla con método de pago inválido (validación schema)."""
        payload = _sale_payload(seed_product.id, payment_method="Bitcoin")
        resp = test_client.post("/sales/", json=payload, headers=auth_headers)

        assert resp.status_code == 422  # Pydantic validation error

    def test_create_credit_sale(self, test_client, auth_headers, seed_product, seed_customer, open_cash_session):
        """Venta a crédito exitosa con cliente válido."""
        payload = _sale_payload(
            seed_product.id, quantity=1,
            customer_id=seed_customer.id,
            payment_method="Crédito",
            credit_days=30,
        )
        resp = test_client.post("/sales/", json=payload, headers=auth_headers)

        assert resp.status_code == 200, resp.json()
        assert resp.json()["sale"]["payment_method"] == "Crédito"

    def test_create_credit_sale_no_customer(self, test_client, auth_headers, seed_product, open_cash_session):
        """Falla crédito sin cliente."""
        payload = _sale_payload(
            seed_product.id, quantity=1,
            payment_method="Crédito",
            credit_days=30,
        )
        resp = test_client.post("/sales/", json=payload, headers=auth_headers)

        assert resp.status_code == 400
        assert "crédito" in resp.json()["detail"].lower() or "cliente" in resp.json()["detail"].lower()


class TestVoidSale:
    """Tests para DELETE /sales/{id} (anulación)."""

    def test_void_sale_restores_stock(self, test_client, auth_headers, seed_product, open_cash_session, db_session):
        """Anular una venta restaura el stock."""
        # Registrar stock inicial
        initial_stock = seed_product.stock

        # Crear venta
        payload = _sale_payload(seed_product.id, quantity=3)
        create_resp = test_client.post("/sales/", json=payload, headers=auth_headers)
        assert create_resp.status_code == 200, create_resp.json()
        sale_id = create_resp.json()["sale"]["id"]

        # Verificar stock decrementado
        db_session.refresh(seed_product)
        assert seed_product.stock == initial_stock - 3

        # Anular
        void_resp = test_client.delete(f"/sales/{sale_id}", headers=auth_headers)
        assert void_resp.status_code == 200, void_resp.json()
        assert void_resp.json()["status"] == "ANULADA"

        # Verificar stock restaurado
        db_session.refresh(seed_product)
        assert seed_product.stock == initial_stock

    def test_void_nonexistent_sale(self, test_client, auth_headers):
        """Falla al anular venta inexistente."""
        resp = test_client.delete("/sales/999999", headers=auth_headers)
        assert resp.status_code == 404

    def test_void_already_voided(self, test_client, auth_headers, seed_product, open_cash_session):
        """Falla al anular una venta ya anulada."""
        payload = _sale_payload(seed_product.id, quantity=1)
        create_resp = test_client.post("/sales/", json=payload, headers=auth_headers)
        sale_id = create_resp.json()["sale"]["id"]

        # Primera anulación OK
        test_client.delete(f"/sales/{sale_id}", headers=auth_headers)

        # Segunda anulación falla
        resp = test_client.delete(f"/sales/{sale_id}", headers=auth_headers)
        assert resp.status_code == 400
        assert "anulada" in resp.json()["detail"].lower()


class TestListSales:
    """Tests para GET endpoints."""

    def test_list_sales_paginated(self, test_client, auth_headers):
        """GET /sales/ devuelve estructura paginada."""
        resp = test_client.get("/sales/?page=1&page_size=10", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "total_count" in data
        assert "page" in data
        assert "total_pages" in data

    def test_list_sales_today(self, test_client, auth_headers):
        """GET /sales/today devuelve lista."""
        resp = test_client.get("/sales/today", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert isinstance(data["data"], list)

    def test_get_sale_detail(self, test_client, auth_headers, seed_product, open_cash_session):
        """GET /sales/{id} devuelve detalle completo."""
        payload = _sale_payload(seed_product.id, quantity=1)
        create_resp = test_client.post("/sales/", json=payload, headers=auth_headers)
        sale_id = create_resp.json()["sale"]["id"]

        resp = test_client.get(f"/sales/{sale_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == sale_id
        assert "details" in data
        assert len(data["details"]) > 0
        assert "user_id" in data