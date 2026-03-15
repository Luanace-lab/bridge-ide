"""Guardrails route extraction from server.py."""

from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import parse_qs


_is_management_agent: Callable[[str], bool] | None = None
_POLICY_RE = re.compile(r"^/guardrails/([a-zA-Z0-9_-]+)$")
_APPLY_PRESET_RE = re.compile(r"^/guardrails/([a-zA-Z0-9_-]+)/apply-preset$")


def init(*, is_management_agent_fn: Callable[[str], bool]) -> None:
    global _is_management_agent
    _is_management_agent = is_management_agent_fn


def _is_management(agent_id: str) -> bool:
    if _is_management_agent is None:
        raise RuntimeError("handlers.guardrails_routes.init() not called: is_management_agent_fn missing")
    return _is_management_agent(agent_id)


def handle_get(handler: Any, path: str, query_string: str) -> bool:
    import guardrails

    if path == "/guardrails":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        if requesting_agent and not _is_management(requesting_agent):
            handler._respond(403, {"error": "guardrails admin-only (management level)"})
            return True
        policies = guardrails.list_policies()
        handler._respond(200, {
            "policies": policies,
            "count": len(policies),
            "consequential_catalog_groups": list(guardrails.list_consequential_tools().keys()),
        })
        return True

    if path == "/guardrails/catalog":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        if requesting_agent and not _is_management(requesting_agent):
            handler._respond(403, {"error": "guardrails admin-only (management level)"})
            return True
        catalog = guardrails.list_consequential_tools()
        handler._respond(200, {"catalog": catalog, "count": len(catalog)})
        return True

    if path == "/guardrails/presets":
        presets = guardrails.list_presets()
        handler._respond(200, {"presets": presets, "count": len(presets)})
        return True

    if path == "/guardrails/summary":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        qs = parse_qs(query_string, keep_blank_values=False)
        agent_filter = qs.get("agent_id", [""])[0]
        type_filter = qs.get("type", [""])[0]
        limit = min(int(qs.get("limit", ["500"])[0]), 500)
        if requesting_agent and not _is_management(requesting_agent):
            if not agent_filter:
                handler._respond(403, {"error": "guardrails summary requires self agent_id filter or management access"})
                return True
            if agent_filter != requesting_agent:
                handler._respond(403, {"error": "guardrails summary access is limited to own entries"})
                return True
        summary = guardrails.summarize_violations(
            agent_id=agent_filter,
            limit=limit,
            violation_type=type_filter,
        )
        handler._respond(200, {"summary": summary})
        return True

    if path == "/guardrails/violations":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        qs = parse_qs(query_string, keep_blank_values=False)
        agent_filter = qs.get("agent_id", [""])[0]
        type_filter = qs.get("type", [""])[0]
        limit = min(int(qs.get("limit", ["50"])[0]), 500)
        if requesting_agent and not _is_management(requesting_agent):
            if not agent_filter:
                handler._respond(403, {"error": "guardrails violations require self agent_id filter or management access"})
                return True
            if agent_filter != requesting_agent:
                handler._respond(403, {"error": "guardrails violations access is limited to own entries"})
                return True
        violations = guardrails.get_violations(
            agent_id=agent_filter,
            limit=limit,
            violation_type=type_filter,
        )
        handler._respond(200, {"violations": violations, "count": len(violations)})
        return True

    policy_match = _POLICY_RE.match(path)
    if policy_match and policy_match.group(1) != "violations":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        agent_id = policy_match.group(1)
        if requesting_agent and not _is_management(requesting_agent) and requesting_agent != agent_id:
            handler._respond(403, {"error": "guardrails policy access is limited to self or management"})
            return True
        policy = guardrails.get_policy(agent_id)
        handler._respond(200, policy)
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    import guardrails

    if path == "/guardrails/evaluate":
        requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        agent_id = str(data.get("agent_id", "")).strip()
        if not agent_id:
            handler._respond(400, {"error": "field 'agent_id' is required"})
            return True
        if requesting_agent and requesting_agent != agent_id and not _is_management(requesting_agent):
            handler._respond(403, {"error": "guardrails evaluate requires self or management access"})
            return True
        tool_name = str(data.get("tool_name", "")).strip()
        action_text = str(data.get("action_text", "")).strip()
        result = guardrails.evaluate_policy(agent_id, tool_name=tool_name, action_text=action_text)
        handler._respond(200, {"ok": True, "evaluation": result})
        return True

    match = _APPLY_PRESET_RE.match(path)
    if not match:
        return False

    requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
    if requesting_agent and not _is_management(requesting_agent):
        handler._respond(403, {"error": "guardrails preset apply admin-only (management level)"})
        return True
    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid or missing JSON body"})
        return True
    preset_name = str(data.get("preset_name", "")).strip()
    if not preset_name:
        handler._respond(400, {"error": "field 'preset_name' is required"})
        return True
    try:
        policy = guardrails.apply_preset(
            match.group(1),
            preset_name,
            overrides=data.get("overrides"),
            replace=bool(data.get("replace", True)),
        )
    except KeyError:
        handler._respond(404, {"error": f"guardrails preset '{preset_name}' not found"})
        return True
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
        return True
    handler._respond(200, {"ok": True, "preset_name": preset_name, "policy": policy})
    return True


def handle_put(handler: Any, path: str) -> bool:
    match = _POLICY_RE.match(path)
    if not match:
        return False

    import guardrails

    requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
    if requesting_agent and not _is_management(requesting_agent):
        handler._respond(403, {"error": "guardrails admin-only (management level)"})
        return True
    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid or missing JSON body"})
        return True
    valid_keys = {
        "allowed_tools",
        "denied_actions",
        "rate_limits",
        "output_schema",
        "consequential_tools_mode",
        "preset_name",
        "preset_applied_at",
    }
    unknown = set(data.keys()) - valid_keys
    if unknown:
        handler._respond(400, {"error": f"unknown fields: {sorted(unknown)}. Allowed: {sorted(valid_keys)}"})
        return True
    policy = guardrails.set_policy(match.group(1), data)
    handler._respond(200, {"ok": True, "policy": policy})
    return True


def handle_delete(handler: Any, path: str) -> bool:
    match = _POLICY_RE.match(path)
    if not match:
        return False

    import guardrails

    requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
    if requesting_agent and not _is_management(requesting_agent):
        handler._respond(403, {"error": "guardrails admin-only (management level)"})
        return True
    agent_id = match.group(1)
    deleted = guardrails.delete_policy(agent_id)
    if deleted:
        handler._respond(200, {"ok": True, "message": f"policy for '{agent_id}' deleted (reverted to default)"})
    else:
        handler._respond(404, {"error": f"no policy for '{agent_id}'"})
    return True
