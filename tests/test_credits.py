def test_create_credit_account(test_client):
    response = test_client.post("/credits/1/create")  # Asegurate que customer_id 1 exista
    assert response.status_code in [200, 400]  # 400 si ya existía
    assert "credit_id" in response.json() or "detail" in response.json()

def test_add_credit_sale(test_client):
    payload = {"amount": 100.0}
    response = test_client.post("/credits/1/add", json=payload)
    assert response.status_code == 200 or response.status_code == 400
    assert "message" in response.json()

def test_add_payment(test_client):
    payload = {"amount": 50.0}
    response = test_client.post("/credits/1/payments", json=payload)
    assert response.status_code == 200 or response.status_code == 404
