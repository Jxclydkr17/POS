# tests/test_ai_providers.py
"""
FASE 7 — Unit tests para los adapters de cada proveedor LLM.
Testea format_messages, format_tools, parse_response, manejo de errores.
Todo con mocks de HTTP — no requiere API keys reales.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from app.ai.providers.base import BaseLLMProvider, ToolCall
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.openai_provider import OpenAIProvider
from app.ai.providers.google_provider import GoogleProvider


# ═══════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════

SAMPLE_TOOLS = [
    {
        "name": "query_sales",
        "description": "Consulta ventas de un periodo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week", "month"],
                    "description": "Periodo a consultar",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_cash_status",
        "description": "Estado de caja.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

SAMPLE_MESSAGES = [
    {"role": "user", "content": "hola"},
    {"role": "assistant", "content": "pura vida"},
    {"role": "user", "content": "ventas de hoy"},
]


# ═══════════════════════════════════════════════════════
# ANTHROPIC PROVIDER
# ═══════════════════════════════════════════════════════

class TestAnthropicProvider:

    def setup_method(self):
        self.provider = AnthropicProvider()

    def test_metadata(self):
        assert self.provider.name == "anthropic"
        assert self.provider.display_name == "Claude (Anthropic)"
        # FASE 1.2 — Fix 1.2: el default debe ser un modelo vigente
        assert self.provider.default_model in self.provider.supported_models
        # Sonnet 4.6 es el default actual recomendado para POS
        assert "claude-sonnet-4-6" in self.provider.supported_models

    def test_no_deprecated_models_in_supported(self):
        """FASE 1.2 — Fix 1.2: ningún modelo deprecado en supported_models."""
        deprecated = getattr(self.provider, "deprecated_models", frozenset())
        for m in deprecated:
            assert m not in self.provider.supported_models, (
                f"Modelo deprecado '{m}' no debe estar en supported_models"
            )

    def test_safe_model_falls_back_on_deprecated(self):
        """FASE 1.2 — Fix 1.2: si el modelo está deprecado, cae al default."""
        # Asumimos que _safe_model existe (es helper interno pero estable)
        result = self.provider._safe_model("claude-sonnet-4-20250514")
        assert result == self.provider.default_model
        # Modelo vigente se mantiene
        result = self.provider._safe_model("claude-haiku-4-5-20251001")
        assert result == "claude-haiku-4-5-20251001"
        # Vacío/None cae al default
        assert self.provider._safe_model(None) == self.provider.default_model
        assert self.provider._safe_model("") == self.provider.default_model
        assert self.provider._safe_model("   ") == self.provider.default_model

    def test_format_system_prompt(self):
        result = self.provider.format_system_prompt("Eres Violette")
        assert result == "Eres Violette"  # Anthropic: string directo

    def test_format_messages_alternation(self):
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},  # duplicate user
            {"role": "assistant", "content": "c"},
        ]
        result = self.provider.format_messages(msgs)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_format_messages_starts_with_user(self):
        msgs = [
            {"role": "assistant", "content": "x"},
            {"role": "user", "content": "y"},
        ]
        result = self.provider.format_messages(msgs)
        assert result[0]["role"] == "user"

    def test_format_tools_passthrough(self):
        result = self.provider.format_tools(SAMPLE_TOOLS)
        assert result == SAMPLE_TOOLS  # Anthropic format = our internal format

    def test_extract_text(self):
        response = {"content": [{"type": "text", "text": "Hola mae"}]}
        assert self.provider.extract_text(response) == "Hola mae"

    def test_extract_text_empty(self):
        assert self.provider.extract_text({}) == ""
        assert self.provider.extract_text(None) == ""

    def test_extract_tool_calls(self):
        response = {
            "content": [
                {"type": "text", "text": "Voy a consultar"},
                {"type": "tool_use", "id": "call_1", "name": "query_sales", "input": {"period": "today"}},
            ]
        }
        tcs = self.provider.extract_tool_calls(response)
        assert len(tcs) == 1
        assert tcs[0].name == "query_sales"
        assert tcs[0].id == "call_1"
        assert tcs[0].input == {"period": "today"}

    def test_is_tool_use_response(self):
        yes = {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "x", "name": "y", "input": {}}]}
        no = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "done"}]}
        assert self.provider.is_tool_use_response(yes) is True
        assert self.provider.is_tool_use_response(no) is False

    def test_format_tool_result(self):
        result = self.provider.format_tool_result("call_1", "data here")
        assert result == {"type": "tool_result", "tool_use_id": "call_1", "content": "data here"}

    def test_build_tool_results_messages(self):
        results = [{"type": "tool_result", "tool_use_id": "a", "content": "x"}]
        msgs = self.provider.build_tool_results_messages(results)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == results

    @patch("app.ai.providers.anthropic_provider.requests.post")
    def test_call_completion_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": [{"type": "text", "text": "ok"}]}
        mock_post.return_value = mock_resp

        result = self.provider.call_completion(
            api_key="sk-ant-test", messages=[], tools=[], system="", max_tokens=100,
        )
        assert result["success"] is True
        assert result["raw_response"]["content"][0]["text"] == "ok"

    @patch("app.ai.providers.anthropic_provider.requests.post")
    def test_call_completion_auth_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp

        result = self.provider.call_completion(
            api_key="bad-key", messages=[], tools=[], system="", max_tokens=100,
        )
        assert result["success"] is False
        assert result["error_type"] == "auth"

    @patch("app.ai.providers.anthropic_provider.requests.post")
    def test_call_completion_rate_limit(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_post.return_value = mock_resp

        result = self.provider.call_completion(
            api_key="sk-ant-test", messages=[], tools=[], system="", max_tokens=100,
        )
        assert result["success"] is False
        assert result["error_type"] == "rate_limit"

    @patch("app.ai.providers.anthropic_provider.requests.post")
    def test_call_completion_timeout(self, mock_post):
        import requests as req
        mock_post.side_effect = req.Timeout()

        result = self.provider.call_completion(
            api_key="sk-ant-test", messages=[], tools=[], system="", max_tokens=100,
        )
        assert result["success"] is False
        assert result["error_type"] == "timeout"

    @patch("app.ai.providers.anthropic_provider.requests.post")
    def test_call_completion_server_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        result = self.provider.call_completion(
            api_key="sk-ant-test", messages=[], tools=[], system="", max_tokens=100,
        )
        assert result["success"] is False
        assert result["error_type"] == "server_error"


# ═══════════════════════════════════════════════════════
# OPENAI PROVIDER
# ═══════════════════════════════════════════════════════

class TestOpenAIProvider:

    def setup_method(self):
        self.provider = OpenAIProvider()

    def test_metadata(self):
        assert self.provider.name == "openai"
        assert "gpt-4o" in self.provider.supported_models
        assert "gpt-4o-mini" in self.provider.supported_models

    def test_format_system_prompt(self):
        result = self.provider.format_system_prompt("Eres Violette")
        assert result == {"role": "system", "content": "Eres Violette"}

    def test_format_tools_conversion(self):
        result = self.provider.format_tools(SAMPLE_TOOLS)
        assert len(result) == 2
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "query_sales"
        assert result[0]["function"]["parameters"]["properties"]["period"]["type"] == "string"

    def test_extract_text(self):
        response = {"choices": [{"message": {"content": "Tuanis mae"}, "finish_reason": "stop"}]}
        assert self.provider.extract_text(response) == "Tuanis mae"

    def test_extract_text_null_content(self):
        response = {"choices": [{"message": {"content": None}, "finish_reason": "tool_calls"}]}
        assert self.provider.extract_text(response) == ""

    def test_extract_tool_calls(self):
        response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call_abc",
                        "type": "function",
                        "function": {"name": "query_sales", "arguments": '{"period": "today"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }]
        }
        tcs = self.provider.extract_tool_calls(response)
        assert len(tcs) == 1
        assert tcs[0].name == "query_sales"
        assert tcs[0].input == {"period": "today"}

    def test_extract_tool_calls_malformed_json(self):
        """Argumentos JSON malformados no deben crashear."""
        response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call_x",
                        "type": "function",
                        "function": {"name": "test", "arguments": "not json"},
                    }],
                },
                "finish_reason": "tool_calls",
            }]
        }
        tcs = self.provider.extract_tool_calls(response)
        assert len(tcs) == 1
        assert tcs[0].input == {}  # fallback to empty dict

    def test_format_tool_result(self):
        result = self.provider.format_tool_result("call_1", "data")
        assert result == {"role": "tool", "tool_call_id": "call_1", "content": "data"}

    def test_build_tool_results_messages(self):
        results = [
            {"role": "tool", "tool_call_id": "a", "content": "x"},
            {"role": "tool", "tool_call_id": "b", "content": "y"},
        ]
        msgs = self.provider.build_tool_results_messages(results)
        assert len(msgs) == 2  # OpenAI: separate messages
        assert msgs[0]["role"] == "tool"

    @patch("app.ai.providers.openai_provider.requests.post")
    def test_call_completion_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_post.return_value = mock_resp

        result = self.provider.call_completion(
            api_key="sk-test", messages=[{"role": "user", "content": "hi"}],
            tools=[], system={"role": "system", "content": "sys"}, max_tokens=100,
        )
        assert result["success"] is True

    @patch("app.ai.providers.openai_provider.requests.post")
    def test_call_completion_auth_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp

        result = self.provider.call_completion(
            api_key="bad", messages=[], tools=[], system="", max_tokens=100,
        )
        assert result["error_type"] == "auth"


# ═══════════════════════════════════════════════════════
# GOOGLE PROVIDER
# ═══════════════════════════════════════════════════════

class TestGoogleProvider:

    def setup_method(self):
        self.provider = GoogleProvider()

    def test_metadata(self):
        assert self.provider.name == "google"
        assert "gemini-2.0-flash" in self.provider.supported_models
        assert "gemini-2.5-pro" in self.provider.supported_models

    def test_format_system_prompt(self):
        result = self.provider.format_system_prompt("Eres Violette")
        assert result == {"parts": [{"text": "Eres Violette"}]}

    def test_format_messages_role_mapping(self):
        result = self.provider.format_messages(SAMPLE_MESSAGES)
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "model"  # assistant → model
        assert result[0]["parts"] == [{"text": "hola"}]

    def test_format_messages_merge_consecutive(self):
        msgs = [
            {"role": "user", "content": "hola"},
            {"role": "user", "content": "qué tal"},
            {"role": "assistant", "content": "bien"},
        ]
        result = self.provider.format_messages(msgs)
        assert len(result) == 2  # 2 users merged
        assert len(result[0]["parts"]) == 2

    def test_format_messages_starts_with_user(self):
        msgs = [{"role": "assistant", "content": "x"}, {"role": "user", "content": "y"}]
        result = self.provider.format_messages(msgs)
        assert result[0]["role"] == "user"

    def test_format_tools_gemini_conversion(self):
        result = self.provider.format_tools(SAMPLE_TOOLS)
        assert len(result) == 1
        assert "function_declarations" in result[0]
        decls = result[0]["function_declarations"]
        assert len(decls) == 2
        assert decls[0]["name"] == "query_sales"
        assert decls[0]["parameters"]["type"] == "OBJECT"
        assert decls[0]["parameters"]["properties"]["period"]["type"] == "STRING"
        assert decls[0]["parameters"]["properties"]["period"]["enum"] == ["today", "week", "month"]
        # No properties → no parameters key
        assert "parameters" not in decls[1]

    def test_extract_text(self):
        response = {"candidates": [{"content": {"role": "model", "parts": [{"text": "Hola"}]}, "finishReason": "STOP"}]}
        assert self.provider.extract_text(response) == "Hola"

    def test_extract_tool_calls(self):
        response = {
            "candidates": [{
                "content": {
                    "role": "model",
                    "parts": [{"functionCall": {"name": "query_sales", "args": {"period": "today"}}}],
                },
            }]
        }
        tcs = self.provider.extract_tool_calls(response)
        assert len(tcs) == 1
        assert tcs[0].name == "query_sales"
        assert tcs[0].input == {"period": "today"}

    def test_format_tool_result(self):
        result = self.provider.format_tool_result("gemini_query_sales_0", "data")
        assert "functionResponse" in result
        assert result["functionResponse"]["name"] == "query_sales"

    def test_is_blocked_safety(self):
        blocked = {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}
        assert self.provider._is_blocked(blocked) is True

        safety_finish = {"candidates": [{"finishReason": "SAFETY", "content": {}}]}
        assert self.provider._is_blocked(safety_finish) is True

        ok = {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}
        assert self.provider._is_blocked(ok) is False

    def test_build_tool_results_messages(self):
        results = [{"functionResponse": {"name": "test", "response": {"data": "x"}}}]
        msgs = self.provider.build_tool_results_messages(results)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["parts"] == results

    @patch("app.ai.providers.google_provider.requests.post")
    def test_call_completion_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]
        }
        mock_post.return_value = mock_resp

        result = self.provider.call_completion(
            api_key="AIza-test", messages=[{"role": "user", "parts": [{"text": "hi"}]}],
            tools=[], system={"parts": [{"text": "sys"}]}, max_tokens=100,
        )
        assert result["success"] is True

    @patch("app.ai.providers.google_provider.requests.post")
    def test_call_completion_blocked(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}
        mock_post.return_value = mock_resp

        result = self.provider.call_completion(
            api_key="AIza-test", messages=[], tools=[], system={}, max_tokens=100,
        )
        assert result["success"] is False
        assert result["error_type"] == "server_error"

    @patch("app.ai.providers.google_provider.requests.post")
    def test_call_completion_auth_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_post.return_value = mock_resp

        result = self.provider.call_completion(
            api_key="bad", messages=[], tools=[], system={}, max_tokens=100,
        )
        assert result["error_type"] == "auth"


# ═══════════════════════════════════════════════════════
# FULL TOOL DEFINITIONS CONVERSION (all 3 providers)
# ═══════════════════════════════════════════════════════

class TestToolConversionAllProviders:
    """Verifica que las 21 tool definitions reales se convierten sin error."""

    def test_anthropic_tools(self):
        from app.ai.llm_tools import TOOL_DEFINITIONS
        p = AnthropicProvider()
        result = p.format_tools(TOOL_DEFINITIONS)
        assert len(result) == len(TOOL_DEFINITIONS)

    def test_openai_tools(self):
        from app.ai.llm_tools import TOOL_DEFINITIONS
        p = OpenAIProvider()
        result = p.format_tools(TOOL_DEFINITIONS)
        assert len(result) == len(TOOL_DEFINITIONS)
        for t in result:
            assert t["type"] == "function"
            assert "name" in t["function"]

    def test_google_tools(self):
        from app.ai.llm_tools import TOOL_DEFINITIONS
        p = GoogleProvider()
        result = p.format_tools(TOOL_DEFINITIONS)
        decls = result[0]["function_declarations"]
        assert len(decls) == len(TOOL_DEFINITIONS)
        for d in decls:
            assert "name" in d
            assert "description" in d