"""
api_server.py — Unified REST API Server

Exposes all Bridge IDE backend modules via HTTP endpoints.
Runs alongside the existing bridge server as a separate service.

Phase: Integration

Endpoints:
  /api/status                    — Platform status overview
  /api/memory/*                  — Memory Engine (write, search, daily notes)
  /api/skills/*                  — Skill Manager (list, activate, deactivate)
  /api/approval/*                — Approval Gate (queue, approve, deny)
  /api/credentials/*             — Credential Vault (store, retrieve, list)
  /api/engines/*                 — Engine Registry (list, route, health)
  /api/agents/*                  — Runtime Manager (list, status)
  /api/monitor/*                 — Agent Monitor (metrics, costs, alerts)
  /api/messages/*                — Message Bus (send, receive, history)
  /api/shared/*                  — Shared Memory (read, write, search)
  /api/auth/*                    — Auth (keys, authenticate)
  /api/ha/*                      — Home Assistant (states, services)
  /api/office/*                  — Office Automation (excel, pptx, pdf)
  /api/email/*                   — Email Integration (inbox, send, drafts)
  /api/telephony/*               — Telephony (calls, sms, voice)
  /api/delegation/*              — Delegation (tasks, create, status)
  /api/reflection/*              — Self-Reflection (distill, lessons)
  /api/soul/*                    — Soul Engine (identity, resolve)
  /api/context/scan              — Project context scanning
  /api/projects/create           — Project structure creation
  /api/runtime/configure         — Team configuration & startup

Design:
  - Pure stdlib (http.server) — no framework dependency
  - JSON request/response
  - Modular handler registration
  - Thread-safe via ThreadingHTTPServer
  - CORS headers for frontend access
"""

from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

# Add Backend dir to path
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Import all modules
from approval_gate import ApprovalGate
from auth import AuthManager
import board_api
from credential_vault import CredentialVault
from delegation import DelegationManager
from engine_abc import ENGINE_REGISTRY
from engine_routing import EngineRouter
from memory_engine import MemoryEngine
from message_bus import MessageBus
from runtime_manager import RuntimeManager
from self_reflection import SelfReflection
from shared_memory import SharedMemory
from skill_manager import SkillManager
import soul_engine

# Optional real-world integrations
from email_integration import EmailClient
from ha_integration import HAClient
from office_automation import OfficeClient
from telephony_integration import TelephonyClient
from agent_monitor import AgentMonitor


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_API_PORT = 9222
API_VERSION = "1.0"
ALLOWED_ORIGINS = ["http://127.0.0.1:9111"]


# ---------------------------------------------------------------------------
# Module Registry — singleton instances
# ---------------------------------------------------------------------------

class Platform:
    """Holds all module instances."""

    def __init__(self, data_dir: str = "") -> None:
        self.data_dir = data_dir or os.path.join(BACKEND_DIR, ".platform_data")
        os.makedirs(self.data_dir, exist_ok=True)
        board_api.PROJECTS_FILE = os.path.join(self.data_dir, "projects.json")

        # Phase A — Foundation
        self.memory = MemoryEngine(Path(os.path.join(self.data_dir, "memory")))
        self.memory.scaffold()
        self.approval = ApprovalGate()
        self.vault = CredentialVault(Path(os.path.join(self.data_dir, "vault")))
        self.souls_dir = Path(os.path.join(self.data_dir, "souls"))
        os.makedirs(self.souls_dir, exist_ok=True)

        # Phase B — Capabilities
        self.skills = SkillManager(Path(os.path.join(self.data_dir, "skills")))
        self.ha = HAClient()
        self.office = OfficeClient()
        self.email_client = EmailClient()
        self.telephony = TelephonyClient()

        # Phase C — Intelligence
        self.router = EngineRouter()

        # Phase D — Scale
        self.runtime = RuntimeManager()
        self.bus = MessageBus(
            persist_path=Path(os.path.join(self.data_dir, "bus")),
        )
        self.shared = SharedMemory(Path(os.path.join(self.data_dir, "shared")))
        self.monitor = AgentMonitor()
        self.reflection = SelfReflection(
            Path(os.path.join(self.data_dir, "reflection")),
        )
        self.delegation = DelegationManager()

        # Platform
        self.auth = AuthManager()

    def status(self) -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "timestamp": time.time(),
            "modules": {
                "memory": self.memory.status(),
                "approval": {"status": "active", "stats": self.approval.stats()},
                "vault": {"status": "active"},
                "soul": {"status": "active", "souls_dir": str(self.souls_dir)},
                "skills": self.skills.status(),
                "ha": self.ha.status(),
                "office": self.office.status(),
                "email": self.email_client.status(),
                "telephony": self.telephony.status(),
                "engines": {"registered": list(ENGINE_REGISTRY.keys())},
                "router": self.router.status(),
                "runtime": self.runtime.status(),
                "bus": self.bus.status(),
                "shared": self.shared.status(),
                "monitor": self.monitor.status(),
                "auth": self.auth.status(),
            },
        }


