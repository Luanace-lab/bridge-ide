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
import handlers.metrics_routes as routes_mod  # noqa: E402


class TestMetricsRoutesHttpContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict = srv.BRIDGE_STRICT_AUTH
        srv.BRIDGE_STRICT_AUTH = False
        routes_mod.init(
            get_token_metrics_fn=lambda **kwargs: {"kind": "tokens", **kwargs},
            get_cost_summary_fn=lambda **kwargs: {"kind": "costs", **kwargs},
            model_prices_fn=lambda: {"gpt-test": {"input": 1, "output": 2}},
            log_usage_fn=lambda **kwargs: {"kind": "usage", **kwargs},
        )

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict
        routes_mod.init(
            get_token_metrics_fn=srv.token_tracker.get_token_metrics,
            get_cost_summary_fn=srv.token_tracker.get_cost_summary,
            model_prices_fn=lambda: srv.token_tracker.MODEL_PRICES,
            log_usage_fn=srv.token_tracker.log_usage,
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

    def _post(self, base_url: str, path: str, payload: dict, *, headers: dict[str, str] | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_metrics_read_routes_http(self) -> None:
        base_url = self._start_server()

        token_status, token_body = self._get(base_url, "/metrics/tokens?agent_id=codex&period=week")
        self.assertEqual(token_status, 200)
        self.assertEqual(token_body["kind"], "tokens")
        self.assertEqual(token_body["period"], "week")

        cost_status, cost_body = self._get(base_url, "/metrics/costs?period=bogus")
        self.assertEqual(cost_status, 200)
        self.assertEqual(cost_body["kind"], "costs")
        self.assertEqual(cost_body["period"], "today")

        price_status, price_body = self._get(base_url, "/metrics/prices")
        self.assertEqual(price_status, 200)
        self.assertIn("gpt-test", price_body["prices"])

    def test_metrics_write_route_http(self) -> None:
        base_url = self._start_server()

        status, body = self._post(
            base_url,
            "/metrics/tokens",
            {
                "engine": "codex",
                "model": "gpt-test",
                "input_tokens": 10,
                "output_tokens": 5,
                "cached_tokens": 2,
            },
            headers={"X-Bridge-Agent": "codex"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["entry"]["agent_id"], "codex")
        self.assertEqual(body["entry"]["kind"], "usage")


if __name__ == "__main__":
    unittest.main()
