def test_login(test_client):
    response = test_client.post("/users/login", data={
        "username": "testuser",
        "password": "testpass123"
    })
    assert response.status_code == 200
    assert "access_token" in response.json()
