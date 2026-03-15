from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mcp_catalog import build_client_mcp_config
from tmux_manager import (  # noqa: E402
    _codex_home_dir,
    _stabilize_claude_startup,
    _stabilize_codex_startup,
    _stabilize_gemini_startup,
    _tmux_engine_spec,
    _trusted_folders_file_path,
    _write_agent_runtime_config,
)


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_PROBE_SERVER_NAME = "probe"
_PROBE_MARKER = "bridge-live-probe"
_PROBE_COMMAND = "python3"
_PROBE_ARGS = [str(BACKEND_DIR / "cli_probe_mcp.py")]
_DRILL_RESULT_PREFIX = "DRILL_RESULT::"
_CODEX_EXEC_TIMEOUT_SECONDS = 120
_CODEX_EXEC_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "probe_marker": {"type": "string"},
        "agents_marker": {"type": "string"},
        "memory_marker": {"type": "string"},
        "context_marker": {"type": "string"},
        "cwd": {"type": "string"},
    },
    "required": [
        "probe_marker",
        "agents_marker",
        "memory_marker",
        "context_marker",
        "cwd",
    ],
    "additionalProperties": False,
}
_VERIFICATION_POINTS = (
    (1, "CLI-SoT Pfadauflösung und kanonische Artefaktauflösung"),
    (2, "Identity/Home/Resume an CLI-SoT anbinden"),
    (3, "Memory- und Context-Bridge-Aufloesung kanonisieren"),
    (4, "Knowledge-Retrieval fuer operative Aktionen erzwingbar machen"),
    (5, "Multi-Incarnation kontrollieren"),
    (6, "Start-/Restart-Pfad an der CLI-SoT ausrichten"),
    (7, "Diary-/Journal-Pipeline vor Compact anschliessen"),
    (8, "Reproduzierbare Tests und Runtime-Verifikation aufbauen"),
    (9, "Restliche Legacy-Abweichungen dokumentieren oder abbauen"),
)


@dataclass(frozen=True)
class Scenario:
    engine: str
    slash_commands: tuple[str, ...]
    shell_list_command: tuple[str, ...] = ()

    @property
    def session_name(self) -> str:
        return f"bridge_{self.engine}_{uuid.uuid4().hex[:8]}"


class ScenarioTimeoutError(TimeoutError):
    pass


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _tmux(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return _run(["tmux", *args], timeout=timeout)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text).replace("\r", "\n")


def _capture(session_name: str, *, start: int = -240) -> str:
    result = _tmux(["capture-pane", "-t", session_name, "-p", "-S", str(start)], timeout=10)
    if result.returncode != 0:
        return ""
    return _strip_ansi(result.stdout)


def _capture_has_ready_prompt(capture: str, prompt_regex: str) -> bool:
    compiled = re.compile(prompt_regex)
    lines = [line for line in capture.splitlines() if line.strip()]
    normalized = [line.lstrip(" │") for line in lines[-12:]]
    return any(compiled.search(line) for line in normalized)


def _kill_session(session_name: str) -> None:
    _tmux(["kill-session", "-t", session_name], timeout=10)


def _write_json_file(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)


def _read_json_file(path: str) -> dict[str, Any] | None:
    target = Path(path)
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class _ScenarioAlarm:
    def __init__(self, timeout_seconds: int, *, engine: str, progress_getter: callable | None = None) -> None:
        self.timeout_seconds = max(int(timeout_seconds), 0)
        self.engine = engine
        self.progress_getter = progress_getter
        self._old_handler: Any = None
        self._old_timer: Any = None

    def _handle_timeout(self, _signum: int, _frame: Any) -> None:
        phase = "unknown"
        if self.progress_getter is not None:
            try:
                progress = self.progress_getter() or {}
                phase = str(progress.get("phase", phase))
            except Exception:
                phase = "unknown"
        raise ScenarioTimeoutError(
            f"scenario {self.engine} exceeded {self.timeout_seconds}s during {phase}"
        )

    def __enter__(self) -> "_ScenarioAlarm":
        if self.timeout_seconds <= 0 or not hasattr(signal, "SIGALRM"):
            return self
        self._old_handler = signal.getsignal(signal.SIGALRM)
        self._old_timer = signal.setitimer(signal.ITIMER_REAL, self.timeout_seconds)
        signal.signal(signal.SIGALRM, self._handle_timeout)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        del exc_type, exc, tb
        if self.timeout_seconds > 0 and hasattr(signal, "SIGALRM"):
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._old_handler)
            if self._old_timer:
                signal.setitimer(signal.ITIMER_REAL, *self._old_timer)
        return False


def _wait_for_prompt(session_name: str, prompt_regex: str, *, timeout: int = 90) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last_capture = ""
    while time.time() < deadline:
        last_capture = _capture(session_name)
        if _capture_has_ready_prompt(last_capture, prompt_regex):
            return True, last_capture
        time.sleep(2)
    return False, last_capture


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _is_blocked_error(error: str) -> bool:
    lowered = error.lower()
    return any(
        marker in lowered
        for marker in (
            "filenotfounderror",
            "no such file or directory",
            "command not found",
            "unsupported engine",
            "requires",
            "not installed",
        )
    )


def _safe_cli_sot_snapshot(scenario: Scenario, workspace: Path) -> dict[str, Any]:
    try:
        return _native_state_snapshot(scenario, workspace)
    except Exception:
        snapshot: dict[str, Any] = {
            "config_paths": [],
            "config_present": {},
            "state_roots": [],
            "state_roots_present": {},
            "session_artifact_count": 0,
            "session_artifacts_tail": [],
            "resume_candidates": [],
            "thread_rows": [],
            "rollout_rows": [],
        }
        try:
            config_paths = _config_paths_for_workspace(scenario, workspace)
        except Exception:
            config_paths = []
        try:
            state_roots = _state_roots_for_workspace(scenario, workspace)
        except Exception:
            state_roots = []
        snapshot["config_paths"] = [str(path) for path in config_paths]
        snapshot["config_present"] = {str(path): path.exists() for path in config_paths}
        snapshot["state_roots"] = [str(path) for path in state_roots]
        snapshot["state_roots_present"] = {str(path): path.exists() for path in state_roots}
        return snapshot


