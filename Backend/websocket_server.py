from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

try:
    import websockets
    import websockets.asyncio.server

    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

WS_CLIENTS: dict[Any, dict[str, str]] = {}
WS_LOCK = threading.Lock()
WS_LOOP: asyncio.AbstractEventLoop | None = None

_bridge_user_token_getter: Callable[[], str] | None = None
_ui_session_token_getter: Callable[[], str] | None = None
_strict_auth_getter: Callable[[], bool] | None = None
_append_message_fn: Callable[..., Any] | None = None
_is_federation_target_fn: Callable[[str], bool] | None = None
_federation_send_outbound_fn: Callable[[str, str, str], dict[str, Any]] | None = None
_update_agent_status_fn: Callable[[str], Any] | None = None
_runtime_snapshot_fn: Callable[[], dict[str, Any]] | None = None
_get_team_members_fn: Callable[[str], list[str]] | None = None
_ws_host_getter: Callable[[], str] | None = None
_ws_port_getter: Callable[[], int] | None = None
_allowed_origins_getter: Callable[[], list[str]] | None = None

_AGENT_STATE_LOCK: threading.Lock | None = None
_SESSION_TOKENS: dict[str, str] | None = None
_GRACE_TOKENS: dict[str, tuple[str, float]] | None = None
_AGENT_BUSY: dict[str, bool] | None = None
_AGENT_LAST_SEEN: dict[str, float] | None = None
_COND: threading.Condition | None = None
_MESSAGES: list[dict[str, Any]] | None = None


def init(
    *,
    bridge_user_token_getter: Callable[[], str],
    ui_session_token_getter: Callable[[], str],
    strict_auth_getter: Callable[[], bool],
    agent_state_lock: threading.Lock,
    session_tokens: dict[str, str],
    grace_tokens: dict[str, tuple[str, float]],
    append_message_fn: Callable[..., Any],
    is_federation_target_fn: Callable[[str], bool],
    federation_send_outbound_fn: Callable[[str, str, str], dict[str, Any]],
    update_agent_status_fn: Callable[[str], Any],
    agent_busy: dict[str, bool],
    agent_last_seen: dict[str, float],
    cond: threading.Condition,
    messages: list[dict[str, Any]],
    runtime_snapshot_fn: Callable[[], dict[str, Any]],
    get_team_members_fn: Callable[[str], list[str]],
    ws_host_getter: Callable[[], str],
    ws_port_getter: Callable[[], int],
    allowed_origins_getter: Callable[[], list[str]],
) -> None:
    global _bridge_user_token_getter, _ui_session_token_getter, _strict_auth_getter
    global _AGENT_STATE_LOCK, _SESSION_TOKENS, _GRACE_TOKENS
    global _append_message_fn, _is_federation_target_fn, _federation_send_outbound_fn
    global _update_agent_status_fn, _AGENT_BUSY, _AGENT_LAST_SEEN
    global _COND, _MESSAGES, _runtime_snapshot_fn, _get_team_members_fn
    global _ws_host_getter, _ws_port_getter, _allowed_origins_getter

    _bridge_user_token_getter = bridge_user_token_getter
    _ui_session_token_getter = ui_session_token_getter
    _strict_auth_getter = strict_auth_getter
    _AGENT_STATE_LOCK = agent_state_lock
    _SESSION_TOKENS = session_tokens
    _GRACE_TOKENS = grace_tokens
    _append_message_fn = append_message_fn
    _is_federation_target_fn = is_federation_target_fn
    _federation_send_outbound_fn = federation_send_outbound_fn
    _update_agent_status_fn = update_agent_status_fn
    _AGENT_BUSY = agent_busy
    _AGENT_LAST_SEEN = agent_last_seen
    _COND = cond
    _MESSAGES = messages
    _runtime_snapshot_fn = runtime_snapshot_fn
    _get_team_members_fn = get_team_members_fn
    _ws_host_getter = ws_host_getter
    _ws_port_getter = ws_port_getter
    _allowed_origins_getter = allowed_origins_getter


def _require_initialized() -> None:
    required = (
        _bridge_user_token_getter,
        _ui_session_token_getter,
        _strict_auth_getter,
        _AGENT_STATE_LOCK,
        _SESSION_TOKENS,
        _GRACE_TOKENS,
        _append_message_fn,
        _is_federation_target_fn,
        _federation_send_outbound_fn,
        _update_agent_status_fn,
        _AGENT_BUSY,
        _AGENT_LAST_SEEN,
        _COND,
        _MESSAGES,
        _runtime_snapshot_fn,
        _get_team_members_fn,
        _ws_host_getter,
        _ws_port_getter,
        _allowed_origins_getter,
    )
    if any(item is None for item in required):
        raise RuntimeError("websocket_server not initialized")


