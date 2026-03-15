"""
Tests for litellm_engine.py — LiteLLM Proxy Engine Adapter

Tests cover:
  - Engine properties (name, type, capabilities)
  - Session management (start, stop, status)
  - Prompt sending with mocked client
  - Tool calling conversion
  - Token tracking
  - Provider detection
  - Error handling
  - Missing SDK graceful degradation
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine_abc import EngineConfig, EngineStatus, EngineType
from litellm_engine import LiteLLMEngine, _detect_provider


class TestEngineProperties(unittest.TestCase):
    """Test engine properties and capabilities."""

    def setUp(self):
        self.engine = LiteLLMEngine()

    def test_engine_name(self):
        self.assertEqual(self.engine.engine_name, "litellm")

    def test_engine_type(self):
        self.assertEqual(self.engine.engine_type, EngineType.PROXY)

    def test_supports_streaming(self):
        self.assertTrue(self.engine.supports_streaming())

    def test_supports_mcp(self):
        self.assertTrue(self.engine.supports_mcp())

    def test_not_interactive(self):
        self.assertFalse(self.engine.supports_interactive())


class TestStartStop(unittest.TestCase):
    """Test session start and stop."""

    def setUp(self):
        self.engine = LiteLLMEngine()

    @patch("litellm_engine.HAS_LITELLM", True)
    @patch("litellm_engine.litellm_sdk")
    def test_start_success(self, mock_sdk):
        config = EngineConfig(
            engine="litellm",
            agent_id="agent_1",
            model="gpt-4o",
        )
        result = self.engine.start(config)
        self.assertTrue(result)
        self.assertEqual(self.engine.get_status("agent_1"), EngineStatus.READY)

    @patch("litellm_engine.HAS_LITELLM", True)
    @patch("litellm_engine.litellm_sdk")
    def test_start_no_api_key_still_works(self, mock_sdk):
        """LiteLLM can work without explicit API key (env vars)."""
        config = EngineConfig(
            engine="litellm",
            agent_id="agent_1",
            api_key="",
        )
        result = self.engine.start(config)
        self.assertTrue(result)

    @patch("litellm_engine.HAS_LITELLM", False)
    def test_start_no_sdk(self):
        config = EngineConfig(
            engine="litellm",
            agent_id="agent_1",
        )
        result = self.engine.start(config)
        self.assertFalse(result)

    @patch("litellm_engine.HAS_LITELLM", True)
    @patch("litellm_engine.litellm_sdk")
    def test_stop(self, mock_sdk):
        config = EngineConfig(
            engine="litellm",
            agent_id="agent_1",
        )
        self.engine.start(config)
        self.assertTrue(self.engine.stop("agent_1"))
        self.assertEqual(self.engine.get_status("agent_1"), EngineStatus.STOPPED)

    def test_stop_not_started(self):
        self.assertFalse(self.engine.stop("missing"))

    def test_status_not_started(self):
        self.assertEqual(self.engine.get_status("missing"), EngineStatus.STOPPED)


class TestIsAlive(unittest.TestCase):
    """Test is_alive checks."""

    def setUp(self):
        self.engine = LiteLLMEngine()

    def test_not_started(self):
        self.assertFalse(self.engine.is_alive("missing"))

    @patch("litellm_engine.HAS_LITELLM", True)
    @patch("litellm_engine.litellm_sdk")
    def test_alive_when_ready(self, mock_sdk):
        config = EngineConfig(
            engine="litellm",
            agent_id="agent_1",
        )
        self.engine.start(config)
        self.assertTrue(self.engine.is_alive("agent_1"))


def _make_mock_response(content="Hello!", tool_calls=None, prompt_tokens=10, completion_tokens=20):
    """Create a mock LiteLLM completion response."""
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls or [],
    )
    choice = SimpleNamespace(
        message=message,
        finish_reason="stop",
    )
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return SimpleNamespace(
        choices=[choice],
        usage=usage,
        _hidden_params={"response_cost": 0.001},
    )


class TestSendPrompt(unittest.TestCase):
    """Test prompt sending with mocked client."""

    def test_not_started(self):
        engine = LiteLLMEngine()
        resp = engine.send_prompt("missing", "Hello")
        self.assertFalse(resp.success)
        self.assertIn("not started", resp.error)

    @patch("litellm_engine.HAS_LITELLM", True)
    @patch("litellm_engine.litellm_sdk")
    def test_basic_prompt(self, mock_sdk):
        mock_sdk.completion.return_value = _make_mock_response(content="Hi!")

        engine = LiteLLMEngine()
        config = EngineConfig(
            engine="litellm",
            agent_id="agent_1",
            model="gpt-4o",
        )
        engine.start(config)
        resp = engine.send_prompt("agent_1", "Hello")

        self.assertTrue(resp.success)
        self.assertEqual(resp.content, "Hi!")
        self.assertEqual(resp.engine, "litellm")
        self.assertEqual(resp.engine_type, "proxy")

    @patch("litellm_engine.HAS_LITELLM", True)
    @patch("litellm_engine.litellm_sdk")
    def test_token_tracking(self, mock_sdk):
        mock_sdk.completion.return_value = _make_mock_response(
            prompt_tokens=100, completion_tokens=50,
        )

        engine = LiteLLMEngine()
        config = EngineConfig(
            engine="litellm",
            agent_id="agent_1",
        )
        engine.start(config)
        resp = engine.send_prompt("agent_1", "Count tokens")

        self.assertEqual(resp.tokens_used["input"], 100)
        self.assertEqual(resp.tokens_used["output"], 50)

    @patch("litellm_engine.HAS_LITELLM", True)
    @patch("litellm_engine.litellm_sdk")
    def test_with_api_key(self, mock_sdk):
        mock_sdk.completion.return_value = _make_mock_response()

        engine = LiteLLMEngine()
        config = EngineConfig(
            engine="litellm",
            agent_id="agent_1",
            api_key="sk-test",
            model="gpt-4o",
        )
        engine.start(config)
        engine.send_prompt("agent_1", "Hello")

        call_kwargs = mock_sdk.completion.call_args[1]
        self.assertEqual(call_kwargs["api_key"], "sk-test")

    @patch("litellm_engine.HAS_LITELLM", True)
    @patch("litellm_engine.litellm_sdk")
    def test_with_system_prompt(self, mock_sdk):
        mock_sdk.completion.return_value = _make_mock_response()

        engine = LiteLLMEngine()
        config = EngineConfig(
            engine="litellm",
            agent_id="agent_1",
            system_prompt="You are helpful.",
        )
        engine.start(config)
        engine.send_prompt("agent_1", "Hello")

        call_kwargs = mock_sdk.completion.call_args[1]
        messages = call_kwargs["messages"]
        self.assertEqual(messages[0]["role"], "system")


class TestToolCalling(unittest.TestCase):
    """Test tool/function calling."""

    @patch("litellm_engine.HAS_LITELLM", True)
    @patch("litellm_engine.litellm_sdk")
    def test_tool_call_in_response(self, mock_sdk):
        mock_tc = SimpleNamespace(
            id="call_xyz",
            function=SimpleNamespace(
                name="bridge_send",
                arguments='{"to":"agent_b"}',
            ),
        )
        mock_sdk.completion.return_value = _make_mock_response(
            content="", tool_calls=[mock_tc],
        )

        engine = LiteLLMEngine()
        config = EngineConfig(engine="litellm", agent_id="agent_1")
        engine.start(config)
        resp = engine.send_prompt("agent_1", "Send message")

        self.assertEqual(len(resp.tool_calls), 1)
        self.assertEqual(resp.tool_calls[0]["name"], "bridge_send")


class TestErrorHandling(unittest.TestCase):
    """Test error handling."""

    @patch("litellm_engine.HAS_LITELLM", True)
    @patch("litellm_engine.litellm_sdk")
    def test_api_error(self, mock_sdk):
        mock_sdk.completion.side_effect = Exception("Connection refused")

        engine = LiteLLMEngine()
        config = EngineConfig(engine="litellm", agent_id="agent_1")
        engine.start(config)
        resp = engine.send_prompt("agent_1", "Hello")

        self.assertFalse(resp.success)
        self.assertIn("Connection refused", resp.error)
        self.assertEqual(engine.get_status("agent_1"), EngineStatus.ERROR)


class TestSessionStats(unittest.TestCase):
    """Test session statistics."""

    @patch("litellm_engine.HAS_LITELLM", True)
    @patch("litellm_engine.litellm_sdk")
    def test_stats(self, mock_sdk):
        mock_sdk.completion.return_value = _make_mock_response(
            prompt_tokens=50, completion_tokens=100,
        )

        engine = LiteLLMEngine()
        config = EngineConfig(
            engine="litellm",
            agent_id="agent_1",
            model="gpt-4o",
        )
        engine.start(config)
        engine.send_prompt("agent_1", "Request")

        stats = engine.get_session_stats("agent_1")
        self.assertIsNotNone(stats)
        self.assertEqual(stats["model"], "gpt-4o")
        self.assertEqual(stats["provider"], "openai")
        self.assertEqual(stats["total_input_tokens"], 50)
        self.assertEqual(stats["request_count"], 1)

    def test_stats_not_started(self):
        engine = LiteLLMEngine()
        self.assertIsNone(engine.get_session_stats("missing"))


class TestProviderDetection(unittest.TestCase):
    """Test _detect_provider helper."""

    def test_prefixed_model(self):
        self.assertEqual(_detect_provider("anthropic/claude-3-opus"), "anthropic")

    def test_claude_model(self):
        self.assertEqual(_detect_provider("claude-3-opus"), "anthropic")

    def test_gpt_model(self):
        self.assertEqual(_detect_provider("gpt-4o"), "openai")

    def test_o1_model(self):
        self.assertEqual(_detect_provider("o1-mini"), "openai")

    def test_gemini_model(self):
        self.assertEqual(_detect_provider("gemini-2.0-flash"), "google")

    def test_unknown_model(self):
        self.assertEqual(_detect_provider("some-custom-model"), "unknown")

    def test_llama_model(self):
        self.assertEqual(_detect_provider("llama-3.1-70b"), "meta/mistral")


class TestRegistration(unittest.TestCase):
    """Test engine registration."""

    def test_registered(self):
        from engine_abc import ENGINE_REGISTRY
        self.assertIn("litellm", ENGINE_REGISTRY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
