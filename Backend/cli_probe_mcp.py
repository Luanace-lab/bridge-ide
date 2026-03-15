from __future__ import annotations

import os
import platform
import socket
from pathlib import Path

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("probe")


def _marker() -> str:
    return os.environ.get("BRIDGE_PROBE_MARKER", "bridge-probe-marker")


def _snapshot() -> dict[str, str]:
    return {
        "cwd": str(Path.cwd()),
        "hostname": socket.gethostname(),
        "marker": _marker(),
        "pid": str(os.getpid()),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


@mcp.tool()
def probe_ping(message: str = "ping") -> dict[str, str]:
    """Return a deterministic payload so CLI MCP loading can be verified."""
    payload = _snapshot()
    payload["message"] = message
    payload["ok"] = "true"
    payload["server"] = "probe"
    return payload


@mcp.tool()
def probe_echo(payload: str) -> str:
    """Echo a unique marker so agent tool execution is easy to detect in logs."""
    return f"probe::{_marker()}::{payload}"


if __name__ == "__main__":
    mcp.run()
