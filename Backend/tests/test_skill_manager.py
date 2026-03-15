"""
Tests for skill_manager.py — Skill Registry and MCP Server Management

Tests cover:
  - YAML frontmatter parsing
  - Skill discovery from filesystem
  - Skill loading and caching
  - Skill activation / deactivation
  - CLAUDE.md skills section generation
  - MCP server config loading
  - MCP server lifecycle (start, stop, health check)
  - Status reporting
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_manager import (
    MCPServerInfo,
    Skill,
    SkillManager,
    SkillSummary,
    _parse_frontmatter,
)


class TestFrontmatterParser(unittest.TestCase):
    """Test YAML frontmatter parsing."""

    def test_basic_frontmatter(self):
        content = """---
name: pdf
description: Read and write PDF files.
license: MIT
---

## PDF Operations

Instructions here.
"""
        fm, body = _parse_frontmatter(content)
        self.assertEqual(fm["name"], "pdf")
        self.assertEqual(fm["description"], "Read and write PDF files.")
        self.assertEqual(fm["license"], "MIT")
        self.assertIn("PDF Operations", body)

    def test_no_frontmatter(self):
        content = "# Just a markdown file\n\nNo frontmatter."
        fm, body = _parse_frontmatter(content)
        self.assertEqual(fm, {})
        self.assertEqual(body, content)

    def test_quoted_values(self):
        content = '---\nname: "test-skill"\nversion: \'1.0\'\n---\nBody.'
        fm, body = _parse_frontmatter(content)
        self.assertEqual(fm["name"], "test-skill")
        self.assertEqual(fm["version"], "1.0")

    def test_nested_metadata(self):
        content = """---
name: excel
metadata:
  author: bridge-platform
  version: "2.0"
---
Body text."""
        fm, body = _parse_frontmatter(content)
        self.assertIsInstance(fm["metadata"], dict)
        self.assertEqual(fm["metadata"]["author"], "bridge-platform")
        self.assertEqual(fm["metadata"]["version"], "2.0")

    def test_empty_content(self):
        fm, body = _parse_frontmatter("")
        self.assertEqual(fm, {})

    def test_unclosed_frontmatter(self):
        content = "---\nname: broken\nno closing delimiter"
        fm, body = _parse_frontmatter(content)
        self.assertEqual(fm, {})


class TestSkillSummary(unittest.TestCase):
    """Test SkillSummary data class."""

    def test_to_dict(self):
        s = SkillSummary(name="pdf", description="PDF operations")
        d = s.to_dict()
        self.assertEqual(d["name"], "pdf")
        self.assertEqual(d["description"], "PDF operations")


class TestSkill(unittest.TestCase):
    """Test Skill data class."""

    def test_to_dict(self):
        s = Skill(
            name="excel",
            description="Excel operations",
            license="MIT",
            full_content="Full body text here.",
            source_path="/skills/excel/SKILL.md",
        )
        d = s.to_dict()
        self.assertEqual(d["name"], "excel")
        self.assertEqual(d["content_length"], len("Full body text here."))
        self.assertNotIn("full_content", d)  # Not exposed in dict

    def test_to_summary(self):
        s = Skill(name="pdf", description="PDF ops", full_content="Long body...")
        summary = s.to_summary()
        self.assertIsInstance(summary, SkillSummary)
        self.assertEqual(summary.name, "pdf")


class TestSkillDiscovery(unittest.TestCase):
    """Test skill discovery from filesystem."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.skills_dir = Path(self.tmpdir) / "skills"
        self.skills_dir.mkdir()

        # Create test skills
        self._create_skill("pdf", "Read and write PDF files.")
        self._create_skill("excel", "Excel spreadsheet operations.")
        self._create_skill("email", "Send and receive emails.")

        self.manager = SkillManager(self.skills_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_skill(self, name: str, description: str):
        skill_dir = self.skills_dir / name
        skill_dir.mkdir()
        content = f"""---
name: {name}
description: {description}
license: MIT
---

## {name.title()} Operations

Full instructions for {name}.
"""
        (skill_dir / "SKILL.md").write_text(content)

    def test_list_skills(self):
        skills = self.manager.list_skills()
        self.assertEqual(len(skills), 3)
        names = [s.name for s in skills]
        self.assertIn("pdf", names)
        self.assertIn("excel", names)
        self.assertIn("email", names)

    def test_list_skills_sorted(self):
        skills = self.manager.list_skills()
        names = [s.name for s in skills]
        self.assertEqual(names, sorted(names))

    def test_get_skill(self):
        skill = self.manager.get_skill("pdf")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.name, "pdf")
        self.assertIn("Full instructions for pdf", skill.full_content)

    def test_get_skill_not_found(self):
        skill = self.manager.get_skill("nonexistent")
        self.assertIsNone(skill)

    def test_skill_caching(self):
        s1 = self.manager.get_skill("pdf")
        s2 = self.manager.get_skill("pdf")
        self.assertIs(s1, s2)  # Same object from cache

    def test_invalidate_cache(self):
        s1 = self.manager.get_skill("pdf")
        self.manager.invalidate_cache("pdf")
        s2 = self.manager.get_skill("pdf")
        self.assertIsNot(s1, s2)  # New object after invalidation

    def test_invalidate_all_cache(self):
        self.manager.get_skill("pdf")
        self.manager.get_skill("excel")
        self.manager.invalidate_cache()
        self.assertEqual(len(self.manager._skills_cache), 0)

    def test_empty_skills_dir(self):
        empty_dir = Path(self.tmpdir) / "empty"
        empty_dir.mkdir()
        mgr = SkillManager(empty_dir)
        self.assertEqual(mgr.list_skills(), [])

    def test_missing_skills_dir(self):
        mgr = SkillManager(Path(self.tmpdir) / "missing")
        self.assertEqual(mgr.list_skills(), [])

    def test_dir_without_skill_md_ignored(self):
        (self.skills_dir / "no_skill").mkdir()
        (self.skills_dir / "no_skill" / "README.md").write_text("Not a skill")
        skills = self.manager.list_skills()
        names = [s.name for s in skills]
        self.assertNotIn("no_skill", names)


