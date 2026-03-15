from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import handlers.mcp_catalog_routes as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self):
        self.responses: list[tuple[int, dict]] = []
        self.headers: dict[str, str] = {}
        self._json_body: dict | None = None

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def _parse_json_body(self) -> dict | None:
        return self._json_body


class TestMcpCatalogRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="mcp_catalog_routes_contract_")
        self._templates_path = os.path.join(self._tmpdir, "industry_templates.json")
        with open(self._templates_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "version": 2,
                    "templates": {
                        "finance": {"name": "Finance Ops", "description": "Trading and audit"},
                        "marketing": {"name": "Marketing Ops", "description": "Campaign planning"},
                    },
                },
                handle,
            )
        routes_mod.init(
            runtime_mcp_registry_fn=lambda: [{"name": "bridge", "transport": "stdio"}],
            industry_templates_path=self._templates_path,
            register_runtime_server_fn=self._register_runtime_server,
            rbac_platform_operators_getter=lambda: {"ordo", "buddy"},
            ws_broadcast_fn=self._broadcast,
        )
        self.registered: list[tuple[str, dict]] = []
        self.events: list[tuple[str, dict]] = []

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _register_runtime_server(self, name: str, spec: dict) -> list[dict]:
        self.registered.append((name, dict(spec)))
        return [{"name": name, **spec}]

    def _broadcast(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))

    def test_catalog_and_template_queries(self) -> None:
        handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(handler, "/mcp-catalog", {}))
        self.assertEqual(handler.responses[-1][0], 200)
        self.assertEqual(handler.responses[-1][1]["count"], 1)

        self.assertTrue(routes_mod.handle_get(handler, "/industry-templates", {"q": ["marketing"]}))
        self.assertEqual(handler.responses[-1][0], 200)
        self.assertEqual(handler.responses[-1][1]["count"], 1)
        self.assertIn("marketing", handler.responses[-1][1]["templates"])

    def test_post_registers_runtime_server_for_platform_operator(self) -> None:
        handler = _DummyHandler()
        handler.headers["X-Bridge-Agent"] = "ordo"
        handler._json_body = {"name": "slice105", "spec": {"transport": "stdio", "command": "echo"}}
        self.assertTrue(routes_mod.handle_post(handler, "/mcp-catalog"))
        self.assertEqual(handler.responses[-1][0], 201)
        self.assertEqual(self.registered, [("slice105", {"transport": "stdio", "command": "echo"})])
        self.assertEqual(self.events[-1][0], "mcp_registered")

    def test_post_rejects_non_operator(self) -> None:
        handler = _DummyHandler()
        handler.headers["X-Bridge-Agent"] = "codex"
        handler._json_body = {"name": "slice105", "spec": {"transport": "stdio"}}
        self.assertTrue(routes_mod.handle_post(handler, "/mcp-catalog"))
        self.assertEqual(handler.responses[-1], (403, {"error": "insufficient permissions to register MCP servers"}))


if __name__ == "__main__":
    unittest.main()
