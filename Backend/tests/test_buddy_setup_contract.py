from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import handlers.agents as agents_mod  # noqa: E402
import handlers.cli as cli_mod  # noqa: E402


class TestCliDetectSetupContract(unittest.TestCase):
    def test_detect_cli_setup_state_uses_official_probe_results_and_legacy_tools_map(self):
        fake_paths = {
            "claude": "/usr/bin/claude",
            "codex": "/usr/bin/codex",
            "gemini": "",
            "qwen": "/usr/bin/qwen",
        }

        def fake_which(binary: str) -> str | None:
            return fake_paths.get(binary) or None

        def fake_probe(cli_name: str, binary_path: str) -> dict[str, str]:
            self.assertEqual(fake_paths[cli_name], binary_path)
            if cli_name == "claude":
                return {"status": "authenticated", "probe": "claude auth status", "note": "claude@example.com"}
            if cli_name == "codex":
                return {"status": "authenticated", "probe": "codex login status", "note": "Logged in using ChatGPT"}
            return {"status": "unknown", "probe": "", "note": "No verified non-interactive auth probe configured"}

        def fake_runtime_probe(cli_name: str, binary_path: str) -> dict[str, str]:
            self.assertEqual(fake_paths[cli_name], binary_path)
            if cli_name == "claude":
                return {"status": "usage_limit_reached", "probe": "claude -p ok --output-format text", "note": "You've hit your limit"}
            if cli_name == "codex":
                return {"status": "ready", "probe": "codex exec", "note": "What do you want to do in `/tmp`?"}
            return {"status": "unknown", "probe": "", "note": "No verified non-interactive runtime probe configured"}

        with mock.patch("shutil.which", side_effect=fake_which), mock.patch.object(
            cli_mod,
            "_probe_cli_auth_status",
            side_effect=fake_probe,
        ), mock.patch.object(
            cli_mod,
            "_probe_cli_runtime_status",
            side_effect=fake_runtime_probe,
        ), mock.patch.dict(os.environ, {}, clear=False):
            result = srv._detect_cli_setup_state()

        self.assertEqual(result["tools"]["claude"], True)
        self.assertEqual(result["tools"]["codex"], True)
        self.assertEqual(result["tools"]["gemini"], False)
        self.assertEqual(result["tools"]["qwen"], True)
        self.assertEqual(result["cli"]["available"], ["claude", "codex", "qwen"])
        self.assertEqual(result["cli"]["authenticated"], ["claude", "codex"])
        self.assertEqual(result["cli"]["unauthenticated"], [])
        self.assertEqual(result["cli"]["unknown_auth"], ["qwen"])
        self.assertEqual(result["cli"]["ready"], ["codex"])
        self.assertEqual(result["cli"]["usage_limited"], ["claude"])
        self.assertEqual(result["cli"]["unknown_runtime"], ["qwen"])
        self.assertEqual(result["cli"]["recommended"], "codex")
        doc_map = {entry["id"]: entry["doc_filename"] for entry in result["cli"]["entries"]}
        self.assertEqual(doc_map["claude"], "CLAUDE.md")
        self.assertEqual(doc_map["codex"], "AGENTS.md")
        self.assertEqual(doc_map["qwen"], "QWEN.md")

    def test_detect_cli_setup_state_can_skip_runtime_probes_for_fast_frontdoor(self):
        fake_paths = {
            "claude": "/usr/bin/claude",
            "codex": "/usr/bin/codex",
            "gemini": "",
            "qwen": "",
        }

        def fake_which(binary: str) -> str | None:
            return fake_paths.get(binary) or None

        def fake_probe(cli_name: str, binary_path: str) -> dict[str, str]:
            self.assertEqual(fake_paths[cli_name], binary_path)
            if cli_name == "codex":
                return {"status": "authenticated", "probe": "codex login status", "note": "Logged in using ChatGPT"}
            return {"status": "unknown", "probe": "", "note": "No verified non-interactive auth probe configured"}

        with mock.patch("shutil.which", side_effect=fake_which), mock.patch.object(
            cli_mod,
            "_probe_cli_auth_status",
            side_effect=fake_probe,
        ), mock.patch.object(
            cli_mod,
            "_probe_cli_runtime_status",
            side_effect=AssertionError("runtime probe must be skipped"),
        ) as runtime_probe, mock.patch.dict(os.environ, {}, clear=False):
            result = srv._detect_cli_setup_state(include_runtime_probes=False)

        runtime_probe.assert_not_called()
        self.assertEqual(result["cli"]["available"], ["claude", "codex"])
        self.assertEqual(result["cli"]["authenticated"], ["codex"])
        self.assertEqual(result["cli"]["unknown_auth"], ["claude"])
        self.assertEqual(result["cli"]["unknown_runtime"], ["claude", "codex"])
        self.assertEqual(result["cli"]["recommended"], "codex")
        runtime_notes = {
            entry["id"]: entry["runtime_note"]
            for entry in result["cli"]["entries"]
            if entry["available"]
        }
        self.assertEqual(runtime_notes["claude"], "Runtime probe skipped for fast detect")
        self.assertEqual(runtime_notes["codex"], "Runtime probe skipped for fast detect")