# ---------------------------------------------------------------------------
# Route Handler Type
# ---------------------------------------------------------------------------

RouteHandler = Callable[["APIHandler", dict[str, Any]], dict[str, Any]]
_routes: dict[str, dict[str, RouteHandler]] = {}


def route(method: str, path: str):
    """Decorator to register an API route."""
    def decorator(func: RouteHandler) -> RouteHandler:
        key = method.upper()
        if key not in _routes:
            _routes[key] = {}
        _routes[key][path] = func
        return func
    return decorator


# ---------------------------------------------------------------------------
# Route Definitions
# ---------------------------------------------------------------------------

# --- Platform Status ---

@route("GET", "/api/status")
def get_status(handler: "APIHandler", params: dict) -> dict:
    return handler.platform.status()


# --- Board ---

@route("GET", "/board/projects")
def board_projects(handler: "APIHandler", params: dict) -> dict:
    payload = board_api.get_all_projects({}, {})
    raw_limit = params.get("limit")
    if raw_limit is not None:
        try:
            limit = max(int(raw_limit), 0)
        except (TypeError, ValueError):
            limit = None
        if limit is not None:
            payload = dict(payload)
            payload["projects"] = list(payload.get("projects", []))[:limit]
    return payload


@route("POST", "/board/projects")
def board_create_project(handler: "APIHandler", params: dict) -> dict:
    project_id = str(params.get("id") or params.get("project_id") or "").strip()
    name = str(params.get("name", "")).strip()
    try:
        return board_api.create_project(project_id, name)
    except ValueError as exc:
        return {"error": str(exc)}


# --- Memory ---

@route("POST", "/api/memory/write")
def memory_write(handler: "APIHandler", params: dict) -> dict:
    agent_id = params.get("agent_id", "")
    category = params.get("category", "episodes")
    content = params.get("content", "")
    if not agent_id or not content:
        return {"error": "agent_id and content required"}
    result = handler.platform.memory.write(agent_id, category, content)
    return {"success": True, "result": result}


@route("POST", "/api/memory/search")
def memory_search(handler: "APIHandler", params: dict) -> dict:
    query = params.get("query", "")
    agent_id = params.get("agent_id", "")
    top_k = params.get("top_k", 5)
    if not query or not agent_id:
        return {"error": "query and agent_id required"}
    results = handler.platform.memory.search(query, agent_id, top_k=top_k)
    return {"results": [r.to_dict() for r in results]}


@route("POST", "/api/memory/daily")
def memory_daily(handler: "APIHandler", params: dict) -> dict:
    agent_id = params.get("agent_id", "")
    content = params.get("content", "")
    if not agent_id or not content:
        return {"error": "agent_id and content required"}
    result = handler.platform.memory.daily_note(agent_id, content)
    return {"success": True, "result": result}


@route("GET", "/api/memory/episodes")
def memory_episodes(handler: "APIHandler", params: dict) -> dict:
    agent_id = params.get("agent_id")
    limit = int(params.get("limit", "20"))
    episodes = handler.platform.memory.list_episodes(agent_id=agent_id, limit=limit)
    return {"episodes": episodes}


