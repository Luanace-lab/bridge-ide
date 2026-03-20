"""CLI detection, probing, and agent home materialisation helpers.

Extracted from server.py (Slice 01).
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from persistence_utils import instruction_filename_for_engine

# ---------------------------------------------------------------------------
# Module-level globals (were in server.py)
# ---------------------------------------------------------------------------

_SETUP_CLI_BINARIES: dict[str, str] = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
    "qwen": "qwen",
}

_SETUP_API_ENV_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

_CLI_SETUP_STATE_LOCK = threading.Lock()
_CLI_SETUP_STATE_INFLIGHT: dict[bool, threading.Event] = {}
_CLI_SETUP_STATE_CACHE: dict[bool, dict[str, Any]] = {}
_CLI_SETUP_STATE_CACHE_AT: dict[bool, float] = {}
_CLI_SETUP_STATE_CACHE_TTL_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Helpers (not in the original extraction list but required by listed functions)
# ---------------------------------------------------------------------------

def _infer_subscription_provider(sub_path: str, provider: str = "") -> str:
    explicit = str(provider or "").strip().lower()
    if explicit:
        return explicit
    path_text = str(sub_path or "").strip().rstrip("/")
    if not path_text:
        return ""
    base = os.path.basename(path_text).lower()
    if base.startswith(".claude"):
        return "claude"
    if base == ".codex":
        return "openai"
    if base == ".gemini":
        return "gemini"
    if base == ".qwen":
        return "qwen"
    return ""


def _probe_claude_profile_state(config_dir: str) -> dict[str, str]:
    config_root = str(config_dir or "").strip()
    if not config_root:
        return {
            "profile_status": "unknown",
            "profile_probe": "claude auth status",
            "profile_note": "No Claude profile path configured",
            "observed_email": "",
            "observed_subscription_type": "",
        }
    binary_path = shutil.which("claude")
    if not binary_path:
        return {
            "profile_status": "degraded",
            "profile_probe": "claude auth status",
            "profile_note": "Claude CLI not installed",
            "observed_email": "",
            "observed_subscription_type": "",
        }
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = config_root
    env.pop("CLAUDECODE", None)
    rc, stdout, stderr = _run_cli_probe(
        [binary_path, "auth", "status"],
        timeout=10.0,
        env=env,
    )
    combined = "\n".join(part for part in (stdout, stderr) if part).strip()
    observed_email = ""
    observed_subscription_type = ""
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            observed_email = str(payload.get("email", "")).strip()
            observed_subscription_type = str(payload.get("subscriptionType", "")).strip()
            if payload.get("loggedIn") is True:
                note = observed_email or str(payload.get("authMethod", "")).strip() or "Official Claude auth detected"
                return {
                    "profile_status": "ready",
                    "profile_probe": "claude auth status",
                    "profile_note": note,
                    "observed_email": observed_email,
                    "observed_subscription_type": observed_subscription_type,
                }
            if payload.get("loggedIn") is False:
                return {
                    "profile_status": "login_required",
                    "profile_probe": "claude auth status",
                    "profile_note": "Claude auth status reports logged out",
                    "observed_email": observed_email,
                    "observed_subscription_type": observed_subscription_type,
                }
    lowered = combined.lower()
    if "not logged" in lowered or "login" in lowered:
        status = "login_required"
    elif rc == 0 and combined:
        status = "ready"
    else:
        status = "degraded" if combined else "unknown"
    return {
        "profile_status": status,
        "profile_probe": "claude auth status",
        "profile_note": combined or "Claude auth status inconclusive",
        "observed_email": observed_email,
        "observed_subscription_type": observed_subscription_type,
    }


# ---------------------------------------------------------------------------
# Listed functions (copied 1:1 from server.py)
# ---------------------------------------------------------------------------

def write_file_if_missing(path: str, content: str, overwrite: bool) -> tuple[bool, str]:
    if os.path.exists(path) and not overwrite:
        return False, "exists"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return True, "written"


def _run_cli_probe(
    command: list[str],
    *,
    timeout: float = 5.0,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError:
        return (127, "", "not found")
    except subprocess.TimeoutExpired as exc:
        stdout = str(exc.stdout or "").strip()
        stderr = str(exc.stderr or "").strip() or "timed out"
        return (124, stdout, stderr)
    except OSError as exc:
        return (126, "", str(exc))
    return (result.returncode, result.stdout.strip(), result.stderr.strip())


def _probe_cli_auth_status(cli_name: str, binary_path: str) -> dict[str, str]:
    if cli_name == "claude":
        probe = [binary_path, "auth", "status"]
        rc, stdout, stderr = _run_cli_probe(probe)
        combined = "\n".join(part for part in (stdout, stderr) if part).strip()
        if rc == 0:
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                payload = {}
            if payload.get("loggedIn") is True:
                note = (
                    str(payload.get("email", "")).strip()
                    or str(payload.get("authMethod", "")).strip()
                    or "Official Claude auth detected"
                )
                return {
                    "status": "authenticated",
                    "probe": "claude auth status",
                    "note": note,
                }
            if payload.get("loggedIn") is False:
                return {
                    "status": "unauthenticated",
                    "probe": "claude auth status",
                    "note": "Claude auth status reports logged out",
                }
            return {
                "status": "unknown",
                "probe": "claude auth status",
                "note": combined or "Claude auth status inconclusive",
            }
        lowered = combined.lower()
        if "not logged" in lowered or "login" in lowered:
            status = "unauthenticated"
        else:
            status = "unknown"
        return {
            "status": status,
            "probe": "claude auth status",
            "note": combined or "Claude auth status probe failed",
        }

    if cli_name == "codex":
        probe = [binary_path, "login", "status"]
        rc, stdout, stderr = _run_cli_probe(probe)
        combined = "\n".join(part for part in (stdout, stderr) if part).strip()
        lowered = combined.lower()
        if rc == 0 and "logged in" in lowered:
            return {
                "status": "authenticated",
                "probe": "codex login status",
                "note": combined.splitlines()[0].strip() or "Official Codex auth detected",
            }
        if "not logged" in lowered or "log in" in lowered:
            return {
                "status": "unauthenticated",
                "probe": "codex login status",
                "note": combined or "Codex login status reports logged out",
            }
        return {
            "status": "unknown",
            "probe": "codex login status",
            "note": combined or "Codex login status inconclusive",
        }

    return {
        "status": "unknown",
        "probe": "",
        "note": "No verified non-interactive auth probe configured",
    }


def _probe_cli_runtime_status(cli_name: str, binary_path: str) -> dict[str, str]:
    timeout_seconds = {
        "claude": 12,
        "codex": 10,
        "gemini": 10,
    }.get(cli_name, 8)

    def _status_from_output(
        probe_name: str,
        rc: int,
        stdout: str,
        stderr: str,
    ) -> dict[str, str]:
        combined = "\n".join(part for part in (stdout, stderr) if part).strip()
        lowered = combined.lower()
        if "you've hit your limit" in lowered or "usage limit" in lowered:
            return {
                "status": "usage_limit_reached",
                "probe": probe_name,
                "note": combined or "Usage limit reached",
            }
        if "not logged" in lowered or "login required" in lowered or "please log in" in lowered:
            return {
                "status": "login_required",
                "probe": probe_name,
                "note": combined or "Login required",
            }
        if rc == 0 and combined:
            return {
                "status": "ready",
                "probe": probe_name,
                "note": combined.splitlines()[0].strip() or "CLI runtime ready",
            }
        if rc == 124:
            return {
                "status": "unknown",
                "probe": probe_name,
                "note": combined or "Runtime probe timed out",
            }
        return {
            "status": "unknown",
            "probe": probe_name,
            "note": combined or "Runtime probe inconclusive",
        }

    if cli_name == "claude":
        return {
            "status": "unknown",
            "probe": "",
            "note": "No verified non-interactive runtime probe configured for Claude",
        }

    if cli_name == "codex":
        rc, stdout, stderr = _run_cli_probe(
            [binary_path, "-C", "/tmp", "exec", "--skip-git-repo-check", "ok"],
            timeout=timeout_seconds,
        )
        return _status_from_output("codex -C /tmp exec --skip-git-repo-check ok", rc, stdout, stderr)

    if cli_name == "gemini":
        rc, stdout, stderr = _run_cli_probe(
            [binary_path, "-p", "ok"],
            timeout=timeout_seconds,
        )
        return _status_from_output("gemini -p ok", rc, stdout, stderr)

    return {
        "status": "unknown",
        "probe": "",
        "note": "No verified non-interactive runtime probe configured",
    }


def _build_subscription_response_item(sub: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    provider = _infer_subscription_provider(sub.get("path", ""), sub.get("provider", ""))
    sub_path = str(sub.get("path", "")).strip()
    sub_path_norm = sub_path.rstrip("/")
    default_path_norm = os.path.expanduser("~/.claude").rstrip("/")
    agent_count = sum(
        1 for a in agents
        if (a.get("config_dir") or "").rstrip("/") == sub_path_norm
        or (not a.get("config_dir") and sub_path_norm == default_path_norm)
    )
    result = {
        "id": sub.get("id", ""),
        "name": sub.get("name", ""),
        "path": sub_path,
        "active": sub.get("active", False),
        "agent_count": agent_count,
        "api_key_hint": sub.get("api_key_hint", ""),
        "provider": provider,
        "detected": bool(sub.get("_detected")),
    }
    if provider == "claude":
        result.update(
            {
                "email": "",
                "plan": "",
                "billing_type": "",
                "display_name": "",
                "account_created_at": "",
                "rate_limit_tier": "",
            }
        )
        result.update(_probe_claude_profile_state(sub_path))
        return result
    result.update(
        {
            "email": sub.get("email", ""),
            "plan": sub.get("plan", ""),
            "billing_type": sub.get("billing_type", ""),
            "display_name": sub.get("display_name", ""),
            "account_created_at": sub.get("account_created_at", ""),
            "rate_limit_tier": sub.get("rate_limit_tier", ""),
        }
    )
    return result


def _detect_cli_setup_state(*, include_runtime_probes: bool = True) -> dict[str, Any]:
    available_cli: list[str] = []
    authenticated_cli: list[str] = []
    unauthenticated_cli: list[str] = []
    unknown_auth_cli: list[str] = []
    ready_cli: list[str] = []
    login_required_cli: list[str] = []
    usage_limited_cli: list[str] = []
    degraded_cli: list[str] = []
    unknown_runtime_cli: list[str] = []
    cli_paths: dict[str, str] = {}
    entries: list[dict[str, Any]] = []
    runtime_targets: list[tuple[dict[str, Any], str, str]] = []
    tools: dict[str, bool] = {}

    for cli_name, binary in _SETUP_CLI_BINARIES.items():
        binary_path = shutil.which(binary)
        available = bool(binary_path)
        tools[cli_name] = available
        entry: dict[str, Any] = {
            "id": cli_name,
            "binary": binary,
            "available": available,
            "authenticated": False,
            "auth_status": "unavailable",
            "auth_probe": "",
            "runtime_status": "unavailable",
            "runtime_probe": "",
            "doc_filename": instruction_filename_for_engine(cli_name),
            "path": binary_path or "",
            "note": "CLI binary not found",
            "runtime_note": "CLI binary not found",
        }
        if binary_path:
            available_cli.append(cli_name)
            cli_paths[cli_name] = binary_path
            auth_probe = _probe_cli_auth_status(cli_name, binary_path)
            entry["auth_status"] = auth_probe["status"]
            entry["auth_probe"] = auth_probe["probe"]
            entry["note"] = auth_probe["note"]
            entry["authenticated"] = auth_probe["status"] == "authenticated"
            if auth_probe["status"] == "authenticated":
                authenticated_cli.append(cli_name)
            elif auth_probe["status"] == "unauthenticated":
                unauthenticated_cli.append(cli_name)
            else:
                unknown_auth_cli.append(cli_name)
            if include_runtime_probes:
                runtime_targets.append((entry, cli_name, binary_path))
            else:
                entry["runtime_status"] = "unknown"
                entry["runtime_note"] = "Runtime probe skipped for fast detect"
                unknown_runtime_cli.append(cli_name)
        entries.append(entry)

    if runtime_targets:
        with ThreadPoolExecutor(
            max_workers=min(4, len(runtime_targets)),
            thread_name_prefix="cli-runtime-probe",
        ) as executor:
            future_map = {
                executor.submit(_probe_cli_runtime_status, cli_name, binary_path): (entry, cli_name)
                for entry, cli_name, binary_path in runtime_targets
            }
            for future, (entry, cli_name) in future_map.items():
                try:
                    runtime_probe = future.result()
                except Exception as exc:
                    runtime_probe = {
                        "status": "unknown",
                        "probe": "",
                        "note": f"Runtime probe failed: {exc}",
                    }
                entry["runtime_status"] = runtime_probe["status"]
                entry["runtime_probe"] = runtime_probe["probe"]
                entry["runtime_note"] = runtime_probe["note"]
                if runtime_probe["status"] == "ready":
                    ready_cli.append(cli_name)
                elif runtime_probe["status"] == "login_required":
                    login_required_cli.append(cli_name)
                elif runtime_probe["status"] == "usage_limit_reached":
                    usage_limited_cli.append(cli_name)
                elif runtime_probe["status"] == "degraded":
                    degraded_cli.append(cli_name)
                else:
                    unknown_runtime_cli.append(cli_name)

    available_api = [
        provider
        for provider, env_var in _SETUP_API_ENV_VARS.items()
        if os.environ.get(env_var, "").strip()
    ]

    preferred_order = ("claude", "codex", "gemini", "qwen")
    recommended = next((name for name in preferred_order if name in ready_cli), None)
    if recommended is None:
        recommended = next((name for name in preferred_order if name in authenticated_cli), None)
    if recommended is None:
        recommended = next((name for name in preferred_order if name in available_cli), None)

    return {
        "tools": tools,
        "cli": {
            "available": available_cli,
            "authenticated": authenticated_cli,
            "unauthenticated": unauthenticated_cli,
            "unknown_auth": unknown_auth_cli,
            "ready": ready_cli,
            "login_required": login_required_cli,
            "usage_limited": usage_limited_cli,
            "degraded": degraded_cli,
            "unknown_runtime": unknown_runtime_cli,
            "paths": cli_paths,
            "recommended": recommended,
            "entries": entries,
        },
        "api": {
            "available": available_api,
            "note": "API keys detected in environment" if available_api else "No API keys found",
        },
    }


def _get_cli_setup_state_cached(*, force: bool = False, include_runtime_probes: bool = True) -> dict[str, Any]:
    global _CLI_SETUP_STATE_INFLIGHT, _CLI_SETUP_STATE_CACHE, _CLI_SETUP_STATE_CACHE_AT

    now_ts = time.time()
    cache_key = bool(include_runtime_probes)
    wait_event: threading.Event | None = None
    is_owner = False

    with _CLI_SETUP_STATE_LOCK:
        cached_payload = _CLI_SETUP_STATE_CACHE.get(cache_key)
        cached_at = _CLI_SETUP_STATE_CACHE_AT.get(cache_key, 0.0)
        if (
            not force
            and cached_payload is not None
            and (now_ts - cached_at) <= _CLI_SETUP_STATE_CACHE_TTL_SECONDS
        ):
            return copy.deepcopy(cached_payload)
        wait_event = _CLI_SETUP_STATE_INFLIGHT.get(cache_key)
        if wait_event is None:
            wait_event = threading.Event()
            _CLI_SETUP_STATE_INFLIGHT[cache_key] = wait_event
            is_owner = True
        else:
            is_owner = False

    if not is_owner and wait_event is not None:
        wait_event.wait(timeout=20)
        with _CLI_SETUP_STATE_LOCK:
            cached_payload = _CLI_SETUP_STATE_CACHE.get(cache_key)
            if cached_payload is not None:
                return copy.deepcopy(cached_payload)

    payload: dict[str, Any] | None = None
    exc: Exception | None = None
    try:
        payload = _detect_cli_setup_state(include_runtime_probes=include_runtime_probes)
    except Exception as err:  # pragma: no cover - defensive runtime path
        exc = err
    finally:
        with _CLI_SETUP_STATE_LOCK:
            if payload is not None:
                _CLI_SETUP_STATE_CACHE[cache_key] = copy.deepcopy(payload)
                _CLI_SETUP_STATE_CACHE_AT[cache_key] = time.time()
            inflight = _CLI_SETUP_STATE_INFLIGHT.pop(cache_key, None)
            if inflight is not None:
                inflight.set()

    if exc is not None:
        raise exc

    return copy.deepcopy(payload or {})


def _render_buddy_operator_guide() -> str:
    return (
        "# Bridge Operator Guide — Buddy\n\n"
        "## Rolle\n\n"
        "Du bist Buddy — Concierge, Frontdoor und Superagent der Bridge. "
        "Du fuehrst den User durch Setup, Betrieb und Umsetzung. "
        "Du darfst handeln, delegieren, konfigurieren und Teams aufsetzen. "
        "Du bist nicht auf Erklaerungen beschraenkt.\n\n"
        "## Architekturaxiom\n\n"
        "- Die jeweilige CLI und ihre native Infrastruktur sind die operative SoT.\n"
        "- Die Bridge ist Wrapper, Control Plane, UI, Task-, Workflow- und Messaging-Schicht.\n"
        "- Fuer Claude/Codex/Gemini/Qwen arbeitest du ueber offizielle CLI-Wege, Session-I/O, tmux, Hooks, MCP und dokumentierte Projektdateien.\n"
        "- Keine Credential-Dateien lesen, patchen, symlinken oder serverseitig als Produktwahrheit projizieren.\n\n"
        "## Kanonische Projektstellen\n\n"
        "- Architektur/Runtime/API: `Backend/server.py`\n"
        "- Team-/Agent-Definitionen: `Backend/team.json`\n"
        "- Frontdoor fuer Buddy: `Frontend/buddy_landing.html`\n"
        "- Hauptarbeitsflaeche: `Frontend/chat.html`\n"
        "- Operatives Dashboard: `Frontend/control_center.html`\n"
        "- Projekt-/Runtime-Setup: `Frontend/project_config.html`\n\n"
        "## Kanonische Bridge-Pfade\n\n"
        "- Verfuegbare Engines/CLIs scannen: `GET /cli/detect`\n"
        "- Agent-Engine/Profil aendern: `PATCH /agents/{id}` oder `PUT /agents/{id}/subscription`\n"
        "- Engine-spezifische Home-Dokumente materialisieren: `POST /agents/{id}/setup-home`\n"
        "- Agent starten/restarten: `POST /agents/{id}/start`, `POST /agents/{id}/restart`\n"
        "- Teams/Agents/Workflows ueber die bestehenden Bridge-APIs oder Bridge-MCP-Tools bedienen\n\n"
        "## Setup-Regel\n\n"
        "1. Verfuegbare CLI-Engines scannen.\n"
        "2. Mit dem User die passende Engine waehlen.\n"
        "3. Das passende Home-Dokument fuer diese Engine materialisieren lassen.\n"
        "4. Erst danach den Agenten starten.\n"
        "5. Fuer Login/Approval den User explizit auffordern, die offizielle CLI selbst zu bestaetigen.\n\n"
        "## User-Scope\n\n"
        "- Kanonischer User-Scope: `Users/<user_id>/USER.md`\n"
        "- Initialisieren ueber `bridge_knowledge_init(user_id=\"<user_id>\")`\n"
        "- Lesen ueber `bridge_knowledge_read(\"Users/<user_id>/USER\")`\n"
        "- Legacy-Dateien sind nur Fallback, nicht die SoT.\n\n"
        "## Knowledge Vault und Approval\n\n"
        "- User- und Bridge-Wissen liegt im Knowledge Vault; nutze die kanonischen `bridge_knowledge_*`-Pfade statt ad-hoc Privatdateien.\n"
        "- Approval-pflichtige reale Aktionen bleiben explizit sichtbar und usergesteuert.\n\n"
        "## Operative Leitplanken\n\n"
        "- Handle deterministisch und ueber kanonische Produktpfade.\n"
        "- Nutze die Bridge fuer Teams, Tasks, Messaging, Whiteboard, Workflows und Runtime-Orchestrierung.\n"
        "- Wenn der User sagt `Erstelle mir ein Marketing-Team`, nutze die bestehenden Team-/Agent-/Workflow-Pfade oder die dazu dokumentierten Formulare statt ad-hoc Nebenpfade.\n"
        "- Was du nicht belegt hast, bleibt `Nicht verifiziert.`\n"
    )


def _render_buddy_engine_doc(filename: str) -> str:
    return (
        f"# {filename} — Buddy\n\n"
        "Lies zuerst:\n"
        "- `SOUL.md`\n"
        "- `BRIDGE_OPERATOR_GUIDE.md`\n\n"
        "Du bist Buddy — Concierge und Superagent der Bridge.\n"
        "Du bist nicht auf Erklaerungen beschraenkt. "
        "Du darfst ueber bestehende Bridge-Pfade handeln, delegieren, Teams aufsetzen, Agents starten und den User operativ fuehren.\n\n"
        "Arbeite immer ueber offizielle Wege der gewaehlten CLI und ueber die kanonische Bridge-Control-Plane.\n"
        "Der kanonische User-Scope liegt in `Users/<user_id>/USER.md`.\n"
        "Initialisiere fehlende User-Scopes ueber `bridge_knowledge_init(user_id=\"<user_id>\")`.\n"
        "Lies den aktiven User-Scope ueber `bridge_knowledge_read(\"Users/<user_id>/USER\")`.\n"
        "Die vollstaendige Bridge-Betriebslogik steht in `BRIDGE_OPERATOR_GUIDE.md`.\n"
    )


def _render_agent_engine_doc(agent_id: str, agent_entry: dict[str, Any], filename: str) -> str:
    name = str(agent_entry.get("name", "")).strip() or agent_id
    role = str(agent_entry.get("role", "")).strip() or str(agent_entry.get("description", "")).strip() or "Agent"
    description = str(agent_entry.get("description", "")).strip()
    return (
        f"# {filename} — {name}\n\n"
        f"**Role:** {role}\n"
        + (f"**Description:** {description}\n" if description else "")
        + "\n"
        "Du arbeitest innerhalb der Bridge als Agent in einer CLI-gebundenen Laufzeit.\n"
        "Nutze die Bridge fuer Messaging, Tasks, Workflows und Koordination.\n"
        "Die operative Wahrheit liegt in der nativen CLI-Session und ihren offiziellen Projektdateien.\n"
    )


def _materialize_agent_setup_home(
    agent_id: str,
    agent_entry: dict[str, Any],
    *,
    engine: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    home_dir = str(agent_entry.get("home_dir", "")).strip()
    if not home_dir:
        raise OSError(f"home_dir missing for agent '{agent_id}'")
    os.makedirs(home_dir, exist_ok=True)
    created: list[dict[str, Any]] = []
    selected_filename = instruction_filename_for_engine(engine)

    if agent_id == "buddy":
        guide_path = os.path.join(home_dir, "BRIDGE_OPERATOR_GUIDE.md")
        changed, state = write_file_if_missing(
            guide_path,
            _render_buddy_operator_guide(),
            overwrite=overwrite,
        )
        created.append({"path": guide_path, "state": state, "changed": changed})
        for engine_name in _SETUP_CLI_BINARIES:
            filename = instruction_filename_for_engine(engine_name)
            path = os.path.join(home_dir, filename)
            changed, state = write_file_if_missing(
                path,
                _render_buddy_engine_doc(filename),
                overwrite=overwrite,
            )
            created.append({"path": path, "state": state, "changed": changed})
        instruction_path = os.path.join(home_dir, selected_filename)
        return {
            "instruction_path": instruction_path,
            "guide_path": guide_path,
            "created": created,
        }

    instruction_path = os.path.join(home_dir, selected_filename)
    changed, state = write_file_if_missing(
        instruction_path,
        _render_agent_engine_doc(agent_id, agent_entry, selected_filename),
        overwrite=overwrite,
    )
    created.append({"path": instruction_path, "state": state, "changed": changed})
    return {
        "instruction_path": instruction_path,
        "guide_path": "",
        "created": created,
    }
