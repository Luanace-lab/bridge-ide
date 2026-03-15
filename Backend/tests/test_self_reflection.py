"""
Tests for self_reflection.py — Self-Reflection and Memory Distillation

Tests cover:
  - Lesson dataclass (creation, to_dict, to_markdown)
  - ReflectionPrompt (generation, to_text)
  - GrowthProposal (creation, validation)
  - Reflection prompt generation (categories, context)
  - Lesson management (add, get, validation)
  - MEMORY.md persistence (read, write, append)
  - Distillation (needs check, input preparation, prompt generation)
  - Lesson parsing from MEMORY.md
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

from self_reflection import (
    LESSON_CATEGORIES,
    REFLECTION_QUESTIONS,
    GrowthProposal,
    Lesson,
    ReflectionPrompt,
    SelfReflection,
)
from persistence_utils import (
    ensure_agent_memory_file,
    find_agent_memory_path,
    resolve_agent_cli_layout,
)


class TestLesson(unittest.TestCase):
    """Test Lesson dataclass."""

    def test_create(self):
        l = Lesson(title="Test", content="Content", agent_id="a1")
        self.assertEqual(l.title, "Test")
        self.assertEqual(l.category, "general")
        self.assertGreater(l.created_at, 0)

    def test_to_dict(self):
        l = Lesson(
            title="Test", content="Content",
            category="technical", agent_id="a1",
        )
        d = l.to_dict()
        self.assertEqual(d["title"], "Test")
        self.assertEqual(d["category"], "technical")
        self.assertIn("created_at", d)

    def test_to_markdown(self):
        l = Lesson(
            title="Read Before Write",
            content="Always read code before modifying it.",
            category="technical",
            confidence=0.9,
            agent_id="alex",
            source_episodes=["ep_001"],
        )
        md = l.to_markdown()
        self.assertIn("### Read Before Write", md)
        self.assertIn("technical", md)
        self.assertIn("90%", md)
        self.assertIn("ep_001", md)


class TestReflectionPrompt(unittest.TestCase):
    """Test ReflectionPrompt dataclass."""

    def test_to_text(self):
        p = ReflectionPrompt(
            agent_id="alex",
            questions=["What did I learn?", "What went wrong?"],
            context="Worked on frontend refactor",
            session_duration=3600,
            tasks_completed=3,
        )
        text = p.to_text()
        self.assertIn("Session Reflection", text)
        self.assertIn("frontend refactor", text)
        self.assertIn("1.0 hours", text)
        self.assertIn("3", text)
        self.assertIn("What did I learn?", text)

    def test_to_text_minimal(self):
        p = ReflectionPrompt(agent_id="a1", questions=["Q1?"])
        text = p.to_text()
        self.assertIn("Q1?", text)


class TestGrowthProposal(unittest.TestCase):
    """Test GrowthProposal dataclass."""

    def test_create(self):
        g = GrowthProposal(
            agent_id="alex", category="strength",
            description="Good at code review",
            evidence="Caught 5 bugs in reviews",
        )
        self.assertEqual(g.category, "strength")
        self.assertEqual(g.confidence, 0.8)

    def test_to_dict(self):
        g = GrowthProposal(
            agent_id="a1", category="insight",
            description="Desc", evidence="Ev",
        )
        d = g.to_dict()
        self.assertEqual(d["category"], "insight")
        self.assertIn("confidence", d)


class TestReflectionPromptGeneration(unittest.TestCase):
    """Test reflection prompt generation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sr = SelfReflection(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_generate_all_categories(self):
        prompt = self.sr.generate_reflection_prompt("alex")
        self.assertGreater(len(prompt.questions), 0)
        # Should include questions from all categories
        total_expected = sum(len(qs) for qs in REFLECTION_QUESTIONS.values())
        self.assertEqual(len(prompt.questions), total_expected)

    def test_generate_specific_categories(self):
        prompt = self.sr.generate_reflection_prompt(
            "alex", categories=["technical"],
        )
        self.assertEqual(
            len(prompt.questions),
            len(REFLECTION_QUESTIONS["technical"]),
        )

    def test_generate_with_context(self):
        prompt = self.sr.generate_reflection_prompt(
            "alex", context="Built 3 modules",
            session_duration=7200, tasks_completed=5,
        )
        self.assertEqual(prompt.context, "Built 3 modules")
        self.assertEqual(prompt.session_duration, 7200)
        self.assertEqual(prompt.tasks_completed, 5)


class TestLessonManagement(unittest.TestCase):
    """Test lesson CRUD operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sr = SelfReflection(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_lesson(self):
        lesson = self.sr.add_lesson(
            "alex", "Read Before Write",
            "Always read code before modifying it.",
            category="technical",
        )
        self.assertEqual(lesson.title, "Read Before Write")
        self.assertEqual(lesson.agent_id, "alex")

    def test_add_lesson_persists(self):
        self.sr.add_lesson("alex", "Lesson 1", "Content 1")
        content = self.sr.read_memory("alex")
        self.assertIn("Lesson 1", content)
        self.assertIn("Content 1", content)

    def test_add_multiple_lessons(self):
        self.sr.add_lesson("alex", "Lesson 1", "Content 1")
        self.sr.add_lesson("alex", "Lesson 2", "Content 2")
        content = self.sr.read_memory("alex")
        self.assertIn("Lesson 1", content)
        self.assertIn("Lesson 2", content)

    def test_get_lessons(self):
        self.sr.add_lesson("alex", "L1", "C1", category="technical")
        self.sr.add_lesson("alex", "L2", "C2", category="process")
        lessons = self.sr.get_lessons("alex")
        self.assertEqual(len(lessons), 2)

    def test_get_lessons_by_category(self):
        self.sr.add_lesson("alex", "L1", "C1", category="technical")
        self.sr.add_lesson("alex", "L2", "C2", category="process")
        tech = self.sr.get_lessons("alex", category="technical")
        self.assertEqual(len(tech), 1)
        self.assertEqual(tech[0].title, "L1")

    def test_get_lessons_empty(self):
        lessons = self.sr.get_lessons("alex")
        self.assertEqual(lessons, [])

    def test_add_empty_title_raises(self):
        with self.assertRaises(ValueError):
            self.sr.add_lesson("alex", "", "Content")

    def test_add_empty_content_raises(self):
        with self.assertRaises(ValueError):
            self.sr.add_lesson("alex", "Title", "")

    def test_add_invalid_category_raises(self):
        with self.assertRaises(ValueError):
            self.sr.add_lesson("alex", "T", "C", category="invalid")

    def test_add_invalid_confidence_raises(self):
        with self.assertRaises(ValueError):
            self.sr.add_lesson("alex", "T", "C", confidence=1.5)


class TestMemoryManagement(unittest.TestCase):
    """Test MEMORY.md read/write."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sr = SelfReflection(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_empty(self):
        content = self.sr.read_memory("alex")
        self.assertEqual(content, "")

    def test_write_memory(self):
        result = self.sr.write_memory("alex", "# My Memory\n\nImportant stuff.")
        self.assertIn("path", result)
        self.assertGreater(result["size_bytes"], 0)
        self.assertEqual(self.sr.read_memory("alex"), "# My Memory\n\nImportant stuff.")

    def test_write_creates_dirs(self):
        sr = SelfReflection(Path(self.tmpdir) / "deep" / "nested")
        sr.write_memory("alex", "Content")
        self.assertEqual(sr.read_memory("alex"), "Content")


class TestCliSotMemoryManagement(unittest.TestCase):
    """Regression: reflection memory must use the CLI SoT path when available."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.backend_dir = Path(self.tmpdir) / "Backend"
        self.backend_dir.mkdir()
        self.agent_home = Path(self.tmpdir) / "workspace" / ".agent_sessions" / "alex"
        self.agent_home.mkdir(parents=True)
        self.config_dir = Path(self.tmpdir) / ".claude-agent-alex"
        self.agent_config = {
            "id": "alex",
            "role": "agent",
            "home_dir": str(self.agent_home),
            "config_dir": str(self.config_dir),
        }
        team_payload = {
            "agents": [self.agent_config],
        }
        self.team_path = self.backend_dir / "team.json"
        self.team_path.write_text(
            json.dumps(team_payload),
            encoding="utf-8",
        )
        self.sr = SelfReflection(
            self.backend_dir,
            agent_configs={"alex": self.agent_config},
        )
        self.legacy_path = self.backend_dir / "agents" / "alex" / "MEMORY.md"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _canonical_path(self) -> Path:
        path = find_agent_memory_path(
            "alex",
            str(self.agent_home),
            str(self.config_dir),
        )
        return Path(path) if path else Path()

    def test_read_memory_prefers_cli_sot_path(self):
        canonical_path = Path(
            ensure_agent_memory_file(
                "alex",
                "agent",
                str(self.agent_home),
                str(self.config_dir),
            ),
        )
        canonical_path.write_text("canonical", encoding="utf-8")
        self.legacy_path.parent.mkdir(parents=True, exist_ok=True)
        self.legacy_path.write_text("legacy", encoding="utf-8")

        self.assertEqual(self.sr.read_memory("alex"), "canonical")

    def test_write_memory_uses_cli_sot_path(self):
        result = self.sr.write_memory("alex", "cli-sot")
        canonical_path = self._canonical_path()

        self.assertTrue(canonical_path.is_file())
        self.assertEqual(result["path"], str(canonical_path))
        self.assertEqual(canonical_path.read_text(encoding="utf-8"), "cli-sot")
        self.assertFalse(self.legacy_path.exists())

    def test_add_lesson_uses_cli_sot_path(self):
        self.sr.add_lesson("alex", "CLI", "Persist to canonical memory")
        canonical_path = self._canonical_path()
        content = canonical_path.read_text(encoding="utf-8")

        self.assertIn("### CLI", content)
        self.assertIn("Persist to canonical memory", content)
        self.assertFalse(self.legacy_path.exists())

    def test_status_reports_cli_sot_memory(self):
        self.sr.write_memory("alex", "status-memory")

        status = self.sr.status()

        self.assertIn("alex", status["agents_with_memory"])
        self.assertGreater(status["memory_sizes"]["alex"], 0)

    def test_explicit_agent_config_wins_over_team_lookup(self):
        stale_team_payload = {
            "agents": [
                {
                    "id": "alex",
                    "role": "agent",
                    "home_dir": str(self.backend_dir / "stale-home"),
                    "config_dir": str(self.backend_dir / "stale-config"),
                },
            ],
        }
        self.team_path.write_text(
            json.dumps(stale_team_payload),
            encoding="utf-8",
        )

        result = self.sr.write_memory("alex", "explicit-config")

        self.assertEqual(result["path"], str(self._canonical_path()))
        self.assertEqual(
            self._canonical_path().read_text(encoding="utf-8"),
            "explicit-config",
        )

    def test_team_json_fallback_still_uses_cli_sot_path(self):
        sr = SelfReflection(self.backend_dir)

        result = sr.write_memory("alex", "team-fallback")

        self.assertEqual(result["path"], str(self._canonical_path()))


class TestCliSotCanonicalWorkspaceMemoryPath(unittest.TestCase):
    """Regression: project-root homes must still resolve memory via CLI workspace."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.backend_dir = Path(self.tmpdir) / "Backend"
        self.backend_dir.mkdir()
        self.project_home = Path(self.tmpdir) / "project-home"
        self.project_home.mkdir()
        self.config_dir = Path(self.tmpdir) / ".claude-agent-alex"
        self.agent_config = {
            "id": "alex",
            "role": "agent",
            "home_dir": str(self.project_home),
            "config_dir": str(self.config_dir),
        }
        self.sr = SelfReflection(
            self.backend_dir,
            agent_configs={"alex": self.agent_config},
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _mangle(self, cwd: str) -> str:
        return cwd.replace("/", "-").replace(".", "-").replace("_", "-")

    def test_write_memory_uses_workspace_mangled_cli_path(self):
        layout = resolve_agent_cli_layout(str(self.project_home), "alex")
        expected = Path(layout["workspace"]) / "MEMORY.md"
        legacy_root = (
            self.config_dir
            / "projects"
            / self._mangle(str(self.project_home))
            / "memory"
            / "MEMORY.md"
        )

        result = self.sr.write_memory("alex", "workspace-canonical")

        self.assertEqual(result["path"], str(expected))
        self.assertTrue(expected.is_file())
        self.assertEqual(expected.read_text(encoding="utf-8"), "workspace-canonical")
        self.assertFalse(legacy_root.exists())


class TestRuntimeAgentStateCliMemoryFallback(unittest.TestCase):
    """Runtime agents outside team.json must still resolve to workspace memory."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.backend_dir = Path(self.tmpdir) / "Backend"
        self.backend_dir.mkdir()
        self.workspace = Path(self.tmpdir) / "project" / ".agent_sessions" / "codex_a"
        self.workspace.mkdir(parents=True)
        agent_state_dir = self.backend_dir / "agent_state"
        agent_state_dir.mkdir()
        agent_state_dir.joinpath("codex_a.json").write_text(
            json.dumps(
                {
                    "agent_id": "codex_a",
                    "role": "Agent A",
                    "home_dir": str(self.workspace),
                    "workspace": str(self.workspace),
                    "project_root": str(self.workspace.parent.parent),
                    "cli_identity_source": "cli_register",
                },
            ),
            encoding="utf-8",
        )
        self.sr = SelfReflection(self.backend_dir)
        self.expected_path = self.workspace / "MEMORY.md"
        self.legacy_path = self.backend_dir / "agents" / "codex_a" / "MEMORY.md"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_memory_uses_runtime_agent_state_workspace_path(self):
        result = self.sr.write_memory("codex_a", "runtime-memory")

        self.assertEqual(result["path"], str(self.expected_path))
        self.assertTrue(self.expected_path.is_file())
        self.assertEqual(
            self.expected_path.read_text(encoding="utf-8"),
            "runtime-memory",
        )
        self.assertFalse(self.legacy_path.exists())

    def test_add_lesson_uses_runtime_agent_state_workspace_path(self):
        self.sr.add_lesson(
            "codex_a",
            "Runtime lesson",
            "Persist through runtime agent_state fallback",
            category="technical",
        )

        content = self.expected_path.read_text(encoding="utf-8")
        self.assertIn("### Runtime lesson", content)
        self.assertIn("Persist through runtime agent_state fallback", content)
        self.assertFalse(self.legacy_path.exists())


class TestDistillation(unittest.TestCase):
    """Test distillation workflow."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sr = SelfReflection(Path(self.tmpdir))
        # Create episodes directory with test data
        self.episodes_dir = Path(self.tmpdir) / "episodes"
        self.episodes_dir.mkdir(parents=True)
        index_path = self.episodes_dir / "index.jsonl"
        episodes = [
            {
                "agent_id": "alex",
                "task": "Fix login bug",
                "summary": "Found race condition in auth module",
                "timestamp": "2026-02-20T10:00:00Z",
                "bullets": ["Identified mutex issue", "Added lock"],
            },
            {
                "agent_id": "alex",
                "task": "Add user settings",
                "summary": "Implemented settings page with persistence",
                "timestamp": "2026-02-21T14:00:00Z",
                "bullets": ["Used localStorage", "Added validation"],
            },
            {
                "agent_id": "blake",
                "task": "Deploy v2",
                "summary": "Deployed to production",
                "timestamp": "2026-02-21T16:00:00Z",
            },
        ]
        with open(index_path, "w") as f:
            for ep in episodes:
                f.write(json.dumps(ep) + "\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_needs_distillation_first_time(self):
        self.assertTrue(self.sr.needs_distillation("alex"))

    def test_needs_distillation_after_mark(self):
        self.sr.mark_distilled("alex")
        self.assertFalse(self.sr.needs_distillation("alex", interval_hours=24))

    def test_prepare_input(self):
        inp = self.sr.prepare_distillation_input("alex", self.episodes_dir)
        self.assertEqual(inp["agent_id"], "alex")
        self.assertEqual(inp["episode_count"], 2)  # Only alex's episodes
        self.assertIn("Fix login bug", inp["episodes_text"])
        self.assertIn("Add user settings", inp["episodes_text"])

    def test_prepare_input_empty(self):
        empty_dir = Path(self.tmpdir) / "empty_ep"
        empty_dir.mkdir()
        inp = self.sr.prepare_distillation_input("alex", empty_dir)
        self.assertEqual(inp["episode_count"], 0)

    def test_generate_distillation_prompt(self):
        inp = self.sr.prepare_distillation_input("alex", self.episodes_dir)
        prompt = self.sr.generate_distillation_prompt(inp)
        self.assertIn("alex", prompt)
        self.assertIn("2 episodes", prompt)
        self.assertIn("Fix login bug", prompt)

    def test_generate_distillation_prompt_empty(self):
        empty_dir = Path(self.tmpdir) / "empty_ep"
        empty_dir.mkdir()
        inp = self.sr.prepare_distillation_input("alex", empty_dir)
        prompt = self.sr.generate_distillation_prompt(inp)
        self.assertEqual(prompt, "")


class TestGrowthProposalGeneration(unittest.TestCase):
    """Test growth proposal generation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sr = SelfReflection(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_generate_proposal(self):
        g = self.sr.generate_growth_proposal(
            "alex", "strength",
            "Good at debugging race conditions",
            "Fixed 3 race conditions this week",
        )
        self.assertEqual(g.category, "strength")
        self.assertEqual(g.agent_id, "alex")

    def test_invalid_category_raises(self):
        with self.assertRaises(ValueError):
            self.sr.generate_growth_proposal(
                "alex", "invalid", "desc", "evidence",
            )

    def test_empty_description_raises(self):
        with self.assertRaises(ValueError):
            self.sr.generate_growth_proposal(
                "alex", "strength", "", "evidence",
            )

    def test_empty_evidence_raises(self):
        with self.assertRaises(ValueError):
            self.sr.generate_growth_proposal(
                "alex", "strength", "desc", "",
            )


class TestLessonParsing(unittest.TestCase):
    """Test parsing lessons from MEMORY.md content."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sr = SelfReflection(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_parse_roundtrip(self):
        self.sr.add_lesson(
            "alex", "Always Read First",
            "Read code before modifying it.",
            category="technical", confidence=0.9,
        )
        lessons = self.sr.get_lessons("alex")
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0].title, "Always Read First")
        self.assertEqual(lessons[0].category, "technical")

    def test_parse_multiple(self):
        self.sr.add_lesson("alex", "L1", "C1", category="technical")
        self.sr.add_lesson("alex", "L2", "C2", category="process")
        self.sr.add_lesson("alex", "L3", "C3", category="collaboration")
        lessons = self.sr.get_lessons("alex")
        self.assertEqual(len(lessons), 3)
        titles = [l.title for l in lessons]
        self.assertEqual(titles, ["L1", "L2", "L3"])


class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sr = SelfReflection(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_status_empty(self):
        s = self.sr.status()
        self.assertEqual(s["agents_with_memory"], [])
        self.assertIn("reflection_categories", s)
        self.assertIn("lesson_categories", s)

    def test_status_with_memory(self):
        self.sr.add_lesson("alex", "L1", "C1")
        s = self.sr.status()
        self.assertIn("alex", s["agents_with_memory"])
        self.assertGreater(s["memory_sizes"]["alex"], 0)


class TestConstants(unittest.TestCase):
    """Test module constants."""

    def test_reflection_categories(self):
        self.assertIn("technical", REFLECTION_QUESTIONS)
        self.assertIn("collaboration", REFLECTION_QUESTIONS)
        self.assertIn("process", REFLECTION_QUESTIONS)
        self.assertIn("general", REFLECTION_QUESTIONS)

    def test_lesson_categories(self):
        self.assertIn("general", LESSON_CATEGORIES)
        self.assertIn("technical", LESSON_CATEGORIES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
