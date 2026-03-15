from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import start_platform_runtime as spr  # noqa: E402


class TestStartPlatformRuntimeContract(unittest.TestCase):
    def _write_team(self, payload: dict) -> str:
        tmpdir = tempfile.mkdtemp(prefix="slice43_team_")
        path = os.path.join(tmpdir, "team.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def test_partial_runtime_pair_falls_back_to_explicit_active_agents(self):
        team_path = self._write_team(
            {
                "agents": [
                    {"id": "codex", "engine": "codex", "active": True, "role": "senior"},
                    {"id": "claude", "engine": "claude", "active": False, "role": "senior"},
                ]
            }
        )

        payload = spr.build_runtime_configure_payload(
            team_path=team_path,
            pair_mode="codex-claude",
            agent_a_engine="codex",
            agent_b_engine="claude",
            project_path="/tmp/project",
            allow_peer_auto=False,
            peer_auto_require_flag=True,
            max_peer_hops=20,
            max_turns=0,
            process_all=False,
            keep_history=False,
            timeout=90,
            stabilize_seconds=30.0,
        )

        self.assertNotIn("agent_a_engine", payload)
        self.assertNotIn("agent_b_engine", payload)
        self.assertEqual(len(payload["agents"]), 1)
        self.assertEqual(payload["agents"][0]["id"], "codex")
        self.assertEqual(payload["agents"][0]["engine"], "codex")

    def test_pair_mode_fallback_uses_default_engines_when_env_is_empty(self):
        team_path = self._write_team(
            {
                "agents": [
                    {"id": "codex", "engine": "codex", "active": True, "role": "senior"},
                    {"id": "claude", "engine": "claude", "active": False, "role": "senior"},
                ]
            }
        )

        payload = spr.build_runtime_configure_payload(
            team_path=team_path,
            pair_mode="codex-claude",
            agent_a_engine="",
            agent_b_engine="",
            project_path="/tmp/project",
            allow_peer_auto=False,
            peer_auto_require_flag=True,
            max_peer_hops=20,
            max_turns=0,
            process_all=False,
            keep_history=False,
            timeout=90,
            stabilize_seconds=30.0,
        )

        self.assertEqual(len(payload["agents"]), 1)
        self.assertEqual(payload["agents"][0]["id"], "codex")
        self.assertEqual(payload["agents"][0]["engine"], "codex")

    def test_full_runtime_pair_keeps_pair_payload(self):
        team_path = self._write_team(
            {
                "agents": [
                    {"id": "codex", "engine": "codex", "active": True, "role": "senior"},
                    {"id": "claude", "engine": "claude", "active": True, "role": "senior"},
                ]
            }
        )

        payload = spr.build_runtime_configure_payload(
            team_path=team_path,
            pair_mode="codex-claude",
            agent_a_engine="codex",
            agent_b_engine="claude",
            project_path="/tmp/project",
            allow_peer_auto=False,
            peer_auto_require_flag=True,
            max_peer_hops=20,
            max_turns=0,
            process_all=False,
            keep_history=False,
            timeout=90,
            stabilize_seconds=30.0,
        )

        self.assertEqual(payload["agent_a_engine"], "codex")
        self.assertEqual(payload["agent_b_engine"], "claude")
        self.assertNotIn("agents", payload)

    def test_unknown_layout_ids_keep_legacy_pair_payload(self):
        team_path = self._write_team(
            {
                "agents": [
                    {"id": "codex", "engine": "codex", "active": True, "role": "senior"},
                    {"id": "codex_2", "engine": "codex", "active": False, "role": "senior"},
                ]
            }
        )

        payload = spr.build_runtime_configure_payload(
            team_path=team_path,
            pair_mode="codex-codex",
            agent_a_engine="codex",
            agent_b_engine="codex",
            project_path="/tmp/project",
            allow_peer_auto=False,
            peer_auto_require_flag=True,
            max_peer_hops=20,
            max_turns=0,
            process_all=False,
            keep_history=False,
            timeout=90,
            stabilize_seconds=30.0,
        )

        self.assertEqual(payload["agent_a_engine"], "codex")
        self.assertEqual(payload["agent_b_engine"], "codex")
        self.assertNotIn("agents", payload)
