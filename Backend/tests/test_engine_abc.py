"""
Tests for engine_abc.py — Abstract Base Class for Engine Adapters

Tests cover:
  - EngineType and EngineStatus enums
  - EngineResponse data class
  - EngineConfig data class (including api_key masking)
  - EngineAdapter ABC (abstract methods, capabilities, defaults)
  - EchoAdapter (reference implementation)
  - Engine Registry (register, get, list)
  - Instruction file mapping
  - Custom adapter registration
"""

import os
import sys
import unittest
from typing import Any

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine_abc import (
    ENGINE_REGISTRY,
    INSTRUCTION_FILES,
    EchoAdapter,
    EngineAdapter,
    EngineConfig,
    EngineResponse,
    EngineStatus,
    EngineType,
    get_engine,
    list_engines,
    register_engine,
)


class TestEngineType(unittest.TestCase):
    """Test EngineType enum."""

    def test_values(self):
        self.assertEqual(EngineType.CLI_INTERACTIVE.value, "cli_interactive")
        self.assertEqual(EngineType.CLI_SUBPROCESS.value, "cli_subprocess")
        self.assertEqual(EngineType.API_DIRECT.value, "api_direct")
        self.assertEqual(EngineType.PROXY.value, "proxy")
        self.assertEqual(EngineType.WEB_AUTOMATION.value, "web_automation")

    def test_all_types(self):
        self.assertEqual(len(EngineType), 5)


class TestEngineStatus(unittest.TestCase):
    """Test EngineStatus enum."""

    def test_values(self):
        self.assertEqual(EngineStatus.READY.value, "ready")
        self.assertEqual(EngineStatus.BUSY.value, "busy")
        self.assertEqual(EngineStatus.ERROR.value, "error")
        self.assertEqual(EngineStatus.STOPPED.value, "stopped")
        self.assertEqual(EngineStatus.STARTING.value, "starting")


class TestEngineResponse(unittest.TestCase):
    """Test EngineResponse data class."""

    def test_basic_response(self):
        resp = EngineResponse(
            success=True,
            engine="claude",
            engine_type="cli_interactive",
            content="Hello world",
        )
        self.assertTrue(resp.success)
        self.assertEqual(resp.content, "Hello world")
        self.assertIsNone(resp.error)
        self.assertEqual(resp.tool_calls, [])

    def test_error_response(self):
        resp = EngineResponse(
            success=False,
            engine="gpt",
            engine_type="api_direct",
            content="",
            error="API key invalid",
        )
        self.assertFalse(resp.success)
        self.assertEqual(resp.error, "API key invalid")

    def test_with_tokens(self):
        resp = EngineResponse(
            success=True,
            engine="claude",
            engine_type="api_direct",
            content="Result",
            tokens_used={"input": 100, "output": 50},
        )
        self.assertEqual(resp.tokens_used["input"], 100)
        self.assertEqual(resp.tokens_used["output"], 50)

    def test_to_dict(self):
        resp = EngineResponse(
            success=True, engine="echo", engine_type="cli_subprocess",
            content="Test", session_id="s1",
        )
        d = resp.to_dict()
        self.assertIn("success", d)
        self.assertIn("content", d)
        self.assertEqual(d["session_id"], "s1")

    def test_with_tool_calls(self):
        resp = EngineResponse(
            success=True, engine="claude", engine_type="api_direct",
            content="",
            tool_calls=[{"name": "search", "input": {"q": "test"}}],
        )
        self.assertEqual(len(resp.tool_calls), 1)


class TestEngineConfig(unittest.TestCase):
    """Test EngineConfig data class."""

    def test_basic_config(self):
        cfg = EngineConfig(engine="claude", agent_id="alex")
        self.assertEqual(cfg.engine, "claude")
        self.assertEqual(cfg.agent_id, "alex")
        self.assertEqual(cfg.max_tokens, 4096)
        self.assertEqual(cfg.temperature, 0.7)

    def test_api_key_masked_in_dict(self):
        cfg = EngineConfig(
            engine="openai_api", agent_id="alex",
            api_key="sk-12345-secret-key",
        )
        d = cfg.to_dict()
        self.assertEqual(d["api_key"], "***")
        self.assertNotIn("sk-12345", str(d))

    def test_empty_api_key_in_dict(self):
        cfg = EngineConfig(engine="echo", agent_id="alex")
        d = cfg.to_dict()
        self.assertEqual(d["api_key"], "(not set)")

    def test_system_prompt_truncated_in_dict(self):
        cfg = EngineConfig(
            engine="claude", agent_id="alex",
            system_prompt="A" * 200,
        )
        d = cfg.to_dict()
        self.assertTrue(d["system_prompt"].endswith("..."))
        self.assertLess(len(d["system_prompt"]), 100)

    def test_extras(self):
        cfg = EngineConfig(
            engine="claude", agent_id="alex",
            extras={"tmux_session": "acw_alex"},
        )
        self.assertEqual(cfg.extras["tmux_session"], "acw_alex")


