"""
Tests for memory_engine.py — Persistent Memory with BM25 Search

Tests cover:
  - BM25 index (build, search, scoring, empty)
  - Tokenizer
  - Chunking (file-based, text-based, overlap)
  - Temporal decay (formula, edge cases)
  - Episodes (write, load, index, list)
  - Daily notes (append, read, multi-day)
  - Memory packets (read_packet with all components)
  - Scaffold (directory creation)
  - Write (generic append/overwrite)
  - Search integration (end-to-end)
  - Status reporting
  - Thread safety
"""

import json
import math
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory_engine import (
    BM25Index,
    MemoryEngine,
    MemoryPacket,
    SearchResult,
    Episode,
    DECAY_LAMBDA,
    _tokenize,
    chunk_file,
    chunk_text,
)


class TestTokenizer(unittest.TestCase):
    """Test the tokenizer."""

    def test_basic_tokenization(self):
        tokens = _tokenize("Hello World BM25 search")
        self.assertEqual(tokens, ["hello", "world", "bm25", "search"])

    def test_filters_short_tokens(self):
        tokens = _tokenize("I am a developer")
        # "I", "a" filtered (len <= 1)
        self.assertNotIn("i", tokens)
        self.assertNotIn("a", tokens)
        self.assertIn("am", tokens)
        self.assertIn("developer", tokens)

    def test_handles_special_chars(self):
        tokens = _tokenize("path/to/file.py — test (v2)")
        self.assertIn("path", tokens)
        self.assertIn("file", tokens)
        self.assertIn("py", tokens)
        self.assertIn("test", tokens)
        self.assertIn("v2", tokens)

    def test_handles_german_umlauts(self):
        tokens = _tokenize("Überprüfung der Änderung")
        self.assertIn("überprüfung", tokens)
        self.assertIn("änderung", tokens)

    def test_empty_string(self):
        self.assertEqual(_tokenize(""), [])


class TestBM25Index(unittest.TestCase):
    """Test BM25 index and search."""

    def setUp(self):
        self.index = BM25Index()

    def test_empty_index_search(self):
        self.index.rebuild()
        results = self.index.search("anything")
        self.assertEqual(results, [])

    def test_single_document(self):
        self.index.add_document(
            "BM25 is a ranking function used in information retrieval",
            "doc1.md", 0, 0
        )
        self.index.rebuild()
        results = self.index.search("BM25 ranking")
        self.assertEqual(len(results), 1)
        self.assertGreater(results[0].score, 0)

    def test_multiple_documents_ranking(self):
        self.index.add_document(
            "Python is a programming language used for data science",
            "python.md", 0, 5
        )
        self.index.add_document(
            "BM25 is a ranking function for search engines",
            "bm25.md", 0, 3
        )
        self.index.add_document(
            "Machine learning uses Python for training models",
            "ml.md", 0, 2
        )
        self.index.rebuild()

        results = self.index.search("BM25 search ranking")
        self.assertGreater(len(results), 0)
        # The BM25 document should rank highest
        self.assertEqual(results[0].file, "bm25.md")

    def test_no_match_returns_empty(self):
        self.index.add_document("cats and dogs", "animals.md", 0, 0)
        self.index.rebuild()
        results = self.index.search("quantum physics")
        self.assertEqual(results, [])

    def test_top_k_limit(self):
        for i in range(10):
            self.index.add_document(
                f"document {i} about search and retrieval",
                f"doc{i}.md", 0, 0
            )
        self.index.rebuild()
        results = self.index.search("search retrieval", top_k=3)
        self.assertLessEqual(len(results), 3)

    def test_doc_count(self):
        self.assertEqual(self.index.doc_count, 0)
        self.index.add_document("test", "f.md", 0, 0)
        self.index.rebuild()
        self.assertEqual(self.index.doc_count, 1)

    def test_search_result_has_metadata(self):
        self.index.add_document(
            "test content", "myfile.md", 10, 20
        )
        self.index.rebuild()
        results = self.index.search("test content")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].file, "myfile.md")
        self.assertEqual(results[0].line_start, 10)
        self.assertEqual(results[0].line_end, 20)

    def test_idf_distinguishes_common_vs_rare(self):
        # "common" appears in all docs, "rare" in only one
        self.index.add_document("common word here", "d1.md", 0, 0)
        self.index.add_document("common word there", "d2.md", 0, 0)
        self.index.add_document("common rare special", "d3.md", 0, 0)
        self.index.rebuild()

        results = self.index.search("rare")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].file, "d3.md")


