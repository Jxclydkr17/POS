def test_login(test_client):
    response = test_client.post("/auth/login", data={
        "username": "admin@example.com",
        "password": "admin123"
    })
    assert response.status_code == 200
    assert "access_token" in response.json()
