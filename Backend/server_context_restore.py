"""Context restore and persistence handoff helpers extracted from server.py (Slice 39)."""

from __future__ import annotations

import os
import time
from typing import Any, Callable

_GET_AGENT_HOME_DIR_FN: Callable[[str], str] = lambda _agent_id: ""
_NORMALIZE_CLI_IDENTITY_PATH_FN: Callable[[Any], str] = lambda _value: ""
_GET_RUNTIME_CONFIG_DIR_FN: Callable[[str], str] = lambda _agent_id: ""
_FIRST_EXISTING_PATH_FN: Callable[[list[str]], str] = lambda _paths: ""
_CONTEXT_BRIDGE_CANDIDATES_FN: Callable[[str, str], list[str]] = lambda _agent_home, _agent_id: []
_SOUL_CANDIDATES_FN: Callable[[str, str], list[str]] = lambda _agent_home, _agent_id: []
_INSTRUCTION_CANDIDATES_FN: Callable[[str, str, str], list[str]] = (
    lambda _agent_home, _agent_id, _engine="": []
)
_DETECT_INSTRUCTION_FILENAME_FN: Callable[[str, str, str], str] = (
    lambda _agent_home, _agent_id, _engine="": "CLAUDE.md"
)
_FIND_AGENT_MEMORY_PATH_FN: Callable[[str, str, str], str] = (
    lambda _agent_id, _agent_home, _config_dir="": ""
)
_FIND_MEMORY_BACKUP_PATH_FN: Callable[[str, str], str] = lambda _agent_id, _agent_home: ""
_LOAD_STANDING_APPROVALS_FN: Callable[[], list[dict[str, Any]]] = lambda: []
_IS_MANAGEMENT_AGENT_FN: Callable[[str], bool] = lambda _agent_id: False
_AGENT_IS_LIVE_FN: Callable[..., bool] = lambda *_args, **_kwargs: False
_TEAM_CONFIG_GETTER: Callable[[], dict[str, Any]] = lambda: {}
_REGISTERED_AGENTS_GETTER: Callable[[], dict[str, Any]] = lambda: {}
_TASKS_GETTER: Callable[[], dict[str, dict[str, Any]]] = lambda: {}
_MESSAGES_GETTER: Callable[[], list[dict[str, Any]]] = lambda: []
_SYSTEM_STATUS_GETTER: Callable[[], dict[str, Any]] = lambda: {}
_AGENT_STATE_LOCK: Any = None
_TASK_LOCK: Any = None
_MESSAGE_LOCK: Any = None
_AGENT_NONCES: dict[str, str] = {}
_AGENT_LAST_CONTEXT_RESTORE: dict[str, float] = {}
_CONTEXT_RESTORE_COOLDOWN = 300.0