# --- Skills ---

@route("GET", "/api/skills/list")
def skills_list(handler: "APIHandler", params: dict) -> dict:
    skills = handler.platform.skills.list_skills()
    return {"skills": [s.to_dict() for s in skills]}


@route("POST", "/api/skills/activate")
def skills_activate(handler: "APIHandler", params: dict) -> dict:
    name = params.get("name", "")
    agent_id = params.get("agent_id", "")
    if not name or not agent_id:
        return {"error": "name and agent_id required"}
    ok = handler.platform.skills.activate_skill(name, agent_id)
    return {"success": ok}


@route("POST", "/api/skills/deactivate")
def skills_deactivate(handler: "APIHandler", params: dict) -> dict:
    name = params.get("name", "")
    agent_id = params.get("agent_id", "")
    if not name or not agent_id:
        return {"error": "name and agent_id required"}
    ok = handler.platform.skills.deactivate_skill(name, agent_id)
    return {"success": ok}


# --- Approval Gate ---

@route("GET", "/api/approval/queue")
def approval_queue(handler: "APIHandler", params: dict) -> dict:
    agent_id = params.get("agent_id")
    items = handler.platform.approval.get_pending(agent_id=agent_id)
    return {"pending": [i.to_dict() for i in items]}


@route("POST", "/api/approval/request")
def approval_request(handler: "APIHandler", params: dict) -> dict:
    action_type = params.get("action_type", "")
    agent_id = params.get("agent_id", "")
    description = params.get("description", "")
    preview = params.get("preview", "")
    if not action_type or not agent_id:
        return {"error": "action_type and agent_id required"}
    req = handler.platform.approval.request_approval(
        action_type=action_type,
        agent_id=agent_id,
        description=description,
        preview=preview,
    )
    return {"success": True, "request": req.to_dict()}


@route("POST", "/api/approval/approve")
def approval_approve(handler: "APIHandler", params: dict) -> dict:
    request_id = params.get("request_id", "")
    approver = params.get("approver", "user")
    if not request_id:
        return {"error": "request_id required"}
    result = handler.platform.approval.approve(request_id, approver=approver)
    if result:
        return {"success": True, "result": result.to_dict()}
    return {"success": False, "error": "Request not found or already resolved"}


@route("POST", "/api/approval/deny")
def approval_deny(handler: "APIHandler", params: dict) -> dict:
    request_id = params.get("request_id", "")
    reason = params.get("reason", "")
    approver = params.get("approver", "user")
    if not request_id:
        return {"error": "request_id required"}
    result = handler.platform.approval.deny(
        request_id, approver=approver, reason=reason,
    )
    if result:
        return {"success": True, "result": result.to_dict()}
    return {"success": False, "error": "Request not found or already resolved"}


# --- Auth ---

@route("POST", "/api/auth/create_key")
def auth_create_key(handler: "APIHandler", params: dict) -> dict:
    owner = params.get("owner", "")
    if not owner:
        return {"error": "owner required"}
    raw_key, api_key = handler.platform.auth.create_key(owner)
    return {"key": raw_key, "key_info": api_key.to_dict()}


@route("GET", "/api/auth/keys")
def auth_list_keys(handler: "APIHandler", params: dict) -> dict:
    owner = params.get("owner")
    keys = handler.platform.auth.list_keys(owner=owner)
    return {"keys": [k.to_dict() for k in keys]}


# --- Engine Routing ---

@route("GET", "/api/engines/list")
def engines_list(handler: "APIHandler", params: dict) -> dict:
    return {"engines": list(ENGINE_REGISTRY.keys())}


@route("POST", "/api/engines/route")
def engines_route(handler: "APIHandler", params: dict) -> dict:
    category = params.get("category", "default")
    agent_id = params.get("agent_id", "")
    decision = handler.platform.router.route(category=category, agent_id=agent_id)
    return {"decision": decision.to_dict()}


# --- Runtime Manager ---

