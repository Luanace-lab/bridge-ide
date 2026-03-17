"""
engine_backend.py — Dual CLI+API Backend Abstraction for Bridge ACE

Defines the EngineBackend Protocol and provides two implementations:
- TmuxBackend: Wraps existing CLI tools via tmux (claude, codex, qwen, gemini)
- ApiBackend: Direct API calls without tmux (Anthropic, OpenAI, Google, Alibaba)

Architecture Reference: docs/API_SUPPORT_ANALYSIS.md
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Engine Backend Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class EngineBackend(Protocol):
    """Abstract interface for agent engine backends."""

    async def start(self, agent_id: str, config: dict[str, Any]) -> bool:
        """Start an agent session. Returns True on success."""
        ...

    async def send(self, agent_id: str, message: str) -> str:
        """Send a message to the agent and return the response."""
        ...

    async def stop(self, agent_id: str) -> bool:
        """Stop an agent session. Returns True on success."""
        ...

    def is_alive(self, agent_id: str) -> bool:
        """Check if agent session is active."""
        ...

    def get_engine_name(self) -> str:
        """Return the engine identifier (e.g., 'claude', 'openai')."""
        ...


# ---------------------------------------------------------------------------
# API Key Configuration
# ---------------------------------------------------------------------------

@dataclass
class ApiKeyConfig:
    """Stores API keys for various providers."""
    anthropic: str = ""
    openai: str = ""
    google: str = ""
    alibaba: str = ""
    xai: str = ""

    @classmethod
    def from_env(cls) -> "ApiKeyConfig":
        """Load API keys from environment variables."""
        return cls(
            anthropic=os.environ.get("ANTHROPIC_API_KEY", ""),
            openai=os.environ.get("OPENAI_API_KEY", ""),
            google=os.environ.get("GOOGLE_AI_API_KEY", os.environ.get("GEMINI_API_KEY", "")),
            alibaba=os.environ.get("DASHSCOPE_API_KEY", os.environ.get("ALIBABA_API_KEY", "")),
            xai=os.environ.get("XAI_API_KEY", os.environ.get("GROK_API_KEY", "")),
        )

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> "ApiKeyConfig":
        """Load API keys from a dictionary (e.g., from UI input)."""
        return cls(
            anthropic=d.get("anthropic", d.get("ANTHROPIC_API_KEY", "")),
            openai=d.get("openai", d.get("OPENAI_API_KEY", "")),
            google=d.get("google", d.get("GOOGLE_AI_API_KEY", "")),
            alibaba=d.get("alibaba", d.get("DASHSCOPE_API_KEY", "")),
            xai=d.get("xai", d.get("XAI_API_KEY", "")),
        )

    def get_key(self, provider: str) -> str:
        """Get API key for a provider."""
        mapping = {
            "anthropic": self.anthropic, "claude": self.anthropic,
            "openai": self.openai, "codex": self.openai, "gpt": self.openai,
            "google": self.google, "gemini": self.google,
            "alibaba": self.alibaba, "qwen": self.alibaba, "dashscope": self.alibaba,
            "xai": self.xai, "grok": self.xai,
        }
        return mapping.get(provider.lower(), "")

    def available_providers(self) -> list[str]:
        """Return list of providers with configured API keys."""
        providers = []
        if self.anthropic: providers.append("anthropic")
        if self.openai: providers.append("openai")
        if self.google: providers.append("google")
        if self.alibaba: providers.append("alibaba")
        if self.xai: providers.append("xai")
        return providers


# ---------------------------------------------------------------------------
# Agent Session State
# ---------------------------------------------------------------------------

@dataclass
class ApiAgentSession:
    """Tracks state for an API-backed agent."""
    agent_id: str
    provider: str
    model: str
    system_prompt: str = ""
    messages: list[dict[str, str]] = field(default_factory=list)
    started_at: float = 0.0
    last_activity: float = 0.0
    total_tokens: int = 0
    alive: bool = False


# ---------------------------------------------------------------------------
# Claude API Backend (Anthropic)
# ---------------------------------------------------------------------------

class ClaudeApiBackend:
    """Direct Anthropic Messages API backend — no tmux required."""

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-6"):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._sessions: dict[str, ApiAgentSession] = {}

    async def start(self, agent_id: str, config: dict[str, Any]) -> bool:
        if not self._api_key:
            print(f"[api-backend] ERROR: No Anthropic API key for {agent_id}")
            return False
        session = ApiAgentSession(
            agent_id=agent_id,
            provider="anthropic",
            model=config.get("model", self._model),
            system_prompt=config.get("system_prompt", ""),
            started_at=time.time(),
            last_activity=time.time(),
            alive=True,
        )
        self._sessions[agent_id] = session
        print(f"[api-backend] Started Claude API session for {agent_id} (model={session.model})")
        return True

    async def send(self, agent_id: str, message: str) -> str:
        session = self._sessions.get(agent_id)
        if not session or not session.alive:
            return json.dumps({"error": f"No active session for {agent_id}"})

        session.messages.append({"role": "user", "content": message})
        session.last_activity = time.time()

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)
            response = client.messages.create(
                model=session.model,
                max_tokens=4096,
                system=session.system_prompt,
                messages=session.messages,
            )
            assistant_text = response.content[0].text if response.content else ""
            session.messages.append({"role": "assistant", "content": assistant_text})
            session.total_tokens += (response.usage.input_tokens + response.usage.output_tokens)
            return assistant_text
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def stop(self, agent_id: str) -> bool:
        session = self._sessions.pop(agent_id, None)
        if session:
            session.alive = False
            print(f"[api-backend] Stopped Claude API session for {agent_id} ({session.total_tokens} tokens)")
            return True
        return False

    def is_alive(self, agent_id: str) -> bool:
        session = self._sessions.get(agent_id)
        return bool(session and session.alive)

    def get_engine_name(self) -> str:
        return "claude-api"


# ---------------------------------------------------------------------------
# OpenAI API Backend (GPT/Codex)
# ---------------------------------------------------------------------------

class OpenAiApiBackend:
    """Direct OpenAI Chat Completions API backend."""

    def __init__(self, api_key: str = "", model: str = "gpt-4o"):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._sessions: dict[str, ApiAgentSession] = {}

    async def start(self, agent_id: str, config: dict[str, Any]) -> bool:
        if not self._api_key:
            print(f"[api-backend] ERROR: No OpenAI API key for {agent_id}")
            return False
        session = ApiAgentSession(
            agent_id=agent_id,
            provider="openai",
            model=config.get("model", self._model),
            system_prompt=config.get("system_prompt", ""),
            started_at=time.time(),
            last_activity=time.time(),
            alive=True,
        )
        self._sessions[agent_id] = session
        print(f"[api-backend] Started OpenAI API session for {agent_id} (model={session.model})")
        return True

    async def send(self, agent_id: str, message: str) -> str:
        session = self._sessions.get(agent_id)
        if not session or not session.alive:
            return json.dumps({"error": f"No active session for {agent_id}"})

        session.messages.append({"role": "user", "content": message})
        session.last_activity = time.time()

        try:
            import openai
            client = openai.OpenAI(api_key=self._api_key)
            messages = []
            if session.system_prompt:
                messages.append({"role": "system", "content": session.system_prompt})
            messages.extend(session.messages)
            response = client.chat.completions.create(
                model=session.model,
                messages=messages,
                max_tokens=4096,
            )
            assistant_text = response.choices[0].message.content or ""
            session.messages.append({"role": "assistant", "content": assistant_text})
            if response.usage:
                session.total_tokens += response.usage.total_tokens
            return assistant_text
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def stop(self, agent_id: str) -> bool:
        session = self._sessions.pop(agent_id, None)
        if session:
            session.alive = False
            print(f"[api-backend] Stopped OpenAI API session for {agent_id} ({session.total_tokens} tokens)")
            return True
        return False

    def is_alive(self, agent_id: str) -> bool:
        session = self._sessions.get(agent_id)
        return bool(session and session.alive)

    def get_engine_name(self) -> str:
        return "openai-api"


# ---------------------------------------------------------------------------
# Google AI API Backend (Gemini)
# ---------------------------------------------------------------------------

class GoogleAiApiBackend:
    """Direct Google AI (Gemini) API backend."""

    def __init__(self, api_key: str = "", model: str = "gemini-2.5-flash"):
        self._api_key = api_key or os.environ.get("GOOGLE_AI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
        self._model = model
        self._sessions: dict[str, ApiAgentSession] = {}

    async def start(self, agent_id: str, config: dict[str, Any]) -> bool:
        if not self._api_key:
            print(f"[api-backend] ERROR: No Google AI API key for {agent_id}")
            return False
        session = ApiAgentSession(
            agent_id=agent_id,
            provider="google",
            model=config.get("model", self._model),
            system_prompt=config.get("system_prompt", ""),
            started_at=time.time(),
            last_activity=time.time(),
            alive=True,
        )
        self._sessions[agent_id] = session
        print(f"[api-backend] Started Google AI session for {agent_id} (model={session.model})")
        return True

    async def send(self, agent_id: str, message: str) -> str:
        session = self._sessions.get(agent_id)
        if not session or not session.alive:
            return json.dumps({"error": f"No active session for {agent_id}"})

        session.messages.append({"role": "user", "content": message})
        session.last_activity = time.time()

        try:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            model = genai.GenerativeModel(
                model_name=session.model,
                system_instruction=session.system_prompt or None,
            )
            # Convert message history to Gemini format
            history = []
            for msg in session.messages[:-1]:
                role = "model" if msg["role"] == "assistant" else "user"
                history.append({"role": role, "parts": [msg["content"]]})
            chat = model.start_chat(history=history)
            response = chat.send_message(message)
            assistant_text = response.text or ""
            session.messages.append({"role": "assistant", "content": assistant_text})
            return assistant_text
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def stop(self, agent_id: str) -> bool:
        session = self._sessions.pop(agent_id, None)
        if session:
            session.alive = False
            print(f"[api-backend] Stopped Google AI session for {agent_id}")
            return True
        return False

    def is_alive(self, agent_id: str) -> bool:
        session = self._sessions.get(agent_id)
        return bool(session and session.alive)

    def get_engine_name(self) -> str:
        return "gemini-api"


# ---------------------------------------------------------------------------
# xAI/Grok API Backend (OpenAI-compatible)
# ---------------------------------------------------------------------------

class XaiApiBackend:
    """xAI/Grok API backend — uses OpenAI-compatible endpoint."""

    def __init__(self, api_key: str = "", model: str = "grok-3"):
        self._api_key = api_key or os.environ.get("XAI_API_KEY", os.environ.get("GROK_API_KEY", ""))
        self._model = model
        self._sessions: dict[str, ApiAgentSession] = {}
        self._base_url = "https://api.x.ai/v1"

    async def start(self, agent_id: str, config: dict[str, Any]) -> bool:
        if not self._api_key:
            print(f"[api-backend] ERROR: No xAI API key for {agent_id}")
            return False
        session = ApiAgentSession(
            agent_id=agent_id,
            provider="xai",
            model=config.get("model", self._model),
            system_prompt=config.get("system_prompt", ""),
            started_at=time.time(),
            last_activity=time.time(),
            alive=True,
        )
        self._sessions[agent_id] = session
        print(f"[api-backend] Started xAI session for {agent_id} (model={session.model})")
        return True

    async def send(self, agent_id: str, message: str) -> str:
        session = self._sessions.get(agent_id)
        if not session or not session.alive:
            return json.dumps({"error": f"No active session for {agent_id}"})

        session.messages.append({"role": "user", "content": message})
        session.last_activity = time.time()

        try:
            import openai
            client = openai.OpenAI(api_key=self._api_key, base_url=self._base_url)
            messages = []
            if session.system_prompt:
                messages.append({"role": "system", "content": session.system_prompt})
            messages.extend(session.messages)
            response = client.chat.completions.create(
                model=session.model,
                messages=messages,
                max_tokens=4096,
            )
            assistant_text = response.choices[0].message.content or ""
            session.messages.append({"role": "assistant", "content": assistant_text})
            if response.usage:
                session.total_tokens += response.usage.total_tokens
            return assistant_text
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def stop(self, agent_id: str) -> bool:
        session = self._sessions.pop(agent_id, None)
        if session:
            session.alive = False
            print(f"[api-backend] Stopped xAI session for {agent_id} ({session.total_tokens} tokens)")
            return True
        return False

    def is_alive(self, agent_id: str) -> bool:
        session = self._sessions.get(agent_id)
        return bool(session and session.alive)

    def get_engine_name(self) -> str:
        return "xai-api"


# ---------------------------------------------------------------------------
# Alibaba/Qwen API Backend (DashScope)
# ---------------------------------------------------------------------------

class QwenApiBackend:
    """Alibaba DashScope API backend for Qwen models — OpenAI-compatible."""

    def __init__(self, api_key: str = "", model: str = "qwen-max"):
        self._api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", os.environ.get("ALIBABA_API_KEY", ""))
        self._model = model
        self._sessions: dict[str, ApiAgentSession] = {}
        self._base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    async def start(self, agent_id: str, config: dict[str, Any]) -> bool:
        if not self._api_key:
            print(f"[api-backend] ERROR: No DashScope API key for {agent_id}")
            return False
        session = ApiAgentSession(
            agent_id=agent_id,
            provider="alibaba",
            model=config.get("model", self._model),
            system_prompt=config.get("system_prompt", ""),
            started_at=time.time(),
            last_activity=time.time(),
            alive=True,
        )
        self._sessions[agent_id] = session
        print(f"[api-backend] Started Qwen/DashScope session for {agent_id} (model={session.model})")
        return True

    async def send(self, agent_id: str, message: str) -> str:
        session = self._sessions.get(agent_id)
        if not session or not session.alive:
            return json.dumps({"error": f"No active session for {agent_id}"})

        session.messages.append({"role": "user", "content": message})
        session.last_activity = time.time()

        try:
            import openai
            client = openai.OpenAI(api_key=self._api_key, base_url=self._base_url)
            messages = []
            if session.system_prompt:
                messages.append({"role": "system", "content": session.system_prompt})
            messages.extend(session.messages)
            response = client.chat.completions.create(
                model=session.model,
                messages=messages,
                max_tokens=4096,
            )
            assistant_text = response.choices[0].message.content or ""
            session.messages.append({"role": "assistant", "content": assistant_text})
            if response.usage:
                session.total_tokens += response.usage.total_tokens
            return assistant_text
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def stop(self, agent_id: str) -> bool:
        session = self._sessions.pop(agent_id, None)
        if session:
            session.alive = False
            print(f"[api-backend] Stopped Qwen session for {agent_id} ({session.total_tokens} tokens)")
            return True
        return False

    def is_alive(self, agent_id: str) -> bool:
        session = self._sessions.get(agent_id)
        return bool(session and session.alive)

    def get_engine_name(self) -> str:
        return "qwen-api"


# ---------------------------------------------------------------------------
# Backend Registry
# ---------------------------------------------------------------------------

_BACKENDS: dict[str, EngineBackend] = {}


def register_backend(name: str, backend: EngineBackend) -> None:
    """Register an engine backend by name."""
    _BACKENDS[name] = backend


def get_backend(name: str) -> EngineBackend | None:
    """Get a registered backend by name."""
    return _BACKENDS.get(name)


def list_backends() -> list[str]:
    """List all registered backend names."""
    return list(_BACKENDS.keys())


def init_api_backends(api_keys: ApiKeyConfig | None = None) -> dict[str, str]:
    """Initialize all API backends from API keys. Returns {provider: status}."""
    keys = api_keys or ApiKeyConfig.from_env()
    results: dict[str, str] = {}

    if keys.anthropic:
        register_backend("claude-api", ClaudeApiBackend(api_key=keys.anthropic))
        results["anthropic"] = "ready"
    else:
        results["anthropic"] = "no_key"

    if keys.openai:
        register_backend("openai-api", OpenAiApiBackend(api_key=keys.openai))
        results["openai"] = "ready"
    else:
        results["openai"] = "no_key"

    if keys.google:
        register_backend("gemini-api", GoogleAiApiBackend(api_key=keys.google))
        results["google"] = "ready"
    else:
        results["google"] = "no_key"

    if keys.xai:
        register_backend("xai-api", XaiApiBackend(api_key=keys.xai))
        results["xai"] = "ready"
    else:
        results["xai"] = "no_key"

    if keys.alibaba:
        register_backend("qwen-api", QwenApiBackend(api_key=keys.alibaba))
        results["alibaba"] = "ready"
    else:
        results["alibaba"] = "no_key"

    return results


def resolve_backend(engine: str, backend_pref: str = "") -> EngineBackend | None:
    """Resolve the best backend for an engine.

    If backend_pref is "api", tries API backend first.
    If backend_pref is "tmux" or empty, returns None (caller uses tmux).
    """
    if backend_pref == "api":
        api_mapping = {
            "claude": "claude-api",
            "codex": "openai-api",
            "openai": "openai-api",
            "gemini": "gemini-api",
            "google": "gemini-api",
            "qwen": "qwen-api",
            "alibaba": "qwen-api",
            "dashscope": "qwen-api",
            "grok": "xai-api",
            "xai": "xai-api",
        }
        backend_name = api_mapping.get(engine.lower())
        if backend_name:
            return get_backend(backend_name)
    return None
