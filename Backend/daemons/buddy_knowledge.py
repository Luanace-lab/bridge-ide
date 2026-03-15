from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

_BUDDY_KNOWLEDGE_INTERVAL = 300

_system_shutdown_active_cb: Callable[[], bool] | None = None
_team_config_getter: Callable[[], dict[str, Any] | None] | None = None
_backend_dir = ""
_agent_state_dir = ""
_log_file = ""
_port = 0
_ws_port = 0
_bridge_strict_auth = False


def init(
    *,
    system_shutdown_active: Callable[[], bool],
    team_config_getter: Callable[[], dict[str, Any] | None],
    backend_dir: str,
    agent_state_dir: str,
    log_file: str,
    port: int,
    ws_port: int,
    bridge_strict_auth: bool,
) -> None:
    global _system_shutdown_active_cb, _team_config_getter
    global _backend_dir, _agent_state_dir, _log_file
    global _port, _ws_port, _bridge_strict_auth

    _system_shutdown_active_cb = system_shutdown_active
    _team_config_getter = team_config_getter
    _backend_dir = backend_dir
    _agent_state_dir = agent_state_dir
    _log_file = log_file
    _port = port
    _ws_port = ws_port
    _bridge_strict_auth = bridge_strict_auth


def _team_config() -> dict[str, Any]:
    if _team_config_getter is None:
        return {}
    return _team_config_getter() or {}


def _buddy_knowledge_tick() -> bool:
    if _system_shutdown_active_cb is None or _team_config_getter is None:
        raise RuntimeError("daemons.buddy_knowledge not initialized")
    if _system_shutdown_active_cb():
        return False
    _generate_buddy_knowledge()
    return True


def _buddy_knowledge_loop() -> None:
    time.sleep(5)
    while True:
        try:
            if _system_shutdown_active_cb and _system_shutdown_active_cb():
                time.sleep(_BUDDY_KNOWLEDGE_INTERVAL)
                continue
            _generate_buddy_knowledge()
        except Exception as exc:
            print(f"[buddy-knowledge] Error: {exc}")
        time.sleep(_BUDDY_KNOWLEDGE_INTERVAL)


def _generate_buddy_knowledge() -> None:
    """Generate static knowledge reference docs for Buddy agent."""
    buddy_home = ""
    team_config = _team_config()
    for agent in team_config.get("agents", []):
        if agent.get("id") == "buddy":
            buddy_home = str(agent.get("home_dir", "")).strip()
            break
    if not buddy_home:
        return

    knowledge_dir = os.path.join(buddy_home, "knowledge")
    os.makedirs(knowledge_dir, exist_ok=True)

    team_json_path = os.path.join(_backend_dir, "team.json")
    team_mtime = os.path.getmtime(team_json_path) if os.path.exists(team_json_path) else 0

    live_path = os.path.join(knowledge_dir, "LIVE_STATUS.md")
    if os.path.exists(live_path):
        try:
            os.unlink(live_path)
            print("[buddy-knowledge] Removed deprecated LIVE_STATUS.md")
        except OSError:
            pass

    idx_path = os.path.join(knowledge_dir, "KNOWLEDGE_INDEX.md")
    if not _is_up_to_date(idx_path, team_mtime):
        _build_knowledge_index(idx_path, knowledge_dir)

    sysmap_path = os.path.join(knowledge_dir, "SYSTEM_MAP.md")
    if not _is_up_to_date(sysmap_path, team_mtime):
        _build_system_map(sysmap_path)

    sot_path = os.path.join(knowledge_dir, "BUDDY_SYSTEM_SOT.md")
    if not _is_up_to_date(sot_path, team_mtime):
        _build_buddy_system_sot(sot_path, buddy_home)


def _is_up_to_date(file_path: str, reference_mtime: float) -> bool:
    try:
        return os.path.getmtime(file_path) >= reference_mtime
    except OSError:
        return False