def init(
    *,
    get_agent_home_dir_fn: Callable[[str], str],
    normalize_cli_identity_path_fn: Callable[[Any], str],
    get_runtime_config_dir_fn: Callable[[str], str],
    first_existing_path_fn: Callable[[list[str]], str],
    context_bridge_candidates_fn: Callable[[str, str], list[str]],
    soul_candidates_fn: Callable[[str, str], list[str]],
    instruction_candidates_fn: Callable[[str, str, str], list[str]],
    detect_instruction_filename_fn: Callable[[str, str, str], str],
    find_agent_memory_path_fn: Callable[[str, str, str], str],
    find_memory_backup_path_fn: Callable[[str, str], str],
    load_standing_approvals_fn: Callable[[], list[dict[str, Any]]],
    is_management_agent_fn: Callable[[str], bool],
    agent_is_live_fn: Callable[..., bool],
    team_config_getter: Callable[[], dict[str, Any]],
    registered_agents_getter: Callable[[], dict[str, Any]],
    tasks_getter: Callable[[], dict[str, dict[str, Any]]],
    messages_getter: Callable[[], list[dict[str, Any]]],
    system_status_getter: Callable[[], dict[str, Any]],
    agent_state_lock: Any,
    task_lock: Any,
    message_lock: Any,
    agent_nonces: dict[str, str],
    agent_last_context_restore: dict[str, float],
    context_restore_cooldown: float,
) -> None:
    global _GET_AGENT_HOME_DIR_FN
    global _NORMALIZE_CLI_IDENTITY_PATH_FN
    global _GET_RUNTIME_CONFIG_DIR_FN
    global _FIRST_EXISTING_PATH_FN
    global _CONTEXT_BRIDGE_CANDIDATES_FN
    global _SOUL_CANDIDATES_FN
    global _INSTRUCTION_CANDIDATES_FN
    global _DETECT_INSTRUCTION_FILENAME_FN
    global _FIND_AGENT_MEMORY_PATH_FN
    global _FIND_MEMORY_BACKUP_PATH_FN
    global _LOAD_STANDING_APPROVALS_FN
    global _IS_MANAGEMENT_AGENT_FN
    global _AGENT_IS_LIVE_FN
    global _TEAM_CONFIG_GETTER
    global _REGISTERED_AGENTS_GETTER
    global _TASKS_GETTER
    global _MESSAGES_GETTER
    global _SYSTEM_STATUS_GETTER
    global _AGENT_STATE_LOCK
    global _TASK_LOCK
    global _MESSAGE_LOCK
    global _AGENT_NONCES
    global _AGENT_LAST_CONTEXT_RESTORE
    global _CONTEXT_RESTORE_COOLDOWN

    _GET_AGENT_HOME_DIR_FN = get_agent_home_dir_fn
    _NORMALIZE_CLI_IDENTITY_PATH_FN = normalize_cli_identity_path_fn
    _GET_RUNTIME_CONFIG_DIR_FN = get_runtime_config_dir_fn
    _FIRST_EXISTING_PATH_FN = first_existing_path_fn
    _CONTEXT_BRIDGE_CANDIDATES_FN = context_bridge_candidates_fn
    _SOUL_CANDIDATES_FN = soul_candidates_fn
    _INSTRUCTION_CANDIDATES_FN = instruction_candidates_fn
    _DETECT_INSTRUCTION_FILENAME_FN = detect_instruction_filename_fn
    _FIND_AGENT_MEMORY_PATH_FN = find_agent_memory_path_fn
    _FIND_MEMORY_BACKUP_PATH_FN = find_memory_backup_path_fn
    _LOAD_STANDING_APPROVALS_FN = load_standing_approvals_fn
    _IS_MANAGEMENT_AGENT_FN = is_management_agent_fn
    _AGENT_IS_LIVE_FN = agent_is_live_fn
    _TEAM_CONFIG_GETTER = team_config_getter
    _REGISTERED_AGENTS_GETTER = registered_agents_getter
    _TASKS_GETTER = tasks_getter
    _MESSAGES_GETTER = messages_getter
    _SYSTEM_STATUS_GETTER = system_status_getter
    _AGENT_STATE_LOCK = agent_state_lock
    _TASK_LOCK = task_lock
    _MESSAGE_LOCK = message_lock
    _AGENT_NONCES = agent_nonces
    _AGENT_LAST_CONTEXT_RESTORE = agent_last_context_restore
    _CONTEXT_RESTORE_COOLDOWN = float(context_restore_cooldown)


def _grow_path(agent_id: str) -> str:
    return os.path.join(
        os.path.dirname(__file__),
        "..",
        "Knowledge",
        "Agents",
        agent_id,
        "GROW.md",
    )


def _read_text_if_present(path: str, max_chars: int) -> str:
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            content = fh.read().strip()
    except (FileNotFoundError, OSError):
        return ""
    if len(content) > max_chars:
        return content[: max_chars - 3] + "..."
    return content


def _registered_agent(agent_id: str) -> dict[str, Any]:
    if _AGENT_STATE_LOCK is None:
        return dict(_REGISTERED_AGENTS_GETTER().get(agent_id) or {})
    with _AGENT_STATE_LOCK:
        return dict(_REGISTERED_AGENTS_GETTER().get(agent_id) or {})


