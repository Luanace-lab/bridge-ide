from __future__ import annotations

import re
from dataclasses import dataclass


_VALID_AGENT_ID = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclass(frozen=True)
class TmuxEngineSpec:
    """Engine-specific startup metadata for persistent tmux-backed agents."""

    engine: str
    instruction_filename: str
    start_shell: str
    ready_prompt_regex: str
    submit_enter_count: int


def validate_agent_id(agent_id: str) -> None:
    """Validate agent_id against whitelist (alphanumeric + underscore)."""
    if not agent_id or not _VALID_AGENT_ID.match(agent_id):
        raise ValueError(f"invalid agent_id: {agent_id!r} (must be alphanumeric, underscore, or hyphen)")


def tmux_engine_spec(engine: str) -> TmuxEngineSpec:
    normalized = (engine or "claude").strip().lower()
    if normalized == "claude":
        return TmuxEngineSpec(
            engine="claude",
            instruction_filename="CLAUDE.md",
            start_shell="unset CLAUDECODE CODEX_MANAGED_BY_NPM CODEX_THREAD_ID CODEX_CI CODEX_SANDBOX_NETWORK_DISABLED && claude",
            ready_prompt_regex=r"^\s*[>⏵❯]\s*(?!\d+\.)",
            submit_enter_count=2,
        )
    if normalized == "codex":
        return TmuxEngineSpec(
            engine="codex",
            instruction_filename="AGENTS.md",
            start_shell="unset CLAUDECODE CODEX_MANAGED_BY_NPM CODEX_THREAD_ID CODEX_CI CODEX_SANDBOX_NETWORK_DISABLED && codex --no-alt-screen",
            ready_prompt_regex=r"^\s*›\s*(?!\d+\.)",
            submit_enter_count=1,
        )
    if normalized == "qwen":
        return TmuxEngineSpec(
            engine="qwen",
            instruction_filename="QWEN.md",
            start_shell="qwen",
            ready_prompt_regex=r"^\s*(?:[>⏵❯]\s*(?!\d+\.)|\*\s+Type your message)",
            submit_enter_count=2,
        )
    if normalized == "gemini":
        return TmuxEngineSpec(
            engine="gemini",
            instruction_filename="GEMINI.md",
            start_shell="gemini",
            ready_prompt_regex=r"^\s*(?:[>⏵❯]\s*(?!\d+\.)|\*\s+Type your message)",
            submit_enter_count=2,
        )
    raise ValueError(
        f"unsupported tmux engine: {engine!r} (supported: claude, codex, qwen, gemini)"
    )


def normalize_permission_mode(permission_mode: str) -> str:
    mode = (permission_mode or "default").strip()
    allowed = {"default", "acceptEdits", "dontAsk", "bypassPermissions", "plan", "auto"}
    return mode if mode in allowed else "default"


def normalize_builtin_tools(
    allowed_tools: list[str] | None,
    *,
    permission_mode: str = "default",
) -> list[str]:
    """Return a deterministic built-in tool allow-list for Claude-style settings."""
    default_tools = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebFetch", "Task"]
    if allowed_tools:
        valid = {"Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebFetch", "WebSearch", "Task"}
        selected = [tool for tool in allowed_tools if tool in valid]
        tools = selected or default_tools
    else:
        tools = list(default_tools)
    if normalize_permission_mode(permission_mode) == "plan":
        tools = [tool for tool in tools if tool not in {"Write", "Edit", "Bash", "Task"}]
        if "Read" not in tools:
            tools.insert(0, "Read")
        if "Glob" not in tools:
            tools.append("Glob")
        if "Grep" not in tools:
            tools.append("Grep")
    return tools


def codex_runtime_policy(permission_mode: str) -> tuple[str, str]:
    mode = normalize_permission_mode(permission_mode)
    mapping = {
        "plan": ("read-only", "on-request"),
        "default": ("workspace-write", "on-request"),
        "acceptEdits": ("workspace-write", "on-failure"),
        "dontAsk": ("workspace-write", "never"),
        "bypassPermissions": ("danger-full-access", "never"),
        "auto": ("workspace-write", "never"),
    }
    return mapping.get(mode, mapping["default"])


def qwen_approval_mode(permission_mode: str) -> str:
    mode = normalize_permission_mode(permission_mode)
    mapping = {
        "plan": "plan",
        "default": "default",
        "acceptEdits": "auto-edit",
        "dontAsk": "yolo",
        "bypassPermissions": "yolo",
        "auto": "yolo",
    }
    return mapping.get(mode, "default")


def gemini_settings_approval_mode(permission_mode: str) -> str:
    mode = normalize_permission_mode(permission_mode)
    mapping = {
        "plan": "plan",
        "default": "default",
        "acceptEdits": "auto_edit",
        "dontAsk": "auto_edit",
        "bypassPermissions": "auto_edit",
        "auto": "auto_edit",
    }
    return mapping.get(mode, "default")


def gemini_approval_mode(permission_mode: str) -> str:
    mode = normalize_permission_mode(permission_mode)
    mapping = {
        "plan": "plan",
        "default": "default",
        "acceptEdits": "auto_edit",
        "dontAsk": "yolo",
        "bypassPermissions": "yolo",
        "auto": "yolo",
    }
    return mapping.get(mode, "default")
