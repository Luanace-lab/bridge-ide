from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import unittest
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.agents as agents_mod  # noqa: E402
import server as srv  # noqa: E402


class TestAgentAvatarRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="agent_avatar_http_")
        self.frontend_dir = self._tmpdir.name
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        self.team_config = {
            "agents": [{"id": "assi"}],
            "subscriptions": [],
        }
        self._reinit(self.team_config, self._persist, self.frontend_dir)

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        self._reinit(srv.TEAM_CONFIG, srv._atomic_write_team_json, srv.FRONTEND_DIR)
        self._tmpdir.cleanup()

    def _persist(self) -> None:
        return None

    def _reinit(self, team_config: dict, persist_fn, frontend_dir: str) -> None:
        agents_mod.init(
            registered_agents=srv.REGISTERED_AGENTS,
            agent_last_seen=srv.AGENT_LAST_SEEN,
            agent_busy=srv.AGENT_BUSY,
            session_tokens=srv.SESSION_TOKENS,
            agent_tokens=srv.AGENT_TOKENS,
            agent_state_lock=srv.AGENT_STATE_LOCK,
            tasks=srv.TASKS,
            task_lock=srv.TASK_LOCK,
            team_config=team_config,
            team_config_lock=srv.TEAM_CONFIG_LOCK,
            frontend_dir=frontend_dir,
            runtime=srv.RUNTIME,
            runtime_lock=srv.RUNTIME_LOCK,
            ws_broadcast_fn=srv.ws_broadcast,
            notify_teamlead_crashed_fn=srv._notify_teamlead_agent_crashed,
            tmux_session_for_fn=srv._tmux_session_for,
            tmux_session_name_exists_fn=srv._tmux_session_name_exists,
            runtime_layout_from_state_fn=srv._runtime_layout_from_state,
            get_agent_home_dir_fn=srv._get_agent_home_dir,
            check_agent_memory_health_fn=srv._check_agent_memory_health,
            append_message_fn=srv.append_message,
            atomic_write_team_json_fn=persist_fn,
        )

    def _start_server(self) -> str:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        except PermissionError as exc:
            self.skipTest(f"loopback sockets are not permitted in this environment: {exc}")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _multipart_body(self, field: str, filename: str, payload: bytes) -> tuple[bytes, str]:
        boundary = "slice103boundary"
        buf = io.BytesIO()
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode())
        buf.write(b"Content-Type: application/octet-stream\r\n\r\n")
        buf.write(payload)
        buf.write(f"\r\n--{boundary}--\r\n".encode())
        return buf.getvalue(), boundary

    def test_agent_avatar_route_http(self) -> None:
        base_url = self._start_server()
        payload, boundary = self._multipart_body("avatar", "assi.png", b"png-bytes")
        req = urllib.request.Request(
            f"{base_url}/agents/assi/avatar",
            data=payload,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(body["avatar_url"], "/avatars/assi.png")
        self.assertTrue(os.path.exists(os.path.join(self.frontend_dir, "avatars", "assi.png")))

        bad_payload, bad_boundary = self._multipart_body("avatar", "assi.gif", b"gif")
        bad_req = urllib.request.Request(
            f"{base_url}/agents/assi/avatar",
            data=bad_payload,
            headers={"Content-Type": f"multipart/form-data; boundary={bad_boundary}"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(bad_req, timeout=5)
        self.assertEqual(exc_info.exception.code, 400)
        err = json.loads(exc_info.exception.read().decode("utf-8"))
        self.assertEqual(err["error"], "unsupported format '.gif'. Allowed: png, jpg, jpeg, webp")


if __name__ == "__main__":
    unittest.main()
