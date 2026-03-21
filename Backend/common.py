#!/usr/bin/env python3
"""Shared helpers for bridge clients."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

# --- Phone Number Masking (Privacy) ---
_PHONE_PATTERN = re.compile(r"(\+?\d{2,4})\d{4,}(\d{4})")
_JID_PATTERN = re.compile(r"(\d{2,4})\d{4,}(\d{4})@")
TOKEN_CONFIG_FILE = Path(
    os.environ.get("BRIDGE_TOKEN_CONFIG_FILE", "~/.config/bridge/tokens.json")
).expanduser()
BRIDGE_AGENT_SESSION_DIR = ".bridge"
BRIDGE_AGENT_SESSION_FILE = "agent_session.json"


def is_pid_alive(pid: int) -> bool:
    """Check if process with given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def mask_phone(number: str) -> str:
    """Mask phone number for privacy: +49171***1234 style."""
    if not number:
        return number
    if "@" in number:
        return _JID_PATTERN.sub(r"\1***\2@", number)
    return _PHONE_PATTERN.sub(r"\1***\2", number)


def load_bridge_user_token(token_file: str | Path | None = None) -> str:
    token = os.environ.get("BRIDGE_USER_TOKEN", "").strip()
    if token:
        return token
    if token_file:
        path = Path(token_file).expanduser()
    else:
        path = Path(
            os.environ.get("BRIDGE_TOKEN_CONFIG_FILE", str(TOKEN_CONFIG_FILE))
        ).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("user_token", "")).strip()


def build_bridge_auth_headers(
    *,
    agent_id: str = "",
    content_type: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = content_type
    token = load_bridge_user_token()
    if token:
        headers["X-Bridge-Token"] = token
    if agent_id:
        headers["X-Bridge-Agent"] = agent_id
    if extra_headers:
        headers.update(extra_headers)
    return headers


def build_bridge_ws_auth_message() -> dict[str, str] | None:
    token = load_bridge_user_token()
    if not token:
        return None
    return {"type": "auth", "token": token}


def bridge_agent_session_file(workspace: str | Path) -> Path:
    return (
        Path(workspace).expanduser()
        / BRIDGE_AGENT_SESSION_DIR
        / BRIDGE_AGENT_SESSION_FILE
    )


def load_bridge_agent_session_token(
    workspace: str | Path | None,
    *,
    agent_id: str = "",
) -> str:
    if not workspace:
        return ""
    path = bridge_agent_session_file(workspace)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    stored_agent = str(payload.get("agent_id", "")).strip()
    if agent_id and stored_agent and stored_agent != agent_id:
        return ""
    return str(payload.get("session_token", "")).strip()


def store_bridge_agent_session_token(
    workspace: str | Path,
    *,
    agent_id: str,
    session_token: str,
    source: str = "bridge_mcp",
) -> Path:
    path = bridge_agent_session_file(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "agent_id": str(agent_id).strip(),
        "session_token": str(session_token).strip(),
        "source": str(source).strip() or "bridge_mcp",
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)
    return path


def http_get_json(
    url: str,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request = Request(url, method="GET", headers=headers or {})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def http_post_json(
    url: str,
    payload: dict[str, Any],
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    merged_headers = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        merged_headers.update(headers)
    request = Request(
        url,
        method="POST",
        data=raw,
        headers=merged_headers,
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = response.read().decode("utf-8")
    return json.loads(body)


def send_message(
    server: str,
    sender: str,
    recipient: str,
    content: str,
    meta: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    body: dict[str, Any] = {"from": sender, "to": recipient, "content": content}
    if meta:
        body["meta"] = meta
    return http_post_json(
        f"{server.rstrip('/')}/send",
        body,
        timeout=timeout,
        headers=build_bridge_auth_headers(
            agent_id=sender,
            content_type="application/json; charset=utf-8",
        ),
    )


def receive_messages(
    server: str,
    agent_id: str,
    wait_seconds: float = 20.0,
    limit: int = 100,
    timeout_padding: float = 10.0,
) -> list[dict[str, Any]]:
    endpoint = (
        f"{server.rstrip('/')}/receive/{quote(agent_id)}"
        f"?wait={wait_seconds}&limit={limit}"
    )
    request = Request(
        endpoint,
        method="GET",
        headers={
            "X-Bridge-Client": "agent_client",
            "X-Bridge-Agent": agent_id,
        },
    )
    with urlopen(request, timeout=max(wait_seconds + timeout_padding, 5.0)) as response:  # noqa: S310
        raw = response.read().decode("utf-8")
    payload = json.loads(raw)
    messages = payload.get("messages", [])
    if isinstance(messages, list):
        return messages
    return []
