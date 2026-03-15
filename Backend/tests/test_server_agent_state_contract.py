from __future__ import annotations

import os
import sys
import tempfile
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import server_agent_state as state_mod  # noqa: E402


class TestServerAgentStateContract(unittest.TestCase):
    def test_server_reexports_agent_state_helpers(self) -> None:
        self.assertIs(srv._agent_state_path, state_mod._agent_state_path)
        self.assertIs(srv._load_agent_state, state_mod._load_agent_state)
        self.assertIs(srv._save_agent_state, state_mod._save_agent_state)
        self.assertIs(srv._get_agent_home_dir, state_mod._get_agent_home_dir)
        self.assertIs(srv._cli_identity_bundle, state_mod._cli_identity_bundle)
        self.assertIs(srv._AGENT_STATE_CACHE, state_mod._AGENT_STATE_CACHE)

    def test_get_agent_home_dir_uses_live_server_team_config(self) -> None:
        original_team = srv.TEAM_CONFIG
        try:
            srv.TEAM_CONFIG = {
                "agents": [
                    {"id": "codex_contract_agent", "home_dir": "/srv/contract-home"},
                ]
            }
            self.assertEqual(srv._get_agent_home_dir("codex_contract_agent"), "/srv/contract-home")
        finally:
            srv.TEAM_CONFIG = original_team

    def test_cli_identity_bundle_falls_back_to_persisted_agent_state(self) -> None:
        original_dir = state_mod._AGENT_STATE_DIR
        original_team_getter = state_mod._TEAM_CONFIG_GETTER
        original_registered_getter = state_mod._REGISTERED_AGENTS_GETTER
        original_lock = state_mod._AGENT_STATE_LOCK
        original_layout = state_mod._RESOLVE_AGENT_CLI_LAYOUT_FN
        original_write_lock = state_mod._AGENT_STATE_WRITE_LOCK
        original_cache_ttl = state_mod._AGENT_STATE_CACHE_TTL
        original_cache = dict(state_mod._AGENT_STATE_CACHE)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                state_mod.init(
                    agent_state_dir=tmpdir,
                    utc_now_iso_fn=lambda: "2026-03-14T18:30:00+00:00",
                    team_config_getter=lambda: {"agents": []},
                    registered_agents_getter=lambda: {},
                    agent_state_lock=srv.AGENT_STATE_LOCK,
                    resolve_agent_cli_layout_fn=lambda path, agent_id: {
                        "home_dir": path,
                        "workspace": path if path.endswith(f".agent_sessions/{agent_id}") else os.path.join(path, ".agent_sessions", agent_id),
                        "project_root": path.rsplit("/.agent_sessions/", 1)[0] if f"/.agent_sessions/{agent_id}" in path else path,
                    },
                    agent_state_write_lock=original_write_lock,
                )
                state_mod._AGENT_STATE_CACHE.clear()
                state_mod._AGENT_STATE_CACHE_TTL = 0.0
                state_mod._save_agent_state(
                    "codex_contract_agent",
                    {
                        "resume_id": "019cec1d-3a61-7031-853e-163b79813892",
                        "workspace": "/tmp/project/.agent_sessions/codex_contract_agent",
                        "project_root": "/tmp/project",
                        "home_dir": "/tmp/project/.agent_sessions/codex_contract_agent",
                        "instruction_path": "/tmp/project/.agent_sessions/codex_contract_agent/AGENTS.md",
                        "cli_identity_source": "cli_register",
                    },
                )

                bundle = state_mod._cli_identity_bundle("codex_contract_agent", {})
        finally:
            state_mod._AGENT_STATE_DIR = original_dir
            state_mod._TEAM_CONFIG_GETTER = original_team_getter
            state_mod._REGISTERED_AGENTS_GETTER = original_registered_getter
            state_mod._AGENT_STATE_LOCK = original_lock
            state_mod._RESOLVE_AGENT_CLI_LAYOUT_FN = original_layout
            state_mod._AGENT_STATE_WRITE_LOCK = original_write_lock
            state_mod._AGENT_STATE_CACHE_TTL = original_cache_ttl
            state_mod._AGENT_STATE_CACHE.clear()
            state_mod._AGENT_STATE_CACHE.update(original_cache)

        self.assertEqual(bundle["resume_id"], "019cec1d-3a61-7031-853e-163b79813892")
        self.assertEqual(bundle["workspace"], "/tmp/project/.agent_sessions/codex_contract_agent")
        self.assertEqual(bundle["project_root"], "/tmp/project")
        self.assertEqual(bundle["home_dir"], "/tmp/project/.agent_sessions/codex_contract_agent")
        self.assertEqual(bundle["instruction_path"], "/tmp/project/.agent_sessions/codex_contract_agent/AGENTS.md")
        self.assertEqual(bundle["cli_identity_source"], "cli_register")


if __name__ == "__main__":
    unittest.main()
