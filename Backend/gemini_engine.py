"""
gemini_engine.py — Google Gemini API Engine Adapter

Implements EngineAdapter for Google's Gemini API (gemini-2.0-flash,
gemini-2.0-pro, etc.). Supports function calling and token tracking.

Architecture Reference: R5_Integration_Roadmap.md C3
Phase: C — Intelligence

Dependencies:
  - google-genai (pip install google-genai) — optional, checked at start()
  - engine_abc.py — EngineAdapter base class
  - tool_bridge.py — MCP → Gemini tool format conversion

Design:
  - Graceful degradation when SDK not installed
  - Handles Gemini's unique function calling format
  - Thread-safe per-agent state tracking
  - Token and cost tracking
"""

from __future__ import annotations

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
from tool_bridge import mcp_to_gemini

# Optional SDK import
try:
    import google.generativeai as genai_sdk  # type: ignore[import-untyped]

    HAS_GEMINI = True
except ImportError:
    genai_sdk = None  # type: ignore[assignment]
    HAS_GEMINI = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gemini-2.0-flash"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7

# Model pricing (USD per 1M tokens)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-pro": {"input": 1.25, "output": 5.0},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.0},
}


# ---------------------------------------------------------------------------
# Agent Session State
# ---------------------------------------------------------------------------

class _AgentSession:
    """Per-agent session state for Gemini."""

    def __init__(self, config: EngineConfig):
        self.agent_id: str = config.agent_id
        self.model_name: str = config.model or DEFAULT_MODEL
        self.system_prompt: str = config.system_prompt
        self.max_tokens: int = config.max_tokens or DEFAULT_MAX_TOKENS
        self.temperature: float = config.temperature
        self.status: EngineStatus = EngineStatus.STARTING
        self.model: Any = None  # genai GenerativeModel instance
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.request_count: int = 0


# ---------------------------------------------------------------------------
# Gemini Engine Adapter
# ---------------------------------------------------------------------------

class GeminiEngine(EngineAdapter):
    """Google Gemini API engine adapter.

    Supports Gemini 2.0 Flash, Pro, and older 1.5 models.
    Handles function calling with MCP tool conversion.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _AgentSession] = {}
        self._configured: bool = False
        self._lock = threading.Lock()

    @property
    def engine_name(self) -> str:
        return "gemini_api"

    @property
    def engine_type(self) -> EngineType:
        return EngineType.API_DIRECT

    def start(self, config: EngineConfig) -> bool:
        """Start Gemini engine for an agent.

        Configures SDK with API key and creates model instance.

        Args:
            config: Engine configuration with api_key and model.

        Returns:
            True if started successfully.
        """
        if not HAS_GEMINI:
            return False

        api_key = config.api_key or config.extras.get("api_key", "")
        if not api_key:
            return False

        with self._lock:
            if not self._configured:
                genai_sdk.configure(api_key=api_key)
                self._configured = True

            session = _AgentSession(config)

            try:
                # Create model with system instruction
                generation_config = {
                    "max_output_tokens": session.max_tokens,
                    "temperature": session.temperature,
                }
                model_kwargs: dict[str, Any] = {
                    "model_name": session.model_name,
                    "generation_config": generation_config,
                }
                if session.system_prompt:
                    model_kwargs["system_instruction"] = session.system_prompt

                session.model = genai_sdk.GenerativeModel(**model_kwargs)
                session.status = EngineStatus.READY
            except Exception:
                session.status = EngineStatus.ERROR
                self._sessions[config.agent_id] = session
                return False

            self._sessions[config.agent_id] = session

        return True

    def send_prompt(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> EngineResponse:
        """Send a prompt to Gemini API and return response.

        Args:
            agent_id: Target agent.
            prompt: User prompt text.
            system_prompt: Override system prompt (optional).
            tools: MCP tool definitions (auto-converted to Gemini format).

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

        if session.model is None:
            return EngineResponse(
                success=False,
                engine=self.engine_name,
                engine_type=self.engine_type.value,
                content="",
                error="Gemini model not initialized",
            )

        session.status = EngineStatus.BUSY
        start_time = time.time()

        try:
            # Build generation kwargs
            kwargs: dict[str, Any] = {}

            # Convert MCP tools to Gemini format
            if tools:
                gemini_tools = mcp_to_gemini(tools)
                kwargs["tools"] = gemini_tools

            response = session.model.generate_content(prompt, **kwargs)

            # Extract text content
            content = ""
            tool_calls: list[dict[str, Any]] = []

            if response.candidates:
                candidate = response.candidates[0]
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        content += part.text
                    elif hasattr(part, "function_call"):
                        fc = part.function_call
                        tool_calls.append({
                            "id": f"gemini_{fc.name}",
                            "name": fc.name,
                            "arguments": dict(fc.args) if fc.args else {},
                        })

            # Track tokens from usage metadata
            tokens = {"input": 0, "output": 0}
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                um = response.usage_metadata
                tokens["input"] = getattr(um, "prompt_token_count", 0) or 0
                tokens["output"] = getattr(um, "candidates_token_count", 0) or 0

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
                metadata={"model": session.model_name},
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
            session.model = None
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
            "model": session.model_name,
            "total_input_tokens": session.total_input_tokens,
            "total_output_tokens": session.total_output_tokens,
            "request_count": session.request_count,
            "estimated_cost_usd": self._estimate_cost(session),
        }

    def _estimate_cost(self, session: _AgentSession) -> float:
        """Estimate USD cost based on token usage."""
        pricing = MODEL_PRICING.get(session.model_name)
        if pricing is None:
            return 0.0
        input_cost = session.total_input_tokens * pricing["input"] / 1_000_000
        output_cost = session.total_output_tokens * pricing["output"] / 1_000_000
        return round(input_cost + output_cost, 6)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

register_engine("gemini_api", GeminiEngine)
