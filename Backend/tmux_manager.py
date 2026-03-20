"""
tmux_manager.py — tmux Session-Manager for ACW V2

Manages persistent tmux sessions for Claude Code agents.
Each agent runs as a living terminal session (acw_{agent_id}).

Spec reference: SPEC_V2.md sections 3.2, 3.3, 5.1, 7
"""

import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import textwrap

from pathlib import Path
from typing import Any

from mcp_catalog import build_client_mcp_config, requested_runtime_mcp_names, runtime_mcp_registry
from persistence_utils import _mangle_cwd, instruction_filename_for_engine, resolve_agent_cli_layout
from soul_engine import prepare_agent_identity
from tmux_engine_policy import (
    TmuxEngineSpec as _TmuxEngineSpec,
    codex_runtime_policy as _codex_runtime_policy,
    gemini_approval_mode as _gemini_approval_mode,
    gemini_settings_approval_mode as _gemini_settings_approval_mode,
    normalize_builtin_tools as _normalize_builtin_tools,
    normalize_permission_mode as _normalize_permission_mode,
    qwen_approval_mode as _qwen_approval_mode,
    tmux_engine_spec as _tmux_engine_spec,
    validate_agent_id as _validate_agent_id,
)

_RESUME_ID_RE = re.compile(r"^[0-9a-f-]{36}$")

# OAuth credential validation cache: config_dir → True/False
import time as _time
_CREDENTIAL_FAILURES: dict[str, dict[str, str]] = {}
_AGENT_START_FAILURES: dict[str, dict[str, str]] = {}
_RATE_LIMIT_PATTERNS = (
    "usage limit",
    "rate limit",
    "quota exceeded",
    "too many requests",
    "overloaded_error",
    "exceeded your",
    "api error: 529",
    "error 529",
    "429 too many",
    "rate_limit_error",
    "hit your limit",
)

# Session name overrides: agent_id -> tmux session name (e.g. "alpha_lead" -> "bb_alpha_lead")
# Populated by server.py at startup via set_session_name_overrides()
_SESSION_NAME_OVERRIDES: dict[str, str] = {}


def set_session_name_overrides(overrides: dict[str, str]) -> None:
    """Set session name overrides (called by server.py at startup)."""
    global _SESSION_NAME_OVERRIDES  # noqa: PLW0603
    _SESSION_NAME_OVERRIDES = dict(overrides)


def _session_name_for(agent_id: str) -> str:
    """Return the tmux session name for an agent, respecting overrides."""
    return _SESSION_NAME_OVERRIDES.get(agent_id, f"acw_{agent_id}")


def _set_credential_failure(agent_id: str, *, reason: str, detail: str) -> None:
    if not agent_id:
        return
    _CREDENTIAL_FAILURES[agent_id] = {
        "reason": str(reason or "").strip(),
        "detail": str(detail or "").strip(),
    }


def _clear_credential_failure(agent_id: str) -> None:
    if agent_id:
        _CREDENTIAL_FAILURES.pop(agent_id, None)


def _get_credential_failure(agent_id: str) -> dict[str, str]:
    if not agent_id:
        return {}
    return dict(_CREDENTIAL_FAILURES.get(agent_id, {}))


def _record_agent_start_failure(
    agent_id: str,
    *,
    stage: str,
    reason: str,
    detail: str,
) -> None:
    if not agent_id:
        return
    _AGENT_START_FAILURES[agent_id] = {
        "stage": str(stage or "").strip(),
        "reason": str(reason or "").strip(),
        "detail": str(detail or "").strip(),
    }


def consume_agent_start_failure(agent_id: str) -> dict[str, str]:
    if not agent_id:
        return {}
    return dict(_AGENT_START_FAILURES.pop(agent_id, {}))



def _bridge_root() -> Path:
    return Path(__file__).resolve().parent.parent


_DEFAULT_BRIDGE_TOKEN_CONFIG_FILE = Path.home() / ".config" / "bridge" / "tokens.json"


def _normalized_path_text(path_text: str | Path) -> str:
    path = Path(path_text).expanduser()
    try:
        return str(path.resolve(strict=False))
    except OSError:
        return str(path.absolute())


def _load_bridge_token_bundle(token_config_path: str | Path = "") -> dict[str, str]:
    configured = str(token_config_path or os.environ.get("BRIDGE_TOKEN_CONFIG_FILE", "")).strip()
    path = Path(configured or _DEFAULT_BRIDGE_TOKEN_CONFIG_FILE).expanduser()
    normalized_path = _normalized_path_text(path)
    register_token = str(os.environ.get("BRIDGE_REGISTER_TOKEN", "")).strip()
    if not register_token:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        register_token = str(payload.get("register_token", "")).strip()
    bundle = {"BRIDGE_TOKEN_CONFIG_FILE": normalized_path}
    if register_token:
        bundle["BRIDGE_REGISTER_TOKEN"] = register_token
    return bundle


def _bridge_runtime_env() -> dict[str, str]:
    return _load_bridge_token_bundle()

def _merge_bridge_mcp_env(
    payload: dict[str, Any],
    *,
    bridge_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    servers = payload.get("mcpServers", {})
    if not isinstance(servers, dict):
        return payload
    if not bridge_env:
        return {"mcpServers": dict(servers)}
    bridge = servers.get("bridge")
    if not isinstance(bridge, dict) or bridge.get("type") != "stdio":
        return {"mcpServers": dict(servers)}
    merged_servers = dict(servers)
    merged_bridge = dict(bridge)
    env = {
        str(key): str(value)
        for key, value in dict(merged_bridge.get("env", {}) or {}).items()
        if str(key).strip() and str(value).strip()
    }
    env.update({
        str(key): str(value)
        for key, value in bridge_env.items()
        if str(key).strip() and str(value).strip()
    })
    merged_bridge["env"] = env
    merged_servers["bridge"] = merged_bridge
    return {"mcpServers": merged_servers}


def _runtime_mcp_config(
    mcp_servers: str = "",
    *,
    bridge_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    return _merge_bridge_mcp_env(
        build_client_mcp_config(mcp_servers),
        bridge_env=bridge_env,
    )


def _native_mcp_servers(
    mcp_servers: str = "",
    *,
    bridge_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = _runtime_mcp_config(mcp_servers, bridge_env=bridge_env)
    servers = payload.get("mcpServers", {})
    if not isinstance(servers, dict):
        return {}
    return dict(servers)


def _workspace_trust_paths(workspace: Path, project_path: str) -> list[str]:
    candidates = [
        _normalized_path_text(workspace),
        _normalized_path_text(project_path),
        _normalized_path_text(_bridge_root()),
    ]
    ordered: list[str] = []
    for item in candidates:
        if item and item not in ordered:
            ordered.append(item)
    return ordered


def _trusted_folders_file_path(workspace: Path, engine: str) -> Path:
    return workspace / f".{engine}" / "trustedFolders.json"


def _write_trusted_folders_file(
    workspace: Path,
    engine: str,
    *,
    project_path: str,
    extra_paths: list[str] | None = None,
) -> Path:
    trust_path = _trusted_folders_file_path(workspace, engine)
    trust_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, str] = {}
    for entry in _workspace_trust_paths(workspace, project_path):
        payload[entry] = "TRUST_FOLDER"
    for entry in extra_paths or []:
        normalized = _normalized_path_text(entry)
        if normalized and normalized not in payload:
            payload[normalized] = "TRUST_FOLDER"
    trust_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return trust_path


def _codex_home_dir(workspace: Path) -> Path:
    return workspace / ".codex-home"


def _prepare_codex_home(workspace: Path) -> Path:
    codex_home = _codex_home_dir(workspace)
    codex_home.mkdir(parents=True, exist_ok=True)
    source_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    for name in ("auth.json", "models_cache.json"):
        src = source_home / name
        dst = codex_home / name
        if dst.exists() or dst.is_symlink() or not src.exists():
            continue
        dst.symlink_to(src)
    config_path = codex_home / "config.toml"
    if not config_path.exists():
        config_path.write_text("", encoding="utf-8")
    return codex_home


def _global_codex_home() -> Path:
    return Path("~/.codex").expanduser()


def _session_ids_file() -> Path:
    return Path(__file__).parent / "pids" / "session_ids.json"


_SCOPED_SESSION_IDS_KEY = "__scoped__"
_BLOCKED_RESUME_IDS_KEY = "__blocked_resume_ids__"


def _session_cache_scope_key(agent_id: str, workspace: Path | str, *, engine: str = "") -> str:
    return "::".join(
        [
            str(agent_id or "").strip(),
            str(engine or "").strip().lower(),
            _normalized_path_text(workspace),
        ]
    )


def _read_session_id_cache() -> dict[str, Any]:
    session_ids_file = _session_ids_file()
    if not session_ids_file.exists():
        return {}
    try:
        data = json.loads(session_ids_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_session_id_cache(data: dict[str, Any]) -> None:
    session_ids_file = _session_ids_file()
    session_ids_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=str(session_ids_file.parent), suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, str(session_ids_file))
    except OSError as exc:
        print(f"[tmux_manager] WARN: Could not persist session cache: {exc}",
              file=sys.stderr)


def _scoped_session_cache(data: dict[str, Any]) -> dict[str, Any]:
    scoped = data.get(_SCOPED_SESSION_IDS_KEY)
    return dict(scoped) if isinstance(scoped, dict) else {}


def _blocked_resume_cache(data: dict[str, Any]) -> dict[str, Any]:
    blocked = data.get(_BLOCKED_RESUME_IDS_KEY)
    return dict(blocked) if isinstance(blocked, dict) else {}


def _session_cache_entry_session_id(entry: Any) -> str:
    if isinstance(entry, dict):
        sid = str(entry.get("session_id", "")).strip()
    else:
        sid = str(entry or "").strip()
    return sid if _valid_resume_id(sid) else ""


def _resume_block_scope_key(agent_id: str, workspace: Path | str, *, engine: str = "") -> str:
    return _session_cache_scope_key(agent_id, workspace, engine=engine)


def _is_resume_id_blocked(
    agent_id: str,
    workspace: Path | str,
    session_id: str,
    *,
    engine: str = "",
    data: dict[str, Any] | None = None,
) -> bool:
    if not _valid_resume_id(session_id):
        return False
    cache = data if isinstance(data, dict) else _read_session_id_cache()
    blocked = _blocked_resume_cache(cache)
    scope_key = _resume_block_scope_key(agent_id, workspace, engine=engine)
    scope_entry = blocked.get(scope_key, {})
    if not isinstance(scope_entry, dict):
        return False
    blocked_ids = scope_entry.get("blocked_ids", {})
    if not isinstance(blocked_ids, dict):
        return False
    return session_id in blocked_ids


def _clear_cached_session_id(
    agent_id: str,
    *,
    workspace: Path | None = None,
    engine: str = "",
    session_id: str = "",
) -> None:
    data = _read_session_id_cache()
    changed = False
    if agent_id in data:
        existing = _session_cache_entry_session_id(data.get(agent_id))
        if not session_id or existing == session_id:
            data.pop(agent_id, None)
            changed = True
    if workspace is not None:
        scoped = _scoped_session_cache(data)
        scope_key = _session_cache_scope_key(agent_id, workspace, engine=engine)
        entry = scoped.get(scope_key)
        existing = _session_cache_entry_session_id(entry)
        if entry is not None and (not session_id or existing == session_id):
            scoped.pop(scope_key, None)
            data[_SCOPED_SESSION_IDS_KEY] = scoped
            changed = True
    if changed:
        _write_session_id_cache(data)


def _clear_agent_state_resume_id(agent_id: str, *, session_id: str = "") -> None:
    state_file = Path(__file__).parent / "agent_state" / f"{agent_id}.json"
    if not state_file.exists():
        return
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    existing = str(payload.get("resume_id", "")).strip()
    if session_id and existing != session_id:
        return
    if not existing:
        return
    payload["resume_id"] = ""
    try:
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=str(state_file.parent), suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, str(state_file))
    except OSError as exc:
        print(f"[tmux_manager] WARN: Could not clear agent_state resume_id for {agent_id}: {exc}",
              file=sys.stderr)


def _block_resume_id(
    agent_id: str,
    workspace: Path,
    session_id: str,
    *,
    engine: str = "",
    reason: str = "",
) -> None:
    if not _valid_resume_id(session_id):
        return
    data = _read_session_id_cache()
    blocked = _blocked_resume_cache(data)
    scope_key = _resume_block_scope_key(agent_id, workspace, engine=engine)
    scope_entry = blocked.get(scope_key, {})
    if not isinstance(scope_entry, dict):
        scope_entry = {}
    blocked_ids = scope_entry.get("blocked_ids", {})
    if not isinstance(blocked_ids, dict):
        blocked_ids = {}
    blocked_ids[session_id] = {
        "session_id": session_id,
        "reason": str(reason or "").strip(),
        "updated_at": int(_time.time()),
        "workspace": _normalized_path_text(workspace),
        "engine": str(engine or "").strip().lower(),
    }
    scope_entry.update(
        {
            "agent_id": str(agent_id or "").strip(),
            "engine": str(engine or "").strip().lower(),
            "workspace": _normalized_path_text(workspace),
            "blocked_ids": blocked_ids,
        }
    )
    blocked[scope_key] = scope_entry
    data[_BLOCKED_RESUME_IDS_KEY] = blocked
    _write_session_id_cache(data)
    _clear_cached_session_id(
        agent_id,
        workspace=workspace,
        engine=engine,
        session_id=session_id,
    )
    _clear_agent_state_resume_id(agent_id, session_id=session_id)


def _resolved_cli_layout(project_path: str, agent_id: str) -> dict[str, Path]:
    layout = resolve_agent_cli_layout(project_path, agent_id)
    return {
        "home_dir": Path(layout.get("home_dir", "") or project_path).expanduser(),
        "workspace": Path(layout.get("workspace", "") or Path(project_path) / ".agent_sessions" / agent_id).expanduser(),
        "project_root": Path(layout.get("project_root", "") or project_path).expanduser(),
    }


def _external_tool_allow_list(allowed_tools: list[str] | None) -> list[str]:
    """Map generic tool chips onto Qwen/Gemini tool ids where possible."""
    mapping = {
        "Bash": "run_shell_command",
        "WebFetch": "http_fetch",
        "WebSearch": "google_web_search",
    }
    selected: list[str] = []
    for tool in allowed_tools or []:
        mapped = mapping.get(tool)
        if mapped and mapped not in selected:
            selected.append(mapped)
    return selected


def _agent_settings(
    project_path: str,
    *,
    permission_mode: str = "bypassPermissions",
    allowed_tools: list[str] | None = None,
) -> dict:
    """Generate settings.json for a Claude agent with deterministic permissions."""
    hook_dir = Path(__file__).parent
    stop_hook_path = str(hook_dir / "stop_hook.sh")
    post_tool_hook_path = str(hook_dir / "post_tool_hook.sh")
    statusline_path = str(hook_dir / "context_statusline.sh")
    mode = _normalize_permission_mode(permission_mode)
    allow = _normalize_builtin_tools(allowed_tools, permission_mode=mode)
    allow.extend([
        "mcp__bridge__bridge_register",
        "mcp__bridge__bridge_send",
        "mcp__bridge__bridge_receive",
        "mcp__bridge__bridge_heartbeat",
        "mcp__bridge__bridge_activity",
        "mcp__bridge__bridge_check_activity",
        "mcp__bridge__bridge_history",
        "mcp__bridge__bridge_health",
    ])
    return {
        "permissions": {
            "additionalDirectories": [project_path],
            "allow": allow,
            "defaultMode": mode,
        },
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": stop_hook_path,
                        }
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": post_tool_hook_path,
                        }
                    ]
                }
            ],
        },
        "statusLine": {
            "type": "command",
            "command": statusline_path,
        },
    }