def _bridge_user_token() -> str:
    return (_bridge_user_token_getter or (lambda: ""))()


def _ui_session_token() -> str:
    return (_ui_session_token_getter or (lambda: ""))()


def _strict_auth() -> bool:
    return bool((_strict_auth_getter or (lambda: False))())


def ws_broadcast(event_type: str, payload: dict[str, Any]) -> None:
    if not HAS_WEBSOCKETS:
        return
    with WS_LOCK:
        clients = set(WS_CLIENTS.keys())
        loop = WS_LOOP
    if not clients or loop is None:
        return

    message = json.dumps({"type": event_type, **payload}, ensure_ascii=False)

    async def _broadcast() -> None:
        dead: list[Any] = []
        for ws in clients:
            try:
                await ws.send(message)
            except Exception:
                dead.append(ws)
        if dead:
            with WS_LOCK:
                for ws in dead:
                    WS_CLIENTS.pop(ws, None)

    try:
        asyncio.run_coroutine_threadsafe(_broadcast(), loop)
    except RuntimeError:
        pass


def ws_broadcast_message(msg: dict[str, Any]) -> None:
    if not HAS_WEBSOCKETS:
        return
    _require_initialized()
    with WS_LOCK:
        all_clients = dict(WS_CLIENTS)
        loop = WS_LOOP
    if not all_clients or loop is None:
        return

    recipient = str(msg.get("to", ""))
    sender = str(msg.get("from", ""))
    full_payload = json.dumps({"type": "message", "message": msg}, ensure_ascii=False)

    async def _targeted_broadcast() -> None:
        dead: list[Any] = []
        for ws, info in all_clients.items():
            ws_agent = info.get("agent_id", "")
            ws_role = info.get("role", "")

            if ws_role in {"ui", "user"}:
                try:
                    await ws.send(full_payload)
                except Exception:
                    dead.append(ws)
                continue

            if ws_agent == sender:
                continue
            deliver = False
            if recipient in {ws_agent, "all", "all_managers"}:
                deliver = True
            elif recipient.startswith("team:"):
                team_id = recipient[len("team:"):]
                if ws_agent in _get_team_members_fn(team_id):
                    deliver = True
            if deliver:
                try:
                    await ws.send(full_payload)
                except Exception:
                    dead.append(ws)

        if dead:
            with WS_LOCK:
                for ws in dead:
                    WS_CLIENTS.pop(ws, None)

    try:
        asyncio.run_coroutine_threadsafe(_targeted_broadcast(), loop)
    except RuntimeError:
        pass


