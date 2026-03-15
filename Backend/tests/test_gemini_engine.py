"""
Tests for gemini_engine.py — Google Gemini API Engine Adapter

Tests cover:
  - Engine properties (name, type, capabilities)
  - Session management (start, stop, status)
  - Prompt sending with mocked client
  - Tool calling conversion
  - Token tracking and cost estimation
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
from gemini_engine import GeminiEngine, MODEL_PRICING


class TestEngineProperties(unittest.TestCase):
    """Test engine properties and capabilities."""

    def setUp(self):
        self.engine = GeminiEngine()

    def test_engine_name(self):
        self.assertEqual(self.engine.engine_name, "gemini_api")

    def test_engine_type(self):
        self.assertEqual(self.engine.engine_type, EngineType.API_DIRECT)

    def test_supports_streaming(self):
        self.assertTrue(self.engine.supports_streaming())

    def test_supports_mcp(self):
        self.assertTrue(self.engine.supports_mcp())

    def test_not_interactive(self):
        self.assertFalse(self.engine.supports_interactive())


class TestStartStop(unittest.TestCase):
    """Test session start and stop."""

    def setUp(self):
        self.engine = GeminiEngine()

    @patch("gemini_engine.HAS_GEMINI", True)
    @patch("gemini_engine.genai_sdk")
    def test_start_success(self, mock_sdk):
        mock_model = MagicMock()
        mock_sdk.GenerativeModel.return_value = mock_model

        config = EngineConfig(
            engine="gemini_api",
            agent_id="agent_1",
            api_key="test-key",
            model="gemini-2.0-flash",
        )
        result = self.engine.start(config)
        self.assertTrue(result)
        self.assertEqual(self.engine.get_status("agent_1"), EngineStatus.READY)
        mock_sdk.configure.assert_called_once_with(api_key="test-key")

    @patch("gemini_engine.HAS_GEMINI", False)
    def test_start_no_sdk(self):
        config = EngineConfig(
            engine="gemini_api",
            agent_id="agent_1",
            api_key="test-key",
        )
        result = self.engine.start(config)
        self.assertFalse(result)

    @patch("gemini_engine.HAS_GEMINI", True)
    @patch("gemini_engine.genai_sdk")
    def test_start_no_api_key(self, mock_sdk):
        config = EngineConfig(
            engine="gemini_api",
            agent_id="agent_1",
            api_key="",
        )
        result = self.engine.start(config)
        self.assertFalse(result)

    @patch("gemini_engine.HAS_GEMINI", True)
    @patch("gemini_engine.genai_sdk")
    def test_stop(self, mock_sdk):
        mock_sdk.GenerativeModel.return_value = MagicMock()
        config = EngineConfig(
            engine="gemini_api",
            agent_id="agent_1",
            api_key="test-key",
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
        self.engine = GeminiEngine()

    def test_not_started(self):
        self.assertFalse(self.engine.is_alive("missing"))

    @patch("gemini_engine.HAS_GEMINI", True)
    @patch("gemini_engine.genai_sdk")
    def test_alive_when_ready(self, mock_sdk):
        mock_sdk.GenerativeModel.return_value = MagicMock()
        config = EngineConfig(
            engine="gemini_api",
            agent_id="agent_1",
            api_key="test-key",
        )
        self.engine.start(config)
        self.assertTrue(self.engine.is_alive("agent_1"))


def _make_mock_response(text="Hello!", prompt_tokens=10, completion_tokens=20, tool_calls=None):
    """Create a mock Gemini generate_content response."""
    parts = []
    if text:
        parts.append(SimpleNamespace(text=text, function_call=None))
    if tool_calls:
        for tc in tool_calls:
            parts.append(SimpleNamespace(
                text=None,
                function_call=SimpleNamespace(
                    name=tc["name"],
                    args=tc.get("args", {}),
                ),
            ))

    candidate = SimpleNamespace(
        content=SimpleNamespace(parts=parts),
    )
    usage = SimpleNamespace(
        prompt_token_count=prompt_tokens,
        candidates_token_count=completion_tokens,
    )
    return SimpleNamespace(
        candidates=[candidate],
        usage_metadata=usage,
    )


class TestSendPrompt(unittest.TestCase):
    """Test prompt sending with mocked client."""

    def _start_engine(self, mock_sdk, model="gemini-2.0-flash"):
        mock_model = MagicMock()
        mock_sdk.GenerativeModel.return_value = mock_model

        engine = GeminiEngine()
        config = EngineConfig(
            engine="gemini_api",
            agent_id="agent_1",
            api_key="test-key",
            model=model,
        )
        engine.start(config)
        return engine, mock_model

    def test_not_started(self):
        engine = GeminiEngine()
        resp = engine.send_prompt("missing", "Hello")
        self.assertFalse(resp.success)
        self.assertIn("not started", resp.error)

    @patch("gemini_engine.HAS_GEMINI", True)
    @patch("gemini_engine.genai_sdk")
    def test_basic_prompt(self, mock_sdk):
        engine, mock_model = self._start_engine(mock_sdk)
        mock_model.generate_content.return_value = _make_mock_response(text="Hi!")

        resp = engine.send_prompt("agent_1", "Hello")
        self.assertTrue(resp.success)
        self.assertEqual(resp.content, "Hi!")
        self.assertEqual(resp.engine, "gemini_api")

    @patch("gemini_engine.HAS_GEMINI", True)
    @patch("gemini_engine.genai_sdk")
    def test_token_tracking(self, mock_sdk):
        engine, mock_model = self._start_engine(mock_sdk)
        mock_model.generate_content.return_value = _make_mock_response(
            prompt_tokens=100, completion_tokens=50,
        )

        resp = engine.send_prompt("agent_1", "Count tokens")
        self.assertEqual(resp.tokens_used["input"], 100)
        self.assertEqual(resp.tokens_used["output"], 50)


class TestToolCalling(unittest.TestCase):
    """Test tool/function calling."""

    @patch("gemini_engine.HAS_GEMINI", True)
    @patch("gemini_engine.genai_sdk")
    def test_tool_call_in_response(self, mock_sdk):
        mock_model = MagicMock()
        mock_sdk.GenerativeModel.return_value = mock_model

        engine = GeminiEngine()
        config = EngineConfig(
            engine="gemini_api",
            agent_id="agent_1",
            api_key="test-key",
        )
        engine.start(config)

        mock_model.generate_content.return_value = _make_mock_response(
            text="",
            tool_calls=[{"name": "bridge_send", "args": {"to": "agent_b"}}],
        )

        resp = engine.send_prompt("agent_1", "Send message")
        self.assertEqual(len(resp.tool_calls), 1)
        self.assertEqual(resp.tool_calls[0]["name"], "bridge_send")
        self.assertEqual(resp.tool_calls[0]["arguments"]["to"], "agent_b")


class TestErrorHandling(unittest.TestCase):
    """Test error handling."""

    @patch("gemini_engine.HAS_GEMINI", True)
    @patch("gemini_engine.genai_sdk")
    def test_api_error(self, mock_sdk):
        mock_model = MagicMock()
        mock_sdk.GenerativeModel.return_value = mock_model
        mock_model.generate_content.side_effect = Exception("Quota exceeded")

        engine = GeminiEngine()
        config = EngineConfig(
            engine="gemini_api",
            agent_id="agent_1",
            api_key="test-key",
        )
        engine.start(config)
        resp = engine.send_prompt("agent_1", "Hello")

        self.assertFalse(resp.success)
        self.assertIn("Quota exceeded", resp.error)
        self.assertEqual(engine.get_status("agent_1"), EngineStatus.ERROR)


class TestSessionStats(unittest.TestCase):
    """Test session statistics."""

    @patch("gemini_engine.HAS_GEMINI", True)
    @patch("gemini_engine.genai_sdk")
    def test_stats(self, mock_sdk):
        mock_model = MagicMock()
        mock_sdk.GenerativeModel.return_value = mock_model
        mock_model.generate_content.return_value = _make_mock_response(
            prompt_tokens=50, completion_tokens=100,
        )

        engine = GeminiEngine()
        config = EngineConfig(
            engine="gemini_api",
            agent_id="agent_1",
            api_key="test-key",
            model="gemini-2.0-flash",
        )
        engine.start(config)
        engine.send_prompt("agent_1", "Request 1")

        stats = engine.get_session_stats("agent_1")
        self.assertIsNotNone(stats)
        self.assertEqual(stats["model"], "gemini-2.0-flash")
        self.assertEqual(stats["total_input_tokens"], 50)
        self.assertEqual(stats["total_output_tokens"], 100)
        self.assertEqual(stats["request_count"], 1)

    def test_stats_not_started(self):
        engine = GeminiEngine()
        self.assertIsNone(engine.get_session_stats("missing"))


class TestModelPricing(unittest.TestCase):
    """Test model pricing constants."""

    def test_known_models(self):
        self.assertIn("gemini-2.0-flash", MODEL_PRICING)
        self.assertIn("gemini-2.0-pro", MODEL_PRICING)

    def test_pricing_structure(self):
        for model, pricing in MODEL_PRICING.items():
            self.assertIn("input", pricing)
            self.assertIn("output", pricing)


class TestRegistration(unittest.TestCase):
    """Test engine registration."""

    def test_registered(self):
        from engine_abc import ENGINE_REGISTRY
        self.assertIn("gemini_api", ENGINE_REGISTRY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
