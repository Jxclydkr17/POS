def test_create_customer(test_client):
    payload = {
        "name": "Cliente Prueba",
        "email": "cliente_prueba@example.com",
        "phone": "123456789"
    }
    response = test_client.post("/customers/", json=payload)
    assert response.status_code == 200
    assert response.json()["name"] == payload["name"]
    assert "id" in response.json()
