"""Tests for engine_backend.py — API Backend Protocol and Implementations."""

import os
import unittest
from unittest.mock import patch, MagicMock

# Add Backend to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine_backend import (
    ApiKeyConfig,
    ApiAgentSession,
    ClaudeApiBackend,
    OpenAiApiBackend,
    GoogleAiApiBackend,
    XaiApiBackend,
    register_backend,
    get_backend,
    list_backends,
    init_api_backends,
    resolve_backend,
    _BACKENDS,
)


class TestApiKeyConfig(unittest.TestCase):
    """Test API key configuration."""

    def test_from_env_reads_standard_vars(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test", "OPENAI_API_KEY": "sk-oai-test"}):
            config = ApiKeyConfig.from_env()
            self.assertEqual(config.anthropic, "sk-ant-test")
            self.assertEqual(config.openai, "sk-oai-test")

    def test_from_dict(self):
        config = ApiKeyConfig.from_dict({"anthropic": "key1", "openai": "key2"})
        self.assertEqual(config.anthropic, "key1")
        self.assertEqual(config.openai, "key2")

    def test_get_key_maps_engine_names(self):
        config = ApiKeyConfig(anthropic="ant", openai="oai", google="goo")
        self.assertEqual(config.get_key("claude"), "ant")
        self.assertEqual(config.get_key("codex"), "oai")
        self.assertEqual(config.get_key("gemini"), "goo")

    def test_available_providers(self):
        config = ApiKeyConfig(anthropic="key", google="key")
        providers = config.available_providers()
        self.assertIn("anthropic", providers)
        self.assertIn("google", providers)
        self.assertNotIn("openai", providers)


class TestClaudeApiBackend(unittest.TestCase):
    """Test Claude API backend."""

    def test_start_fails_without_key(self):
        import asyncio
        backend = ClaudeApiBackend(api_key="")
        result = asyncio.run(backend.start("test-agent", {}))
        self.assertFalse(result)

    def test_start_succeeds_with_key(self):
        import asyncio
        backend = ClaudeApiBackend(api_key="sk-test")
        result = asyncio.run(backend.start("test-agent", {"model": "claude-sonnet-4-6"}))
        self.assertTrue(result)
        self.assertTrue(backend.is_alive("test-agent"))

    def test_stop_cleans_session(self):
        import asyncio
        backend = ClaudeApiBackend(api_key="sk-test")
        asyncio.run(backend.start("test-agent", {}))
        self.assertTrue(backend.is_alive("test-agent"))
        asyncio.run(backend.stop("test-agent"))
        self.assertFalse(backend.is_alive("test-agent"))

    def test_engine_name(self):
        backend = ClaudeApiBackend()
        self.assertEqual(backend.get_engine_name(), "claude-api")


class TestOpenAiApiBackend(unittest.TestCase):
    """Test OpenAI API backend."""

    def test_start_fails_without_key(self):
        import asyncio
        backend = OpenAiApiBackend(api_key="")
        result = asyncio.run(backend.start("test-agent", {}))
        self.assertFalse(result)

    def test_engine_name(self):
        backend = OpenAiApiBackend()
        self.assertEqual(backend.get_engine_name(), "openai-api")


class TestBackendRegistry(unittest.TestCase):
    """Test backend registry."""

    def setUp(self):
        _BACKENDS.clear()

    def test_register_and_get(self):
        backend = ClaudeApiBackend(api_key="test")
        register_backend("test-claude", backend)
        self.assertIs(get_backend("test-claude"), backend)

    def test_list_backends(self):
        register_backend("a", ClaudeApiBackend(api_key="t"))
        register_backend("b", OpenAiApiBackend(api_key="t"))
        names = list_backends()
        self.assertIn("a", names)
        self.assertIn("b", names)

    def test_init_api_backends_with_keys(self):
        config = ApiKeyConfig(anthropic="key1", openai="key2")
        results = init_api_backends(config)
        self.assertEqual(results["anthropic"], "ready")
        self.assertEqual(results["openai"], "ready")
        self.assertEqual(results["google"], "no_key")

    def test_resolve_backend_api(self):
        config = ApiKeyConfig(anthropic="key")
        init_api_backends(config)
        backend = resolve_backend("claude", "api")
        self.assertIsNotNone(backend)
        self.assertEqual(backend.get_engine_name(), "claude-api")

    def test_resolve_backend_tmux_returns_none(self):
        backend = resolve_backend("claude", "tmux")
        self.assertIsNone(backend)

    def tearDown(self):
        _BACKENDS.clear()


if __name__ == "__main__":
    unittest.main()
