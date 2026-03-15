"""
Shared Tool Store — Dynamic tool discovery and execution.

Scans /BRIDGE/shared_tools/ for Python files that follow the standard interface:
  - TOOL_META: dict with name, description, author_agent, version, created_at
  - TOOL_SCHEMA: dict with JSON Schema for input/output
  - def execute(**kwargs) -> dict: Main function

Tools are loaded in-process via importlib. No separate server needed.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger("tool_store")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SHARED_TOOLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "shared_tools",
)

EXECUTE_TIMEOUT = 30.0  # default timeout per tool execution (seconds)
MAX_EXECUTE_TIMEOUT = 300.0

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_TOOLS: dict[str, dict[str, Any]] = {}  # name → {meta, schema, module, file, loaded_at}
_TOOLS_LOCK = threading.Lock()
_LAST_SCAN: float = 0.0
_SCAN_COOLDOWN = 5.0  # min seconds between scans


def _load_tool_from_file(fpath: str) -> dict[str, Any] | None:
    """Load a single tool from a Python file. Returns tool entry or None."""
    fname = os.path.basename(fpath)
    module_name = f"shared_tool_{fname[:-3]}"

    try:
        spec = importlib.util.spec_from_file_location(module_name, fpath)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        log.warning("Failed to load tool %s: %s", fpath, exc)
        return None

    # Validate required attributes
    meta = getattr(module, "TOOL_META", None)
    if not isinstance(meta, dict) or not meta.get("name"):
        log.warning("Tool %s: missing or invalid TOOL_META", fname)
        return None

    schema = getattr(module, "TOOL_SCHEMA", {})
    if not isinstance(schema, dict):
        schema = {}

    execute_fn = getattr(module, "execute", None)
    if not callable(execute_fn):
        log.warning("Tool %s: missing execute() function", fname)
        return None

    return {
        "meta": {
            "name": meta.get("name", ""),
            "description": meta.get("description", ""),
            "author_agent": meta.get("author_agent", "unknown"),
            "version": meta.get("version", "1.0.0"),
            "created_at": meta.get("created_at", ""),
        },
        "schema": schema,
        "module": module,
        "file": fpath,
        "loaded_at": time.time(),
    }


def scan_tools(force: bool = False) -> int:
    """Scan shared_tools/ directory and load/reload tools.

    Returns count of loaded tools.
    Respects cooldown unless force=True.
    """
    global _LAST_SCAN

    if not force and (time.time() - _LAST_SCAN) < _SCAN_COOLDOWN:
        return len(_TOOLS)

    if not os.path.isdir(SHARED_TOOLS_DIR):
        return 0

    found: dict[str, dict[str, Any]] = {}
    for fname in sorted(os.listdir(SHARED_TOOLS_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        fpath = os.path.join(SHARED_TOOLS_DIR, fname)
        if not os.path.isfile(fpath):
            continue

        # Check if already loaded and not modified
        with _TOOLS_LOCK:
            existing = _TOOLS.get(fname[:-3])
        if existing and not force:
            try:
                mtime = os.path.getmtime(fpath)
                if mtime <= existing.get("loaded_at", 0):
                    found[existing["meta"]["name"]] = existing
                    continue
            except OSError:
                pass

        tool = _load_tool_from_file(fpath)
        if tool:
            found[tool["meta"]["name"]] = tool
            log.info("Loaded tool: %s (v%s) from %s",
                     tool["meta"]["name"], tool["meta"]["version"], fname)

    with _TOOLS_LOCK:
        _TOOLS.clear()
        _TOOLS.update(found)

    _LAST_SCAN = time.time()
    log.info("Tool scan complete: %d tools loaded", len(found))
    return len(found)


def list_tools() -> list[dict[str, Any]]:
    """List all loaded tools with meta and schema."""
    scan_tools()  # auto-scan if cooldown elapsed
    with _TOOLS_LOCK:
        return [
            {
                "name": t["meta"]["name"],
                "description": t["meta"]["description"],
                "author_agent": t["meta"]["author_agent"],
                "version": t["meta"]["version"],
                "created_at": t["meta"]["created_at"],
                "schema": t["schema"],
                "file": os.path.basename(t["file"]),
            }
            for t in _TOOLS.values()
        ]


def get_tool(name: str) -> dict[str, Any] | None:
    """Get tool details by name."""
    scan_tools()
    with _TOOLS_LOCK:
        tool = _TOOLS.get(name)
    if tool is None:
        return None
    return {
        "name": tool["meta"]["name"],
        "description": tool["meta"]["description"],
        "author_agent": tool["meta"]["author_agent"],
        "version": tool["meta"]["version"],
        "created_at": tool["meta"]["created_at"],
        "schema": tool["schema"],
        "file": os.path.basename(tool["file"]),
    }


def execute_tool(
    name: str,
    kwargs: dict[str, Any],
    timeout: float = EXECUTE_TIMEOUT,
) -> dict[str, Any]:
    """Execute a tool by name with given kwargs.

    Runs in a separate thread with timeout.
    Returns {"ok": True, "result": ...} or {"ok": False, "error": ...}.
    """
    scan_tools()
    with _TOOLS_LOCK:
        tool = _TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": f"Tool '{name}' not found"}

    timeout = min(max(timeout, 1.0), MAX_EXECUTE_TIMEOUT)
    result_holder: list[Any] = [None]
    error_holder: list[str] = [""]

    def _run() -> None:
        try:
            result_holder[0] = tool["module"].execute(**kwargs)
        except Exception as exc:
            error_holder[0] = f"{type(exc).__name__}: {exc}"

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        return {"ok": False, "error": f"Tool '{name}' timed out after {timeout}s"}

    if error_holder[0]:
        return {"ok": False, "error": error_holder[0]}

    return {"ok": True, "result": result_holder[0]}
