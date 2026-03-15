"""
Tests for openai_engine.py — OpenAI API Engine Adapter

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
from openai_engine import OpenAIEngine, MODEL_PRICING


class TestEngineProperties(unittest.TestCase):
    """Test engine properties and capabilities."""

    def setUp(self):
        self.engine = OpenAIEngine()

    def test_engine_name(self):
        self.assertEqual(self.engine.engine_name, "openai_api")

    def test_engine_type(self):
        self.assertEqual(self.engine.engine_type, EngineType.API_DIRECT)

    def test_supports_streaming(self):
        self.assertTrue(self.engine.supports_streaming())

    def test_supports_mcp(self):
        self.assertTrue(self.engine.supports_mcp())

    def test_not_interactive(self):
        self.assertFalse(self.engine.supports_interactive())

    def test_no_session_resume(self):
        self.assertFalse(self.engine.supports_session_resume())


class TestStartStop(unittest.TestCase):
    """Test session start and stop."""

    def setUp(self):
        self.engine = OpenAIEngine()

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_start_success(self, mock_sdk):
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
            model="gpt-4o",
        )
        result = self.engine.start(config)
        self.assertTrue(result)
        self.assertEqual(self.engine.get_status("agent_1"), EngineStatus.READY)

    @patch("openai_engine.HAS_OPENAI", False)
    def test_start_no_sdk(self):
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
        )
        result = self.engine.start(config)
        self.assertFalse(result)

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_start_no_api_key(self, mock_sdk):
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="",
        )
        result = self.engine.start(config)
        self.assertFalse(result)

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_stop(self, mock_sdk):
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
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
        self.engine = OpenAIEngine()

    def test_not_started(self):
        self.assertFalse(self.engine.is_alive("missing"))

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_alive_when_ready(self, mock_sdk):
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
        )
        self.engine.start(config)
        self.assertTrue(self.engine.is_alive("agent_1"))

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_not_alive_when_stopped(self, mock_sdk):
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
        )
        self.engine.start(config)
        self.engine.stop("agent_1")
        self.assertFalse(self.engine.is_alive("agent_1"))


def _make_mock_response(content="Hello!", tool_calls=None, prompt_tokens=10, completion_tokens=20):
    """Create a mock OpenAI chat completion response."""
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
    )


class TestSendPrompt(unittest.TestCase):
    """Test prompt sending with mocked client."""

    def setUp(self):
        self.engine = OpenAIEngine()

    def test_not_started(self):
        resp = self.engine.send_prompt("missing", "Hello")
        self.assertFalse(resp.success)
        self.assertIn("not started", resp.error)

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_basic_prompt(self, mock_sdk):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            content="Hi there!"
        )
        mock_sdk.OpenAI.return_value = mock_client

        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
            model="gpt-4o",
        )
        self.engine.start(config)
        resp = self.engine.send_prompt("agent_1", "Hello")

        self.assertTrue(resp.success)
        self.assertEqual(resp.content, "Hi there!")
        self.assertEqual(resp.engine, "openai_api")
        self.assertEqual(resp.engine_type, "api_direct")

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_token_tracking(self, mock_sdk):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            prompt_tokens=100, completion_tokens=50,
        )
        mock_sdk.OpenAI.return_value = mock_client

        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
        )
        self.engine.start(config)
        resp = self.engine.send_prompt("agent_1", "Count tokens")

        self.assertEqual(resp.tokens_used["input"], 100)
        self.assertEqual(resp.tokens_used["output"], 50)

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_with_system_prompt(self, mock_sdk):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response()
        mock_sdk.OpenAI.return_value = mock_client

        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
            system_prompt="You are a helpful assistant.",
        )
        self.engine.start(config)
        self.engine.send_prompt("agent_1", "Hello")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "You are a helpful assistant.")

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_system_prompt_override(self, mock_sdk):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response()
        mock_sdk.OpenAI.return_value = mock_client

        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
            system_prompt="Default prompt",
        )
        self.engine.start(config)
        self.engine.send_prompt("agent_1", "Hello", system_prompt="Override prompt")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        self.assertEqual(messages[0]["content"], "Override prompt")


class TestToolCalling(unittest.TestCase):
    """Test tool/function calling."""

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_tools_converted(self, mock_sdk):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response()
        mock_sdk.OpenAI.return_value = mock_client

        engine = OpenAIEngine()
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
        )
        engine.start(config)

        mcp_tools = [
            {
                "name": "bridge_send",
                "description": "Send message",
                "inputSchema": {
                    "type": "object",
                    "properties": {"to": {"type": "string"}},
                },
            }
        ]
        engine.send_prompt("agent_1", "Send msg", tools=mcp_tools)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        tools = call_kwargs["tools"]
        self.assertEqual(tools[0]["type"], "function")
        self.assertEqual(tools[0]["function"]["name"], "bridge_send")

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_tool_call_in_response(self, mock_sdk):
        mock_tc = SimpleNamespace(
            id="call_abc",
            function=SimpleNamespace(
                name="bridge_send",
                arguments='{"to":"agent_b","content":"hello"}',
            ),
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            content="", tool_calls=[mock_tc],
        )
        mock_sdk.OpenAI.return_value = mock_client

        engine = OpenAIEngine()
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
        )
        engine.start(config)
        resp = engine.send_prompt("agent_1", "Send a message")

        self.assertEqual(len(resp.tool_calls), 1)
        self.assertEqual(resp.tool_calls[0]["id"], "call_abc")
        self.assertEqual(resp.tool_calls[0]["name"], "bridge_send")
        self.assertEqual(resp.tool_calls[0]["arguments"]["to"], "agent_b")


class TestErrorHandling(unittest.TestCase):
    """Test error handling."""

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_api_error(self, mock_sdk):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("Rate limited")
        mock_sdk.OpenAI.return_value = mock_client

        engine = OpenAIEngine()
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
        )
        engine.start(config)
        resp = engine.send_prompt("agent_1", "Hello")

        self.assertFalse(resp.success)
        self.assertIn("Rate limited", resp.error)
        self.assertEqual(engine.get_status("agent_1"), EngineStatus.ERROR)


class TestSessionStats(unittest.TestCase):
    """Test session statistics."""

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_stats_after_requests(self, mock_sdk):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            prompt_tokens=50, completion_tokens=100,
        )
        mock_sdk.OpenAI.return_value = mock_client

        engine = OpenAIEngine()
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
            model="gpt-4o",
        )
        engine.start(config)
        engine.send_prompt("agent_1", "Request 1")
        engine.send_prompt("agent_1", "Request 2")

        stats = engine.get_session_stats("agent_1")
        self.assertIsNotNone(stats)
        self.assertEqual(stats["model"], "gpt-4o")
        self.assertEqual(stats["total_input_tokens"], 100)
        self.assertEqual(stats["total_output_tokens"], 200)
        self.assertEqual(stats["request_count"], 2)
        self.assertGreater(stats["estimated_cost_usd"], 0)

    def test_stats_not_started(self):
        engine = OpenAIEngine()
        self.assertIsNone(engine.get_session_stats("missing"))


class TestCostEstimation(unittest.TestCase):
    """Test cost estimation."""

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_known_model_cost(self, mock_sdk):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response(
            prompt_tokens=1_000_000, completion_tokens=1_000_000,
        )
        mock_sdk.OpenAI.return_value = mock_client

        engine = OpenAIEngine()
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
            model="gpt-4o",
        )
        engine.start(config)
        engine.send_prompt("agent_1", "Big request")

        stats = engine.get_session_stats("agent_1")
        # gpt-4o: $2.50/M input + $10.00/M output = $12.50
        self.assertAlmostEqual(stats["estimated_cost_usd"], 12.50, places=2)

    @patch("openai_engine.HAS_OPENAI", True)
    @patch("openai_engine.openai_sdk")
    def test_unknown_model_zero_cost(self, mock_sdk):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_mock_response()
        mock_sdk.OpenAI.return_value = mock_client

        engine = OpenAIEngine()
        config = EngineConfig(
            engine="openai_api",
            agent_id="agent_1",
            api_key="sk-test-key",
            model="some-new-model",
        )
        engine.start(config)
        engine.send_prompt("agent_1", "Hello")

        stats = engine.get_session_stats("agent_1")
        self.assertEqual(stats["estimated_cost_usd"], 0.0)


class TestModelPricing(unittest.TestCase):
    """Test model pricing constants."""

    def test_known_models(self):
        self.assertIn("gpt-4o", MODEL_PRICING)
        self.assertIn("gpt-4o-mini", MODEL_PRICING)

    def test_pricing_structure(self):
        for model, pricing in MODEL_PRICING.items():
            self.assertIn("input", pricing, f"Missing input price for {model}")
            self.assertIn("output", pricing, f"Missing output price for {model}")
            self.assertGreater(pricing["input"], 0)
            self.assertGreater(pricing["output"], 0)


class TestRegistration(unittest.TestCase):
    """Test engine registration."""

    def test_registered(self):
        from engine_abc import ENGINE_REGISTRY
        self.assertIn("openai_api", ENGINE_REGISTRY)
        self.assertEqual(ENGINE_REGISTRY["openai_api"], OpenAIEngine)


if __name__ == "__main__":
    unittest.main(verbosity=2)