class TestBuddySetupHomeMaterialization(unittest.TestCase):
    def test_materialize_agent_setup_home_writes_buddy_guide_and_engine_wrappers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = srv._materialize_agent_setup_home(
                "buddy",
                {"id": "buddy", "name": "Buddy", "home_dir": tmpdir},
                engine="codex",
                overwrite=True,
            )

            self.assertTrue(result["guide_path"].endswith("BRIDGE_OPERATOR_GUIDE.md"))
            self.assertTrue(os.path.isfile(result["guide_path"]))
            self.assertTrue(result["instruction_path"].endswith("AGENTS.md"))

            for filename in ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "QWEN.md"):
                path = os.path.join(tmpdir, filename)
                self.assertTrue(os.path.isfile(path), path)
                raw = open(path, encoding="utf-8").read()
                self.assertIn("BRIDGE_OPERATOR_GUIDE.md", raw)
                self.assertIn("SOUL.md", raw)

            guide_raw = open(result["guide_path"], encoding="utf-8").read()
            self.assertIn("Bridge Operator Guide", guide_raw)
            self.assertIn("GET /cli/detect", guide_raw)
            self.assertIn("POST /agents/{id}/setup-home", guide_raw)


class TestCliDetectCaching(unittest.TestCase):
    def setUp(self):
        self._orig_cache = dict(cli_mod._CLI_SETUP_STATE_CACHE)
        self._orig_cache_at = dict(cli_mod._CLI_SETUP_STATE_CACHE_AT)
        self._orig_inflight = dict(cli_mod._CLI_SETUP_STATE_INFLIGHT)
        cli_mod._CLI_SETUP_STATE_CACHE = {}
        cli_mod._CLI_SETUP_STATE_CACHE_AT = {}
        cli_mod._CLI_SETUP_STATE_INFLIGHT = {}

    def tearDown(self):
        cli_mod._CLI_SETUP_STATE_CACHE = self._orig_cache
        cli_mod._CLI_SETUP_STATE_CACHE_AT = self._orig_cache_at
        cli_mod._CLI_SETUP_STATE_INFLIGHT = self._orig_inflight

    def test_get_cli_setup_state_cached_reuses_recent_payload(self):
        calls = []

        def fake_detect(*, include_runtime_probes: bool = True):
            calls.append(include_runtime_probes)
            return {"cli": {"recommended": "codex", "ready": ["codex"]}}

        with mock.patch.object(cli_mod, "_detect_cli_setup_state", side_effect=fake_detect):
            first = srv._get_cli_setup_state_cached(include_runtime_probes=True)
            second = srv._get_cli_setup_state_cached(include_runtime_probes=True)

        self.assertEqual(first["cli"]["recommended"], "codex")
        self.assertEqual(second["cli"]["recommended"], "codex")
        self.assertEqual(calls, [True])

    def test_get_cli_setup_state_cached_separates_fast_and_full_probe_modes(self):
        calls = []

        def fake_detect(*, include_runtime_probes: bool = True):
            calls.append(include_runtime_probes)
            return {
                "cli": {
                    "recommended": "codex" if include_runtime_probes else "claude",
                    "ready": ["codex"] if include_runtime_probes else [],
                }
            }

        with mock.patch.object(cli_mod, "_detect_cli_setup_state", side_effect=fake_detect):
            fast = srv._get_cli_setup_state_cached(include_runtime_probes=False)
            full = srv._get_cli_setup_state_cached(include_runtime_probes=True)

        self.assertEqual(fast["cli"]["recommended"], "claude")
        self.assertEqual(full["cli"]["recommended"], "codex")
        self.assertEqual(calls, [False, True])


