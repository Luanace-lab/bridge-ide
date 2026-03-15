"""Onboarding/frontdoor POST routes extracted from server.py."""

from __future__ import annotations

from typing import Any, Callable


_STRICT_AUTH_GETTER: Callable[[], bool] | None = None
_ENSURE_BUDDY_FRONTDOOR_FN: Callable[[str], dict[str, Any]] | None = None
_GET_BUDDY_FRONTDOOR_STATUS_FN: Callable[[str], dict[str, Any]] | None = None


def init(
    *,
    strict_auth_getter: Callable[[], bool],
    ensure_buddy_frontdoor_fn: Callable[[str], dict[str, Any]],
    get_buddy_frontdoor_status_fn: Callable[[str], dict[str, Any]],
) -> None:
    global _STRICT_AUTH_GETTER, _ENSURE_BUDDY_FRONTDOOR_FN, _GET_BUDDY_FRONTDOOR_STATUS_FN
    _STRICT_AUTH_GETTER = strict_auth_getter
    _ENSURE_BUDDY_FRONTDOOR_FN = ensure_buddy_frontdoor_fn
    _GET_BUDDY_FRONTDOOR_STATUS_FN = get_buddy_frontdoor_status_fn


def _strict_auth() -> bool:
    if _STRICT_AUTH_GETTER is None:
        raise RuntimeError("handlers.onboarding_routes.init() not called: strict_auth_getter missing")
    return _STRICT_AUTH_GETTER()


def _ensure_buddy_frontdoor(user_id: str) -> dict[str, Any]:
    if _ENSURE_BUDDY_FRONTDOOR_FN is None:
        raise RuntimeError("handlers.onboarding_routes.init() not called: ensure_buddy_frontdoor_fn missing")
    return _ENSURE_BUDDY_FRONTDOOR_FN(user_id)


def _get_buddy_frontdoor_status(user_id: str) -> dict[str, Any]:
    if _GET_BUDDY_FRONTDOOR_STATUS_FN is None:
        raise RuntimeError("handlers.onboarding_routes.init() not called: get_buddy_frontdoor_status_fn missing")
    return _GET_BUDDY_FRONTDOOR_STATUS_FN(user_id)


def handle_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path != "/onboarding/status":
        return False

    user_id = str((query.get("user_id") or ["user"])[0]).strip() or "user"
    handler._respond(200, {"ok": True, **_get_buddy_frontdoor_status(user_id)})
    return True


def handle_post(handler: Any, path: str) -> bool:
    if path != "/onboarding/start":
        return False

    data = handler._parse_json_body() or {}
    if _strict_auth():
        ok, role, _identity = handler._require_authenticated()
        if not ok:
            return True
        if role != "user":
            handler._respond(403, {"error": "only UI/user auth may trigger onboarding"})
            return True

    user_id = str(data.get("user_id", "")).strip() or "user"
    result = _ensure_buddy_frontdoor(user_id)
    if result["status"] == "unavailable":
        handler._respond(503, {"ok": False, **result})
        return True
    handler._respond(200, {"ok": True, **result})
    return True
