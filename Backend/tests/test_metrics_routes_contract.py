from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.metrics_routes as routes_mod  # noqa: E402


class _DummyHandler:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.body: dict | None = None
        self.responses: list[tuple[int, dict]] = []

    def _respond(self, status: int, body: dict) -> None:
        self.responses.append((status, body))

    def _parse_json_body(self) -> dict | None:
        return self.body


class TestMetricsRoutesContract(unittest.TestCase):
    def setUp(self) -> None:
        routes_mod.init(
            get_token_metrics_fn=lambda **kwargs: {"kind": "tokens", **kwargs},
            get_cost_summary_fn=lambda **kwargs: {"kind": "costs", **kwargs},
            model_prices_fn=lambda: {"gpt-test": {"input": 1, "output": 2}},
            log_usage_fn=lambda **kwargs: {"kind": "usage", **kwargs},
        )

    def test_metrics_read_routes(self) -> None:
        token_handler = _DummyHandler()
        self.assertTrue(
            routes_mod.handle_get(
                token_handler,
                "/metrics/tokens",
                {"agent_id": ["codex"], "period": ["month"]},
            )
        )
        self.assertEqual(token_handler.responses[0][1]["kind"], "tokens")
        self.assertEqual(token_handler.responses[0][1]["period"], "month")

        cost_handler = _DummyHandler()
        self.assertTrue(
            routes_mod.handle_get(
                cost_handler,
                "/metrics/costs",
                {"period": ["bogus"]},
            )
        )
        self.assertEqual(cost_handler.responses[0][1]["kind"], "costs")
        self.assertEqual(cost_handler.responses[0][1]["period"], "today")

        price_handler = _DummyHandler()
        self.assertTrue(routes_mod.handle_get(price_handler, "/metrics/prices", {}))
        self.assertIn("gpt-test", price_handler.responses[0][1]["prices"])

    def test_server_uses_extracted_metrics_handlers(self) -> None:
        self.assertIs(srv._handle_metrics_get, routes_mod.handle_get)
        self.assertIs(srv._handle_metrics_post, routes_mod.handle_post)

    def test_metrics_token_write_route(self) -> None:
        handler = _DummyHandler()
        handler.headers = {"X-Bridge-Agent": "codex"}
        handler.body = {
            "engine": "codex",
            "model": "gpt-test",
            "input_tokens": 12,
            "output_tokens": 3,
            "cached_tokens": 1,
        }

        self.assertTrue(routes_mod.handle_post(handler, "/metrics/tokens"))
        self.assertEqual(handler.responses[0][0], 201)
        self.assertEqual(handler.responses[0][1]["entry"]["agent_id"], "codex")
        self.assertEqual(handler.responses[0][1]["entry"]["kind"], "usage")

    def test_metrics_token_write_rejects_invalid_counts(self) -> None:
        handler = _DummyHandler()
        handler.body = {"input_tokens": -1}

        self.assertTrue(routes_mod.handle_post(handler, "/metrics/tokens"))
        self.assertEqual(handler.responses[0][0], 400)


if __name__ == "__main__":
    unittest.main()