@route("GET", "/api/agents/list")
def agents_list(handler: "APIHandler", params: dict) -> dict:
    agents = handler.platform.runtime.list_agents()
    return {"agents": [a.to_dict() for a in agents]}


@route("GET", "/api/agents/status")
def agents_status(handler: "APIHandler", params: dict) -> dict:
    return handler.platform.runtime.status()


# --- Message Bus ---

@route("POST", "/api/messages/send")
def messages_send(handler: "APIHandler", params: dict) -> dict:
    sender = params.get("sender", "")
    recipient = params.get("recipient", "")
    content = params.get("content", "")
    if not sender or not content:
        return {"error": "sender and content required"}
    msg = handler.platform.bus.append(sender, recipient, content)
    return {"success": True, "message": msg.to_dict()}


@route("POST", "/api/messages/receive")
def messages_receive(handler: "APIHandler", params: dict) -> dict:
    agent_id = params.get("agent_id", "")
    limit = params.get("limit", 50)
    if not agent_id:
        return {"error": "agent_id required"}
    messages = handler.platform.bus.receive(agent_id, wait=0, limit=limit)
    return {"messages": [m.to_dict() for m in messages]}


@route("GET", "/api/messages/history")
def messages_history(handler: "APIHandler", params: dict) -> dict:
    limit = int(params.get("limit", "50"))
    messages = handler.platform.bus.history(limit=limit)
    return {"messages": [m.to_dict() for m in messages]}


# --- Shared Memory ---

@route("POST", "/api/shared/write")
def shared_write(handler: "APIHandler", params: dict) -> dict:
    topic = params.get("topic", "")
    content = params.get("content", "")
    agent_id = params.get("agent_id", "")
    if not topic or not content:
        return {"error": "topic and content required"}
    result = handler.platform.shared.write(topic, content, agent_id)
    return {"success": True, "result": result}


@route("GET", "/api/shared/read")
def shared_read(handler: "APIHandler", params: dict) -> dict:
    topic = params.get("topic", "")
    if not topic:
        return {"error": "topic required"}
    entry = handler.platform.shared.read(topic)
    if entry:
        return {"entry": entry.to_dict()}
    return {"entry": None}


@route("POST", "/api/shared/search")
def shared_search(handler: "APIHandler", params: dict) -> dict:
    query = params.get("query", "")
    if not query:
        return {"error": "query required"}
    results = handler.platform.shared.search(query)
    return {"results": [r.to_dict() for r in results]}


# --- Monitor ---

@route("GET", "/api/monitor/fleet")
def monitor_fleet(handler: "APIHandler", params: dict) -> dict:
    summary = handler.platform.monitor.fleet_summary()
    return summary.to_dict()


@route("GET", "/api/monitor/alerts")
def monitor_alerts(handler: "APIHandler", params: dict) -> dict:
    agent_id = params.get("agent_id")
    level = params.get("level")
    limit = int(params.get("limit", "50"))
    alerts = handler.platform.monitor.get_alerts(
        agent_id=agent_id, level=level, limit=limit,
    )
    return {"alerts": [a.to_dict() for a in alerts]}


# --- Delegation ---

@route("POST", "/api/delegation/create")
def delegation_create(handler: "APIHandler", params: dict) -> dict:
    parent_agent = params.get("parent_agent", "")
    description = params.get("description", "")
    if not parent_agent or not description:
        return {"error": "parent_agent and description required"}
    task = handler.platform.delegation.create_task(
        parent_agent=parent_agent,
        description=description,
        engine=params.get("engine", "claude"),
    )
    return {"success": True, "task": task.to_dict()}


@route("GET", "/api/delegation/status")
def delegation_status(handler: "APIHandler", params: dict) -> dict:
    return handler.platform.delegation.status()


@route("GET", "/api/delegation/task")
def delegation_task(handler: "APIHandler", params: dict) -> dict:
    task_id = params.get("task_id", "")
    if not task_id:
        return {"error": "task_id required"}
    task = handler.platform.delegation.get_task(task_id)
    if task:
        return {"task": task.to_dict()}
    return {"error": f"Task '{task_id}' not found"}