class TestChunking(unittest.TestCase):
    """Test file and text chunking."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_chunk_small_file(self):
        path = Path(self.tmpdir) / "small.md"
        path.write_text("This is a small file with few words.\n")
        chunks = chunk_file(path, chunk_size=100)
        self.assertEqual(len(chunks), 1)
        self.assertIn("small file", chunks[0]["text"])

    def test_chunk_large_file(self):
        path = Path(self.tmpdir) / "large.md"
        # Create a file with ~1000 words
        lines = [f"Line {i} with some words to fill space.\n" for i in range(150)]
        path.write_text("".join(lines))

        chunks = chunk_file(path, chunk_size=100, overlap=20)
        self.assertGreater(len(chunks), 1)

        # All chunks should have content
        for chunk in chunks:
            self.assertTrue(chunk["text"].strip())
            self.assertIn("file", chunk)

    def test_chunk_preserves_file_path(self):
        path = Path(self.tmpdir) / "test.md"
        path.write_text("Some content\n")
        chunks = chunk_file(path)
        self.assertEqual(chunks[0]["file"], str(path))

    def test_chunk_nonexistent_file(self):
        path = Path(self.tmpdir) / "missing.md"
        chunks = chunk_file(path)
        self.assertEqual(chunks, [])

    def test_chunk_empty_file(self):
        path = Path(self.tmpdir) / "empty.md"
        path.write_text("")
        chunks = chunk_file(path)
        self.assertEqual(chunks, [])

    def test_chunk_text_inline(self):
        text = "Hello world this is inline text\n" * 10
        chunks = chunk_text(text, source="test", chunk_size=50)
        self.assertGreater(len(chunks), 0)
        self.assertEqual(chunks[0]["file"], "test")


class TestTemporalDecay(unittest.TestCase):
    """Test temporal decay formula."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = MemoryEngine(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_decay_for_today(self):
        now = datetime.now(timezone.utc)
        ep = Episode(
            timestamp=now.isoformat(),
            agent_id="test", task="t", summary_file="f.md",
        )
        result = self.engine.apply_temporal_decay([ep], reference_time=now)
        self.assertAlmostEqual(result[0].decay_factor, 1.0, places=2)

    def test_half_life_at_30_days(self):
        now = datetime.now(timezone.utc)
        ep_time = now - timedelta(days=30)
        ep = Episode(
            timestamp=ep_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            agent_id="test", task="t", summary_file="f.md",
        )
        result = self.engine.apply_temporal_decay([ep], reference_time=now)
        # Should be approximately 0.5
        self.assertAlmostEqual(result[0].decay_factor, 0.5, places=1)

    def test_decay_at_7_days(self):
        now = datetime.now(timezone.utc)
        ep_time = now - timedelta(days=7)
        ep = Episode(
            timestamp=ep_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            agent_id="test", task="t", summary_file="f.md",
        )
        result = self.engine.apply_temporal_decay([ep], reference_time=now)
        expected = math.exp(-DECAY_LAMBDA * 7)
        self.assertAlmostEqual(result[0].decay_factor, expected, places=3)

    def test_decay_at_100_days(self):
        now = datetime.now(timezone.utc)
        ep_time = now - timedelta(days=100)
        ep = Episode(
            timestamp=ep_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            agent_id="test", task="t", summary_file="f.md",
        )
        result = self.engine.apply_temporal_decay([ep], reference_time=now)
        # Should be approximately 10%
        self.assertAlmostEqual(result[0].decay_factor, 0.1, places=1)

    def test_decay_affects_score(self):
        now = datetime.now(timezone.utc)
        ep = Episode(
            timestamp=(now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            agent_id="test", task="t", summary_file="f.md",
            score=10.0,
        )
        result = self.engine.apply_temporal_decay([ep], reference_time=now)
        self.assertAlmostEqual(result[0].score, 5.0, places=0)

    def test_decay_sets_age_days(self):
        now = datetime.now(timezone.utc)
        ep_time = now - timedelta(days=15)
        ep = Episode(
            timestamp=ep_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            agent_id="test", task="t", summary_file="f.md",
        )
        result = self.engine.apply_temporal_decay([ep], reference_time=now)
        self.assertAlmostEqual(result[0].age_days, 15.0, delta=0.1)


class TestScaffold(unittest.TestCase):
    """Test directory scaffolding."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = MemoryEngine(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_directories(self):
        result = self.engine.scaffold()
        self.assertGreater(len(result["created"]), 0)

        base = Path(self.tmpdir) / ".agent"
        self.assertTrue((base / "project").exists())
        self.assertTrue((base / "agents").exists())
        self.assertTrue((base / "daily").exists())
        self.assertTrue((base / "episodes").exists())

    def test_creates_default_files(self):
        self.engine.scaffold()
        base = Path(self.tmpdir) / ".agent"
        self.assertTrue((base / "project" / "PROJECT.md").exists())
        self.assertTrue((base / "project" / "DECISIONS.md").exists())

    def test_idempotent(self):
        r1 = self.engine.scaffold()
        r2 = self.engine.scaffold()
        # Second call creates nothing new
        self.assertEqual(len(r2["created"]), 0)


class TestEpisodes(unittest.TestCase):
    """Test episode writing and loading."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = MemoryEngine(Path(self.tmpdir))
        self.engine.scaffold()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_episode(self):
        result = self.engine.write_episode(
            agent_id="alex",
            summary="Implemented BM25 search engine.",
            task="implement-bm25",
            bullets=["Built index", "Added tests"],
        )
        self.assertEqual(result["status"], "ok")
        self.assertTrue(Path(result["file"]).exists())

    def test_episode_file_contains_summary(self):
        result = self.engine.write_episode(
            agent_id="alex",
            summary="Test summary content.",
            task="test-task",
        )
        content = Path(result["file"]).read_text()
        self.assertIn("Test summary content", content)
        self.assertIn("alex", content)

    def test_episode_index_updated(self):
        self.engine.write_episode("alex", "Summary 1", "task-1")
        self.engine.write_episode("alex", "Summary 2", "task-2")

        index_path = self.engine.base_path / "episodes" / "index.jsonl"
        self.assertTrue(index_path.exists())
        lines = index_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)

    def test_load_episodes_filters_by_agent(self):
        self.engine.write_episode("alex", "A summary", "task-a")
        self.engine.write_episode("blake", "B summary", "task-b")

        alex_eps = self.engine._load_episodes(agent_id="alex")
        self.assertEqual(len(alex_eps), 1)
        self.assertEqual(alex_eps[0].agent_id, "alex")

    def test_list_episodes_with_decay(self):
        self.engine.write_episode("alex", "Summary.", "task-1")
        episodes = self.engine.list_episodes(agent_id="alex")
        self.assertEqual(len(episodes), 1)
        self.assertIn("decay_factor", episodes[0])
        self.assertIn("age_days", episodes[0])

    def test_write_episode_auto_bullets(self):
        result = self.engine.write_episode(
            "alex",
            "First point. Second point. Third point.",
            "task-1",
        )
        # bullets auto-extracted from sentences
        episodes = self.engine._load_episodes("alex")
        self.assertGreater(len(episodes[0].summary_bullets), 0)