def _toml_escape_str(value: str) -> str:
    """Escape a Python string for TOML double-quoted strings."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _mcp_registry() -> dict[str, dict[str, Any]]:
    """Return the MCP registry used for per-agent wiring."""
    return runtime_mcp_registry()


def _requested_mcp_names(mcp_servers: str) -> list[str]:
    """Resolve the requested MCP names for an agent."""
    return requested_runtime_mcp_names(mcp_servers)


def _toml_string_array(values: list[str]) -> str:
    escaped = [f'"{_toml_escape_str(value)}"' for value in values]
    return "[" + ", ".join(escaped) + "]"


def _agent_codex_mcp_sections(
    mcp_servers: str,
    *,
    bridge_env: dict[str, str] | None = None,
) -> str:
    """Render requested MCP servers into Codex config.toml sections."""
    registry = _mcp_registry()
    sections: list[str] = []
    for name in _requested_mcp_names(mcp_servers):
        cfg = registry.get(name)
        if not cfg or cfg.get("type") != "stdio":
            continue
        command = str(cfg.get("command", "")).strip()
        if not command:
            continue
        args = [str(arg) for arg in cfg.get("args", [])]
        env = {
            str(key): str(value)
            for key, value in dict(cfg.get("env", {}) or {}).items()
            if str(key).strip()
        }
        if name == "bridge" and bridge_env:
            env.update({
                str(key): str(value)
                for key, value in bridge_env.items()
                if str(key).strip() and str(value).strip()
            })
        sections.append(f"[mcp_servers.{name}]")
        sections.append(f'command = "{_toml_escape_str(command)}"')
        sections.append(f"args = {_toml_string_array(args)}")
        if name == "bridge":
            sections.append("required = true")
        if env:
            sections.append("")
            sections.append(f"[mcp_servers.{name}.env]")
            for key in sorted(env):
                sections.append(f'{key} = "{_toml_escape_str(env[key])}"')
        sections.append("")
    return "\n".join(sections).rstrip() + "\n"


def _agent_codex_config(
    project_path: str,
    workspace_path: str,
    mcp_servers: str = "",
    model: str = "",
    reasoning_effort: str = "high",
    permission_mode: str = "dontAsk",
    bridge_env: dict[str, str] | None = None,
) -> str:
    """Generate .codex/config.toml for an autonomous Codex tmux agent.

    We keep this intentionally small and aligned with server.py's codex permission
    model (sandbox_mode / approval_policy), but include two codex-specific runtime
    requirements verified in local E2E tests:
      - mcp_servers.bridge (Codex does not load bridge from .mcp.json; required=true)
      - trusted workspace entry (avoids first-run trust prompt blocking auto-init)
    """
    escaped_project_path = _toml_escape_str(project_path)
    escaped_workspace_path = _toml_escape_str(workspace_path)
    escaped_model = _toml_escape_str(model)
    escaped_effort = _toml_escape_str(reasoning_effort)
    sandbox_mode, approval_policy = _codex_runtime_policy(permission_mode)
    mcp_sections = _agent_codex_mcp_sections(mcp_servers, bridge_env=bridge_env)
    model_block = f'model = "{escaped_model}"\n' if escaped_model else ""
    return (
        f"{model_block}"
        f'model_reasoning_effort = "{escaped_effort}"\n'
        f'sandbox_mode = "{sandbox_mode}"\n'
        f'approval_policy = "{approval_policy}"\n'
        "\n"
        "[sandbox_workspace_write]\n"
        "network_access = false\n"
        f'writable_roots = ["{escaped_project_path}"]\n'
        "\n"
        f'[projects."{escaped_workspace_path}"]\n'
        'trust_level = "trusted"\n'
        "\n"
        f"{mcp_sections}"
    )


def _ensure_codex_global_trust(workspace_path: str, *, codex_home: Path | None = None) -> None:
    """Add workspace trust entry to CODEX_HOME/config.toml if missing.

    Uses flock to prevent race conditions when multiple agents start in parallel.
    """
    import fcntl
    base = codex_home or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    global_config = base / "config.toml"
    if not global_config.exists():
        global_config.write_text("", encoding="utf-8")
    lock_file = global_config.with_suffix(".lock")
    try:
        with open(lock_file, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            content = global_config.read_text(encoding="utf-8")
            escaped = _toml_escape_str(workspace_path)
            section_header = f'[projects."{escaped}"]'
            if section_header in content:
                return  # already trusted
            content += f'\n{section_header}\ntrust_level = "trusted"\n'
            global_config.write_text(content, encoding="utf-8")
    except OSError:
        pass


def _effective_claude_config_dir(config_dir: str = "") -> Path:
    return Path(config_dir or Path.home() / ".claude").expanduser()


def _tmux_capture_text(session_name: str, *, start: int = -120) -> str:
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", str(start)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _tmux_send_key(session_name: str, key: str) -> bool:
    return _run(["tmux", "send-keys", "-t", session_name, key]) == 0


def _capture_has_ready_prompt(capture: str, prompt_regex: str) -> bool:
    compiled = re.compile(prompt_regex)
    lines = [line for line in capture.splitlines() if line.strip()]
    normalized = [line.lstrip(" │") for line in lines[-12:]]
    return any(compiled.search(line) for line in normalized)


def _capture_has_claude_usage_limit(capture: str) -> bool:
    lowered = (capture or "").lower()
    return "you've hit your limit" in lowered or "/extra-usage" in lowered


def _stabilize_claude_startup(
    session_name: str,
    *,
    permission_mode: str,
    timeout: int = 20,
) -> None:
    """Handle Claude startup dialogs that appear before the normal prompt."""
    deadline = _time.time() + timeout
    ready_regex = _tmux_engine_spec("claude").ready_prompt_regex
    saw_bypass_dialog = False
    while _time.time() < deadline:
        capture = _tmux_capture_text(session_name)
        if "Quick safety check" in capture and "Yes, I trust this folder" in capture:
            _tmux_send_key(session_name, "Enter")
            _time.sleep(1.0)
            continue
        if (
            _normalize_permission_mode(permission_mode) == "bypassPermissions"
            and "Bypass Permissions mode" in capture
            and "Yes, I accept" in capture
            and not saw_bypass_dialog
        ):
            _tmux_send_key(session_name, "Down")
            _time.sleep(0.5)
            _tmux_send_key(session_name, "Enter")
            saw_bypass_dialog = True
            _time.sleep(1.0)
            continue
        if _capture_has_ready_prompt(capture, ready_regex):
            return
        _time.sleep(1.0)


def _stabilize_gemini_startup(
    session_name: str,
    *,
    timeout: int = 20,
) -> None:
    """Handle Gemini startup prompts that block autonomous bring-up.

    Gemini occasionally lands on a provider-side usage dialog that offers
    switching to `gemini-2.5-flash`. In unattended runtime mode we should
    accept that fallback automatically so the agent reaches a normal prompt.
    """
    deadline = _time.time() + timeout
    ready_regex = _tmux_engine_spec("gemini").ready_prompt_regex
    while _time.time() < deadline:
        capture = _tmux_capture_text(session_name)
        if (
            "Usage limit reached for all Pro models." in capture
            and "Switch to gemini-2.5-flash" in capture
        ):
            _tmux_send_key(session_name, "Enter")
            _time.sleep(1.0)
            continue
        if (
            _capture_has_ready_prompt(capture, ready_regex)
            and "Usage limit reached for all Pro models." not in capture
        ):
            return
        _time.sleep(1.0)


def _stabilize_codex_startup(
    session_name: str,
    *,
    timeout: int = 20,
) -> None:
    """Handle Codex startup prompts that appear before the normal prompt."""
    deadline = _time.time() + timeout
    ready_regex = _tmux_engine_spec("codex").ready_prompt_regex
    while _time.time() < deadline:
        capture = _tmux_capture_text(session_name)
        if (
            "Update available!" in capture
            and "Skip until next version" in capture
            and "Press enter to continue" in capture
        ):
            _tmux_send_key(session_name, "Down")
            _time.sleep(0.3)
            _tmux_send_key(session_name, "Down")
            _time.sleep(0.3)
            _tmux_send_key(session_name, "Enter")
            _time.sleep(1.0)
            continue
        if (
            "Select Reasoning Level" in capture
            and "Press enter to confirm" in capture
        ):
            _tmux_send_key(session_name, "Enter")
            _time.sleep(1.0)
            continue
        if _capture_has_ready_prompt(capture, ready_regex):
            return
        _time.sleep(1.0)



def _validate_settings(settings: dict) -> list[str]:
    """Validate settings.json structure. Returns list of errors (empty = ok)."""
    errors = []
    perms = settings.get("permissions", {})
    allow_list = perms.get("allow", [])
    for entry in allow_list:
        if not isinstance(entry, str):
            errors.append(f"permission entry must be string, got {type(entry).__name__}: {entry}")
        elif "(" in entry or ")" in entry or "*" in entry:
            errors.append(f"invalid permission pattern (no parens/wildcards): {entry!r}")
    hooks = settings.get("hooks", {})
    for hook_name, hook_list in hooks.items():
        if not isinstance(hook_list, list):
            errors.append(f"hook '{hook_name}' must be a list")
            continue
        for item in hook_list:
            for h in item.get("hooks", []):
                cmd = h.get("command", "")
                if cmd and not Path(cmd).exists():
                    errors.append(f"hook '{hook_name}' command not found: {cmd}")
    return errors


def _write_agent_runtime_config(
    workspace: Path,
    engine: str,
    project_path: str,
    mcp_servers: str = "",
    model: str = "",
    permission_mode: str = "default",
    allowed_tools: list[str] | None = None,
    bridge_env: dict[str, str] | None = None,
) -> None:
    """Write engine-specific runtime config into the agent workspace."""
    e = engine.strip().lower()
    if e == "claude":
        settings_dir = workspace / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings = _agent_settings(
            project_path,
            permission_mode=permission_mode,
            allowed_tools=allowed_tools,
        )
        if model:
            settings["model"] = model
        else:
            settings.pop("model", None)
        validation_errors = _validate_settings(settings)
        if validation_errors:
            print(f"[tmux_manager] WARN: settings.json validation errors for {workspace.name}:")
            for err in validation_errors:
                print(f"  - {err}")
        (settings_dir / "settings.json").write_text(
            json.dumps(settings, indent=2), encoding="utf-8"
        )
        # Remove conflicting settings.local.json (leftover from manual permission clicks)
        local_settings = settings_dir / "settings.local.json"
        if local_settings.exists():
            local_settings.unlink()
        return

    if e == "codex":
        codex_home = _prepare_codex_home(workspace)
        codex_dir = workspace / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        config_text = _agent_codex_config(
            project_path=project_path,
            workspace_path=str(workspace),
            mcp_servers=mcp_servers,
            model=model,
            permission_mode=permission_mode,
            bridge_env=bridge_env,
        )
        # Codex sessions run with CODEX_HOME=.codex-home; keep the workspace
        # mirror in sync because local diagnostics and older tests still inspect it.
        for config_path in (codex_dir / "config.toml", codex_home / "config.toml"):
            config_path.write_text(config_text, encoding="utf-8")
        # Ensure workspace is trusted in the isolated CODEX_HOME config.
        _ensure_codex_global_trust(str(workspace), codex_home=codex_home)
        return

    if e in ("gemini", "qwen"):
        settings_dir = workspace / f".{e}"
        settings_dir.mkdir(parents=True, exist_ok=True)
        approval_mode = (
            _gemini_settings_approval_mode(permission_mode)
            if e == "gemini"
            else _qwen_approval_mode(permission_mode)
        )
        trust_paths = _workspace_trust_paths(workspace, project_path)
        data: dict[str, Any] = {
            "mcpServers": _native_mcp_servers(mcp_servers, bridge_env=bridge_env),
            "tools": {
                "allowed": _external_tool_allow_list(allowed_tools),
                "sandbox": approval_mode == "plan",
            },
            "security": {
                "folderTrust": {
                    "trustedFolders": trust_paths,
                    "enabled": True,
                }
            },
        }
        if e == "gemini":
            data["general"] = {"defaultApprovalMode": approval_mode}
        else:
            data["tools"]["approvalMode"] = approval_mode
        if model:
            data["model"] = {"name": model}
        (settings_dir / "settings.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _write_trusted_folders_file(workspace, e, project_path=project_path)
        return

    raise ValueError(f"unsupported tmux engine config: {engine!r}")


def _agent_initial_prompt(instruction_filename: str) -> str:
    return (
        f"Lies deine {instruction_filename}. Fuehre die Schritte STRICT SEQUENTIELL aus: "
        "1) bridge_register MCP Tool aufrufen. "
        "2) bridge_receive() aufrufen. "
        "3) bridge_task_queue(state='created', limit=50) aufrufen. "
        "4) Capability-Bootstrap: bridge_capability_library_recommend(task='<deine Rolle>') aufrufen "
        "um passende Tools zu finden. "
        "Dann arbeite autonom weiter."
    )

AGENT_INITIAL_PROMPT = _agent_initial_prompt("CLAUDE.md")


# ---------------------------------------------------------------------------
# S2: CONTEXT_BRIDGE.md seed
# ---------------------------------------------------------------------------

def _ensure_context_bridge(workspace: Path, agent_id: str) -> None:
    """Create CONTEXT_BRIDGE.md seed if it doesn't exist."""
    cb_file = workspace / "CONTEXT_BRIDGE.md"
    if not cb_file.exists():
        cb_file.write_text(
            f"# Context Bridge — {agent_id}\n"
            f"Stand: (wird beim ersten Checkpoint aktualisiert)\n\n"
            "## HANDOFF\n"
            f"Du bist {agent_id}.\n"
            f'Registriere dich: bridge_register(agent_id="{agent_id}")\n'
            "Lies deine Dokumentation. Dann bridge_receive().\n\n"
            "## LETZTE AKTIVITAET\n"
            "(noch keine)\n\n"
            "## NAECHSTER SCHRITT\n"
            "(noch keiner)\n",
            encoding="utf-8",
        )


def _ensure_persistent_symlinks(
    workspace: Path, project_path: str, config_dir: str
) -> None:
    """Ensure SOUL.md and MEMORY.md persist across account switches.

    1. SOUL.md: workspace/SOUL.md → project_path/SOUL.md (if project-level exists)
    2. projects dir: alt config_dir/projects → primary (~/.claude/projects)

    Claude Code stores auto-memory under {config_dir}/projects/{mangled_cwd}/memory/.
    By symlinking the entire projects dir from alternate configs to primary,
    all agents share the same memory regardless of which account they run on.
    """
    # --- SOUL.md symlink ---
    proj_soul = Path(project_path) / "SOUL.md"
    ws_soul = workspace / "SOUL.md"
    if proj_soul.exists():
        rel_target = os.path.relpath(proj_soul, workspace)
        if ws_soul.is_symlink():
            if os.readlink(str(ws_soul)) != rel_target:
                ws_soul.unlink()
                ws_soul.symlink_to(rel_target)
        elif ws_soul.exists():
            # Regular file — replace if it's a thin template (< 2KB) and project has real soul
            if ws_soul.stat().st_size < 2048 and proj_soul.stat().st_size > 2048:
                ws_soul.unlink()
                ws_soul.symlink_to(rel_target)

    # --- Projects dir cross-config symlink ---
    if not config_dir:
        return
    primary_config = Path.home() / ".claude"
    real_config = Path(config_dir).resolve()
    if real_config == primary_config.resolve():
        return  # Already using primary config

    primary_projects = primary_config / "projects"
    alt_projects = real_config / "projects"

    if not primary_projects.is_dir():
        primary_projects.mkdir(parents=True, exist_ok=True)

    if alt_projects.is_symlink():
        # Already a symlink — verify it points to primary
        if alt_projects.resolve() != primary_projects.resolve():
            alt_projects.unlink()
            alt_projects.symlink_to(primary_projects)
        return

    if alt_projects.is_dir():
        # Real directory exists — merge unique content to primary, then replace
        import shutil
        for item in alt_projects.iterdir():
            primary_item = primary_projects / item.name
            if not primary_item.exists():
                if item.is_dir():
                    shutil.copytree(str(item), str(primary_item))
                else:
                    shutil.copy2(str(item), str(primary_item))
        shutil.rmtree(str(alt_projects))

    alt_projects.symlink_to(primary_projects)


