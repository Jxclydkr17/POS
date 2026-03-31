import pytest

def test_create_product(test_client, auth_headers):
    payload = {
        "code": "PROD001",
        "name": "Producto Test",
        "price": 100.0,
        "stock": 50,
        "category_id": 1,
        "supplier_id": 1
    }
    response = test_client.post("/products/", json=payload, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Producto creado correctamente"
    assert "id" in data["data"]

def test_list_products(test_client, auth_headers):
    response = test_client.get("/products/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert isinstance(data["data"], list)

def test_search_product_by_barcode(test_client, auth_headers):
    # Asume que existe un producto con código de barras "123456"
    response = test_client.get("/products/barcode/123456", headers=auth_headers)
    assert response.status_code in [200, 404]