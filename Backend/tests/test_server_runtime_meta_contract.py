from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402
import server_runtime_meta as meta  # noqa: E402


class TestServerRuntimeMetaContract(unittest.TestCase):
    def test_server_reexports_runtime_meta_helpers(self) -> None:
        self.assertIs(srv.pair_mode_of, meta.pair_mode_of)
        self.assertIs(srv.resolve_layout, meta.resolve_layout)
        self.assertIs(srv.resolve_runtime_specs, meta.resolve_runtime_specs)
        self.assertIs(srv._runtime_profile_for_agent, meta._runtime_profile_for_agent)
        self.assertIs(srv._runtime_profile_capabilities, meta._runtime_profile_capabilities)
        self.assertIs(srv._capability_match, meta._capability_match)

    def test_runtime_configure_payload_summary_wrapper_delegates(self) -> None:
        payload = {
            "project_name": "bridge-dogfood",
            "project_path": "/tmp/bridge-dogfood",
            "agent_a_engine": "claude",
            "agent_b_engine": "codex",
            "leader": {"name": "lead", "model": "claude-sonnet-4-6", "role": "lead"},
            "agents": [{"name": f"agent-{idx}", "model": "m", "role": "worker", "engine": "codex"} for idx in range(6)],
        }
        self.assertEqual(
            srv._runtime_configure_payload_summary(payload),
            meta.build_runtime_configure_payload_summary(payload),
        )

    def test_resolve_runtime_specs_uses_current_server_detect_available_engines(self) -> None:
        original_detect = srv._detect_available_engines
        original_resolve = meta.runtime_layout.resolve_runtime_specs
        seen: list[set[str]] = []
        try:
            srv._detect_available_engines = lambda: {"codex"}

            def fake_resolve_runtime_specs(*args, **kwargs):
                seen.append(set(kwargs.get("available_engines", set())))
                return []

            meta.runtime_layout.resolve_runtime_specs = fake_resolve_runtime_specs
            result = srv.resolve_runtime_specs("codex", "claude")
            self.assertEqual(result, [])
            self.assertEqual(seen, [{"codex"}])
        finally:
            meta.runtime_layout.resolve_runtime_specs = original_resolve
            srv._detect_available_engines = original_detect


if __name__ == "__main__":
    unittest.main()
