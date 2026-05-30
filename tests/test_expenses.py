def test_create_expense(test_client, auth_headers):
    payload = {
        "description": "Compra de suministros",
        "amount": 500.0,
        "category": "Compras / Proveedores",
        "payment_method": "Efectivo"
    }
    response = test_client.post("/expenses/", json=payload, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "message" in body


def test_list_expenses(test_client, auth_headers):
    response = test_client.get("/expenses/", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body["data"], dict)
    assert "items" in body["data"]
    assert isinstance(body["data"]["items"], list)
    assert "total_count" in body["data"]


def test_list_expenses_pagination(test_client, auth_headers):
    response = test_client.get("/expenses/?skip=0&limit=10", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "total_count" in body["data"]


def test_update_expense(test_client, auth_headers):
    # Primero crear un gasto
    create_payload = {
        "description": "Gasto para editar",
        "amount": 100.0,
        "category": "Servicios",
        "payment_method": "Efectivo"
    }
    create_res = test_client.post("/expenses/", json=create_payload, headers=auth_headers)
    assert create_res.status_code == 200
    expense_id = create_res.json()["data"]["expense_id"]

    # Editar el gasto
    update_payload = {
        "description": "Gasto editado",
        "amount": 250.0,
    }
    update_res = test_client.put(f"/expenses/{expense_id}", json=update_payload, headers=auth_headers)
    assert update_res.status_code == 200
    body = update_res.json()
    assert body["success"] is True
    assert body["data"]["amount"] == 250.0


def test_update_expense_not_found(test_client, auth_headers):
    update_payload = {"description": "No existe"}
    response = test_client.put("/expenses/999999", json=update_payload, headers=auth_headers)
    assert response.status_code in [404, 500]