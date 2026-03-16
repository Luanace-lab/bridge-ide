"""Credential store HTTP routes extracted from server.py."""

from __future__ import annotations

from typing import Any

import credential_store

# SEC-001: Lazy import to avoid circular dependency
_registered_agents = None

def _is_known_agent(agent_id: str) -> bool:
    """Check if agent_id is a registered agent, 'user', or 'system'."""
    global _registered_agents
    if agent_id in ("user", "system"):
        return True
    if _registered_agents is None:
        try:
            import server
            _registered_agents = server.REGISTERED_AGENTS
        except (ImportError, AttributeError):
            return True  # fail-open if import fails
    return agent_id in _registered_agents


def _extract_service_and_key(path: str) -> tuple[str, str] | None:
    if not path.startswith("/credentials/"):
        return None
    parts = path.split("/")
    if len(parts) < 3 or not parts[2]:
        return None
    service = parts[2]
    key = parts[3] if len(parts) > 3 and parts[3] else ""
    return service, key


def handle_get(handler: Any, path: str) -> bool:
    parsed = _extract_service_and_key(path)
    if parsed is None:
        return False

    cred_service, cred_key = parsed
    agent_id = str(handler.headers.get("X-Bridge-Agent", "")).strip()
    if not agent_id:
        handler._respond(401, {"error": "X-Bridge-Agent header required"})
        return True
    if not _is_known_agent(agent_id):
        handler._respond(403, {"error": f"Unknown agent: {agent_id}"})
        return True

    try:
        if cred_key:
            result = credential_store.get(cred_service, cred_key, agent_id=agent_id)
        else:
            result = credential_store.list_keys(cred_service, agent_id=agent_id)
        handler._respond(200, result)
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
    except KeyError as exc:
        handler._respond(404, {"error": str(exc)})
    except PermissionError as exc:
        handler._respond(403, {"error": str(exc)})
    except Exception as exc:
        handler._respond(500, {"error": str(exc)})
    return True


def handle_post(handler: Any, path: str) -> bool:
    parsed = _extract_service_and_key(path)
    if parsed is None:
        return False

    cred_service, cred_key = parsed
    if not cred_key:
        handler._respond(400, {"error": "path must be /credentials/{service}/{key}"})
        return True

    agent_id = str(handler.headers.get("X-Bridge-Agent", "")).strip()
    if not agent_id:
        handler._respond(401, {"error": "X-Bridge-Agent header required"})
        return True
    if not _is_known_agent(agent_id):
        handler._respond(403, {"error": f"Unknown agent: {agent_id}"})
        return True

    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid or missing JSON body"})
        return True
    value = data.get("value")
    if value is None:
        handler._respond(400, {"error": "value field is required"})
        return True

    try:
        result = credential_store.store(cred_service, cred_key, value, agent_id=agent_id)
        handler._respond(201, result)
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
    except Exception as exc:
        handler._respond(500, {"error": str(exc)})
    return True


def handle_delete(handler: Any, path: str) -> bool:
    parsed = _extract_service_and_key(path)
    if parsed is None:
        return False

    cred_service, cred_key = parsed
    if not cred_key:
        handler._respond(400, {"error": "path must be /credentials/{service}/{key}"})
        return True

    agent_id = str(handler.headers.get("X-Bridge-Agent", "")).strip()
    if not agent_id:
        handler._respond(401, {"error": "X-Bridge-Agent header required"})
        return True
    if not _is_known_agent(agent_id):
        handler._respond(403, {"error": f"Unknown agent: {agent_id}"})
        return True

    try:
        result = credential_store.delete(cred_service, cred_key, agent_id=agent_id)
        handler._respond(200, result)
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
    except KeyError as exc:
        handler._respond(404, {"error": str(exc)})
    except PermissionError as exc:
        handler._respond(403, {"error": str(exc)})
    except Exception as exc:
        handler._respond(500, {"error": str(exc)})
    return True