class TestSkillActivation(unittest.TestCase):
    """Test skill activation and deactivation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.skills_dir = Path(self.tmpdir) / "skills"
        self.skills_dir.mkdir()

        # Create test skill
        skill_dir = self.skills_dir / "pdf"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: pdf\ndescription: PDF ops\n---\nPDF instructions."
        )

        self.manager = SkillManager(self.skills_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_activate_skill(self):
        self.assertTrue(self.manager.activate_skill("pdf", "alex"))

    def test_activate_nonexistent_skill(self):
        self.assertFalse(self.manager.activate_skill("missing", "alex"))

    def test_get_active_skills(self):
        self.manager.activate_skill("pdf", "alex")
        active = self.manager.get_active_skills("alex")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].name, "pdf")

    def test_get_active_skills_empty(self):
        active = self.manager.get_active_skills("alex")
        self.assertEqual(active, [])

    def test_deactivate_skill(self):
        self.manager.activate_skill("pdf", "alex")
        self.assertTrue(self.manager.deactivate_skill("pdf", "alex"))
        self.assertEqual(self.manager.get_active_skills("alex"), [])

    def test_deactivate_inactive_skill(self):
        self.assertFalse(self.manager.deactivate_skill("pdf", "alex"))

    def test_is_active(self):
        self.assertFalse(self.manager.is_active("pdf", "alex"))
        self.manager.activate_skill("pdf", "alex")
        self.assertTrue(self.manager.is_active("pdf", "alex"))


class TestSkillsSectionGeneration(unittest.TestCase):
    """Test CLAUDE.md skills section generation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.skills_dir = Path(self.tmpdir) / "skills"
        self.skills_dir.mkdir()

        for name, desc in [("pdf", "PDF ops"), ("excel", "Excel ops")]:
            skill_dir = self.skills_dir / name
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {desc}\n---\n"
                f"Full {name} instructions."
            )

        self.manager = SkillManager(self.skills_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_generate_with_no_active(self):
        section = self.manager.generate_skills_section("alex")
        self.assertIn("Available Skills", section)
        self.assertIn("pdf", section)
        self.assertIn("available", section)

    def test_generate_with_active_skill(self):
        self.manager.activate_skill("pdf", "alex")
        section = self.manager.generate_skills_section("alex")
        self.assertIn("ACTIVE", section)
        self.assertIn("Full pdf instructions", section)

    def test_generate_empty(self):
        mgr = SkillManager(Path(self.tmpdir) / "empty")
        section = mgr.generate_skills_section("alex")
        self.assertEqual(section, "")


class TestMCPServerConfig(unittest.TestCase):
    """Test MCP server configuration."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_mcp_server(self):
        mgr = SkillManager(Path(self.tmpdir) / "skills")
        mgr.add_mcp_server("bridge", "python3", ["/path/to/bridge_mcp.py"])
        servers = mgr.list_mcp_servers()
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0].name, "bridge")

    def test_load_mcp_config(self):
        config_path = Path(self.tmpdir) / ".mcp.json"
        config_path.write_text(json.dumps({
            "mcpServers": {
                "bridge": {
                    "command": "python3",
                    "args": ["/path/to/bridge_mcp.py"],
                    "env": {"BRIDGE_PORT": "9111"},
                }
            }
        }))

        mgr = SkillManager(
            Path(self.tmpdir) / "skills",
            mcp_config_path=config_path,
        )
        servers = mgr.list_mcp_servers()
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0].command, "python3")

    def test_load_invalid_mcp_config(self):
        config_path = Path(self.tmpdir) / ".mcp.json"
        config_path.write_text("not json")

        # Should not crash
        mgr = SkillManager(
            Path(self.tmpdir) / "skills",
            mcp_config_path=config_path,
        )
        self.assertEqual(mgr.list_mcp_servers(), [])


class TestMCPServerLifecycle(unittest.TestCase):
    """Test MCP server start/stop/health."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.manager = SkillManager(Path(self.tmpdir) / "skills")
        # Use 'sleep' as a test process
        self.manager.add_mcp_server("test_server", "sleep", ["300"])

    def tearDown(self):
        # Cleanup any started processes
        for name in list(self.manager._mcp_processes.keys()):
            self.manager.stop_mcp_server(name)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_start_server(self):
        self.assertTrue(self.manager.start_mcp_server("test_server"))
        server = self.manager._mcp_servers["test_server"]
        self.assertTrue(server.running)
        self.assertIsNotNone(server.pid)

    def test_start_unknown_server(self):
        self.assertFalse(self.manager.start_mcp_server("missing"))

    def test_stop_server(self):
        self.manager.start_mcp_server("test_server")
        self.assertTrue(self.manager.stop_mcp_server("test_server"))
        server = self.manager._mcp_servers["test_server"]
        self.assertFalse(server.running)

    def test_health_check(self):
        self.manager.start_mcp_server("test_server")
        self.assertTrue(self.manager.health_check_mcp("test_server"))

    def test_health_check_stopped(self):
        self.assertFalse(self.manager.health_check_mcp("test_server"))

    def test_health_check_unknown(self):
        self.assertFalse(self.manager.health_check_mcp("missing"))


class TestSkillManagerStatus(unittest.TestCase):
    """Test status reporting."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.skills_dir = Path(self.tmpdir) / "skills"
        self.skills_dir.mkdir()

        skill_dir = self.skills_dir / "pdf"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: pdf\ndescription: PDF ops\n---\nInstructions."
        )

        self.manager = SkillManager(self.skills_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_status(self):
        self.manager.activate_skill("pdf", "alex")
        status = self.manager.status()
        self.assertTrue(status["skills_dir_exists"])
        self.assertEqual(status["total_skills"], 1)
        self.assertIn("alex", status["active_skills"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
