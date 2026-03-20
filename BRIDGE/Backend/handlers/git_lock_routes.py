"""Git advisory lock HTTP routes extracted from server.py."""

from __future__ import annotations

from typing import Any, Callable


_git_locks_file: str | None = None
_acquire_lock: Callable[[str, str, str, str], dict[str, Any]] | None = None
_release_lock: Callable[[str, str, str], dict[str, Any]] | None = None
_load_locks: Callable[[str], list[dict[str, Any]]] | None = None
_save_locks: Callable[[str, list[dict[str, Any]]], None] | None = None
_is_management_agent: Callable[[str], bool] | None = None


def init(
    *,
    git_locks_file: str,
    acquire_lock_fn: Callable[[str, str, str, str], dict[str, Any]] | None,
    release_lock_fn: Callable[[str, str, str], dict[str, Any]] | None,
    load_locks_fn: Callable[[str], list[dict[str, Any]]] | None,
    save_locks_fn: Callable[[str, list[dict[str, Any]]], None] | None,
    is_management_agent_fn: Callable[[str], bool],
) -> None:
    global _git_locks_file, _acquire_lock, _release_lock, _load_locks, _save_locks, _is_management_agent
    _git_locks_file = git_locks_file
    _acquire_lock = acquire_lock_fn
    _release_lock = release_lock_fn
    _load_locks = load_locks_fn
    _save_locks = save_locks_fn
    _is_management_agent = is_management_agent_fn


def _require_locks_file() -> str:
    if not _git_locks_file:
        raise RuntimeError("handlers.git_lock_routes.init() not called: git_locks_file missing")
    return _git_locks_file


def _management_agent(agent_id: str) -> bool:
    if _is_management_agent is None:
        raise RuntimeError("handlers.git_lock_routes.init() not called: is_management_agent_fn missing")
    return _is_management_agent(agent_id)


def handle_get(handler: Any, path: str) -> bool:
    if path != "/git/locks":
        return False

    if _load_locks is None:
        handler._respond(501, {"error": "git_collaboration module not available"})
        return True
    active = _load_locks(_require_locks_file())
    handler._respond(200, {"ok": True, "locks": active, "count": len(active)})
    return True


def handle_post(handler: Any, path: str) -> bool:
    if path != "/git/lock":
        return False

    if _acquire_lock is None:
        handler._respond(501, {"error": "git_collaboration module not available"})
        return True

    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid JSON body"})
        return True

    branch = str(data.get("branch", "")).strip()
    instance_id = str(data.get("instance_id", "")).strip()
    header_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
    body_agent = str(data.get("agent_id", "")).strip()
    lock_agent = header_agent or body_agent

    if not branch or not lock_agent:
        handler._respond(400, {"error": "branch and agent_id (or X-Bridge-Agent header) required"})
        return True
    if header_agent and body_agent and header_agent != body_agent and not _management_agent(header_agent):
        handler._respond(
            403,
            {
                "error": (
                    f"Identity mismatch: header agent '{header_agent}' != body agent_id '{body_agent}'. "
                    "Cannot acquire locks for other agents."
                )
            },
        )
        return True

    result = _acquire_lock(_require_locks_file(), branch, lock_agent, instance_id)
    handler._respond(200 if result.get("ok") else 409, result)
    return True


def handle_delete(handler: Any, path: str) -> bool:
    if path != "/git/lock":
        return False

    if _release_lock is None:
        handler._respond(501, {"error": "git_collaboration module not available"})
        return True

    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid JSON body"})
        return True

    branch = str(data.get("branch", "")).strip()
    header_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
    body_agent = str(data.get("agent_id", "")).strip()
    lock_agent = header_agent or body_agent

    if not branch:
        handler._respond(400, {"error": "branch required"})
        return True
    if not lock_agent:
        handler._respond(400, {"error": "agent_id (or X-Bridge-Agent header) required"})
        return True
    if header_agent and body_agent and header_agent != body_agent and not _management_agent(header_agent):
        handler._respond(
            403,
            {
                "error": (
                    f"Identity mismatch: header agent '{header_agent}' != body agent_id '{body_agent}'. "
                    "Cannot release locks for other agents."
                )
            },
        )
        return True

    result = _release_lock(_require_locks_file(), branch, lock_agent)
    if result.get("ok"):
        handler._respond(200, result)
        return True
    if result.get("error") == "not_locked":
        handler._respond(404, result)
        return True
    if result.get("error") == "not_owner":
        requesting = header_agent
        if requesting and _management_agent(requesting) and _load_locks and _save_locks:
            locks = _load_locks(_require_locks_file())
            locks = [lock for lock in locks if lock.get("branch") != branch]
            _save_locks(_require_locks_file(), locks)
            handler._respond(200, {"ok": True, "released": branch, "forced_by": requesting})
            return True
        handler._respond(403, result)
        return True

    handler._respond(400, result)
    return True