async def ws_handler(websocket: Any) -> None:
    _require_initialized()
    remote = getattr(websocket, "remote_address", ("?", 0))

    ws_path = getattr(websocket, "path", "") or ""
    if not ws_path:
        req = getattr(websocket, "request", None)
        if req:
            ws_path = getattr(req, "path", "") or ""

    def _ws_request_context() -> str:
        req = getattr(websocket, "request", None)
        headers = getattr(req, "headers", None) if req is not None else None
        if headers is None:
            headers = getattr(websocket, "request_headers", None)
        user_agent = "-"
        origin = "-"
        referer = "-"
        if headers is not None:
            try:
                user_agent = str(headers.get("User-Agent", "")).strip() or "-"
                origin = str(headers.get("Origin", "")).strip() or "-"
                referer = str(headers.get("Referer", "")).strip() or "-"
            except Exception:
                pass
        path_text = ws_path or "-"
        return f"path={path_text} origin={origin} referer={referer} ua={user_agent}"

    params = parse_qs(urlsplit(ws_path).query)
    token = (params.get("token") or [""])[0]

    if token:
        if _bridge_user_token() and secrets.compare_digest(token, _bridge_user_token()):
            ws_role = "user"
            ws_agent_id = "user"
        elif _ui_session_token() and secrets.compare_digest(token, _ui_session_token()):
            ws_role = "ui"
            ws_agent_id = "ui"
        else:
            with _AGENT_STATE_LOCK:
                bound_agent = _SESSION_TOKENS.get(token)
            if not bound_agent:
                grace_entry = _GRACE_TOKENS.get(token)
                if grace_entry and time.time() < grace_entry[1]:
                    bound_agent = grace_entry[0]
            if bound_agent:
                ws_role = "agent"
                ws_agent_id = bound_agent
            else:
                await websocket.close(4001, "unauthorized")
                print(f"[ws] rejected connection from {remote}: invalid token ({_ws_request_context()})")
                return
    else:
        try:
            raw_auth = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            auth_data = json.loads(raw_auth)
            if isinstance(auth_data, dict) and auth_data.get("type") == "auth":
                fm_token = str(auth_data.get("token", "")).strip()
                if fm_token:
                    if _bridge_user_token() and secrets.compare_digest(fm_token, _bridge_user_token()):
                        ws_role = "user"
                        ws_agent_id = "user"
                    elif _ui_session_token() and secrets.compare_digest(fm_token, _ui_session_token()):
                        ws_role = "ui"
                        ws_agent_id = "ui"
                    else:
                        with _AGENT_STATE_LOCK:
                            bound_agent = _SESSION_TOKENS.get(fm_token)
                        if not bound_agent:
                            grace_entry = _GRACE_TOKENS.get(fm_token)
                            if grace_entry and time.time() < grace_entry[1]:
                                bound_agent = grace_entry[0]
                        if bound_agent:
                            ws_role = "agent"
                            ws_agent_id = bound_agent
                        else:
                            await websocket.close(4001, "unauthorized")
                            print(f"[ws] rejected connection from {remote}: invalid token in auth message ({_ws_request_context()})")
                            return
                else:
                    await websocket.close(4001, "unauthorized")
                    print(f"[ws] rejected connection from {remote}: empty token in auth message ({_ws_request_context()})")
                    return
            else:
                if _strict_auth():
                    await websocket.close(4001, "unauthorized")
                    print(f"[ws] rejected connection from {remote}: first message not auth ({_ws_request_context()})")
                    return
                ws_role = "ui"
                ws_agent_id = "ui"
        except (asyncio.TimeoutError, json.JSONDecodeError, TypeError):
            if _strict_auth():
                await websocket.close(4001, "unauthorized")
                print(f"[ws] rejected connection from {remote}: auth timeout or invalid ({_ws_request_context()})")
                return
            ws_role = "ui"
            ws_agent_id = "ui"

    with WS_LOCK:
        WS_CLIENTS[websocket] = {"agent_id": ws_agent_id, "role": ws_role}
    print(f"[ws] client connected: {remote} (agent_id={ws_agent_id}, role={ws_role}, {_ws_request_context()})")

    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            msg_type = data.get("type", "")

            if msg_type == "send":
                sender = ws_agent_id if ws_role == "agent" else "user"
                recipient = str(data.get("to", "")).strip()
                content = str(data.get("content", "")).strip()
                meta = data.get("meta")
                if sender and recipient and content:
                    federation_target = _is_federation_target_fn(recipient)
                    msg_meta = dict(meta) if isinstance(meta, dict) else None
                    if federation_target:
                        try:
                            fed_meta = _federation_send_outbound_fn(sender, recipient, content)
                        except Exception as exc:
                            _append_message_fn(
                                "system",
                                sender,
                                f"[FEDERATION_ERROR] outbound delivery failed: {exc}",
                                meta={"type": "federation_error"},
                            )
                            continue
                        if msg_meta is None:
                            msg_meta = {}
                        msg_meta["federation"] = fed_meta

                    _append_message_fn(sender, recipient, content, msg_meta)
                    non_agent = {"system", "user", "all", "all_managers", "leads"}
                    if federation_target:
                        non_agent.add(recipient)
                    if recipient not in non_agent and not recipient.startswith("team:"):
                        with _AGENT_STATE_LOCK:
                            _AGENT_BUSY[recipient] = True
                        _update_agent_status_fn(recipient)
                    if sender not in non_agent:
                        with _AGENT_STATE_LOCK:
                            _AGENT_BUSY[sender] = False
                            _AGENT_LAST_SEEN[sender] = time.time()
                        _update_agent_status_fn(sender)

            elif msg_type == "subscribe":
                if ws_role in {"agent", "user"}:
                    with _COND:
                        history = list(_MESSAGES[-500:])
                    await websocket.send(json.dumps({"type": "history", "messages": history}, ensure_ascii=False))
                snapshot = _runtime_snapshot_fn()
                await websocket.send(json.dumps({"type": "runtime", "runtime": snapshot}, ensure_ascii=False))

            elif msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))

    except Exception:
        pass
    finally:
        with WS_LOCK:
            WS_CLIENTS.pop(websocket, None)
        print(f"[ws] client disconnected: {remote} (agent_id={ws_agent_id})")


def run_websocket_server() -> None:
    global WS_LOOP
    _require_initialized()
    if not HAS_WEBSOCKETS:
        print("[ws] websockets library not installed, WebSocket server disabled")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    WS_LOOP = loop

    async def _serve() -> None:
        async with websockets.asyncio.server.serve(
            ws_handler,
            _ws_host_getter(),
            _ws_port_getter(),
            max_size=10 * 1024 * 1024,
            origins=[None, *_allowed_origins_getter()],
        ):
            print(f"[ws] WebSocket server listening on ws://{_ws_host_getter()}:{_ws_port_getter()}")
            await asyncio.Future()

    try:
        loop.run_until_complete(_serve())
    except Exception as exc:
        print(f"[ws] WebSocket server error: {exc}")
    finally:
        loop.close()
