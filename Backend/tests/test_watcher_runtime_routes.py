from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bridge_watcher as watcher  # noqa: E402


class TestWatcherRuntimeRoutes(unittest.TestCase):
    def test_merge_registered_agent_routes_adds_runtime_only_agent_bidirectionally(self) -> None:
        base_routes = {
            "user": {"alpha"},
            "alpha": {"user"},
            "beta": {"user"},
        }

        merged = watcher._merge_registered_agent_routes(
            base_routes,
            {"alpha", "beta", "runtime_conductor"},
        )

        self.assertIn("runtime_conductor", merged["user"])
        self.assertIn("runtime_conductor", merged["alpha"])
        self.assertIn("runtime_conductor", merged["beta"])
        self.assertIn("alpha", merged["runtime_conductor"])
        self.assertIn("beta", merged["runtime_conductor"])
        self.assertIn("user", merged["runtime_conductor"])

    def test_merge_registered_agent_routes_ignores_reserved_targets(self) -> None:
        merged = watcher._merge_registered_agent_routes(
            {"user": {"alpha"}, "alpha": {"user"}},
            {"user", "system", "ui", "alpha"},
        )

        self.assertNotIn("system", merged)
        self.assertNotIn("ui", merged)
        self.assertNotIn("system", merged["alpha"])
        self.assertNotIn("ui", merged["alpha"])

    def test_watcher_sender_is_treated_like_system_for_delivery_errors(self) -> None:
        original = watcher.ALLOWED_ROUTES
        try:
            watcher.ALLOWED_ROUTES = {"alpha": {"user"}}
            self.assertTrue(watcher._is_route_allowed("watcher", "alpha"))
        finally:
            watcher.ALLOWED_ROUTES = original


if __name__ == "__main__":
    unittest.main()