class TestInstructionFiles(unittest.TestCase):
    """Test instruction file mapping."""

    def test_claude_maps_to_claude_md(self):
        self.assertEqual(INSTRUCTION_FILES["claude"], "CLAUDE.md")

    def test_codex_maps_to_agents_md(self):
        self.assertEqual(INSTRUCTION_FILES["codex"], "AGENTS.md")

    def test_gemini_maps_to_gemini_md(self):
        self.assertEqual(INSTRUCTION_FILES["gemini"], "GEMINI.md")

    def test_api_engines_map_correctly(self):
        self.assertEqual(INSTRUCTION_FILES["anthropic_api"], "CLAUDE.md")
        self.assertEqual(INSTRUCTION_FILES["openai_api"], "AGENTS.md")

    def test_proxy_engines_default_to_claude(self):
        self.assertEqual(INSTRUCTION_FILES["openrouter"], "CLAUDE.md")
        self.assertEqual(INSTRUCTION_FILES["litellm"], "CLAUDE.md")


class TestEngineAdapterABC(unittest.TestCase):
    """Test that EngineAdapter enforces abstract methods."""

    def test_cannot_instantiate_abstract(self):
        with self.assertRaises(TypeError):
            EngineAdapter()  # type: ignore

    def test_incomplete_subclass_fails(self):
        # Missing abstract methods should fail
        class IncompleteAdapter(EngineAdapter):
            @property
            def engine_name(self) -> str:
                return "incomplete"

            @property
            def engine_type(self) -> EngineType:
                return EngineType.CLI_SUBPROCESS

        with self.assertRaises(TypeError):
            IncompleteAdapter()  # type: ignore


class TestEchoAdapter(unittest.TestCase):
    """Test the reference EchoAdapter implementation."""

    def setUp(self):
        self.adapter = EchoAdapter()

    def test_engine_name(self):
        self.assertEqual(self.adapter.engine_name, "echo")

    def test_engine_type(self):
        self.assertEqual(self.adapter.engine_type, EngineType.CLI_SUBPROCESS)

    def test_start(self):
        config = EngineConfig(engine="echo", agent_id="test_agent")
        self.assertTrue(self.adapter.start(config))

    def test_send_prompt(self):
        config = EngineConfig(engine="echo", agent_id="test_agent")
        self.adapter.start(config)

        resp = self.adapter.send_prompt("test_agent", "Hello world")
        self.assertTrue(resp.success)
        self.assertEqual(resp.content, "[echo] Hello world")
        self.assertEqual(resp.engine, "echo")
        self.assertIsNotNone(resp.tokens_used)

    def test_send_prompt_not_started(self):
        resp = self.adapter.send_prompt("unknown", "Hello")
        self.assertFalse(resp.success)
        self.assertIn("not started", resp.error)

    def test_is_alive(self):
        config = EngineConfig(engine="echo", agent_id="test_agent")
        self.adapter.start(config)
        self.assertTrue(self.adapter.is_alive("test_agent"))
        self.assertFalse(self.adapter.is_alive("unknown"))

    def test_stop(self):
        config = EngineConfig(engine="echo", agent_id="test_agent")
        self.adapter.start(config)
        self.assertTrue(self.adapter.stop("test_agent"))
        self.assertFalse(self.adapter.is_alive("test_agent"))

    def test_stop_unknown(self):
        self.assertFalse(self.adapter.stop("unknown"))

    def test_get_status(self):
        config = EngineConfig(engine="echo", agent_id="test_agent")
        self.adapter.start(config)
        self.assertEqual(self.adapter.get_status("test_agent"), EngineStatus.READY)

    def test_get_status_stopped(self):
        self.assertEqual(self.adapter.get_status("unknown"), EngineStatus.STOPPED)

    def test_capabilities(self):
        caps = self.adapter.capabilities()
        self.assertFalse(caps["interactive"])
        self.assertFalse(caps["mcp"])
        self.assertFalse(caps["streaming"])
        self.assertFalse(caps["session_resume"])

    def test_instruction_file(self):
        self.assertEqual(self.adapter.get_instruction_file(), "CLAUDE.md")

    def test_repr(self):
        r = repr(self.adapter)
        self.assertIn("EchoAdapter", r)
        self.assertIn("echo", r)

    def test_supports_methods(self):
        self.assertFalse(self.adapter.supports_interactive())
        self.assertFalse(self.adapter.supports_mcp())
        self.assertFalse(self.adapter.supports_streaming())
        self.assertFalse(self.adapter.supports_session_resume())


