#!/usr/bin/env python3
"""Telegram Watcher — polls Telegram Bot API and routes inbound messages to Bridge agents.

Behavior:
- watches explicitly configured chats only
- @agent targets specific agents
- @all/@alle broadcasts to all agents
- no mention defaults to configured default_route

Safety:
- single-instance file lock
- persistent Bot API offset state
- append-only JSONL store for bridge_telegram_read
- fail-closed if bot token or watched chats are missing
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


_BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:9111").rstrip("/")
_BRIDGE_USER_TOKEN = os.environ.get("BRIDGE_USER_TOKEN", "").strip()
_TELEGRAM_API_BASE_URL = os.environ.get("TELEGRAM_API_BASE_URL", "https://api.telegram.org").rstrip("/")
_TELEGRAM_TOKEN_PATH = os.path.expanduser("~/.config/bridge/telegram_bot_token")
_DEFAULT_STORE_CANDIDATES = (
    "~/.local/share/bridge/telegram/updates.jsonl",
    "~/.config/bridge/telegram/updates.jsonl",
)
_POLL_TIMEOUT = max(int(os.environ.get("TELEGRAM_WATCHER_POLL_TIMEOUT", "20") or "20"), 1)
_POLL_INTERVAL = max(float(os.environ.get("TELEGRAM_WATCHER_POLL_INTERVAL", "1.0") or "1.0"), 0.1)
_STATE_FILE = os.path.expanduser(
    os.environ.get(
        "TELEGRAM_WATCHER_STATE_FILE",
        os.path.join(os.path.dirname(__file__), ".telegram_watcher_state.json"),
    )
)
_LOCK_FILE = os.path.expanduser(
    os.environ.get(
        "TELEGRAM_WATCHER_LOCK_FILE",
        os.path.join(os.path.dirname(__file__), ".telegram_watcher.lock"),
    )
)


def _resolve_telegram_config_path() -> str:
    env_val = os.environ.get("TELEGRAM_CONFIG_PATH", "").strip()
    if env_val:
        return os.path.expanduser(env_val)
    candidates = (
        "~/.config/bridge/telegram_config.json",
        os.path.join(os.path.dirname(__file__), "telegram_config.json"),
    )
    for candidate in candidates:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return os.path.expanduser("~/.config/bridge/telegram_config.json")


def _resolve_store_path() -> str:
    env_val = os.environ.get("TELEGRAM_UPDATES_STORE_PATH", "").strip()
    if env_val:
        return os.path.expanduser(env_val)
    for candidate in _DEFAULT_STORE_CANDIDATES:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return os.path.expanduser(_DEFAULT_STORE_CANDIDATES[0])


def _load_config() -> dict[str, Any]:
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _config_list(key: str, env_key: str) -> list[str]:
    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        return [value.strip() for value in env_val.split(",") if value.strip()]
    raw = _CONFIG.get(key, [])
    if isinstance(raw, list):
        return [str(value).strip() for value in raw if str(value).strip()]
    return []


def _config_string(key: str, env_key: str, default: str = "") -> str:
    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        return env_val
    raw = _CONFIG.get(key, default)
    if raw is None:
        return default
    return str(raw).strip()


_CONFIG_PATH = _resolve_telegram_config_path()
_CONFIG = _load_config()
_STORE_PATH = _resolve_store_path()


def _load_bot_token() -> str:
    env_val = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if env_val:
        return env_val
    if os.path.exists(_TELEGRAM_TOKEN_PATH):
        try:
            with open(_TELEGRAM_TOKEN_PATH, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


_BOT_TOKEN = _load_bot_token()
_READ_WHITELIST = _config_list("read_whitelist", "TELEGRAM_READ_WHITELIST")
_WATCH_CHATS = _config_list("watch_chats", "TELEGRAM_WATCH_CHATS") or list(_READ_WHITELIST)
_DEFAULT_ROUTE = _config_string("default_route", "TELEGRAM_DEFAULT_ROUTE", "buddy") or "buddy"
_BROADCAST_TAGS = {"all", "alle"}
_AGENT_CACHE_TTL = 30.0
_KNOWN_AGENTS = {"ordo", "viktor", "nova", "frontend", "backend", "security", "lucy", "stellexa", "codex", "kai"}
_agent_cache = {"agents": set(_KNOWN_AGENTS), "ts": 0.0}
_lock_handle = None


def _load_state() -> dict[str, Any]:
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                return {"offset": int(payload.get("offset", 0) or 0)}
        except Exception:
            pass
    return {"offset": 0}


def _save_state(state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
    tmp_path = f"{_STATE_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"offset": int(state.get("offset", 0) or 0)}, f, indent=2)
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, _STATE_FILE)
    try:
        os.chmod(_STATE_FILE, 0o600)
    except OSError:
        pass


def _acquire_lock() -> None:
    global _lock_handle
    os.makedirs(os.path.dirname(_LOCK_FILE), exist_ok=True)
    _lock_handle = open(_LOCK_FILE, "w", encoding="utf-8")
    try:
        os.chmod(_LOCK_FILE, 0o600)
    except OSError:
        pass
    try:
        fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[telegram_watcher] Bereits aktiv — zweite Instanz beendet.", file=sys.stderr)
        raise SystemExit(1)
    _lock_handle.seek(0)
    _lock_handle.truncate()
    _lock_handle.write(str(os.getpid()))
    _lock_handle.flush()


def _known_agents_runtime() -> set[str]:
    now = time.time()
    cached_ts = float(_agent_cache.get("ts", 0.0))
    if (now - cached_ts) < _AGENT_CACHE_TTL:
        return set(_agent_cache.get("agents", set(_KNOWN_AGENTS)))

    merged = set(_KNOWN_AGENTS)
    try:
        resp = httpx.get(f"{_BRIDGE_URL}/agents", timeout=3.0)
        data = resp.json() if resp.status_code == 200 else {}
        for entry in data.get("agents", []):
            aid = str(entry.get("agent_id", "")).strip().lower()
            if aid and aid not in {"user", "system", "all"}:
                merged.add(aid)
    except Exception:
        pass

    _agent_cache["agents"] = merged
    _agent_cache["ts"] = now
    return merged


def _extract_mentions(text: str) -> list[str]:
    return re.findall(r"@([a-zA-Z0-9_]+)", text.lower())


def _strip_mentions(text: str) -> str:
    cleaned = re.sub(r"@([a-zA-Z0-9_]+)", "", text)
    return " ".join(cleaned.split()).strip()


def _route_message(text: str) -> list[tuple[str, str]]:
    mentions = _extract_mentions(text)
    payload = _strip_mentions(text) or text.strip()

    if any(mention in _BROADCAST_TAGS for mention in mentions):
        return [("all", payload)]

    targets: list[str] = []
    seen: set[str] = set()
    known_agents = _known_agents_runtime()
    for mention in mentions:
        if mention in known_agents and mention not in seen:
            seen.add(mention)
            targets.append(mention)
    if targets:
        return [(agent, payload) for agent in targets]
    return [(_DEFAULT_ROUTE, payload)]


def _telegram_api_call(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not _BOT_TOKEN:
        return {"error": "Telegram Bot Token fehlt."}

    url = f"{_TELEGRAM_API_BASE_URL}/bot{_BOT_TOKEN}/{method}"
    try:
        with httpx.Client(timeout=max(float(_POLL_TIMEOUT) + 10.0, 30.0)) as client:
            resp = client.post(url, json=payload or {})
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        return {"error": f"Telegram API nicht erreichbar: {_TELEGRAM_API_BASE_URL}"}
    except Exception as exc:
        return {"error": f"Telegram API request failed: {exc}"}

    if not data.get("ok"):
        return {"error": f"Telegram API error: {data.get('description', 'unknown_error')}"}
    return data


def _normalize_update(update: dict[str, Any]) -> dict[str, Any] | None:
    raw_message = update.get("message") or update.get("channel_post")
    if not isinstance(raw_message, dict):
        return None
    chat = raw_message.get("chat", {})
    chat_id = str(chat.get("id", "")).strip()
    if not chat_id:
        return None
    sender_obj = raw_message.get("from") or {}
    sender = (
        str(sender_obj.get("username", "")).strip()
        or " ".join(
            part
            for part in (
                str(sender_obj.get("first_name", "")).strip(),
                str(sender_obj.get("last_name", "")).strip(),
            )
            if part
        ).strip()
        or str(sender_obj.get("id", "")).strip()
    )
    timestamp = raw_message.get("date")
    time_iso = ""
    if isinstance(timestamp, (int, float)) and float(timestamp) > 0:
        time_iso = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat()
    return {
        "update_id": int(update.get("update_id", 0) or 0),
        "message_id": raw_message.get("message_id"),
        "chat_id": chat_id,
        "chat": str(chat.get("title") or chat.get("username") or chat_id),
        "sender": sender,
        "text": str(raw_message.get("text") or raw_message.get("caption") or "").strip(),
        "time": time_iso,
        "is_bot": bool(sender_obj.get("is_bot", False)),
    }


def _append_store(entry: dict[str, Any]) -> None:
    store_path = Path(_STORE_PATH)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with open(store_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    try:
        os.chmod(store_path, 0o600)
    except OSError:
        pass


def _bridge_send(to: str, content: str, *, meta: dict[str, Any]) -> bool:
    try:
        headers = {}
        if _BRIDGE_USER_TOKEN:
            headers["X-Bridge-Token"] = _BRIDGE_USER_TOKEN
        payload = {
            "from": "user",
            "to": to,
            "content": f"[Telegram/{meta.get('telegram_chat', meta.get('telegram_chat_id', 'chat'))}] {content}",
            "meta": meta,
        }
        resp = httpx.post(
            f"{_BRIDGE_URL}/send",
            json=payload,
            headers=headers or None,
            timeout=10.0,
        )
        data = resp.json()
        if data.get("ok"):
            return True
        print(f"[telegram_watcher] bridge_send to {to} failed: {data}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"[telegram_watcher] bridge_send error: {exc}", file=sys.stderr)
        return False


def _bootstrap_offset(state: dict[str, Any]) -> None:
    if int(state.get("offset", 0) or 0) > 0:
        return
    result = _telegram_api_call(
        "getUpdates",
        {
            "limit": 100,
            "timeout": 0,
            "allowed_updates": ["message", "channel_post"],
        },
    )
    if result.get("error"):
        print(f"[telegram_watcher] Bootstrap failed: {result['error']}", file=sys.stderr)
        return
    max_update_id = 0
    for raw in result.get("result", []):
        if not isinstance(raw, dict):
            continue
        update_id = int(raw.get("update_id", 0) or 0)
        max_update_id = max(max_update_id, update_id + 1)
    if max_update_id > 0:
        state["offset"] = max_update_id
        _save_state(state)
        print(f"[telegram_watcher] Erster Start — beginne ab update_id {max_update_id}")


def _poll_updates(state: dict[str, Any]) -> list[dict[str, Any]]:
    offset = int(state.get("offset", 0) or 0)
    payload: dict[str, Any] = {
        "timeout": _POLL_TIMEOUT,
        "allowed_updates": ["message", "channel_post"],
    }
    if offset > 0:
        payload["offset"] = offset
    result = _telegram_api_call("getUpdates", payload)
    if result.get("error"):
        print(f"[telegram_watcher] Poll failed: {result['error']}", file=sys.stderr)
        return []

    normalized_updates: list[dict[str, Any]] = []
    next_offset = offset
    for raw in result.get("result", []):
        if not isinstance(raw, dict):
            continue
        update_id = int(raw.get("update_id", 0) or 0)
        next_offset = max(next_offset, update_id + 1)
        normalized = _normalize_update(raw)
        if not normalized:
            continue
        if normalized["chat_id"] not in _WATCH_CHATS:
            continue
        _append_store(normalized)
        normalized_updates.append(normalized)

    if next_offset != offset:
        state["offset"] = next_offset
        _save_state(state)
    return normalized_updates


def main() -> None:
    print("[telegram_watcher] Telegram Watcher gestartet")
    print(f"[telegram_watcher] Bridge: {_BRIDGE_URL}")
    print(f"[telegram_watcher] API: {_TELEGRAM_API_BASE_URL}")
    print(f"[telegram_watcher] Config: {_CONFIG_PATH}")
    print(f"[telegram_watcher] Store: {_STORE_PATH}")
    print(f"[telegram_watcher] Watch chats: {', '.join(_WATCH_CHATS) if _WATCH_CHATS else 'MISSING'}")
    print(f"[telegram_watcher] Default route: {_DEFAULT_ROUTE}")
    print(f"[telegram_watcher] Token: {'set' if _BOT_TOKEN else 'MISSING'}")

    if not _BOT_TOKEN:
        print(
            "[telegram_watcher] Telegram Bot Token fehlt. Setze TELEGRAM_BOT_TOKEN oder ~/.config/bridge/telegram_bot_token.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not _WATCH_CHATS:
        print(
            "[telegram_watcher] Keine Telegram watch_chats konfiguriert. Setze TELEGRAM_WATCH_CHATS oder watch_chats/read_whitelist in telegram_config.json.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    _acquire_lock()
    state = _load_state()
    _bootstrap_offset(state)

    while True:
        try:
            for message in _poll_updates(state):
                if message.get("is_bot"):
                    continue
                content = str(message.get("text", "")).strip()
                if not content:
                    continue
                meta = {
                    "source": "telegram",
                    "reply_channel": "telegram",
                    "telegram_chat_id": message.get("chat_id", ""),
                    "telegram_chat": message.get("chat", ""),
                    "telegram_message_id": message.get("message_id"),
                }
                for agent, payload in _route_message(content):
                    ok = _bridge_send(agent, payload, meta=meta)
                    status = "OK" if ok else "FAIL"
                    print(
                        f"[telegram_watcher] {message.get('time', '')} chat={message.get('chat_id', '')} -> {agent}: {status}"
                    )
        except KeyboardInterrupt:
            print("[telegram_watcher] Stop requested")
            return
        except Exception as exc:
            print(f"[telegram_watcher] Loop error: {exc}", file=sys.stderr)

        time.sleep(_POLL_INTERVAL)


if __name__ == "__main__":
    main()