# --- Soul ---

@route("GET", "/api/soul/resolve")
def soul_resolve(handler: "APIHandler", params: dict) -> dict:
    agent_id = params.get("agent_id", "")
    if not agent_id:
        return {"error": "agent_id required"}
    config = soul_engine.resolve_soul(agent_id, handler.platform.souls_dir)
    return {"soul": {
        "agent_id": config.agent_id,
        "name": config.name,
        "core_truths": config.core_truths,
        "strengths": config.strengths,
        "growth_area": config.growth_area,
        "communication_style": config.communication_style,
        "quirks": config.quirks,
        "boundaries": config.boundaries,
    }}


@route("GET", "/api/soul/identity")
def soul_identity(handler: "APIHandler", params: dict) -> dict:
    agent_id = params.get("agent_id", "")
    if not agent_id:
        return {"error": "agent_id required"}
    prolog, md = soul_engine.prepare_agent_identity(
        agent_id, handler.platform.souls_dir,
    )
    return {"prolog": prolog, "soul_md": md}


# --- Reflection ---

@route("GET", "/api/reflection/status")
def reflection_status(handler: "APIHandler", params: dict) -> dict:
    return {"status": "active"}


# --- Context Scan ---

@route("GET", "/api/context/scan")
def context_scan(handler: "APIHandler", params: dict) -> dict:
    """Scan a project directory for Claude/Codex config files."""
    project_path = params.get("project_path", "")
    if not project_path:
        return {"error": "project_path required"}

    p = Path(project_path)
    if not p.is_dir():
        return {"error": f"Directory not found: {project_path}"}

    claude_files = [
        {"source": "CLAUDE.md", "path": str(p / "CLAUDE.md"),
         "exists": (p / "CLAUDE.md").exists(), "is_dir": False},
        {"source": ".claude/", "path": str(p / ".claude"),
         "exists": (p / ".claude").is_dir(), "is_dir": True},
        {"source": ".claude/settings.json", "path": str(p / ".claude" / "settings.json"),
         "exists": (p / ".claude" / "settings.json").exists(), "is_dir": False},
        {"source": ".claude/settings.local.json", "path": str(p / ".claude" / "settings.local.json"),
         "exists": (p / ".claude" / "settings.local.json").exists(), "is_dir": False},
        {"source": ".agent_sessions/", "path": str(p / ".agent_sessions"),
         "exists": (p / ".agent_sessions").is_dir(), "is_dir": True},
        {"source": ".mcp.json", "path": str(p / ".mcp.json"),
         "exists": (p / ".mcp.json").exists(), "is_dir": False},
    ]

    codex_files = [
        {"source": "AGENTS.md", "path": str(p / "AGENTS.md"),
         "exists": (p / "AGENTS.md").exists(), "is_dir": False},
        {"source": "codex.json", "path": str(p / "codex.json"),
         "exists": (p / "codex.json").exists(), "is_dir": False},
    ]

    return {
        "claude": {"config": claude_files},
        "codex": {"config": codex_files},
    }


# --- Project Create ---

@route("POST", "/api/projects/create")
def projects_create(handler: "APIHandler", params: dict) -> dict:
    """Create a new Bridge IDE project structure."""
    project_name = params.get("project_name", "")
    base_dir = params.get("base_dir", "")
    if not project_name or not base_dir:
        return {"ok": False, "error": "project_name and base_dir required"}

    p = Path(base_dir)
    if not p.is_dir():
        return {"ok": False, "error": f"Directory not found: {base_dir}"}

    created = []

    # CLAUDE.md
    claude_md_path = p / "CLAUDE.md"
    if not claude_md_path.exists():
        claude_md_path.write_text(
            f"# {project_name}\n\nBridge IDE Project.\n", encoding="utf-8"
        )
        created.append(str(claude_md_path))

    # .claude directory + settings
    claude_dir = p / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.json"
    if not settings_path.exists():
        settings_path.write_text(json.dumps({
            "permissions": {
                "allow": ["Read", "Edit", "Write", "Bash", "Glob", "Grep",
                           "mcp__bridge"],
                "defaultMode": "bypassPermissions"
            }
        }, indent=2), encoding="utf-8")
        created.append(str(settings_path))

    # .agent_sessions directory
    sessions_dir = p / ".agent_sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    created.append(str(sessions_dir))

    return {
        "ok": True,
        "project_path": str(p),
        "created": created,
    }


