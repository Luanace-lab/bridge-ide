#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class _QuietHandler(BaseHTTPRequestHandler):
    server_version = "BridgeTelegramSmoke/1.0"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        del format, args


class _FakeTelegramHandler(_QuietHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw or "{}")
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
                "json": payload,
            }
        )

        if self.path.endswith("/sendMessage"):
            chat_id = str(payload.get("chat_id", "")).strip()
            text = str(payload.get("text", ""))
            body = {
                "ok": True,
                "result": {
                    "message_id": len(self.server.sent_messages) + 1,  # type: ignore[attr-defined]
                    "chat": {"id": chat_id, "title": "Smoke Telegram"},
                    "text": text,
                },
            }
            self.server.sent_messages.append(body["result"])  # type: ignore[attr-defined]
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        if self.path.endswith("/getUpdates"):
            offset = int(payload.get("offset", 0) or 0)
            updates = [
                update for update in self.server.updates  # type: ignore[attr-defined]
                if int(update.get("update_id", 0) or 0) >= offset
            ]
            body = {"ok": True, "result": updates}
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        self.send_error(404)


class _FakeBridgeHandler(_QuietHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw or "{}")
        self.server.requests.append({"path": self.path, "json": payload})  # type: ignore[attr-defined]

        if self.path == "/approval/request":
            body = {"status": "auto_approved", "standing_approval_id": "smoke-standing-telegram"}
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        if self.path == "/send":
            body = {"ok": True}
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        self.send_error(404)


def _start_server(handler_cls: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    server.requests = []  # type: ignore[attr-defined]
    if handler_cls is _FakeTelegramHandler:
        server.updates = []  # type: ignore[attr-defined]
        server.sent_messages = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    return server, thread, base_url


def _stop_server(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    with suppress(Exception):
        server.shutdown()
    with suppress(Exception):
        server.server_close()
    thread.join(timeout=1)


def _write_config(config_path: Path, *, chat_id: str) -> None:
    payload = {
        "read_whitelist": [chat_id],
        "send_whitelist": [chat_id],
        "approval_whitelist": [],
        "watch_chats": [chat_id],
        "default_route": "ordo",
        "contacts": {
            "team": chat_id,
        },
    }
    config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _append_update(server: ThreadingHTTPServer, *, update_id: int, chat_id: str, text: str, sender: str) -> None:
    server.updates.append(  # type: ignore[attr-defined]
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 1741867200 + update_id,
                "chat": {"id": int(chat_id), "title": "Smoke Telegram"},
                "from": {"id": 555000 + update_id, "username": sender, "is_bot": False},
                "text": text,
            },
        }
    )


