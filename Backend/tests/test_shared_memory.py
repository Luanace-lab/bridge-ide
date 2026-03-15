"""
Tests for shared_memory.py — Shared Memory Layer (Blackboard Pattern)

Tests cover:
  - Topic validation
  - Write operations (append, replace, validation)
  - Read operations (topic, project files)
  - Search (BM25 across topics)
  - Topic management (list, exists, delete)
  - Author/timestamp tracking
  - Scaffold creation
  - Status reporting
  - Thread safety
"""

import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared_memory import (
    MAX_CONTENT_LENGTH,
    MAX_TOPIC_LENGTH,
    SharedMemory,
    TopicContent,
    TopicEntry,
    TopicInfo,
)


class TestTopicEntry(unittest.TestCase):
    """Test TopicEntry dataclass."""

    def test_to_markdown(self):
        entry = TopicEntry(author="alex", timestamp="2026-01-01T00:00:00Z", content="Hello")
        md = entry.to_markdown()
        self.assertIn("**Author:** alex", md)
        self.assertIn("**Timestamp:** 2026-01-01T00:00:00Z", md)
        self.assertIn("Hello", md)


class TestTopicInfo(unittest.TestCase):
    """Test TopicInfo dataclass."""

    def test_to_dict(self):
        info = TopicInfo(
            name="decisions", path="/tmp/decisions.md",
            size_bytes=1024, last_modified=1000.0, last_author="alex",
        )
        d = info.to_dict()
        self.assertEqual(d["name"], "decisions")
        self.assertEqual(d["size_bytes"], 1024)
        self.assertEqual(d["last_author"], "alex")


class TestTopicContent(unittest.TestCase):
    """Test TopicContent dataclass."""

    def test_to_dict(self):
        tc = TopicContent(
            topic="arch", content="# Arch", last_updated="T",
            updated_by="alex", size_bytes=6,
        )
        d = tc.to_dict()
        self.assertEqual(d["topic"], "arch")
        self.assertEqual(d["content"], "# Arch")