def _build_knowledge_index(idx_path: str, knowledge_dir: str) -> None:
    del knowledge_dir  # reserved for future local knowledge partitioning
    lines = [
        "# Knowledge Index — Nachschlagewerk",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Dieses Dokument zeigt dir WO du Informationen findest.",
        "Fuer Live-Daten (Agent-Status, Tasks) nutze die Bridge-Tools direkt.",
        "",
    ]

    lines.append("## Agent-Memories")
    lines.append("")
    lines.append("Jeder Claude-Agent hat ein persistentes Memory:")
    lines.append("- Pattern: `~/.claude-agent-{AGENT_ID}/projects/*/memory/MEMORY.md`")
    lines.append("- Zugriff: Datei direkt lesen (Read-Tool) oder `bridge_memory_search`")
    lines.append("")

    home_dir = os.path.expanduser("~")
    agents_with_memory: list[str] = []
    try:
        for entry in sorted(os.listdir(home_dir)):
            if entry.startswith(".claude-agent-"):
                agents_with_memory.append(entry.replace(".claude-agent-", ""))
    except OSError:
        pass
    if agents_with_memory:
        lines.append(f"Agents mit Memory-Verzeichnis ({len(agents_with_memory)}):")
        lines.append(f"- {', '.join(agents_with_memory)}")
    lines.append("")

    kv_base = os.path.join(_backend_dir, "..", "Knowledge")
    kv_abs = os.path.abspath(kv_base) if os.path.isdir(kv_base) else "N/A"
    lines.append("## Knowledge Vault (Shared)")
    lines.append(f"- Pfad: `{kv_abs}`")
    lines.append("- Zugriff: `bridge_knowledge_read(path)`, `bridge_knowledge_search(query)`")
    if os.path.isdir(kv_base):
        lines.append("- Struktur:")
        for entry in sorted(os.listdir(kv_base)):
            entry_path = os.path.join(kv_base, entry)
            if os.path.isdir(entry_path):
                count = len([name for name in os.listdir(entry_path) if not name.startswith(".")])
                lines.append(f"  - `{entry}/` ({count} Eintraege)")
    lines.append("")

    lines.append("## Daily Logs")
    lines.append(f"- Pattern: `{kv_abs}/Agents/{{agent_id}}/DAILY/YYYY-MM-DD.md`")
    lines.append('- Zugriff: `bridge_knowledge_read("Agents/{agent_id}/DAILY/YYYY-MM-DD.md")`')
    daily_agents: list[str] = []
    if os.path.isdir(kv_base):
        agents_dir = os.path.join(kv_base, "Agents")
        if os.path.isdir(agents_dir):
            for agent in sorted(os.listdir(agents_dir)):
                daily_dir = os.path.join(agents_dir, agent, "DAILY")
                if os.path.isdir(daily_dir):
                    log_files = [name for name in os.listdir(daily_dir) if name.endswith(".md")]
                    if log_files:
                        daily_agents.append(
                            f"- **{agent}**: {len(log_files)} Log(s), letzter: {sorted(log_files)[-1]}"
                        )
    if daily_agents:
        lines.append("- Agents mit Daily Logs:")
        lines.extend(daily_agents)
    else:
        lines.append("- Aktuell keine Daily Logs vorhanden")
    lines.append("")

    lines.append("## Credentials & Accounts")
    lines.append("- Zugriff: `bridge_credential_list(service)` — zeigt Metadaten")
    lines.append("- Secrets: `bridge_credential_get(service, key)` — gibt verschluesselten Wert")
    lines.append("- Speicher: `~/.config/bridge/` (verschluesselt, NICHT direkt lesen)")
    lines.append("")

    lines.append("## Semantic Memory")
    lines.append("- Zugriff: `bridge_memory_search(query, scope)`")
    lines.append("- Speicher: `~/.config/bridge/memory/`")
    lines.append("- Hybrid-Retrieval: Embeddings + BM25 (semantic_memory.py)")
    lines.append("")

    lines.append("## Live-Daten (on-demand via Bridge-Tools)")
    lines.append("- Agent-Status: `bridge_health` oder Dashboard")
    lines.append("- Nachrichten: `bridge_receive()`, `bridge_history(limit=N)`")
    lines.append("- Tasks: `bridge_task_queue(state='created')`, `bridge_task_get(task_id)`")
    lines.append("- Aktivitaeten: `bridge_check_activity(agent_id)`")
    lines.append("")

    lines.append("## Speicherorte (Uebersicht)")
    lines.append(f"- Knowledge Vault: `{kv_abs}`")
    lines.append(f"- Agent State: `{_agent_state_dir}`")
    lines.append(f"- Message Log: `{_log_file}`")
    lines.append("- Credential Store: `~/.config/bridge/` (verschluesselt)")
    lines.append("- Semantic Memory: `~/.config/bridge/memory/`")
    lines.append("- Media Workspace: `/tmp/bridge_creator_workspace/`")
    lines.append("")

    lines.append("## Retrieval-Pfad (Reihenfolge)")
    lines.append("1. `knowledge/` Dateien lesen (KNOWLEDGE_INDEX.md, SYSTEM_MAP.md)")
    lines.append("2. `bridge_memory_search(query, scope)` — semantische Suche")
    lines.append("3. `bridge_knowledge_search(query)` — Fulltext/Regex im Knowledge Vault")
    lines.append("4. `bridge_credential_list(service)` — Credential-Metadaten")
    lines.append("")

    lines.append("## Tooling-Familien")
    lines.append("- Browser: `bridge_browser_*`, `bridge_stealth_*`")
    lines.append("- Knowledge: `bridge_knowledge_*`")
    lines.append("- Memory: `bridge_memory_*`")
    lines.append("- Credentials: `bridge_credential_*`")
    lines.append("- Tasks: `bridge_task_*`")
    lines.append("- Email: `bridge_email_*`")
    lines.append("- Slack: `bridge_slack_*`")
    lines.append("- Telegram: `bridge_telegram_*`")
    lines.append("- WhatsApp: `bridge_whatsapp_*`")
    lines.append("- Creator: `bridge_creator_*`")
    lines.append("- Desktop: `bridge_desktop_*`")
    lines.append("- Voice: `bridge_voice_*`")
    lines.append("- Capabilities: `bridge_capability_library_*`")

    _atomic_write_file(idx_path, "\n".join(lines))
    print("[buddy-knowledge] KNOWLEDGE_INDEX.md generated")


