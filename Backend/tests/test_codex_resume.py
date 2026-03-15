from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import tmux_manager  # noqa: E402


def _write_threads_db(db_path: Path, rows: list[tuple[str, str, int, str]]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                sandbox_policy TEXT NOT NULL,
                approval_mode TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, source,
                model_provider, cwd, title, sandbox_policy, approval_mode
            ) VALUES (?, ?, ?, ?, 'cli', 'openai', ?, 'thread', 'workspace-write', 'never')
            """,
            [(sid, rollout_path, created_at, created_at, cwd) for sid, cwd, created_at, rollout_path in rows],
        )
        conn.commit()
    finally:
        conn.close()


def _write_rollout(session_root: Path, session_id: str, cwd: str, *, mtime: int) -> Path:
    rollout_dir = session_root / "2026" / "03" / "11"
    rollout_dir.mkdir(parents=True, exist_ok=True)
    rollout_file = rollout_dir / f"rollout-2026-03-11T08-00-00-{session_id}.jsonl"
    payload = {
        "timestamp": "2026-03-11T08:00:00.000Z",
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "timestamp": "2026-03-11T08:00:00.000Z",
            "cwd": cwd,
            "originator": "codex_cli_rs",
        },
    }
    rollout_file.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    os.utime(rollout_file, (mtime, mtime))
    return rollout_file


class TestCodexResume(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.project = self.tmp / "project"
        self.workspace = self.project / ".agent_sessions" / "codex"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.codex_home = self.tmp / ".codex"
        self.session_ids = self.tmp / "session_ids.json"
        self.global_home_patch = mock.patch.object(
            tmux_manager, "_global_codex_home", return_value=self.codex_home
        )
        self.session_ids_patch = mock.patch.object(
            tmux_manager, "_session_ids_file", return_value=self.session_ids
        )
        self.global_home_patch.start()
        self.session_ids_patch.start()

    def tearDown(self) -> None:
        self.session_ids_patch.stop()
        self.global_home_patch.stop()
        self.tmpdir.cleanup()

    def test_extract_resume_id_prefers_sqlite_and_refreshes_stale_cache(self) -> None:
        stale_sid = "11111111-1111-1111-1111-111111111111"
        latest_sid = "22222222-2222-2222-2222-222222222222"
        self.session_ids.write_text(json.dumps({"codex": stale_sid}), encoding="utf-8")
        rollout_path = _write_rollout(
            self.codex_home / "sessions",
            latest_sid,
            str(self.workspace),
            mtime=200,
        )
        _write_threads_db(
            self.codex_home / "state_5.sqlite",
            [(latest_sid, str(self.workspace), 200, str(rollout_path))],
        )

        sid = tmux_manager._extract_resume_id(str(self.project), "codex", engine="codex")

        self.assertEqual(sid, latest_sid)
        persisted = json.loads(self.session_ids.read_text(encoding="utf-8"))
        self.assertEqual(persisted["codex"], latest_sid)
        scoped = persisted["__scoped__"][
            tmux_manager._session_cache_scope_key("codex", self.workspace, engine="codex")
        ]
        self.assertEqual(scoped["session_id"], latest_sid)
        self.assertEqual(scoped["workspace"], str(self.workspace.resolve()))
        self.assertEqual(scoped["project_root"], str(self.project.resolve()))
        self.assertEqual(scoped["resume_source"], "codex_sot")

    def test_extract_resume_id_falls_back_to_latest_matching_global_rollout(self) -> None:
        old_sid = "33333333-3333-3333-3333-333333333333"
        latest_sid = "44444444-4444-4444-4444-444444444444"
        unrelated_sid = "55555555-5555-5555-5555-555555555555"
        _write_rollout(self.codex_home / "sessions", old_sid, str(self.workspace), mtime=100)
        _write_rollout(self.codex_home / "sessions", latest_sid, str(self.workspace), mtime=200)
        _write_rollout(self.codex_home / "sessions", unrelated_sid, str(self.project), mtime=300)

        sid = tmux_manager._extract_resume_id(str(self.project), "codex", engine="codex")

        self.assertEqual(sid, latest_sid)
        persisted = json.loads(self.session_ids.read_text(encoding="utf-8"))
        self.assertEqual(persisted["codex"], latest_sid)

    def test_extract_resume_id_ignores_sibling_workspace_substring_match(self) -> None:
        exact_sid = "45454545-4545-4545-4545-454545454545"
        sibling_sid = "46464646-4646-4646-4646-464646464646"
        sibling_workspace = self.project / ".agent_sessions" / "codex_3"
        sibling_workspace.mkdir(parents=True, exist_ok=True)
        exact_rollout = _write_rollout(
            self.codex_home / "sessions",
            exact_sid,
            str(self.workspace),
            mtime=100,
        )
        sibling_rollout = _write_rollout(
            self.codex_home / "sessions",
            sibling_sid,
            str(sibling_workspace),
            mtime=200,
        )
        _write_threads_db(
            self.codex_home / "state_5.sqlite",
            [
                (exact_sid, str(self.workspace), 100, str(exact_rollout)),
                (sibling_sid, str(sibling_workspace), 200, str(sibling_rollout)),
            ],
        )

        sid = tmux_manager._extract_resume_id(str(self.project), "codex", engine="codex")

        self.assertEqual(sid, exact_sid)

    def test_persist_latest_codex_session_id_uses_local_codex_home_fallback(self) -> None:
        latest_sid = "66666666-6666-6666-6666-666666666666"
        local_rollout = _write_rollout(
            self.workspace / ".codex-home" / "sessions",
            latest_sid,
            str(self.workspace),
            mtime=400,
        )
        _write_threads_db(
            self.workspace / ".codex-home" / "state_5.sqlite",
            [(latest_sid, str(self.workspace), 400, str(local_rollout))],
        )

        sid = tmux_manager._persist_latest_codex_session_id(
            "codex", self.workspace, timeout=0.1, poll_interval=0.01
        )

        self.assertEqual(sid, latest_sid)
        persisted = json.loads(self.session_ids.read_text(encoding="utf-8"))
        self.assertEqual(persisted["codex"], latest_sid)

    def test_extract_resume_id_prefers_local_codex_home_over_stale_global_history(self) -> None:
        stale_sid = "67676767-6767-6767-6767-676767676767"
        latest_sid = "68686868-6868-6868-6868-686868686868"
        stale_rollout = _write_rollout(
            self.codex_home / "sessions",
            stale_sid,
            str(self.workspace),
            mtime=200,
        )
        latest_rollout = _write_rollout(
            self.workspace / ".codex-home" / "sessions",
            latest_sid,
            str(self.workspace),
            mtime=500,
        )
        _write_threads_db(
            self.codex_home / "state_5.sqlite",
            [(stale_sid, str(self.workspace), 200, str(stale_rollout))],
        )
        _write_threads_db(
            self.workspace / ".codex-home" / "state_5.sqlite",
            [(latest_sid, str(self.workspace), 500, str(latest_rollout))],
        )

        sid = tmux_manager._extract_resume_id(str(self.project), "codex", engine="codex")

        self.assertEqual(sid, latest_sid)
        persisted = json.loads(self.session_ids.read_text(encoding="utf-8"))
        self.assertEqual(persisted["codex"], latest_sid)
        scoped = persisted["__scoped__"][
            tmux_manager._session_cache_scope_key("codex", self.workspace, engine="codex")
        ]
        self.assertEqual(scoped["resume_source"], "codex_sot")

    def test_validate_local_codex_resume_id_uses_workspace_codex_home_only(self) -> None:
        session_id = "67676767-6767-6767-6767-676767676767"
        _write_rollout(
            self.workspace / ".codex-home" / "sessions",
            session_id,
            str(self.workspace),
            mtime=410,
        )

        self.assertTrue(tmux_manager._validate_local_codex_resume_id(session_id, self.workspace))

    def test_persist_latest_codex_session_id_ignores_older_global_thread_after_start(self) -> None:
        stale_sid = "78787878-7878-7878-7878-787878787878"
        latest_sid = "88888888-8888-8888-8888-888888888888"
        stale_rollout = _write_rollout(
            self.codex_home / "sessions",
            stale_sid,
            str(self.workspace),
            mtime=200,
        )
        latest_rollout = _write_rollout(
            self.workspace / ".codex-home" / "sessions",
            latest_sid,
            str(self.workspace),
            mtime=500,
        )
        _write_threads_db(
            self.codex_home / "state_5.sqlite",
            [(stale_sid, str(self.workspace), 200, str(stale_rollout))],
        )
        _write_threads_db(
            self.workspace / ".codex-home" / "state_5.sqlite",
            [(latest_sid, str(self.workspace), 500, str(latest_rollout))],
        )

        sid = tmux_manager._persist_latest_codex_session_id(
            "codex",
            self.workspace,
            started_after=300,
            timeout=0.1,
            poll_interval=0.01,
        )

        self.assertEqual(sid, latest_sid)
        persisted = json.loads(self.session_ids.read_text(encoding="utf-8"))
        self.assertEqual(persisted["codex"], latest_sid)

    def test_scoped_session_cache_keeps_workspace_lineage_separate(self) -> None:
        other_project = self.tmp / "other-project"
        other_workspace = other_project / ".agent_sessions" / "codex"
        other_workspace.mkdir(parents=True, exist_ok=True)
        first_sid = "91919191-9191-9191-9191-919191919191"
        second_sid = "92929292-9292-9292-9292-929292929292"

        tmux_manager._persist_session_id(
            "codex",
            first_sid,
            workspace=self.workspace,
            project_root=self.project,
            engine="codex",
            resume_source="session_cache",
        )
        tmux_manager._persist_session_id(
            "codex",
            second_sid,
            workspace=other_workspace,
            project_root=other_project,
            engine="codex",
            resume_source="session_cache",
        )

        self.assertEqual(
            tmux_manager._load_cached_session_id("codex", workspace=self.workspace, engine="codex"),
            first_sid,
        )
        self.assertEqual(
            tmux_manager._load_cached_session_id("codex", workspace=other_workspace, engine="codex"),
            second_sid,
        )

    def test_persist_session_id_preserves_identity_metadata_without_live_session(self) -> None:
        session_id = "93939393-9393-9393-9393-939393939393"

        tmux_manager._persist_session_id(
            "codex",
            session_id,
            workspace=self.workspace,
            project_root=self.project,
            engine="codex",
            session_name="acw_codex",
            incarnation_id="codex:codex:123",
            resume_source="post_start_discovery",
        )
        with mock.patch.object(tmux_manager, "_tmux_session_workspace", return_value=""):
            tmux_manager._persist_session_id(
                "codex",
                session_id,
                workspace=self.workspace,
                project_root=self.project,
                engine="codex",
                resume_source="codex_sot",
            )

        scoped = json.loads(self.session_ids.read_text(encoding="utf-8"))["__scoped__"][
            tmux_manager._session_cache_scope_key("codex", self.workspace, engine="codex")
        ]
        self.assertEqual(scoped["session_name"], "acw_codex")
        self.assertEqual(scoped["incarnation_id"], "codex:codex:123")
        self.assertEqual(scoped["resume_source"], "codex_sot")

    def test_extract_resume_id_backfills_live_tmux_identity_metadata(self) -> None:
        latest_sid = "94949494-9494-9494-9494-949494949494"
        rollout_path = _write_rollout(
            self.codex_home / "sessions",
            latest_sid,
            str(self.workspace),
            mtime=200,
        )
        _write_threads_db(
            self.codex_home / "state_5.sqlite",
            [(latest_sid, str(self.workspace), 200, str(rollout_path))],
        )

        def fake_tmux_env(session_name: str, variable: str) -> str:
            values = {
                ("acw_codex", "BRIDGE_CLI_SESSION_NAME"): "acw_codex",
                ("acw_codex", "BRIDGE_CLI_INCARNATION_ID"): "codex:codex:live",
            }
            return values.get((session_name, variable), "")

        with (
            mock.patch.object(tmux_manager, "_tmux_session_workspace", return_value=str(self.workspace)),
            mock.patch.object(tmux_manager, "_tmux_session_env_value", side_effect=fake_tmux_env),
        ):
            sid = tmux_manager._extract_resume_id(str(self.project), "codex", engine="codex")

        self.assertEqual(sid, latest_sid)
        scoped = json.loads(self.session_ids.read_text(encoding="utf-8"))["__scoped__"][
            tmux_manager._session_cache_scope_key("codex", self.workspace, engine="codex")
        ]
        self.assertEqual(scoped["session_name"], "acw_codex")
        self.assertEqual(scoped["incarnation_id"], "codex:codex:live")
        self.assertEqual(scoped["resume_source"], "codex_sot")

    def test_agent_codex_config_includes_bridge_cli_identity_env(self) -> None:
        instruction_path = self.workspace / "AGENTS.md"
        with (
            mock.patch.object(
                tmux_manager,
                "_mcp_registry",
                return_value={
                    "bridge": {
                        "type": "stdio",
                        "command": "bridge-cmd",
                        "args": ["serve"],
                        "env": {"BRIDGE_BASE": "1"},
                    }
                },
            ),
            mock.patch.object(tmux_manager, "_requested_mcp_names", return_value=["bridge"]),
        ):
            raw = tmux_manager._agent_codex_config(
                project_path=str(self.project),
                workspace_path=str(self.workspace),
                mcp_servers="bridge",
                bridge_env={
                    "BRIDGE_CLI_WORKSPACE": str(self.workspace),
                    "BRIDGE_CLI_PROJECT_ROOT": str(self.project),
                    "BRIDGE_CLI_INSTRUCTION_PATH": str(instruction_path),
                    "BRIDGE_TOKEN_CONFIG_FILE": "/tmp/bridge-tokens.json",
                    "BRIDGE_REGISTER_TOKEN": "register-token",
                },
            )

        self.assertIn("[mcp_servers.bridge]", raw)
        self.assertIn('command = "bridge-cmd"', raw)
        self.assertIn("[mcp_servers.bridge.env]", raw)
        self.assertIn('BRIDGE_BASE = "1"', raw)
        self.assertIn(f'BRIDGE_CLI_WORKSPACE = "{self.workspace}"', raw)
        self.assertIn(f'BRIDGE_CLI_PROJECT_ROOT = "{self.project}"', raw)
        self.assertIn(f'BRIDGE_CLI_INSTRUCTION_PATH = "{instruction_path}"', raw)
        self.assertIn('BRIDGE_TOKEN_CONFIG_FILE = "/tmp/bridge-tokens.json"', raw)
        self.assertIn('BRIDGE_REGISTER_TOKEN = "register-token"', raw)

    def test_native_mcp_servers_inject_bridge_token_config_env(self) -> None:
        with (
            mock.patch.object(
                tmux_manager,
                "build_client_mcp_config",
                return_value={
                    "mcpServers": {
                        "bridge": {
                            "type": "stdio",
                            "command": "python3",
                            "args": ["bridge_mcp.py"],
                            "env": {},
                        }
                    }
                },
            ),
        ):
            servers = tmux_manager._native_mcp_servers(
                "bridge",
                bridge_env={
                    "BRIDGE_TOKEN_CONFIG_FILE": "/tmp/bridge-tokens.json",
                    "BRIDGE_REGISTER_TOKEN": "register-token",
                },
            )

        self.assertEqual(
            servers["bridge"]["env"]["BRIDGE_TOKEN_CONFIG_FILE"],
            "/tmp/bridge-tokens.json",
        )
        self.assertEqual(
            servers["bridge"]["env"]["BRIDGE_REGISTER_TOKEN"],
            "register-token",
        )

    def test_create_agent_session_codex_triggers_post_start_persist(self) -> None:
        persist_sid = "77777777-7777-7777-7777-777777777777"
        with (
            mock.patch.object(tmux_manager, "prepare_agent_identity", return_value=("", "")),
            mock.patch.object(tmux_manager, "generate_agent_claude_md", return_value="AGENTS"),
            mock.patch.object(tmux_manager, "_ensure_context_bridge"),
            mock.patch.object(tmux_manager, "_ensure_persistent_symlinks"),
            mock.patch.object(tmux_manager, "_write_agent_runtime_config"),
            mock.patch.object(tmux_manager, "_run", return_value=0),
            mock.patch.object(tmux_manager, "_find_conflicting_workspace_session", return_value=""),
            mock.patch.object(tmux_manager, "_is_inside_git_repo", return_value=False),
            mock.patch.object(tmux_manager, "_tmux_session_workspace", return_value=None),
            mock.patch.object(tmux_manager, "_stabilize_codex_startup"),
            mock.patch.object(tmux_manager, "is_session_alive", side_effect=[False, True]),
            mock.patch.object(
                tmux_manager, "_persist_latest_codex_session_id", return_value=persist_sid
            ) as persist_mock,
            mock.patch.object(tmux_manager.subprocess, "Popen"),
        ):
            ok = tmux_manager.create_agent_session(
                agent_id="codex",
                role="Coder",
                project_path=str(self.project),
                team_members=[],
                engine="codex",
                initial_prompt="resume-test",
            )

        self.assertTrue(ok)
        persist_mock.assert_called_once_with("codex", self.workspace, started_after=mock.ANY)

    def test_create_agent_session_exports_cli_identity_env_for_register_bridge(self) -> None:
        sent_commands: list[list[str]] = []
        popen_calls: list[list[str]] = []

        def fake_run(cmd: list[str]) -> int:
            sent_commands.append(cmd)
            return 0

        def fake_popen(args, **kwargs):
            popen_calls.append(list(args))
            class _Dummy:
                pass
            return _Dummy()

        with (
            mock.patch.object(tmux_manager, "prepare_agent_identity", return_value=("", "")),
            mock.patch.object(tmux_manager, "generate_agent_claude_md", return_value="AGENTS"),
            mock.patch.object(tmux_manager, "_ensure_context_bridge"),
            mock.patch.object(tmux_manager, "_ensure_persistent_symlinks"),
            mock.patch.object(tmux_manager, "_write_agent_runtime_config"),
            mock.patch.object(tmux_manager, "_run", side_effect=fake_run),
            mock.patch.object(tmux_manager, "_find_conflicting_workspace_session", return_value=""),
            mock.patch.object(
                tmux_manager,
                "_extract_resume_lineage",
                return_value=("99999999-9999-9999-9999-999999999999", "session_cache"),
            ),
            mock.patch.object(tmux_manager, "_validate_local_codex_resume_id", return_value=True),
            mock.patch.object(tmux_manager, "_is_inside_git_repo", return_value=False),
            mock.patch.object(tmux_manager, "_tmux_session_workspace", return_value=None),
            mock.patch.object(tmux_manager, "_stabilize_codex_startup"),
            mock.patch.object(tmux_manager, "is_session_alive", side_effect=[False, True]),
            mock.patch.object(tmux_manager, "_persist_latest_codex_session_id", return_value="99999999-9999-9999-9999-999999999999"),
            mock.patch.object(tmux_manager.subprocess, "Popen", side_effect=fake_popen),
        ):
            ok = tmux_manager.create_agent_session(
                agent_id="codex",
                role="Coder",
                project_path=str(self.project),
                team_members=[],
                engine="codex",
                initial_prompt="resume-test",
            )

        self.assertTrue(ok)
        send_keys_call = next(
            call for call in sent_commands
            if call[:4] == ["tmux", "send-keys", "-t", "acw_codex"]
        )
        launch_cmd = send_keys_call[4]
        self.assertIn("BRIDGE_CLI_AGENT_ID=codex", launch_cmd)
        self.assertIn("BRIDGE_CLI_ENGINE=codex", launch_cmd)
        self.assertIn("BRIDGE_CLI_HOME_DIR=", launch_cmd)
        self.assertIn("BRIDGE_CLI_WORKSPACE=", launch_cmd)
        self.assertIn("BRIDGE_CLI_PROJECT_ROOT=", launch_cmd)
        self.assertIn("BRIDGE_CLI_INSTRUCTION_PATH=", launch_cmd)
        self.assertIn("BRIDGE_CLI_SESSION_NAME=acw_codex", launch_cmd)
        self.assertIn("BRIDGE_CLI_RESUME_SOURCE=session_cache", launch_cmd)
        self.assertIn("BRIDGE_CLI_INCARNATION_ID=", launch_cmd)
        self.assertIn("BRIDGE_RESUME_ID=99999999-9999-9999-9999-999999999999", launch_cmd)
        self.assertIn("BRIDGE_TOKEN_CONFIG_FILE=", launch_cmd)
        self.assertIn("BRIDGE_REGISTER_TOKEN=", launch_cmd)
        self.assertNotIn("--skip-git-repo-check", launch_cmd)
        self.assertTrue(popen_calls)
        self.assertEqual(popen_calls[0][3], "5")

    def test_create_agent_session_codex_skips_non_local_resume_id(self) -> None:
        sent_commands: list[list[str]] = []

        def fake_run(cmd: list[str]) -> int:
            sent_commands.append(cmd)
            return 0

        with (
            mock.patch.object(tmux_manager, "prepare_agent_identity", return_value=("", "")),
            mock.patch.object(tmux_manager, "generate_agent_claude_md", return_value="AGENTS"),
            mock.patch.object(tmux_manager, "_ensure_context_bridge"),
            mock.patch.object(tmux_manager, "_ensure_persistent_symlinks"),
            mock.patch.object(tmux_manager, "_write_agent_runtime_config"),
            mock.patch.object(tmux_manager, "_run", side_effect=fake_run),
            mock.patch.object(tmux_manager, "_find_conflicting_workspace_session", return_value=""),
            mock.patch.object(
                tmux_manager,
                "_extract_resume_lineage",
                return_value=("99999999-9999-9999-9999-999999999999", "codex_sot"),
            ),
            mock.patch.object(tmux_manager, "_validate_local_codex_resume_id", return_value=False),
            mock.patch.object(tmux_manager, "_is_inside_git_repo", return_value=False),
            mock.patch.object(tmux_manager, "_tmux_session_workspace", return_value=None),
            mock.patch.object(tmux_manager, "_stabilize_codex_startup"),
            mock.patch.object(tmux_manager, "is_session_alive", side_effect=[False, True]),
            mock.patch.object(tmux_manager, "_persist_latest_codex_session_id", return_value=""),
            mock.patch.object(tmux_manager.subprocess, "Popen"),
        ):
            ok = tmux_manager.create_agent_session(
                agent_id="codex",
                role="Coder",
                project_path=str(self.project),
                team_members=[],
                engine="codex",
                initial_prompt="resume-test",
            )

        self.assertTrue(ok)
        launch_cmd = next(
            call for call in sent_commands
            if call[:4] == ["tmux", "send-keys", "-t", "acw_codex"]
        )[4]
        self.assertIn("codex --no-alt-screen", launch_cmd)
        self.assertNotIn("codex resume 99999999-9999-9999-9999-999999999999", launch_cmd)

    def test_create_agent_session_normalizes_workspace_project_path(self) -> None:
        sent_commands: list[list[str]] = []

        def fake_run(cmd: list[str]) -> int:
            sent_commands.append(cmd)
            return 0

        with (
            mock.patch.object(tmux_manager, "prepare_agent_identity", return_value=("", "")),
            mock.patch.object(tmux_manager, "generate_agent_claude_md", return_value="AGENTS"),
            mock.patch.object(tmux_manager, "_ensure_context_bridge"),
            mock.patch.object(tmux_manager, "_ensure_persistent_symlinks"),
            mock.patch.object(tmux_manager, "_write_agent_runtime_config"),
            mock.patch.object(tmux_manager, "_run", side_effect=fake_run),
            mock.patch.object(tmux_manager, "_find_conflicting_workspace_session", return_value=""),
            mock.patch.object(tmux_manager, "_extract_resume_lineage", return_value=("", "")),
            mock.patch.object(tmux_manager, "_is_inside_git_repo", return_value=False),
            mock.patch.object(tmux_manager, "_stabilize_codex_startup"),
            mock.patch.object(tmux_manager, "is_session_alive", side_effect=[False, True]),
            mock.patch.object(tmux_manager, "_persist_latest_codex_session_id", return_value=""),
            mock.patch.object(tmux_manager.subprocess, "Popen"),
        ):
            ok = tmux_manager.create_agent_session(
                agent_id="codex",
                role="Coder",
                project_path=str(self.workspace),
                team_members=[],
                engine="codex",
                initial_prompt="resume-test",
            )

        self.assertTrue(ok)
        new_session_call = next(call for call in sent_commands if call[:4] == ["tmux", "new-session", "-d", "-s"])
        self.assertEqual(new_session_call[-1], str(self.workspace))
        launch_cmd = next(
            call for call in sent_commands
            if call[:4] == ["tmux", "send-keys", "-t", "acw_codex"]
        )[4]
        self.assertIn(f"BRIDGE_CLI_PROJECT_ROOT={self.project}", launch_cmd)
        self.assertNotIn(".agent_sessions/codex/.agent_sessions/codex", launch_cmd)
        self.assertNotIn("--skip-git-repo-check", launch_cmd)

    def test_create_agent_session_claude_writes_bridge_token_config_into_mcp_json(self) -> None:
        claude_config_dir = self.tmp / ".claude-config"
        claude_config_dir.mkdir(parents=True, exist_ok=True)

        with (
            mock.patch.dict(
                os.environ,
                {
                    "BRIDGE_TOKEN_CONFIG_FILE": "/tmp/bridge-tokens.json",
                    "BRIDGE_REGISTER_TOKEN": "runtime-register-token",
                },
                clear=False,
            ),
            mock.patch.object(tmux_manager, "prepare_agent_identity", return_value=("", "")),
            mock.patch.object(tmux_manager, "generate_agent_claude_md", return_value="AGENTS"),
            mock.patch.object(tmux_manager, "_ensure_context_bridge"),
            mock.patch.object(tmux_manager, "_ensure_persistent_symlinks"),
            mock.patch.object(tmux_manager, "_extract_resume_lineage", return_value=("", "")),
            mock.patch.object(tmux_manager, "_find_conflicting_workspace_session", return_value=""),
            mock.patch.object(tmux_manager, "_deploy_agent_skills", return_value=""),
            mock.patch.object(tmux_manager, "_effective_claude_config_dir", return_value=claude_config_dir),
            mock.patch.object(tmux_manager, "_check_claude_auth_status", return_value="ready"),
            mock.patch.object(tmux_manager, "_stabilize_claude_startup"),
            mock.patch.object(tmux_manager, "_run", return_value=0),
            mock.patch.object(tmux_manager, "_is_inside_git_repo", return_value=False),
            mock.patch.object(tmux_manager, "is_session_alive", side_effect=[False, True]),
            mock.patch.object(tmux_manager.subprocess, "Popen"),
        ):
            ok = tmux_manager.create_agent_session(
                agent_id="claude",
                role="Coder",
                project_path=str(self.project),
                team_members=[],
                engine="claude",
                initial_prompt="bootstrap",
            )

        self.assertTrue(ok)
        data = json.loads((self.project / ".agent_sessions" / "claude" / ".mcp.json").read_text(encoding="utf-8"))
        bridge_env = data["mcpServers"]["bridge"]["env"]
        self.assertEqual(
            bridge_env["BRIDGE_TOKEN_CONFIG_FILE"],
            "/tmp/bridge-tokens.json",
        )
        self.assertEqual(
            bridge_env["BRIDGE_REGISTER_TOKEN"],
            "runtime-register-token",
        )

    def test_create_agent_session_claude_skips_non_local_resume_id(self) -> None:
        claude_config_dir = self.tmp / ".claude-config"
        claude_config_dir.mkdir(parents=True, exist_ok=True)

        with (
            mock.patch.dict(
                os.environ,
                {"BRIDGE_TOKEN_CONFIG_FILE": "/tmp/bridge-tokens.json"},
                clear=False,
            ),
            mock.patch.object(tmux_manager, "prepare_agent_identity", return_value=("", "")),
            mock.patch.object(tmux_manager, "generate_agent_claude_md", return_value="AGENTS"),
            mock.patch.object(tmux_manager, "_ensure_context_bridge"),
            mock.patch.object(tmux_manager, "_ensure_persistent_symlinks"),
            mock.patch.object(
                tmux_manager,
                "_extract_resume_lineage",
                return_value=("dddddddd-dddd-dddd-dddd-dddddddddddd", "session_cache"),
            ),
            mock.patch.object(tmux_manager, "_find_conflicting_workspace_session", return_value=""),
            mock.patch.object(tmux_manager, "_deploy_agent_skills", return_value=""),
            mock.patch.object(tmux_manager, "_effective_claude_config_dir", return_value=claude_config_dir),
            mock.patch.object(tmux_manager, "_check_claude_auth_status", return_value="ready"),
            mock.patch.object(tmux_manager, "_stabilize_claude_startup"),
            mock.patch.object(tmux_manager, "_run", return_value=0),
            mock.patch.object(tmux_manager, "_is_inside_git_repo", return_value=False),
            mock.patch.object(tmux_manager, "is_session_alive", side_effect=[False, True]),
            mock.patch.object(tmux_manager.subprocess, "Popen"),
        ):
            ok = tmux_manager.create_agent_session(
                agent_id="claude",
                role="Coder",
                project_path=str(self.project),
                team_members=[],
                engine="claude",
                initial_prompt="bootstrap",
            )

        self.assertTrue(ok)
        data = json.loads((self.project / ".agent_sessions" / "claude" / ".mcp.json").read_text(encoding="utf-8"))
        bridge_env = data["mcpServers"]["bridge"]["env"]
        self.assertNotIn("BRIDGE_RESUME_ID", bridge_env)

    def test_create_agent_session_claude_falls_back_to_fresh_start_on_resume_limit(self) -> None:
        claude_config_dir = self.tmp / ".claude-config"
        claude_config_dir.mkdir(parents=True, exist_ok=True)
        claude_workspace = self.project / ".agent_sessions" / "claude"
        fake_backend = self.tmp / "backend"
        fake_backend.mkdir(parents=True, exist_ok=True)
        state_dir = fake_backend / "agent_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "claude.json").write_text(
            json.dumps({"resume_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"}),
            encoding="utf-8",
        )

        with (
            mock.patch.object(tmux_manager, "prepare_agent_identity", return_value=("", "")),
            mock.patch.object(tmux_manager, "generate_agent_claude_md", return_value="AGENTS"),
            mock.patch.object(tmux_manager, "_ensure_context_bridge"),
            mock.patch.object(tmux_manager, "_ensure_persistent_symlinks"),
            mock.patch.object(
                tmux_manager,
                "_extract_resume_lineage",
                return_value=("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee", "session_cache"),
            ),
            mock.patch.object(tmux_manager, "_find_conflicting_workspace_session", return_value=""),
            mock.patch.object(tmux_manager, "_deploy_agent_skills", return_value=""),
            mock.patch.object(tmux_manager, "_effective_claude_config_dir", return_value=claude_config_dir),
            mock.patch.object(tmux_manager, "_validate_local_claude_resume_id", return_value=True),
            mock.patch.object(
                tmux_manager,
                "_tmux_capture_text",
                side_effect=["You've hit your limit · resets tomorrow", ""],
            ),
            mock.patch.object(tmux_manager, "_check_claude_auth_status", return_value="ready"),
            mock.patch.object(tmux_manager, "_stabilize_claude_startup"),
            mock.patch.object(tmux_manager, "_run", return_value=0) as run_mock,
            mock.patch.object(tmux_manager, "_is_inside_git_repo", return_value=False),
            mock.patch.object(tmux_manager, "is_session_alive", side_effect=[False, False, True]),
            mock.patch.object(tmux_manager, "kill_agent_session") as kill_mock,
            mock.patch.object(tmux_manager.subprocess, "Popen"),
            mock.patch.object(tmux_manager, "__file__", str(fake_backend / "tmux_manager.py")),
        ):
            ok = tmux_manager.create_agent_session(
                agent_id="claude",
                role="Coder",
                project_path=str(self.project),
                team_members=[],
                engine="claude",
                initial_prompt="bootstrap",
            )

        self.assertTrue(ok)
        data = json.loads((self.project / ".agent_sessions" / "claude" / ".mcp.json").read_text(encoding="utf-8"))
        bridge_env = data["mcpServers"]["bridge"]["env"]
        self.assertNotIn("BRIDGE_RESUME_ID", bridge_env)
        kill_mock.assert_called_once_with("claude")
        sent_commands = [" ".join(call.args[0]) for call in run_mock.call_args_list if call.args]
        self.assertTrue(any("--resume eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee --permission-mode default" in cmd for cmd in sent_commands))
        self.assertTrue(any("claude --permission-mode default" in cmd and "--resume" not in cmd for cmd in sent_commands))
        persisted = json.loads(self.session_ids.read_text(encoding="utf-8"))
        self.assertNotIn("claude", persisted)
        scoped = persisted[tmux_manager._BLOCKED_RESUME_IDS_KEY][
            tmux_manager._resume_block_scope_key("claude", claude_workspace, engine="claude")
        ]
        self.assertIn("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee", scoped["blocked_ids"])
        agent_state = json.loads((state_dir / "claude.json").read_text(encoding="utf-8"))
        self.assertEqual(agent_state["resume_id"], "")

    def test_extract_resume_id_skips_blocked_claude_resume_from_cache_and_session_file(self) -> None:
        session_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        claude_workspace = self.project / ".agent_sessions" / "claude"
        self.session_ids.write_text(
            json.dumps(
                {
                    "claude": session_id,
                    "__scoped__": {
                        tmux_manager._session_cache_scope_key("claude", claude_workspace, engine="claude"): {
                            "session_id": session_id,
                            "agent_id": "claude",
                            "engine": "claude",
                            "workspace": str(claude_workspace.resolve()),
                            "project_root": str(self.project.resolve()),
                            "resume_source": "session_cache",
                        }
                    },
                    tmux_manager._BLOCKED_RESUME_IDS_KEY: {
                        tmux_manager._resume_block_scope_key("claude", claude_workspace, engine="claude"): {
                            "agent_id": "claude",
                            "engine": "claude",
                            "workspace": str(claude_workspace.resolve()),
                            "blocked_ids": {
                                session_id: {
                                    "session_id": session_id,
                                    "reason": "usage_limit_screen",
                                }
                            },
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        mangled = "".join(
            ch if ch.isalnum() or ch == "-" else "-"
            for ch in str(claude_workspace)
        )
        claude_config_dir = self.tmp / ".claude-sub2"
        project_dir = claude_config_dir / "projects" / mangled
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / f"{session_id}.jsonl").write_text("{}", encoding="utf-8")

        with mock.patch.object(Path, "home", return_value=self.tmp):
            sid = tmux_manager._extract_resume_id(str(self.project), "claude", engine="claude")

        self.assertEqual(sid, "")
        persisted = json.loads(self.session_ids.read_text(encoding="utf-8"))
        self.assertNotIn("claude", persisted)

    def test_create_agent_session_aborts_on_conflicting_workspace_session(self) -> None:
        with (
            mock.patch.object(tmux_manager, "is_session_alive", return_value=False),
            mock.patch.object(
                tmux_manager,
                "_find_conflicting_workspace_session",
                return_value="acw_codex_stale",
            ),
            mock.patch.object(tmux_manager, "_run") as run_mock,
        ):
            ok = tmux_manager.create_agent_session(
                agent_id="codex",
                role="Coder",
                project_path=str(self.project),
                team_members=[],
                engine="codex",
            )

        self.assertFalse(ok)
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
