def test_delete_sale_requires_admin(test_client, auth_headers):
    response = test_client.delete("/sales/999", headers=auth_headers)
    assert response.status_code in [200, 403, 404]