def _build_system_map(sysmap_path: str) -> None:
    lines = [
        "# System Map",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Server",
        f"- HTTP: 127.0.0.1:{_port}",
        f"- WebSocket: 127.0.0.1:{_ws_port}",
        f"- Auth: {'strict' if _bridge_strict_auth else 'permissive'}",
        "",
        "## Agents",
    ]

    team_config = _team_config()
    for agent in team_config.get("agents", []):
        agent_id = agent.get("id", "?")
        desc = agent.get("description", agent.get("role", ""))
        engine = agent.get("engine", "claude")
        level = agent.get("level", "?")
        reports_to = agent.get("reports_to", "-")
        active = agent.get("active", False)
        status = "aktiv" if active else "inaktiv"
        lines.append(
            f"- {agent_id}: {desc} (L{level}, {engine}, reports_to={reports_to}, {status})"
        )
    lines.append("")

    lines.append("## Engines")
    engines_seen: set[str] = set()
    for agent in team_config.get("agents", []):
        engine = agent.get("engine", "claude")
        if engine not in engines_seen:
            engines_seen.add(engine)
            lines.append(f"- {engine}")
    lines.append("")

    kv_base = os.path.join(_backend_dir, "..", "Knowledge")
    if os.path.isdir(kv_base):
        lines.append("## Knowledge Vault")
        for entry in sorted(os.listdir(kv_base)):
            entry_path = os.path.join(kv_base, entry)
            if os.path.isdir(entry_path):
                count = len([name for name in os.listdir(entry_path) if not name.startswith(".")])
                lines.append(f"- {entry}/ ({count} Eintraege)")

    _atomic_write_file(sysmap_path, "\n".join(lines))
    print("[buddy-knowledge] SYSTEM_MAP.md regenerated")


