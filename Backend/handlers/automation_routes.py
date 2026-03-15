"""Automation route extraction from server.py."""

from __future__ import annotations

import re
from typing import Any, Callable


_GET_ALL_AUTOMATIONS_FN: Callable[[], list[dict[str, Any]]] | None = None
_GET_AUTOMATION_FN: Callable[[str], dict[str, Any] | None] | None = None
_GET_EXECUTION_HISTORY_FN: Callable[[str, int], list[dict[str, Any]]] | None = None
_GET_EXECUTION_BY_ID_FN: Callable[[str], dict[str, Any] | None] | None = None
_ADD_AUTOMATION_FN: Callable[[dict[str, Any]], tuple[dict[str, Any] | None, str | None]] | None = None
_UPDATE_AUTOMATION_FN: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None
_DELETE_AUTOMATION_FN: Callable[[str], bool] | None = None
_SET_AUTOMATION_ACTIVE_FN: Callable[[str, bool], dict[str, Any] | None] | None = None
_SET_AUTOMATION_PAUSE_FN: Callable[[str, str | None], dict[str, Any] | None] | None = None
_CHECK_HIERARCHY_PERMISSION_FN: Callable[[str, str], bool] | None = None
_WS_BROADCAST_FN: Callable[[str, dict[str, Any]], None] | None = None
_GET_SCHEDULER_FN: Callable[[], Any] | None = None
_DISPATCH_WEBHOOK_FN: Callable[[str, dict[str, Any] | None], dict[str, Any]] | None = None


def init(
    *,
    get_all_automations_fn: Callable[[], list[dict[str, Any]]],
    get_automation_fn: Callable[[str], dict[str, Any] | None],
    get_execution_history_fn: Callable[[str, int], list[dict[str, Any]]],
    get_execution_by_id_fn: Callable[[str], dict[str, Any] | None],
    add_automation_fn: Callable[[dict[str, Any]], tuple[dict[str, Any] | None, str | None]],
    update_automation_fn: Callable[[str, dict[str, Any]], dict[str, Any] | None],
    delete_automation_fn: Callable[[str], bool],
    set_automation_active_fn: Callable[[str, bool], dict[str, Any] | None],
    set_automation_pause_fn: Callable[[str, str | None], dict[str, Any] | None],
    check_hierarchy_permission_fn: Callable[[str, str], bool],
    ws_broadcast_fn: Callable[[str, dict[str, Any]], None],
    get_scheduler_fn: Callable[[], Any],
    dispatch_webhook_fn: Callable[[str, dict[str, Any] | None], dict[str, Any]],
) -> None:
    global _GET_ALL_AUTOMATIONS_FN, _GET_AUTOMATION_FN
    global _GET_EXECUTION_HISTORY_FN, _GET_EXECUTION_BY_ID_FN
    global _ADD_AUTOMATION_FN, _UPDATE_AUTOMATION_FN, _DELETE_AUTOMATION_FN
    global _SET_AUTOMATION_ACTIVE_FN, _SET_AUTOMATION_PAUSE_FN
    global _CHECK_HIERARCHY_PERMISSION_FN, _WS_BROADCAST_FN
    global _GET_SCHEDULER_FN, _DISPATCH_WEBHOOK_FN
    _GET_ALL_AUTOMATIONS_FN = get_all_automations_fn
    _GET_AUTOMATION_FN = get_automation_fn
    _GET_EXECUTION_HISTORY_FN = get_execution_history_fn
    _GET_EXECUTION_BY_ID_FN = get_execution_by_id_fn
    _ADD_AUTOMATION_FN = add_automation_fn
    _UPDATE_AUTOMATION_FN = update_automation_fn
    _DELETE_AUTOMATION_FN = delete_automation_fn
    _SET_AUTOMATION_ACTIVE_FN = set_automation_active_fn
    _SET_AUTOMATION_PAUSE_FN = set_automation_pause_fn
    _CHECK_HIERARCHY_PERMISSION_FN = check_hierarchy_permission_fn
    _WS_BROADCAST_FN = ws_broadcast_fn
    _GET_SCHEDULER_FN = get_scheduler_fn
    _DISPATCH_WEBHOOK_FN = dispatch_webhook_fn


