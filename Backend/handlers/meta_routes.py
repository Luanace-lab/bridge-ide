"""Small GET route extraction for engine registry and CLI detection."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import parse_qs

from server_utils import parse_bool


_engine_model_registry_fn: Callable[[], dict[str, dict[str, Any]]] | None = None
_get_cli_setup_state_cached_fn: Callable[..., dict[str, Any]] | None = None


def init(
    *,
    engine_model_registry_fn: Callable[[], dict[str, dict[str, Any]]],
    get_cli_setup_state_cached_fn: Callable[..., dict[str, Any]],
) -> None:
    global _engine_model_registry_fn, _get_cli_setup_state_cached_fn
    _engine_model_registry_fn = engine_model_registry_fn
    _get_cli_setup_state_cached_fn = get_cli_setup_state_cached_fn


def _engine_registry() -> dict[str, dict[str, Any]]:
    if _engine_model_registry_fn is None:
        raise RuntimeError("handlers.meta_routes.init() not called: engine_model_registry_fn missing")
    return _engine_model_registry_fn()


def _cli_setup_state(*, force: bool, include_runtime_probes: bool) -> dict[str, Any]:
    if _get_cli_setup_state_cached_fn is None:
        raise RuntimeError("handlers.meta_routes.init() not called: get_cli_setup_state_cached_fn missing")
    return _get_cli_setup_state_cached_fn(
        force=force,
        include_runtime_probes=include_runtime_probes,
    )


def handle_get(handler: Any, path: str, query_string: str) -> bool:
    if path == "/engines/models":
        handler._respond(200, {"engines": _engine_registry()})
        return True

    if path != "/cli/detect":
        return False

    qs = parse_qs(query_string, keep_blank_values=False)
    include_runtime = True
    if "skip_runtime" in qs:
        include_runtime = not parse_bool(qs.get("skip_runtime", [""])[0], False)
    elif "include_runtime" in qs:
        include_runtime = parse_bool(qs.get("include_runtime", [""])[0], True)
    force_refresh = parse_bool(qs.get("force", [""])[0], False)
    handler._respond(
        200,
        _cli_setup_state(
            force=force_refresh,
            include_runtime_probes=include_runtime,
        ),
    )
    return True