def _wait_for(predicate: Any, *, timeout: float = 10.0, interval: float = 0.1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _extract_path(server: ThreadingHTTPServer, path_suffix: str) -> list[dict[str, Any]]:
    return [
        entry
        for entry in server.requests  # type: ignore[attr-defined]
        if str(entry.get("path", "")).endswith(path_suffix)
    ]


def _stop_process_capture(proc: subprocess.Popen[str] | None) -> str:
    if proc is None:
        return ""
    output = ""
    if proc.poll() is None:
        with suppress(Exception):
            proc.terminate()
            output, _ = proc.communicate(timeout=5)
        if proc.poll() is None:
            with suppress(Exception):
                proc.kill()
                output, _ = proc.communicate(timeout=5)
    elif proc.stdout is not None:
        with suppress(Exception):
            output = proc.stdout.read()
    return output


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bridge_telegram_smoke_") as tmpdir:
        temp_root = Path(tmpdir)
        config_path = temp_root / "telegram_config.json"
        store_path = temp_root / "telegram_updates.jsonl"
        watcher_state_path = temp_root / "telegram_watcher_state.json"
        watcher_lock_path = temp_root / "telegram_watcher.lock"
        chat_id = "-1001234567890"

        _write_config(config_path, chat_id=chat_id)

        telegram_server, telegram_thread, telegram_base = _start_server(_FakeTelegramHandler)
        bridge_server, bridge_thread, bridge_base = _start_server(_FakeBridgeHandler)
        watcher_proc: subprocess.Popen[str] | None = None

        _append_update(telegram_server, update_id=100, chat_id=chat_id, text="Vorhandene Smoke-Nachricht", sender="smoke_user")

        old_env = os.environ.copy()
        os.environ.update(
            {
                "TELEGRAM_CONFIG_PATH": str(config_path),
                "TELEGRAM_BOT_TOKEN": "smoke-bot-token",
                "TELEGRAM_API_BASE_URL": telegram_base,
                "TELEGRAM_READ_WHITELIST": chat_id,
                "TELEGRAM_SEND_WHITELIST": chat_id,
                "TELEGRAM_APPROVAL_WHITELIST": "",
                "TELEGRAM_UPDATES_STORE_PATH": str(store_path),
            }
        )

        try:
            bridge_mcp = importlib.import_module("bridge_mcp")
            bridge_mcp = importlib.reload(bridge_mcp)
            bridge_mcp.BRIDGE_HTTP = bridge_base
            if bridge_mcp._http_client is not None:
                asyncio.run(bridge_mcp._http_client.aclose())
            bridge_mcp._http_client = None
            bridge_mcp._agent_id = "codex"

            send_raw = asyncio.run(bridge_mcp.bridge_telegram_send("team", "Smoke outbound"))
            send_data = json.loads(send_raw)
            if send_data.get("status") != "sent":
                raise RuntimeError(f"Telegram send failed: {send_data}")

            live_read_raw = asyncio.run(bridge_mcp.bridge_telegram_read(limit=5))
            live_read_data = json.loads(live_read_raw)
            if live_read_data.get("status") != "ok":
                raise RuntimeError(f"Telegram live read failed: {live_read_data}")
            live_messages = live_read_data.get("messages", [])
            if not isinstance(live_messages, list) or not live_messages:
                raise RuntimeError(f"Telegram live read returned no messages: {live_read_data}")

            watcher_env = old_env.copy()
            watcher_env.update(
                {
                    "TELEGRAM_CONFIG_PATH": str(config_path),
                    "TELEGRAM_BOT_TOKEN": "smoke-bot-token",
                    "TELEGRAM_API_BASE_URL": telegram_base,
                    "TELEGRAM_UPDATES_STORE_PATH": str(store_path),
                    "TELEGRAM_WATCHER_STATE_FILE": str(watcher_state_path),
                    "TELEGRAM_WATCHER_LOCK_FILE": str(watcher_lock_path),
                    "TELEGRAM_WATCH_CHATS": chat_id,
                    "TELEGRAM_READ_WHITELIST": chat_id,
                    "BRIDGE_URL": bridge_base,
                }
            )

            watcher_proc = subprocess.Popen(
                [sys.executable, "-u", str(BACKEND_DIR / "telegram_watcher.py")],
                cwd=str(BACKEND_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=watcher_env,
            )

            if not _wait_for(lambda: watcher_state_path.exists(), timeout=8.0):
                raise RuntimeError("telegram watcher did not initialize state file")

            _append_update(telegram_server, update_id=101, chat_id=chat_id, text="@codex smoke inbound", sender="smoke_user")

            if not _wait_for(lambda: len(_extract_path(bridge_server, "/send")) >= 1, timeout=12.0):
                watcher_output = _stop_process_capture(watcher_proc)
                raise RuntimeError(f"telegram watcher did not forward inbound message. Output:\n{watcher_output}")

            if not _wait_for(lambda: store_path.exists(), timeout=5.0):
                raise RuntimeError("telegram watcher did not create local updates store")

            store_read_raw = asyncio.run(bridge_mcp.bridge_telegram_read(limit=10))
            store_read_data = json.loads(store_read_raw)
            if store_read_data.get("status") != "ok" or store_read_data.get("source") != "store":
                raise RuntimeError(f"Telegram store read failed: {store_read_data}")

            watcher_output = _stop_process_capture(watcher_proc)

            telegram_send_requests = _extract_path(telegram_server, "/sendMessage")
            telegram_update_requests = _extract_path(telegram_server, "/getUpdates")
            bridge_approval_requests = _extract_path(bridge_server, "/approval/request")
            bridge_inbound_requests = _extract_path(bridge_server, "/send")

            if len(bridge_approval_requests) < 1:
                raise RuntimeError("expected Telegram approval request")
            if len(telegram_send_requests) < 1:
                raise RuntimeError("expected Telegram sendMessage call")
            if len(telegram_update_requests) < 1:
                raise RuntimeError("expected Telegram getUpdates calls")

            result = {
                "ok": True,
                "temp_root": str(temp_root),
                "checks": {
                    "send": {
                        "status": "ok",
                        "approval_requests": len(bridge_approval_requests),
                        "payload": telegram_send_requests[0]["json"],
                    },
                    "read_live": {
                        "status": "ok",
                        "count": len(live_messages),
                        "first_message": live_messages[0],
                    },
                    "watcher_inbound": {
                        "status": "ok",
                        "bridge_send_payload": bridge_inbound_requests[0]["json"],
                        "watcher_output_tail": watcher_output.splitlines()[-8:],
                    },
                    "read_store": {
                        "status": "ok",
                        "count": len(store_read_data.get("messages", [])),
                        "source": store_read_data.get("source"),
                    },
                },
                "limitations": [
                    "No real Telegram network send was performed.",
                    "No real BotFather token or live Telegram chat was used.",
                ],
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        finally:
            _stop_process_capture(watcher_proc)
            if "bridge_mcp" in locals() and getattr(bridge_mcp, "_http_client", None) is not None:
                with suppress(Exception):
                    asyncio.run(bridge_mcp._http_client.aclose())
            os.environ.clear()
            os.environ.update(old_env)
            _stop_server(telegram_server, telegram_thread)
            _stop_server(bridge_server, bridge_thread)


if __name__ == "__main__":
    raise SystemExit(main())
