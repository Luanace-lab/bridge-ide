"""Tests for memory_constitution — precedence, classes, profiles, retrieval."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class TestSourcePrecedence(unittest.TestCase):
    """Test source precedence rules."""

    def test_precedence_order(self) -> None:
        from memory_constitution import precedence_level
        # Human explicit has highest priority (lowest number)
        self.assertEqual(precedence_level("human_explicit"), 1)
        self.assertEqual(precedence_level("cli_runtime"), 2)
        self.assertEqual(precedence_level("project_team_decision"), 3)
        self.assertEqual(precedence_level("agent_local_memory"), 4)
        self.assertEqual(precedence_level("durable_knowledge"), 5)
        self.assertEqual(precedence_level("semantic_recall"), 6)

    def test_unknown_source_lowest_priority(self) -> None:
        from memory_constitution import precedence_level
        self.assertEqual(precedence_level("unknown_source"), 99)

    def test_human_always_wins(self) -> None:
        from memory_constitution import precedence_level
        human = precedence_level("human_explicit")
        for source in ["cli_runtime", "project_team_decision", "agent_local_memory", "durable_knowledge", "semantic_recall"]:
            self.assertLess(human, precedence_level(source))

    def test_six_levels_defined(self) -> None:
        from memory_constitution import SOURCE_PRECEDENCE
        self.assertEqual(len(SOURCE_PRECEDENCE), 6)


class TestMemoryClasses(unittest.TestCase):
    """Test memory class definitions."""

    def test_three_classes_defined(self) -> None:
        from memory_constitution import MEMORY_CLASSES
        self.assertEqual(len(MEMORY_CLASSES), 3)

    def test_class_names(self) -> None:
        from memory_constitution import (
            MEMORY_CLASS_AGENT_LOCAL,
            MEMORY_CLASS_SHARED_COORDINATION,
            MEMORY_CLASS_DURABLE_KNOWLEDGE,
        )
        self.assertEqual(MEMORY_CLASS_AGENT_LOCAL, "agent_local")
        self.assertEqual(MEMORY_CLASS_SHARED_COORDINATION, "shared_coordination")
        self.assertEqual(MEMORY_CLASS_DURABLE_KNOWLEDGE, "durable_knowledge")

    def test_each_class_has_systems(self) -> None:
        from memory_constitution import MEMORY_CLASSES
        for name, cls in MEMORY_CLASSES.items():
            self.assertIn("systems", cls, f"{name} missing systems")
            self.assertIsInstance(cls["systems"], list)
            self.assertGreater(len(cls["systems"]), 0)

    def test_durable_knowledge_no_ttl(self) -> None:
        from memory_constitution import MEMORY_CLASSES, MEMORY_CLASS_DURABLE_KNOWLEDGE
        self.assertIsNone(MEMORY_CLASSES[MEMORY_CLASS_DURABLE_KNOWLEDGE]["default_ttl_days"])


class TestRoleProfiles(unittest.TestCase):
    """Test role persistence profiles."""

    def test_config_file_valid(self) -> None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "role_memory_profiles.json",
        )
        with open(config_path) as f:
            data = json.load(f)
        profiles = {k: v for k, v in data.items() if k != "_meta"}
        self.assertGreater(len(profiles), 7)

    def test_get_role_profile_known(self) -> None:
        from memory_constitution import get_role_profile
        profile = get_role_profile("backend")
        self.assertIn("retrieval_weights", profile)
        self.assertIn("preferred_kinds", profile)
        self.assertEqual(profile["retrieval_weights"]["durable_knowledge"], 0.5)

    def test_get_role_profile_unknown_falls_back(self) -> None:
        from memory_constitution import get_role_profile
        profile = get_role_profile("underwater_basket_weaver")
        # Falls back to senior
        self.assertIn("retrieval_weights", profile)

    def test_weights_sum_to_one(self) -> None:
        from memory_constitution import load_role_profiles
        profiles = load_role_profiles()
        for role, profile in profiles.items():
            weights = profile.get("retrieval_weights", {})
            total = sum(weights.values())
            self.assertAlmostEqual(total, 1.0, places=2, msg=f"{role} weights sum to {total}")

    def test_load_role_profiles_skips_meta(self) -> None:
        from memory_constitution import load_role_profiles
        profiles = load_role_profiles()
        self.assertNotIn("_meta", profiles)

    def test_coordinator_prioritizes_shared(self) -> None:
        from memory_constitution import get_role_profile
        profile = get_role_profile("coordinator")
        weights = profile["retrieval_weights"]
        self.assertGreater(weights["shared_coordination"], weights["agent_local"])
        self.assertGreater(weights["shared_coordination"], weights["durable_knowledge"])

    def test_architect_prioritizes_durable(self) -> None:
        from memory_constitution import get_role_profile
        profile = get_role_profile("architect")
        weights = profile["retrieval_weights"]
        self.assertGreater(weights["durable_knowledge"], weights["agent_local"])
        self.assertGreater(weights["durable_knowledge"], weights["shared_coordination"])

    def test_security_until_resolved(self) -> None:
        from memory_constitution import get_role_profile
        profile = get_role_profile("security")
        self.assertEqual(profile["ttl_tendency"], "until_resolved")


class TestContextBridgeRules(unittest.TestCase):
    """Test context bridge and soul rules."""

    def test_context_bridge_purpose(self) -> None:
        from memory_constitution import CONTEXT_BRIDGE_RULES
        self.assertIn("Compress", CONTEXT_BRIDGE_RULES["purpose"])
        self.assertIn("Never store original truth", CONTEXT_BRIDGE_RULES["purpose"])

    def test_soul_purpose(self) -> None:
        from memory_constitution import SOUL_RULES
        self.assertIn("Stable identity", SOUL_RULES["purpose"])
        self.assertIn("project-specific", SOUL_RULES["purpose"])

    def test_soul_forbidden(self) -> None:
        from memory_constitution import SOUL_RULES
        forbidden = SOUL_RULES["forbidden_content"]
        self.assertTrue(any("Project-specific" in f for f in forbidden))
        self.assertTrue(any("Temporary roles" in f for f in forbidden))


class TestMemoryStatus(unittest.TestCase):
    """Test memory status function."""

    def test_status_returns_all_fields(self) -> None:
        from memory_constitution import memory_status
        status = memory_status("backend", "backend")
        self.assertEqual(status["agent_id"], "backend")
        self.assertEqual(status["role"], "backend")
        self.assertIn("profile", status)
        self.assertIn("memory_classes", status)
        self.assertEqual(status["precedence_levels"], 6)

    def test_status_resolves_agent_storage_from_team_json(self) -> None:
        from memory_constitution import memory_status

        with tempfile.TemporaryDirectory() as tmp:
            backend_dir = os.path.join(tmp, "Backend")
            os.makedirs(backend_dir, exist_ok=True)
            with open(os.path.join(backend_dir, "team.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "agents": [
                            {
                                "id": "ordo",
                                "home_dir": "/workspace/ordo-home",
                                "config_dir": "/configs/ordo",
                            }
                        ]
                    },
                    handle,
                )

            with patch(
                "memory_constitution.find_agent_memory_path",
                return_value="/configs/ordo/projects/x/memory/MEMORY.md",
            ):
                status = memory_status("ordo", role="coordinator", project_path=tmp)

        self.assertEqual(status["agent_home"], "/workspace/ordo-home")
        self.assertEqual(status["config_dir"], "/configs/ordo")
        self.assertEqual(status["resolved_memory_path"], "/configs/ordo/projects/x/memory/MEMORY.md")


class TestUnifiedRetrieval(unittest.TestCase):
    """Test unified memory retrieval."""

    def test_retrieve_returns_list(self) -> None:
        from memory_constitution import retrieve_for_agent
        results = retrieve_for_agent("test_agent", "test query", role="senior")
        self.assertIsInstance(results, list)

    def test_retrieve_respects_top_k(self) -> None:
        from memory_constitution import retrieve_for_agent
        results = retrieve_for_agent("test_agent", "test", role="senior", top_k=3)
        self.assertLessEqual(len(results), 3)

    def test_retrieve_with_role(self) -> None:
        from memory_constitution import retrieve_for_agent
        # Should not crash for any role
        for role in ["backend", "frontend", "coordinator", "security", "architect"]:
            results = retrieve_for_agent("test", "query", role=role)
            self.assertIsInstance(results, list)


class TestQueryAdapters(unittest.TestCase):
    """Exercise real adapter contracts against expected upstream shapes."""

    def test_query_agent_local_uses_real_signatures_and_memory_path(self) -> None:
        from memory_constitution import _query_agent_local

        fake_module = types.ModuleType("memory_engine")

        class FakeHit:
            def __init__(self) -> None:
                self.content = "local result"
                self.score = 0.91
                self.file = "/tmp/local.md"
                self.line_start = 7

        class FakeMemoryEngine:
            def __init__(self, base_path) -> None:
                self.base_path = base_path

            def search(self, query: str, agent_id: str, top_k: int = 5):
                self.called = (query, agent_id, top_k)
                return [FakeHit()]

        fake_module.MemoryEngine = FakeMemoryEngine

        with tempfile.TemporaryDirectory() as tmp:
            memory_path = os.path.join(tmp, "MEMORY.md")
            with open(memory_path, "w", encoding="utf-8") as handle:
                handle.write("Bridge Persistenz local memory hit")

            with patch.dict(sys.modules, {"memory_engine": fake_module}):
                with patch("memory_constitution._resolve_agent_storage", return_value=("/tmp/project", "")):
                    with patch("memory_constitution.find_agent_memory_path", return_value=memory_path):
                        results = _query_agent_local("codex", "Persistenz", "/tmp/project")

        self.assertGreaterEqual(len(results), 2)
        self.assertTrue(any(r["kind"] == "agent_memory" for r in results))
        self.assertTrue(any(r["kind"] == "cli_memory" for r in results))

    def test_query_shared_coordination_reads_searchresult_objects(self) -> None:
        from memory_constitution import _query_shared_coordination

        fake_module = types.ModuleType("shared_memory")

        class FakeHit:
            def __init__(self) -> None:
                self.content = "shared result"
                self.score = 0.73
                self.file = "/tmp/shared.md"
                self.line_start = 4

        class FakeSharedMemory:
            def __init__(self, base_path) -> None:
                self.base_path = base_path

            def search(self, query: str, top_k: int = 5):
                return [FakeHit()]

        fake_module.SharedMemory = FakeSharedMemory

        with patch.dict(sys.modules, {"shared_memory": fake_module}):
            results = _query_shared_coordination("coordination", "/tmp/project")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], "shared_topic")
        self.assertEqual(results[0]["metadata"]["file"], "/tmp/shared.md")

    def test_query_durable_knowledge_uses_search_notes(self) -> None:
        from memory_constitution import _query_durable_knowledge

        fake_module = types.ModuleType("knowledge_engine")

        def fake_search_notes(query: str):
            return {
                "results": [
                    {
                        "path": "Shared/architecture.md",
                        "matches": ["Persistence constitution", "Source precedence"],
                        "frontmatter": {"status": "done"},
                    }
                ]
            }

        fake_module.search_notes = fake_search_notes

        with patch.dict(sys.modules, {"knowledge_engine": fake_module}):
            results = _query_durable_knowledge("Persistence")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], "knowledge_note")
        self.assertIn("Persistence constitution", results[0]["content"])

    def test_query_semantic_uses_agent_search_contract(self) -> None:
        from memory_constitution import _query_semantic

        fake_module = types.ModuleType("semantic_memory")

        def fake_search(agent_id: str, query: str, top_k: int = 5, min_score: float = 0.3, alpha: float = 0.7):
            return {
                "results": [
                    {
                        "id": "chunk-1",
                        "text": "semantic result",
                        "hybrid_score": 0.66,
                    }
                ]
            }

        fake_module.search = fake_search

        with patch.dict(sys.modules, {"semantic_memory": fake_module}):
            results = _query_semantic("codex", "semantic")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], "semantic_chunk")
        self.assertEqual(results[0]["metadata"]["chunk_id"], "chunk-1")


if __name__ == "__main__":
    unittest.main()
