import requests
from datetime import datetime, timedelta
from ui.session_manager import session
from ui.api import BASE_URL

API_AI_INSIGHTS = f"{BASE_URL}/ai/insights/today"
API_SALES_TODAY = f"{BASE_URL}/sales/today"
API_DASHBOARD_SUMMARY = f"{BASE_URL}/dashboard/summary"
API_DASHBOARD_TOP_LISTS = f"{BASE_URL}/dashboard/top-lists"
API_FINANCIAL_SUMMARY = f"{BASE_URL}/financial/summary"


def _headers():
    if not session.token:
        raise ValueError("No hay sesión activa. Token no encontrado.")
    return {"Authorization": f"Bearer {session.token}"}


def fetch_ai_insights_today():
    r = requests.get(API_AI_INSIGHTS, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def fetch_sales_today_total():
    r = requests.get(API_SALES_TODAY, headers=_headers(), timeout=10)
    r.raise_for_status()
    payload = r.json()

    sales = payload.get("data", []) if isinstance(payload, dict) else payload
    total = 0.0
    for s in sales:
        try:
            total += float(s.get("total", 0))
        except Exception:
            pass
    return total


def fetch_dashboard_summary():
    r = requests.get(API_DASHBOARD_SUMMARY, headers=_headers(), timeout=10)
    r.raise_for_status()
    payload = r.json()

    if isinstance(payload, dict):
        return payload.get("data", {}) or {}

    return {}


def fetch_dashboard_7d_performance():
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=6)

    r = requests.get(
        API_FINANCIAL_SUMMARY,
        headers=_headers(),
        params={
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
        },
        timeout=10
    )
    r.raise_for_status()
    return r.json()


def fetch_dashboard_top_lists():
    r = requests.get(API_DASHBOARD_TOP_LISTS, headers=_headers(), timeout=10)
    r.raise_for_status()
    payload = r.json()

    if isinstance(payload, dict):
        return payload.get("data", {}) or {}

    return {}