class TestBuddySetupHomeEndpoint(unittest.TestCase):
    def setUp(self):
        self._orig_team_config = srv.TEAM_CONFIG
        self._orig_tokens = dict(srv.SESSION_TOKENS)
        self._orig_atomic_write = srv._atomic_write_team_json
        self._orig_sync = srv._sync_agent_persistent_cli_config
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def tearDown(self):
        srv.TEAM_CONFIG = self._orig_team_config
        srv.SESSION_TOKENS.clear()
        srv.SESSION_TOKENS.update(self._orig_tokens)
        srv._atomic_write_team_json = self._orig_atomic_write
        srv._sync_agent_persistent_cli_config = self._orig_sync
        self._reinit_agents()

    def _start_server(self) -> str:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.BridgeHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 1)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def _reinit_agents(self) -> None:
        agents_mod.init(
            registered_agents=srv.REGISTERED_AGENTS,
            agent_last_seen=srv.AGENT_LAST_SEEN,
            agent_busy=srv.AGENT_BUSY,
            session_tokens=srv.SESSION_TOKENS,
            agent_tokens=srv.AGENT_TOKENS,
            agent_state_lock=srv.AGENT_STATE_LOCK,
            tasks=srv.TASKS,
            task_lock=srv.TASK_LOCK,
            team_config=srv.TEAM_CONFIG,
            team_config_lock=srv.TEAM_CONFIG_LOCK,
            team_config_getter_fn=lambda: srv.TEAM_CONFIG,
            frontend_dir=srv.FRONTEND_DIR,
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
            atomic_write_team_json_fn=lambda: srv._atomic_write_team_json(),
            setup_cli_binaries=srv._SETUP_CLI_BINARIES,
            materialize_agent_setup_home_fn=lambda *args, **kwargs: srv._materialize_agent_setup_home(*args, **kwargs),
            sync_agent_persistent_cli_config_fn=lambda aid, entry: srv._sync_agent_persistent_cli_config(aid, entry),
            root_dir=srv.ROOT_DIR,
            bridge_port=srv.PORT,
            create_agent_session_fn=srv.create_agent_session,
            kill_agent_session_fn=srv.kill_agent_session,
            is_session_alive_fn=srv.is_session_alive,
        )

    def test_platform_operator_can_materialize_buddy_home_and_switch_engine(self):
        buddy_home = os.path.join(self._tmpdir.name, "Buddy")
        os.makedirs(buddy_home, exist_ok=True)
        srv.TEAM_CONFIG = {
            "agents": [
                {
                    "id": "buddy",
                    "name": "Buddy",
                    "role": "concierge",
                    "description": "Buddy frontdoor",
                    "engine": "claude",
                    "home_dir": buddy_home,
                    "agent_md": "",
                }
            ]
        }
        srv.SESSION_TOKENS["buddy-token"] = "buddy"
        srv._atomic_write_team_json = lambda: None
        sync_calls: list[tuple[str, str]] = []
        srv._sync_agent_persistent_cli_config = lambda aid, entry: sync_calls.append((aid, entry["engine"]))
        self._reinit_agents()

        base_url = self._start_server()
        req = urllib.request.Request(
            f"{base_url}/agents/buddy/setup-home",
            data=json.dumps({"engine": "gemini", "overwrite": True}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Bridge-Token": "buddy-token"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(resp.status, 200)
        self.assertEqual(payload["engine"], "gemini")
        self.assertTrue(payload["agent_md"].endswith("GEMINI.md"))
        self.assertTrue(os.path.isfile(os.path.join(buddy_home, "BRIDGE_OPERATOR_GUIDE.md")))
        self.assertTrue(os.path.isfile(os.path.join(buddy_home, "GEMINI.md")))
        self.assertEqual(srv.TEAM_CONFIG["agents"][0]["engine"], "gemini")
        self.assertEqual(sync_calls, [("buddy", "gemini")])


if __name__ == "__main__":
    unittest.main()
