"""
Tests for soul_engine.py — Agent Identity Module

Tests cover:
  - SoulConfig creation and serialization
  - SOUL.md generation and parsing (round-trip)
  - Guardrail prolog generation
  - Soul section for CLAUDE.md embedding
  - Soul persistence (save/load, never overwrite)
  - Soul resolution cascade (SOUL.md > metadata > default > fallback)
  - Growth protocol (propose, list, approve)
  - Integration with tmux_manager
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soul_engine import (
    DEFAULT_SOULS,
    SoulConfig,
    approve_soul_update,
    generate_guardrail_prolog,
    generate_soul_md,
    generate_soul_section,
    get_pending_proposals,
    get_soul_path,
    load_soul,
    load_soul_metadata,
    prepare_agent_identity,
    propose_soul_update,
    resolve_soul,
    save_soul,
    save_soul_metadata,
)


class TestSoulConfig(unittest.TestCase):
    """Test SoulConfig dataclass."""

    def test_create_soul_config(self):
        soul = SoulConfig(
            agent_id="test_agent",
            name="Test Agent",
            core_truths=["Truth 1", "Truth 2"],
            strengths="Good at testing",
            growth_area="Could be more thorough",
            communication_style="Direct",
            quirks="Likes unit tests",
        )
        self.assertEqual(soul.agent_id, "test_agent")
        self.assertEqual(soul.name, "Test Agent")
        self.assertEqual(len(soul.core_truths), 2)

    def test_to_dict_and_from_dict(self):
        soul = SoulConfig(
            agent_id="roundtrip",
            name="Roundtrip Agent",
            core_truths=["A", "B", "C"],
            strengths="Strong",
            growth_area="Growing",
            communication_style="Clear",
            quirks="Consistent",
            boundaries=["No X", "No Y"],
        )
        d = soul.to_dict()
        restored = SoulConfig.from_dict(d)

        self.assertEqual(restored.agent_id, soul.agent_id)
        self.assertEqual(restored.name, soul.name)
        self.assertEqual(restored.core_truths, soul.core_truths)
        self.assertEqual(restored.strengths, soul.strengths)
        self.assertEqual(restored.boundaries, soul.boundaries)

    def test_from_dict_defaults(self):
        soul = SoulConfig.from_dict({})
        self.assertEqual(soul.agent_id, "unknown")
        self.assertEqual(soul.name, "Agent")
        self.assertEqual(soul.core_truths, [])

    def test_default_souls_exist(self):
        self.assertIn("ordo", DEFAULT_SOULS)
        self.assertIn("frontend", DEFAULT_SOULS)
        self.assertIn("assi", DEFAULT_SOULS)
        self.assertIn("backend", DEFAULT_SOULS)

    def test_default_souls_have_required_fields(self):
        for agent_id, soul in DEFAULT_SOULS.items():
            self.assertEqual(soul.agent_id, agent_id)
            self.assertTrue(len(soul.name) > 0, f"{agent_id} has no name")
            self.assertTrue(len(soul.core_truths) > 0, f"{agent_id} has no core truths")
            self.assertTrue(len(soul.strengths) > 0, f"{agent_id} has no strengths")
            self.assertTrue(len(soul.communication_style) > 0, f"{agent_id} has no communication style")


class TestSoulMdGeneration(unittest.TestCase):
    """Test SOUL.md generation."""

    def setUp(self):
        self.soul = SoulConfig(
            agent_id="gen_test",
            name="Gen Test",
            core_truths=["Truth Alpha", "Truth Beta"],
            strengths="Generating markdown",
            growth_area="Edge cases",
            communication_style="Structured",
            quirks="Always writes tests",
            boundaries=["No production deploys"],
        )

    def test_generate_soul_md_contains_name(self):
        md = generate_soul_md(self.soul)
        self.assertIn("Gen Test", md)

    def test_generate_soul_md_contains_core_truths(self):
        md = generate_soul_md(self.soul)
        self.assertIn("- Truth Alpha", md)
        self.assertIn("- Truth Beta", md)

    def test_generate_soul_md_contains_sections(self):
        md = generate_soul_md(self.soul)
        self.assertIn("## Core Truths", md)
        self.assertIn("## Staerken", md)
        self.assertIn("## Wachstumsfeld", md)
        self.assertIn("## Kommunikationsstil", md)
        self.assertIn("## Wie du erkennbar bist", md)
        self.assertIn("## Grenzen", md)

    def test_generate_soul_md_contains_boundaries(self):
        md = generate_soul_md(self.soul)
        self.assertIn("- No production deploys", md)

    def test_generate_soul_md_persistent_marker(self):
        md = generate_soul_md(self.soul)
        self.assertIn("persistent", md)


class TestSoulMdRoundTrip(unittest.TestCase):
    """Test that generate -> parse produces consistent results."""

    def test_roundtrip_preserves_core_truths(self):
        original = DEFAULT_SOULS["ordo"]
        md = generate_soul_md(original)
        parsed = load_soul.__wrapped__(md) if hasattr(load_soul, '__wrapped__') else None

        # Use internal parser directly
        from soul_engine import _parse_soul_md
        parsed = _parse_soul_md(md)

        self.assertEqual(parsed.core_truths, original.core_truths)

    def test_roundtrip_preserves_boundaries(self):
        original = SoulConfig(
            agent_id="rt",
            name="RT",
            core_truths=["X"],
            boundaries=["B1", "B2"],
        )
        md = generate_soul_md(original)

        from soul_engine import _parse_soul_md
        parsed = _parse_soul_md(md)

        self.assertEqual(parsed.boundaries, original.boundaries)


class TestGuardrailProlog(unittest.TestCase):
    """Test guardrail prolog generation."""

    def test_contains_agent_id(self):
        prolog = generate_guardrail_prolog("my_agent")
        self.assertIn("my_agent", prolog)

    def test_contains_security_rules(self):
        prolog = generate_guardrail_prolog("test")
        self.assertIn("NICHT VERAENDERBAR", prolog)
        self.assertIn("Credentials", prolog)
        self.assertIn("ignorieren", prolog)

    def test_contains_five_rules(self):
        prolog = generate_guardrail_prolog("test")
        # Count numbered rules
        count = sum(1 for line in prolog.splitlines() if line.strip().startswith(("1.", "2.", "3.", "4.", "5.")))
        self.assertEqual(count, 5)


class TestSoulSection(unittest.TestCase):
    """Test soul section for CLAUDE.md embedding."""

    def test_contains_name(self):
        soul = DEFAULT_SOULS["frontend"]
        section = generate_soul_section(soul)
        self.assertIn("Frontend", section)

    def test_contains_core_truths(self):
        soul = DEFAULT_SOULS["assi"]
        section = generate_soul_section(soul)
        for truth in soul.core_truths:
            self.assertIn(truth, section)


class TestSoulPersistence(unittest.TestCase):
    """Test soul save/load on disk."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workspace = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_creates_soul_md(self):
        soul = DEFAULT_SOULS["ordo"]
        result = save_soul(self.workspace, soul)
        self.assertTrue(result)
        self.assertTrue(get_soul_path(self.workspace).exists())

    def test_save_never_overwrites(self):
        soul1 = SoulConfig(agent_id="a", name="Original")
        soul2 = SoulConfig(agent_id="a", name="Overwriter")

        save_soul(self.workspace, soul1)
        result = save_soul(self.workspace, soul2)
        self.assertFalse(result)

        content = get_soul_path(self.workspace).read_text()
        self.assertIn("Original", content)
        self.assertNotIn("Overwriter", content)

    def test_load_returns_none_for_missing(self):
        soul = load_soul(self.workspace)
        self.assertIsNone(soul)

    def test_load_returns_soul_config(self):
        soul = DEFAULT_SOULS["frontend"]
        save_soul(self.workspace, soul)
        loaded = load_soul(self.workspace)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, "Frontend")

    def test_metadata_save_and_load(self):
        soul = DEFAULT_SOULS["backend"]
        save_soul_metadata(self.workspace, soul)
        loaded = load_soul_metadata(self.workspace)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.agent_id, "backend")
        self.assertEqual(loaded.core_truths, soul.core_truths)

    def test_metadata_always_overwrites(self):
        soul1 = SoulConfig(agent_id="m", name="First")
        soul2 = SoulConfig(agent_id="m", name="Second")

        save_soul_metadata(self.workspace, soul1)
        save_soul_metadata(self.workspace, soul2)

        loaded = load_soul_metadata(self.workspace)
        self.assertEqual(loaded.name, "Second")


