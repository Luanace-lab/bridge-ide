"""
openai_engine.py — OpenAI API Engine Adapter

Implements EngineAdapter for OpenAI's API (GPT-4o, GPT-4o-mini, etc.).
Supports tool/function calling, streaming, and token tracking.

Architecture Reference: R5_Integration_Roadmap.md C2
Phase: C — Intelligence

Dependencies:
  - openai (pip install openai) — optional, checked at start()
  - engine_abc.py — EngineAdapter base class
  - tool_bridge.py — MCP → OpenAI tool format conversion

Design:
  - Graceful degradation when openai SDK not installed
  - Tracks tokens and cost per request
  - Converts tools from MCP format automatically
  - Thread-safe per-agent state tracking
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from engine_abc import (
    EngineAdapter,
    EngineConfig,
    EngineResponse,
    EngineStatus,
    EngineType,
    register_engine,
)
from tool_bridge import mcp_to_openai

# Optional SDK import
try:
    import openai as openai_sdk

    HAS_OPENAI = True
except ImportError:
    openai_sdk = None  # type: ignore[assignment]
    HAS_OPENAI = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gpt-4o"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7

# Model pricing (USD per 1M tokens)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "o1": {"input": 15.0, "output": 60.0},
    "o1-mini": {"input": 3.0, "output": 12.0},
}


# ---------------------------------------------------------------------------
# Agent Session State
# ---------------------------------------------------------------------------

class _AgentSession:
    """Per-agent session state."""

    def __init__(self, config: EngineConfig):
        self.agent_id: str = config.agent_id
        self.model: str = config.model or DEFAULT_MODEL
        self.system_prompt: str = config.system_prompt
        self.max_tokens: int = config.max_tokens or DEFAULT_MAX_TOKENS
        self.temperature: float = config.temperature
        self.status: EngineStatus = EngineStatus.STARTING
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.request_count: int = 0


# ---------------------------------------------------------------------------
# OpenAI Engine Adapter
# ---------------------------------------------------------------------------

class OpenAIEngine(EngineAdapter):
    """OpenAI API engine adapter.

    Supports GPT-4o, GPT-4o-mini, and other OpenAI models.
    Handles function/tool calling with MCP tool conversion.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _AgentSession] = {}
        self._client: Any = None
        self._api_key: str = ""
        self._lock = threading.Lock()

    @property
    def engine_name(self) -> str:
        return "openai_api"

    @property
    def engine_type(self) -> EngineType:
        return EngineType.API_DIRECT

    def start(self, config: EngineConfig) -> bool:
        """Start OpenAI engine for an agent.

        Creates SDK client and validates API key.

        Args:
            config: Engine configuration with api_key and model.

        Returns:
            True if started successfully.
        """
        if not HAS_OPENAI:
            return False

        api_key = config.api_key or config.extras.get("api_key", "")
        if not api_key:
            return False

        with self._lock:
            if self._client is None or api_key != self._api_key:
                self._api_key = api_key
                self._client = openai_sdk.OpenAI(api_key=api_key)

            session = _AgentSession(config)
            session.status = EngineStatus.READY
            self._sessions[config.agent_id] = session

        return True

    def send_prompt(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> EngineResponse:
        """Send a prompt to OpenAI API and return response.

        Handles tool/function calling loop automatically.

        Args:
            agent_id: Target agent.
            prompt: User prompt text.
            system_prompt: Override system prompt (optional).
            tools: MCP tool definitions (auto-converted to OpenAI format).

        Returns:
            Unified EngineResponse.
        """
        session = self._sessions.get(agent_id)
        if session is None:
            return EngineResponse(
                success=False,
                engine=self.engine_name,
                engine_type=self.engine_type.value,
                content="",
                error=f"Agent {agent_id} not started",
            )

        if self._client is None:
            return EngineResponse(
                success=False,
                engine=self.engine_name,
                engine_type=self.engine_type.value,
                content="",
                error="OpenAI client not initialized",
            )

        session.status = EngineStatus.BUSY
        start_time = time.time()

        # Build messages
        messages: list[dict[str, Any]] = []
        sys_prompt = system_prompt or session.system_prompt
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.append({"role": "user", "content": prompt})

        # Convert MCP tools to OpenAI format
        openai_tools = mcp_to_openai(tools) if tools else None

        try:
            kwargs: dict[str, Any] = {
                "model": session.model,
                "messages": messages,
                "max_tokens": session.max_tokens,
                "temperature": session.temperature,
            }
            if openai_tools:
                kwargs["tools"] = openai_tools

            response = self._client.chat.completions.create(**kwargs)

            # Extract response
            choice = response.choices[0]
            content = choice.message.content or ""
            tool_calls_raw = choice.message.tool_calls or []

            # Convert tool calls to MCP format
            tool_calls = []
            for tc in tool_calls_raw:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                })

            # Track tokens
            tokens = {
                "input": response.usage.prompt_tokens if response.usage else 0,
                "output": response.usage.completion_tokens if response.usage else 0,
            }
            session.total_input_tokens += tokens["input"]
            session.total_output_tokens += tokens["output"]
            session.request_count += 1

            duration_ms = int((time.time() - start_time) * 1000)
            session.status = EngineStatus.READY

            return EngineResponse(
                success=True,
                engine=self.engine_name,
                engine_type=self.engine_type.value,
                content=content,
                tool_calls=tool_calls,
                tokens_used=tokens,
                duration_ms=duration_ms,
                metadata={
                    "model": session.model,
                    "finish_reason": choice.finish_reason,
                },
            )

        except Exception as e:
            session.status = EngineStatus.ERROR
            duration_ms = int((time.time() - start_time) * 1000)
            return EngineResponse(
                success=False,
                engine=self.engine_name,
                engine_type=self.engine_type.value,
                content="",
                error=str(e),
                duration_ms=duration_ms,
            )

    def is_alive(self, agent_id: str) -> bool:
        """Check if agent session is active."""
        session = self._sessions.get(agent_id)
        return session is not None and session.status not in (
            EngineStatus.STOPPED, EngineStatus.ERROR
        )

    def stop(self, agent_id: str) -> bool:
        """Stop the engine for an agent."""
        with self._lock:
            session = self._sessions.get(agent_id)
            if session is None:
                return False
            session.status = EngineStatus.STOPPED
            return True

    def get_status(self, agent_id: str) -> EngineStatus:
        """Get engine status for an agent."""
        session = self._sessions.get(agent_id)
        return session.status if session else EngineStatus.STOPPED

    def get_session_stats(self, agent_id: str) -> dict[str, Any] | None:
        """Get usage statistics for an agent session.

        Returns:
            Dict with token counts and request count, or None.
        """
        session = self._sessions.get(agent_id)
        if session is None:
            return None
        return {
            "model": session.model,
            "total_input_tokens": session.total_input_tokens,
            "total_output_tokens": session.total_output_tokens,
            "request_count": session.request_count,
            "estimated_cost_usd": self._estimate_cost(session),
        }

    def _estimate_cost(self, session: _AgentSession) -> float:
        """Estimate USD cost based on token usage."""
        pricing = MODEL_PRICING.get(session.model)
        if pricing is None:
            return 0.0
        input_cost = session.total_input_tokens * pricing["input"] / 1_000_000
        output_cost = session.total_output_tokens * pricing["output"] / 1_000_000
        return round(input_cost + output_cost, 6)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

register_engine("openai_api", OpenAIEngine)
