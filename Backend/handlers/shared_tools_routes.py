"""Shared tools route extraction from server.py."""

from __future__ import annotations

import os
import re
from typing import Any, Callable


_is_management_agent: Callable[[str], bool] | None = None
_platform_operators_getter: Callable[[], set[str]] | None = None
_TOOL_NAME_RE = re.compile(r"^/tools/([a-zA-Z0-9_-]+)$")
_TOOL_EXEC_RE = re.compile(r"^/tools/([a-zA-Z0-9_-]+)/execute$")


def init(
    *,
    is_management_agent_fn: Callable[[str], bool],
    platform_operators_getter: Callable[[], set[str]],
) -> None:
    global _is_management_agent, _platform_operators_getter
    _is_management_agent = is_management_agent_fn
    _platform_operators_getter = platform_operators_getter


def _is_management(agent_id: str) -> bool:
    if _is_management_agent is None:
        raise RuntimeError("handlers.shared_tools_routes.init() not called: is_management_agent_fn missing")
    return _is_management_agent(agent_id)


def _is_platform_operator(agent_id: str) -> bool:
    if agent_id == "user":
        return True
    if _platform_operators_getter is None:
        raise RuntimeError("handlers.shared_tools_routes.init() not called: platform_operators_getter missing")
    return agent_id in _platform_operators_getter()


def handle_get(handler: Any, path: str) -> bool:
    import tool_store

    if path == "/tools":
        tools = tool_store.list_tools()
        handler._respond(200, {"tools": tools, "count": len(tools)})
        return True

    match = _TOOL_NAME_RE.match(path)
    if not match:
        return False

    tool_name = match.group(1)
    tool_info = tool_store.get_tool(tool_name)
    if tool_info is None:
        handler._respond(404, {"error": f"Tool '{tool_name}' not found"})
    else:
        handler._respond(200, tool_info)
    return True


def handle_post(handler: Any, path: str) -> bool:
    import tool_store

    if path == "/tools/register":
        caller = str(handler.headers.get("X-Bridge-Agent", "")).strip()
        if not _is_platform_operator(caller):
            handler._respond(403, {"error": "insufficient permissions to register tools"})
            return True
        data = handler._parse_json_body()
        if data is None:
            handler._respond(400, {"error": "invalid or missing JSON body"})
            return True
        tool_name = str(data.get("name", "")).strip()
        tool_code = str(data.get("code", "")).strip()
        author = str(data.get("author", "")).strip() or str(handler.headers.get("X-Bridge-Agent", "unknown")).strip()
        if not tool_name or not tool_code:
            handler._respond(400, {"error": "'name' and 'code' are required"})
            return True
        if not re.match(r"^[a-z][a-z0-9_]{0,49}$", tool_name):
            handler._respond(400, {"error": "name must match [a-z][a-z0-9_]{0,49}"})
            return True
        if len(tool_code) > 100_000:
            handler._respond(400, {"error": "code exceeds 100KB limit"})
            return True
        for required in ("TOOL_META", "TOOL_SCHEMA", "def execute("):
            if required not in tool_code:
                handler._respond(400, {"error": f"code must contain '{required}'"})
                return True
        fname = f"{tool_name}.py"
        fpath = os.path.join(tool_store.SHARED_TOOLS_DIR, fname)
        if os.path.exists(fpath):
            handler._respond(409, {"error": f"Tool '{tool_name}' already exists. Use DELETE first to replace."})
            return True
        try:
            os.makedirs(tool_store.SHARED_TOOLS_DIR, exist_ok=True)
            with open(fpath, "w", encoding="utf-8") as handle:
                handle.write(tool_code)
        except OSError as exc:
            handler._respond(500, {"error": f"failed to write tool file: {exc}"})
            return True
        tool_store.scan_tools(force=True)
        tool_info = tool_store.get_tool(tool_name)
        if tool_info is None:
            try:
                os.remove(fpath)
            except OSError:
                pass
            tool_store.scan_tools(force=True)
            handler._respond(422, {"error": f"Tool '{tool_name}' failed validation after write. Check TOOL_META/TOOL_SCHEMA/execute()."})
            return True
        handler._respond(201, {"ok": True, "tool": tool_info, "author": author})
        return True

    match = _TOOL_EXEC_RE.match(path)
    if not match:
        return False

    caller = str(handler.headers.get("X-Bridge-Agent", "")).strip()
    if not _is_platform_operator(caller):
        handler._respond(403, {"error": "insufficient permissions to execute tools"})
        return True
    exec_tool_name = match.group(1)
    data = handler._parse_json_body()
    if data is None:
        data = {}
    kwargs = data.get("input", data.get("kwargs", {}))
    if not isinstance(kwargs, dict):
        kwargs = {}
    try:
        timeout = float(data.get("timeout", tool_store.EXECUTE_TIMEOUT))
    except (ValueError, TypeError):
        handler._respond(400, {"error": "timeout must be a number"})
        return True
    result = tool_store.execute_tool(exec_tool_name, kwargs, timeout=timeout)
    if result.get("ok"):
        handler._respond(200, result)
    else:
        status = 404 if "not found" in result.get("error", "") else 500
        handler._respond(status, result)
    return True


def handle_delete(handler: Any, path: str) -> bool:
    import tool_store

    match = _TOOL_NAME_RE.match(path)
    if not match:
        return False

    tool_name = match.group(1)
    tool_info = tool_store.get_tool(tool_name)
    if tool_info is None:
        handler._respond(404, {"error": f"Tool '{tool_name}' not found"})
        return True
    requesting_agent = str(handler.headers.get("X-Bridge-Agent", "")).strip()
    tool_author = tool_info.get("author_agent", "")
    if requesting_agent and requesting_agent != tool_author and not _is_management(requesting_agent):
        handler._respond(403, {"error": f"Only author '{tool_author}' or management can delete this tool"})
        return True
    fpath = os.path.join(tool_store.SHARED_TOOLS_DIR, tool_info.get("file", ""))
    try:
        if os.path.exists(fpath):
            os.remove(fpath)
    except OSError as exc:
        handler._respond(500, {"error": f"failed to delete tool file: {exc}"})
        return True
    tool_store.scan_tools(force=True)
    handler._respond(200, {"ok": True, "deleted": tool_name})
    return True