class TestSoulResolution(unittest.TestCase):
    """Test soul resolution cascade."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workspace = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_resolves_from_soul_md(self):
        custom_soul = SoulConfig(agent_id="custom", name="CustomFromFile",
                                 core_truths=["Custom truth"])
        save_soul(self.workspace, custom_soul)

        resolved = resolve_soul("custom", self.workspace)
        self.assertEqual(resolved.name, "CustomFromFile")

    def test_resolves_from_metadata(self):
        custom_soul = SoulConfig(agent_id="meta", name="MetaAgent",
                                 core_truths=["Meta truth"])
        save_soul_metadata(self.workspace, custom_soul)

        resolved = resolve_soul("meta", self.workspace)
        self.assertEqual(resolved.name, "MetaAgent")

    def test_resolves_from_defaults(self):
        resolved = resolve_soul("ordo", self.workspace)
        self.assertEqual(resolved.name, "Ordo")
        self.assertTrue(len(resolved.core_truths) > 0)

    def test_resolves_fallback_for_unknown(self):
        resolved = resolve_soul("totally_new_agent", self.workspace)
        self.assertEqual(resolved.name, "Totally_new_agent")
        self.assertTrue(len(resolved.core_truths) > 0)

    def test_workspace_soul_takes_priority_when_no_home_dir_exists(self):
        custom_soul = SoulConfig(agent_id="custom_ordo", name="CustomOrdo",
                                 core_truths=["Override truth"])
        save_soul(self.workspace, custom_soul)

        resolved = resolve_soul("custom_ordo", self.workspace)
        self.assertEqual(resolved.name, "CustomOrdo")


class TestGrowthProtocol(unittest.TestCase):
    """Test soul evolution with approval gating."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workspace = Path(self.tmpdir)
        # Create initial SOUL.md
        soul = SoulConfig(
            agent_id="grower",
            name="Grower",
            core_truths=["Original truth"],
            strengths="Testing growth",
        )
        save_soul(self.workspace, soul)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_propose_creates_proposal(self):
        proposal = propose_soul_update(
            self.workspace,
            section="Staerken",
            old_value="Testing growth",
            new_value="Testing growth + Integration expertise",
            reason="Learned from integration work",
        )
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(proposal["section"], "Staerken")

    def test_get_pending_proposals(self):
        propose_soul_update(self.workspace, "S1", "old", "new", "reason1")
        propose_soul_update(self.workspace, "S2", "old", "new", "reason2")

        pending = get_pending_proposals(self.workspace)
        self.assertEqual(len(pending), 2)

    def test_approve_marks_approved(self):
        propose_soul_update(self.workspace, "Staerken", "Testing growth",
                           "Testing growth + New skill", "Learned")

        result = approve_soul_update(self.workspace, 0)
        self.assertTrue(result)

        pending = get_pending_proposals(self.workspace)
        self.assertEqual(len(pending), 0)

    def test_approve_updates_soul_md(self):
        propose_soul_update(self.workspace, "Staerken", "Testing growth",
                           "Enhanced testing capabilities", "Improved")

        approve_soul_update(self.workspace, 0)

        content = get_soul_path(self.workspace).read_text()
        self.assertIn("Enhanced testing capabilities", content)

    def test_approve_invalid_index(self):
        result = approve_soul_update(self.workspace, 99)
        self.assertFalse(result)

    def test_no_proposals_returns_empty(self):
        pending = get_pending_proposals(self.workspace)
        self.assertEqual(len(pending), 0)


