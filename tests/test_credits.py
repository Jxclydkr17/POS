# tests/test_credits.py
"""
Tests del flujo de credito (fiado) validando el contrato REAL de /credits:
  - Registrar credito sobre una venta existente: POST /credits/{id}/add
  - Rechazo de payload invalido (sin sale_id) en /add
  - Venta a credito que genera deuda + consulta de resumen
  - Abono que reduce el saldo: POST /credits/{id}/payments

Requiere que la BD de prueba siembre el "Cliente General" (id=1), para que
los clientes reales obtengan id >= 2 y puedan operar a credito (el backend
niega credito a customer_id == 1). Eso lo garantiza tests/conftest.py.
"""
import pytest
from datetime import date

from app.db.models.category import Category
from app.db.models.product import Product
from app.db.models.customer import Customer
from app.db.models.cash_session import CashSession


# --- Fixtures -------------------------------------------------------------

@pytest.fixture
def cred_product(db_session):
    cat = Category(name="Cred Cat", is_active=True)
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)

    prod = Product(
        code="CRED-001", name="Producto Credito",
        price=1000.0, cost=500.0, stock=100, min_stock=1,
        is_active=True, category_id=cat.id, tax_rate=13.0, tax_type="IVA",
    )
    db_session.add(prod)
    db_session.commit()
    db_session.refresh(prod)
    return prod


@pytest.fixture
def cred_customer(db_session):
    """Cliente real con credito habilitado (id >= 2; id=1 = Cliente General)."""
    cust = Customer(
        name="Cliente Credito Test",
        id_type="01", id_number="900112233", phone="70001122",
        credit_limit=1_000_000.0, has_credit_limit=True, credit_balance=0.0,
        is_active=True,
    )
    db_session.add(cust)
    db_session.commit()
    db_session.refresh(cust)
    return cust


@pytest.fixture
def open_cash(db_session):
    cs = CashSession(date=date.today(), status="open", opening_amount=0.0)
    db_session.add(cs)
    db_session.commit()
    db_session.refresh(cs)
    return cs


def _sale_payload(product_id, **overrides):
    payload = {
        "payment_method": "Efectivo",
        "document_type": "04",
        "details": [
            {"product_id": product_id, "quantity": 1, "unit_price": 1000.0, "discount_percent": 0}
        ],
    }
    payload.update(overrides)
    return payload


# --- /credits/{id}/add : registrar credito sobre venta existente ----------

def test_register_credit_on_existing_sale(
    test_client, auth_headers, cred_product, cred_customer, open_cash
):
    """Una venta de contado puede registrarse como credito via /credits/{id}/add."""
    sale = test_client.post("/sales/", json=_sale_payload(cred_product.id), headers=auth_headers)
    assert sale.status_code == 200, sale.json()
    sale_id = sale.json()["sale"]["id"]

    resp = test_client.post(
        f"/credits/{cred_customer.id}/add",
        json={"sale_id": sale_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["success"] is True
    assert "credit_id" in body["data"]


def test_add_credit_requires_sale_id(test_client, auth_headers, cred_customer):
    """El endpoint /add exige sale_id; un payload sin el se rechaza (422)."""
    resp = test_client.post(
        f"/credits/{cred_customer.id}/add",
        json={"amount": 100.0},  # falta sale_id
        headers=auth_headers,
    )
    assert resp.status_code == 422


# --- Venta a credito + abono ----------------------------------------------

def test_credit_sale_creates_debt(
    test_client, auth_headers, cred_product, cred_customer, open_cash
):
    """Una venta a credito genera deuda visible en el resumen del cliente."""
    sale = test_client.post(
        "/sales/",
        json=_sale_payload(
            cred_product.id, customer_id=cred_customer.id,
            payment_method="Crédito", credit_days=30,
        ),
        headers=auth_headers,
    )
    assert sale.status_code == 200, sale.json()

    summary = test_client.get(f"/credits/{cred_customer.id}", headers=auth_headers)
    assert summary.status_code == 200, summary.json()
    assert summary.json()["data"]["balance"] > 0


def test_payment_reduces_balance(
    test_client, auth_headers, cred_product, cred_customer, open_cash
):
    """Un abono reduce el saldo de la deuda del cliente."""
    sale = test_client.post(
        "/sales/",
        json=_sale_payload(
            cred_product.id, customer_id=cred_customer.id,
            payment_method="Crédito", credit_days=30,
        ),
        headers=auth_headers,
    )
    assert sale.status_code == 200, sale.json()

    balance_before = test_client.get(
        f"/credits/{cred_customer.id}", headers=auth_headers
    ).json()["data"]["balance"]
    assert balance_before > 0

    pay = test_client.post(
        f"/credits/{cred_customer.id}/payments",
        json={"amount": 500.0, "payment_method": "Efectivo"},
        headers=auth_headers,
    )
    assert pay.status_code == 200, pay.json()
    assert pay.json()["success"] is True

    balance_after = test_client.get(
        f"/credits/{cred_customer.id}", headers=auth_headers
    ).json()["data"]["balance"]
    assert balance_after == pytest.approx(balance_before - 500.0, abs=0.01)

# --- FASE 1.5: el Cliente General se identifica por bandera, no por id ---

def test_credit_to_general_customer_rejected(
    test_client, auth_headers, cred_product, open_cash
):
    """No se puede vender a credito al Cliente General (id=1, is_general=True)."""
    resp = test_client.post(
        "/sales/",
        json=_sale_payload(
            cred_product.id, customer_id=1,  # el General sembrado en conftest
            payment_method="Crédito", credit_days=30,
        ),
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "general" in resp.json()["detail"].lower()


def test_credit_blocked_by_flag_not_by_id(
    test_client, auth_headers, cred_product, open_cash, db_session
):
    """Un cliente marcado is_general=True se bloquea AUNQUE su id no sea 1.

    Prueba que el bloqueo lo decide la bandera is_general y no el viejo
    hardcode customer_id == 1.
    """
    from app.db.models.customer import Customer
    gen = Customer(name="Mostrador Sucursal", is_general=True, is_active=True)
    db_session.add(gen)
    db_session.commit()
    db_session.refresh(gen)
    assert gen.id != 1  # tiene otro id; debe bloquearse igual por la bandera

    resp = test_client.post(
        "/sales/",
        json=_sale_payload(
            cred_product.id, customer_id=gen.id,
            payment_method="Crédito", credit_days=30,
        ),
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "general" in resp.json()["detail"].lower()


def test_real_customer_at_id_1_can_get_credit(
    test_client, auth_headers, cred_product, open_cash, db_session
):
    """Reproduce el bug original: el cliente id=1, si NO es general, admite credito.

    Antes, el hardcode customer_id == 1 bloqueaba al PRIMER cliente real (que
    tomaba id=1). Aqui desmarcamos el General de id=1 para simular un cliente
    real en esa posicion, le damos cupo, y el credito debe COMPLETARSE.
    """
    from app.db.models.customer import Customer
    c1 = db_session.get(Customer, 1)
    c1.is_general = False
    c1.has_credit_limit = True
    c1.credit_limit = 1_000_000.0
    db_session.commit()

    resp = test_client.post(
        "/sales/",
        json=_sale_payload(
            cred_product.id, customer_id=1,
            payment_method="Crédito", credit_days=30,
        ),
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["sale"]["payment_method"] == "Crédito"