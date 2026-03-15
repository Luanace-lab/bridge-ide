"""
litellm_engine.py — LiteLLM Proxy Engine Adapter

Implements EngineAdapter for LiteLLM, a unified gateway that supports
100+ LLMs through a single interface. Uses OpenAI-compatible format
with provider-prefixed model names.

Architecture Reference: R5_Integration_Roadmap.md C4
Phase: C — Intelligence

Dependencies:
  - litellm (pip install litellm) — optional, checked at start()
  - engine_abc.py — EngineAdapter base class
  - tool_bridge.py — MCP → OpenAI tool format conversion (LiteLLM uses OpenAI format)

Design:
  - Uses LiteLLM's completion() for unified access
  - Provider-prefixed model names (e.g., "claude-3-opus", "gpt-4o")
  - Automatic cost tracking via LiteLLM's built-in cost calculation
  - Thread-safe per-agent state tracking
  - Works as self-hosted proxy or direct library
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
    import litellm as litellm_sdk  # type: ignore[import-untyped]

    HAS_LITELLM = True
except ImportError:
    litellm_sdk = None  # type: ignore[assignment]
    HAS_LITELLM = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gpt-4o"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7


# ---------------------------------------------------------------------------
# Agent Session State
# ---------------------------------------------------------------------------

class _AgentSession:
    """Per-agent session state for LiteLLM."""

    def __init__(self, config: EngineConfig):
        self.agent_id: str = config.agent_id
        self.model: str = config.model or DEFAULT_MODEL
        self.system_prompt: str = config.system_prompt
        self.max_tokens: int = config.max_tokens or DEFAULT_MAX_TOKENS
        self.temperature: float = config.temperature
        self.api_key: str = config.api_key
        self.api_base: str = config.extras.get("api_base", "")
        self.status: EngineStatus = EngineStatus.STARTING
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cost: float = 0.0
        self.request_count: int = 0


# ---------------------------------------------------------------------------
# LiteLLM Engine Adapter
# ---------------------------------------------------------------------------

class LiteLLMEngine(EngineAdapter):
    """LiteLLM proxy engine adapter.

    Provides unified access to 100+ LLMs through LiteLLM's
    OpenAI-compatible interface. Supports provider-prefixed
    model names and automatic cost tracking.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _AgentSession] = {}
        self._lock = threading.Lock()

    @property
    def engine_name(self) -> str:
        return "litellm"

    @property
    def engine_type(self) -> EngineType:
        return EngineType.PROXY

    def start(self, config: EngineConfig) -> bool:
        """Start LiteLLM engine for an agent.

        Args:
            config: Engine configuration. api_key is optional if
                    environment variables are set for the provider.

        Returns:
            True if started successfully.
        """
        if not HAS_LITELLM:
            return False

        with self._lock:
            session = _AgentSession(config)

            # Configure LiteLLM API base if provided
            if session.api_base:
                litellm_sdk.api_base = session.api_base

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
        """Send a prompt via LiteLLM and return response.

        Uses LiteLLM's completion() which routes to the appropriate
        provider based on the model name.

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

        session.status = EngineStatus.BUSY
        start_time = time.time()

        # Build messages
        messages: list[dict[str, Any]] = []
        sys_prompt = system_prompt or session.system_prompt
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.append({"role": "user", "content": prompt})

        # Convert MCP tools to OpenAI format (LiteLLM uses OpenAI format)
        openai_tools = mcp_to_openai(tools) if tools else None

        try:
            kwargs: dict[str, Any] = {
                "model": session.model,
                "messages": messages,
                "max_tokens": session.max_tokens,
                "temperature": session.temperature,
            }
            if session.api_key:
                kwargs["api_key"] = session.api_key
            if session.api_base:
                kwargs["api_base"] = session.api_base
            if openai_tools:
                kwargs["tools"] = openai_tools

            response = litellm_sdk.completion(**kwargs)

            # Extract response
            choice = response.choices[0]
            content = choice.message.content or ""

            # Extract tool calls (OpenAI format)
            tool_calls: list[dict[str, Any]] = []
            raw_calls = getattr(choice.message, "tool_calls", None) or []
            for tc in raw_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                })

            # Track tokens
            tokens = {"input": 0, "output": 0}
            if hasattr(response, "usage") and response.usage:
                tokens["input"] = getattr(response.usage, "prompt_tokens", 0) or 0
                tokens["output"] = getattr(response.usage, "completion_tokens", 0) or 0

            session.total_input_tokens += tokens["input"]
            session.total_output_tokens += tokens["output"]
            session.request_count += 1

            # LiteLLM tracks cost automatically
            cost = getattr(response, "_hidden_params", {}).get("response_cost", 0.0)
            if cost:
                session.total_cost += cost

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
                    "provider": _detect_provider(session.model),
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
            EngineStatus.STOPPED, EngineStatus.ERROR,
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
        """Get usage statistics for an agent session."""
        session = self._sessions.get(agent_id)
        if session is None:
            return None
        return {
            "model": session.model,
            "provider": _detect_provider(session.model),
            "total_input_tokens": session.total_input_tokens,
            "total_output_tokens": session.total_output_tokens,
            "total_cost_usd": round(session.total_cost, 6),
            "request_count": session.request_count,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_provider(model: str) -> str:
    """Detect the provider from a model name.

    LiteLLM uses provider-prefixed names in some cases.

    Args:
        model: Model identifier.

    Returns:
        Provider name string.
    """
    if "/" in model:
        return model.split("/")[0]

    model_lower = model.lower()
    if "claude" in model_lower:
        return "anthropic"
    if "gpt" in model_lower or "o1" in model_lower:
        return "openai"
    if "gemini" in model_lower:
        return "google"
    if "llama" in model_lower or "mixtral" in model_lower:
        return "meta/mistral"
    return "unknown"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

register_engine("litellm", LiteLLMEngine)