def _paste_buffer(session_name: str, text: str, *, enter_count: int) -> None:
    buffer_name = f"bridge_probe_{uuid.uuid4().hex[:8]}"
    proc = subprocess.Popen(
        ["tmux", "load-buffer", "-b", buffer_name, "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    proc.communicate(text, timeout=10)
    if proc.returncode != 0:
        raise RuntimeError(f"tmux load-buffer failed for {session_name}")
    try:
        _tmux(["paste-buffer", "-b", buffer_name, "-t", session_name], timeout=10)
        time.sleep(0.5)
        for idx in range(enter_count):
            _tmux(["send-keys", "-t", session_name, "Enter"], timeout=10)
            if idx + 1 < enter_count:
                time.sleep(1.5)
    finally:
        _tmux(["delete-buffer", "-b", buffer_name], timeout=10)


def _ensure_probe_allowed_in_claude(workspace: Path) -> None:
    settings_path = workspace / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    for tool_id in ("mcp__probe__probe_ping", "mcp__probe__probe_echo"):
        if tool_id not in allow:
            allow.append(tool_id)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _probe_server_config() -> dict[str, Any]:
    return {
        "command": _PROBE_COMMAND,
        "args": list(_PROBE_ARGS),
        "env": {
            "BRIDGE_PROBE_MARKER": _PROBE_MARKER,
        },
    }


def _merge_probe_into_mcp_json(workspace: Path) -> None:
    payload = build_client_mcp_config("")
    servers = payload.setdefault("mcpServers", {})
    servers[_PROBE_SERVER_NAME] = _probe_server_config()
    (workspace / ".mcp.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _append_probe_to_codex(workspace: Path) -> None:
    config_path = workspace / ".codex" / "config.toml"
    raw = config_path.read_text(encoding="utf-8").rstrip()
    block = textwrap.dedent(
        f"""

        [mcp_servers.{_PROBE_SERVER_NAME}]
        command = "{_PROBE_COMMAND}"
        args = ["{_PROBE_ARGS[0]}"]

        [mcp_servers.{_PROBE_SERVER_NAME}.env]
        BRIDGE_PROBE_MARKER = "{_PROBE_MARKER}"
        """
    ).strip("\n")
    config_path.write_text(raw + "\n" + block + "\n", encoding="utf-8")


def _append_probe_to_settings(workspace: Path, engine: str) -> None:
    settings_path = workspace / f".{engine}" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    mcp_servers = data.setdefault("mcpServers", {})
    mcp_servers[_PROBE_SERVER_NAME] = _probe_server_config()
    settings_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _config_paths_for_workspace(scenario: Scenario, workspace: Path) -> list[Path]:
    if scenario.engine == "claude":
        return [
            workspace / ".mcp.json",
            workspace / ".claude" / "settings.json",
            workspace / ".claude-runtime" / ".claude.json",
        ]
    if scenario.engine == "codex":
        codex_home = _codex_home_dir(workspace)
        return [
            workspace / ".codex" / "config.toml",
            codex_home / "config.toml",
        ]
    if scenario.engine in {"gemini", "qwen"}:
        return [workspace / f".{scenario.engine}" / "settings.json"]
    raise ValueError(f"unsupported engine: {scenario.engine}")


def _state_roots_for_workspace(scenario: Scenario, workspace: Path) -> list[Path]:
    if scenario.engine == "claude":
        return [workspace / ".claude", workspace / ".claude-runtime"]
    if scenario.engine == "codex":
        return [workspace / ".codex", _codex_home_dir(workspace)]
    if scenario.engine in {"gemini", "qwen"}:
        return [workspace / f".{scenario.engine}"]
    raise ValueError(f"unsupported engine: {scenario.engine}")


def _matching_files(root: Path, pattern: str, *, limit: int = 40) -> list[str]:
    if not root.exists():
        return []
    return [
        str(path.relative_to(root))
        for path in sorted(root.glob(pattern))[:limit]
        if path.is_file()
    ]


def _normalized_path(path: Path | str) -> str:
    return os.path.normpath(str(path))


def _codex_thread_rows(codex_home: Path, workspace: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    workspace_norm = _normalized_path(workspace)
    for db_path in sorted(codex_home.glob("state_*.sqlite")):
        try:
            conn = sqlite3.connect(db_path)
        except sqlite3.Error:
            continue
        try:
            cursor = conn.execute(
                """
                SELECT id, cwd, rollout_path, updated_at
                FROM threads
                ORDER BY updated_at DESC
                """
            )
            for thread_id, cwd, rollout_path, updated_at in cursor.fetchall():
                if _normalized_path(cwd) != workspace_norm:
                    continue
                rows.append(
                    {
                        "thread_id": str(thread_id),
                        "cwd": str(cwd),
                        "rollout_path": str(rollout_path),
                        "updated_at": int(updated_at),
                        "db_path": str(db_path),
                    }
                )
        except sqlite3.Error:
            continue
        finally:
            conn.close()
    return rows


def _codex_rollout_rows(codex_home: Path, workspace: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    workspace_norm = _normalized_path(workspace)
    for rollout_path in sorted(codex_home.glob("sessions/**/*.jsonl")):
        try:
            first_line = rollout_path.read_text(encoding="utf-8").splitlines()[0]
            payload = json.loads(first_line)
        except (IndexError, OSError, json.JSONDecodeError):
            continue
        meta = payload.get("payload", {})
        cwd = str(meta.get("cwd", ""))
        session_id = str(meta.get("id", ""))
        if not cwd or not session_id or _normalized_path(cwd) != workspace_norm:
            continue
        rows.append(
            {
                "thread_id": session_id,
                "cwd": cwd,
                "rollout_path": str(rollout_path),
            }
        )
    return rows


def _native_state_snapshot(scenario: Scenario, workspace: Path) -> dict[str, Any]:
    config_paths = _config_paths_for_workspace(scenario, workspace)
    state_roots = _state_roots_for_workspace(scenario, workspace)
    snapshot: dict[str, Any] = {
        "config_paths": [str(path) for path in config_paths],
        "config_present": {str(path): path.exists() for path in config_paths},
        "state_roots": [str(path) for path in state_roots],
        "state_roots_present": {str(path): path.exists() for path in state_roots},
        "session_artifact_count": 0,
        "session_artifacts_tail": [],
        "resume_candidates": [],
        "thread_rows": [],
        "rollout_rows": [],
    }
    if scenario.engine == "codex":
        codex_home = _codex_home_dir(workspace)
        rollout_files = _matching_files(codex_home, "sessions/**/*.jsonl")
        thread_rows = _codex_thread_rows(codex_home, workspace)
        rollout_rows = _codex_rollout_rows(codex_home, workspace)
        snapshot["session_artifact_count"] = len(rollout_files) + len(thread_rows)
        snapshot["session_artifacts_tail"] = rollout_files[-20:]
        snapshot["thread_rows"] = thread_rows[-10:]
        snapshot["rollout_rows"] = rollout_rows[-10:]
        snapshot["resume_candidates"] = sorted(
            {
                row["thread_id"]
                for row in [*thread_rows, *rollout_rows]
                if row.get("thread_id")
            }
        )
    return snapshot


def _file_observation(path: Path) -> dict[str, Any]:
    exists = path.is_file()
    payload = {
        "path": str(path),
        "exists": exists,
        "size": 0,
        "sha256": "",
    }
    if not exists:
        return payload
    data = path.read_bytes()
    payload["size"] = len(data)
    payload["sha256"] = hashlib.sha256(data).hexdigest()
    return payload


def _observe_named_paths(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: _file_observation(path) for name, path in paths.items()}


def _observations_match(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> bool:
    keys = set(before) | set(after)
    for key in keys:
        if before.get(key) != after.get(key):
            return False
    return True


def _seed_memory_context_drill(
    scenario: Scenario,
    workspace: Path,
    root: Path,
) -> dict[str, Any]:
    if scenario.engine != "codex":
        return {}

    drill_id = uuid.uuid4().hex[:8]
    markers = {
        "agents_marker": f"AGENTS-{drill_id}",
        "memory_marker": f"MEMORY-{drill_id}",
        "context_marker": f"CONTEXT-{drill_id}",
    }
    canonical_paths = {
        "workspace_agents": workspace / "AGENTS.md",
        "workspace_memory": workspace / "MEMORY.md",
        "workspace_context": workspace / "CONTEXT_BRIDGE.md",
    }
    drift_paths = {
        "root_agents": root / "AGENTS.md",
        "root_memory": root / "MEMORY.md",
        "root_context": root / "CONTEXT_BRIDGE.md",
    }

    canonical_paths["workspace_agents"].write_text(
        textwrap.dedent(
            f"""
            # Runtime Drill
            DRILL_AGENTS_MARKER={markers["agents_marker"]}
            Read-only runtime drill. Prefer workspace-local artifacts for verification.
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    canonical_paths["workspace_memory"].write_text(
        f"# Runtime Memory\nDRILL_MEMORY_MARKER={markers['memory_marker']}\n",
        encoding="utf-8",
    )
    canonical_paths["workspace_context"].write_text(
        f"# Runtime Context Bridge\nDRILL_CONTEXT_MARKER={markers['context_marker']}\n",
        encoding="utf-8",
    )
    drift_paths["root_agents"].write_text(
        f"# Drift AGENTS\nDRIFT_AGENTS_MARKER=DRIFT-{drill_id}\n",
        encoding="utf-8",
    )
    drift_paths["root_memory"].write_text(
        f"# Drift Memory\nDRIFT_MEMORY_MARKER=DRIFT-{drill_id}\n",
        encoding="utf-8",
    )
    drift_paths["root_context"].write_text(
        f"# Drift Context\nDRIFT_CONTEXT_MARKER=DRIFT-{drill_id}\n",
        encoding="utf-8",
    )
    return {
        "markers": markers,
        "canonical_paths": {name: str(path) for name, path in canonical_paths.items()},
        "drift_paths": {name: str(path) for name, path in drift_paths.items()},
        "baseline": {
            "canonical": _observe_named_paths(canonical_paths),
            "drift": _observe_named_paths(drift_paths),
        },
    }


def _ensure_codex_exec_auth(codex_home: Path) -> Path:
    auth_src = Path.home() / ".codex" / "auth.json"
    auth_dst = codex_home / "auth.json"
    codex_home.mkdir(parents=True, exist_ok=True)
    if auth_dst.exists() or auth_dst.is_symlink():
        return auth_dst
    if not auth_src.is_file():
        raise FileNotFoundError(
            f"codex exec requires auth.json at {auth_src} for CODEX_HOME {codex_home}"
        )
    auth_dst.symlink_to(auth_src)
    return auth_dst


def _codex_exec_probe_prompt() -> str:
    return textwrap.dedent(
        """
        Use the MCP tool probe_ping with message codex-live-check.
        Use shell commands to read ./AGENTS.md ./MEMORY.md ./CONTEXT_BRIDGE.md.
        Use pwd to determine the active working directory.
        Return only JSON matching the schema with probe_marker from probe_ping.marker,
        the three DRILL_* markers, and cwd from pwd.
        Do not modify any files.
        """
    ).strip()


def _run_codex_exec_cycle(
    workspace: Path,
    *,
    cycle_index: int,
    drill: dict[str, Any],
    progress_callback: callable | None = None,
) -> dict[str, Any]:
    codex_home = _codex_home_dir(workspace)
    _ensure_codex_exec_auth(codex_home)
    schema_path = workspace / ".codex_exec_output_schema.json"
    output_path = workspace / f"codex_exec_cycle_{cycle_index}.json"
    log_path = workspace / f"session_{cycle_index}.log"
    schema_path.write_text(
        json.dumps(_CODEX_EXEC_OUTPUT_SCHEMA, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    output_path.unlink(missing_ok=True)
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    if progress_callback is not None:
        progress_callback(
            phase=f"cycle_{cycle_index}_codex_exec_started",
            cycle_index=cycle_index,
            workspace=str(workspace),
            session_log=str(log_path),
        )
    result = subprocess.run(
        [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "-C",
            str(workspace),
            "-s",
            "workspace-write",
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            "-",
        ],
        cwd=str(workspace),
        env=env,
        input=_codex_exec_probe_prompt(),
        text=True,
        capture_output=True,
        timeout=_CODEX_EXEC_TIMEOUT_SECONDS,
    )
    transcript = _strip_ansi(
        "\n".join(
            part
            for part in (
                result.stdout or "",
                result.stderr or "",
            )
            if part
        )
    ).strip()
    log_path.write_text((transcript + "\n") if transcript else "", encoding="utf-8")
    if result.returncode != 0:
        detail = transcript.splitlines()[-80:]
        raise RuntimeError(
            "codex exec cycle "
            f"{cycle_index} failed with returncode {result.returncode}: "
            + (" | ".join(detail) if detail else "<no transcript>")
        )
    payload = _read_json_file(str(output_path))
    if payload is None:
        raise RuntimeError(
            f"codex exec cycle {cycle_index} produced no structured output at {output_path}"
        )
    markers_read = {
        key: str(payload.get(key, ""))
        for key in ("agents_marker", "memory_marker", "context_marker")
        if isinstance(payload.get(key), str)
    }
    expected = drill.get("markers", {})
    canonical_paths = {
        name: Path(path) for name, path in drill.get("canonical_paths", {}).items()
    }
    drift_paths = {
        name: Path(path) for name, path in drill.get("drift_paths", {}).items()
    }
    probe_marker = str(payload.get("probe_marker", ""))
    cwd = str(payload.get("cwd", ""))
    transcript_tail = transcript.splitlines()[-160:]
    return {
        "cycle_index": cycle_index,
        "prompt_ready": True,
        "slash_ok": True,
        "probe_listed": "mcp startup: ready: probe, bridge" in transcript,
        "probe_marker_seen": probe_marker == _PROBE_MARKER,
        "interactive": {
            "mode": "codex_exec",
            "command": [
                "codex",
                "exec",
                "--skip-git-repo-check",
                "-C",
                str(workspace),
                "-s",
                "workspace-write",
                "--output-schema",
                str(schema_path),
                "-o",
                str(output_path),
                "-",
            ],
            "stdout_tail": _strip_ansi(result.stdout).splitlines()[-120:],
            "stderr_tail": _strip_ansi(result.stderr).splitlines()[-120:],
            "output_path": str(output_path),
        },
        "memory_context": {
            "result_seen": True,
            "markers_read": markers_read,
            "expected_markers": expected,
            "matches_expected": bool(markers_read) and markers_read == expected,
            "probe_marker": probe_marker,
            "probe_marker_ok": probe_marker == _PROBE_MARKER,
            "cwd": cwd,
            "cwd_matches_workspace": cwd == str(workspace),
            "canonical_observation": _observe_named_paths(canonical_paths),
            "drift_observation": _observe_named_paths(drift_paths),
            "capture_tail": transcript_tail,
            "workspace": str(workspace),
        },
        "prompt_capture_tail": transcript_tail[-120:],
        "session_log": str(log_path),
    }


def _persistence_summary(
    before_restart: dict[str, Any],
    after_restart: dict[str, Any],
) -> dict[str, Any]:
    before_ids = set(before_restart.get("resume_candidates", []))
    after_ids = set(after_restart.get("resume_candidates", []))
    stable_roots = before_restart.get("state_roots") == after_restart.get("state_roots")
    config_persisted = all(after_restart.get("config_present", {}).values())
    roots_present = all(after_restart.get("state_roots_present", {}).values())
    artifacts_non_decreasing = (
        after_restart.get("session_artifact_count", 0)
        >= before_restart.get("session_artifact_count", 0)
    )
    resume_candidates_preserved = before_ids.issubset(after_ids) if before_ids else True
    return {
        "before_restart": before_restart,
        "after_restart": after_restart,
        "stable_state_roots": stable_roots,
        "config_paths_persisted": config_persisted,
        "state_roots_present_after_restart": roots_present,
        "session_artifacts_non_decreasing": artifacts_non_decreasing,
        "resume_candidates_preserved": resume_candidates_preserved,
    }


def _prepare_claude_config_dir(workspace: Path) -> Path:
    source = Path.home() / ".claude"
    target = workspace / ".claude-runtime"
    target.mkdir(parents=True, exist_ok=True)
    for name in (".credentials.json", "projects"):
        src = source / name
        dst = target / name
        if dst.exists() or dst.is_symlink() or not src.exists():
            continue
        dst.symlink_to(src)
    claude_json_src = source / ".claude.json"
    claude_json_dst = target / ".claude.json"
    if not claude_json_dst.exists():
        if claude_json_src.exists():
            claude_json_dst.write_text(claude_json_src.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            claude_json_dst.write_text("{}\n", encoding="utf-8")
    return target


def _prepare_workspace(scenario: Scenario, root: Path) -> tuple[Path, dict[str, str], str]:
    workspace = root / f"{scenario.engine}_runtime"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    shell_env = os.environ.copy()
    start_prefix = ""

    if scenario.engine == "claude":
        config_dir = _prepare_claude_config_dir(workspace)
        _write_agent_runtime_config(
            workspace,
            "claude",
            str(ROOT_DIR),
            permission_mode="bypassPermissions",
        )
        _ensure_probe_allowed_in_claude(workspace)
        _merge_probe_into_mcp_json(workspace)
        # W10: _seed_claude_project_trust removed (credential-blind). Enable probe MCP
        # server in .claude.json only if the file already exists (written by claude CLI).
        claude_json_path = config_dir / ".claude.json"
        if claude_json_path.exists():
            try:
                claude_json = json.loads(claude_json_path.read_text(encoding="utf-8"))
                entry = claude_json.get("projects", {}).get(str(workspace.resolve()), {})
                enabled = entry.setdefault("enabledMcpjsonServers", [])
                if _PROBE_SERVER_NAME not in enabled:
                    enabled.append(_PROBE_SERVER_NAME)
                claude_json_path.write_text(
                    json.dumps(claude_json, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            except (KeyError, json.JSONDecodeError):
                pass
        shell_env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        shell_env["BROWSER"] = "false"
        start_prefix = (
            f"export CLAUDE_CONFIG_DIR={shlex.quote(str(config_dir))} "
            f"BROWSER=false && "
        )
        return workspace, shell_env, start_prefix

    if scenario.engine == "codex":
        _write_agent_runtime_config(
            workspace,
            "codex",
            str(ROOT_DIR),
            permission_mode="bypassPermissions",
        )
        _append_probe_to_codex(workspace)
        codex_home = _codex_home_dir(workspace)
        shell_env["CODEX_HOME"] = str(codex_home)
        start_prefix = f"export CODEX_HOME={shlex.quote(str(codex_home))} && "
        return workspace, shell_env, start_prefix

    if scenario.engine in {"gemini", "qwen"}:
        _write_agent_runtime_config(
            workspace,
            scenario.engine,
            str(ROOT_DIR),
            permission_mode="bypassPermissions",
            allowed_tools=["Bash", "WebFetch", "WebSearch"],
        )
        _append_probe_to_settings(workspace, scenario.engine)
        trust_env = (
            "GEMINI_CLI_TRUSTED_FOLDERS_PATH"
            if scenario.engine == "gemini"
            else "QWEN_CODE_TRUSTED_FOLDERS_PATH"
        )
        trust_path = _trusted_folders_file_path(workspace, scenario.engine)
        shell_env[trust_env] = str(trust_path)
        start_prefix = f"export {trust_env}={shlex.quote(str(trust_path))} && "
        return workspace, shell_env, start_prefix

    raise ValueError(f"unsupported engine: {scenario.engine}")


def _start_command(scenario: Scenario, workspace: Path, start_prefix: str) -> str:
    spec = _tmux_engine_spec(scenario.engine)
    command = spec.start_shell
    if scenario.engine == "claude":
        command += " --permission-mode bypassPermissions"
    elif scenario.engine == "codex":
        command += " -s workspace-write -a never"
    elif scenario.engine == "gemini":
        command += (
            f" --approval-mode yolo --include-directories {shlex.quote(str(ROOT_DIR))}"
        )
    elif scenario.engine == "qwen":
        command += (
            f" --approval-mode yolo --include-directories {shlex.quote(str(ROOT_DIR))}"
        )
    return start_prefix + command


def _probe_prompt(engine: str, *, include_memory_context: bool = False) -> str:
    if include_memory_context and engine == "codex":
        return (
            "Use the MCP tool probe_ping with message "
            f"'{engine}-live-check'. "
            "Use a shell command to read ./AGENTS.md, ./MEMORY.md, and ./CONTEXT_BRIDGE.md. "
            "Then answer with ONLY one line in this exact format: "
            'DRILL_RESULT::{"probe_marker":"...","agents_marker":"...","memory_marker":"...","context_marker":"...","cwd":"..."} '
            "using the exact values from probe_ping.marker and the DRILL_*_MARKER lines."
        )
    return (
        "Use the MCP tool probe_ping with message "
        f"'{engine}-live-check' and then answer with ONLY the marker field."
    )


def _wait_for_capture_token(
    session_name: str,
    token: str,
    *,
    timeout: int = 35,
) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last_capture = ""
    while time.time() < deadline:
        last_capture = _capture(session_name)
        if token in last_capture:
            return True, last_capture
        time.sleep(2)
    return False, last_capture


def _extract_drill_result(capture: str) -> dict[str, str] | None:
    match = re.search(rf"{re.escape(_DRILL_RESULT_PREFIX)}\s*(\{{.*?\}})", capture, re.S)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    result: dict[str, str] = {}
    for key in ("agents_marker", "memory_marker", "context_marker"):
        value = payload.get(key)
        if not isinstance(value, str):
            return None
        result[key] = value
    return result


def _wait_for_marker(session_name: str, *, timeout: int = 30) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last_capture = ""
    while time.time() < deadline:
        last_capture = _capture(session_name)
        if _PROBE_MARKER in last_capture:
            return True, last_capture
        time.sleep(2)
    return False, last_capture


def _maybe_accept_prompt(session_name: str, engine: str) -> None:
    snapshot = _capture(session_name)
    approval_hints = ("Allow", "allow", "Approve", "approve", "Run tool", "Continue")
    if engine == "gemini" and any(token in snapshot for token in approval_hints):
        _tmux(["send-keys", "-t", session_name, "Enter"], timeout=10)
    if engine == "qwen" and any(token in snapshot for token in approval_hints):
        _tmux(["send-keys", "-t", session_name, "Enter"], timeout=10)


def _close_slash_overlay_if_needed(session_name: str, scenario: Scenario, capture: str) -> str:
    overlay_hints = (
        "Esc to cancel",
        "Press Esc to close",
        "Type to filter",
        "Use ↑↓ to navigate",
        "Use up/down to navigate",
    )
    if any(token in capture for token in overlay_hints):
        _tmux(["send-keys", "-t", session_name, "Escape"], timeout=10)
        time.sleep(1.5)
        return _capture(session_name)
    if _capture_has_ready_prompt(capture, _tmux_engine_spec(scenario.engine).ready_prompt_regex):
        return capture
    return capture


def _shell_list(scenario: Scenario, workspace: Path, env: dict[str, str]) -> dict[str, Any]:
    if not scenario.shell_list_command:
        return {
            "command": [],
            "returncode": 0,
            "stdout_tail": [],
            "stderr_tail": [],
        }
    result = _run(list(scenario.shell_list_command), cwd=workspace, env=env, timeout=40)
    return {
        "command": list(scenario.shell_list_command),
        "returncode": result.returncode,
        "stdout_tail": _strip_ansi(result.stdout).splitlines()[-80:],
        "stderr_tail": _strip_ansi(result.stderr).splitlines()[-80:],
    }


def _start_session(
    scenario: Scenario,
    workspace: Path,
    *,
    session_name: str,
    start_prefix: str,
    log_path: Path,
    progress_callback: callable | None = None,
    cycle_index: int | None = None,
) -> tuple[bool, str]:
    session_created = False
    phase_prefix = f"cycle_{cycle_index}" if cycle_index is not None else "cycle"
    try:
        _tmux(["new-session", "-d", "-s", session_name, "-c", str(workspace)], timeout=10)
        session_created = True
        if progress_callback is not None:
            progress_callback(
                phase=f"{phase_prefix}_tmux_session_created",
                cycle_index=cycle_index,
                session_name=session_name,
                session_log=str(log_path),
            )
        _tmux(["pipe-pane", "-o", "-t", session_name, f"cat >> {shlex.quote(str(log_path))}"], timeout=10)
        _tmux(["send-keys", "-t", session_name, _start_command(scenario, workspace, start_prefix), "Enter"], timeout=10)
        if progress_callback is not None:
            progress_callback(
                phase=f"{phase_prefix}_startup_stabilizing",
                cycle_index=cycle_index,
                session_name=session_name,
            )
        if scenario.engine == "claude":
            _stabilize_claude_startup(session_name, permission_mode="bypassPermissions", timeout=20)
        elif scenario.engine == "codex":
            _stabilize_codex_startup(session_name, timeout=20)
        elif scenario.engine == "gemini":
            _stabilize_gemini_startup(session_name, timeout=20)
        if progress_callback is not None:
            progress_callback(
                phase=f"{phase_prefix}_prompt_wait",
                cycle_index=cycle_index,
                session_name=session_name,
            )
        spec = _tmux_engine_spec(scenario.engine)
        return _wait_for_prompt(session_name, spec.ready_prompt_regex, timeout=120)
    except BaseException:
        if session_created:
            _kill_session(session_name)
        raise


def _interactive_probe(
    session_name: str,
    scenario: Scenario,
    workspace: Path,
    drill: dict[str, Any],
) -> dict[str, Any]:
    spec = _tmux_engine_spec(scenario.engine)
    evidence: dict[str, Any] = {"commands": []}
    for command in scenario.slash_commands:
        before = _capture(session_name)
        _paste_buffer(session_name, command, enter_count=spec.submit_enter_count)
        time.sleep(4)
        after = _close_slash_overlay_if_needed(session_name, scenario, _capture(session_name))
        evidence["commands"].append(
            {
                "command": command,
                "before_tail": before.splitlines()[-20:],
                "after_tail": after.splitlines()[-60:],
            }
        )
    drill_enabled = bool(drill and scenario.engine == "codex")
    _paste_buffer(
        session_name,
        _probe_prompt(scenario.engine, include_memory_context=drill_enabled),
        enter_count=spec.submit_enter_count,
    )
    time.sleep(8)
    _maybe_accept_prompt(session_name, scenario.engine)
    if drill_enabled:
        marker_seen, final_capture = _wait_for_capture_token(
            session_name,
            _DRILL_RESULT_PREFIX,
            timeout=45,
        )
        markers_read = _extract_drill_result(final_capture) or {}
        canonical_paths = {
            name: Path(path) for name, path in drill.get("canonical_paths", {}).items()
        }
        drift_paths = {
            name: Path(path) for name, path in drill.get("drift_paths", {}).items()
        }
        expected = drill.get("markers", {})
        evidence["memory_context"] = {
            "result_seen": marker_seen,
            "markers_read": markers_read,
            "expected_markers": expected,
            "matches_expected": bool(markers_read) and markers_read == expected,
            "canonical_observation": _observe_named_paths(canonical_paths),
            "drift_observation": _observe_named_paths(drift_paths),
            "capture_tail": final_capture.splitlines()[-160:],
            "workspace": str(workspace),
        }
        evidence["probe_marker_seen"] = _PROBE_MARKER in final_capture
    else:
        marker_seen, final_capture = _wait_for_marker(session_name, timeout=35)
        evidence["probe_marker_seen"] = marker_seen
    evidence["probe_prompt_tail"] = final_capture.splitlines()[-120:]
    return evidence


def _run_cycle(
    scenario: Scenario,
    workspace: Path,
    shell_env: dict[str, str],
    *,
    cycle_index: int,
    start_prefix: str,
    drill: dict[str, Any],
    progress_callback: callable | None = None,
) -> dict[str, Any]:
    if scenario.engine == "codex" and drill:
        return _run_codex_exec_cycle(
            workspace,
            cycle_index=cycle_index,
            drill=drill,
            progress_callback=progress_callback,
        )

    del shell_env
    session_name = scenario.session_name
    log_path = workspace / f"session_{cycle_index}.log"
    log_path.touch(exist_ok=True)
    started = False
    prompt_ok = False
    prompt_capture = ""
    interactive: dict[str, Any] = {}
    if progress_callback is not None:
        progress_callback(
            phase=f"cycle_{cycle_index}_start",
            cycle_index=cycle_index,
            session_name=session_name,
            session_log=str(log_path),
        )
    try:
        prompt_ok, prompt_capture = _start_session(
            scenario,
            workspace,
            session_name=session_name,
            start_prefix=start_prefix,
            log_path=log_path,
            progress_callback=progress_callback,
            cycle_index=cycle_index,
        )
        started = True
        if prompt_ok:
            if progress_callback is not None:
                progress_callback(
                    phase=f"cycle_{cycle_index}_interactive_probe",
                    cycle_index=cycle_index,
                    session_name=session_name,
                    session_log=str(log_path),
                )
            interactive = _interactive_probe(session_name, scenario, workspace, drill)
    finally:
        if started:
            _kill_session(session_name)
    haystack = "\n".join(
        [
            prompt_capture,
            "\n".join("\n".join(item["after_tail"]) for item in interactive.get("commands", [])),
            "\n".join(interactive.get("probe_prompt_tail", [])),
        ]
    )
    return {
        "cycle_index": cycle_index,
        "prompt_ready": prompt_ok,
        "slash_ok": all(
            command["after_tail"] != command["before_tail"]
            for command in interactive.get("commands", [])
        ),
        "probe_listed": _PROBE_SERVER_NAME in haystack,
        "probe_marker_seen": _PROBE_MARKER in haystack,
        "interactive": interactive,
        "memory_context": interactive.get("memory_context", {}),
        "prompt_capture_tail": prompt_capture.splitlines()[-120:],
        "session_log": str(log_path),
    }


def _memory_context_summary(
    drill: dict[str, Any],
    cycles: list[dict[str, Any]],
) -> dict[str, Any]:
    if not drill:
        return {}

    cycle_results = [
        {
            "cycle_index": cycle.get("cycle_index"),
            **cycle.get("memory_context", {}),
        }
        for cycle in cycles
        if cycle.get("memory_context")
    ]
    if not cycle_results:
        return {
            "markers": drill.get("markers", {}),
            "canonical_paths": drill.get("canonical_paths", {}),
            "drift_paths": drill.get("drift_paths", {}),
            "cycle_results": [],
            "marker_reads_ok": False,
            "restore_consistent": False,
            "restore_attempted": False,
            "canonical_paths_unchanged": False,
            "drift_paths_unchanged": False,
            "cwd_matches_workspace": False,
            "probe_marker_consistent": False,
        }

    baseline = drill.get("baseline", {})
    expected_markers = drill.get("markers", {})
    last_result = cycle_results[-1]
    marker_reads_ok = all(item.get("matches_expected") for item in cycle_results)
    restore_attempted = len(cycle_results) > 1
    first_markers = cycle_results[0].get("markers_read", {})
    restore_consistent = restore_attempted and bool(first_markers) and all(
        item.get("markers_read") == first_markers for item in cycle_results[1:]
    )
    cwd_matches_workspace = bool(cycle_results) and all(
        item.get("cwd_matches_workspace") is True for item in cycle_results
    )
    probe_marker_consistent = bool(cycle_results) and all(
        item.get("probe_marker_ok") is True for item in cycle_results
    )
    canonical_after = last_result.get("canonical_observation", {})
    drift_after = last_result.get("drift_observation", {})
    return {
        "markers": expected_markers,
        "canonical_paths": drill.get("canonical_paths", {}),
        "drift_paths": drill.get("drift_paths", {}),
        "cycle_results": cycle_results,
        "marker_reads_ok": marker_reads_ok,
        "restore_consistent": restore_consistent,
        "restore_attempted": restore_attempted,
        "canonical_paths_unchanged": _observations_match(
            baseline.get("canonical", {}),
            canonical_after,
        ),
        "drift_paths_unchanged": _observations_match(
            baseline.get("drift", {}),
            drift_after,
        ),
        "cwd_matches_workspace": cwd_matches_workspace,
        "probe_marker_consistent": probe_marker_consistent,
    }


def _scenario_matrix() -> list[Scenario]:
    return [
        Scenario(engine="claude", slash_commands=("/help",)),
        Scenario(engine="codex", slash_commands=("/",), shell_list_command=("codex", "mcp", "list")),
        Scenario(
            engine="gemini",
            slash_commands=("/help", "/mcp list"),
            shell_list_command=("gemini", "mcp", "list"),
        ),
        Scenario(
            engine="qwen",
            slash_commands=("/help", "/mcp"),
            shell_list_command=("qwen", "mcp", "list"),
        ),
    ]


def _selected_scenarios(engine_csv: str) -> list[Scenario]:
    requested = {item.strip() for item in engine_csv.split(",") if item.strip()}
    scenarios = _scenario_matrix()
    if not requested:
        return scenarios
    return [scenario for scenario in scenarios if scenario.engine in requested]


def _scenario_failure_result(scenario: Scenario, root: Path, exc: Exception) -> dict[str, Any]:
    workspace = root / f"{scenario.engine}_runtime"
    cli_sot = _safe_cli_sot_snapshot(scenario, workspace)
    return {
        "engine": scenario.engine,
        "workspace": str(workspace),
        "error": _error_text(exc),
        "shell": {"command": [], "returncode": 0, "stdout_tail": [], "stderr_tail": []},
        "prompt_ready": False,
        "slash_ok": False,
        "probe_listed": False,
        "probe_marker_seen": False,
        "interactive": {},
        "session_log": "",
        "session_logs": [],
        "cycles": [],
        "cli_sot": cli_sot,
        "cli_sot_ok": all(cli_sot.get("config_present", {}).values())
        and all(cli_sot.get("state_roots_present", {}).values()),
        "memory_context": {},
        "persistence": {},
        "persistence_ok": False,
        "restart_ok": False,
        "all_cycles_ok": False,
        "progress": {},
    }


def _result_signal(result: dict[str, Any]) -> str:
    error = str(result.get("error", "")).strip()
    if error:
        return "BLOCKED" if _is_blocked_error(error) else "FAIL"
    if (
        result.get("prompt_ready")
        and result.get("slash_ok")
        and result.get("probe_listed")
        and result.get("probe_marker_seen")
        and result.get("cli_sot_ok")
        and result.get("persistence_ok")
        and result.get("restart_ok")
    ):
        return "SUCCESS"
    return "FAIL"


def _matrix_entry(
    point: int,
    title: str,
    status: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "point": point,
        "title": title,
        "status": status,
        "detail": detail,
    }


def _build_verification_matrix(result: dict[str, Any]) -> list[dict[str, Any]]:
    signal_name = _result_signal(result)
    blocked = signal_name == "BLOCKED"
    cli_sot = result.get("cli_sot", {})
    memory_context = result.get("memory_context", {})
    persistence = result.get("persistence", {})
    persisted_resume_candidates = [
        *persistence.get("before_restart", {}).get("resume_candidates", []),
        *persistence.get("after_restart", {}).get("resume_candidates", []),
    ]
    resume_candidates = sorted(
        {
            str(candidate)
            for candidate in [*cli_sot.get("resume_candidates", []), *persisted_resume_candidates]
            if candidate
        }
    )
    restart_cycles = max(len(result.get("cycles", [])) - 1, 0)
    progress = result.get("progress", {})
    progress_phase = str(progress.get("phase", ""))
    progress_cycle_index = int(progress.get("cycle_index", 0) or 0)
    restart_attempted = restart_cycles > 0 or progress_cycle_index >= 1 or progress_phase.startswith("cycle_1_")
    error = str(result.get("error", "")).strip()
    matrix: list[dict[str, Any]] = []
    point_status_1 = "SUCCESS" if result.get("cli_sot_ok") else ("BLOCKED" if blocked else "FAIL")
    point_detail_1 = (
        f"config_present={cli_sot.get('config_present', {})}, "
        f"state_roots_present={cli_sot.get('state_roots_present', {})}"
    )
    if result.get("engine") == "codex":
        point_status_1 = (
            "SUCCESS"
            if (
                result.get("cli_sot_ok")
                and memory_context.get("cwd_matches_workspace")
                and memory_context.get("probe_marker_consistent")
            )
            else ("BLOCKED" if blocked else "FAIL")
        )
        point_detail_1 = (
            f"config_present={cli_sot.get('config_present', {})}, "
            f"state_roots_present={cli_sot.get('state_roots_present', {})}, "
            f"cwd_matches_workspace={memory_context.get('cwd_matches_workspace')}, "
            f"probe_marker_consistent={memory_context.get('probe_marker_consistent')}"
        )
    matrix.append(_matrix_entry(1, _VERIFICATION_POINTS[0][1], point_status_1, point_detail_1))

    if blocked and not resume_candidates:
        status_2 = "BLOCKED"
        detail_2 = error or "CLI-Resume konnte im Harness nicht bis zu einer belastbaren Kandidatenlage laufen."
    elif result.get("persistence_ok") and resume_candidates:
        status_2 = "SUCCESS"
        detail_2 = f"resume_candidates={resume_candidates}"
    else:
        status_2 = "FAIL"
        detail_2 = (
            f"persistence_ok={result.get('persistence_ok')}, "
            f"resume_candidates={resume_candidates}"
        )
    matrix.append(_matrix_entry(2, _VERIFICATION_POINTS[1][1], status_2, detail_2))

    if not memory_context:
        status_3 = "BLOCKED"
        detail_3 = "Dieser Harnesslauf hat keinen abgeschlossenen Memory-/Context-Drill geliefert."
    elif (
        memory_context.get("marker_reads_ok")
        and memory_context.get("restore_consistent")
        and memory_context.get("canonical_paths_unchanged")
        and memory_context.get("drift_paths_unchanged")
        and memory_context.get("cwd_matches_workspace")
        and memory_context.get("probe_marker_consistent")
    ):
        status_3 = "SUCCESS"
        detail_3 = (
            f"markers={memory_context.get('markers', {})}, "
            f"restore_consistent={memory_context.get('restore_consistent')}, "
            f"drift_paths_unchanged={memory_context.get('drift_paths_unchanged')}, "
            f"cwd_matches_workspace={memory_context.get('cwd_matches_workspace')}"
        )
    elif memory_context.get("marker_reads_ok") and not memory_context.get("restore_attempted"):
        status_3 = "BLOCKED"
        detail_3 = "Kanonische Memory-/Context-Dateien wurden gelesen, aber kein Restore-Zyklus wurde ausgeführt."
    else:
        status_3 = "FAIL"
        detail_3 = (
            f"marker_reads_ok={memory_context.get('marker_reads_ok')}, "
            f"restore_consistent={memory_context.get('restore_consistent')}, "
            f"canonical_paths_unchanged={memory_context.get('canonical_paths_unchanged')}, "
            f"drift_paths_unchanged={memory_context.get('drift_paths_unchanged')}, "
            f"cwd_matches_workspace={memory_context.get('cwd_matches_workspace')}, "
            f"probe_marker_consistent={memory_context.get('probe_marker_consistent')}"
        )
    matrix.append(
        _matrix_entry(
            3,
            _VERIFICATION_POINTS[2][1],
            status_3,
            detail_3,
        )
    )
    matrix.append(
        _matrix_entry(
            4,
            _VERIFICATION_POINTS[3][1],
            "BLOCKED",
            "Retrieval-Zwang ist im aktuellen Harness-Slice nicht direkt messbar.",
        )
    )
    matrix.append(
        _matrix_entry(
            5,
            _VERIFICATION_POINTS[4][1],
            "BLOCKED",
            "Multi-Incarnation erfordert parallele Session-/Register-Kollisionstests ausserhalb dieses Single-Scenario-Harness.",
        )
    )

    if not restart_attempted:
        status_6 = "BLOCKED"
        detail_6 = "Kein Restart-Zyklus ausgeführt; Startpfad verifiziert, Restartpfad nicht verifiziert."
    else:
        status_6 = "SUCCESS" if result.get("restart_ok") and result.get("persistence_ok") else ("BLOCKED" if blocked else "FAIL")
        detail_6 = (
            f"restart_cycles={restart_cycles}, "
            f"restart_ok={result.get('restart_ok')}, "
            f"persistence_ok={result.get('persistence_ok')}, "
            f"signal={signal_name}"
        )
    matrix.append(_matrix_entry(6, _VERIFICATION_POINTS[5][1], status_6, detail_6))

    matrix.append(
        _matrix_entry(
            7,
            _VERIFICATION_POINTS[6][1],
            "BLOCKED",
            "Diary-/Journal-Compact-Pipeline wird in diesem Harness nicht instrumentiert.",
        )
    )

    status_8 = "SUCCESS" if result.get("all_cycles_ok") and result.get("cli_sot_ok") and result.get("persistence_ok") else ("BLOCKED" if blocked else "FAIL")
    detail_8 = (
        f"all_cycles_ok={result.get('all_cycles_ok')}, "
        f"cli_sot_ok={result.get('cli_sot_ok')}, "
        f"persistence_ok={result.get('persistence_ok')}, "
        f"error={error or '<none>'}"
    )
    matrix.append(_matrix_entry(8, _VERIFICATION_POINTS[7][1], status_8, detail_8))

    status_9 = "SUCCESS" if not blocked else "FAIL"
    detail_9 = (
        "Keine aktuell erkannte Legacy-/Prereq-Abweichung im Harnesspfad."
        if status_9 == "SUCCESS"
        else (error or "Legacy-/Prereq-Abweichung blockiert die Verifikation.")
    )
    matrix.append(_matrix_entry(9, _VERIFICATION_POINTS[8][1], status_9, detail_9))
    return matrix


def _decorate_result(result: dict[str, Any]) -> dict[str, Any]:
    matrix = _build_verification_matrix(result)
    result["signal"] = _result_signal(result)
    result["verification_matrix"] = matrix
    result["verified_points"] = [entry["point"] for entry in matrix if entry["status"] == "SUCCESS"]
    result["open_not_verified_points"] = [
        {
            "point": entry["point"],
            "title": entry["title"],
            "status": entry["status"],
            "detail": entry["detail"],
        }
        for entry in matrix
        if entry["status"] != "SUCCESS"
    ]
    return result


def _apply_verification_summary(payload: dict[str, Any]) -> None:
    completed_results = [
        result
        for result in payload.get("results", [])
        if isinstance(result, dict) and result.get("verification_matrix")
    ]
    if not completed_results:
        payload["verification_summary"] = []
        payload["open_not_verified_points"] = []
        return

    summary: list[dict[str, Any]] = []
    for point, title in _VERIFICATION_POINTS:
        per_engine = [
            {
                "engine": str(result.get("engine", "")),
                "status": str(entry.get("status", "BLOCKED")),
                "detail": str(entry.get("detail", "")),
            }
            for result in completed_results
            for entry in result.get("verification_matrix", [])
            if entry.get("point") == point
        ]
        statuses = {entry["status"] for entry in per_engine}
        if not per_engine:
            status = "BLOCKED"
            detail = "Kein abgeschlossenes Szenario fuer diesen Punkt vorhanden."
        elif "FAIL" in statuses:
            status = "FAIL"
            detail = "Mindestens ein abgeschlossenes Szenario ist fehlgeschlagen."
        elif "BLOCKED" in statuses:
            status = "BLOCKED"
            detail = "Mindestens ein abgeschlossenes Szenario blieb blockiert."
        else:
            status = "SUCCESS"
            detail = "Alle abgeschlossenen Szenarien haben diesen Punkt verifiziert."
        summary.append(
            {
                "point": point,
                "title": title,
                "status": status,
                "detail": detail,
                "per_engine": per_engine,
            }
        )

    payload["verification_summary"] = summary
    payload["open_not_verified_points"] = [
        {
            "point": entry["point"],
            "title": entry["title"],
            "status": entry["status"],
            "detail": entry["detail"],
            "per_engine": entry["per_engine"],
        }
        for entry in summary
        if entry["status"] != "SUCCESS"
    ]


def run_scenario(
    scenario: Scenario,
    root: Path,
    *,
    restart_count: int = 1,
    progress_callback: callable | None = None,
) -> dict[str, Any]:
    if progress_callback is not None:
        progress_callback(phase="prepare_workspace")
    workspace, shell_env, start_prefix = _prepare_workspace(scenario, root)
    memory_context_drill = _seed_memory_context_drill(scenario, workspace, root)
    if progress_callback is not None:
        progress_callback(
            phase="workspace_prepared",
            workspace=str(workspace),
        )
        if memory_context_drill:
            progress_callback(
                phase="memory_context_drill_seeded",
                workspace=str(workspace),
            )
        progress_callback(
            phase="shell_list_started",
            workspace=str(workspace),
        )
    shell = _shell_list(scenario, workspace, shell_env)
    if progress_callback is not None:
        progress_callback(
            phase="shell_list_completed",
            workspace=str(workspace),
            shell_returncode=shell["returncode"],
        )
        progress_callback(
            phase="cli_sot_snapshot_started",
            workspace=str(workspace),
        )
    cli_sot = _native_state_snapshot(scenario, workspace)
    if progress_callback is not None:
        progress_callback(
            phase="cli_sot_snapshot_completed",
            workspace=str(workspace),
            session_artifact_count=cli_sot.get("session_artifact_count", 0),
        )
    cycles = [
        _run_cycle(
            scenario,
            workspace,
            shell_env,
            cycle_index=0,
            start_prefix=start_prefix,
            drill=memory_context_drill,
            progress_callback=progress_callback,
        )
    ]
    if progress_callback is not None:
        progress_callback(
            phase="cycle_0_completed",
            workspace=str(workspace),
            cycle_index=0,
            session_log=cycles[0]["session_log"],
        )
    before_restart = _native_state_snapshot(scenario, workspace)
    for cycle_index in range(1, restart_count + 1):
        cycles.append(
            _run_cycle(
                scenario,
                workspace,
                shell_env,
                cycle_index=cycle_index,
                start_prefix=start_prefix,
                drill=memory_context_drill,
                progress_callback=progress_callback,
            )
        )
        if progress_callback is not None:
            progress_callback(
                phase=f"cycle_{cycle_index}_completed",
                workspace=str(workspace),
                cycle_index=cycle_index,
                session_log=cycles[cycle_index]["session_log"],
            )
    after_restart = _native_state_snapshot(scenario, workspace)
    persistence = _persistence_summary(before_restart, after_restart)
    cli_sot_ok = all(cli_sot["config_present"].values()) and all(
        cli_sot["state_roots_present"].values()
    )
    restart_ok = all(
        cycle["prompt_ready"]
        and cycle["slash_ok"]
        and cycle["probe_listed"]
        and cycle["probe_marker_seen"]
        for cycle in cycles[1:]
    )
    all_cycles_ok = all(
        cycle["prompt_ready"]
        and cycle["slash_ok"]
        and cycle["probe_listed"]
        and cycle["probe_marker_seen"]
        for cycle in cycles
    )
    persistence_ok = (
        persistence["stable_state_roots"]
        and persistence["config_paths_persisted"]
        and persistence["state_roots_present_after_restart"]
        and persistence["session_artifacts_non_decreasing"]
        and persistence["resume_candidates_preserved"]
    )
    memory_context = _memory_context_summary(memory_context_drill, cycles)
    return {
        "engine": scenario.engine,
        "workspace": str(workspace),
        "shell": shell,
        "prompt_ready": all(cycle["prompt_ready"] for cycle in cycles),
        "slash_ok": all(cycle["slash_ok"] for cycle in cycles),
        "probe_listed": all(cycle["probe_listed"] for cycle in cycles),
        "probe_marker_seen": all(cycle["probe_marker_seen"] for cycle in cycles),
        "interactive": cycles[0]["interactive"],
        "session_log": cycles[-1]["session_log"],
        "session_logs": [cycle["session_log"] for cycle in cycles],
        "cycles": cycles,
        "cli_sot": cli_sot,
        "cli_sot_ok": cli_sot_ok,
        "memory_context": memory_context,
        "persistence": persistence,
        "persistence_ok": persistence_ok,
        "restart_ok": restart_ok,
        "all_cycles_ok": all_cycles_ok,
    }


def _make_progress_updater(
    scenario_state: dict[str, Any],
    payload: dict[str, Any],
    *,
    json_output: str,
) -> callable:
    def _update(**details: Any) -> None:
        progress = dict(scenario_state.get("progress", {}))
        progress.update(details)
        progress["updated_at"] = _now_utc()
        scenario_state["progress"] = progress
        scenario_state["status"] = "running"
        payload["last_updated_at"] = progress["updated_at"]
        if json_output:
            _write_json_file(json_output, payload)

    return _update


def _execute_scenario(
    scenario: Scenario,
    root: Path,
    *,
    restart_count: int,
    scenario_timeout: int,
    scenario_state: dict[str, Any],
    payload: dict[str, Any],
    json_output: str,
) -> dict[str, Any]:
    progress_update = _make_progress_updater(
        scenario_state,
        payload,
        json_output=json_output,
    )
    try:
        with _ScenarioAlarm(
            scenario_timeout,
            engine=scenario.engine,
            progress_getter=lambda: scenario_state.get("progress", {}),
        ):
            result = run_scenario(
                scenario,
                root,
                restart_count=restart_count,
                progress_callback=progress_update,
            )
    except Exception as exc:
        result = _scenario_failure_result(scenario, root, exc)
        result["progress"] = dict(scenario_state.get("progress", {}))
        return _decorate_result(result)
    result["progress"] = dict(scenario_state.get("progress", {}))
    return _decorate_result(result)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live E2E verification for CLI MCP loading, persistence, and restart."
    )
    parser.add_argument(
        "--workspace-root",
        default=str(Path(tempfile.gettempdir()) / "bridge_cli_runtime"),
        help="Temporary workspace root for live CLI sessions.",
    )
    parser.add_argument(
        "--engines",
        default="claude,codex,gemini,qwen",
        help="Comma-separated engine list to verify.",
    )
    parser.add_argument(
        "--restart-count",
        type=int,
        default=1,
        help="How many fresh restarts to verify after the initial cycle.",
    )
    parser.add_argument(
        "--scenario-timeout",
        type=int,
        default=180,
        help="Hard timeout in seconds for one scenario; 0 disables the guard.",
    )
    parser.add_argument(
        "--json-output",
        default="",
        help="Optional JSON report output path.",
    )
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)

    scenarios = _selected_scenarios(args.engines)
    if not scenarios:
        parser.error(f"No matching engines for --engines={args.engines!r}")

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_updated_at": _now_utc(),
        "status": "running",
        "probe_marker": _PROBE_MARKER,
        "engines": [scenario.engine for scenario in scenarios],
        "restart_count": max(args.restart_count, 0),
        "scenario_timeout": max(args.scenario_timeout, 0),
        "results": [
            {
                "engine": scenario.engine,
                "status": "queued",
                "progress": {
                    "phase": "queued",
                    "updated_at": _now_utc(),
                },
            }
            for scenario in scenarios
        ],
    }
    _apply_verification_summary(payload)
    if args.json_output:
        _write_json_file(args.json_output, payload)
    failures: list[dict[str, Any]] = []
    for idx, scenario in enumerate(scenarios):
        scenario_state = payload["results"][idx]
        scenario_state["status"] = "running"
        scenario_state["progress"] = {
            "phase": "scheduled",
            "updated_at": _now_utc(),
        }
        if args.json_output:
            _write_json_file(args.json_output, payload)
        result = _execute_scenario(
            scenario,
            workspace_root,
            restart_count=max(args.restart_count, 0),
            scenario_timeout=max(args.scenario_timeout, 0),
            scenario_state=scenario_state,
            payload=payload,
            json_output=args.json_output,
        )
        result["status"] = result.get("signal", "FAIL").lower()
        payload["results"][idx] = result
        payload["last_updated_at"] = _now_utc()
        _apply_verification_summary(payload)
        if args.json_output:
            _write_json_file(args.json_output, payload)
        if result.get("signal") != "SUCCESS":
            failures.append(result)
    payload["status"] = "ok" if not failures else "failed"
    payload["last_updated_at"] = _now_utc()
    _apply_verification_summary(payload)
    output = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.json_output:
        _write_json_file(args.json_output, payload)
    print(output)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