class TestDailyNotes(unittest.TestCase):
    """Test daily note system."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = MemoryEngine(Path(self.tmpdir))
        self.engine.scaffold()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_daily_note(self):
        result = self.engine.daily_note("alex", "Today I worked on BM25.")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(Path(result["file"]).exists())

    def test_append_to_existing_note(self):
        self.engine.daily_note("alex", "First entry.")
        self.engine.daily_note("alex", "Second entry.")

        content = Path(
            self.engine.base_path / "daily" / "alex"
        ).glob("*.md")
        notes = list(content)
        self.assertEqual(len(notes), 1)  # Same day, one file
        text = notes[0].read_text()
        self.assertIn("First entry", text)
        self.assertIn("Second entry", text)

    def test_read_daily_notes(self):
        self.engine.daily_note("alex", "Today's note.")
        notes = self.engine.read_daily_notes("alex", days=1)
        self.assertIn("Today's note", notes)

    def test_read_daily_notes_missing_agent(self):
        notes = self.engine.read_daily_notes("nonexistent", days=2)
        self.assertEqual(notes, "")


class TestWrite(unittest.TestCase):
    """Test generic write operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = MemoryEngine(Path(self.tmpdir))
        self.engine.scaffold()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_agent_context(self):
        result = self.engine.write("alex", "agents", "My context.", mode="overwrite")
        self.assertEqual(result["status"], "ok")

        agent_file = self.engine.base_path / "agents" / "alex.md"
        self.assertTrue(agent_file.exists())
        self.assertEqual(agent_file.read_text(), "My context.")

    def test_write_append(self):
        self.engine.write("alex", "agents", "Line 1.", mode="overwrite")
        self.engine.write("alex", "agents", "Line 2.", mode="append")

        agent_file = self.engine.base_path / "agents" / "alex.md"
        content = agent_file.read_text()
        self.assertIn("Line 1", content)
        self.assertIn("Line 2", content)

    def test_write_project(self):
        result = self.engine.write("alex", "project", "New architecture.", mode="append")
        self.assertEqual(result["status"], "ok")

    def test_write_unknown_category(self):
        result = self.engine.write("alex", "unknown", "data")
        self.assertEqual(result["status"], "error")