def _build_buddy_system_sot(sot_path: str, buddy_home: str) -> None:
    project_root = os.path.abspath(os.path.join(_backend_dir, ".."))
    platforms_root = os.path.abspath(os.path.join(project_root, "..", "Plattformen"))
    docs_root = os.path.join(_backend_dir, "docs")
    refactor_root = os.path.join(
        project_root,
        "Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead",
        "Projekt_Dokumentation",
    )

    lines = [
        "# Buddy System SoT",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Zweck",
        "",
        "Dieses Dokument ist Buddys zentrale Einstiegskarte in die Bridge.",
        "Es zeigt die autoritativen Quellen und die sichere Lesereihenfolge.",
        "",
        "## Pfad-Wahrheit",
        "",
        f"- Buddy-Home laut Team-Konfiguration: `{buddy_home}`",
        f"- Buddys laufende Session: `{os.path.join(buddy_home, '.agent_sessions', 'buddy')}`",
        "- Wenn in Buddys Instruktionen `knowledge/` steht, ist damit das Buddy-Home gemeint, nicht das Session-Unterverzeichnis.",
        "",
        "## Liesereihenfolge fuer Buddy",
        "",
        "1. `knowledge/BUDDY_SYSTEM_SOT.md`",
        "2. `knowledge/SYSTEM_MAP.md`",
        "3. `knowledge/KNOWLEDGE_INDEX.md`",
        "4. `BRIDGE_OPERATOR_GUIDE.md`",
        "5. `BRIDGE/Knowledge/Users/<user_id>/USER.md`",
        "6. Live-Zustand nur ueber Bridge-APIs und Bridge-Tools",
        "",
        "## Kanonische Quellen fuer Buddy",
        "",
        "### User und Persona",
        "",
        "- Kanonischer User-Scope: `/home/user/bridge/BRIDGE/Knowledge/Users/<user_id>/USER.md`",
        f"- Legacy-Fallback nur falls noetig: `{os.path.join(buddy_home, 'memory', 'user_model.json')}`",
        "",
        "### Live-Systemzustand",
        "",
        "- `/status`",
        "- `/health`",
        "- `/runtime`",
        "- `/agents/{id}`",
        "- `/task/queue`",
        "- `/task/tracker`",
        "- `/history`",
        "- `/receive/{agent_id}`",
        "",
        "### Architektur und Runtime",
        "",
        f"- Backend-Referenz: `{os.path.join(docs_root, 'BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md')}`",
        f"- Refactor-Leitstand: `{os.path.join(refactor_root, '03_Leitstand_9_Punkte_Refaktor.md')}`",
        f"- Projekt-Doku-Master-Index: `{os.path.join(refactor_root, '00_MASTER_INDEX.md')}`",
        "",
        "### Produkt- und Plattformdoku",
        "",
        "Diese Dokumente sind Mindestanforderung an den Code.",
        f"- Persistenz: `{os.path.join(platforms_root, 'PERSISTENZ_SYSTEM.md')}`",
        f"- MCP-/Capability-Library: `{os.path.join(platforms_root, 'MCP_LIBRARY_STRATEGIE.md')}`",
        f"- Skill-/MCP-Integration: `{os.path.join(platforms_root, 'SKILL_MCP_INTEGRATION_KONZEPT.md')}`",
        f"- Creator-Plattform: `{os.path.join(platforms_root, 'CREATOR_PLATTFORM.md')}`",
        f"- Big-Data-Plattform: `{os.path.join(platforms_root, 'BIG_DATA_PLATTFORM.md')}`",
        f"- Marketing-Plattform: `{os.path.join(platforms_root, 'MARKETING_PLATTFORM.md')}`",
        f"- Legal-Plattform: `{os.path.join(platforms_root, 'LEGAL_PLATTFORM.md')}`",
        "",
        "### Vertiefende Specs unter Backend/docs",
        "",
        f"- Creator-Spec: `{os.path.join(docs_root, 'CREATOR_PLATFORM_RELIABILITY_SPEC.md')}`",
        f"- Big-Data-Spec: `{os.path.join(docs_root, 'BIG_DATA_ANALYSIS_PLATFORM_SPEC.md')}`",
        f"- Marketplace-/MCP-Analyse: `{os.path.join(docs_root, 'MARKETPLACE_ANALYSIS.md')}`",
        "",
        "### Buddy-nahe Zusatzdoku",
        "",
        f"- Dokumentenindex: `{os.path.join(buddy_home, 'knowledge', 'docs', 'DOCS_INDEX.md')}`",
        f"- Backend-/Infra-Snapshot: `{os.path.join(buddy_home, 'knowledge', 'docs', 'BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md')}`",
        f"- Frontend-Snapshot: `{os.path.join(buddy_home, 'knowledge', 'docs', 'frontend', 'README.md')}`",
        f"- Frontend-Contracts: `{os.path.join(buddy_home, 'knowledge', 'docs', 'frontend', 'contracts.md')}`",
        "",
        "### Frontdoor fuer den User",
        "",
        f"- Buddy Landing: `{os.path.join(project_root, 'Frontend', 'buddy_landing.html')}`",
        f"- Hauptchat: `{os.path.join(project_root, 'Frontend', 'chat.html')}`",
        f"- Operatives Dashboard: `{os.path.join(project_root, 'Frontend', 'control_center.html')}`",
        f"- Projekt-/Runtime-Setup: `{os.path.join(project_root, 'Frontend', 'project_config.html')}`",
        "",
        "## Buddy-Arbeitsregel",
        "",
        "- Fuer Systemfragen zuerst `SYSTEM_MAP.md` und `KNOWLEDGE_INDEX.md`.",
        "- Fuer Bedienlogik `BRIDGE_OPERATOR_GUIDE.md`.",
        "- Fuer Produktziel und Mindeststandard die Plattformdoku unter `/home/user/bridge/Plattformen`.",
        "- Fuer aktuelle Wahrheit nur Live-APIs und Bridge-Tools.",
        "- Nicht `.agent_sessions/buddy` mit dem Buddy-Home verwechseln.",
        "",
        "## Nicht tun",
        "",
        "- Keine Credential-Dateien als Produkt-SoT lesen.",
        "- `memory/user_model.json` nicht als primaere Wahrheit behandeln, wenn ein echter User-Scope existiert.",
    ]

    _atomic_write_file(sot_path, "\n".join(lines))
    print("[buddy-knowledge] BUDDY_SYSTEM_SOT.md generated")


def _atomic_write_file(path: str, content: str) -> None:
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