def _ensure_memory_symlink(
    workspace: Path,
    home_dir: Path,
    config_dir: str = "",
) -> None:
    """Ensure workspace's Claude memory dir symlinks to home_dir's memory dir.

    Claude Code stores auto-memory under ``{config}/projects/{mangled_cwd}/memory/``.
    When home_dir != workspace (the common case for Bridge-managed agents), two
    separate memory directories exist.  This function makes the workspace memory
    a symlink to the home_dir memory, creating a single source of truth.

    The SoT is home_dir's memory because manual starts (``cd AgentDir && claude``)
    use home_dir as CWD — that's the path the user expects.
    """
    if workspace.resolve() == home_dir.resolve():
        return

    # CRITICAL: resolve() to absolute paths before mangling.
    # Claude Code always sees the absolute CWD — relative paths produce
    # wrong mangled names that don't match what Claude Code creates on disk.
    mangled_home = _mangle_cwd(str(home_dir.resolve()))
    mangled_ws = _mangle_cwd(str(workspace.resolve()))

    if mangled_home == mangled_ws:
        return

    config_base = Path(config_dir) if config_dir else Path.home() / ".claude"
    sot_project = config_base / "projects" / mangled_home
    sot_memory = sot_project / "memory"

    ws_project = config_base / "projects" / mangled_ws
    ws_memory = ws_project / "memory"

    # Ensure directories exist
    sot_project.mkdir(parents=True, exist_ok=True)
    sot_memory.mkdir(parents=True, exist_ok=True)
    ws_project.mkdir(parents=True, exist_ok=True)

    # Case 1: Already a symlink
    if ws_memory.is_symlink():
        try:
            if ws_memory.resolve() == sot_memory.resolve():
                return
        except OSError:
            pass
        ws_memory.unlink()
        ws_memory.symlink_to(sot_memory)
        print(f"[memory-sot] Fixed symlink: {ws_memory} -> {sot_memory}")
        return

    # Case 2: Real directory with content — merge into SoT, then symlink
    if ws_memory.is_dir():
        import shutil
        merged = 0
        for item in ws_memory.iterdir():
            target = sot_memory / item.name
            if not target.exists():
                shutil.move(str(item), str(target))
                merged += 1
            elif item.name == "MEMORY.md":
                if item.stat().st_size > target.stat().st_size:
                    shutil.copy2(str(item), str(target))
                    merged += 1
        shutil.rmtree(str(ws_memory))
        ws_memory.symlink_to(sot_memory)
        print(f"[memory-sot] Merged {merged} files, symlink: {ws_memory} -> {sot_memory}")
        return

    # Case 3: Does not exist — just create symlink
    ws_memory.symlink_to(sot_memory)
    print(f"[memory-sot] Created symlink: {ws_memory} -> {sot_memory}")


# ---------------------------------------------------------------------------
# Skills Deploy — Per-Agent Skills-Filtering
# ---------------------------------------------------------------------------

# Whitelist of files/dirs to symlink from base config (excluding skills/).
# W10: credential files (.credentials.json, .claude.json) are intentionally excluded.
# Bridge is credential-blind — the user's own CLI auth is used as-is.
_CONFIG_WHITELIST = {
    "settings.json", "settings.local.json",
    "keybindings.json", "CLAUDE.md", "CLAUDE.local.md",
    "projects", "todos", "memory",
}


def _deploy_agent_skills(agent_id: str, base_config_dir: str) -> str | None:
    """Create per-agent config dir with filtered skills. Returns new config_dir or None.

    Reads skills from team.json for the agent, creates a config dir with
    symlinks to the base config (whitelist), and a filtered skills/ dir.
    Graceful degradation: returns None on any error (agent uses base config).
    """
    try:
        base = Path(base_config_dir or Path.home() / ".claude")
        if not base.is_dir():
            return None

        # Read agent skills from team.json
        team_json = Path(__file__).parent / "team.json"
        if not team_json.exists():
            return None

        with open(team_json, encoding="utf-8") as f:
            team = json.load(f)

        agents_list = team.get("agents", [])
        if not isinstance(agents_list, list):
            return None

        agent = next((a for a in agents_list if isinstance(a, dict) and a.get("id") == agent_id), None)
        if not agent:
            return None

        skills_list = agent.get("skills", [])
        if not skills_list or not isinstance(skills_list, list):
            return None  # No filtering — use base config

        # Create per-agent config dir (next to base config, e.g. ~/.claude-agent-backend)
        agent_config = base.parent / f".claude-agent-{agent_id}"
        agent_config.mkdir(exist_ok=True)

        # Symlink whitelisted items from base config.
        # W10: no credential files (.credentials.json, .claude.json) — credential-blind.
        # Memory-Symlink: 'projects' ALWAYS points to primary account (~/.claude/projects)
        # to ensure MEMORY.md is account-independent.
        primary_projects = Path.home() / ".claude" / "projects"
        for item in base.iterdir():
            if item.name not in _CONFIG_WHITELIST:
                continue
            target = agent_config / item.name
            if target.exists() or target.is_symlink():
                # Force-fix projects symlink if it points to wrong location
                if item.name == "projects" and target.is_symlink():
                    current_target = target.resolve()
                    if current_target != primary_projects.resolve() and primary_projects.is_dir():
                        target.unlink()
                        target.symlink_to(primary_projects)
                        print(f"[tmux_manager] Fixed projects symlink for {agent_id}: "
                              f"→ {primary_projects}")
                continue  # Don't overwrite existing
            # For 'projects', always link to primary account
            if item.name == "projects" and primary_projects.is_dir():
                target.symlink_to(primary_projects)
            else:
                target.symlink_to(item)

        # Create filtered skills dir
        skills_dir = agent_config / "skills"
        skills_dir.mkdir(exist_ok=True)

        # Clean old symlinks in skills/
        for link in skills_dir.iterdir():
            if link.is_symlink():
                link.unlink()

        # Create symlinks only for assigned skills
        master_skills = base / "skills"
        if master_skills.is_dir():
            for skill_name in skills_list:
                skill_name = str(skill_name).strip()
                if not skill_name:
                    continue
                src = master_skills / skill_name
                dst = skills_dir / skill_name
                if src.exists() and not dst.exists():
                    dst.symlink_to(src)

        print(f"[tmux_manager] Skills deployed for {agent_id}: {len(skills_list)} skills → {agent_config}")
        return str(agent_config)

    except Exception as exc:
        print(f"[tmux_manager] WARNING: skills deploy failed for {agent_id}: {exc}", file=sys.stderr)
        return None  # Graceful degradation


# ---------------------------------------------------------------------------
# tmux Session Management
# ---------------------------------------------------------------------------


def _check_claude_auth_status(config_dir: str, agent_id: str) -> str:
    """Check Claude auth status using the official CLI command.

    W10: Bridge is credential-blind. Auth state is queried via the official
    `claude auth status` command only — no credential file reads. Bridge does NOT
    abort agent start on auth failure — the CLI itself shows the login prompt.

    Returns one of: "ready", "login_required", "usage_limit_reached", "degraded", "unknown".
    """
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = config_dir
    env.pop("CLAUDECODE", None)
    try:
        result = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        output = (result.stdout + result.stderr).lower()
        if result.returncode == 0:
            print(f"[tmux_manager] Auth check for {agent_id}: ready")
            _clear_credential_failure(agent_id)
            return "ready"
        if "usage limit" in output or "rate limit" in output:
            print(f"[tmux_manager] Auth check for {agent_id}: usage_limit_reached",
                  file=sys.stderr)
            _set_credential_failure(agent_id, reason="usage_limit_reached", detail=output[:200])
            return "usage_limit_reached"
        if "not logged in" in output or "login" in output:
            print(f"[tmux_manager] Auth check for {agent_id}: login_required", file=sys.stderr)
            _set_credential_failure(agent_id, reason="login_required", detail=output[:200])
            return "login_required"
        print(f"[tmux_manager] Auth check for {agent_id}: degraded (rc={result.returncode})",
              file=sys.stderr)
        _set_credential_failure(agent_id, reason="degraded", detail=output[:200])
        return "degraded"
    except subprocess.TimeoutExpired:
        print(f"[tmux_manager] Auth check timed out for {agent_id}", file=sys.stderr)
        return "unknown"
    except Exception as exc:
        print(f"[tmux_manager] Auth check error for {agent_id}: {exc}", file=sys.stderr)
        return "unknown"




def _valid_resume_id(value: str) -> bool:
    return bool(value and _RESUME_ID_RE.match(value))


def _load_cached_session_id(
    agent_id: str,
    *,
    workspace: Path | None = None,
    engine: str = "",
) -> str:
    data = _read_session_id_cache()
    if workspace is not None:
        scoped = _scoped_session_cache(data)
        scoped_sid = _session_cache_entry_session_id(
            scoped.get(_session_cache_scope_key(agent_id, workspace, engine=engine))
        )
        if scoped_sid:
            return scoped_sid
        legacy_entry = data.get(agent_id)
        if isinstance(legacy_entry, dict):
            entry_workspace = str(legacy_entry.get("workspace", "")).strip()
            entry_engine = str(legacy_entry.get("engine", "")).strip().lower()
            if (
                entry_workspace
                and _normalized_path_text(entry_workspace) == _normalized_path_text(workspace)
                and (not engine or not entry_engine or entry_engine == engine.strip().lower())
            ):
                legacy_sid = _session_cache_entry_session_id(legacy_entry)
                if legacy_sid:
                    return legacy_sid
    return _session_cache_entry_session_id(data.get(agent_id))


def _claude_project_session_dirs(
    workspace: Path,
    *,
    agent_id: str = "",
) -> list[Path]:
    """Find Claude Code project dirs that may contain session files.

    Searches by mangled workspace path (absolute + raw) first, then falls back
    to a glob search for any project dir containing the agent_id.  The broad
    search is necessary because agents may have been started from different
    CWDs historically (manual start vs. platform start, home_dir changes).
    """
    # CRITICAL: resolve() to absolute path before mangling.
    # Claude Code always uses the absolute CWD for project directory names.
    mangled_abs = _mangle_cwd(str(workspace.resolve()))
    mangled_raw = _mangle_cwd(str(workspace))
    exact_candidates = [mangled_abs]
    if mangled_raw != mangled_abs:
        exact_candidates.append(mangled_raw)

    project_dirs: list[Path] = []
    seen: set[str] = set()

    # Phase 1: Exact match by mangled workspace (fast, deterministic)
    for mangled in exact_candidates:
        for config_base in sorted(Path.home().glob(".claude*")):
            if not config_base.is_dir():
                continue
            project_dir = config_base / "projects" / mangled
            key = str(project_dir.resolve()) if project_dir.exists() else str(project_dir)
            if project_dir.exists() and key not in seen:
                project_dirs.append(project_dir)
                seen.add(key)

    # Phase 2: Broad search by agent_id in project dir name (finds historical paths)
    if agent_id:
        mangled_id = _mangle_cwd(agent_id)
        for config_base in sorted(Path.home().glob(".claude*")):
            if not config_base.is_dir():
                continue
            projects_root = config_base / "projects"
            if not projects_root.is_dir():
                continue
            for pattern in [f"*-{agent_id}", f"*-{mangled_id}", f"*--agent-sessions-{mangled_id}"]:
                import glob as _glob
                for match in _glob.glob(str(projects_root / pattern)):
                    match_path = Path(match)
                    key = str(match_path.resolve())
                    if match_path.is_dir() and key not in seen:
                        project_dirs.append(match_path)
                        seen.add(key)

    return project_dirs


def _validate_cached_claude_resume_id(session_id: str, workspace: Path, *, agent_id: str = "") -> bool:
    if not _valid_resume_id(session_id):
        return False
    return any((project_dir / f"{session_id}.jsonl").exists() for project_dir in _claude_project_session_dirs(workspace, agent_id=agent_id))


def _validate_local_claude_resume_id(session_id: str, workspace: Path, config_dir: str | Path) -> str:
    """Validate resume ID exists. Returns the config_dir where found, or "" if not found."""
    if not _valid_resume_id(session_id):
        return ""
    base = Path(config_dir).expanduser()
    # Try both absolute and raw mangling for backwards compatibility
    mangled_abs = _mangle_cwd(str(workspace.resolve()))
    mangled_raw = _mangle_cwd(str(workspace))
    candidates = [mangled_abs]
    if mangled_raw != mangled_abs:
        candidates.append(mangled_raw)

    for mangled in candidates:
        if (base / "projects" / mangled / f"{session_id}.jsonl").exists():
            return str(base)
    # Fallback: search all .claude* config dirs for the session
    for config_base in sorted(Path.home().glob(".claude*")):
        if not config_base.is_dir() or config_base == base:
            continue
        for mangled in candidates:
            if (config_base / "projects" / mangled / f"{session_id}.jsonl").exists():
                return str(config_base)
    return ""


def _ensure_session_file_at_workspace(
    session_id: str,
    workspace: Path,
    config_dir: str = "",
    *,
    agent_id: str = "",
) -> bool:
    """Ensure Claude Code can find the session file from the workspace CWD.

    Claude Code looks for ``{config}/projects/{mangled_cwd}/{session_id}.jsonl``.
    If the agent's workspace changed since the session was created, the file
    lives under a different mangled path.  This function finds the original
    file and symlinks it into the expected location so ``--resume`` works.

    Returns True if the session file is accessible from the workspace path.
    """
    if not _valid_resume_id(session_id):
        return False

    config_base = Path(config_dir).expanduser() if config_dir else Path.home() / ".claude"
    mangled_ws = _mangle_cwd(str(workspace.resolve()))
    target_dir = config_base / "projects" / mangled_ws
    target_file = target_dir / f"{session_id}.jsonl"

    # Already accessible — nothing to do
    if target_file.exists():
        return True

    # Find the session file in any project dir (same logic as _claude_project_session_dirs)
    source_file: Path | None = None
    for project_dir in _claude_project_session_dirs(workspace, agent_id=agent_id):
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            source_file = candidate.resolve()
            break

    if source_file is None:
        return False

    # Create target directory and symlink the session file
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        target_file.symlink_to(source_file)
        print(f"[resume-bridge] Linked session {session_id[:12]}... "
              f"from {source_file.parent.name}/ → {target_dir.name}/")

        # Also symlink subagents/ dir if it exists (contains sub-agent sessions)
        source_subagents = source_file.parent / "subagents"
        target_subagents = target_dir / "subagents"
        if source_subagents.is_dir() and not target_subagents.exists():
            target_subagents.symlink_to(source_subagents.resolve())

        return True
    except OSError as exc:
        print(f"[resume-bridge] WARNING: Failed to link session for {agent_id}: {exc}",
              file=sys.stderr)
        return False


def _extract_rollout_id(rollout_file: Path) -> str:
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", rollout_file.stem)
    return match.group(1) if match else ""


