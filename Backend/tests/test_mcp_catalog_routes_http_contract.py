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
import handlers.mcp_catalog_routes as routes_mod  # noqa: E402


class TestMcpCatalogRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="mcp_catalog_routes_http_contract_")
        self._templates_path = os.path.join(self._tmpdir, "industry_templates.json")
        with open(self._templates_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "version": 3,
                    "templates": {
                        "platform": {"name": "Platform Ops", "description": "Agent infrastructure"},
                        "sales": {"name": "Sales Ops", "description": "Lead follow-up"},
                    },
                },
                handle,
            )
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        self.registered: list[tuple[str, dict]] = []
        self.events: list[tuple[str, dict]] = []
        routes_mod.init(
            runtime_mcp_registry_fn=lambda: [{"name": "bridge", "transport": "stdio"}],
            industry_templates_path=self._templates_path,
            register_runtime_server_fn=self._register_runtime_server,
            rbac_platform_operators_getter=lambda: {"ordo", "buddy"},
            ws_broadcast_fn=self._broadcast,
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        routes_mod.init(
            runtime_mcp_registry_fn=srv.mcp_catalog.runtime_mcp_registry,
            industry_templates_path=os.path.join(srv.ROOT_DIR, "config", "industry_templates.json"),
            register_runtime_server_fn=srv.mcp_catalog.register_runtime_server,
            rbac_platform_operators_getter=lambda: set(srv._RBAC_PLATFORM_OPERATORS),
            ws_broadcast_fn=srv.ws_broadcast,
        )
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _register_runtime_server(self, name: str, spec: dict) -> list[dict]:
        self.registered.append((name, dict(spec)))
        return [{"name": name, **spec}]

    def _broadcast(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))

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

    def _get(self, base_url: str, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _post(self, base_url: str, path: str, body: dict, *, agent: str) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Bridge-Agent": agent},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_catalog_and_templates_http(self) -> None:
        base_url = self._start_server()
        status_catalog, body_catalog = self._get(base_url, "/mcp-catalog")
        self.assertEqual(status_catalog, 200)
        self.assertEqual(body_catalog["count"], 1)

        status_templates, body_templates = self._get(base_url, "/industry-templates?q=platform")
        self.assertEqual(status_templates, 200)
        self.assertEqual(body_templates["count"], 1)
        self.assertIn("platform", body_templates["templates"])

        status_post, body_post = self._post(
            base_url,
            "/mcp-catalog",
            {"name": "slice105", "spec": {"transport": "stdio", "command": "echo"}},
            agent="ordo",
        )
        self.assertEqual(status_post, 201)
        self.assertEqual(body_post["name"], "slice105")
        self.assertEqual(self.registered, [("slice105", {"transport": "stdio", "command": "echo"})])
        self.assertEqual(self.events[-1][0], "mcp_registered")

        bad_req = urllib.request.Request(
            f"{base_url}/mcp-catalog",
            data=json.dumps({"name": "slice105", "spec": {"transport": "stdio"}}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Bridge-Agent": "codex"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(bad_req, timeout=5)
        self.assertEqual(exc_info.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