class TestTopicValidation(unittest.TestCase):
    """Test topic name validation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = SharedMemory(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_valid_topic(self):
        # Should not raise
        self.sm.write("my-topic_123", "content", "alex")

    def test_empty_topic_raises(self):
        with self.assertRaises(ValueError):
            self.sm.write("", "content", "alex")

    def test_topic_too_long(self):
        with self.assertRaises(ValueError):
            self.sm.write("x" * (MAX_TOPIC_LENGTH + 1), "content", "alex")

    def test_invalid_chars_raises(self):
        with self.assertRaises(ValueError):
            self.sm.write("My Topic!", "content", "alex")

    def test_uppercase_raises(self):
        with self.assertRaises(ValueError):
            self.sm.write("MyTopic", "content", "alex")


class TestWrite(unittest.TestCase):
    """Test write operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = SharedMemory(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_append(self):
        result = self.sm.write("decisions", "First decision", "alex")
        self.assertEqual(result["topic"], "decisions")
        self.assertEqual(result["mode"], "append")
        self.assertEqual(result["author"], "alex")
        self.assertIn("timestamp", result)
        self.assertGreater(result["size_bytes"], 0)

    def test_write_append_accumulates(self):
        self.sm.write("decisions", "Decision 1", "alex")
        self.sm.write("decisions", "Decision 2", "blake")
        tc = self.sm.read("decisions")
        self.assertIn("Decision 1", tc.content)
        self.assertIn("Decision 2", tc.content)

    def test_write_replace(self):
        self.sm.write("decisions", "Old content", "alex")
        self.sm.write("decisions", "New content", "blake", mode="replace")
        tc = self.sm.read("decisions")
        self.assertNotIn("Old content", tc.content)
        self.assertIn("New content", tc.content)

    def test_write_empty_content_raises(self):
        with self.assertRaises(ValueError):
            self.sm.write("test", "", "alex")

    def test_write_content_too_long(self):
        with self.assertRaises(ValueError):
            self.sm.write("test", "x" * (MAX_CONTENT_LENGTH + 1), "alex")

    def test_write_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            self.sm.write("test", "content", "alex", mode="invalid")

    def test_write_creates_directory(self):
        sm = SharedMemory(Path(self.tmpdir) / "deep" / "nested")
        sm.write("test", "content", "alex")
        tc = sm.read("test")
        self.assertIsNotNone(tc)

    def test_write_author_tracking(self):
        self.sm.write("log", "Entry 1", "alex")
        self.sm.write("log", "Entry 2", "blake")
        tc = self.sm.read("log")
        self.assertEqual(tc.updated_by, "blake")


class TestRead(unittest.TestCase):
    """Test read operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = SharedMemory(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_existing(self):
        self.sm.write("arch", "Architecture notes", "alex")
        tc = self.sm.read("arch")
        self.assertIsNotNone(tc)
        self.assertEqual(tc.topic, "arch")
        self.assertIn("Architecture notes", tc.content)
        self.assertGreater(tc.size_bytes, 0)

    def test_read_not_found(self):
        tc = self.sm.read("nonexistent")
        self.assertIsNone(tc)

    def test_read_project(self):
        project_dir = Path(self.tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "DECISIONS.md").write_text("# Decisions\n- Use Python")
        content = self.sm.read_project("DECISIONS.md")
        self.assertIsNotNone(content)
        self.assertIn("Use Python", content)

    def test_read_project_not_found(self):
        content = self.sm.read_project("MISSING.md")
        self.assertIsNone(content)


class TestSearch(unittest.TestCase):
    """Test BM25 search across shared topics."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = SharedMemory(Path(self.tmpdir))
        # Create topics with distinct content
        self.sm.write("database", "PostgreSQL schema with users table and transactions table", "alex")
        self.sm.write("frontend", "React components with TypeScript and CSS modules", "blake")
        self.sm.write("deployment", "Docker containers with Kubernetes orchestration", "charlie")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_search_finds_relevant(self):
        results = self.sm.search("PostgreSQL database schema")
        self.assertGreater(len(results), 0)
        # database topic should rank highest
        self.assertIn("database", results[0].file)

    def test_search_empty_query(self):
        results = self.sm.search("")
        self.assertEqual(results, [])

    def test_search_no_match(self):
        results = self.sm.search("quantum physics black hole")
        # May return results with low scores, or empty
        if results:
            self.assertLess(results[0].score, 5.0)

    def test_search_top_k(self):
        results = self.sm.search("table", top_k=1)
        self.assertLessEqual(len(results), 1)

    def test_search_includes_project(self):
        project_dir = Path(self.tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "PROJECT.md").write_text("# Project\nUses PostgreSQL database")
        self.sm.invalidate_index()
        results = self.sm.search("PostgreSQL", top_k=10)
        files = [r.file for r in results]
        has_project = any("project" in f for f in files)
        self.assertTrue(has_project)

    def test_search_excludes_project(self):
        project_dir = Path(self.tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "PROJECT.md").write_text("# Project\nUses PostgreSQL database")
        self.sm.invalidate_index()
        results = self.sm.search("PostgreSQL", top_k=10, include_project=False)
        files = [r.file for r in results]
        has_project = any("project" in f for f in files)
        self.assertFalse(has_project)


class TestTopicManagement(unittest.TestCase):
    """Test topic listing, existence, deletion."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = SharedMemory(Path(self.tmpdir))
        self.sm.write("alpha", "Content A", "alex")
        self.sm.write("beta", "Content B", "blake")
        self.sm.write("gamma", "Content C", "charlie")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_topics(self):
        topics = self.sm.list_topics()
        self.assertEqual(len(topics), 3)
        names = [t.name for t in topics]
        self.assertEqual(names, ["alpha", "beta", "gamma"])  # Sorted

    def test_list_topics_empty(self):
        sm = SharedMemory(Path(self.tmpdir) / "empty")
        topics = sm.list_topics()
        self.assertEqual(topics, [])

    def test_topic_exists(self):
        self.assertTrue(self.sm.topic_exists("alpha"))
        self.assertFalse(self.sm.topic_exists("missing"))

    def test_delete_topic(self):
        self.assertTrue(self.sm.delete_topic("beta"))
        self.assertFalse(self.sm.topic_exists("beta"))
        topics = self.sm.list_topics()
        self.assertEqual(len(topics), 2)

    def test_delete_not_found(self):
        self.assertFalse(self.sm.delete_topic("missing"))

    def test_topic_info_has_author(self):
        topics = self.sm.list_topics()
        alpha = [t for t in topics if t.name == "alpha"][0]
        self.assertEqual(alpha.last_author, "alex")


class TestScaffold(unittest.TestCase):
    """Test scaffold creation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scaffold_creates_dirs(self):
        sm = SharedMemory(Path(self.tmpdir) / "new_project")
        result = sm.scaffold()
        self.assertTrue(any(v for v in result.values()))
        self.assertTrue((Path(self.tmpdir) / "new_project" / "shared").exists())
        self.assertTrue((Path(self.tmpdir) / "new_project" / "project").exists())

    def test_scaffold_idempotent(self):
        sm = SharedMemory(Path(self.tmpdir) / "project")
        sm.scaffold()
        result = sm.scaffold()
        # All False (already existed)
        self.assertTrue(all(not v for v in result.values()))


class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = SharedMemory(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_status_empty(self):
        s = self.sm.status()
        self.assertEqual(s["total_topics"], 0)
        self.assertEqual(s["total_bytes"], 0)

    def test_status_with_topics(self):
        self.sm.write("arch", "Architecture", "alex")
        self.sm.write("deploy", "Deployment", "blake")
        s = self.sm.status()
        self.assertEqual(s["total_topics"], 2)
        self.assertGreater(s["total_bytes"], 0)
        self.assertEqual(len(s["topics"]), 2)

    def test_status_with_project_files(self):
        project_dir = Path(self.tmpdir) / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "DECISIONS.md").write_text("# Decisions")
        s = self.sm.status()
        self.assertIn("DECISIONS.md", s["project_files"])


class TestThreadSafety(unittest.TestCase):
    """Test thread safety."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = SharedMemory(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_concurrent_writes(self):
        errors = []

        def writer(agent_id, n):
            try:
                for i in range(20):
                    self.sm.write("shared-log", f"Entry {agent_id}_{i}", agent_id)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=writer, args=(f"agent_{i}", 20))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        tc = self.sm.read("shared-log")
        self.assertIsNotNone(tc)
        # All 100 entries should be present
        for i in range(5):
            for j in range(20):
                self.assertIn(f"Entry agent_{i}_{j}", tc.content)

    def test_concurrent_read_write(self):
        self.sm.write("data", "Initial content", "setup")
        errors = []

        def reader():
            try:
                for _ in range(20):
                    self.sm.read("data")
            except Exception as e:
                errors.append(str(e))

        def writer():
            try:
                for i in range(20):
                    self.sm.write("data", f"Update {i}", "writer")
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
