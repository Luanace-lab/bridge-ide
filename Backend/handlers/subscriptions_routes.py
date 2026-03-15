"""Subscription CRUD route extraction from server.py."""

from __future__ import annotations

import os
import re
from typing import Any, Callable


_TEAM_CONFIG: dict[str, Any] | None = None
_TEAM_CONFIG_LOCK: Any = None
_BUILD_SUBSCRIPTION_RESPONSE_ITEM_FN: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]] | None = None
_INFER_SUBSCRIPTION_PROVIDER_FN: Callable[[str, str], str] | None = None
_ATOMIC_WRITE_TEAM_JSON_FN: Callable[[], None] | None = None


def init(
    *,
    team_config: dict[str, Any] | None,
    team_config_lock: Any,
    build_subscription_response_item_fn: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]],
    infer_subscription_provider_fn: Callable[[str, str], str],
    atomic_write_team_json_fn: Callable[[], None],
) -> None:
    global _TEAM_CONFIG, _TEAM_CONFIG_LOCK
    global _BUILD_SUBSCRIPTION_RESPONSE_ITEM_FN, _INFER_SUBSCRIPTION_PROVIDER_FN, _ATOMIC_WRITE_TEAM_JSON_FN
    _TEAM_CONFIG = team_config
    _TEAM_CONFIG_LOCK = team_config_lock
    _BUILD_SUBSCRIPTION_RESPONSE_ITEM_FN = build_subscription_response_item_fn
    _INFER_SUBSCRIPTION_PROVIDER_FN = infer_subscription_provider_fn
    _ATOMIC_WRITE_TEAM_JSON_FN = atomic_write_team_json_fn


