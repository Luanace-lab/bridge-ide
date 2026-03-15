from __future__ import annotations

import copy
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.runtime as _hr  # noqa: E402


class TestRuntimeConfigureContract(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_strict_auth = srv.BRIDGE_STRICT_AUTH
        self._orig_open_agent_sessions = srv.open_agent_sessions
        self._orig_stop_known_agents = srv.stop_known_agents
        self._orig_wait_for_agent_registration = srv._wait_for_agent_registration
        self._orig_is_session_alive = srv.is_session_alive
        self._orig_collect_runtime_registration_failures = srv._collect_runtime_registration_failures
        self._orig_persist_runtime_overlay = srv._persist_runtime_overlay
        self._orig_reset_team_lead_state = srv.reset_team_lead_state
        self._orig_ws_broadcast = srv.ws_broadcast
        self._orig_current_runtime_overlay = srv._current_runtime_overlay
        self._hr_orig_persist_runtime_overlay = _hr._persist_runtime_overlay
        self._hr_orig_reset_team_lead_state = _hr.reset_team_lead_state
        self._hr_orig_current_runtime_overlay = _hr._current_runtime_overlay
        self._orig_runtime = copy.deepcopy(srv.RUNTIME)
        self._orig_registered_agents = copy.deepcopy(srv.REGISTERED_AGENTS)
        self._orig_agent_last_seen = copy.deepcopy(srv.AGENT_LAST_SEEN)
        self._orig_agent_busy = copy.deepcopy(srv.AGENT_BUSY)
        self._orig_prev_agent_status = copy.deepcopy(srv._PREV_AGENT_STATUS)

        srv.BRIDGE_STRICT_AUTH = False
        srv._current_runtime_overlay = lambda: None
        _hr._current_runtime_overlay = lambda: None
        self.persist_calls: list[object] = []
        self.team_lead_reasons: list[str] = []
        self.broadcasts: list[tuple[str, dict]] = []
        srv._persist_runtime_overlay = lambda overlay: self.persist_calls.append(overlay)
        _hr._persist_runtime_overlay = lambda overlay: self.persist_calls.append(overlay)
        srv.reset_team_lead_state = lambda reason="": self.team_lead_reasons.append(reason)
        _hr.reset_team_lead_state = lambda reason="": self.team_lead_reasons.append(reason)
        srv.ws_broadcast = lambda event, payload: self.broadcasts.append((event, payload))
        srv.stop_known_agents = lambda: []
        srv._wait_for_agent_registration = lambda agent_ids, timeout_seconds: True
        srv.is_session_alive = lambda _agent_id: True
        srv._collect_runtime_registration_failures = lambda agent_ids, missing, dead: []
        srv.RUNTIME.update({
            "project_name": "stale-runtime",
            "project_path": REPO_ROOT,
            "agent_profiles": [{"id": "stale", "slot": "a", "engine": "codex"}],
            "runtime_specs": [{"id": "stale", "slot": "a", "engine": "codex", "peer": ""}],
            "runtime_overlay": {"active": True},
            "last_start_at": "2026-03-11T00:00:00+00:00",
        })
        srv.REGISTERED_AGENTS.clear()
        srv.AGENT_LAST_SEEN.clear()
        srv.AGENT_BUSY.clear()
        srv._PREV_AGENT_STATUS.clear()

    def tearDown(self) -> None:
        srv.BRIDGE_STRICT_AUTH = self._orig_strict_auth
        srv.open_agent_sessions = self._orig_open_agent_sessions
        srv.stop_known_agents = self._orig_stop_known_agents
        srv._wait_for_agent_registration = self._orig_wait_for_agent_registration
        srv.is_session_alive = self._orig_is_session_alive
        srv._collect_runtime_registration_failures = self._orig_collect_runtime_registration_failures
        srv._persist_runtime_overlay = self._orig_persist_runtime_overlay
        srv.reset_team_lead_state = self._orig_reset_team_lead_state
        srv.ws_broadcast = self._orig_ws_broadcast
        srv._current_runtime_overlay = self._orig_current_runtime_overlay
        _hr._persist_runtime_overlay = self._hr_orig_persist_runtime_overlay
        _hr.reset_team_lead_state = self._hr_orig_reset_team_lead_state
        _hr._current_runtime_overlay = self._hr_orig_current_runtime_overlay
        srv.RUNTIME.clear()
        srv.RUNTIME.update(copy.deepcopy(self._orig_runtime))
        srv.REGISTERED_AGENTS.clear()
        srv.REGISTERED_AGENTS.update(copy.deepcopy(self._orig_registered_agents))
        srv.AGENT_LAST_SEEN.clear()
        srv.AGENT_LAST_SEEN.update(copy.deepcopy(self._orig_agent_last_seen))
        srv.AGENT_BUSY.clear()
        srv.AGENT_BUSY.update(copy.deepcopy(self._orig_agent_busy))
        srv._PREV_AGENT_STATUS.clear()
        srv._PREV_AGENT_STATUS.update(copy.deepcopy(self._orig_prev_agent_status))

    def _start_server(self) -> str:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _post(self, base_url: str, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _get(self, base_url: str, path: str) -> tuple[int, dict]:
        with urllib.request.urlopen(f"{base_url}{path}", timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_runtime_configure_fails_closed_when_any_runtime_agent_fails_to_start(self) -> None:
        srv.open_agent_sessions = lambda _config: [
            {"id": "codex", "alive": True, "engine": "codex"},
            {"id": "claude", "alive": False, "engine": "claude"},
        ]

        base_url = self._start_server()

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self._post(base_url, "/runtime/configure", {"project_path": REPO_ROOT})

        self.assertEqual(raised.exception.code, 500)
        body = json.loads(raised.exception.read().decode("utf-8"))
        self.assertIn("failed to start runtime agents", body["error"])
        self.assertEqual(body["runtime"]["configured"], False)
        self.assertEqual(self.persist_calls, [None])
        self.assertEqual(self.team_lead_reasons, ["runtime_configure_failed"])

        status, runtime_body = self._get(base_url, "/runtime")
        self.assertEqual(status, 200)
        self.assertFalse(runtime_body["configured"])
        self.assertEqual(runtime_body["project_name"], "")
        self.assertEqual(runtime_body["agent_profiles"], [])

    def test_runtime_configure_fails_closed_when_agents_do_not_register(self) -> None:
        srv.open_agent_sessions = lambda _config: [
            {"id": "codex", "alive": True, "engine": "codex"},
            {"id": "claude", "alive": True, "engine": "claude"},
        ]
        srv._wait_for_agent_registration = lambda agent_ids, timeout_seconds: False

        base_url = self._start_server()

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self._post(base_url, "/runtime/configure", {"project_path": REPO_ROOT})

        self.assertEqual(raised.exception.code, 500)
        body = json.loads(raised.exception.read().decode("utf-8"))
        self.assertIn("runtime agents failed to stabilize", body["error"])
        self.assertEqual(sorted(body["missing_registrations"]), ["claude", "codex"])
        self.assertEqual(body["dead_sessions"], [])
        self.assertEqual(body["runtime"]["configured"], False)

        status, runtime_body = self._get(base_url, "/runtime")
        self.assertEqual(status, 200)
        self.assertFalse(runtime_body["configured"])
        self.assertEqual(runtime_body["project_name"], "")
        self.assertEqual(runtime_body["runtime_specs"], [])

    def test_runtime_configure_projects_manual_setup_required_for_unregistered_agent(self) -> None:
        srv.open_agent_sessions = lambda _config: [
            {"id": "codex", "alive": True, "engine": "codex"},
            {"id": "claude", "alive": True, "engine": "claude"},
        ]
        srv._wait_for_agent_registration = lambda agent_ids, timeout_seconds: False
        srv.is_session_alive = lambda agent_id: agent_id == "claude"
        srv._collect_runtime_registration_failures = lambda agent_ids, missing, dead: [
            {
                "id": "claude",
                "engine": "claude",
                "error_stage": "interactive_setup",
                "error_reason": "manual_setup_required",
                "error_detail": "Claude Code first-run setup requires a manual theme selection in the session.",
            }
        ]

        base_url = self._start_server()

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self._post(base_url, "/runtime/configure", {"project_path": REPO_ROOT})

        self.assertEqual(raised.exception.code, 500)
        body = json.loads(raised.exception.read().decode("utf-8"))
        failed = {item["id"]: item for item in body["failed"]}
        self.assertEqual(failed["claude"]["error_reason"], "manual_setup_required")
        self.assertIn("theme selection", failed["claude"]["error_detail"])
        self.assertEqual(body["dead_sessions"], ["codex"])

    def test_runtime_configure_projects_usage_limit_for_unregistered_agent(self) -> None:
        srv.open_agent_sessions = lambda _config: [
            {"id": "codex", "alive": True, "engine": "codex"},
            {"id": "claude", "alive": True, "engine": "claude"},
        ]
        srv._wait_for_agent_registration = lambda agent_ids, timeout_seconds: False
        srv.is_session_alive = lambda agent_id: agent_id == "claude"
        srv._collect_runtime_registration_failures = lambda agent_ids, missing, dead: [
            {
                "id": "claude",
                "engine": "claude",
                "error_stage": "runtime_stabilization",
                "error_reason": "usage_limit_reached",
                "error_detail": "You've hit your limit · resets Mar 16, 2am (Europe/Berlin)",
            }
        ]

        base_url = self._start_server()

        with self.assertRaises(urllib.error.HTTPError) as raised:
            self._post(base_url, "/runtime/configure", {"project_path": REPO_ROOT})

        self.assertEqual(raised.exception.code, 500)
        body = json.loads(raised.exception.read().decode("utf-8"))
        failed = {item["id"]: item for item in body["failed"]}
        self.assertEqual(failed["claude"]["error_reason"], "usage_limit_reached")
        self.assertIn("You've hit your limit", failed["claude"]["error_detail"])
        self.assertEqual(body["dead_sessions"], ["codex"])

    def test_runtime_configure_uses_30s_default_stabilization_window(self) -> None:
        observed: list[float] = []

        def _open_sessions(_config):
            srv.REGISTERED_AGENTS["codex"] = {
                "registered_at": "2026-03-14T00:00:00+00:00",
                "last_heartbeat": 1.0,
                "last_heartbeat_iso": "2026-03-14T00:00:00+00:00",
            }
            srv.REGISTERED_AGENTS["claude"] = {
                "registered_at": "2026-03-14T00:00:00+00:00",
                "last_heartbeat": 1.0,
                "last_heartbeat_iso": "2026-03-14T00:00:00+00:00",
            }
            return [
                {"id": "codex", "alive": True, "engine": "codex"},
                {"id": "claude", "alive": True, "engine": "claude"},
            ]

        srv.open_agent_sessions = _open_sessions

        def _record_timeout(agent_ids, timeout_seconds):
            observed.append(timeout_seconds)
            return True

        srv._wait_for_agent_registration = _record_timeout

        base_url = self._start_server()
        status, body = self._post(base_url, "/runtime/configure", {"project_path": REPO_ROOT})

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(observed, [30.0])


if __name__ == "__main__":
    unittest.main()