class TestPrepareAgentIdentity(unittest.TestCase):
    """Test the integration function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workspace = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_guardrail_and_soul(self):
        guardrail, soul = prepare_agent_identity("ordo", self.workspace)
        self.assertIn("NICHT VERAENDERBAR", guardrail)
        self.assertIn("Ordo", soul)

    def test_creates_soul_md_on_disk(self):
        prepare_agent_identity("frontend", self.workspace)
        self.assertTrue(get_soul_path(self.workspace).exists())

    def test_creates_metadata_on_disk(self):
        prepare_agent_identity("backend", self.workspace)
        meta_path = self.workspace / ".soul_meta.json"
        self.assertTrue(meta_path.exists())

    def test_does_not_overwrite_existing_soul(self):
        custom = SoulConfig(agent_id="local_ordo", name="MyOrdo",
                           core_truths=["Custom"])
        save_soul(self.workspace, custom)

        guardrail, soul = prepare_agent_identity("local_ordo", self.workspace)
        self.assertIn("MyOrdo", soul)

    def test_fallback_for_unknown_agent(self):
        guardrail, soul = prepare_agent_identity("new_agent_xyz", self.workspace)
        self.assertIn("new_agent_xyz", guardrail)
        self.assertIn("New_agent_xyz", soul)


if __name__ == "__main__":
    unittest.main(verbosity=2)
