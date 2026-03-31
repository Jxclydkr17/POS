import pytest


# --------------------------------------------------
# 🔐 AUTH REQUIRED
# --------------------------------------------------
def test_ai_insights_requires_auth(test_client):
    response = test_client.get("/ai/insights/today")
    assert response.status_code in (401, 403)


# --------------------------------------------------
# ✅ SUCCESS RESPONSE
# --------------------------------------------------
def test_ai_insights_success(test_client, auth_headers):
    response = test_client.get(
        "/ai/insights/today",
        headers=auth_headers
    )

    assert response.status_code == 200
    assert isinstance(response.json(), dict)


# --------------------------------------------------
# 🧠 STRUCTURE VALIDATION
# --------------------------------------------------
def test_ai_insights_structure(test_client, auth_headers):
    data = test_client.get(
        "/ai/insights/today",
        headers=auth_headers
    ).json()

    assert "summary" in data
    assert "alerts" in data
    assert isinstance(data["summary"], str)
    assert isinstance(data["alerts"], list)


# --------------------------------------------------
# 🚨 ALERTS CONTENT
# --------------------------------------------------
def test_ai_insights_alerts_fields(test_client, auth_headers):
    alerts = test_client.get(
        "/ai/insights/today",
        headers=auth_headers
    ).json()["alerts"]

    for alert in alerts:
        assert "type" in alert
        assert "level" in alert
        assert "message" in alert

        if "reference" in alert:
            assert alert["reference"] is None or isinstance(alert["reference"], (int, str))


# --------------------------------------------------
# 🟡 LEVELS VALIDATION
# --------------------------------------------------
def test_ai_insights_alert_levels(test_client, auth_headers):
    valid_levels = {"info", "warning", "critical"}

    alerts = test_client.get(
        "/ai/insights/today",
        headers=auth_headers
    ).json()["alerts"]

    for alert in alerts:
        assert alert["level"] in valid_levels


# --------------------------------------------------
# 🧪 EMPTY SAFE (NO DATA)
# --------------------------------------------------
def test_ai_insights_empty_safe(test_client, auth_headers):
    data = test_client.get(
        "/ai/insights/today",
        headers=auth_headers
    ).json()

    assert "alerts" in data
    assert isinstance(data["alerts"], list)

def test_sales_prediction_handles_zero_days(client, auth_headers):
    res = client.get("/ai/insights/today", headers=auth_headers)
    assert res.status_code == 200
