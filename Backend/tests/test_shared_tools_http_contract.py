from __future__ import annotations

import json
import os
import shutil
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

import server as srv  # noqa: E402
import tool_store  # noqa: E402


class TestSharedToolsHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="shared_tools_http_contract_")
        self._orig_shared_tools_dir = tool_store.SHARED_TOOLS_DIR
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        self._orig_session_tokens = dict(srv.SESSION_TOKENS)
        self._orig_team_config = srv.TEAM_CONFIG

        tool_store.SHARED_TOOLS_DIR = os.path.join(self._tmpdir, "shared_tools")
        os.makedirs(tool_store.SHARED_TOOLS_DIR, exist_ok=True)
        tool_store.scan_tools(force=True)
        srv.BRIDGE_STRICT_AUTH = False
        srv.SESSION_TOKENS.clear()
        srv.TEAM_CONFIG = {
            "agents": [
                {"id": "manager", "level": 1, "active": True},
                {"id": "codex", "level": 3, "active": True},
            ]
        }

    def tearDown(self) -> None:
        tool_store.SHARED_TOOLS_DIR = self._orig_shared_tools_dir
        tool_store.scan_tools(force=True)
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        srv.SESSION_TOKENS.clear()
        srv.SESSION_TOKENS.update(self._orig_session_tokens)
        srv.TEAM_CONFIG = self._orig_team_config
        shutil.rmtree(self._tmpdir, ignore_errors=True)

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

    def _get(self, base_url: str, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", headers=headers or {}, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _post(self, base_url: str, path: str, payload: dict, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _delete(self, base_url: str, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", headers=headers or {}, method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_tools_register_list_detail_execute_and_delete_endpoints(self) -> None:
        base_url = self._start_server()
        tool_name = "slice60_http_tool"
        tool_code = """
TOOL_META = {
    "name": "slice60_http_tool",
    "description": "HTTP contract probe tool",
    "author_agent": "user",
    "version": "1.0.0",
    "created_at": "2026-03-15T00:00:00+00:00",
}
TOOL_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
}
def execute(**kwargs):
    return {"echo": kwargs.get("value", ""), "ok": True}
""".strip()

        status_register, body_register = self._post(
            base_url,
            "/tools/register",
            {"name": tool_name, "code": tool_code},
            headers={"X-Bridge-Agent": "user"},
        )
        self.assertEqual(status_register, 201)
        self.assertTrue(body_register["ok"])
        self.assertEqual(body_register["tool"]["name"], tool_name)

        status_list, body_list = self._get(base_url, "/tools")
        self.assertEqual(status_list, 200)
        self.assertEqual(body_list["count"], 1)
        self.assertEqual(body_list["tools"][0]["name"], tool_name)

        status_detail, body_detail = self._get(base_url, f"/tools/{tool_name}")
        self.assertEqual(status_detail, 200)
        self.assertEqual(body_detail["name"], tool_name)
        self.assertEqual(body_detail["author_agent"], "user")

        status_execute, body_execute = self._post(
            base_url,
            f"/tools/{tool_name}/execute",
            {"input": {"value": "hello"}},
            headers={"X-Bridge-Agent": "user"},
        )
        self.assertEqual(status_execute, 200)
        self.assertTrue(body_execute["ok"])
        self.assertEqual(body_execute["result"]["echo"], "hello")

        status_delete, body_delete = self._delete(
            base_url,
            f"/tools/{tool_name}",
            headers={"X-Bridge-Agent": "user"},
        )
        self.assertEqual(status_delete, 200)
        self.assertTrue(body_delete["ok"])
        self.assertEqual(body_delete["deleted"], tool_name)

        with self.assertRaises(urllib.error.HTTPError) as missing_again:
            self._get(base_url, f"/tools/{tool_name}")
        self.assertEqual(missing_again.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