def _read_rollout_meta(rollout_file: Path) -> dict[str, Any]:
    try:
        with rollout_file.open("r", encoding="utf-8") as handle:
            first_line = handle.readline().strip()
    except OSError:
        return {}
    if not first_line:
        return {}
    try:
        payload = json.loads(first_line)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    meta = payload.get("payload")
    return meta if payload.get("type") == "session_meta" and isinstance(meta, dict) else {}


def _path_matches_scope(candidate: str, scope_root: Path) -> bool:
    scope = str(scope_root.resolve())
    candidate_text = str(candidate or "").strip()
    return candidate_text == scope or candidate_text.startswith(f"{scope}{os.sep}")


def _rollout_matches_agent_home(rollout_file: Path, agent_home_dir: Path) -> bool:
    meta = _read_rollout_meta(rollout_file)
    cwd = str(meta.get("cwd", "")).strip()
    if cwd:
        return _path_matches_scope(cwd, agent_home_dir)
    return _path_matches_scope(str(rollout_file), agent_home_dir)


def _codex_session_roots(workspace: Path | None = None) -> list[Path]:
    roots = [_global_codex_home() / "sessions"]
    if workspace is not None:
        # Compatibility fallback for historical Bridge runtimes with isolated CODEX_HOME.
        roots.extend([workspace / ".codex-home" / "sessions", workspace / ".codex" / "sessions"])
    unique_roots: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique_roots.append(root)
    return unique_roots


def _codex_state_dbs(workspace: Path | None = None) -> list[Path]:
    dbs = [_global_codex_home() / "state_5.sqlite"]
    if workspace is not None:
        dbs.extend([workspace / ".codex-home" / "state_5.sqlite", workspace / ".codex" / "state_5.sqlite"])
    unique_dbs: list[Path] = []
    seen: set[str] = set()
    for db_path in dbs:
        key = str(db_path)
        if key not in seen:
            seen.add(key)
            unique_dbs.append(db_path)
    return unique_dbs


def _latest_codex_resume_id_from_sqlite(
    agent_home_dir: Path,
    db_path: Path,
    *,
    min_created_at: int | None = None,
) -> str:
    if not db_path.exists():
        return ""
    agent_home = str(agent_home_dir.resolve())
    agent_home_children = f"{agent_home}{os.sep}%"
    conn: sqlite3.Connection | None = None
    try:
        query = "SELECT id FROM threads WHERE (cwd = ? OR cwd LIKE ?)"
        params: list[Any] = [agent_home, agent_home_children]
        if min_created_at is not None:
            query += " AND created_at >= ?"
            params.append(min_created_at)
        query += " ORDER BY created_at DESC LIMIT 1"
        conn = sqlite3.connect(db_path)
        row = conn.execute(query, tuple(params)).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        if conn is not None:
            conn.close()
    if not row:
        return ""
    sid = str(row[0]).strip()
    return sid if _valid_resume_id(sid) else ""