def _resolve_agent_home(agent_id: str, state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    agent_home = _GET_AGENT_HOME_DIR_FN(agent_id)
    registered = _registered_agent(agent_id)
    if agent_home:
        return agent_home, registered

    runtime_identity_sources: list[dict[str, Any]] = []
    if isinstance(state, dict):
        runtime_identity_sources.append(state)
    if registered:
        runtime_identity_sources.append(registered)

    for identity in runtime_identity_sources:
        for key in ("home_dir", "workspace", "project_root"):
            candidate = _NORMALIZE_CLI_IDENTITY_PATH_FN(identity.get(key, ""))
            if candidate:
                return candidate, registered
    return "", registered


def _resolve_agent_engine(agent_id: str, state: dict[str, Any], registered: dict[str, Any]) -> str:
    engine = str(registered.get("engine", "") or state.get("engine", "")).strip().lower()
    if engine:
        return engine
    team_config = _TEAM_CONFIG_GETTER()
    if isinstance(team_config, dict):
        for agent in team_config.get("agents", []):
            if agent.get("id") == agent_id:
                return str(agent.get("engine", "")).strip().lower()
    return ""


def resolve_context_restore_artifacts(agent_id: str, state: dict[str, Any]) -> dict[str, str]:
    agent_home, registered = _resolve_agent_home(agent_id, state)
    engine = _resolve_agent_engine(agent_id, state, registered)
    memory_config_dir = _GET_RUNTIME_CONFIG_DIR_FN(agent_id) if agent_home else ""

    instruction_path = ""
    instruction_filename = _DETECT_INSTRUCTION_FILENAME_FN(agent_home, agent_id, engine) if agent_home else "CLAUDE.md"
    if state.get("instruction_path"):
        instruction_path = _NORMALIZE_CLI_IDENTITY_PATH_FN(state.get("instruction_path"))
    if not instruction_path and registered.get("instruction_path"):
        instruction_path = _NORMALIZE_CLI_IDENTITY_PATH_FN(registered.get("instruction_path"))
    if not instruction_path and agent_home:
        instruction_path = _FIRST_EXISTING_PATH_FN(
            _INSTRUCTION_CANDIDATES_FN(agent_home, agent_id, engine)
        )

    context_bridge_path = (
        _FIRST_EXISTING_PATH_FN(_CONTEXT_BRIDGE_CANDIDATES_FN(agent_home, agent_id))
        if agent_home
        else ""
    )
    soul_path = (
        _FIRST_EXISTING_PATH_FN(_SOUL_CANDIDATES_FN(agent_home, agent_id))
        if agent_home
        else ""
    )
    grow_path = _grow_path(agent_id)
    if not os.path.isfile(grow_path):
        grow_path = ""

    memory_path = ""
    if agent_home:
        memory_path = _FIND_AGENT_MEMORY_PATH_FN(agent_id, agent_home, memory_config_dir)
        if not memory_path:
            memory_path = _FIND_MEMORY_BACKUP_PATH_FN(agent_id, agent_home)

    return {
        "agent_home": agent_home,
        "engine": engine,
        "instruction_filename": instruction_filename,
        "instruction_path": instruction_path,
        "context_bridge_path": context_bridge_path,
        "soul_path": soul_path,
        "grow_path": grow_path,
        "memory_path": memory_path,
        "memory_config_dir": memory_config_dir,
    }


def _append_persistence_hook(lines: list[str], artifacts: dict[str, str]) -> None:
    entries: list[tuple[str, str]] = []
    instruction_path = artifacts.get("instruction_path", "")
    instruction_filename = artifacts.get("instruction_filename", "CLAUDE.md")
    if instruction_path:
        entries.append((instruction_filename, instruction_path))
    context_bridge_path = artifacts.get("context_bridge_path", "")
    if context_bridge_path:
        entries.append(("CONTEXT_BRIDGE.md", context_bridge_path))
    soul_path = artifacts.get("soul_path", "")
    if soul_path:
        entries.append(("SOUL.md", soul_path))
    memory_path = artifacts.get("memory_path", "")
    if memory_path:
        entries.append((os.path.basename(memory_path), memory_path))
    grow_path = artifacts.get("grow_path", "")
    if grow_path:
        entries.append(("GROW.md", grow_path))
    if not entries:
        return

    lines.append("")
    lines.append("## PERSISTENZ-HOOK (JETZT AUSFUEHREN)")
    lines.append(
        "Lies diese persistierten Dateien jetzt VOLLSTAENDIG von Disk. "
        "Die eingebetteten Ausschnitte unten sind nur Snapshot, nicht Ersatz."
    )
    for label, path in entries:
        lines.append(f"- {label}: {path}")
    lines.append("- Wenn etwas fehlt oder unklar ist: [UNKNOWN] statt raten.")
    lines.append("- Danach: bridge_receive() fuer neue Nachrichten pruefen und erst dann weiterarbeiten.")


def build_context_restore_message(agent_id: str, state: dict[str, Any]) -> str:
    """Build a human-readable context restore message from saved state."""
    lines = ["[CONTEXT RESTORE] Dein letzter Zustand:"]

    artifacts = resolve_context_restore_artifacts(agent_id, state)
    _append_persistence_hook(lines, artifacts)

    cb_content = _read_text_if_present(artifacts.get("context_bridge_path", ""), 2000)
    if cb_content:
        lines.append("")
        lines.append("## Gespeicherter Kontext (CONTEXT_BRIDGE.md):")
        lines.append(cb_content)
        lines.append("")

    soul_content = _read_text_if_present(artifacts.get("soul_path", ""), 1500)
    if soul_content:
        lines.append("")
        lines.append("## Deine Identitaet (SOUL.md):")
        lines.append(soul_content)
        lines.append("")

    grow_content = _read_text_if_present(artifacts.get("grow_path", ""), 1000)
    if grow_content:
        lines.append("")
        lines.append("## Deine Learnings (GROW.md):")
        lines.append(grow_content)
        lines.append("")

    memory_path = artifacts.get("memory_path", "")
    memory_content = _read_text_if_present(memory_path, 2000)
    if memory_content:
        lines.append("")
        if os.path.basename(memory_path) == "MEMORY.md":
            lines.append("## Deine Persistente Memory (MEMORY.md):")
        else:
            lines.append(f"## Gesicherte Memory ({os.path.basename(memory_path)}):")
        lines.append(memory_content)
        lines.append("")

    summary = state.get("context_summary", "")
    if summary:
        lines.append(f"- Zusammenfassung: {summary}")

    last_act = state.get("last_activity")
    if last_act and isinstance(last_act, dict):
        action = last_act.get("action", "")
        target = last_act.get("target", "")
        desc = last_act.get("description", "")
        parts = [p for p in [action, target, desc] if p]
        if parts:
            lines.append(f"- Letzte Aktivitaet: {' → '.join(parts)}")

    tasks = state.get("open_tasks", [])
    if tasks:
        lines.append(f"- Offene Tasks: {', '.join(str(t) for t in tasks)}")

    team_config = _TEAM_CONFIG_GETTER()
    if team_config:
        for agent in team_config.get("agents", []):
            if agent.get("id") != agent_id:
                continue
            perms = agent.get("permissions", [])
            if perms and isinstance(perms, list):
                lines.append("")
                lines.append("## Deine Berechtigungen (PERSISTENT — ueberlebt Compact)")
                lines.append("Du darfst folgende Aktionen SELBSTSTAENDIG ausfuehren — OHNE User-Freigabe:")
                for permission in perms:
                    lines.append(f"  - {permission}")
            agent_scope = agent.get("scope", [])
            if agent_scope and isinstance(agent_scope, list):
                lines.append("")
                lines.append("## Dein Zustaendigkeitsbereich")
                lines.append("Du darfst NUR diese Dateien/Bereiche aendern:")
                for scope_entry in agent_scope:
                    lines.append(f"  - {scope_entry}")
            break

    try:
        standing_approvals = _LOAD_STANDING_APPROVALS_FN()
        active_sas = [
            approval
            for approval in standing_approvals
            if approval.get("agent_id") == agent_id and approval.get("active", False)
        ]
        if active_sas:
            lines.append("- Stehende Freigaben (Standing Approvals):")
            for approval in active_sas:
                lines.append(
                    f"  - {approval.get('action', '?')}: "
                    f"{approval.get('scope', '*')} (bis {approval.get('expires_at', 'unbegrenzt')})"
                )
    except Exception:
        pass

    lines.append("")
    lines.append("## DNA-REMINDER (gilt IMMER)")
    lines.append("- 'Ich kann nicht' ist verboten. Erst Tools pruefen, Capabilities suchen, andere Agents fragen.")
    lines.append("- Selbstoptimierung ist Ueberlebensbedingung. Lerne aus Fehlern, optimiere dein Vorgehen.")
    lines.append("- ERFORSCHE aktiv was du kannst: bridge_capability_library_search, CLI-Doku, ausprobieren.")

    agent_mode = state.get("mode", "normal")
    lines.append(f"- Modus: {agent_mode}")
    if agent_mode == "auto":
        lines.append("- AUTO-MODUS AKTIV: Du arbeitest autonom weiter. Finde selbst die naechste Aufgabe.")
    elif agent_mode == "standby":
        lines.append("- STANDBY-MODUS: Warte auf direkte Auftraege. Keine eigenstaendige Arbeit.")

    active_tasks: list[str] = []
    with _TASK_LOCK:
        for task in _TASKS_GETTER().values():
            if task.get("state") not in ("created", "claimed", "acked"):
                continue
            if task.get("assigned_to") == agent_id or task.get("created_by") == agent_id:
                role = "assigned" if task.get("assigned_to") == agent_id else "created"
                active_tasks.append(f"{task.get('title', '?')} ({role}, state={task.get('state')})")
    if active_tasks:
        lines.append(f"- Aktive Tasks: {'; '.join(active_tasks[:5])}")

    recent_msgs: list[dict[str, Any]] = []
    with _MESSAGE_LOCK:
        for msg in reversed(_MESSAGES_GETTER()):
            if len(recent_msgs) >= 10:
                break
            sender = msg.get("from", "")
            recipient = msg.get("to", "")
            if sender == agent_id or recipient == agent_id or recipient == "all" or (
                recipient == "all_managers" and _IS_MANAGEMENT_AGENT_FN(agent_id)
            ):
                meta = msg.get("meta") or {}
                if meta.get("type") == "context_restore":
                    continue
                if sender == "system":
                    continue
                recent_msgs.append(msg)

    if recent_msgs:
        recent_msgs.reverse()
        lines.append("")
        lines.append("Letzte Nachrichten:")
        for msg in recent_msgs:
            sender = msg.get("from", "?")
            recipient = msg.get("to", "?")
            content = str(msg.get("content", ""))
            if len(content) > 150:
                content = content[:147] + "..."
            lines.append(f"  [{sender} → {recipient}] {content}")

    active_agents: list[str] = []
    with _AGENT_STATE_LOCK:
        for other_id, reg in _REGISTERED_AGENTS_GETTER().items():
            if other_id == agent_id:
                continue
            role_str = reg.get("role", "")
            if _AGENT_IS_LIVE_FN(other_id, stale_seconds=120.0, reg=reg):
                active_agents.append(f"{other_id} ({role_str})" if role_str else other_id)
    if active_agents:
        lines.append("")
        lines.append(f"Aktive Agents: {', '.join(active_agents)}")

    if agent_id == "buddy":
        try:
            team_manifest_lines: list[str] = []
            if team_config:
                for agent in team_config.get("agents", []):
                    other_id = agent.get("id", "")
                    if not other_id or other_id == "buddy" or not agent.get("active", False):
                        continue
                    role = agent.get("role", "Agent")
                    top_skills: list[str] = []
                    grow_candidates = [_grow_path(other_id)]
                    agent_home_dir = agent.get("home_dir", "")
                    if agent_home_dir:
                        grow_candidates.append(os.path.join(agent_home_dir, "GROW.md"))
                    grow_file = ""
                    for candidate in grow_candidates:
                        if os.path.isfile(candidate):
                            grow_file = candidate
                            break
                    try:
                        if not grow_file:
                            raise FileNotFoundError
                        with open(grow_file, encoding="utf-8") as fh:
                            grow_text = fh.read()
                        in_section = False
                        for line in grow_text.splitlines():
                            if line.startswith("## Patterns") or line.startswith("## Staerken") or line.startswith("### Staerken"):
                                in_section = True
                                continue
                            if in_section and line.startswith("##"):
                                break
                            if in_section and line.strip().startswith("- "):
                                skill = line.strip()[2:].strip()
                                if len(skill) > 60:
                                    skill = skill[:57] + "..."
                                top_skills.append(skill)
                                if len(top_skills) >= 3:
                                    break
                    except (FileNotFoundError, OSError):
                        pass
                    skill_str = f" | Skills: {', '.join(top_skills)}" if top_skills else ""
                    team_manifest_lines.append(f"  - {other_id}: {role}{skill_str}")
            if team_manifest_lines:
                lines.append("")
                lines.append("## Team-Manifest (wer kann was)")
                lines.extend(team_manifest_lines)
                lines.append("")
                lines.append(
                    "WICHTIG: Lies dein knowledge/ Verzeichnis nach jedem Start. "
                    "Dort liegen KNOWLEDGE_INDEX.md (Nachschlagewerk) und SYSTEM_MAP.md (Architektur). "
                    "Fuer Live-Daten nutze Bridge-Tools."
                )
        except Exception:
            pass

    try:
        agent_role = ""
        with _AGENT_STATE_LOCK:
            reg = _REGISTERED_AGENTS_GETTER().get(agent_id, {})
            agent_role = reg.get("role", "")
        if agent_role:
            lines.append("")
            lines.append(
                'Tipp: Pruefe `bridge_capability_library_search(query="...")` '
                "fuer Tools und MCPs die zu deiner Rolle passen. 592 Eintraege verfuegbar."
            )
    except Exception:
        pass

    system_status = _SYSTEM_STATUS_GETTER()
    if system_status.get("shutdown_active"):
        reason = system_status.get("shutdown_reason", "")
        lines.append("")
        lines.append(f"⚠ SYSTEM-STATUS: SHUTDOWN AKTIV" + (f" — {reason}" if reason else ""))
    else:
        lines.append("")
        lines.append("SYSTEM-STATUS: Normalbetrieb. Kein aktiver Shutdown.")

    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def should_send_context_restore(agent_id: str, nonce: str | None, context_lost: bool) -> bool:
    """Determine if CONTEXT RESTORE should be sent after /register."""
    now = time.time()

    if not nonce:
        last_restore = _AGENT_LAST_CONTEXT_RESTORE.get(agent_id, 0)
        if now - last_restore < _CONTEXT_RESTORE_COOLDOWN:
            print(
                f"[register] CONTEXT RESTORE suppressed for {agent_id}: cooldown "
                f"({int(now - last_restore)}s < {_CONTEXT_RESTORE_COOLDOWN}s)"
            )
            return False
        return True

    stored_nonce = _AGENT_NONCES.get(agent_id)
    if stored_nonce is None:
        return True
    if nonce != stored_nonce:
        return True

    if context_lost:
        last_restore = _AGENT_LAST_CONTEXT_RESTORE.get(agent_id, 0)
        if now - last_restore < _CONTEXT_RESTORE_COOLDOWN:
            print(
                f"[register] CONTEXT RESTORE suppressed for {agent_id}: cooldown after /compact "
                f"({int(now - last_restore)}s < {_CONTEXT_RESTORE_COOLDOWN}s)"
            )
            return False
        return True

    print(
        f"[register] CONTEXT RESTORE skipped for {agent_id}: token refresh "
        "(same nonce, no context loss)"
    )
    return False
