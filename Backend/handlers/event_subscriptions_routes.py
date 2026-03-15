"""Event subscription route extraction from server.py."""

from __future__ import annotations

import re
from typing import Any, Callable


_LIST_SUBSCRIPTIONS_FN: Callable[..., list[dict[str, Any]]] | None = None
_SUBSCRIBE_FN: Callable[..., dict[str, Any]] | None = None
_UNSUBSCRIBE_FN: Callable[[str], bool] | None = None


def init(
    *,
    list_subscriptions_fn: Callable[..., list[dict[str, Any]]],
    subscribe_fn: Callable[..., dict[str, Any]],
    unsubscribe_fn: Callable[[str], bool],
) -> None:
    global _LIST_SUBSCRIPTIONS_FN, _SUBSCRIBE_FN, _UNSUBSCRIBE_FN
    _LIST_SUBSCRIPTIONS_FN = list_subscriptions_fn
    _SUBSCRIBE_FN = subscribe_fn
    _UNSUBSCRIBE_FN = unsubscribe_fn


def _list_subscriptions(*, created_by: str | None = None) -> list[dict[str, Any]]:
    if _LIST_SUBSCRIPTIONS_FN is None:
        raise RuntimeError("handlers.event_subscriptions_routes.init() not called: list_subscriptions_fn missing")
    return _LIST_SUBSCRIPTIONS_FN(created_by=created_by)


def _subscribe(*, event_type: str, webhook_url: str, created_by: str, filter_rules: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if _SUBSCRIBE_FN is None:
        raise RuntimeError("handlers.event_subscriptions_routes.init() not called: subscribe_fn missing")
    return _SUBSCRIBE_FN(
        event_type=event_type,
        webhook_url=webhook_url,
        created_by=created_by,
        filter_rules=filter_rules,
        label=label,
    )


def _unsubscribe(subscription_id: str) -> bool:
    if _UNSUBSCRIBE_FN is None:
        raise RuntimeError("handlers.event_subscriptions_routes.init() not called: unsubscribe_fn missing")
    return _UNSUBSCRIBE_FN(subscription_id)


def handle_get(handler: Any, path: str) -> bool:
    if path != "/events/subscriptions":
        return False
    created_by_filter = str(handler.headers.get("X-Bridge-Agent", "")).strip() or None
    subs = _list_subscriptions(created_by=created_by_filter)
    handler._respond(200, {"subscriptions": subs, "count": len(subs)})
    return True


def handle_post(handler: Any, path: str) -> bool:
    if path != "/events/subscribe":
        return False
    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid or missing JSON body"})
        return True
    evt_type = str(data.get("event_type", "")).strip()
    webhook_url = str(data.get("webhook_url", "")).strip()
    if not evt_type or not webhook_url:
        handler._respond(400, {"error": "event_type and webhook_url are required"})
        return True
    label = str(data.get("label", "")).strip()
    filter_rules = data.get("filter")
    if filter_rules is not None and not isinstance(filter_rules, dict):
        handler._respond(400, {"error": "filter must be a dict"})
        return True
    created_by = str(data.get("created_by", "")).strip() or str(handler.headers.get("X-Bridge-Agent", "")).strip() or "system"
    sub = _subscribe(
        event_type=evt_type,
        webhook_url=webhook_url,
        created_by=created_by,
        filter_rules=filter_rules,
        label=label,
    )
    handler._respond(201, {"ok": True, "subscription": sub})
    return True


def handle_delete(handler: Any, path: str) -> bool:
    match = re.match(r"^/events/subscriptions/([a-zA-Z0-9_-]+)$", path)
    if not match:
        return False
    sub_id = match.group(1)
    if _unsubscribe(sub_id):
        handler._respond(200, {"ok": True, "deleted": sub_id})
    else:
        handler._respond(404, {"error": f"subscription '{sub_id}' not found"})
    return True
