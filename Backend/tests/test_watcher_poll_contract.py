import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWatcherPollContract(unittest.TestCase):
    def _mod(self):
        import bridge_watcher  # type: ignore

        return bridge_watcher

    def test_agent_has_pollable_task_work_true_for_acked_tasks(self):
        mod = self._mod()

        def fake_http_get_json(url, timeout=0.0, headers=None):
            del timeout, headers
            if "state=acked" in url:
                return {"count": 1, "tasks": [{"task_id": "t-acked"}]}
            if "state=created" in url:
                return {"count": 0, "tasks": []}
            raise AssertionError(url)

        with patch.object(mod, "http_get_json", side_effect=fake_http_get_json):
            self.assertTrue(mod._agent_has_pollable_task_work("codex"))

    def test_agent_has_pollable_task_work_true_for_claimable_created_task(self):
        mod = self._mod()

        def fake_http_get_json(url, timeout=0.0, headers=None):
            del timeout, headers
            if "state=acked" in url:
                return {"count": 0, "tasks": []}
            if "state=created" in url:
                return {
                    "count": 2,
                    "tasks": [
                        {"task_id": "t1", "_claimability": {"claimable": False}},
                        {"task_id": "t2", "_claimability": {"claimable": True}},
                    ],
                }
            raise AssertionError(url)

        with patch.object(mod, "http_get_json", side_effect=fake_http_get_json):
            self.assertTrue(mod._agent_has_pollable_task_work("codex"))

    def test_agent_has_pollable_task_work_false_without_backlog(self):
        mod = self._mod()

        def fake_http_get_json(url, timeout=0.0, headers=None):
            del timeout, headers
            if "state=acked" in url:
                return {"count": 0, "tasks": []}
            if "state=created" in url:
                return {
                    "count": 2,
                    "tasks": [
                        {"task_id": "t1", "_claimability": {"claimable": False}},
                        {"task_id": "t2", "_claimability": {"claimable": False}},
                    ],
                }
            raise AssertionError(url)

        with patch.object(mod, "http_get_json", side_effect=fake_http_get_json):
            self.assertFalse(mod._agent_has_pollable_task_work("codex"))

    def test_agent_has_pollable_task_work_fails_open_on_probe_error(self):
        mod = self._mod()

        with patch.object(mod, "http_get_json", side_effect=RuntimeError("probe down")):
            self.assertTrue(mod._agent_has_pollable_task_work("codex"))


if __name__ == "__main__":
    unittest.main()
