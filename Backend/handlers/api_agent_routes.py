"""API Agent routes — send messages to API-backed agents.

Complements the tmux-based agent management with direct API interaction
for agents configured with backend: "api" in team.json.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Lazy imports
_engine_backend = None


def _get_engine_backend():
    global _engine_backend
    if _engine_backend is None:
        import engine_backend
        _engine_backend = engine_backend
    return _engine_backend


def handle_api_agent_send(handler, path: str) -> bool:
    """POST /agents/{id}/api/send — Send message to an API-backed agent."""
    match = re.match(r"^/agents/([^/]+)/api/send$", path)
    if not match:
        return False

    agent_id = match.group(1)
    data = handler._parse_json_body()
    if not data:
        handler._respond(400, {"error": "JSON body with 'message' required"})
        return True

    message = str(data.get("message", "")).strip()
    if not message:
        handler._respond(400, {"error": "'message' field is required"})
        return True

    eb = _get_engine_backend()

    # Find backend for this agent
    backend = None
    for name in eb.list_backends():
        b = eb.get_backend(name)
        if b and b.is_alive(agent_id):
            backend = b
            break

    if not backend:
        handler._respond(404, {"error": f"No active API session for agent '{agent_id}'"})
        return True

    # Send message (sync wrapper for async)
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                response = pool.submit(asyncio.run, backend.send(agent_id, message)).result(timeout=120)
        else:
            response = asyncio.run(backend.send(agent_id, message))
    except Exception as exc:
        handler._respond(500, {"error": f"API call failed: {exc}"})
        return True

    handler._respond(200, {
        "ok": True,
        "agent_id": agent_id,
        "response": response,
        "backend": backend.get_engine_name(),
    })
    return True


def handle_api_agent_start(handler, path: str) -> bool:
    """POST /agents/{id}/api/start — Start an API-backed agent session."""
    match = re.match(r"^/agents/([^/]+)/api/start$", path)
    if not match:
        return False

    agent_id = match.group(1)
    data = handler._parse_json_body() or {}

    engine = str(data.get("engine", "claude")).strip().lower()
    model = str(data.get("model", "")).strip()
    system_prompt = str(data.get("system_prompt", "")).strip()

    eb = _get_engine_backend()
    backend = eb.resolve_backend(engine, "api")

    if not backend:
        handler._respond(400, {
            "error": f"No API backend available for engine '{engine}'. Configure API key first via POST /api/keys.",
            "available_backends": eb.list_backends(),
        })
        return True

    config = {
        "model": model,
        "system_prompt": system_prompt,
    }

    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                ok = pool.submit(asyncio.run, backend.start(agent_id, config)).result(timeout=30)
        else:
            ok = asyncio.run(backend.start(agent_id, config))
    except Exception as exc:
        handler._respond(500, {"error": f"Failed to start API agent: {exc}"})
        return True

    if ok:
        handler._respond(200, {
            "ok": True,
            "agent_id": agent_id,
            "backend": backend.get_engine_name(),
            "engine": engine,
            "model": model,
        })
    else:
        handler._respond(500, {"error": f"Backend start failed for {agent_id}"})
    return True


def handle_api_agent_stop(handler, path: str) -> bool:
    """POST /agents/{id}/api/stop — Stop an API-backed agent session."""
    match = re.match(r"^/agents/([^/]+)/api/stop$", path)
    if not match:
        return False

    agent_id = match.group(1)
    eb = _get_engine_backend()

    stopped = False
    for name in eb.list_backends():
        b = eb.get_backend(name)
        if b and b.is_alive(agent_id):
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        stopped = pool.submit(asyncio.run, b.stop(agent_id)).result(timeout=10)
                else:
                    stopped = asyncio.run(b.stop(agent_id))
            except Exception:
                pass
            break

    if stopped:
        handler._respond(200, {"ok": True, "agent_id": agent_id})
    else:
        handler._respond(404, {"error": f"No active API session for '{agent_id}'"})
    return True


def handle_api_agent_status(handler, path: str) -> bool:
    """GET /agents/{id}/api/status — Check API agent session status."""
    match = re.match(r"^/agents/([^/]+)/api/status$", path)
    if not match:
        return False

    agent_id = match.group(1)
    eb = _get_engine_backend()

    for name in eb.list_backends():
        b = eb.get_backend(name)
        if b and b.is_alive(agent_id):
            handler._respond(200, {
                "agent_id": agent_id,
                "alive": True,
                "backend": b.get_engine_name(),
            })
            return True

    handler._respond(200, {"agent_id": agent_id, "alive": False})
    return True
