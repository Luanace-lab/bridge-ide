"""Tests for Skill-MCP integration — skill_mcp_map, resolve, suggest."""

from __future__ import annotations

import json
import os
import unittest


class TestSkillMcpMap(unittest.TestCase):
    """Test skill_mcp_map.json structure and validity."""

    def test_map_is_valid_json(self) -> None:
        map_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "skill_mcp_map.json",
        )
        with open(map_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)
        skills = {k: v for k, v in data.items() if k != "_meta"}
        self.assertGreater(len(skills), 15)

    def test_all_referenced_mcps_exist_in_catalog(self) -> None:
        from mcp_catalog import runtime_mcp_specs, _load_skill_mcp_map

        skill_map = _load_skill_mcp_map()
        catalog = runtime_mcp_specs()
        catalog_names = set(catalog.keys())

        missing = []
        for skill_id, entry in skill_map.items():
            for mcp in entry.get("preferred_mcps", []):
                if mcp not in catalog_names:
                    missing.append(f"{skill_id} → {mcp}")

        self.assertEqual(missing, [], f"MCPs not in catalog: {missing}")

    def test_every_entry_has_required_fields(self) -> None:
        from mcp_catalog import _load_skill_mcp_map

        skill_map = _load_skill_mcp_map()
        for skill_id, entry in skill_map.items():
            self.assertIn("summary", entry, f"{skill_id} missing summary")
            self.assertIn("preferred_mcps", entry, f"{skill_id} missing preferred_mcps")
            self.assertIsInstance(entry["preferred_mcps"], list, f"{skill_id} preferred_mcps not list")
            self.assertIn("auto_attach", entry, f"{skill_id} missing auto_attach")


class TestResolveMcpsForSkills(unittest.TestCase):
    """Test resolve_mcps_for_skills function."""

    def test_qa_expert_gets_playwright(self) -> None:
        from mcp_catalog import resolve_mcps_for_skills
        mcps = resolve_mcps_for_skills(["qa-expert"])
        self.assertIn("playwright", mcps)
        self.assertIn("bridge", mcps)

    def test_bridge_agent_core_gets_bridge(self) -> None:
        from mcp_catalog import resolve_mcps_for_skills
        mcps = resolve_mcps_for_skills(["bridge-agent-core"])
        self.assertIn("bridge", mcps)

    def test_security_gets_aase(self) -> None:
        from mcp_catalog import resolve_mcps_for_skills
        mcps = resolve_mcps_for_skills(["security-scanner"])
        self.assertIn("aase", mcps)

    def test_empty_skills_returns_empty(self) -> None:
        from mcp_catalog import resolve_mcps_for_skills
        self.assertEqual(resolve_mcps_for_skills([]), [])

    def test_unknown_skill_returns_empty(self) -> None:
        from mcp_catalog import resolve_mcps_for_skills
        self.assertEqual(resolve_mcps_for_skills(["nonexistent-skill"]), [])

    def test_non_auto_attach_excluded(self) -> None:
        from mcp_catalog import resolve_mcps_for_skills
        # deep-research has auto_attach: false
        mcps = resolve_mcps_for_skills(["deep-research"])
        self.assertEqual(mcps, [])

    def test_multiple_skills_merge(self) -> None:
        from mcp_catalog import resolve_mcps_for_skills
        mcps = resolve_mcps_for_skills(["qa-expert", "security-scanner", "bridge-agent-core"])
        self.assertIn("playwright", mcps)
        self.assertIn("aase", mcps)
        self.assertIn("bridge", mcps)
        # Should be deduplicated
        self.assertEqual(len(mcps), len(set(mcps)))


class TestSuggestMcpsForTask(unittest.TestCase):
    """Test task-based MCP suggestion."""

    def test_testing_task_suggests_qa(self) -> None:
        from mcp_catalog import suggest_mcps_for_task
        result = suggest_mcps_for_task("test the login page", ["qa-expert", "bridge-agent-core"])
        self.assertIn("qa-expert", result["relevant_skills"])
        self.assertIn("playwright", result["attached_mcps"])

    def test_security_task_suggests_scanner(self) -> None:
        from mcp_catalog import suggest_mcps_for_task
        result = suggest_mcps_for_task("scan for vulnerabilities", ["security-scanner"])
        self.assertIn("security-scanner", result["relevant_skills"])
        self.assertIn("aase", result["attached_mcps"])

    def test_unrelated_task_returns_empty(self) -> None:
        from mcp_catalog import suggest_mcps_for_task
        result = suggest_mcps_for_task("cook dinner", ["qa-expert"])
        self.assertEqual(result["relevant_skills"], [])


if __name__ == "__main__":
    unittest.main()