def _build_subscription_response_item(sub: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    if _BUILD_SUBSCRIPTION_RESPONSE_ITEM_FN is None:
        raise RuntimeError("handlers.subscriptions_routes.init() not called: build_subscription_response_item_fn missing")
    return _BUILD_SUBSCRIPTION_RESPONSE_ITEM_FN(sub, agents)


def _infer_subscription_provider(sub_path: str, provider: str = "") -> str:
    if _INFER_SUBSCRIPTION_PROVIDER_FN is None:
        raise RuntimeError("handlers.subscriptions_routes.init() not called: infer_subscription_provider_fn missing")
    return _INFER_SUBSCRIPTION_PROVIDER_FN(sub_path, provider)


def _atomic_write_team_json() -> None:
    if _ATOMIC_WRITE_TEAM_JSON_FN is None:
        raise RuntimeError("handlers.subscriptions_routes.init() not called: atomic_write_team_json_fn missing")
    _ATOMIC_WRITE_TEAM_JSON_FN()


def handle_get(handler: Any, path: str) -> bool:
    if path != "/subscriptions":
        return False
    if _TEAM_CONFIG is None:
        handler._respond(500, {"error": "team.json not loaded"})
        return True
    subs = list(_TEAM_CONFIG.get("subscriptions", []))
    agents = _TEAM_CONFIG.get("agents", [])
    result_subs = [_build_subscription_response_item(sub, agents) for sub in subs]
    handler._respond(200, {"subscriptions": result_subs})
    return True


def handle_post(handler: Any, path: str) -> bool:
    if path != "/subscriptions":
        return False
    if _TEAM_CONFIG is None:
        handler._respond(500, {"error": "team.json not loaded"})
        return True

    data = handler._parse_json_body() or {}
    name = str(data.get("name", "")).strip()
    sub_path = str(data.get("path", "")).strip()
    email = str(data.get("email", "")).strip()
    api_key_hint = str(data.get("api_key_hint", "")).strip()
    if not name:
        handler._respond(400, {"error": "name is required"})
        return True
    if not sub_path:
        handler._respond(400, {"error": "path is required"})
        return True
    if not os.path.isdir(sub_path):
        handler._respond(400, {"error": f"path does not exist: {sub_path}"})
        return True
    settings_path = os.path.join(sub_path, "settings.json")
    if not os.path.isfile(settings_path):
        handler._respond(400, {"error": f"settings.json not found in {sub_path}"})
        return True
    if api_key_hint and len(api_key_hint) > 8:
        handler._respond(400, {"error": "api_key_hint must be max 8 chars (last digits only)"})
        return True

    inferred_provider = _infer_subscription_provider(sub_path)
    with _TEAM_CONFIG_LOCK:
        subs = _TEAM_CONFIG.setdefault("subscriptions", [])
        for existing in subs:
            if existing.get("path", "").rstrip("/") == sub_path.rstrip("/"):
                handler._respond(409, {"error": f"subscription with path '{sub_path}' already exists"})
                return True
        sub_id = f"sub{len(subs) + 1}"
        existing_ids = {s.get("id") for s in subs}
        counter = len(subs) + 1
        while sub_id in existing_ids:
            counter += 1
            sub_id = f"sub{counter}"
        new_sub = {
            "id": sub_id,
            "name": name,
            "path": sub_path,
            "active": True,
        }
        if inferred_provider:
            new_sub["provider"] = inferred_provider
        if email and inferred_provider != "claude":
            new_sub["email"] = email
        if api_key_hint:
            new_sub["api_key_hint"] = api_key_hint
        subs.append(new_sub)
        try:
            _atomic_write_team_json()
        except OSError as exc:
            subs.pop()
            handler._respond(500, {"error": f"failed to persist: {exc}"})
            return True
    handler._respond(201, {"ok": True, "subscription": new_sub})
    return True


def handle_put(handler: Any, path: str) -> bool:
    match = re.match(r"^/subscriptions/([a-z0-9_-]+)$", path)
    if not match:
        return False
    if _TEAM_CONFIG is None:
        handler._respond(500, {"error": "team.json not loaded"})
        return True

    sub_id = match.group(1)
    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid json body"})
        return True

    with _TEAM_CONFIG_LOCK:
        subs = _TEAM_CONFIG.get("subscriptions", [])
        target = None
        for sub in subs:
            if sub.get("id") == sub_id:
                target = sub
                break
        if not target:
            handler._respond(404, {"error": f"subscription '{sub_id}' not found"})
            return True
        provider = _infer_subscription_provider(target.get("path", ""), target.get("provider", ""))
        if provider and not target.get("provider"):
            target["provider"] = provider
        old_snapshot = {k: v for k, v in target.items()}
        if "name" in data:
            new_name = str(data["name"]).strip()
            if not new_name:
                handler._respond(400, {"error": "name cannot be empty"})
                return True
            target["name"] = new_name
        if "email" in data:
            if provider == "claude":
                target.pop("email", None)
            else:
                target["email"] = str(data["email"]).strip()
        if "active" in data:
            target["active"] = bool(data["active"])
        try:
            _atomic_write_team_json()
        except OSError as exc:
            target.clear()
            target.update(old_snapshot)
            handler._respond(500, {"error": f"failed to persist: {exc}"})
            return True
    handler._respond(200, {"ok": True, "subscription": target})
    return True


def handle_delete(handler: Any, path: str) -> bool:
    match = re.match(r"^/subscriptions/([a-z0-9_-]+)$", path)
    if not match:
        return False
    if _TEAM_CONFIG is None:
        handler._respond(500, {"error": "team.json not loaded"})
        return True

    sub_id = match.group(1)
    with _TEAM_CONFIG_LOCK:
        subs = _TEAM_CONFIG.get("subscriptions", [])
        target_idx = None
        target_sub = None
        for index, sub in enumerate(subs):
            if sub.get("id") == sub_id:
                target_idx = index
                target_sub = sub
                break
        if target_sub is None:
            handler._respond(404, {"error": f"subscription '{sub_id}' not found"})
            return True
        sub_path = target_sub.get("path", "")
        sub_path_norm = sub_path.rstrip("/")
        default_path_norm = os.path.expanduser("~/.claude").rstrip("/")
        agents = _TEAM_CONFIG.get("agents", [])
        assigned = [
            agent.get("id")
            for agent in agents
            if (agent.get("config_dir") or "").rstrip("/") == sub_path_norm
            or (not agent.get("config_dir") and sub_path_norm == default_path_norm)
        ]
        if assigned:
            names = ", ".join(assigned[:5])
            handler._respond(409, {"error": f"cannot delete: {len(assigned)} agents assigned ({names})"})
            return True
        subs.pop(target_idx)
        try:
            _atomic_write_team_json()
        except OSError as exc:
            subs.insert(target_idx, target_sub)
            handler._respond(500, {"error": f"failed to persist: {exc}"})
            return True
    handler._respond(200, {"ok": True, "deleted": target_sub})
    return True
