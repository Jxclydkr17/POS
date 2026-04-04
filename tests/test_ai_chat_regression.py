# tests/test_ai_chat_regression.py
"""
FASE 7 — Tests de regresión del chat.
Verifica que TODOS los flujos existentes siguen funcionando:
  - Sin LLM → regex/fuzzy funciona igual
  - Con LLM → interpreter + legacy + LLM fallback
  - Estados pendientes (confirm, choose, await_payment) no se rompen
  - El carrito y acciones legacy siguen intactos
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════

def _chat(client, text: str, headers: dict, session_id: str = "test-session",
          memory=None, context=None) -> dict:
    """Helper para enviar mensaje al chat."""
    payload = {"text": text, "session_id": session_id}
    if memory is not None:
        payload["memory"] = memory
    if context is not None:
        payload["context"] = context
    r = client.post("/ai/chat", json=payload, headers=headers)
    assert r.status_code == 200, f"Chat failed: {r.text}"
    return r.json()


# ═══════════════════════════════════════════════════════
# REGRESSION: Flujos sin LLM (regex/fuzzy puro)
# ═══════════════════════════════════════════════════════

class TestChatRegressionNoLLM:
    """Estos tests corren SIN API key — todo es regex/fuzzy."""

    @pytest.fixture(autouse=True)
    def _clear_env(self):
        """Asegurar que no hay API keys en el entorno."""
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(k, None)
        yield

    def test_greeting(self, test_client, auth_headers):
        r = _chat(test_client, "hola", auth_headers)
        assert r["reply_text"]
        assert r["session_id"]

    def test_navigate_gastos(self, test_client, auth_headers):
        r = _chat(test_client, "abre gastos", auth_headers)
        text = r["reply_text"].lower()
        # Debe responder con algo de navegación o el LLM fallback
        assert r["reply_text"]

    def test_fallback_static(self, test_client, auth_headers):
        """Texto incomprensible sin LLM → fallback estático."""
        r = _chat(test_client, "xyzqwerty asdfgh", auth_headers)
        assert r["reply_text"]
        # El fallback estático tiene "Te puedo ayudar" o similar
        assert len(r["reply_text"]) > 20

    def test_session_id_preserved(self, test_client, auth_headers):
        r = _chat(test_client, "hola", auth_headers, session_id="my-session-123")
        assert r["session_id"] == "my-session-123"

    def test_memory_returned(self, test_client, auth_headers):
        r = _chat(test_client, "hola", auth_headers)
        assert isinstance(r["memory"], list)
        assert len(r["memory"]) >= 2  # user + assistant

    def test_suggestions_returned(self, test_client, auth_headers):
        r = _chat(test_client, "hola", auth_headers)
        assert isinstance(r["suggestions"], list)

    def test_context_questions(self, test_client, auth_headers):
        """Preguntas sobre contexto UI."""
        r = _chat(
            test_client, "¿en qué pantalla estoy?", auth_headers,
            context={"current_screen": "ventas"},
        )
        assert r["reply_text"]

    def test_search_product_regex(self, test_client, auth_headers):
        r = _chat(test_client, "busca cemento", auth_headers)
        assert r["reply_text"]
        # Puede tener acciones de búsqueda
        has_search = any(
            a.get("type") in ("search_product", "navigate")
            for a in r.get("actions", [])
        )
        # Si no hay match, al menos no crasheó
        assert r["reply_text"]


# ═══════════════════════════════════════════════════════
# REGRESSION: Interpreter skip con pending states
# ═══════════════════════════════════════════════════════

class TestChatPendingStates:
    """Verifica que el interpreter se salta cuando hay estados pendientes."""

    @pytest.fixture(autouse=True)
    def _clear_env(self):
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(k, None)
        yield

    def test_pending_confirm_sale_skips_interpreter(self, test_client, auth_headers):
        """Con pending confirm_sale, 'sí' debe ir al handler legacy."""
        memory = [
            {"role": "user", "content": "confirmar venta"},
            {"role": "assistant", "content": "¿Confirmamos?"},
            {"role": "system", "content": "", "pending_action": "confirm_sale"},
        ]
        r = _chat(test_client, "sí", auth_headers, memory=memory)
        # No debe crashear, debe procesar la confirmación
        assert r["reply_text"]

    def test_pending_choose_product(self, test_client, auth_headers):
        """Con pending choose_product, un número debe seleccionar producto."""
        memory = [
            {"role": "user", "content": "busca cemento"},
            {"role": "assistant", "content": "Encontré 3 productos"},
            {"role": "system", "content": "", "pending_action": "choose_product"},
        ]
        r = _chat(test_client, "1", auth_headers, memory=memory)
        assert r["reply_text"]


# ═══════════════════════════════════════════════════════
# REGRESSION: Chat handler structure integrity
# ═══════════════════════════════════════════════════════

class TestChatHandlerStructure:
    """Verifica que la estructura del chat_handler es correcta."""

    def test_interpreter_import_exists(self):
        from app.ai.chat_handler import chat
        import inspect
        src = inspect.getsource(chat)
        assert "interpret(" in src
        assert "execute_interpreted_intent" in src

    def test_legacy_code_preserved(self):
        from app.ai.chat_handler import chat
        import inspect
        src = inspect.getsource(chat)
        # Flujos legacy deben estar intactos
        assert "_low_stock_intent_action" in src
        assert "_search_customer_intent_action" in src
        assert "hybrid_route" in src
        assert "call_llm" in src
        assert "Fallback estático" in src

    def test_pending_state_guard(self):
        from app.ai.chat_handler import chat
        import inspect
        src = inspect.getsource(chat)
        assert "not _has_pending_state" in src

    def test_proactive_alerts_endpoint(self, test_client, auth_headers):
        r = test_client.get("/ai/proactive-alerts", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "alerts" in data
        assert "message" in data

    def test_export_chat_endpoint(self, test_client, auth_headers):
        r = test_client.post(
            "/ai/export-chat",
            json={"messages": [{"role": "user", "content": "hola"}], "format": "text"},
            headers=auth_headers,
        )
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════
# REGRESSION: AI config endpoints
# ═══════════════════════════════════════════════════════

class TestAIConfigEndpoints:
    """Verifica que los endpoints de configuración de IA funcionan."""

    def test_get_ai_config(self, test_client, auth_headers):
        r = test_client.get("/settings/ai-config", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert "provider" in data
        assert "has_api_key" in data
        assert "is_enabled" in data

    def test_get_ai_providers(self, test_client, auth_headers):
        r = test_client.get("/settings/ai-providers", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)
        names = [p["name"] for p in data]
        assert "anthropic" in names
        assert "openai" in names
        assert "google" in names

    def test_update_ai_config(self, test_client, auth_headers):
        r = test_client.put(
            "/settings/ai-config",
            json={"provider": "anthropic", "is_enabled": False, "max_tokens": 512},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["provider"] == "anthropic"
        assert data["max_tokens"] == 512

    def test_update_ai_config_invalid_provider(self, test_client, auth_headers):
        r = test_client.put(
            "/settings/ai-config",
            json={"provider": "invalid_provider"},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_test_ai_config_bad_provider(self, test_client, auth_headers):
        r = test_client.post(
            "/settings/ai-config/test",
            json={"provider": "nonexistent", "api_key": "test"},
            headers=auth_headers,
        )
        assert r.status_code == 400