class TestMemoryPacket(unittest.TestCase):
    """Test combined memory packet loading."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = MemoryEngine(Path(self.tmpdir))
        self.engine.scaffold()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_packet_empty(self):
        packet = self.engine.read_packet("alex")
        self.assertIsInstance(packet, MemoryPacket)
        self.assertGreater(len(packet.shared_context), 0)  # default project files

    def test_read_packet_with_agent_context(self):
        self.engine.write("alex", "agents", "Alex's context.", mode="overwrite")
        packet = self.engine.read_packet("alex")
        self.assertIn("Alex's context", packet.agent_context)

    def test_read_packet_with_episodes(self):
        self.engine.write_episode("alex", "Built search engine.", "bm25")
        packet = self.engine.read_packet("alex")
        self.assertGreater(len(packet.recent_episodes), 0)

    def test_read_packet_with_daily_notes(self):
        self.engine.daily_note("alex", "Daily progress note.")
        packet = self.engine.read_packet("alex")
        self.assertIn("Daily progress note", packet.daily_notes)

    def test_read_packet_token_estimate(self):
        self.engine.write("alex", "agents", "Some context " * 100, mode="overwrite")
        packet = self.engine.read_packet("alex")
        self.assertGreater(packet.token_estimate, 0)

    def test_read_packet_to_dict(self):
        packet = self.engine.read_packet("alex")
        d = packet.to_dict()
        self.assertIn("shared_context", d)
        self.assertIn("token_estimate", d)


class TestSearchIntegration(unittest.TestCase):
    """Test end-to-end BM25 search through MemoryEngine."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = MemoryEngine(Path(self.tmpdir))
        self.engine.scaffold()

        # Write some searchable content
        self.engine.write(
            "alex", "agents",
            "Alex specializes in BM25 search implementation and ranking algorithms.",
            mode="overwrite",
        )
        self.engine.write(
            "alex", "project",
            "\n\nThe Bridge platform uses WebSocket for real-time communication.",
            mode="append",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_search_finds_content(self):
        results = self.engine.search("BM25 search", "alex")
        self.assertGreater(len(results), 0)

    def test_search_returns_search_result(self):
        results = self.engine.search("BM25", "alex")
        self.assertIsInstance(results[0], SearchResult)
        self.assertGreater(results[0].score, 0)

    def test_search_no_match(self):
        results = self.engine.search("quantum computing", "alex")
        self.assertEqual(results, [])

    def test_search_ranks_correctly(self):
        results = self.engine.search("BM25 ranking", "alex")
        # The agent file should score highest (has both terms)
        if results:
            self.assertIn("alex", results[0].file)

    def test_invalidate_index_forces_rebuild(self):
        self.engine.search("test", "alex")  # Build index
        self.assertIn("alex", self.engine._indices)

        self.engine.invalidate_index("alex")
        self.assertNotIn("alex", self.engine._indices)

    def test_invalidate_all_indices(self):
        self.engine.search("test", "alex")
        self.engine.invalidate_index()  # None = all
        self.assertEqual(len(self.engine._indices), 0)

    def test_search_result_to_dict(self):
        results = self.engine.search("BM25", "alex")
        if results:
            d = results[0].to_dict()
            self.assertIn("file", d)
            self.assertIn("score", d)
            self.assertIsInstance(d["score"], float)


class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = MemoryEngine(Path(self.tmpdir))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_status_before_scaffold(self):
        status = self.engine.status()
        self.assertFalse(status["exists"])

    def test_status_after_scaffold(self):
        self.engine.scaffold()
        status = self.engine.status()
        self.assertTrue(status["exists"])
        self.assertGreater(len(status["project_files"]), 0)

    def test_status_counts_episodes(self):
        self.engine.scaffold()
        self.engine.write_episode("alex", "Test.", "t1")
        self.engine.write_episode("alex", "Test.", "t2")
        status = self.engine.status()
        self.assertEqual(status["total_episodes"], 2)


class TestThreadSafety(unittest.TestCase):
    """Test concurrent access."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = MemoryEngine(Path(self.tmpdir))
        self.engine.scaffold()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_concurrent_writes(self):
        errors = []

        def write_notes(agent_id, count):
            try:
                for i in range(count):
                    self.engine.daily_note(agent_id, f"Note {i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=write_notes, args=("alex", 10)),
            threading.Thread(target=write_notes, args=("blake", 10)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)

    def test_concurrent_search_and_write(self):
        self.engine.write("alex", "agents", "Searchable content.", mode="overwrite")
        errors = []

        def do_searches():
            try:
                for _ in range(5):
                    self.engine.search("content", "alex")
            except Exception as e:
                errors.append(e)

        def do_writes():
            try:
                for i in range(5):
                    self.engine.write_episode("alex", f"Episode {i}", f"task-{i}")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=do_searches)
        t2 = threading.Thread(target=do_writes)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
