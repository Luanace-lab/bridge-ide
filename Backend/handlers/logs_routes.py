"""Log read route extraction from server.py."""

from __future__ import annotations

from typing import Any, Callable


_parse_non_negative_int_fn: Callable[[Any, int], int] | None = None
_tail_log_fn: Callable[[str, int], dict[str, Any]] | None = None


def init(
    *,
    parse_non_negative_int_fn: Callable[[Any, int], int],
    tail_log_fn: Callable[[str, int], dict[str, Any]],
) -> None:
    global _parse_non_negative_int_fn, _tail_log_fn
    _parse_non_negative_int_fn = parse_non_negative_int_fn
    _tail_log_fn = tail_log_fn


def _parse_non_negative_int(value: Any, default: int) -> int:
    if _parse_non_negative_int_fn is None:
        raise RuntimeError("handlers.logs_routes.init() not called: parse_non_negative_int_fn missing")
    return _parse_non_negative_int_fn(value, default)


def _tail_log(name: str, lines: int) -> dict[str, Any]:
    if _tail_log_fn is None:
        raise RuntimeError("handlers.logs_routes.init() not called: tail_log_fn missing")
    return _tail_log_fn(name, lines)


def handle_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path != "/logs":
        return False

    name = str((query.get("name") or ["server"])[0]).strip() or "server"
    lines = _parse_non_negative_int((query.get("lines") or [120])[0], 120)
    lines = min(max(lines, 1), 2000)
    try:
        payload = _tail_log(name, lines)
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
        return True
    handler._respond(200, payload)
    return True
