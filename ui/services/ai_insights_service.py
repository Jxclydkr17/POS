# ui/services/ai_insights_service.py
"""
FASE 6 — Fix 6.X: Auto-refresh ante 401.
  `from ui.api import http as requests`.
"""
from ui.session_manager import session
from ui.api import BASE_URL, http as requests

API_AI_INSIGHTS = f"{BASE_URL}/ai/insights/today"


def fetch_today_insights():
    """
    Obtiene los insights de IA del día desde la API.
    """
    if not session.token:
        raise ValueError("No hay sesión activa. Token no encontrado.")

    headers = {"Authorization": f"Bearer {session.token}"}

    response = requests.get(
        API_AI_INSIGHTS,
        headers=headers,
        timeout=10
    )
    response.raise_for_status()
    return response.json()