"""
engine_abc.py — Abstract Base Class for Engine Adapters

Defines the unified interface that all engine types implement:
  - CLI-Interactive (tmux-based: Claude Code, Gemini CLI, Qwen CLI)
  - CLI-Subprocess (ephemeral: Codex)
  - API-Direct (native Python: Anthropic API, OpenAI, Gemini API)
  - Proxy (unified gateway: OpenRouter, LiteLLM)

Architecture Reference: R4_Architekturentwurf.md section 6
Research Reference: R5_Integration_Roadmap.md
Phase: C — Intelligence

Design Principles:
  - Single unified interface hiding four implementation patterns
  - Engine-specific logic isolated in adapters
  - Adding a new engine = 1 file + registry entry, zero refactor elsewhere
  - All engines return the same EngineResponse format
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EngineType(Enum):
    """Classification of engine implementation patterns."""

    CLI_INTERACTIVE = "cli_interactive"    # Persistent tmux sessions
    CLI_SUBPROCESS = "cli_subprocess"      # One-shot calls
    API_DIRECT = "api_direct"              # Native Python SDK calls
    PROXY = "proxy"                        # Unified gateway (OpenRouter, LiteLLM)
    WEB_AUTOMATION = "web_automation"      # Playwright-based (not recommended)


class EngineStatus(Enum):
    """Engine health status."""

    READY = "ready"
    BUSY = "busy"
    ERROR = "error"
    STOPPED = "stopped"
    STARTING = "starting"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class EngineResponse:
    """Unified response from any engine type.

    All engines return this format regardless of implementation.
    """

    success: bool
    engine: str                              # "claude", "gpt", "gemini", etc.
    engine_type: str                         # EngineType value string
    content: str                             # Final text answer
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    session_id: str | None = None            # For session-resume capability
    tokens_used: dict[str, int] | None = None  # {"input": N, "output": M}
    error: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "engine": self.engine,
            "engine_type": self.engine_type,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "session_id": self.session_id,
            "tokens_used": self.tokens_used,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


@dataclass
class EngineConfig:
    """Configuration for starting an engine.

    Common fields shared by all engine types. Engine-specific
    configuration goes in the extras dict.
    """

    engine: str                    # Engine name (registry key)
    agent_id: str                  # Agent identifier
    role: str = ""                 # Agent role description
    project_path: str = ""         # Working directory
    model: str = ""                # Model identifier (for API engines)
    api_key: str = ""              # API key (from credential_vault)
    system_prompt: str = ""        # System prompt / SOUL.md content
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: int = 4096
    temperature: float = 0.7
    streaming: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "engine": self.engine,
            "agent_id": self.agent_id,
            "role": self.role,
            "project_path": self.project_path,
            "model": self.model,
            "system_prompt": self.system_prompt[:50] + "..." if len(self.system_prompt) > 50 else self.system_prompt,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "streaming": self.streaming,
        }
        # Never expose api_key
        result["api_key"] = "***" if self.api_key else "(not set)"
        return result


# ---------------------------------------------------------------------------
# Instruction file mapping
# ---------------------------------------------------------------------------

INSTRUCTION_FILES: dict[str, str] = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
    "qwen": "QWEN.md",
    "anthropic_api": "CLAUDE.md",
    "openai_api": "AGENTS.md",
    "gemini_api": "GEMINI.md",
    "openrouter": "CLAUDE.md",
    "litellm": "CLAUDE.md",
    "echo": "CLAUDE.md",
}


# ---------------------------------------------------------------------------
# Abstract Base Class
# ---------------------------------------------------------------------------

class EngineAdapter(ABC):
    """Abstract base for all engine types.

    Every engine adapter must implement these methods.
    The Bridge platform interacts with engines exclusively
    through this interface.

    Adding a new engine:
      1. Create MyAdapter(EngineAdapter) in a new file
      2. Register: ENGINE_REGISTRY["my_engine"] = MyAdapter
      3. Add to INSTRUCTION_FILES if needed
      4. Done — no changes needed elsewhere
    """

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Unique engine identifier (e.g., 'claude', 'gpt', 'gemini')."""
        ...

    @property
    @abstractmethod
    def engine_type(self) -> EngineType:
        """Engine implementation type."""
        ...

    @abstractmethod
    def start(self, config: EngineConfig) -> bool:
        """Start the engine for an agent.

        For CLI-Interactive: creates tmux session, starts CLI.
        For API-Direct: initializes SDK client, validates API key.
        For Proxy: validates proxy URL, tests connectivity.

        Args:
            config: Engine configuration.

        Returns:
            True if started successfully.
        """
        ...

    @abstractmethod
    def send_prompt(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> EngineResponse:
        """Send a prompt and get a response.

        For CLI engines: injects prompt into tmux session, captures output.
        For API engines: sends messages to API, returns response.

        Args:
            agent_id: Target agent.
            prompt: User/system prompt to send.
            system_prompt: Override system prompt (optional).
            tools: Tool definitions (optional, for API engines).

        Returns:
            Unified EngineResponse.
        """
        ...

    @abstractmethod
    def is_alive(self, agent_id: str) -> bool:
        """Check if the engine is responsive for an agent.

        For CLI: checks if tmux session exists and process is running.
        For API: sends a lightweight health check.

        Args:
            agent_id: Agent to check.

        Returns:
            True if engine is responsive.
        """
        ...

    @abstractmethod
    def stop(self, agent_id: str) -> bool:
        """Stop the engine for an agent.

        For CLI: kills tmux session.
        For API: closes connection, cleans up.

        Args:
            agent_id: Agent to stop.

        Returns:
            True if stopped successfully.
        """
        ...

    @abstractmethod
    def get_status(self, agent_id: str) -> EngineStatus:
        """Get the current status of the engine for an agent.

        Returns:
            EngineStatus enum value.
        """
        ...

    def get_instruction_file(self) -> str:
        """Return the instruction filename for this engine.

        CLI engines embed instructions in files (CLAUDE.md, AGENTS.md).
        API engines inject as system_prompt.
        """
        return INSTRUCTION_FILES.get(self.engine_name, "CLAUDE.md")

    def supports_interactive(self) -> bool:
        """Whether this engine supports persistent interactive sessions."""
        return self.engine_type == EngineType.CLI_INTERACTIVE

    def supports_mcp(self) -> bool:
        """Whether this engine supports MCP tool servers."""
        return self.engine_type in (
            EngineType.CLI_INTERACTIVE,
            EngineType.API_DIRECT,
            EngineType.PROXY,
        )

    def supports_streaming(self) -> bool:
        """Whether this engine supports response streaming."""
        return self.engine_type in (
            EngineType.API_DIRECT,
            EngineType.PROXY,
        )

    def supports_session_resume(self) -> bool:
        """Whether this engine supports session resume."""
        return self.engine_type == EngineType.CLI_INTERACTIVE

    def capabilities(self) -> dict[str, bool]:
        """Return a dict of all engine capabilities."""
        return {
            "interactive": self.supports_interactive(),
            "mcp": self.supports_mcp(),
            "streaming": self.supports_streaming(),
            "session_resume": self.supports_session_resume(),
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} engine={self.engine_name} type={self.engine_type.value}>"


# ---------------------------------------------------------------------------
# Echo Adapter (Test/Reference Implementation)
# ---------------------------------------------------------------------------

class EchoAdapter(EngineAdapter):
    """Test adapter that echoes back the prompt.

    Used for testing, development, and as a reference implementation.
    Does not require any external service.
    """

    def __init__(self) -> None:
        self._agents: dict[str, EngineStatus] = {}

    @property
    def engine_name(self) -> str:
        return "echo"

    @property
    def engine_type(self) -> EngineType:
        return EngineType.CLI_SUBPROCESS

    def start(self, config: EngineConfig) -> bool:
        self._agents[config.agent_id] = EngineStatus.READY
        return True

    def send_prompt(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> EngineResponse:
        if agent_id not in self._agents:
            return EngineResponse(
                success=False,
                engine=self.engine_name,
                engine_type=self.engine_type.value,
                content="",
                error=f"Agent {agent_id} not started",
            )

        self._agents[agent_id] = EngineStatus.BUSY
        content = f"[echo] {prompt}"
        self._agents[agent_id] = EngineStatus.READY

        return EngineResponse(
            success=True,
            engine=self.engine_name,
            engine_type=self.engine_type.value,
            content=content,
            tokens_used={"input": len(prompt.split()), "output": len(content.split())},
        )

    def is_alive(self, agent_id: str) -> bool:
        return agent_id in self._agents and self._agents[agent_id] != EngineStatus.STOPPED

    def stop(self, agent_id: str) -> bool:
        if agent_id in self._agents:
            self._agents[agent_id] = EngineStatus.STOPPED
            return True
        return False

    def get_status(self, agent_id: str) -> EngineStatus:
        return self._agents.get(agent_id, EngineStatus.STOPPED)


# ---------------------------------------------------------------------------
# Codex Adapter (CLI-Interactive, tmux-based)
# ---------------------------------------------------------------------------

class CodexEngineAdapter(EngineAdapter):
    """Codex CLI engine adapter — persistent tmux sessions.

    Engine type: CLI_INTERACTIVE (same lifecycle as Claude).
    Delegates session management to tmux_manager.
    Supports session resume (via thread_id) and MCP (via config.toml).
    """

    def __init__(self) -> None:
        self._agents: dict[str, EngineStatus] = {}

    @property
    def engine_name(self) -> str:
        return "codex"

    @property
    def engine_type(self) -> EngineType:
        return EngineType.CLI_INTERACTIVE

    def start(self, config: EngineConfig) -> bool:
        from tmux_manager import create_agent_session
        success = create_agent_session(
            agent_id=config.agent_id,
            role=config.role,
            project_path=config.project_path,
            team_members=config.extras.get("team_members", []),
            engine="codex",
        )
        if success:
            self._agents[config.agent_id] = EngineStatus.READY
        return success

    def send_prompt(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> EngineResponse:
        from tmux_manager import send_to_session
        if agent_id not in self._agents:
            return EngineResponse(
                success=False,
                engine=self.engine_name,
                engine_type=self.engine_type.value,
                content="",
                error=f"Agent {agent_id} not started via CodexEngineAdapter",
            )
        self._agents[agent_id] = EngineStatus.BUSY
        ok = send_to_session(agent_id, prompt)
        # send_to_session injects into tmux — response comes via MCP, not return value.
        self._agents[agent_id] = EngineStatus.READY
        return EngineResponse(
            success=ok,
            engine=self.engine_name,
            engine_type=self.engine_type.value,
            content="(prompt injected into tmux session)" if ok else "(injection failed)",
            error=None if ok else "tmux send-keys failed",
        )

    def is_alive(self, agent_id: str) -> bool:
        from tmux_manager import is_session_alive
        return is_session_alive(agent_id)

    def stop(self, agent_id: str) -> bool:
        from tmux_manager import kill_agent_session
        ok = kill_agent_session(agent_id)
        if ok:
            self._agents[agent_id] = EngineStatus.STOPPED
        return ok

    def get_status(self, agent_id: str) -> EngineStatus:
        from tmux_manager import is_session_alive
        if agent_id in self._agents:
            if self._agents[agent_id] == EngineStatus.STOPPED:
                return EngineStatus.STOPPED
            if not is_session_alive(agent_id):
                self._agents[agent_id] = EngineStatus.ERROR
                return EngineStatus.ERROR
            return self._agents[agent_id]
        # Not tracked by this adapter — check tmux directly
        if is_session_alive(agent_id):
            return EngineStatus.READY
        return EngineStatus.STOPPED

    def supports_session_resume(self) -> bool:
        return True

    def supports_mcp(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Engine Registry
# ---------------------------------------------------------------------------

ENGINE_REGISTRY: dict[str, type[EngineAdapter]] = {
    "echo": EchoAdapter,
    "codex": CodexEngineAdapter,
}


def register_engine(name: str, adapter_class: type[EngineAdapter]) -> None:
    """Register a new engine adapter.

    Args:
        name: Engine name (used as registry key).
        adapter_class: EngineAdapter subclass.
    """
    if not issubclass(adapter_class, EngineAdapter):
        raise TypeError(f"{adapter_class} is not a subclass of EngineAdapter")
    ENGINE_REGISTRY[name] = adapter_class


def get_engine(name: str) -> EngineAdapter:
    """Create an engine adapter instance by name.

    Args:
        name: Registered engine name.

    Returns:
        Instantiated EngineAdapter.

    Raises:
        KeyError: If engine name is not registered.
    """
    if name not in ENGINE_REGISTRY:
        available = ", ".join(sorted(ENGINE_REGISTRY.keys()))
        raise KeyError(f"Engine '{name}' not registered. Available: {available}")
    return ENGINE_REGISTRY[name]()


def list_engines() -> list[dict[str, Any]]:
    """List all registered engines with their capabilities.

    Returns:
        List of engine info dicts.
    """
    result = []
    for name, cls in sorted(ENGINE_REGISTRY.items()):
        adapter = cls()
        result.append({
            "name": name,
            "engine_name": adapter.engine_name,
            "engine_type": adapter.engine_type.value,
            "instruction_file": adapter.get_instruction_file(),
            "capabilities": adapter.capabilities(),
        })
    return result
