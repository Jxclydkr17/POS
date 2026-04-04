# tests/test_ai_crypto_registry.py
"""
FASE 7 — Tests de encriptación de API keys, provider registry y config service.
"""
import os
import pytest
from unittest.mock import patch, MagicMock


# ═══════════════════════════════════════════════════════
# CRYPTO — Encriptación/desencriptación de API keys
# ═══════════════════════════════════════════════════════

class TestCrypto:

    def test_encrypt_decrypt_roundtrip(self):
        from app.core.crypto import encrypt_value, decrypt_value
        key = "sk-ant-api03-abcdef1234567890"
        encrypted = encrypt_value(key)
        assert encrypted != key
        assert decrypt_value(encrypted) == key

    def test_encrypt_empty(self):
        from app.core.crypto import encrypt_value
        assert encrypt_value("") == ""

    def test_decrypt_empty(self):
        from app.core.crypto import decrypt_value
        assert decrypt_value("") is None
        assert decrypt_value(None) is None

    def test_decrypt_invalid_data(self):
        from app.core.crypto import decrypt_value
        assert decrypt_value("not-valid-encrypted-data") is None

    def test_mask_api_key_anthropic(self):
        from app.core.crypto import mask_api_key
        result = mask_api_key("sk-ant-api03-abcdef1234567890")
        assert result.endswith("7890")
        assert "abcdef" not in result
        assert result.startswith("sk-")

    def test_mask_api_key_short(self):
        from app.core.crypto import mask_api_key
        assert mask_api_key("") == ""
        assert "****" in mask_api_key("abc")

    def test_mask_api_key_openai(self):
        from app.core.crypto import mask_api_key
        result = mask_api_key("sk-proj-abc123xyz789")
        assert result.endswith("z789")

    def test_different_keys_different_ciphertexts(self):
        from app.core.crypto import encrypt_value
        e1 = encrypt_value("key-one")
        e2 = encrypt_value("key-two")
        assert e1 != e2

    def test_same_key_different_ciphertexts(self):
        """Fernet uses random IV, so same plaintext → different ciphertext."""
        from app.core.crypto import encrypt_value
        e1 = encrypt_value("same-key")
        e2 = encrypt_value("same-key")
        assert e1 != e2  # different IVs


# ═══════════════════════════════════════════════════════
# PROVIDER REGISTRY
# ═══════════════════════════════════════════════════════

class TestProviderRegistry:

    def test_all_providers_registered(self):
        from app.ai.providers.provider_registry import _PROVIDER_CLASSES
        assert "anthropic" in _PROVIDER_CLASSES
        assert "openai" in _PROVIDER_CLASSES
        assert "google" in _PROVIDER_CLASSES

    def test_get_provider_instance_caching(self):
        from app.ai.providers.provider_registry import _get_provider_instance
        p1 = _get_provider_instance("anthropic")
        p2 = _get_provider_instance("anthropic")
        assert p1 is p2  # Same instance (cached)

    def test_get_provider_instance_unknown(self):
        from app.ai.providers.provider_registry import _get_provider_instance
        with pytest.raises(ValueError, match="desconocido"):
            _get_provider_instance("nonexistent_provider")

    def test_get_active_provider_no_config(self):
        """Sin API key en env ni BD → RuntimeError."""
        from app.ai.providers.provider_registry import get_active_provider
        # Limpiar env vars
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(key, None)
        with pytest.raises(RuntimeError, match="API key"):
            get_active_provider(None)

    def test_get_active_provider_env_fallback(self):
        """Con API key en env → retorna provider + key + extras."""
        from app.ai.providers.provider_registry import get_active_provider
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-12345"
        try:
            provider, api_key, extras = get_active_provider(None)
            assert provider.name == "anthropic"
            assert api_key == "sk-ant-test-12345"
            assert extras["max_tokens"] == 1024
            assert extras["temperature"] == 0.3
            assert extras["custom_prompt"] == ""
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_is_any_provider_available_false(self):
        from app.ai.providers.provider_registry import is_any_provider_available
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(key, None)
        assert is_any_provider_available(None) is False

    def test_is_any_provider_available_openai(self):
        from app.ai.providers.provider_registry import is_any_provider_available
        os.environ["OPENAI_API_KEY"] = "sk-test-openai"
        try:
            assert is_any_provider_available(None) is True
        finally:
            del os.environ["OPENAI_API_KEY"]

    def test_is_any_provider_available_google(self):
        from app.ai.providers.provider_registry import is_any_provider_available
        os.environ["GOOGLE_API_KEY"] = "AIza-test"
        try:
            assert is_any_provider_available(None) is True
        finally:
            del os.environ["GOOGLE_API_KEY"]

    def test_get_available_providers_list(self):
        from app.ai.providers.provider_registry import get_available_providers
        providers = get_available_providers(None)
        names = [p["name"] for p in providers]
        assert "anthropic" in names
        assert "openai" in names
        assert "google" in names
        for p in providers:
            assert "display_name" in p
            assert "models" in p
            assert "default_model" in p

    def test_env_var_resolution(self):
        from app.ai.providers.provider_registry import _resolve_api_key_from_env
        os.environ["ANTHROPIC_API_KEY"] = "test-key-123"
        try:
            assert _resolve_api_key_from_env("anthropic") == "test-key-123"
            assert _resolve_api_key_from_env("openai") is None
            assert _resolve_api_key_from_env("unknown_provider") is None
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_hot_swap_provider(self):
        """Cambiar de proveedor sin reiniciar."""
        from app.ai.providers.provider_registry import get_active_provider

        # Empezar con Anthropic
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-swap-test"
        try:
            p1, k1, _ = get_active_provider(None)
            assert p1.name == "anthropic"
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

        # Cambiar a OpenAI
        os.environ["OPENAI_API_KEY"] = "sk-openai-swap-test"
        try:
            # Sin anthropic key, con openai → fallback detecta openai
            from app.ai.providers.provider_registry import is_any_provider_available
            assert is_any_provider_available(None) is True
        finally:
            del os.environ["OPENAI_API_KEY"]