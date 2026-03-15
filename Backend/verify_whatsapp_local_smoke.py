#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class _QuietHandler(BaseHTTPRequestHandler):
    server_version = "BridgeWhatsAppSmoke/1.0"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        del format, args


class _FakeWhatsAppHandler(_QuietHandler):
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
        body = {"success": True, "message": "sent"}
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class _FakeBridgeHandler(_QuietHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw or "{}")
        self.server.requests.append({"path": self.path, "json": payload})  # type: ignore[attr-defined]

        if self.path == "/approval/request":
            body = {"status": "auto_approved", "standing_approval_id": "smoke-standing-1"}
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


def _write_config(config_path: Path, *, group_jid: str, sender: str) -> None:
    payload = {
        "watch_group_jid": group_jid,
        "sender_filter": sender,
        "read_whitelist": [group_jid],
        "send_whitelist": [group_jid],
        "approval_whitelist": [],
        "contacts": {
            "team": group_jid,
        },
    }
    config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _init_db(db_path: Path, *, group_jid: str, sender: str) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE chats (
                jid TEXT PRIMARY KEY,
                name TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                chat_jid TEXT NOT NULL,
                sender TEXT,
                content TEXT,
                timestamp TEXT,
                is_from_me INTEGER NOT NULL,
                media_type TEXT,
                filename TEXT,
                file_length INTEGER
            )
            """
        )
        conn.execute("INSERT INTO chats (jid, name) VALUES (?, ?)", (group_jid, "Smoke Team"))
        conn.execute(
            """
            INSERT INTO messages (
                id, chat_jid, sender, content, timestamp, is_from_me,
                media_type, filename, file_length
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-read-1",
                group_jid,
                sender,
                "Vorhandene Smoke-Nachricht",
                "2026-03-13T12:00:00Z",
                1,
                "",
                "",
                0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_message(
    db_path: Path,
    *,
    message_id: str,
    group_jid: str,
    sender: str,
    content: str,
    timestamp: str,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO messages (
                id, chat_jid, sender, content, timestamp, is_from_me,
                media_type, filename, file_length
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, group_jid, sender, content, timestamp, 1, "", "", 0),
        )
        conn.commit()
    finally:
        conn.close()


def _wait_for(predicate: callable, *, timeout: float = 10.0, interval: float = 0.1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _extract_send_paths(server: ThreadingHTTPServer) -> list[dict[str, Any]]:
    return [entry for entry in server.requests if entry.get("path") == "/api/send"]  # type: ignore[attr-defined]


def _extract_bridge_path(server: ThreadingHTTPServer, path: str) -> list[dict[str, Any]]:
    return [entry for entry in server.requests if entry.get("path") == path]  # type: ignore[attr-defined]


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
    with tempfile.TemporaryDirectory(prefix="bridge_whatsapp_smoke_") as tmpdir:
        temp_root = Path(tmpdir)
        config_path = temp_root / "whatsapp_config.json"
        db_path = temp_root / "store" / "messages.db"
        media_path = temp_root / "sample.png"
        audio_path = temp_root / "voice.ogg"
        watcher_state_path = temp_root / "watcher_state.json"
        watcher_lock_path = temp_root / "watcher.lock"

        group_jid = "120363000000000000@g.us"
        sender = "4915111222333"
        _write_config(config_path, group_jid=group_jid, sender=sender)
        _init_db(db_path, group_jid=group_jid, sender=sender)
        media_path.write_bytes(b"fake-image")
        audio_path.write_bytes(b"OggS-smoke-audio")

        wa_server, wa_thread, wa_base = _start_server(_FakeWhatsAppHandler)
        bridge_server, bridge_thread, bridge_base = _start_server(_FakeBridgeHandler)
        watcher_proc: subprocess.Popen[str] | None = None

        old_env = os.environ.copy()
        os.environ.update(
            {
                "WHATSAPP_CONFIG_PATH": str(config_path),
                "WHATSAPP_DB_PATH": str(db_path),
                "WHATSAPP_BRIDGE_URL": wa_base,
                "WHATSAPP_API_TOKEN": "smoke-token",
                "WHATSAPP_GROUP_JID": group_jid,
                "WHATSAPP_LEO_SENDER": sender,
                "WHATSAPP_READ_WHITELIST": group_jid,
                "WHATSAPP_SEND_WHITELIST": group_jid,
                "WHATSAPP_APPROVAL_WHITELIST": "",
                "WHATSAPP_WEBHOOK_ACTIVE": "0",
            }
        )

        try:
            bridge_mcp = importlib.import_module("bridge_mcp")
            bridge_mcp = importlib.reload(bridge_mcp)
            import voice_tts

            bridge_mcp.BRIDGE_HTTP = bridge_base
            if bridge_mcp._http_client is not None:
                asyncio.run(bridge_mcp._http_client.aclose())
            bridge_mcp._http_client = None
            bridge_mcp._agent_id = "codex"

            send_raw = asyncio.run(
                bridge_mcp.bridge_whatsapp_send("team", "Smoke outbound", media_path=str(media_path))
            )
            send_data = json.loads(send_raw)
            if send_data.get("status") != "sent":
                raise RuntimeError(f"Outbound send failed: {send_data}")

            read_raw = asyncio.run(bridge_mcp.bridge_whatsapp_read(limit=5))
            read_data = json.loads(read_raw)
            if read_data.get("status") != "ok":
                raise RuntimeError(f"WhatsApp read failed: {read_data}")
            read_messages = json.loads(read_data.get("result", "[]"))
            if not isinstance(read_messages, list) or not read_messages:
                raise RuntimeError(f"WhatsApp read returned no messages: {read_data}")

            async def _fake_tts(*, text: str, voice_id: str = "") -> dict[str, Any]:
                del voice_id
                return {
                    "audio_path": str(audio_path),
                    "chars_used": len(text),
                    "elapsed_s": 0.01,
                }

            with patch.object(voice_tts, "synthesize_speech", _fake_tts):
                voice_raw = asyncio.run(bridge_mcp.bridge_whatsapp_voice("team", "Smoke voice"))
            voice_data = json.loads(voice_raw)
            if voice_data.get("status") != "sent":
                raise RuntimeError(f"Voice send failed: {voice_data}")

            watcher_env = old_env.copy()
            watcher_env.update(
                {
                    "WHATSAPP_CONFIG_PATH": str(config_path),
                    "WHATSAPP_DB_PATH": str(db_path),
                    "WHATSAPP_BRIDGE_URL": wa_base,
                    "WHATSAPP_API_TOKEN": "smoke-token",
                    "BRIDGE_URL": bridge_base,
                    "WHATSAPP_GROUP_JID": group_jid,
                    "WHATSAPP_LEO_SENDER": sender,
                    "WHATSAPP_READ_WHITELIST": group_jid,
                    "WHATSAPP_SEND_WHITELIST": group_jid,
                    "WHATSAPP_APPROVAL_WHITELIST": "",
                    "WHATSAPP_WEBHOOK_ACTIVE": "0",
                    "WHATSAPP_WATCHER_STATE_FILE": str(watcher_state_path),
                    "WHATSAPP_WATCHER_LOCK_FILE": str(watcher_lock_path),
                }
            )

            watcher_proc = subprocess.Popen(
                [sys.executable, "-u", str(BACKEND_DIR / "whatsapp_watcher.py")],
                cwd=str(BACKEND_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=watcher_env,
            )

            if not _wait_for(lambda: watcher_state_path.exists(), timeout=8.0):
                raise RuntimeError("watcher did not initialize state file")

            _insert_message(
                db_path,
                message_id="msg-watch-1",
                group_jid=group_jid,
                sender=sender,
                content="@codex smoke inbound",
                timestamp="2026-03-13T12:01:00Z",
            )

            if not _wait_for(lambda: len(_extract_bridge_path(bridge_server, "/send")) >= 1, timeout=10.0):
                watcher_output = _stop_process_capture(watcher_proc)
                raise RuntimeError(f"watcher did not forward inbound message. Output:\n{watcher_output}")

            watcher_output = _stop_process_capture(watcher_proc)

            bridge_approval_requests = _extract_bridge_path(bridge_server, "/approval/request")
            bridge_inbound_requests = _extract_bridge_path(bridge_server, "/send")
            wa_requests = _extract_send_paths(wa_server)

            if len(bridge_approval_requests) < 2:
                raise RuntimeError(f"expected >=2 approval requests, got {len(bridge_approval_requests)}")
            if len(wa_requests) < 2:
                raise RuntimeError(f"expected >=2 WhatsApp sends, got {len(wa_requests)}")

            result = {
                "ok": True,
                "temp_root": str(temp_root),
                "checks": {
                    "read": {
                        "status": "ok",
                        "count": len(read_messages),
                        "first_message": read_messages[0],
                    },
                    "send": {
                        "status": "ok",
                        "approval_requests": len(bridge_approval_requests),
                        "payload": wa_requests[0]["json"],
                    },
                    "voice_internal_path": {
                        "status": "ok",
                        "payload": wa_requests[1]["json"],
                        "note": "TTS was stubbed locally; ElevenLabs network was not used.",
                    },
                    "watcher_inbound": {
                        "status": "ok",
                        "bridge_send_payload": bridge_inbound_requests[0]["json"],
                        "watcher_output_tail": watcher_output.splitlines()[-8:],
                    },
                },
                "limitations": [
                    "No real WhatsApp network send was performed.",
                    "No real ElevenLabs API call was performed; voice path was exercised with a local stub.",
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
            _stop_server(wa_server, wa_thread)
            _stop_server(bridge_server, bridge_thread)


if __name__ == "__main__":
    raise SystemExit(main())
