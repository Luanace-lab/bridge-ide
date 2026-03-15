"""
shared_memory.py — Shared Memory Layer (Blackboard Pattern)

Centralized knowledge repository for multi-agent coordination.
Agents post facts, decisions, and artifacts to shared topics that
other agents can read and search.

Architecture Reference: R4_Architekturentwurf.md section 3.2.5
                        R5_Integration_Roadmap.md D4
Phase: D — Scale

Features:
  - Topic-based shared storage (.agent/shared/{topic}.md)
  - Author and timestamp tracking on every write
  - Append-only or replace modes
  - BM25 search across all shared topics
  - Thread-safe concurrent access
  - Topic listing and metadata
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_engine import BM25Index, SearchResult, chunk_text


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TOPIC_LENGTH = 128
MAX_CONTENT_LENGTH = 200_000
TOPIC_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class TopicEntry:
    """A single entry written to a shared topic."""

    author: str
    timestamp: str
    content: str

    def to_markdown(self) -> str:
        """Format as markdown section."""
        return (
            f"\n\n---\n"
            f"**Author:** {self.author} | "
            f"**Timestamp:** {self.timestamp}\n\n"
            f"{self.content}"
        )


@dataclass
class TopicInfo:
    """Metadata about a shared topic."""

    name: str
    path: str
    size_bytes: int
    last_modified: float
    last_author: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "last_modified": self.last_modified,
            "last_author": self.last_author,
        }


@dataclass
class TopicContent:
    """Full content of a shared topic."""

    topic: str
    content: str
    last_updated: str
    updated_by: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "content": self.content,
            "last_updated": self.last_updated,
            "updated_by": self.updated_by,
            "size_bytes": self.size_bytes,
        }


# ---------------------------------------------------------------------------
# Shared Memory (Blackboard)
# ---------------------------------------------------------------------------

class SharedMemory:
    """Blackboard-pattern shared memory for multi-agent coordination.

    Storage layout:
        base_path/
            shared/
                {topic}.md          # Topic files
            project/
                PROJECT.md          # Global project context
                DECISIONS.md        # Architectural decisions
                GLOSSARY.md         # Shared terminology
                RUNBOOK.md          # Operational procedures

    Thread-safe for concurrent read/write from multiple agents.
    """

    def __init__(self, base_path: Path):
        """Initialize shared memory.

        Args:
            base_path: Base path (typically .agent/ directory).
        """
        self._base = base_path
        self._shared_dir = base_path / "shared"
        self._project_dir = base_path / "project"
        self._lock = threading.Lock()
        self._index: BM25Index | None = None
        self._index_dirty = True

    # -------------------------------------------------------------------
    # Scaffold
    # -------------------------------------------------------------------

    def scaffold(self) -> dict[str, bool]:
        """Create directory structure if it doesn't exist.

        Returns:
            Dict of created directories.
        """
        created = {}
        for d in [self._shared_dir, self._project_dir]:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                created[str(d)] = True
            else:
                created[str(d)] = False
        return created

    # -------------------------------------------------------------------
    # Write
    # -------------------------------------------------------------------

    def write(
        self,
        topic: str,
        content: str,
        agent_id: str,
        mode: str = "append",
    ) -> dict[str, Any]:
        """Write content to a shared topic.

        Args:
            topic: Topic name (lowercase, alphanumeric + underscore/hyphen).
            content: Content to write.
            agent_id: Agent performing the write.
            mode: "append" (default) or "replace".

        Returns:
            Result dict with path, size, mode.

        Raises:
            ValueError: If topic name or content invalid.
        """
        self._validate_topic(topic)
        if not content:
            raise ValueError("Content must not be empty")
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Content exceeds max length ({MAX_CONTENT_LENGTH} chars)"
            )
        if mode not in ("append", "replace"):
            raise ValueError(f"Invalid mode: {mode}. Use 'append' or 'replace'")

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        entry = TopicEntry(author=agent_id, timestamp=timestamp, content=content)

        with self._lock:
            self._shared_dir.mkdir(parents=True, exist_ok=True)
            path = self._shared_dir / f"{topic}.md"

            if mode == "append":
                with open(path, "a", encoding="utf-8") as f:
                    f.write(entry.to_markdown())
            else:
                # Atomic replace via temp file + os.replace()
                new_content = f"# {topic}\n" + entry.to_markdown()
                fd, tmp = tempfile.mkstemp(
                    dir=str(self._shared_dir), suffix=".tmp"
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    os.replace(tmp, str(path))
                except BaseException:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise

            self._index_dirty = True

            return {
                "topic": topic,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "mode": mode,
                "author": agent_id,
                "timestamp": timestamp,
            }

    # -------------------------------------------------------------------
    # Read
    # -------------------------------------------------------------------

    def read(self, topic: str) -> TopicContent | None:
        """Read a shared topic's full content.

        Args:
            topic: Topic name.

        Returns:
            TopicContent or None if topic doesn't exist.
        """
        self._validate_topic(topic)
        path = self._shared_dir / f"{topic}.md"

        if not path.exists():
            return None

        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None

        # Extract last author from content
        last_author = self._extract_last_author(content)
        last_updated = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(path.stat().st_mtime),
        )

        return TopicContent(
            topic=topic,
            content=content,
            last_updated=last_updated,
            updated_by=last_author,
            size_bytes=len(content.encode("utf-8")),
        )

    def read_project(self, filename: str) -> str | None:
        """Read a project-level shared file.

        Args:
            filename: File name (e.g., "PROJECT.md", "DECISIONS.md").

        Returns:
            File content or None.
        """
        path = self._project_dir / filename
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    # -------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5,
        include_project: bool = True,
    ) -> list[SearchResult]:
        """BM25 search across shared topics.

        Args:
            query: Search query string.
            top_k: Max results to return.
            include_project: Also search project/ files.

        Returns:
            Ranked list of SearchResult.
        """
        if not query.strip():
            return []

        self._ensure_index(include_project)

        if self._index is None:
            return []

        return self._index.search(query, top_k=top_k)

    # -------------------------------------------------------------------
    # Topic Management
    # -------------------------------------------------------------------

    def list_topics(self) -> list[TopicInfo]:
        """List all shared topics with metadata."""
        topics: list[TopicInfo] = []

        if not self._shared_dir.exists():
            return topics

        for path in sorted(self._shared_dir.iterdir()):
            if not path.is_file() or not path.suffix == ".md":
                continue

            stat = path.stat()
            content = ""
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                pass

            topics.append(TopicInfo(
                name=path.stem,
                path=str(path),
                size_bytes=stat.st_size,
                last_modified=stat.st_mtime,
                last_author=self._extract_last_author(content),
            ))

        return topics

    def topic_exists(self, topic: str) -> bool:
        """Check if a topic exists."""
        return (self._shared_dir / f"{topic}.md").exists()

    def delete_topic(self, topic: str) -> bool:
        """Delete a shared topic.

        Returns True if deleted, False if not found.
        """
        self._validate_topic(topic)
        path = self._shared_dir / f"{topic}.md"
        if not path.exists():
            return False

        with self._lock:
            path.unlink()
            self._index_dirty = True

        return True

    # -------------------------------------------------------------------
    # Index
    # -------------------------------------------------------------------

    def invalidate_index(self) -> None:
        """Mark the search index as dirty (will rebuild on next search)."""
        self._index_dirty = True

    def _ensure_index(self, include_project: bool = True) -> None:
        """Rebuild BM25 index if dirty."""
        if not self._index_dirty and self._index is not None:
            return

        idx = BM25Index()

        # Index shared topics
        if self._shared_dir.exists():
            for path in self._shared_dir.iterdir():
                if not path.is_file() or not path.suffix == ".md":
                    continue
                try:
                    content = path.read_text(encoding="utf-8")
                except OSError:
                    continue

                chunks = chunk_text(content, source=str(path), chunk_size=500)
                for chunk in chunks:
                    idx.add_document(
                        text=chunk["text"],
                        file=chunk["file"],
                        line_start=chunk["line_start"],
                        line_end=chunk["line_end"],
                    )

        # Index project files
        if include_project and self._project_dir.exists():
            for path in self._project_dir.iterdir():
                if not path.is_file() or not path.suffix == ".md":
                    continue
                try:
                    content = path.read_text(encoding="utf-8")
                except OSError:
                    continue

                chunks = chunk_text(content, source=str(path), chunk_size=500)
                for chunk in chunks:
                    idx.add_document(
                        text=chunk["text"],
                        file=chunk["file"],
                        line_start=chunk["line_start"],
                        line_end=chunk["line_end"],
                    )

        idx.rebuild()
        self._index = idx
        self._index_dirty = False

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    @staticmethod
    def _validate_topic(topic: str) -> None:
        """Validate topic name."""
        if not topic:
            raise ValueError("Topic name must not be empty")
        if len(topic) > MAX_TOPIC_LENGTH:
            raise ValueError(
                f"Topic name exceeds max length ({MAX_TOPIC_LENGTH} chars)"
            )
        if not all(c in TOPIC_CHARS for c in topic):
            raise ValueError(
                f"Topic name must be lowercase alphanumeric, "
                f"underscore or hyphen. Got: '{topic}'"
            )

    @staticmethod
    def _extract_last_author(content: str) -> str:
        """Extract the last author from topic content."""
        # Look for **Author:** pattern (from TopicEntry.to_markdown)
        last_author = ""
        for line in content.split("\n"):
            if "**Author:**" in line:
                # Extract: **Author:** alex | **Timestamp:** ...
                parts = line.split("**Author:**")
                if len(parts) > 1:
                    author_part = parts[1].split("|")[0].strip()
                    if author_part:
                        last_author = author_part
        return last_author

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return shared memory status."""
        topics = self.list_topics()
        total_bytes = sum(t.size_bytes for t in topics)

        project_files = []
        if self._project_dir.exists():
            project_files = [
                p.name for p in self._project_dir.iterdir()
                if p.is_file() and p.suffix == ".md"
            ]

        return {
            "base_path": str(self._base),
            "shared_dir_exists": self._shared_dir.exists(),
            "project_dir_exists": self._project_dir.exists(),
            "total_topics": len(topics),
            "total_bytes": total_bytes,
            "topics": [t.to_dict() for t in topics],
            "project_files": sorted(project_files),
            "index_dirty": self._index_dirty,
        }
