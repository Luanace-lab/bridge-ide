"""Read-only MCP catalog route extraction from server.py."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable


_RUNTIME_MCP_REGISTRY_FN: Callable[[], list[dict[str, Any]]] | None = None
_INDUSTRY_TEMPLATES_PATH: str = ""
_REGISTER_RUNTIME_SERVER_FN: Callable[[str, dict[str, Any]], list[dict[str, Any]]] | None = None
_RBAC_PLATFORM_OPERATORS_GETTER: Callable[[], set[str]] | None = None
_ws_broadcast: Callable[..., Any] | None = None


def init(
    *,
    runtime_mcp_registry_fn: Callable[[], list[dict[str, Any]]],
    industry_templates_path: str,
    register_runtime_server_fn: Callable[[str, dict[str, Any]], list[dict[str, Any]]] | None = None,
    rbac_platform_operators_getter: Callable[[], set[str]] | None = None,
    ws_broadcast_fn: Callable[..., Any] | None = None,
) -> None:
    global _RUNTIME_MCP_REGISTRY_FN, _INDUSTRY_TEMPLATES_PATH
    global _REGISTER_RUNTIME_SERVER_FN, _RBAC_PLATFORM_OPERATORS_GETTER, _ws_broadcast
    _RUNTIME_MCP_REGISTRY_FN = runtime_mcp_registry_fn
    _INDUSTRY_TEMPLATES_PATH = industry_templates_path
    _REGISTER_RUNTIME_SERVER_FN = register_runtime_server_fn
    _RBAC_PLATFORM_OPERATORS_GETTER = rbac_platform_operators_getter
    _ws_broadcast = ws_broadcast_fn


def _runtime_mcp_registry() -> list[dict[str, Any]]:
    if _RUNTIME_MCP_REGISTRY_FN is None:
        raise RuntimeError("handlers.mcp_catalog_routes.init() not called: runtime_mcp_registry_fn missing")
    return _RUNTIME_MCP_REGISTRY_FN()


def _register_runtime_server(name: str, spec: dict[str, Any]) -> list[dict[str, Any]]:
    if _REGISTER_RUNTIME_SERVER_FN is None:
        raise RuntimeError("handlers.mcp_catalog_routes.init() not called: register_runtime_server_fn missing")
    return _REGISTER_RUNTIME_SERVER_FN(name, spec)


def _rbac_platform_operators() -> set[str]:
    if _RBAC_PLATFORM_OPERATORS_GETTER is None:
        raise RuntimeError("handlers.mcp_catalog_routes.init() not called: rbac_platform_operators_getter missing")
    return _RBAC_PLATFORM_OPERATORS_GETTER()


def _ws_broadcast_cb(*args: Any, **kwargs: Any) -> Any:
    if _ws_broadcast is None:
        raise RuntimeError("handlers.mcp_catalog_routes.init() not called: ws_broadcast_fn missing")
    return _ws_broadcast(*args, **kwargs)


def handle_get(handler: Any, path: str, query: dict[str, list[str]]) -> bool:
    if path == "/mcp-catalog":
        try:
            registry = _runtime_mcp_registry()
            handler._respond(200, {"ok": True, "servers": registry, "count": len(registry)})
        except Exception as exc:
            handler._respond(500, {"error": f"failed to read MCP catalog: {exc}"})
        return True

    if path == "/industry-templates":
        try:
            with open(_INDUSTRY_TEMPLATES_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            handler._respond(500, {"error": f"failed to load industry templates: {exc}"})
            return True
        q = str((query.get("q") or query.get("query") or [None])[0] or "").strip().lower()
        templates = data.get("templates", {})
        if q:
            matched = {}
            for key, template in templates.items():
                searchable = f"{key} {template.get('name', '')} {template.get('description', '')}".lower()
                if all(word in searchable for word in q.split()):
                    matched[key] = template
            templates = matched
        handler._respond(200, {"ok": True, "version": data.get("version", 1), "templates": templates, "count": len(templates)})
        return True

    return False


def handle_post(handler: Any, path: str) -> bool:
    if path != "/mcp-catalog":
        return False

    caller = str(handler.headers.get("X-Bridge-Agent", "")).strip()
    if caller not in _rbac_platform_operators() and caller != "user":
        handler._respond(403, {"error": "insufficient permissions to register MCP servers"})
        return True

    data = handler._parse_json_body()
    if data is None:
        handler._respond(400, {"error": "invalid json body"})
        return True

    mcp_name = str(data.get("name", "")).strip()
    spec = data.get("spec")
    if not mcp_name or not isinstance(spec, dict):
        handler._respond(400, {"error": "name (string) and spec (object) are required"})
        return True
    if not re.match(r"^[a-z][a-z0-9_-]{0,49}$", mcp_name):
        handler._respond(400, {"error": "name must match [a-z][a-z0-9_-]{0,49}"})
        return True

    try:
        updated = _register_runtime_server(mcp_name, spec)
    except ValueError as exc:
        handler._respond(400, {"error": str(exc)})
        return True
    except OSError as exc:
        handler._respond(500, {"error": f"failed to persist MCP catalog: {exc}"})
        return True

    print(f"[mcp-catalog] Registered runtime MCP server '{mcp_name}' (transport={spec.get('transport', 'stdio')})")
    _ws_broadcast_cb("mcp_registered", {"name": mcp_name, "spec": spec})
    handler._respond(201, {"ok": True, "name": mcp_name, "servers": updated})
    return True
