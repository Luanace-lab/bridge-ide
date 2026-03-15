from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import bridge_watcher as watcher  # noqa: E402
import execution_journal as journal  # noqa: E402


class TestContextBridgeWriter(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.home_dir = Path(self._tmpdir.name) / "agent-home"
        self.workspace = self.home_dir / ".agent_sessions" / "codex"
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _patch_common(self):
        return mock.patch.multiple(
            watcher,
            _get_agent_home_dir=mock.DEFAULT,
            _get_session_name=mock.DEFAULT,
            _capture_cli_session_log=mock.DEFAULT,
            _resolve_tmux_agent_id=mock.DEFAULT,
            _inject_dynamic_claude_block=mock.DEFAULT,
            _log_event=mock.DEFAULT,
            _flush=mock.DEFAULT,
            http_post_json=mock.DEFAULT,
        )

    def test_get_agent_home_dir_falls_back_to_live_agent_endpoint(self) -> None:
        original_cache = watcher._AGENT_META_CACHE
        original_stamps = watcher._AGENT_META_CACHE_STAMPS
        try:
            watcher._AGENT_META_CACHE = {}
            watcher._AGENT_META_CACHE_STAMPS = (
                os.path.getmtime(watcher.AGENTS_CONF) if os.path.exists(watcher.AGENTS_CONF) else 0.0,
                os.path.getmtime(watcher._TEAM_JSON_PATH) if os.path.exists(watcher._TEAM_JSON_PATH) else 0.0,
                os.path.getmtime(watcher._RUNTIME_TEAM_PATH) if os.path.exists(watcher._RUNTIME_TEAM_PATH) else 0.0,
            )
            with mock.patch.object(
                watcher,
                "http_get_json",
                return_value={
                    "home_dir": str(self.workspace),
                    "workspace": str(self.workspace),
                    "project_root": str(self.home_dir),
                },
                ) as fake_get:
                resolved = watcher._get_agent_home_dir("codex")
        finally:
            watcher._AGENT_META_CACHE = original_cache
            watcher._AGENT_META_CACHE_STAMPS = original_stamps

        self.assertEqual(resolved, str(self.workspace))
        fake_get.assert_called_once()

    def test_write_context_bridge_renders_status_messages_and_tasks(self) -> None:
        recent_messages = [
            {
                "timestamp": f"2026-03-11T01:0{i}:00Z",
                "from": "user" if i % 2 == 0 else "codex",
                "to": "codex" if i % 2 == 0 else "viktor",
                "content": f"msg-{i}",
            }
            for i in range(6)
        ]

        def fake_get(
            url: str,
            timeout: float = 5.0,
            headers: dict[str, str] | None = None,
        ) -> dict[str, object]:
            if url.endswith("/health"):
                return {"status": "degraded"}
            if url.endswith("/agents/codex"):
                return {
                    "agent_id": "codex",
                    "role": "Audit Agent",
                    "mode": "focus",
                    "status": "online",
                    "engine": "codex",
                    "last_heartbeat": "2026-03-11T01:15:00Z",
                    "resume_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "workspace": str(self.workspace),
                    "project_root": str(self.home_dir),
                    "instruction_path": str(self.workspace / "AGENTS.md"),
                    "cli_identity_source": "cli_register",
                    "activity": {
                        "action": "auditing",
                        "description": "Prueft Release-Blocker",
                        "target": "RB3",
                    },
                    "context_pct": 82,
                }
            if "/messages?" in url:
                return {"messages": recent_messages}
            if "/task/queue?" in url:
                return {
                    "tasks": [
                        {"title": "Audit RB3", "state": "acked", "priority": 1},
                        {"title": "Closed task", "state": "done", "priority": 3},
                    ]
                }
            raise AssertionError(url)

        with self._patch_common() as patched:
            patched["_get_agent_home_dir"].return_value = str(self.home_dir)
            patched["_get_session_name"].return_value = "acw_codex"
            patched["_capture_cli_session_log"].return_value = "CLI line 1\nCLI line 2\nCLI line 3"
            patched["_resolve_tmux_agent_id"].side_effect = lambda agent_id: agent_id
            with mock.patch.object(watcher, "http_get_json", side_effect=fake_get):
                with mock.patch.object(watcher.execution_journal, "append_cli_session_diary") as append_diary:
                    with mock.patch.object(
                        watcher.execution_journal,
                        "build_agent_diary_bundle",
                        return_value={
                            "context_bundle_id": "agent_diary_codex_acw_codex:step-1",
                            "timestamp": "2026-03-11T01:16:00Z",
                            "event_type": "pre_compact_snapshot",
                            "resume_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                            "workspace": str(self.workspace),
                            "instruction_path": str(self.workspace / "AGENTS.md"),
                            "summary": "Aktivitaet: auditing: Prueft Release-Blocker",
                            "transcript_lines": ["CLI line 2", "CLI line 3"],
                        },
                    ):
                        watcher._write_context_bridge("codex", 82)
        append_diary.assert_called_once()

        output = (self.workspace / "CONTEXT_BRIDGE.md").read_text(encoding="utf-8")
        self.assertIn("- Server-Health: degraded", output)
        self.assertIn("- Agent-Status: online", output)
        self.assertIn("- Modus: focus", output)
        self.assertIn("- Letzte Aktivitaet: auditing: Prueft Release-Blocker (Target: RB3)", output)
        self.assertIn("Audit RB3", output)
        self.assertNotIn("Closed task", output)
        self.assertNotIn("msg-0", output)
        self.assertIn("msg-5", output)
        self.assertIn("## CLI_JOURNAL", output)
        self.assertIn("Context-Bundle: agent_diary_codex_acw_codex:step-1", output)
        self.assertIn("Resume-ID: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", output)
        self.assertIn("CLI-Log: CLI line 3", output)

    def test_write_context_bridge_falls_back_to_history_when_messages_endpoint_is_missing(self) -> None:
        history_messages = [
            {"timestamp": "2026-03-11T01:00:00Z", "from": "user", "to": "codex", "content": "history-hit"},
            {"timestamp": "2026-03-11T01:01:00Z", "from": "user", "to": "backend", "content": "ignore-me"},
        ]

        def fake_get(
            url: str,
            timeout: float = 5.0,
            headers: dict[str, str] | None = None,
        ) -> dict[str, object]:
            if url.endswith("/health"):
                return {"status": "ok"}
            if url.endswith("/agents/codex"):
                return {
                    "agent_id": "codex",
                    "role": "Audit Agent",
                    "mode": "normal",
                    "status": "online",
                    "engine": "codex",
                    "workspace": str(self.workspace),
                }
            if "/messages?" in url:
                raise RuntimeError("404 /messages")
            if "/history?" in url:
                return {"messages": history_messages}
            if "/task/queue?" in url:
                return {"tasks": []}
            raise AssertionError(url)

        with self._patch_common() as patched:
            patched["_get_agent_home_dir"].return_value = str(self.home_dir)
            patched["_get_session_name"].return_value = "acw_codex"
            patched["_capture_cli_session_log"].return_value = ""
            patched["_resolve_tmux_agent_id"].side_effect = lambda agent_id: agent_id
            with mock.patch.object(watcher, "http_get_json", side_effect=fake_get):
                with mock.patch.object(watcher.execution_journal, "append_cli_session_diary") as append_diary:
                    with mock.patch.object(watcher.execution_journal, "build_agent_diary_bundle", return_value={}):
                        watcher._write_context_bridge("codex")
        append_diary.assert_called_once()

        output = (self.workspace / "CONTEXT_BRIDGE.md").read_text(encoding="utf-8")
        self.assertIn("history-hit", output)
        self.assertNotIn("ignore-me", output)

    def test_write_context_bridge_reuses_existing_diary_bundle_without_new_append(self) -> None:
        def fake_get(
            url: str,
            timeout: float = 5.0,
            headers: dict[str, str] | None = None,
        ) -> dict[str, object]:
            if url.endswith("/health"):
                return {"status": "ok"}
            if url.endswith("/agents/codex"):
                return {
                    "agent_id": "codex",
                    "role": "Audit Agent",
                    "mode": "focus",
                    "status": "online",
                    "engine": "codex",
                    "workspace": str(self.workspace),
                    "resume_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "context_pct": 67,
                }
            if "/messages?" in url:
                return {"messages": []}
            if "/task/queue?" in url:
                return {"tasks": []}
            raise AssertionError(url)

        existing_bundle = {
            "context_bundle_id": "agent_diary_codex_acw_codex:step-2",
            "timestamp": "2026-03-11T01:20:00Z",
            "event_type": "pre_compact_snapshot",
            "resume_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "workspace": str(self.workspace),
            "instruction_path": str(self.workspace / "AGENTS.md"),
            "summary": "Aktivitaet: auditing: existing bundle",
            "transcript_lines": ["CLI line 7", "CLI line 8"],
        }

        with self._patch_common() as patched:
            patched["_get_agent_home_dir"].return_value = str(self.home_dir)
            patched["_get_session_name"].return_value = "acw_codex"
            patched["_capture_cli_session_log"].return_value = "new line that should not be appended"
            patched["_resolve_tmux_agent_id"].side_effect = lambda agent_id: agent_id
            with mock.patch.object(watcher, "http_get_json", side_effect=fake_get):
                with mock.patch.object(watcher.execution_journal, "append_cli_session_diary") as append_diary:
                    with mock.patch.object(
                        watcher.execution_journal,
                        "build_agent_diary_bundle",
                        return_value=existing_bundle,
                    ):
                        watcher._write_context_bridge("codex")
        append_diary.assert_not_called()

        output = (self.workspace / "CONTEXT_BRIDGE.md").read_text(encoding="utf-8")
        self.assertIn("Context-Bundle: agent_diary_codex_acw_codex:step-2", output)
        self.assertIn("Resume-ID: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", output)
        self.assertIn(f"Workspace: {self.workspace}", output)
        self.assertIn("CLI-Log: CLI line 8", output)


class TestRuntimeOverlayHomeDir(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmpdir = Path(self._tmpdir.name)
        self.agents_conf = self.tmpdir / "agents.conf"
        self.team_json = self.tmpdir / "team.json"
        self.runtime_team = self.tmpdir / "runtime_team.json"
        self.workspace = self.tmpdir / "project" / ".agent_sessions" / "codex_a"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._orig_agents_conf = watcher.AGENTS_CONF
        self._orig_team_json = watcher._TEAM_JSON_PATH
        self._orig_runtime_team = watcher._RUNTIME_TEAM_PATH
        self._orig_cache = watcher._AGENT_META_CACHE
        self._orig_cache_stamps = watcher._AGENT_META_CACHE_STAMPS
        self._orig_runs_base_dir = journal.RUNS_BASE_DIR
        self.runs_dir = self.tmpdir / "runs"
        watcher.AGENTS_CONF = str(self.agents_conf)
        watcher._TEAM_JSON_PATH = str(self.team_json)
        watcher._RUNTIME_TEAM_PATH = str(self.runtime_team)
        watcher._AGENT_META_CACHE = None
        watcher._AGENT_META_CACHE_STAMPS = None
        journal.RUNS_BASE_DIR = str(self.runs_dir)
        self._mtime_tick = time.time() + 1.0

    def tearDown(self) -> None:
        watcher.AGENTS_CONF = self._orig_agents_conf
        watcher._TEAM_JSON_PATH = self._orig_team_json
        watcher._RUNTIME_TEAM_PATH = self._orig_runtime_team
        watcher._AGENT_META_CACHE = self._orig_cache
        watcher._AGENT_META_CACHE_STAMPS = self._orig_cache_stamps
        journal.RUNS_BASE_DIR = self._orig_runs_base_dir

    def _write_runtime_overlay(self, home_dir: str) -> None:
        self.runtime_team.write_text(
            (
                '{'
                '"active": true, '
                '"agents": ['
                '{'
                '"id": "codex_a", '
                '"engine": "codex", '
                f'"home_dir": "{home_dir}", '
                f'"workspace": "{home_dir}"'
                '}'
                ']'
                '}'
            ),
            encoding="utf-8",
        )
        os.utime(self.runtime_team, (self._mtime_tick, self._mtime_tick))
        self._mtime_tick += 1.0

    def test_get_agent_home_dir_reads_active_runtime_overlay(self) -> None:
        self.agents_conf.write_text("", encoding="utf-8")
        self.team_json.write_text('{"agents": []}', encoding="utf-8")
        self._write_runtime_overlay(str(self.workspace))

        self.assertEqual(watcher._get_agent_home_dir("codex_a"), str(self.workspace))

    def test_get_agent_home_dir_refreshes_after_runtime_overlay_change(self) -> None:
        self.agents_conf.write_text("", encoding="utf-8")
        self.team_json.write_text('{"agents": []}', encoding="utf-8")
        workspace_a = self.workspace
        workspace_b = self.tmpdir / "project" / ".agent_sessions" / "codex_b"
        workspace_b.mkdir(parents=True, exist_ok=True)
        self._write_runtime_overlay(str(workspace_a))

        self.assertEqual(watcher._get_agent_home_dir("codex_a"), str(workspace_a))

        self._write_runtime_overlay(str(workspace_b))

        self.assertEqual(watcher._get_agent_home_dir("codex_a"), str(workspace_b))

    def test_write_context_bridge_uses_runtime_overlay_home_dir_for_runtime_agent(self) -> None:
        self.agents_conf.write_text("", encoding="utf-8")
        self.team_json.write_text('{"agents": []}', encoding="utf-8")
        self._write_runtime_overlay(str(self.workspace))

        def fake_get(
            url: str,
            timeout: float = 5.0,
            headers: dict[str, str] | None = None,
        ) -> dict[str, object]:
            if url.endswith("/health"):
                return {"status": "ok"}
            if url.endswith("/agents/codex_a"):
                return {
                    "agent_id": "codex_a",
                    "role": "Runtime Agent",
                    "mode": "focus",
                    "status": "online",
                    "engine": "codex",
                    "workspace": str(self.workspace),
                    "project_root": str(self.workspace.parent.parent),
                    "instruction_path": str(self.workspace / "AGENTS.md"),
                    "resume_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "cli_identity_source": "cli_register",
                    "context_pct": 82,
                }
            if "/messages?" in url:
                return {"messages": []}
            if "/task/queue?" in url:
                return {"tasks": []}
            raise AssertionError(url)

        with mock.patch.multiple(
            watcher,
            _get_session_name=mock.DEFAULT,
            _capture_cli_session_log=mock.DEFAULT,
            _resolve_tmux_agent_id=mock.DEFAULT,
            _inject_dynamic_claude_block=mock.DEFAULT,
            _log_event=mock.DEFAULT,
            _flush=mock.DEFAULT,
            http_post_json=mock.DEFAULT,
        ) as patched:
            patched["_get_session_name"].return_value = "acw_codex_a"
            patched["_capture_cli_session_log"].return_value = "runtime overlay line"
            patched["_resolve_tmux_agent_id"].side_effect = lambda agent_id: agent_id
            with mock.patch.object(watcher, "http_get_json", side_effect=fake_get):
                watcher._write_context_bridge("codex_a", 82)

        output = (self.workspace / "CONTEXT_BRIDGE.md").read_text(encoding="utf-8")
        self.assertIn("Context-Bundle:", output)
        self.assertIn(f"Workspace: {self.workspace}", output)
        self.assertIn("Resume-ID: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", output)


class TestContextBridgeTriggers(unittest.IsolatedAsyncioTestCase):
    def test_fetch_registered_agent_ids_uses_auth_headers(self) -> None:
        with mock.patch.object(
            watcher,
            "build_bridge_auth_headers",
            return_value={"X-Bridge-Token": "tok", "X-Bridge-Agent": "backend"},
        ) as fake_auth:
            with mock.patch.object(
                watcher,
                "http_get_json",
                return_value={"agents": [{"agent_id": "codex"}]},
            ) as fake_get:
                result = watcher._fetch_registered_agent_ids()

        self.assertEqual(result, {"codex"})
        fake_auth.assert_called_once_with(agent_id="backend")
        fake_get.assert_called_once_with(
            f"{watcher.BRIDGE_HTTP}/agents",
            timeout=5.0,
            headers={"X-Bridge-Token": "tok", "X-Bridge-Agent": "backend"},
        )

    def test_fetch_recent_agent_messages_uses_auth_headers(self) -> None:
        with mock.patch.object(watcher, "_resolve_tmux_agent_id", return_value="codex"):
            with mock.patch.object(
                watcher,
                "build_bridge_auth_headers",
                return_value={"X-Bridge-Token": "tok", "X-Bridge-Agent": "codex"},
            ) as fake_auth:
                with mock.patch.object(
                    watcher,
                    "http_get_json",
                    return_value={"messages": []},
                ) as fake_get:
                    watcher._fetch_recent_agent_messages("codex", limit=2)

        fake_auth.assert_called_once_with(agent_id="codex")
        fake_get.assert_called_once_with(
            f"{watcher.BRIDGE_HTTP}/messages?agent_id=codex&limit=2",
            timeout=5.0,
            headers={"X-Bridge-Token": "tok", "X-Bridge-Agent": "codex"},
        )

    def test_behavior_check_recent_inbound_uses_auth_headers(self) -> None:
        with mock.patch.object(
            watcher,
            "build_bridge_auth_headers",
            return_value={"X-Bridge-Token": "tok", "X-Bridge-Agent": "codex"},
        ) as fake_auth:
            with mock.patch.object(
                watcher,
                "http_get_json",
                return_value={"messages": []},
            ) as fake_get:
                self.assertFalse(watcher._behavior_check_recent_inbound("codex"))

        fake_auth.assert_called_once_with(agent_id="codex")
        fake_get.assert_called_once_with(
            f"{watcher.BRIDGE_HTTP}/history?limit=10",
            timeout=3.0,
            headers={"X-Bridge-Token": "tok", "X-Bridge-Agent": "codex"},
        )

    def test_context_bridge_task_queue_source_includes_auth_headers(self) -> None:
        raw = Path(os.path.join(BACKEND_DIR, "bridge_watcher.py")).read_text(encoding="utf-8")
        self.assertIn(
            'headers=build_bridge_auth_headers(agent_id=resolved_id)',
            raw,
        )

    def test_context_monitor_source_writes_context_bridge_at_warning_threshold(self) -> None:
        raw = Path(os.path.join(BACKEND_DIR, "bridge_watcher.py")).read_text(encoding="utf-8")
        marker = "if pct_used >= 80 and agent_id not in context_warned:"
        idx = raw.find(marker)
        self.assertGreater(idx, 0)
        context = raw[idx: idx + 300]
        self.assertIn("await asyncio.to_thread(_write_context_bridge, agent_id, pct_used)", context)

    def test_refresh_context_bridges_once_updates_each_target(self) -> None:
        refresh_calls: list[str] = []
        with mock.patch.object(watcher, "_context_bridge_agent_ids", return_value=["backend", "codex"]):
            with mock.patch.object(
                watcher,
                "_write_context_bridge",
                side_effect=lambda agent_id, pct=None: refresh_calls.append(agent_id),
            ):
                watcher._refresh_context_bridges_once()
        self.assertEqual(refresh_calls, ["backend", "codex"])

    def test_watch_source_starts_context_bridge_refresh_daemon(self) -> None:
        raw = Path(os.path.join(BACKEND_DIR, "bridge_watcher.py")).read_text(encoding="utf-8")
        self.assertIn(
            'asyncio.create_task(_resilient_task("context_bridge_refresh", _context_bridge_refresh_daemon, CONTEXT_BRIDGE_REFRESH_INTERVAL))',
            raw,
        )


if __name__ == "__main__":
    unittest.main()