class TestEngineRegistry(unittest.TestCase):
    """Test engine registration and discovery."""

    def test_echo_registered(self):
        self.assertIn("echo", ENGINE_REGISTRY)

    def test_get_engine(self):
        adapter = get_engine("echo")
        self.assertIsInstance(adapter, EchoAdapter)

    def test_get_unknown_engine(self):
        with self.assertRaises(KeyError) as ctx:
            get_engine("nonexistent")
        self.assertIn("nonexistent", str(ctx.exception))

    def test_list_engines(self):
        engines = list_engines()
        self.assertGreater(len(engines), 0)
        echo = [e for e in engines if e["name"] == "echo"]
        self.assertEqual(len(echo), 1)
        self.assertEqual(echo[0]["engine_type"], "cli_subprocess")

    def test_register_custom_engine(self):
        class CustomAdapter(EngineAdapter):
            @property
            def engine_name(self) -> str:
                return "custom"

            @property
            def engine_type(self) -> EngineType:
                return EngineType.API_DIRECT

            def start(self, config: EngineConfig) -> bool:
                return True

            def send_prompt(self, agent_id: str, prompt: str,
                            system_prompt: str = "",
                            tools: list[dict[str, Any]] | None = None) -> EngineResponse:
                return EngineResponse(
                    success=True, engine="custom",
                    engine_type="api_direct", content=prompt,
                )

            def is_alive(self, agent_id: str) -> bool:
                return True

            def stop(self, agent_id: str) -> bool:
                return True

            def get_status(self, agent_id: str) -> EngineStatus:
                return EngineStatus.READY

        register_engine("custom_test", CustomAdapter)
        self.assertIn("custom_test", ENGINE_REGISTRY)

        adapter = get_engine("custom_test")
        self.assertEqual(adapter.engine_name, "custom")
        self.assertTrue(adapter.supports_mcp())
        self.assertTrue(adapter.supports_streaming())

        # Cleanup
        del ENGINE_REGISTRY["custom_test"]

    def test_register_invalid_class(self):
        with self.assertRaises(TypeError):
            register_engine("bad", str)  # type: ignore


class TestCustomAdapterCapabilities(unittest.TestCase):
    """Test capability detection for different engine types."""

    def _make_adapter(self, engine_type: EngineType) -> EngineAdapter:
        class TestAdapter(EngineAdapter):
            @property
            def engine_name(self) -> str:
                return "test"

            @property
            def engine_type(self) -> EngineType:
                return engine_type

            def start(self, config: EngineConfig) -> bool:
                return True

            def send_prompt(self, agent_id: str, prompt: str,
                            system_prompt: str = "",
                            tools: list[dict[str, Any]] | None = None) -> EngineResponse:
                return EngineResponse(
                    success=True, engine="test",
                    engine_type=engine_type.value, content="",
                )

            def is_alive(self, agent_id: str) -> bool:
                return True

            def stop(self, agent_id: str) -> bool:
                return True

            def get_status(self, agent_id: str) -> EngineStatus:
                return EngineStatus.READY

        return TestAdapter()

    def test_cli_interactive_capabilities(self):
        a = self._make_adapter(EngineType.CLI_INTERACTIVE)
        self.assertTrue(a.supports_interactive())
        self.assertTrue(a.supports_mcp())
        self.assertFalse(a.supports_streaming())
        self.assertTrue(a.supports_session_resume())

    def test_cli_subprocess_capabilities(self):
        a = self._make_adapter(EngineType.CLI_SUBPROCESS)
        self.assertFalse(a.supports_interactive())
        self.assertFalse(a.supports_mcp())
        self.assertFalse(a.supports_streaming())
        self.assertFalse(a.supports_session_resume())

    def test_api_direct_capabilities(self):
        a = self._make_adapter(EngineType.API_DIRECT)
        self.assertFalse(a.supports_interactive())
        self.assertTrue(a.supports_mcp())
        self.assertTrue(a.supports_streaming())
        self.assertFalse(a.supports_session_resume())

    def test_proxy_capabilities(self):
        a = self._make_adapter(EngineType.PROXY)
        self.assertFalse(a.supports_interactive())
        self.assertTrue(a.supports_mcp())
        self.assertTrue(a.supports_streaming())
        self.assertFalse(a.supports_session_resume())

    def test_web_automation_capabilities(self):
        a = self._make_adapter(EngineType.WEB_AUTOMATION)
        self.assertFalse(a.supports_interactive())
        self.assertFalse(a.supports_mcp())
        self.assertFalse(a.supports_streaming())
        self.assertFalse(a.supports_session_resume())


if __name__ == "__main__":
    unittest.main(verbosity=2)
