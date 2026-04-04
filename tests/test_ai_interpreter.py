# tests/test_ai_interpreter.py
"""
FASE 7 — Tests para la capa inteligente de interpretación.
Testea: JSON parser, InterpretedIntent, execute_interpreted_intent,
y la función interpret() con mocks del LLM.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from app.ai.llm_interpreter import (
    InterpretedIntent,
    interpret,
    execute_interpreted_intent,
    _parse_intent_json,
    _CONFIDENCE_THRESHOLD,
)
from app.ai.ui_context import UIContext


# ═══════════════════════════════════════════════════════
# InterpretedIntent dataclass
# ═══════════════════════════════════════════════════════

class TestInterpretedIntent:

    def test_actionable_high_confidence(self):
        i = InterpretedIntent(intent="search_product", confidence=0.95, params={"query": "cemento"})
        assert i.is_actionable is True

    def test_not_actionable_low_confidence(self):
        i = InterpretedIntent(intent="search_product", confidence=0.5)
        assert i.is_actionable is False

    def test_not_actionable_unknown(self):
        i = InterpretedIntent(intent="unknown", confidence=0.99)
        assert i.is_actionable is False

    def test_not_actionable_general_question(self):
        """general_question siempre se delega al LLM con tools."""
        i = InterpretedIntent(intent="general_question", confidence=0.99)
        assert i.is_actionable is False

    def test_threshold_boundary(self):
        below = InterpretedIntent(intent="navigate", confidence=_CONFIDENCE_THRESHOLD - 0.01)
        at = InterpretedIntent(intent="navigate", confidence=_CONFIDENCE_THRESHOLD)
        above = InterpretedIntent(intent="navigate", confidence=_CONFIDENCE_THRESHOLD + 0.01)
        assert below.is_actionable is False
        assert at.is_actionable is True
        assert above.is_actionable is True


# ═══════════════════════════════════════════════════════
# JSON Parser — robusto ante formatos variados del LLM
# ═══════════════════════════════════════════════════════

class TestParseIntentJson:

    def test_clean_json(self):
        j = _parse_intent_json('{"intent": "greeting", "confidence": 0.9, "params": {}}')
        assert j["intent"] == "greeting"

    def test_with_markdown_backticks(self):
        text = '```json\n{"intent": "navigate", "confidence": 0.8, "params": {"module": "ventas"}}\n```'
        j = _parse_intent_json(text)
        assert j["intent"] == "navigate"
        assert j["params"]["module"] == "ventas"

    def test_with_backticks_no_lang(self):
        text = '```\n{"intent": "cancel", "confidence": 0.85, "params": {}}\n```'
        j = _parse_intent_json(text)
        assert j["intent"] == "cancel"

    def test_json_embedded_in_text(self):
        text = 'Here is the result: {"intent": "greeting", "confidence": 0.9, "params": {}}'
        j = _parse_intent_json(text)
        assert j["intent"] == "greeting"

    def test_json_with_nested_params(self):
        text = '{"intent": "query_data", "confidence": 0.85, "params": {"type": "sales", "period": "today"}, "reply": ""}'
        j = _parse_intent_json(text)
        assert j["intent"] == "query_data"
        assert j["params"]["type"] == "sales"

    def test_invalid_json(self):
        assert _parse_intent_json("not json at all") is None

    def test_json_without_intent(self):
        assert _parse_intent_json('{"name": "test"}') is None

    def test_empty_string(self):
        assert _parse_intent_json("") is None

    def test_whitespace_only(self):
        assert _parse_intent_json("   \n  ") is None


# ═══════════════════════════════════════════════════════
# Execute Interpreted Intent
# ═══════════════════════════════════════════════════════

class TestExecuteInterpretedIntent:

    def test_greeting(self):
        i = InterpretedIntent(intent="greeting", confidence=0.9, reply="¡Mae, pura vida!")
        r = execute_interpreted_intent(i, None)
        assert r is not None
        assert r["reply_text"] == "¡Mae, pura vida!"
        assert r["actions"] == []

    def test_greeting_default_reply(self):
        i = InterpretedIntent(intent="greeting", confidence=0.9, reply="")
        r = execute_interpreted_intent(i, None)
        assert "Pura vida" in r["reply_text"]

    def test_search_product(self):
        i = InterpretedIntent(intent="search_product", confidence=0.9, params={"query": "cemento"})
        r = execute_interpreted_intent(i, None)
        assert r["actions"][0]["type"] == "search_product"
        assert r["actions"][0]["query"] == "cemento"

    def test_search_product_empty_query(self):
        i = InterpretedIntent(intent="search_product", confidence=0.9, params={"query": ""})
        assert execute_interpreted_intent(i, None) is None

    def test_search_customer(self):
        i = InterpretedIntent(intent="search_customer", confidence=0.9, params={"query": "Randall"})
        r = execute_interpreted_intent(i, None)
        assert r["actions"][0]["type"] == "navigate"
        assert r["actions"][0]["module"] == "customers"
        assert r["actions"][0]["query"] == "Randall"

    def test_navigate(self):
        for module, expected in [
            ("gastos", "gastos"),
            ("ventas", "ventas"),
            ("dashboard", "dashboard"),
            ("configuracion", "configuración"),
            ("compras", "compras/facturas"),
            ("reporte_diario", "daily_report"),
        ]:
            i = InterpretedIntent(intent="navigate", confidence=0.9, params={"module": module})
            r = execute_interpreted_intent(i, None)
            assert r is not None, f"navigate({module}) returned None"
            assert r["actions"][0]["module"] == expected, f"navigate({module}): expected {expected}"

    def test_navigate_empty(self):
        i = InterpretedIntent(intent="navigate", confidence=0.9, params={"module": ""})
        assert execute_interpreted_intent(i, None) is None

    def test_set_customer(self):
        i = InterpretedIntent(intent="set_customer", confidence=0.9, params={"name": "Carlos"})
        r = execute_interpreted_intent(i, None)
        assert r["actions"][0]["type"] == "set_customer"
        assert r["actions"][0]["name"] == "Carlos"

    def test_set_payment(self):
        i = InterpretedIntent(intent="set_payment", confidence=0.9, params={"method": "sinpe"})
        r = execute_interpreted_intent(i, None)
        assert r["actions"][0]["type"] == "set_payment_method"
        assert r["actions"][0]["method"] == "sinpe"

    def test_add_to_cart(self):
        i = InterpretedIntent(intent="add_to_cart", confidence=0.9, params={"query": "tornillos", "qty": 5})
        r = execute_interpreted_intent(i, None)
        assert r["actions"][0]["type"] == "search_product"
        assert r["actions"][0]["query"] == "tornillos"
        assert r["actions"][0]["auto_add_qty"] == 5

    def test_add_to_cart_default_qty(self):
        i = InterpretedIntent(intent="add_to_cart", confidence=0.9, params={"query": "martillo"})
        r = execute_interpreted_intent(i, None)
        assert r["actions"][0]["auto_add_qty"] == 1

    def test_confirm_sale(self):
        i = InterpretedIntent(intent="confirm_sale", confidence=0.9, params={})
        r = execute_interpreted_intent(i, None)
        assert r["actions"][0]["type"] == "preview_confirm_sale"

    def test_cancel(self):
        i = InterpretedIntent(intent="cancel", confidence=0.9, params={})
        r = execute_interpreted_intent(i, None)
        assert r["actions"][0]["type"] == "cancel_operation"

    def test_register_expense(self):
        i = InterpretedIntent(
            intent="register_expense", confidence=0.9,
            params={"amount": 15000, "category": "gasolina", "description": "combustible"}
        )
        r = execute_interpreted_intent(i, None)
        assert r["actions"][0]["type"] == "register_expense"
        assert r["actions"][0]["amount"] == 15000

    def test_register_expense_no_amount(self):
        i = InterpretedIntent(intent="register_expense", confidence=0.9, params={"amount": 0})
        assert execute_interpreted_intent(i, None) is None

    def test_query_data_delegated(self):
        """query_data siempre se delega al LLM con tools."""
        i = InterpretedIntent(intent="query_data", confidence=0.9, params={"type": "sales"})
        assert execute_interpreted_intent(i, None) is None

    def test_general_question_delegated(self):
        i = InterpretedIntent(intent="general_question", confidence=0.9, params={})
        assert execute_interpreted_intent(i, None) is None

    def test_unknown_delegated(self):
        i = InterpretedIntent(intent="unknown", confidence=0.5, params={})
        assert execute_interpreted_intent(i, None) is None


# ═══════════════════════════════════════════════════════
# interpret() — con mocks del LLM
# ═══════════════════════════════════════════════════════

class TestInterpretFunction:

    def test_no_llm_returns_none(self):
        """Sin LLM configurado → None (fallback silencioso)."""
        import os
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(k, None)
        result = interpret("hola mae", None)
        assert result is None

    @patch("app.ai.llm_interpreter.get_active_provider")
    def test_successful_interpretation(self, mock_provider):
        """Mock del LLM que retorna JSON válido de intención."""
        mock_p = MagicMock()
        mock_p.format_system_prompt.return_value = "system"
        mock_p.format_messages.return_value = [{"role": "user", "content": "test"}]
        mock_p.call_completion.return_value = {
            "success": True,
            "raw_response": {"mock": True},
            "error_type": None,
            "error_message": None,
        }
        mock_p.extract_text.return_value = '{"intent": "search_product", "confidence": 0.95, "params": {"query": "cemento"}, "reply": ""}'
        mock_provider.return_value = (mock_p, "fake-key", {"model": "", "max_tokens": 1024, "temperature": 0.3, "custom_prompt": ""})

        result = interpret("busca cemento", None)
        assert result is not None
        assert result.intent == "search_product"
        assert result.confidence == 0.95
        assert result.params["query"] == "cemento"
        assert result.is_actionable is True

    @patch("app.ai.llm_interpreter.get_active_provider")
    def test_llm_returns_invalid_json(self, mock_provider):
        """Si el LLM retorna basura → None."""
        mock_p = MagicMock()
        mock_p.format_system_prompt.return_value = "s"
        mock_p.format_messages.return_value = []
        mock_p.call_completion.return_value = {
            "success": True, "raw_response": {}, "error_type": None, "error_message": None,
        }
        mock_p.extract_text.return_value = "I cannot parse this request properly"
        mock_provider.return_value = (mock_p, "k", {"model": "", "max_tokens": 256, "temperature": 0.3, "custom_prompt": ""})

        result = interpret("algo raro", None)
        assert result is None

    @patch("app.ai.llm_interpreter.get_active_provider")
    def test_llm_call_fails(self, mock_provider):
        """Si el LLM falla → None."""
        mock_p = MagicMock()
        mock_p.format_system_prompt.return_value = "s"
        mock_p.format_messages.return_value = []
        mock_p.call_completion.return_value = {
            "success": False, "raw_response": None, "error_type": "timeout", "error_message": "timeout",
        }
        mock_provider.return_value = (mock_p, "k", {"model": "", "max_tokens": 256, "temperature": 0.3, "custom_prompt": ""})

        result = interpret("ventas hoy", None)
        assert result is None

    @patch("app.ai.llm_interpreter.get_active_provider")
    def test_interpret_with_context(self, mock_provider):
        """Verifica que el contexto UI se inyecta en el mensaje."""
        mock_p = MagicMock()
        mock_p.format_system_prompt.return_value = "s"
        mock_p.format_messages.return_value = []
        mock_p.call_completion.return_value = {
            "success": True, "raw_response": {}, "error_type": None, "error_message": None,
        }
        mock_p.extract_text.return_value = '{"intent": "confirm_sale", "confidence": 0.9, "params": {}}'
        mock_provider.return_value = (mock_p, "k", {"model": "", "max_tokens": 256, "temperature": 0.3, "custom_prompt": ""})

        ctx = UIContext(current_screen="ventas", cart_count=3, cart_total=15000)
        result = interpret("cobrále", None, ctx)

        assert result is not None
        assert result.intent == "confirm_sale"

        # Verificar que format_messages recibió el contexto
        call_args = mock_p.format_messages.call_args[0][0]
        assert "CONTEXTO ACTUAL" in call_args[0]["content"]

    @patch("app.ai.llm_interpreter.get_active_provider")
    def test_confidence_clamping(self, mock_provider):
        """Confidence se clampea a [0.0, 1.0]."""
        mock_p = MagicMock()
        mock_p.format_system_prompt.return_value = "s"
        mock_p.format_messages.return_value = []
        mock_p.call_completion.return_value = {
            "success": True, "raw_response": {}, "error_type": None, "error_message": None,
        }
        mock_p.extract_text.return_value = '{"intent": "greeting", "confidence": 1.5, "params": {}}'
        mock_provider.return_value = (mock_p, "k", {"model": "", "max_tokens": 256, "temperature": 0.3, "custom_prompt": ""})

        result = interpret("hola", None)
        assert result.confidence == 1.0  # clamped