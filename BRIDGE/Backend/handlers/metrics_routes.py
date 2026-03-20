"""Read-only metrics route extraction from server.py."""

from __future__ import annotations

from typing import Any, Callable


_GET_TOKEN_METRICS_FN: Callable[..., dict[str, Any]] | None = None
_GET_COST_SUMMARY_FN: Callable[..., dict[str, Any]] | None = None
_MODEL_PRICES_FN: Callable[[], dict[str, Any]] | None = None
_LOG_USAGE_FN: Callable[..., dict[str, Any]] | None = None


def init(
    *,
    get_token_metrics_fn: Callable[..., dict[str, Any]],
    get_cost_summary_fn: Callable[..., dict[str, Any]],
    model_prices_fn: Callable[[], dict[str, Any]],
    log_usage_fn: Callable[..., dict[str, Any]],
) -> None:
    global _GET_TOKEN_METRICS_FN, _GET_COST_SUMMARY_FN, _MODEL_PRICES_FN, _LOG_USAGE_FN
    _GET_TOKEN_METRICS_FN = get_token_metrics_fn
    _GET_COST_SUMMARY_FN = get_cost_summary_fn
    _MODEL_PRICES_FN = model_prices_fn
    _LOG_USAGE_FN = log_usage_fn


def _get_token_metrics(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if _GET_TOKEN_METRICS_FN is None:
        raise RuntimeError("handlers.metrics_routes.init() not called: get_token_metrics_fn missing")
    return _GET_TOKEN_METRICS_FN(*args, **kwargs)


def _get_cost_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if _GET_COST_SUMMARY_FN is None:
        raise RuntimeError("handlers.metrics_routes.init() not called: get_cost_summary_fn missing")
    return _GET_COST_SUMMARY_FN(*args, **kwargs)


def _model_prices() -> dict[str, Any]:
    if _MODEL_PRICES_FN is None:
        raise RuntimeError("handlers.metrics_routes.init() not called: model_prices_fn missing")
    return _MODEL_PRICES_FN()


def _log_usage(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if _LOG_USAGE_FN is None:
        raise RuntimeError("handlers.metrics_routes.init() not called: log_usage_fn missing")
    return _LOG_USAGE_FN(*args, **kwargs)


def handle_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path == "/metrics/tokens":
        agent_id = query.get("agent_id", [""])[0].strip()
        period = query.get("period", ["today"])[0].strip()
        if period not in ("today", "week", "month", "all"):
            period = "today"
        handler._respond(200, _get_token_metrics(agent_id=agent_id, period=period))
        return True

    if path == "/metrics/costs":
        period = query.get("period", ["today"])[0].strip()
        if period not in ("today", "week", "month", "all"):
            period = "today"
        handler._respond(200, _get_cost_summary(period=period))
        return True

    if path == "/metrics/prices":
        handler._respond(200, {"prices": _model_prices()})
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    if path != "/metrics/tokens":
        return False

    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid or missing JSON body"})
        return True

    try:
        t_input = int(data.get("input_tokens", 0))
        t_output = int(data.get("output_tokens", 0))
        t_cached = int(data.get("cached_tokens", 0))
    except (TypeError, ValueError):
        handler._respond(400, {"error": "token counts must be integers"})
        return True

    if t_input < 0 or t_output < 0 or t_cached < 0:
        handler._respond(400, {"error": "token counts must be non-negative"})
        return True

    t_agent = str(data.get("agent_id", "")).strip() or str(handler.headers.get("X-Bridge-Agent", "unknown")).strip()
    t_engine = str(data.get("engine", "")).strip()
    t_model = str(data.get("model", "")).strip()
    entry = _log_usage(
        agent_id=t_agent,
        engine=t_engine,
        model=t_model,
        input_tokens=t_input,
        output_tokens=t_output,
        cached_tokens=t_cached,
    )
    handler._respond(201, {"ok": True, "entry": entry})
    return True