# --- Runtime Configure (Start Team) ---

@route("POST", "/api/runtime/configure")
def runtime_configure(handler: "APIHandler", params: dict) -> dict:
    """Configure and start a team of agents."""
    project_path = params.get("project_path", "")
    if not project_path:
        return {"ok": False, "error": "project_path required"}

    if not Path(project_path).is_dir():
        return {"ok": False, "error": f"Directory not found: {project_path}"}

    leader = params.get("leader", {})
    agents = params.get("agents", [])

    started = []
    errors = []

    # Register leader in runtime manager
    if leader:
        leader_name = leader.get("name", "leader")
        leader_role = leader.get("prompt", "Team Lead")
        leader_engine = params.get("team_lead_engine", "claude")
        try:
            handler.platform.runtime.create_agent(
                agent_id=leader_name, role=leader_role, engine=leader_engine
            )
            handler.platform.runtime.start_agent(leader_name)
            started.append(leader_name)
        except ValueError as e:
            errors.append({"agent": leader_name, "error": str(e)})

    # Register agents in runtime manager
    for i, agent_cfg in enumerate(agents):
        agent_name = agent_cfg.get("name", "") or agent_cfg.get("slot", f"agent_{i}")
        agent_role = agent_cfg.get("prompt", agent_cfg.get("position", "Agent"))
        agent_engine = params.get(f"agent_{'ab'[i]}_engine", "claude") if i < 2 else "claude"
        try:
            handler.platform.runtime.create_agent(
                agent_id=agent_name, role=agent_role, engine=agent_engine
            )
            handler.platform.runtime.start_agent(agent_name)
            started.append(agent_name)
        except ValueError as e:
            errors.append({"agent": agent_name, "error": str(e)})

    result: dict[str, Any] = {"ok": len(errors) == 0, "started": started}
    if errors:
        result["errors"] = errors
    return result


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class APIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the unified API."""

    platform: Platform  # Set by server

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/api/status"
        query = parse_qs(parsed.query)
        params = {k: v[0] if len(v) == 1 else v for k, v in query.items()}

        handler_func = _routes.get("GET", {}).get(path)
        if handler_func:
            try:
                result = handler_func(self, params)
                self._send_json(200, result)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": f"Not found: {path}"})

    def do_POST(self):
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/")

        # Read JSON body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else "{}"
        try:
            params = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        handler_func = _routes.get("POST", {}).get(path)
        if handler_func:
            try:
                result = handler_func(self, params)
                self._send_json(200, result)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": f"Not found: {path}"})

    def _send_cors_and_security_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Content-Security-Policy", "default-src 'none'")

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_and_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_and_security_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default logging


# ---------------------------------------------------------------------------
# Server Startup
# ---------------------------------------------------------------------------

def create_server(
    port: int = DEFAULT_API_PORT,
    data_dir: str = "",
) -> tuple[ThreadingHTTPServer, Platform]:
    """Create and configure the API server.

    Args:
        port: Port to listen on.
        data_dir: Data directory for persistence.

    Returns:
        Tuple of (server, platform).
    """
    platform = Platform(data_dir=data_dir)
    APIHandler.platform = platform

    server = ThreadingHTTPServer(("127.0.0.1", port), APIHandler)
    return server, platform


def main():
    port = int(os.environ.get("BRIDGE_API_PORT", DEFAULT_API_PORT))
    data_dir = os.environ.get("BRIDGE_DATA_DIR", "")

    server, platform = create_server(port=port, data_dir=data_dir)
    print(f"Bridge API Server running on :{port}")
    print(f"Data dir: {platform.data_dir}")
    print(f"Registered routes: {sum(len(v) for v in _routes.values())}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