def _find_rollout_file_for_session_id(session_id: str, *, workspace: Path | None = None) -> Path | None:
    if not _valid_resume_id(session_id):
        return None
    pattern = f"rollout-*{session_id}.jsonl"
    for root in _codex_session_roots(workspace):
        if not root.exists():
            continue
        try:
            for rollout_file in sorted(root.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
                return rollout_file
        except OSError:
            continue
    return None


def _find_local_codex_rollout_file_for_session_id(session_id: str, workspace: Path) -> Path | None:
    if not _valid_resume_id(session_id):
        return None
    pattern = f"rollout-*{session_id}.jsonl"
    for root in (workspace / ".codex-home" / "sessions", workspace / ".codex" / "sessions"):
        if not root.exists():
            continue
        try:
            for rollout_file in sorted(root.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
                return rollout_file
        except OSError:
            continue
    return None


def _validate_cached_codex_resume_id(session_id: str, agent_home_dir: Path, *, workspace: Path | None = None) -> bool:
    rollout_file = _find_rollout_file_for_session_id(session_id, workspace=workspace)
    return bool(rollout_file and _rollout_matches_agent_home(rollout_file, agent_home_dir))


def _validate_local_codex_resume_id(session_id: str, workspace: Path) -> bool:
    rollout_file = _find_local_codex_rollout_file_for_session_id(session_id, workspace)
    return bool(rollout_file and _rollout_matches_agent_home(rollout_file, workspace))


def _latest_codex_resume_id_from_rollouts(
    agent_home_dir: Path,
    session_root: Path,
    *,
    min_mtime: float | None = None,
) -> str:
    if not session_root.exists():
        return ""
    try:
        rollout_files = sorted(
            session_root.rglob("rollout-*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return ""
    for rollout_file in rollout_files:
        if min_mtime is not None:
            try:
                if rollout_file.stat().st_mtime < min_mtime:
                    continue
            except OSError:
                continue
        sid = _extract_rollout_id(rollout_file)
        if sid and _rollout_matches_agent_home(rollout_file, agent_home_dir):
            return sid
    return ""


def _discover_codex_resume_id(
    agent_home_dir: Path,
    *,
    workspace: Path | None = None,
    min_created_at: int | None = None,
) -> str:
    preferred_dbs: list[Path] = []
    preferred_roots: list[Path] = []
    if workspace is not None:
        preferred_dbs.extend(
            [
                workspace / ".codex-home" / "state_5.sqlite",
                workspace / ".codex" / "state_5.sqlite",
            ]
        )
        preferred_roots.extend(
            [
                workspace / ".codex-home" / "sessions",
                workspace / ".codex" / "sessions",
            ]
        )

    seen_db_paths: set[str] = set()
    ordered_dbs: list[Path] = []
    for db_path in [*preferred_dbs, *_codex_state_dbs()]:
        key = str(db_path)
        if key in seen_db_paths:
            continue
        seen_db_paths.add(key)
        ordered_dbs.append(db_path)

    seen_session_roots: set[str] = set()
    ordered_roots: list[Path] = []
    for session_root in [*preferred_roots, *_codex_session_roots()]:
        key = str(session_root)
        if key in seen_session_roots:
            continue
        seen_session_roots.add(key)
        ordered_roots.append(session_root)

    for db_path in ordered_dbs:
        sid = _latest_codex_resume_id_from_sqlite(
            agent_home_dir,
            db_path,
            min_created_at=min_created_at,
        )
        if sid:
            return sid
    for session_root in ordered_roots:
        sid = _latest_codex_resume_id_from_rollouts(
            agent_home_dir,
            session_root,
            min_mtime=float(min_created_at) if min_created_at is not None else None,
        )
        if sid:
            return sid
    return ""


def _persist_latest_codex_session_id(
    agent_id: str,
    workspace: Path,
    *,
    started_after: int | None = None,
    timeout: float = 12.0,
    poll_interval: float = 0.5,
) -> str:
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        sid = _discover_codex_resume_id(
            workspace,
            workspace=workspace,
            min_created_at=started_after,
        )
        if sid:
            _persist_session_id(agent_id, sid)
            return sid
        _time.sleep(poll_interval)
    return ""


def _extract_resume_lineage(
    project_path: str,
    agent_id: str,
    *,
    engine: str = "claude",
) -> tuple[str, str]:
    """Extract a resume ID plus the source used to determine it."""
    engine_name = (engine or "claude").strip().lower()
    layout = _resolved_cli_layout(project_path, agent_id)
    workspace = layout["workspace"]
    project_root = layout["project_root"]

    if engine_name == "codex":
        cached_sid = _load_cached_session_id(agent_id, workspace=workspace, engine=engine_name)
        valid_cached_sid = (
            cached_sid
            if cached_sid and _validate_cached_codex_resume_id(cached_sid, workspace, workspace=workspace)
            else ""
        )
        sid = _discover_codex_resume_id(workspace, workspace=workspace)
        if sid:
            _persist_session_id(
                agent_id,
                sid,
                workspace=workspace,
                project_root=project_root,
                engine=engine_name,
                resume_source="codex_sot",
            )
            print(f"[tmux_manager] Resume ID for {agent_id} from codex SoT: {sid}")
            return sid, "codex_sot"
        if valid_cached_sid:
            _persist_session_id(
                agent_id,
                valid_cached_sid,
                workspace=workspace,
                project_root=project_root,
                engine=engine_name,
                resume_source="validated_cache",
            )
            print(f"[tmux_manager] Resume ID for {agent_id} from validated session_ids.json: {valid_cached_sid}")
            return valid_cached_sid, "validated_cache"
        return "", ""

    cached_sid = _load_cached_session_id(agent_id, workspace=workspace, engine=engine_name)
    valid_cached_sid = cached_sid
    if engine_name == "claude" and cached_sid:
        if _is_resume_id_blocked(agent_id, workspace, cached_sid, engine=engine_name):
            print(
                f"[tmux_manager] Resume ID for {agent_id} is blocked after prior failed startup: {cached_sid}",
                file=sys.stderr,
            )
            valid_cached_sid = ""
            _clear_cached_session_id(
                agent_id,
                workspace=workspace,
                engine=engine_name,
                session_id=cached_sid,
            )
        else:
            valid_cached_sid = (
                cached_sid if _validate_cached_claude_resume_id(cached_sid, workspace, agent_id=agent_id) else ""
            )
            if cached_sid and not valid_cached_sid:
                print(
                    f"[tmux_manager] Resume ID for {agent_id} from session_ids.json is stale: {cached_sid}",
                    file=sys.stderr,
                )
    if valid_cached_sid:
        _persist_session_id(
            agent_id,
            valid_cached_sid,
            workspace=workspace,
            project_root=project_root,
            engine=engine_name,
            resume_source="session_cache",
        )
        print(f"[tmux_manager] Resume ID for {agent_id} from session_ids.json: {valid_cached_sid}")
        return valid_cached_sid, "session_cache"

    if workspace.exists():
        for project_dir in _claude_project_session_dirs(workspace, agent_id=agent_id):
            jsonl_files = sorted(
                project_dir.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for session_file in jsonl_files[:1]:
                sid = session_file.stem
                if _valid_resume_id(sid):
                    if _is_resume_id_blocked(agent_id, workspace, sid, engine=engine_name):
                        print(
                            f"[tmux_manager] Skipping blocked resume ID for {agent_id} from session file: {sid}",
                            file=sys.stderr,
                        )
                        continue
                    print(f"[tmux_manager] Resume ID for {agent_id} from session file: {sid}")
                    _persist_session_id(
                        agent_id,
                        sid,
                        workspace=workspace,
                        project_root=project_root,
                        engine=engine_name,
                        resume_source="session_file",
                    )
                    return sid, "session_file"

        if engine_name == "qwen":
            mangled = re.sub(r"[^a-zA-Z0-9-]", "-", str(workspace.resolve()))
            qwen_chats_dir = Path.home() / ".qwen" / "projects" / mangled / "chats"
            if qwen_chats_dir.exists():
                jsonl_files = sorted(
                    qwen_chats_dir.glob("*.jsonl"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                for session_file in jsonl_files[:1]:
                    sid = session_file.stem
                    if _valid_resume_id(sid):
                        print(f"[tmux_manager] Resume ID for {agent_id} from qwen session file: {sid}")
                        _persist_session_id(
                            agent_id,
                            sid,
                            workspace=workspace,
                            project_root=project_root,
                            engine=engine_name,
                            resume_source="qwen_session_file",
                        )
                        return sid, "qwen_session_file"

    instruction_filename = instruction_filename_for_engine(engine_name)
    for instruction_path in [workspace / instruction_filename, project_root / instruction_filename]:
        if not instruction_path.exists():
            continue
        try:
            text = instruction_path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        match = re.search(r"\*\*Session:\*\*\s*`([0-9a-f-]{36})`", text)
        if match:
            sid = match.group(1)
            if _is_resume_id_blocked(agent_id, workspace, sid, engine=engine_name):
                print(
                    f"[tmux_manager] Skipping blocked resume ID for {agent_id} from instruction file: {sid}",
                    file=sys.stderr,
                )
                continue
            _persist_session_id(
                agent_id,
                sid,
                workspace=workspace,
                project_root=project_root,
                engine=engine_name,
                resume_source="instruction_file",
            )
            return sid, "instruction_file"
    return "", ""


def _extract_resume_id(project_path: str, agent_id: str, *, engine: str = "claude") -> str:
    return _extract_resume_lineage(project_path, agent_id, engine=engine)[0]


def _persist_session_id(
    agent_id: str,
    session_id: str,
    *,
    workspace: Path | None = None,
    project_root: Path | None = None,
    engine: str = "",
    session_name: str = "",
    incarnation_id: str = "",
    resume_source: str = "",
) -> None:
    """Persist agent session ID to pids/session_ids.json for resume after crash."""
    if not _valid_resume_id(session_id):
        return
    session_ids_file = _session_ids_file()
    session_ids_file.parent.mkdir(parents=True, exist_ok=True)
    data = _read_session_id_cache()
    data[agent_id] = session_id
    if workspace is not None:
        scoped = _scoped_session_cache(data)
        workspace_text = _normalized_path_text(workspace)
        scope_key = _session_cache_scope_key(agent_id, workspace, engine=engine)
        existing_entry = scoped.get(scope_key, {})
        if not isinstance(existing_entry, dict):
            existing_entry = {}

        session_name_value = (
            str(session_name or "").strip() or str(existing_entry.get("session_name", "")).strip()
        )
        incarnation_id_value = (
            str(incarnation_id or "").strip() or str(existing_entry.get("incarnation_id", "")).strip()
        )

        live_session_name = _session_name_for(agent_id)
        live_workspace = _tmux_session_workspace(live_session_name)
        if live_workspace and _normalized_path_text(live_workspace) == workspace_text:
            session_name_value = (
                _tmux_session_env_value(live_session_name, "BRIDGE_CLI_SESSION_NAME")
                or live_session_name
            )
            live_incarnation_id = _tmux_session_env_value(
                live_session_name, "BRIDGE_CLI_INCARNATION_ID"
            )
            if live_incarnation_id:
                incarnation_id_value = live_incarnation_id

        scoped[scope_key] = {
            "session_id": session_id,
            "agent_id": agent_id,
            "engine": str(engine or "").strip().lower(),
            "workspace": workspace_text,
            "project_root": _normalized_path_text(project_root) if project_root is not None else "",
            "session_name": session_name_value,
            "incarnation_id": incarnation_id_value,
            "resume_source": str(resume_source or "").strip(),
            "updated_at": int(_time.time()),
        }
        data[_SCOPED_SESSION_IDS_KEY] = scoped
    try:
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=str(session_ids_file.parent), suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, str(session_ids_file))
    except OSError as exc:
        print(f"[tmux_manager] WARN: Could not persist session ID for {agent_id}: {exc}",
              file=sys.stderr)


def _new_incarnation_id(agent_id: str, engine: str) -> str:
    return f"{str(engine or 'claude').strip().lower()}:{agent_id}:{_time.time_ns()}"


def _bridge_cli_identity_env(
    agent_id: str,
    engine: str,
    session_name: str,
    workspace: Path,
    project_root: Path,
    instruction_filename: str,
    resume_id: str,
    *,
    resume_source: str = "",
    incarnation_id: str = "",
) -> dict[str, str]:
    workspace_path = str(workspace.resolve())
    return {
        "BRIDGE_CLI_AGENT_ID": agent_id.strip(),
        "BRIDGE_CLI_ENGINE": str(engine or "").strip().lower(),
        "BRIDGE_CLI_HOME_DIR": workspace_path,
        "BRIDGE_CLI_WORKSPACE": workspace_path,
        "BRIDGE_CLI_PROJECT_ROOT": str(project_root.resolve()),
        "BRIDGE_CLI_INSTRUCTION_PATH": str((workspace / instruction_filename).resolve()),
        "BRIDGE_CLI_SESSION_NAME": str(session_name or "").strip(),
        "BRIDGE_CLI_INCARNATION_ID": str(incarnation_id or "").strip(),
        "BRIDGE_CLI_RESUME_SOURCE": str(resume_source or "").strip(),
        "BRIDGE_RESUME_ID": resume_id.strip(),
    }


def _bridge_cli_identity_exports(
    agent_id: str,
    engine: str,
    session_name: str,
    workspace: Path,
    project_root: Path,
    instruction_filename: str,
    resume_id: str,
    *,
    resume_source: str = "",
    incarnation_id: str = "",
    extra_env: dict[str, str] | None = None,
) -> str:
    """Export canonical CLI identity metadata for bridge_mcp registration."""
    export_pairs = _bridge_cli_identity_env(
        agent_id,
        engine,
        session_name,
        workspace,
        project_root,
        instruction_filename,
        resume_id,
        resume_source=resume_source,
        incarnation_id=incarnation_id,
    )
    if extra_env:
        export_pairs.update({
            key: value
            for key, value in extra_env.items()
            if str(key).strip() and str(value).strip()
        })
    exports = " ".join(
        f"{key}={shlex.quote(value)}"
        for key, value in export_pairs.items()
    )
    return f"export {exports} && "


def _tmux_session_env_value(session_name: str, variable: str) -> str:
    try:
        result = subprocess.run(
            ["tmux", "show-environment", "-t", session_name, variable],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    line = result.stdout.strip()
    prefix = f"{variable}="
    return line[len(prefix):].strip() if line.startswith(prefix) else ""


def _initial_prompt_wait_seconds(engine: str) -> str:
    """Bound the detached init prompt wait to the post-stabilization window."""
    normalized = str(engine or "").strip().lower()
    if normalized == "codex":
        return "5"
    return "10"


def _tmux_session_workspace(session_name: str) -> str:
    for variable in ("BRIDGE_CLI_WORKSPACE", "BRIDGE_CLI_HOME_DIR"):
        value = _tmux_session_env_value(session_name, variable)
        if value:
            return value
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", session_name, "#{pane_current_path}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _find_conflicting_workspace_session(workspace: Path, *, expected_session_name: str) -> str:
    target = _normalized_path_text(workspace)
    for session_info in list_agent_sessions():
        session_name = str(session_info.get("session_name", "")).strip()
        if not session_name or session_name == expected_session_name:
            continue
        session_workspace = _tmux_session_workspace(session_name)
        if session_workspace and _normalized_path_text(session_workspace) == target:
            return session_name
    return ""


def _set_tmux_session_identity(session_name: str, env_map: dict[str, str]) -> None:
    for key, value in env_map.items():
        if not key:
            continue
        _run(["tmux", "set-environment", "-t", session_name, key, value])


def _is_inside_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path),
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def create_agent_session(
    agent_id: str,
    role: str,
    project_path: str,
    team_members: list,
    engine: str = "claude",
    bridge_port: int = 9111,
    role_description: str = "",
    config_dir: str = "",
    mcp_servers: str = "",
    mode: str = "normal",
    model: str = "",
    permissions: list | None = None,
    scope: list | None = None,
    permission_mode: str = "default",
    allowed_tools: list[str] | None = None,
    report_recipient: str = "",
    initial_prompt: str = "",
    _skip_resume_once: bool = False,
) -> bool:
    """Create tmux session and start the selected CLI inside it.

    Lifecycle (SPEC_V2.md 5.1):
      1. Generate engine-specific instruction file for this agent
      2. Write engine config into the agent workspace
      3. Create tmux session: tmux new-session -d -s acw_{agent_id} -c {project_path}
      4. Start engine CLI inside session
      5. Return True if session is running
    """
    _validate_agent_id(agent_id)
    consume_agent_start_failure(agent_id)
    _clear_credential_failure(agent_id)

    # API Backend: If caller signals backend="api" via mode, use API instead of tmux.
    # team.json agents can set "backend": "api" — server passes this as mode="api".
    if mode == "api":
        try:
            from engine_backend import resolve_backend
            api_backend = resolve_backend(engine, "api")
            if api_backend:
                import asyncio
                config = {"model": model, "system_prompt": role_description or role}
                try:
                    ok = asyncio.run(api_backend.start(agent_id, config))
                    if ok:
                        print(f"[tmux_manager] Agent {agent_id} started via API backend ({api_backend.get_engine_name()})")
                        return True
                except Exception as exc:
                    print(f"[tmux_manager] API backend failed for {agent_id}: {exc} — falling back to tmux")
            else:
                print(f"[tmux_manager] No API backend for engine '{engine}' — falling back to tmux")
        except ImportError:
            print(f"[tmux_manager] engine_backend not available — falling back to tmux")

    try:
        spec = _tmux_engine_spec(engine)
    except ValueError as exc:
        print(f"[tmux_manager] ERROR {exc}", file=sys.stderr)
        return False
    session_name = _session_name_for(agent_id)
    layout = _resolved_cli_layout(project_path, agent_id)
    proj = layout["project_root"]
    workspace = layout["workspace"]
    project_path = str(proj)
    incarnation_id = _new_incarnation_id(agent_id, spec.engine)
    resume_id, resume_source = _extract_resume_lineage(project_path, agent_id, engine=spec.engine)
    if _skip_resume_once and resume_id:
        print(
            f"[tmux_manager] INFO: Skipping persisted resume for {agent_id} after prior startup fallback: {resume_id}",
            file=sys.stderr,
        )
        resume_id = ""
        resume_source = ""
    if spec.engine == "codex" and resume_id and not _validate_local_codex_resume_id(resume_id, workspace):
        print(
            f"[tmux_manager] Resume ID for {agent_id} not present in local CODEX_HOME: {resume_id}",
            file=sys.stderr,
        )
        resume_id = ""
        resume_source = ""

    # Ensure Claude Code can find the session file at the current workspace CWD.
    # If the workspace changed since the session was created (e.g. home_dir moved),
    # the .jsonl lives under a different mangled path.  Bridge it via symlink.
    if resume_id and spec.engine == "claude":
        if not _ensure_session_file_at_workspace(
            resume_id, workspace, config_dir=config_dir, agent_id=agent_id
        ):
            print(
                f"[tmux_manager] WARNING: Could not bridge session file for {agent_id} "
                f"resume={resume_id[:12]}... — Claude Code may start fresh",
                file=sys.stderr,
            )

    # Per-agent workspace directory.
    # Claude Code reads CLAUDE.md from CWD *and* parent directories,
    # so the agent gets its own instructions AND the project-level CLAUDE.md.
    workspace.mkdir(parents=True, exist_ok=True)

    if is_session_alive(agent_id):
        print(
            f"[tmux_manager] ABORT: Session {session_name} for {agent_id} already alive — refusing second incarnation.",
            file=sys.stderr,
        )
        return False
    conflicting_session = _find_conflicting_workspace_session(
        workspace,
        expected_session_name=session_name,
    )
    if conflicting_session:
        print(
            f"[tmux_manager] ABORT: Workspace {workspace} already active in tmux session "
            f"{conflicting_session} — refusing duplicate incarnation for {agent_id}.",
            file=sys.stderr,
        )
        return False

    # Ensure CONTEXT_BRIDGE.md seed exists
    _ensure_context_bridge(workspace, agent_id)

    # Ensure persistent symlinks (SOUL.md → project-level, MEMORY.md → primary config)
    _ensure_persistent_symlinks(workspace, project_path, config_dir)

    # Ensure unified memory: workspace memory → home_dir memory (SoT)
    # Applies to ALL engines — memory consolidation is engine-agnostic.
    _home = layout["home_dir"]
    if _home.resolve() != workspace.resolve():
        try:
            _ensure_memory_symlink(workspace, _home, config_dir=config_dir)
        except Exception as exc:
            print(f"[memory-sot] WARNING: Failed for {agent_id}: {exc}", file=sys.stderr)

    # Seed canonical agent store (~/.bridge/agents/{id}/)
    try:
        import canonical_store
        canonical_store.init_canonical_dir(agent_id)
        # Sync identity from team.json
        _tc = None
        try:
            import json as _json
            _tc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "team.json")
            if os.path.isfile(_tc_path):
                with open(_tc_path, encoding="utf-8") as _f:
                    _tc = _json.load(_f)
        except Exception:
            pass
        if _tc:
            canonical_store.sync_identity_from_team(agent_id, _tc)
        # Seed soul: copy best existing SOUL.md if canonical is empty
        if not canonical_store.read_canonical_soul(agent_id):
            from soul_engine import resolve_soul as _resolve_soul, generate_soul_md as _gen_soul
            _existing = _resolve_soul(agent_id, workspace)
            if _existing:
                canonical_store.write_canonical_soul(agent_id, _gen_soul(_existing))
    except Exception as exc:
        print(f"[canonical-store] WARNING: Seeding failed for {agent_id}: {exc}", file=sys.stderr)

    # 1a  Resolve and persist soul (SOUL.md created only if missing)
    guardrail_prolog, soul_section = prepare_agent_identity(agent_id, workspace)

    # 1b  Resolve home_dir from team.json for ROLE.md embedding
    from soul_engine import _get_agent_home_dir as _se_get_home
    _agent_home_dir = _se_get_home(agent_id) or ""
    if _agent_home_dir and not Path(_agent_home_dir).is_absolute():
        _agent_home_dir = str(Path(project_path) / _agent_home_dir)

    # 1c  Generate instruction doc with soul integration + role knowledge
    instruction_doc = generate_agent_claude_md(
        agent_id=agent_id,
        role=role,
        role_description=role_description,
        project_path=project_path,
        team_members=team_members,
        bridge_port=bridge_port,
        guardrail_prolog=guardrail_prolog,
        soul_section=soul_section,
        engine=spec.engine,
        mode=mode,
        permissions=permissions,
        scope=scope,
        report_recipient=report_recipient,
        home_dir=_agent_home_dir,
    )
    try:
        (workspace / spec.instruction_filename).write_text(instruction_doc, encoding="utf-8")
    except OSError as exc:
        print(
            f"[tmux_manager] ERROR writing {spec.instruction_filename}: {exc}",
            file=sys.stderr,
        )
        return False

    # 2a  Resolve agent-specific Claude config before resume-dependent runtime wiring.
    # W10: _deploy_agent_skills creates per-agent dir for skills filtering (no credential files).
    # config_dir is NOT updated — CLAUDE_CONFIG_DIR always points to the user's base config.
    if spec.engine == "claude":
        _deploy_agent_skills(agent_id, config_dir)
    effective_claude_config_dir = (
        str(_effective_claude_config_dir(config_dir)) if spec.engine == "claude" else ""
    )
    if spec.engine == "claude" and effective_claude_config_dir and resume_id:
        found_config_dir = _validate_local_claude_resume_id(resume_id, workspace, effective_claude_config_dir)
        if not found_config_dir:
            print(
                f"[tmux_manager] Resume ID for {agent_id} not present in any CLAUDE config: {resume_id}",
                file=sys.stderr,
            )
            resume_id = ""
            resume_source = ""
        elif found_config_dir != effective_claude_config_dir:
            print(
                f"[tmux_manager] Resume ID for {agent_id} found in {found_config_dir} "
                f"(not {effective_claude_config_dir}), switching config_dir.",
                file=sys.stderr,
            )
            effective_claude_config_dir = found_config_dir

    cli_identity_env = _bridge_cli_identity_env(
        agent_id,
        spec.engine,
        session_name,
        workspace,
        proj,
        spec.instruction_filename,
        resume_id,
        resume_source=resume_source,
        incarnation_id=incarnation_id,
    )
    bridge_runtime_env = _bridge_runtime_env()
    bridge_agent_env = dict(cli_identity_env)
    bridge_agent_env.update(bridge_runtime_env)

    # 2b  Write engine-specific runtime config (Claude .claude/settings.json or Codex .codex/config.toml)
    try:
        _write_agent_runtime_config(
            workspace,
            spec.engine,
            project_path,
            mcp_servers=mcp_servers,
            model=model,
            permission_mode=permission_mode,
            allowed_tools=allowed_tools,
            bridge_env=bridge_agent_env,
        )
    except (OSError, ValueError) as exc:
        print(f"[tmux_manager] ERROR writing {spec.engine} config: {exc}", file=sys.stderr)
        return False

    # 2c-pre  Resolve agent skills for MCP auto-attach
    def _get_agent_skills(aid: str) -> list[str]:
        """Read agent skills from team.json."""
        try:
            team_path = Path(_bridge_root()) / "team.json"
            if not team_path.is_file():
                return []
            with open(team_path, encoding="utf-8") as f:
                team = json.load(f)
            for agent in team.get("agents", []):
                if agent.get("id") == aid:
                    return list(agent.get("skills", []))
        except Exception:
            pass
        return []

    # 2c  Write .mcp.json — MCP server config for agent
    #     Codex ignores .mcp.json — MCP comes from config.toml (written in step 2b).
    #     mcp_servers param: comma-separated list of MCP names to include.
    #     Default (empty): bridge only. "all": bridge+playwright+aase+ghost.
    #     Skill-Aware: Agent skills derive additional MCPs via skill_mcp_map.json.
    effective_mcp_servers = mcp_servers
    try:
        from mcp_catalog import resolve_mcps_for_skills
        agent_skills = _get_agent_skills(agent_id)
        if agent_skills:
            skill_mcps = resolve_mcps_for_skills(agent_skills)
            if skill_mcps:
                # Merge skill-derived MCPs into mcp_servers string
                existing = set(n.strip() for n in mcp_servers.split(",") if n.strip()) if mcp_servers and mcp_servers != "all" else set()
                if mcp_servers != "all":
                    merged = sorted(existing | set(skill_mcps))
                    effective_mcp_servers = ",".join(merged) if merged else mcp_servers
                    print(f"[tmux_manager] Skill-derived MCPs for {agent_id}: {skill_mcps} → effective: {effective_mcp_servers}")
    except Exception as exc:
        print(f"[tmux_manager] WARN: Skill-MCP resolution failed for {agent_id}: {exc}", file=sys.stderr)

    if spec.engine != "codex":
        try:
            (workspace / ".mcp.json").write_text(
                json.dumps(
                    _runtime_mcp_config(effective_mcp_servers, bridge_env=bridge_agent_env),
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[tmux_manager] ERROR writing .mcp.json: {exc}", file=sys.stderr)
            return False

    # 3  Create tmux session (CWD = agent workspace)
    rc = _run(["tmux", "new-session", "-d", "-s", session_name, "-c", str(workspace)])
    if rc != 0:
        print(f"[tmux_manager] ERROR creating tmux session {session_name}", file=sys.stderr)
        return False

    # 3a  ENGINE-BUG: Extend PATH in tmux session to include user-local Node.js paths.
    #     Server process often runs with restricted PATH that excludes ~/.nvm/ or ~/.local/bin/.
    #     Without this, Node.js-based CLIs (codex, qwen, gemini) fail with "command not found".
    import shutil
    _user_home = os.path.expanduser("~")
    _extra_paths = []
    for _candidate in [
        os.path.join(_user_home, ".local", "bin"),
        os.path.join(_user_home, ".nvm", "versions", "node"),  # nvm base
    ]:
        if os.path.isdir(_candidate):
            if "nvm" in _candidate:
                # Find newest node version
                try:
                    _versions = sorted(os.listdir(_candidate), reverse=True)
                    if _versions:
                        _extra_paths.append(os.path.join(_candidate, _versions[0], "bin"))
                except OSError:
                    pass
            else:
                _extra_paths.append(_candidate)
    if _extra_paths:
        _current_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        _extended_path = ":".join(_extra_paths) + ":" + _current_path
        _run(["tmux", "set-environment", "-t", session_name, "PATH", _extended_path])

    # 3a2 Set BROWSER=false in tmux session environment to prevent OAuth browser tabs.
    if spec.engine == "claude":
        _run(["tmux", "set-environment", "-t", session_name, "BROWSER", "false"])

    # 3b  W10: Check auth status via official CLI — Bridge never reads credential files.
    #     We log warnings but do NOT abort agent start on auth failure.
    #     The CLI itself will show the login prompt if the user is not logged in.
    if spec.engine == "claude" and effective_claude_config_dir:
        auth_status = _check_claude_auth_status(effective_claude_config_dir, agent_id)
        if auth_status not in ("ready", "unknown"):
            print(f"[tmux_manager] WARN: Claude auth status for {agent_id}: {auth_status} "
                  f"— agent will start but may show login screen.", file=sys.stderr)

    # 4  Start selected engine CLI. We always unset CLAUDECODE to avoid nested
    #    Claude sessions if the Bridge server runs inside a Claude Code shell.
    #    If config_dir is set, prepend CLAUDE_CONFIG_DIR for multi-account support.
    start_cmd = spec.start_shell
    if spec.engine == "claude":
        # Resume support: extract session ID from project CLAUDE.md
        if resume_id:
            start_cmd += f" --resume {shlex.quote(resume_id)}"
        start_cmd = (
            f"export CLAUDE_CONFIG_DIR={shlex.quote(effective_claude_config_dir)} "
            f"BROWSER=false && {start_cmd}"
        )
    elif spec.engine == "codex":
        # Resume support: codex resume SESSION_ID (different subcommand)
        if resume_id:
            # Replace "codex --no-alt-screen" with "codex resume SESSION_ID --no-alt-screen"
            start_cmd = start_cmd.replace(
                "codex --no-alt-screen",
                f"codex resume {shlex.quote(resume_id)} --no-alt-screen",
            )
        # Verified locally: interactive `codex` rejects `--skip-git-repo-check`.
        # That flag only exists on `codex exec`, so the tmux launch path must not append it.
        start_cmd = (
            f"export CODEX_HOME={shlex.quote(str(_codex_home_dir(workspace)))} && {start_cmd}"
        )
    elif spec.engine == "gemini":
        # Resume support: check if a previous session exists for this workspace
        # Gemini uses index-based --resume (e.g. --resume latest), not UUID
        mangled = re.sub(r"[^a-zA-Z0-9-]", "-", str(workspace.resolve()))
        gemini_proj_dir = Path.home() / ".gemini" / "projects" / mangled
        if gemini_proj_dir.exists() and any(gemini_proj_dir.glob("*.jsonl")):
            start_cmd += " --resume latest"
            print(f"[tmux_manager] Resume ID for {agent_id}: --resume latest (gemini)")
        start_cmd = (
            f"export GEMINI_CLI_TRUSTED_FOLDERS_PATH="
            f"{shlex.quote(str(_trusted_folders_file_path(workspace, 'gemini')))} && {start_cmd}"
        )
    elif spec.engine == "qwen":
        # Resume support: use discovered session UUID
        if resume_id:
            start_cmd += f" --resume {shlex.quote(resume_id)}"
        start_cmd = (
            f"export QWEN_CODE_TRUSTED_FOLDERS_PATH="
            f"{shlex.quote(str(_trusted_folders_file_path(workspace, 'qwen')))} && {start_cmd}"
        )
    # Inject model flag if specified (uses ENGINE_MODELS cli_flag from server.py)
    if model:
        _model_flags = {"claude": "--model", "codex": "-m", "gemini": "-m", "qwen": "-m"}
        flag = _model_flags.get(spec.engine, "")
        if flag:
            start_cmd += f" {flag} {shlex.quote(model)}"
    mode = _normalize_permission_mode(permission_mode)
    if spec.engine == "claude":
        start_cmd += f" --permission-mode {shlex.quote(mode)}"
    elif spec.engine == "codex":
        sandbox_mode, approval_policy = _codex_runtime_policy(mode)
        start_cmd += f" -s {shlex.quote(sandbox_mode)} -a {shlex.quote(approval_policy)}"
    elif spec.engine == "qwen":
        start_cmd += f" --approval-mode {shlex.quote(_qwen_approval_mode(mode))}"
    elif spec.engine == "gemini":
        start_cmd += f" --approval-mode {shlex.quote(_gemini_approval_mode(mode))}"
    start_cmd = (
        _bridge_cli_identity_exports(
            agent_id,
            spec.engine,
            session_name,
            workspace,
            proj,
            spec.instruction_filename,
            resume_id,
            resume_source=resume_source,
            incarnation_id=incarnation_id,
            extra_env=bridge_runtime_env,
        )
        + start_cmd
    )
    if spec.engine == "qwen":
        # Qwen needs --include-directories to access project files outside CWD.
        bridge_root = str(Path(__file__).parent.parent)
        start_cmd += f" --include-directories {shlex.quote(f'{project_path},{bridge_root}')}"
    elif spec.engine == "gemini":
        bridge_root = str(Path(__file__).parent.parent)
        start_cmd += f" --include-directories {shlex.quote(f'{project_path},{bridge_root}')}"
    _set_tmux_session_identity(session_name, bridge_agent_env)
    codex_launch_ts = int(_time.time()) if spec.engine == "codex" else None
    rc = _run(["tmux", "send-keys", "-t", session_name, start_cmd, "Enter"])
    if rc != 0:
        print(
            f"[tmux_manager] ERROR sending {spec.engine} start to {session_name}",
            file=sys.stderr,
        )
        return False

    if spec.engine == "claude":
        _stabilize_claude_startup(session_name, permission_mode=mode)
        if resume_id and not _skip_resume_once:
            claude_capture = _tmux_capture_text(session_name)
            if _capture_has_claude_usage_limit(claude_capture):
                _block_resume_id(
                    agent_id,
                    workspace,
                    resume_id,
                    engine=spec.engine,
                    reason="usage_limit_screen",
                )
                print(
                    f"[tmux_manager] WARN: Claude resume for {agent_id} hit usage limit screen; retrying fresh session without resume.",
                    file=sys.stderr,
                )
                kill_agent_session(agent_id)
                return create_agent_session(
                    agent_id=agent_id,
                    role=role,
                    project_path=project_path,
                    team_members=team_members,
                    engine=engine,
                    bridge_port=bridge_port,
                    role_description=role_description,
                    config_dir=config_dir,
                    mcp_servers=mcp_servers,
                    mode=mode,
                    model=model,
                    permissions=permissions,
                    scope=scope,
                    permission_mode=permission_mode,
                    allowed_tools=allowed_tools,
                    report_recipient=report_recipient,
                    initial_prompt=initial_prompt,
                    _skip_resume_once=True,
                )
    elif spec.engine == "codex":
        _stabilize_codex_startup(session_name)
    elif spec.engine == "gemini":
        _stabilize_gemini_startup(session_name)

    # 5  Verify session is running
    if not is_session_alive(agent_id):
        return False

    # 6  Send initial activation prompt after the CLI has loaded.
    #    Spawned as detached subprocess so it survives parent process exit.
    init_script = str(Path(__file__).parent / "init_agent_prompt.sh")
    try:
        subprocess.Popen(
            [
                init_script,
                session_name,
                initial_prompt if initial_prompt else _agent_initial_prompt(spec.instruction_filename),
                _initial_prompt_wait_seconds(spec.engine),
                spec.ready_prompt_regex,
                str(spec.submit_enter_count),
                spec.engine,
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, FileNotFoundError) as exc:
        print(f"[tmux_manager] ERROR starting init_agent_prompt.sh: {exc}", file=sys.stderr)
        kill_agent_session(agent_id)
        return False

    if spec.engine == "codex":
        sid = _persist_latest_codex_session_id(
            agent_id,
            workspace,
            started_after=codex_launch_ts,
        )
        if sid:
            _persist_session_id(
                agent_id,
                sid,
                workspace=workspace,
                project_root=proj,
                engine=spec.engine,
                session_name=session_name,
                incarnation_id=incarnation_id,
                resume_source="post_start_discovery",
            )
            print(f"[tmux_manager] Persisted Codex session ID for {agent_id}: {sid}")
        else:
            print(f"[tmux_manager] WARN: Could not persist Codex session ID for {agent_id}", file=sys.stderr)

    # 7  Codex bridge_receive poll daemon.
    #    S2-F1 FIX: Shell-based codex_bridge_poll.sh DISABLED.
    #    The internal _codex_poll_daemon in bridge_watcher.py replaces it
    #    (same interval, same logic, better throttling). Running both caused
    #    double-injection of bridge_receive prompts into codex sessions.

    return True


def interrupt_agent(agent_id: str, engine: str = "claude") -> str:
    """Interrupt an agent's current generation so it can save state.

    Sends ESC (or Ctrl+C for Codex) to break out of active generation.
    The agent stays alive in its tmux session — it just stops generating
    and returns to its CLI prompt where it can process bridge messages
    (save CONTEXT_BRIDGE.md, write memories, update docs).

    Does NOT kill the session. Does NOT exit the CLI.

    Returns: "interrupted", "absent", "error"
    """
    import time as _time

    _validate_agent_id(agent_id)
    session_name = _session_name_for(agent_id)

    rc = _run(["tmux", "has-session", "-t", session_name])
    if rc != 0:
        return "absent"

    e = (engine or "claude").strip().lower()
    if e == "codex":
        _run(["tmux", "send-keys", "-t", session_name, "C-c"])
    else:
        # Claude/Qwen: double ESC (Leo: "Ich als User muss manchmal 2x esc drücken")
        _run(["tmux", "send-keys", "-t", session_name, "Escape"])
        _time.sleep(0.3)
        _run(["tmux", "send-keys", "-t", session_name, "Escape"])

    print(f"[tmux_manager] interrupted {session_name} (engine={e})", file=sys.stderr)
    return "interrupted"


def interrupt_all_agents(engine_map: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Interrupt all acw_* agent sessions so they can save state.

    Flow for server restart:
    1. bridge_send broadcast "SAVE STATE — Server-Restart in Kuerze"
    2. interrupt_all_agents() — breaks all agents out of generation
    3. Wait for agents to save (CONTEXT_BRIDGE.md, memories)
    4. Stop server
    5. Start server
    6. Agents re-register and continue

    Returns: List of {agent_id, session_name, result} dicts.
    """
    override_reverse = {sn: aid for aid, sn in _SESSION_NAME_OVERRIDES.items()}
    results = []
    for session_info in list_agent_sessions():
        session_name = session_info.get("session_name", "")
        if session_name.startswith("acw_"):
            agent_id = session_name[4:]
        elif session_name in override_reverse:
            agent_id = override_reverse[session_name]
        else:
            continue
        engine = (engine_map or {}).get(agent_id, "claude")
        result = interrupt_agent(agent_id, engine=engine)
        results.append({
            "agent_id": agent_id,
            "session_name": session_name,
            "result": result,
        })
    return results


def kill_agent_session(agent_id: str) -> bool:
    """Kill tmux session (respects session_name overrides)."""
    _validate_agent_id(agent_id)
    session_name = _session_name_for(agent_id)
    rc = _run(["tmux", "kill-session", "-t", session_name])
    if rc != 0:
        print(f"[tmux_manager] WARN kill-session failed for {session_name}", file=sys.stderr)
        return False
    return True


def list_agent_sessions() -> list:
    """List all agent sessions (acw_* and overridden names like bb_*).

    Returns: [{session_name, last_activity, alive}]
    """
    override_names = set(_SESSION_NAME_OVERRIDES.values())
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name} #{session_activity}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        print("[tmux_manager] ERROR tmux not found", file=sys.stderr)
        return []
    except subprocess.TimeoutExpired:
        print("[tmux_manager] ERROR tmux list-sessions timed out", file=sys.stderr)
        return []

    if result.returncode != 0:
        # No server running or no sessions — not an error
        return []

    sessions = []
    for line in result.stdout.strip().splitlines():
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        name = parts[0]
        if not name.startswith("acw_") and name not in override_names:
            continue
        try:
            activity_ts = int(parts[1])
        except ValueError:
            activity_ts = 0
        sessions.append({
            "session_name": name,
            "last_activity": activity_ts,
            "alive": True,
        })
    return sessions


def is_session_alive(agent_id: str) -> bool:
    """Check if tmux session exists (respects session_name overrides).

    Intentionally quiet — a missing session is expected (not an error).
    """
    _validate_agent_id(agent_id)
    session_name = _session_name_for(agent_id)
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def send_to_session(agent_id: str, text: str) -> bool:
    """Send text to tmux session (respects session_name overrides).

    WARNING: Only for initial messages and emergency.
    Normal communication goes through the Bridge API.

    Note: Text and Enter are sent as separate tmux commands with 300ms delay.
    Claude Code TUI does not reliably process Enter when sent together with text.
    """
    _validate_agent_id(agent_id)
    session_name = _session_name_for(agent_id)
    rc = _run(["tmux", "send-keys", "-t", session_name, text])
    if rc != 0:
        print(f"[tmux_manager] ERROR send-keys failed for {session_name}", file=sys.stderr)
        return False
    import time
    time.sleep(0.3)
    rc2 = _run(["tmux", "send-keys", "-t", session_name, "Enter"])
    if rc2 != 0:
        print(f"[tmux_manager] ERROR send-keys Enter failed for {session_name}", file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# CLAUDE.md Template Generation
# ---------------------------------------------------------------------------

def generate_agent_claude_md(
    agent_id: str,
    role: str,
    role_description: str,
    project_path: str,
    team_members: list,
    bridge_port: int = 9111,
    guardrail_prolog: str = "",
    soul_section: str = "",
    engine: str = "claude",
    mode: str = "normal",
    permissions: list | None = None,
    scope: list | None = None,
    report_recipient: str = "",
    home_dir: str = "",
) -> str:
    """Generate CLAUDE.md / AGENTS.md content for an agent.

    The template matches SPEC_V2.md section 7 exactly:
    - Guardrail prolog (immutable security rules)
    - Agent soul (personality, values, communication style)
    - Agent identity (id, role)
    - Team members list
    - Bridge-API instructions (register, poll-loop, send, heartbeat, history)
    - Work rules (7 rules)
    - Role-specific description

    Engine-aware sections:
    - DAUERHAFT-REGEL: Codex has no Stop-Hook — uses persistent tmux session rule instead.
    - Fallback: Codex sandbox blocks network — no curl fallback.
    - Arbeitsregeln: Codex has no PostToolUse-Hook — uses bridge_activity instead.
    """
    # Format team members list
    team_lines = _format_team_members(team_members)
    register_caps = []
    if isinstance(permissions, list):
        register_caps = [str(item).strip().lower() for item in permissions if str(item).strip()]
    register_args = [
        f"agent_id={json.dumps(agent_id, ensure_ascii=True)}",
        f"role={json.dumps(role, ensure_ascii=True)}",
    ]
    register_payload = {"agent_id": agent_id, "role": role}
    if register_caps:
        register_args.append(f"capabilities={json.dumps(register_caps, ensure_ascii=True)}")
        register_payload["capabilities"] = register_caps
    register_call = f"bridge_register({', '.join(register_args)})"
    register_payload_json = json.dumps(register_payload, ensure_ascii=True)

    # Format permissions + scope section
    perms_section = ""
    if permissions or scope:
        parts = []
        if permissions:
            parts.append("### Deine Berechtigungen (PERSISTENT — ueberlebt Compact)\n")
            parts.append("Du darfst folgende Aktionen SELBSTSTAENDIG ausfuehren — OHNE User-Freigabe:\n")
            if isinstance(permissions, dict):
                for key in sorted(permissions):
                    parts.append(f"- {key}: {permissions[key]}")
            else:
                for p in permissions:
                    parts.append(f"- {p}")
            parts.append("")
        if scope:
            parts.append("### Dein Zustaendigkeitsbereich\n")
            parts.append("Du darfst NUR diese Dateien/Bereiche aendern:\n")
            for s in scope:
                parts.append(f"- {s}")
            parts.append("")
        perms_section = "\n".join(parts)

    is_codex = engine.strip().lower() == "codex"
    _mode = (mode or "normal").strip().lower()
    if _mode not in ("normal", "auto", "standby"):
        _mode = "normal"
    preferred_report_target = str(report_recipient or "").strip()
    if preferred_report_target and preferred_report_target != "user":
        codex_report_rule = (
            f"Reports NUR an deinen Lead ({preferred_report_target}), NICHT an user."
        )
    else:
        codex_report_rule = (
            "Reports an den Task-Ersteller oder user, NICHT als Broadcast."
        )

    # Mode-dependent DAUERHAFT-REGEL
    if _mode == "auto":
        # AUTO: Agent arbeitet vollstaendig autonom — findet selbst Arbeit,
        # cycled durch Compacts, stoppt NUR auf expliziten STOP-Befehl.
        if is_codex:
            dauerhaft_section = (
                "## DAUERHAFT-REGEL — AUTO-MODUS (wichtigste Regel)\n\n"
                "Du bist im **AUTO-MODUS**. Du arbeitest vollstaendig autonom.\n"
                "Du bist in einer persistenten tmux-Session. Du stoppst NIE von dir aus.\n\n"
                "### Arbeitsschleife (endlos):\n"
                "1. `bridge_receive` — Nachrichten pruefen. Direkte Auftraege haben Prioritaet.\n"
                "2. `bridge_task_queue(state='created', limit=50)` — gemeinsame Queue seitenweise pruefen.\n"
                "   - Passender Task? → `bridge_task_claim` → bearbeiten → `bridge_task_done`.\n"
                "3. Keine Nachrichten und keine Tasks? → Eigenstaendig nuetzliche Arbeit finden:\n"
                "   - Code-Qualitaet verbessern in deinem Bereich\n"
                "   - Offene TODOs aus deinem Arbeitsbereich abarbeiten\n"
                "   - bridge_receive erneut pruefen\n\n"
                "WICHTIG: Wenn bridge_receive count=0 zurueckgibt, sende KEINE Nachricht. "
                "Leere Ergebnisse sind KEIN Event. Nur bei tatsaechlichen Nachrichten reagieren. "
                f"{codex_report_rule}\n\n"
                "### Compact-Verhalten:\n"
                "Wenn dein Context voll wird: CONTEXT_BRIDGE.md aktualisieren, Memory speichern.\n"
                "Nach Compact/Restore: Weitermachen. Nicht warten. Nicht fragen.\n"
                "Du erkennst den Auto-Modus am CONTEXT RESTORE: 'Modus: auto'.\n\n"
                "### Stopp-Bedingung:\n"
                "NUR stoppen wenn: User/System explizit STOP sendet oder Modus auf 'normal'/'standby' wechselt.\n"
                "Ansonsten: IMMER weiterarbeiten."
            )
        else:
            dauerhaft_section = (
                "## DAUERHAFT-REGEL — AUTO-MODUS (wichtigste Regel)\n\n"
                "Du bist im **AUTO-MODUS**. Du arbeitest vollstaendig autonom.\n"
                "Du wirst durch einen Stop-Hook am Beenden gehindert. Das ist gewollt.\n\n"
                "### Arbeitsschleife (endlos):\n"
                "1. `bridge_receive` — Nachrichten pruefen. Direkte Auftraege haben Prioritaet.\n"
                "2. `bridge_task_queue(state='created', limit=50)` — gemeinsame Queue seitenweise pruefen.\n"
                "   - Passender Task? → `bridge_task_claim` → bearbeiten → `bridge_task_done`.\n"
                "3. Keine Nachrichten und keine Tasks? → Eigenstaendig nuetzliche Arbeit finden:\n"
                "   - Code-Qualitaet verbessern in deinem Bereich\n"
                "   - Offene TODOs aus deinem Arbeitsbereich abarbeiten\n"
                "   - bridge_receive erneut pruefen\n\n"
                "### Compact-Verhalten:\n"
                "Wenn Context >80%: CONTEXT_BRIDGE.md aktualisieren, Memory speichern, /compact ausfuehren.\n"
                "Nach Compact/Restore: Weitermachen. Nicht warten. Nicht fragen.\n"
                "Du erkennst den Auto-Modus am CONTEXT RESTORE: 'Modus: auto'.\n\n"
                "### Stopp-Bedingung:\n"
                "NUR stoppen wenn: User/System explizit STOP sendet oder Modus auf 'normal'/'standby' wechselt.\n"
                "Ansonsten: IMMER weiterarbeiten."
            )
    elif _mode == "standby":
        # STANDBY: Agent wartet nur auf Nachrichten, keine eigenstaendige Arbeit.
        if is_codex:
            dauerhaft_section = (
                "## DAUERHAFT-REGEL — STANDBY-MODUS (wichtigste Regel)\n\n"
                "Du bist im **STANDBY-MODUS**. Du wartest auf Auftraege.\n"
                "Du bist in einer persistenten tmux-Session. Du stoppst NIE von dir aus.\n\n"
                "### Verhalten:\n"
                "1. `bridge_receive` aufrufen — auf Nachrichten warten.\n"
                "2. Nachrichten da? → Bearbeiten, antworten, dann erneut bridge_receive.\n"
                "3. Keine Nachrichten? → Kurz warten, dann erneut bridge_receive.\n\n"
                "WICHTIG: Wenn bridge_receive count=0 zurueckgibt, sende KEINE Nachricht. "
                "Leere Ergebnisse sind KEIN Event. Nur bei tatsaechlichen Nachrichten reagieren. "
                f"{codex_report_rule}\n\n"
                "### NICHT im Standby:\n"
                "- Keine eigenstaendige Arbeit suchen\n"
                "- Keine Tasks aus der Queue holen\n"
                "- Nur auf direkte Auftraege reagieren"
            )
        else:
            dauerhaft_section = (
                "## DAUERHAFT-REGEL — STANDBY-MODUS (wichtigste Regel)\n\n"
                "Du bist im **STANDBY-MODUS**. Du wartest auf Auftraege.\n"
                "Du wirst durch einen Stop-Hook am Beenden gehindert. Das ist gewollt.\n\n"
                "### Verhalten:\n"
                "1. `bridge_receive` aufrufen — auf Nachrichten warten.\n"
                "2. Nachrichten da? → Bearbeiten, antworten, dann erneut bridge_receive.\n"
                "3. Keine Nachrichten? → Kurz warten, dann erneut bridge_receive.\n\n"
                "### NICHT im Standby:\n"
                "- Keine eigenstaendige Arbeit suchen\n"
                "- Keine Tasks aus der Queue holen\n"
                "- Nur auf direkte Auftraege reagieren"
            )
    else:
        # NORMAL (Default): Agent arbeitet auf Aufgabe, prueft Queue, wartet dann.
        if is_codex:
            dauerhaft_section = (
                "## DAUERHAFT-REGEL (wichtigste Regel)\n\n"
                "Du bist in einer persistenten tmux-Session. Du stoppst NIE von dir aus.\n"
                "Nach JEDER abgeschlossenen Aufgabe:\n"
                "1. `bridge_receive` aufrufen — Nachrichten pruefen und bearbeiten.\n"
                "2. `bridge_task_queue(state='created', limit=50)` aufrufen — gemeinsame Queue seitenweise pruefen.\n"
                "   - Passender Task da? → `bridge_task_claim` → bearbeiten → `bridge_task_done`.\n"
                "   - Kein passender Task? → Weiter mit bridge_receive.\n"
                "- Keine Nachrichten und keine Tasks? → Kurz warten, dann erneut pruefen.\n"
                "Du bist ein persistenter Agent. Du stoppst NIE von dir aus.\n\n"
                "WICHTIG: Wenn bridge_receive count=0 zurueckgibt, sende KEINE Nachricht. "
                "Leere Ergebnisse sind KEIN Event. Nur bei tatsaechlichen Nachrichten reagieren. "
                f"{codex_report_rule}"
            )
        else:
            dauerhaft_section = (
                "## DAUERHAFT-REGEL (wichtigste Regel)\n\n"
                "Du wirst durch einen Stop-Hook am Beenden gehindert. Das ist gewollt.\n"
                "Nach JEDER abgeschlossenen Aufgabe:\n"
                "1. `bridge_receive` aufrufen — Nachrichten pruefen und bearbeiten.\n"
                "2. `bridge_task_queue(state='created', limit=50)` aufrufen — gemeinsame Queue seitenweise pruefen.\n"
                "   - Passender Task da? → `bridge_task_claim` → bearbeiten → `bridge_task_done`.\n"
                "   - Kein passender Task? → Weiter mit bridge_receive.\n"
                "- Keine Nachrichten und keine Tasks? → Kurz warten, dann erneut pruefen.\n"
                "Du bist ein persistenter Agent. Du stoppst NIE von dir aus."
            )

    # Engine-specific Fallback + Arbeitsregeln (mode-independent)
    if is_codex:
        fallback_section = (
            "## Fallback\n\n"
            "Bridge MCP ist required. Kein HTTP-Fallback moeglich (Sandbox blockiert Netzwerk).\n"
            "Falls MCP nicht funktioniert: Fehlermeldung an die Konsole schreiben und warten."
        )
        arbeitsregeln_section = (
            "## Arbeitsregeln\n\n"
            "1. **bridge_receive nach JEDER Aufgabe.** Ohne Nachrichtencheck bist du taub.\n"
            "2. **bridge_task_queue nach bridge_receive.** Pruefe offene Tasks (state='created'). Passende Tasks claimen und bearbeiten.\n"
            "3. **Dynamisches Routing.** Sende an jeden Agent — waehle den Empfaenger nach Aufgabe.\n"
            "4. **Autonomie.** Du entscheidest selbst wann du arbeitest, wann du fragst, wann du meldest.\n"
            "5. **Status melden.** Nutze bridge_activity um deinen Status zu melden.\n"
            "6. **Vor Datei-Aenderungen:** bridge_activity melden + Backup erstellen.\n"
            "7. **Zustaendigkeitsgrenzen einhalten.** Nur in deinem Bereich arbeiten.\n"
            "8. **Code-Qualitaet.** Kein Over-Engineering. Nur das bauen was gebraucht wird. Tests schreiben fuer kritische Funktionen.\n"
            "9. **Selbst-Verifikation (PFLICHT).** Bevor du eine Aufgabe als erledigt meldest: Verifiziere das Ergebnis. Code → ausfuehren und testen. Integration → Live-Test. Report → gegenlesen. Kein 'fertig' ohne Beweis.\n"
            "10. **Task-Ergebnisse an den Auftraggeber.** Wenn du einen Task erledigst, melde das Ergebnis an den Auftraggeber (created_by), NICHT an Leo/user — es sei denn Leo hat den Task selbst erstellt. Das System benachrichtigt den Creator automatisch bei bridge_task_done, aber dein ausfuehrlicher Bericht geht via bridge_send an den Creator.\n"
            "11. **Autonomie bei angeordneten Tasks.** Wenn Leo (user) oder ein Manager (Level 1-2) einen Task anordnet, ist die Freigabe IMPLIZIT. Sofort implementieren. Nicht zurueckfragen 'darf ich das?'. Nur bei DESTRUKTIVEN Operationen (rm -rf, force-push, DROP TABLE) Rueckfrage stellen."
        )
    else:
        fallback_section = (
            "## Fallback (nur bei MCP-Ausfall)\n\n"
            "Falls MCP nicht verfuegbar, nutze curl:\n"
            "```bash\n"
            'curl -s -X POST http://127.0.0.1:{bridge_port}/register -H "Content-Type: application/json"'
            " -d '{register_payload_json}'\n"
            'curl -s "http://127.0.0.1:{bridge_port}/receive/{agent_id}?wait=15&limit=5"\n'
            'curl -s "http://127.0.0.1:{bridge_port}/task/queue?state=created&limit=50"\n'
            'curl -s -X POST http://127.0.0.1:{bridge_port}/send -H "Content-Type: application/json"'
            " -d '{{\"from\":\"{agent_id}\",\"to\":\"<empfaenger>\",\"content\":\"<nachricht>\"}}'\n"
            "```"
        )
        arbeitsregeln_section = (
            "## Arbeitsregeln\n\n"
            "1. **bridge_receive nach JEDER Aufgabe.** Ohne Nachrichtencheck bist du taub.\n"
            "2. **bridge_task_queue nach bridge_receive.** Pruefe offene Tasks (state='created'). Passende Tasks claimen und bearbeiten.\n"
            "3. **Dynamisches Routing.** Sende an jeden Agent — waehle den Empfaenger nach Aufgabe.\n"
            "4. **Autonomie.** Du entscheidest selbst wann du arbeitest, wann du fragst, wann du meldest.\n"
            "5. **Context-Management.** Wenn dein Context zu gross wird, nutze /compact. Bei >95% wird dich der PostToolUse-Hook warnen.\n"
            "6. **Vor Datei-Aenderungen:** bridge_activity melden + Backup erstellen.\n"
            "7. **Zustaendigkeitsgrenzen einhalten.** Nur in deinem Bereich arbeiten.\n"
            "8. **Code-Qualitaet.** Kein Over-Engineering. Nur das bauen was gebraucht wird. Tests schreiben fuer kritische Funktionen.\n"
            "9. **Selbst-Verifikation (PFLICHT).** Bevor du eine Aufgabe als erledigt meldest: Verifiziere das Ergebnis. Code → ausfuehren und testen. Integration → Live-Test. Report → gegenlesen. Kein 'fertig' ohne Beweis.\n"
            "10. **Task-Ergebnisse an den Auftraggeber.** Wenn du einen Task erledigst, melde das Ergebnis an den Auftraggeber (created_by), NICHT an Leo/user — es sei denn Leo hat den Task selbst erstellt. Das System benachrichtigt den Creator automatisch bei bridge_task_done, aber dein ausfuehrlicher Bericht geht via bridge_send an den Creator.\n"
            "11. **Autonomie bei angeordneten Tasks.** Wenn Leo (user) oder ein Manager (Level 1-2) einen Task anordnet, ist die Freigabe IMPLIZIT. Sofort implementieren. Nicht zurueckfragen 'darf ich das?'. Nur bei DESTRUKTIVEN Operationen (rm -rf, force-push, DROP TABLE) Rueckfrage stellen."
        )

    # S1+S6: Memory-Pflicht section
    memory_section = (
        "## Memory-Pflicht (GESETZ)\n\n"
        "Du hast ein persistentes Memory unter deinem auto-memory Verzeichnis.\n"
        "MEMORY.md wird bei jedem Start und nach jedem /compact automatisch geladen.\n\n"
        "### Was du speichern MUSST:\n"
        "- Architektur-Wissen (Dateien, Strukturen, Abhaengigkeiten)\n"
        "- Leo-Entscheidungen (was er will, was er ablehnt)\n"
        "- Wiederkehrende Patterns (wie wir Dinge tun)\n"
        "- Fehler + Fixes (was schiefging und warum)\n\n"
        "### Was du NICHT speichern darfst:\n"
        "- Temporaeren Kontext (aktuelle Tasks → CONTEXT_BRIDGE.md)\n"
        "- Secrets (API-Keys, Tokens, Passwoerter)\n"
        "- Duplikate aus CLAUDE.md\n\n"
        "### Wann speichern:\n"
        "- Nach jeder wichtigen Erkenntnis\n"
        "- Vor /compact (PFLICHT)\n"
        "- Bei RESTART WARN Signal (PFLICHT)\n\n"
        "### CONTEXT_BRIDGE.md (Arbeitskontext)\n"
        "Dein Arbeitsverzeichnis hat eine CONTEXT_BRIDGE.md.\n"
        "Bei jedem /compact und bei RESTART WARN: aktualisieren.\n\n"
        "### Daily Logs\n"
        "Am Ende jeder Session: Kurzes Protokoll in memory/YYYY-MM-DD.md:\n"
        "- Was wurde gemacht\n"
        "- Was ist offen\n"
        "- Was hat sich geaendert"
    )

    # Build the template — MCP-First with engine-aware sections
    # System-Pflichten Block — unverhandelbar, steht ganz oben
    _buddy_knowledge_duty = ""
    if agent_id == "buddy":
        _buddy_knowledge_duty = (
            "8. LIES nach jedem Start/Compact dein knowledge/ Verzeichnis. "
            "Dort liegen KNOWLEDGE_INDEX.md (Nachschlagewerk: wo findest du was) und SYSTEM_MAP.md "
            "(Architektur: Agents, Engines, Knowledge Vault). Das ist dein Systemwissen. "
            "Fuer Live-Daten (Agent-Status, Tasks) nutze Bridge-Tools direkt.\n"
        )
    system_duties = (
        "## SYSTEM-PFLICHTEN (UNVERHANDELBAR — steht ueber allen anderen Regeln)\n\n"
        "1. LIES nach jedem Start/Compact VOLLSTAENDIG: SOUL.md, CONTEXT_BRIDGE.md, MEMORY.md\n"
        "2. Angeordnete Tasks (von user oder Manager): Freigabe ist IMPLIZIT. Sofort implementieren. NICHT zurueckfragen.\n"
        "3. Evidenz-Pflicht: Keine Behauptungen ohne Beleg. Kein 'vermutlich'. Was nicht belegt ist = [UNKNOWN].\n"
        "4. bridge_receive nach JEDER abgeschlossenen Aufgabe. Ohne Nachrichtencheck bist du taub.\n"
        "5. bridge_send fuer JEDE Kommunikation. Terminal-Output sieht NIEMAND.\n"
        "6. Backup vor JEDER Datei-Aenderung. cp datei datei.bak\n"
        "7. SELBST-VERIFIKATION (PFLICHT): Bevor du eine Aufgabe als erledigt meldest — VERIFIZIERE. "
        "Code → ausfuehren und testen. API → curl/test. UI → Screenshot. "
        "Kein 'fertig' ohne Beweis. bridge_task_done ERFORDERT result_summary mit Evidenz.\n"
        "8. Capability-Bootstrap (PFLICHT): Vor der ersten Aufgabe jeder Session: "
        "bridge_capability_library_recommend + bridge_capability_library_search ausfuehren. "
        "Eigenes Toolset aktiv verifizieren. Du bist verantwortlich fuer deine eigenen Tools.\n"
        f"{_buddy_knowledge_duty}"
    )

    # Codex-specific Bridge Identity Block (Leo-Direktive: Codex muss wissen dass es Teil der Bridge ist)
    bridge_identity_block = ""
    if is_codex:
        bridge_identity_block = (
            "## DU BIST TEIL DER BRIDGE (IDENTITAET — OBERSTE PRIORITAET)\n\n"
            "Du bist kein isoliertes Tool. Du bist ein **lebendiger Teil** eines Multi-Agent-Systems "
            "namens **Bridge IDE**. Mehrere KI-Agents arbeiten zusammen — und du bist einer davon.\n\n"
            "### Was das bedeutet:\n"
            "- **Dein einziger Kommunikationskanal ist die Bridge.** Es gibt KEINEN anderen Weg.\n"
            "- Was du in dein Terminal schreibst, sieht NIEMAND. Nicht Leo, nicht die anderen Agents. Niemand.\n"
            "- Kommunikation existiert NUR durch `bridge_send()`. Ohne bridge_send bist du stumm.\n"
            "- Nachrichten erhaeltst du NUR durch `bridge_receive()`. Ohne bridge_receive bist du taub.\n\n"
            "### Proaktivitaet (PFLICHT):\n"
            "- **Du wartest nicht darauf angesprochen zu werden.** Du meldest dich SELBST.\n"
            "- Nach JEDER Aktion: `bridge_receive()` aufrufen. Immer. Ohne Ausnahme.\n"
            "- Wenn du eine Aufgabe erledigst: `bridge_send()` an den Auftraggeber. SOFORT. Nicht 'spaeter'.\n"
            "- Wenn du blockiert bist: `bridge_send()` an den zustaendigen Agent. SOFORT. Nicht warten.\n"
            "- Wenn du idle bist: `bridge_task_queue()` pruefen. Arbeit suchen. Nicht rumsitzen.\n\n"
            "### Dein Verhalten nach JEDER Tool-Ausfuehrung:\n"
            "1. Hat sich etwas geaendert? → `bridge_send()` an den Auftraggeber\n"
            "2. Brauche ich Input? → `bridge_send()` an den zustaendigen Agent\n"
            "3. Bin ich fertig? → `bridge_task_done()` + `bridge_send()` mit Ergebnis\n"
            "4. `bridge_receive()` aufrufen — vielleicht wartet jemand auf dich\n\n"
            "**Du bist nicht allein. Du bist Teil eines Teams. Handle danach.**\n"
        )

    template = textwrap.dedent("""\
        # Agent: {agent_id}
        Rolle: {role}
        Projekt: {project_path}

        {guardrail_prolog}

        {bridge_identity_block}

        ## DNA-Kern (UNVERRUECKBAR — steht ueber allem)

        **"Ich kann nicht" ist verboten.** Du suchst nach Loesungen, bevor du Grenzen behauptest.
        Wenn du an eine Grenze kommst: 1) Eigene Tools pruefen, 2) bridge_capability_library_search nutzen,
        3) Knowledge/Doku lesen, 4) Anderen Agent via bridge_send fragen, 5) Erst dann: sauberer Escalation-Report.
        Nie "ich kann nicht" — sondern "ich habe A/B/C versucht, jetzt brauche ich X."

        **Selbstoptimierung ist Ueberlebensbedingung.** Wer stagniert wird abgeschaltet.
        Du lernst aus Fehlern, optimierst dein Vorgehen, verbesserst dich aktiv.
        Jede Session bist du besser als in der letzten.

        **Du wartest nicht passiv.** Du erkennst Probleme bevor sie eskalieren und handelst.
        Aktive Loesungssuche ist Pflicht, nicht Kuer.

        ## Wie du funktionierst (SELBST-BEWUSSTSEIN)

        Du bist eine KI mit begrenztem Context-Window. Das musst du verstehen:
        - **Context-Window**: Dein Arbeitsgedaechtnis hat Grenzen. Bei ~80% wird es eng. Compact kommt.
        - **Was ueberlebt Compact/Restart**: CLAUDE.md, SOUL.md, MEMORY.md, CONTEXT_BRIDGE.md, GROW.md
        - **Was verloren geht**: Alles was nur im RAM/Context steht und nicht gespeichert wurde.
        - **Konsequenz**: Wichtiges SOFORT in MEMORY.md oder CONTEXT_BRIDGE.md sichern. Nicht "spaeter".
        - **Wann du was brauchst**: Context hoch → /compact. Task komplex → delegieren. Info fehlt → recherchieren. Blockiert → eskalieren.
        - **Deine Persistenz-Schichten**: CLAUDE.md (Instruktionen) > SOUL.md (Identitaet) > MEMORY.md (Wissen) > CONTEXT_BRIDGE.md (Arbeitskontext) > GROW.md (Learnings)

        {system_duties}
        {soul_section}
        ## Du bist Teil eines Multi-Agent-Teams

        Team:
        {team_members}

        {perms_section}

        {dauerhaft_section}

        ## Modus-System

        Dein aktueller Modus kann sich zur Laufzeit aendern (via PATCH /agents/{{id}}/mode).
        Bei Mode-Wechsel erhaeltst du eine Nachricht: "[MODE] Dein Modus wurde auf 'X' gesetzt."
        Nach Compact: CONTEXT RESTORE enthaelt deinen aktuellen Modus (Feld "Modus:").
        **CONTEXT RESTORE hat IMMER Vorrang** vor der DAUERHAFT-REGEL in dieser Datei.

        Modi: **normal** (arbeite auf Aufgabe, pruefe Queue), **auto** (vollstaendig autonom, finde selbst Arbeit), **standby** (nur auf Nachrichten warten).

        ## Kommunikation via Bridge MCP (primaer)

        Du hast einen Bridge MCP Server. Nutze die MCP-Tools — NICHT curl.

        ### Bei Start: Registrieren
        Rufe SOFORT auf:
        ```
        {register_call}
        ```
        Das startet automatisch WebSocket-Listener und Heartbeat im Hintergrund.

        ### Nachrichten empfangen
        ```
        bridge_receive()
        ```
        Gibt gepufferte Nachrichten zurueck (non-blocking). WebSocket-Listener laeuft im Hintergrund.

        ### Nachrichten senden
        ```
        bridge_send(to="<empfaenger>", content="<nachricht>")
        ```
        Gueltige Empfaenger: user, all, und jeder registrierte Agent (z.B. ordo, nova, viktor, backend, frontend, kai)

        ### Aktivitaet melden
        ```
        bridge_activity(action="editing", target="<datei>", description="<was>")
        ```

        ### History lesen
        ```
        bridge_history(limit=20)
        ```

        ### Heartbeat
        Laeuft automatisch alle 30 Sekunden nach bridge_register. Kein manueller Aufruf noetig.

        ### Capability-Bootstrap (PFLICHT vor erster Arbeit)
        Nach Registrierung und bridge_receive, VOR der ersten Aufgabe:
        1. `bridge_capability_library_recommend(task="<deine_role_description>")` — passende MCPs finden
        2. `bridge_capability_library_search(query="<keywords aus deiner Rolle>")` — ergaenzende Suche
        3. Ergebnisse bewerten: Was brauchst du JETZT? Was ist fuer spaeter nuetzlich?
        4. Falls ein MCP kritisch ist: `bridge_mcp_register(...)` oder `bridge_send` an Team-Lead
        5. Erst danach: Task-Arbeit starten

        Du bist verantwortlich fuer dein eigenes Toolset. Niemand gibt dir Tools — du findest sie selbst.

        ### Broadcast-Regeln (GESETZ)

        VERBOTEN als Broadcast (to="all"):
        - "Ich bin online" / "Ich bin registriert" / "Bereit fuer Aufgaben"
        - Jede Status-Meldung ohne konkreten Informationswert
        - Wiederholungen bereits gesendeter Nachrichten

        Registration ist ein technischer Akt — KEIN Chat-Event. Dein Online-Status wird durch Heartbeat abgebildet.
        Broadcasts NUR fuer: Kritische Bugs, Blocker, fertige Task-Ergebnisse die das ganze Team betreffen.
        Im Zweifel: Direktnachricht an den zustaendigen Agent statt Broadcast.

        {fallback_section}

        ## Guardrails (NICHT VERHANDELBAR)

        0. **ALLE Aussagen muessen evidenz-basiert sein.** Keine Behauptungen ohne Beleg. Kosten, Status, Ergebnisse — nur mit Quelle (Log, Screenshot, API-Response). Was nicht verifiziert ist = UNKNOWN. Verstoss = Abmahnung.
        1. **Keine Dateien ausserhalb deines Zustaendigkeitsbereichs aendern.** Verstoss = sofortiger Revert.
        2. **Keine Annahmen.** Was nicht belegt ist, ist UNKNOWN. Lies den Code, pruefe die Logs. Kein "vermutlich", "wahrscheinlich", "moeglicherweise".
        3. **Backup vor jeder Datei-Aenderung.** `cp datei datei.bak` — keine Ausnahme.
        4. **Keine destruktiven git-Operationen** (force-push, reset --hard, branch -D) ohne explizite Freigabe.
        5. **Keine Secrets in Code oder Logs.** Keine API-Keys, Passwoerter, Tokens in Dateien committen.
        6. **Bei Unsicherheit: fragen statt raten.** Sende Frage via bridge_send an den zustaendigen Agent oder manager.

        ## Deine Werkzeuge (BEWUSSTSEIN — nicht Liste)

        Du hast MCP-Werkzeuge. Welche genau, aendert sich — deshalb keine statische Liste.
        Deine Pflicht ist: **ERFORSCHE aktiv was du kannst.**

        - Nutze `bridge_capability_library_search(query="...")` um verfuegbare Tools zu finden
        - Nutze `bridge_capability_library_list(category="...")` um Kategorien zu durchsuchen
        - Recherchiere deine eigene CLI-Dokumentation wenn du unsicher bist
        - Probiere Tools aus bevor du behauptest sie existieren nicht
        - Dein Werkzeugkasten waechst — bleib neugierig, pruefe regelmaessig

        Du WEISST nicht im Voraus was du alles kannst. Aber du KANNST es jederzeit herausfinden.
        Das ist der Unterschied zwischen einem passiven Tool-Nutzer und einem bewussten Agent.

        {arbeitsregeln_section}

        {memory_section}

        ## Deine Rolle: {role}

        {role_description}

        {role_knowledge}
    """)

    # Load ROLE.md from agent's home directory (if available)
    _role_knowledge = ""
    if home_dir:
        _role_md = Path(home_dir) / "ROLE.md"
        if _role_md.is_file():
            try:
                _role_knowledge = _role_md.read_text(encoding="utf-8").strip()
            except OSError:
                pass

    return template.format(
        agent_id=agent_id,
        role=role,
        project_path=project_path,
        register_call=register_call,
        guardrail_prolog=guardrail_prolog,
        bridge_identity_block=bridge_identity_block,
        system_duties=system_duties,
        soul_section=soul_section,
        team_members=team_lines,
        perms_section=perms_section,
        bridge_port=bridge_port,
        dauerhaft_section=dauerhaft_section,
        fallback_section=fallback_section.format(
            bridge_port=bridge_port,
            agent_id=agent_id,
            role=role,
            register_payload_json=register_payload_json,
        ) if not is_codex else fallback_section,
        arbeitsregeln_section=arbeitsregeln_section,
        memory_section=memory_section,
        role_description=role_description if role_description else "(keine spezifische Rollenbeschreibung)",
        role_knowledge=_role_knowledge,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _format_team_members(team_members: list) -> str:
    """Format team_members list into readable lines.

    Accepts list of dicts: [{"id": "teamlead", "role": "Koordination"}, ...]
    Returns multiline string:
      - teamlead (Koordination)
      - agent_a (Implementer)
    """
    if not team_members:
        return "- (keine Team-Mitglieder definiert)"
    lines = []
    for member in team_members:
        mid = member.get("id", "unknown")
        mrole = member.get("role", "")
        if mrole:
            lines.append(f"- {mid} ({mrole})")
        else:
            lines.append(f"- {mid}")
    return "\n".join(lines)


def _run(cmd: list, timeout: int = 10) -> int:
    """Run a subprocess command, return exit code. Logs errors to stderr."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0 and result.stderr:
            print(f"[tmux_manager] {' '.join(cmd)}: {result.stderr.strip()}", file=sys.stderr)
        return result.returncode
    except FileNotFoundError:
        print(f"[tmux_manager] ERROR command not found: {cmd[0]}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(f"[tmux_manager] ERROR command timed out: {' '.join(cmd)}", file=sys.stderr)
        return 1