def _get_all_automations() -> list[dict[str, Any]]:
    if _GET_ALL_AUTOMATIONS_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: get_all_automations_fn missing")
    return _GET_ALL_AUTOMATIONS_FN()


def _get_automation(auto_id: str) -> dict[str, Any] | None:
    if _GET_AUTOMATION_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: get_automation_fn missing")
    return _GET_AUTOMATION_FN(auto_id)


def _get_execution_history(auto_id: str, limit: int) -> list[dict[str, Any]]:
    if _GET_EXECUTION_HISTORY_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: get_execution_history_fn missing")
    return _GET_EXECUTION_HISTORY_FN(auto_id, limit)


def _get_execution_by_id(exec_id: str) -> dict[str, Any] | None:
    if _GET_EXECUTION_BY_ID_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: get_execution_by_id_fn missing")
    return _GET_EXECUTION_BY_ID_FN(exec_id)


def _add_automation(data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if _ADD_AUTOMATION_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: add_automation_fn missing")
    return _ADD_AUTOMATION_FN(data)


def _update_automation(auto_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    if _UPDATE_AUTOMATION_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: update_automation_fn missing")
    return _UPDATE_AUTOMATION_FN(auto_id, data)


def _delete_automation(auto_id: str) -> bool:
    if _DELETE_AUTOMATION_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: delete_automation_fn missing")
    return _DELETE_AUTOMATION_FN(auto_id)


def _set_automation_active(auto_id: str, active: bool) -> dict[str, Any] | None:
    if _SET_AUTOMATION_ACTIVE_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: set_automation_active_fn missing")
    return _SET_AUTOMATION_ACTIVE_FN(auto_id, active)


def _set_automation_pause(auto_id: str, paused_until: str | None) -> dict[str, Any] | None:
    if _SET_AUTOMATION_PAUSE_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: set_automation_pause_fn missing")
    return _SET_AUTOMATION_PAUSE_FN(auto_id, paused_until)


def _check_hierarchy_permission(creator: str, target: str) -> bool:
    if _CHECK_HIERARCHY_PERMISSION_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: check_hierarchy_permission_fn missing")
    return _CHECK_HIERARCHY_PERMISSION_FN(creator, target)


def _ws_broadcast(event: str, payload: dict[str, Any]) -> None:
    if _WS_BROADCAST_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: ws_broadcast_fn missing")
    _WS_BROADCAST_FN(event, payload)


def _get_scheduler() -> Any:
    if _GET_SCHEDULER_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: get_scheduler_fn missing")
    return _GET_SCHEDULER_FN()


def _dispatch_webhook(auto_id: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    if _DISPATCH_WEBHOOK_FN is None:
        raise RuntimeError("handlers.automation_routes.init() not called: dispatch_webhook_fn missing")
    return _DISPATCH_WEBHOOK_FN(auto_id, payload)


def _validate_trigger(handler: Any, trigger: Any) -> bool:
    if not isinstance(trigger, dict) or not trigger.get("type"):
        handler._respond(400, {"error": "trigger with type is required"})
        return False
    valid_trigger_types = {"schedule", "event", "condition", "webhook"}
    if trigger["type"] not in valid_trigger_types:
        handler._respond(400, {"error": f"invalid trigger type: {trigger['type']}. Valid: {sorted(valid_trigger_types)}"})
        return False
    if trigger["type"] == "schedule" and not trigger.get("cron"):
        handler._respond(400, {"error": "schedule trigger requires 'cron' field"})
        return False
    return True


def _validate_action(handler: Any, action: Any) -> bool:
    if not isinstance(action, dict) or not action.get("type"):
        handler._respond(400, {"error": "action with type is required"})
        return False
    valid_action_types = {"create_task", "send_message", "set_mode", "webhook", "chain"}
    if action["type"] not in valid_action_types:
        handler._respond(400, {"error": f"invalid action type: {action['type']}. Valid: {sorted(valid_action_types)}"})
        return False
    return True


def _assigned_target(action: dict[str, Any]) -> str:
    if action.get("type") == "create_task":
        return str(action.get("assigned_to", "")).strip()
    if action.get("type") == "set_mode":
        return str(action.get("agent_id", "")).strip()
    return ""


def handle_get(handler: Any, path: str, query: dict[str, list[str]] | None = None) -> bool:
    if path == "/automations":
        automations = _get_all_automations()
        handler._respond(200, {"automations": automations, "count": len(automations)})
        return True

    auto_match = re.match(r"^/automations/([^/]+)$", path)
    if auto_match:
        auto_id = auto_match.group(1)
        automation = _get_automation(auto_id)
        if not automation:
            handler._respond(404, {"error": f"automation '{auto_id}' not found"})
            return True
        handler._respond(200, automation)
        return True

    history_match = re.match(r"^/automations/([^/]+)/history$", path)
    if history_match:
        auto_id = history_match.group(1)
        try:
            limit = min(int((query or {}).get("limit", ["20"])[0]), 100)
        except (TypeError, ValueError):
            limit = 20
        history = _get_execution_history(auto_id, limit)
        handler._respond(200, {"history": history, "count": len(history)})
        return True

    exec_match = re.match(r"^/automations/([^/]+)/history/([^/]+)$", path)
    if exec_match:
        exec_id = exec_match.group(2)
        entry = _get_execution_by_id(exec_id)
        if not entry:
            handler._respond(404, {"error": f"execution '{exec_id}' not found"})
            return True
        handler._respond(200, entry)
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    if path != "/automations":
        return False

    data = handler._parse_json_body()
    if not data:
        handler._respond(400, {"error": "invalid json body"})
        return True

    name = str(data.get("name", "")).strip()
    if not name:
        handler._respond(400, {"error": "name is required"})
        return True

    trigger = data.get("trigger")
    if not _validate_trigger(handler, trigger):
        return True

    action = data.get("action")
    if not _validate_action(handler, action):
        return True

    created_by = (
        str(data.get("created_by", "")).strip()
        or str(handler.headers.get("X-Bridge-Agent", "")).strip()
        or "user"
    )
    data["created_by"] = created_by

    assigned_to = _assigned_target(action)
    if assigned_to and assigned_to != created_by and not _check_hierarchy_permission(created_by, assigned_to):
        handler._respond(403, {"error": f"'{created_by}' cannot create automations for '{assigned_to}' (hierarchy restriction)"})
        return True

    auto, warning = _add_automation(data)
    if auto is None:
        handler._respond(409, {"error": warning or "automation already exists"})
        return True

    _ws_broadcast("automation_created", {"automation": auto})
    response: dict[str, Any] = {"ok": True, "automation": auto}
    if warning:
        response["warning"] = warning
    handler._respond(201, response)
    return True


def handle_patch(handler: Any, path: str) -> bool:
    active_match = re.match(r"^/automations/([^/]+)/active$", path)
    if active_match:
        auto_id = active_match.group(1)
        data = handler._parse_json_body() or {}
        active = data.get("active")
        if active is None:
            handler._respond(400, {"error": "active (bool) is required"})
            return True
        result = _set_automation_active(auto_id, bool(active))
        if not result:
            handler._respond(404, {"error": f"automation '{auto_id}' not found"})
            return True
        _ws_broadcast("automation_updated", {"automation": result, "change": "active"})
        handler._respond(200, {"ok": True, "automation": result})
        return True

    pause_match = re.match(r"^/automations/([^/]+)/pause$", path)
    if pause_match:
        auto_id = pause_match.group(1)
        data = handler._parse_json_body() or {}
        paused_until = data.get("paused_until")
        result = _set_automation_pause(auto_id, paused_until)
        if not result:
            handler._respond(404, {"error": f"automation '{auto_id}' not found"})
            return True
        _ws_broadcast("automation_updated", {"automation": result, "change": "paused"})
        handler._respond(200, {"ok": True, "automation": result})
        return True

    return False


def handle_put(handler: Any, path: str) -> bool:
    auto_match = re.match(r"^/automations/([^/]+)$", path)
    if not auto_match:
        return False

    auto_id = auto_match.group(1)
    data = handler._parse_json_body()
    if not data:
        handler._respond(400, {"error": "invalid json body"})
        return True

    existing = _get_automation(auto_id)
    if not existing:
        handler._respond(404, {"error": f"automation '{auto_id}' not found"})
        return True

    if "trigger" in data and not _validate_trigger(handler, data["trigger"]):
        return True
    if "action" in data and not _validate_action(handler, data["action"]):
        return True

    requester = (
        str(data.get("updated_by", "")).strip()
        or str(handler.headers.get("X-Bridge-Agent", "")).strip()
        or "user"
    )
    action_data = data.get("action", existing.get("action", {}))
    assigned_to = _assigned_target(action_data)
    if assigned_to and assigned_to != requester and not _check_hierarchy_permission(requester, assigned_to):
        handler._respond(403, {"error": f"'{requester}' cannot create automations for '{assigned_to}' (hierarchy restriction)"})
        return True

    updates: dict[str, Any] = {}
    for field in ("name", "description", "trigger", "action", "options", "active"):
        if field in data:
            updates[field] = data[field]

    result = _update_automation(auto_id, updates)
    if not result:
        handler._respond(404, {"error": f"automation '{auto_id}' not found"})
        return True

    _ws_broadcast("automation_updated", {"automation": result, "change": "updated"})
    handler._respond(200, {"ok": True, "automation": result})
    return True


def handle_delete(handler: Any, path: str) -> bool:
    auto_match = re.match(r"^/automations/([^/]+)$", path)
    if not auto_match:
        return False

    auto_id = auto_match.group(1)
    requester = str(handler.headers.get("X-Bridge-Agent", "")).strip() or "user"
    existing = _get_automation(auto_id)
    if not existing:
        handler._respond(404, {"error": f"automation '{auto_id}' not found"})
        return True

    creator = existing.get("created_by", "user")
    if requester != "user" and requester != creator and not _check_hierarchy_permission(requester, creator):
        handler._respond(403, {"error": f"'{requester}' cannot delete automation created by '{creator}'"})
        return True

    deleted = _delete_automation(auto_id)
    if not deleted:
        handler._respond(404, {"error": f"automation '{auto_id}' not found"})
        return True

    _ws_broadcast("automation_deleted", {"automation_id": auto_id, "deleted_by": requester})
    handler._respond(200, {"ok": True, "deleted": deleted})
    return True


def handle_run(handler: Any, auto_id: str) -> None:
    auto = _get_automation(auto_id)
    if not auto:
        handler._respond(404, {"error": f"automation '{auto_id}' not found"})
        return

    scheduler = _get_scheduler()
    if scheduler and getattr(scheduler, "_action_callback", None):
        try:
            scheduler._action_callback(auto)
            scheduler._update_after_run(auto_id, "success")
            handler._respond(200, {"ok": True, "automation_id": auto_id, "status": "triggered"})
        except Exception as exc:
            scheduler._update_after_run(auto_id, "error", str(exc))
            handler._respond(500, {"error": f"execution failed: {exc}"})
        return

    handler._respond(200, {"ok": True, "automation_id": auto_id, "status": "triggered (no callback yet)"})


def handle_webhook(handler: Any, auto_id: str) -> None:
    data: dict[str, Any] = {}
    raw_length = handler.headers.get("Content-Length", "").strip()
    if raw_length not in ("", "0"):
        parsed = handler._parse_json_body()
        if parsed is None:
            handler._respond(400, {"error": "invalid json body"})
            return
        if not isinstance(parsed, dict):
            handler._respond(400, {"error": "webhook payload must be a JSON object"})
            return
        data = parsed

    result = _dispatch_webhook(auto_id, data)
    if not result.get("ok", False):
        status = 404 if "not found" in str(result.get("error", "")).lower() else 400
        handler._respond(status, result)
        return
    handler._respond(200, {"ok": True, **result})
