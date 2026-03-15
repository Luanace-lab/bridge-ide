from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
import unittest
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.meta_routes as meta_mod  # noqa: E402


class TestMetaRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_init_registry = srv._engine_model_registry
        self._orig_init_cli = srv._get_cli_setup_state_cached
        meta_mod.init(
            engine_model_registry_fn=lambda: {
                "codex": {"default_model": "gpt-5.3-codex"},
                "claude": {"default_model": "claude-opus-4.1"},
            },
            get_cli_setup_state_cached_fn=lambda *, force, include_runtime_probes: {
                "ok": True,
                "force": force,
                "include_runtime_probes": include_runtime_probes,
                "tools": [{"id": "codex", "authenticated": True}],
            },
        )

    def tearDown(self) -> None:
        meta_mod.init(
            engine_model_registry_fn=srv._engine_model_registry,
            get_cli_setup_state_cached_fn=srv._get_cli_setup_state_cached,
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

    def _get(self, base_url: str, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{base_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_engines_models_and_cli_detect_endpoints(self) -> None:
        base_url = self._start_server()

        status_models, body_models = self._get(base_url, "/engines/models")
        self.assertEqual(status_models, 200)
        self.assertEqual(body_models["engines"]["codex"]["default_model"], "gpt-5.3-codex")

        status_detect, body_detect = self._get(base_url, "/cli/detect?skip_runtime=1&force=1")
        self.assertEqual(status_detect, 200)
        self.assertTrue(body_detect["ok"])
        self.assertTrue(body_detect["force"])
        self.assertFalse(body_detect["include_runtime_probes"])
        self.assertEqual(body_detect["tools"][0]["id"], "codex")


if __name__ == "__main__":
    unittest.main()
