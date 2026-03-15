"""
memory_engine.py — Persistent Memory with BM25 Search for Bridge IDE

Manages agent memory: episodes, daily notes, shared project context,
and BM25-based full-text search across all memory files.

Architecture Reference: R4_Architekturentwurf.md section 3.2.2
Research Reference: R2_Memory_Tools_Skills.md
Phase: A — Foundation

Features:
  - BM25 search (pure Python, no external dependencies)
  - Temporal decay (exponential, 30-day half-life)
  - Daily notes (append-only, per-agent)
  - Episodes (task-scoped summaries with JSONL index)
  - Memory packets (combined context for agent startup)
  - Markdown chunking with overlap for search indexing
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# BM25 parameters (standard defaults)
BM25_K1 = 1.5
BM25_B = 0.75

# Temporal decay: lambda chosen so exp(-LAMBDA * 30) ≈ 0.5 (30-day half-life)
DECAY_LAMBDA = 0.023


def _atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write content atomically via temp file + os.replace()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

# Chunking defaults
DEFAULT_CHUNK_SIZE = 500  # tokens (approx words)
DEFAULT_CHUNK_OVERLAP = 80  # tokens overlap between chunks

# Directory structure under .agent/
AGENT_DIR_NAME = ".agent"
PROJECT_SUBDIR = "project"
AGENTS_SUBDIR = "agents"
DAILY_SUBDIR = "daily"
EPISODES_SUBDIR = "episodes"
EPISODE_INDEX_FILE = "index.jsonl"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """A single BM25 search result."""

    file: str
    line_start: int
    line_end: int
    content: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "content": self.content,
            "score": round(self.score, 4),
        }


@dataclass
class Episode:
    """A task-scoped memory episode."""

    timestamp: str
    agent_id: str
    task: str
    summary_file: str
    summary_bullets: list[str] = field(default_factory=list)
    score: float = 1.0
    decay_factor: float = 1.0
    age_days: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "task": self.task,
            "summary_file": self.summary_file,
            "summary_bullets": self.summary_bullets,
        }


@dataclass
class MemoryPacket:
    """Combined context for agent startup."""

    shared_context: str = ""
    agent_context: str = ""
    recent_episodes: list[str] = field(default_factory=list)
    daily_notes: str = ""
    token_estimate: int = 0
    files_read: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shared_context": self.shared_context,
            "agent_context": self.agent_context,
            "recent_episodes": self.recent_episodes,
            "daily_notes": self.daily_notes,
            "token_estimate": self.token_estimate,
            "files_read": self.files_read,
        }


# ---------------------------------------------------------------------------
# BM25 Implementation (pure Python, no dependencies)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Tokenize text: lowercase, split on non-alphanumeric, filter short."""
    tokens = re.findall(r"[a-zA-Z0-9äöüÄÖÜß_]+", text.lower())
    return [t for t in tokens if len(t) > 1]


class BM25Index:
    """BM25Okapi index for full-text search.

    Pure Python implementation — no external dependencies.
    """

    def __init__(self, k1: float = BM25_K1, b: float = BM25_B):
        self.k1 = k1
        self.b = b
        self._corpus_tokens: list[list[str]] = []
        self._corpus_text: list[str] = []
        self._metadata: list[dict[str, Any]] = []
        self._doc_lengths: list[int] = []
        self._avgdl: float = 0.0
        self._df: Counter[str] = Counter()  # document frequency per term
        self._n: int = 0  # total documents
        self._built: bool = False

    def add_document(
        self,
        text: str,
        file: str,
        line_start: int,
        line_end: int,
    ) -> None:
        """Add a document chunk to the index. Call rebuild() after all adds."""
        tokens = _tokenize(text)
        self._corpus_tokens.append(tokens)
        self._corpus_text.append(text)
        self._metadata.append({
            "file": file,
            "line_start": line_start,
            "line_end": line_end,
        })
        self._built = False

    def rebuild(self) -> None:
        """Build IDF and doc-length statistics. Must call after adding docs."""
        self._n = len(self._corpus_tokens)
        if self._n == 0:
            self._built = True
            return

        self._doc_lengths = [len(tokens) for tokens in self._corpus_tokens]
        self._avgdl = sum(self._doc_lengths) / self._n

        self._df = Counter()
        for tokens in self._corpus_tokens:
            unique_terms = set(tokens)
            for term in unique_terms:
                self._df[term] += 1

        self._built = True

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Search the index. Returns top-k results sorted by score."""
        if not self._built or self._n == 0:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scores: list[float] = []
        for i, doc_tokens in enumerate(self._corpus_tokens):
            score = self._score_document(query_tokens, doc_tokens, i)
            scores.append(score)

        # Get top-k indices with score > 0
        indexed_scores = [
            (i, s) for i, s in enumerate(scores) if s > 0
        ]
        indexed_scores.sort(key=lambda x: x[1], reverse=True)
        top = indexed_scores[:top_k]

        results = []
        for idx, score in top:
            meta = self._metadata[idx]
            results.append(SearchResult(
                file=meta["file"],
                line_start=meta["line_start"],
                line_end=meta["line_end"],
                content=self._corpus_text[idx],
                score=score,
            ))
        return results

    def _score_document(
        self,
        query_tokens: list[str],
        doc_tokens: list[str],
        doc_idx: int,
    ) -> float:
        """BM25 score for a single document against query."""
        doc_len = self._doc_lengths[doc_idx]
        tf_counter = Counter(doc_tokens)
        score = 0.0

        for term in query_tokens:
            if term not in self._df:
                continue

            df = self._df[term]
            tf = tf_counter.get(term, 0)
            if tf == 0:
                continue

            # IDF: log((N - df + 0.5) / (df + 0.5) + 1)
            idf = math.log(
                (self._n - df + 0.5) / (df + 0.5) + 1.0
            )

            # TF component with length normalization
            tf_norm = (tf * (self.k1 + 1)) / (
                tf + self.k1 * (1 - self.b + self.b * doc_len / self._avgdl)
            )

            score += idf * tf_norm

        return score

    @property
    def doc_count(self) -> int:
        return self._n


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_file(
    file_path: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """Split a markdown file into overlapping chunks for BM25 indexing.

    Args:
        file_path: Path to the markdown file.
        chunk_size: Target chunk size in approximate word count.
        overlap: Number of words to overlap between chunks.

    Returns:
        List of dicts with keys: text, file, line_start, line_end.
    """
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        return []

    if not lines:
        return []

    chunks: list[dict[str, Any]] = []
    current_lines: list[str] = []
    current_word_count = 0
    start_line = 0

    for i, line in enumerate(lines):
        word_count = len(line.split())
        current_lines.append(line)
        current_word_count += word_count

        if current_word_count >= chunk_size and len(current_lines) > 1:
            # Save chunk
            chunk_text = "".join(current_lines)
            chunks.append({
                "text": chunk_text,
                "file": str(file_path),
                "line_start": start_line,
                "line_end": i,
            })

            # Keep overlap lines
            overlap_words = 0
            overlap_start = len(current_lines)
            for j in range(len(current_lines) - 1, -1, -1):
                overlap_words += len(current_lines[j].split())
                if overlap_words >= overlap:
                    overlap_start = j
                    break

            kept = current_lines[overlap_start:]
            start_line = i - len(kept) + 1
            current_lines = kept
            current_word_count = sum(len(l.split()) for l in current_lines)

    # Final chunk
    if current_lines:
        chunk_text = "".join(current_lines)
        if chunk_text.strip():
            chunks.append({
                "text": chunk_text,
                "file": str(file_path),
                "line_start": start_line,
                "line_end": len(lines) - 1,
            })

    return chunks


def chunk_text(
    text: str,
    source: str = "<inline>",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[dict[str, Any]]:
    """Chunk a raw text string (for inline content like episodes)."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    wc = 0
    start = 0

    for i, line in enumerate(lines):
        current.append(line)
        wc += len(line.split())
        if wc >= chunk_size:
            chunks.append({
                "text": "".join(current),
                "file": source,
                "line_start": start,
                "line_end": i,
            })
            current = []
            wc = 0
            start = i + 1

    if current:
        chunks.append({
            "text": "".join(current),
            "file": source,
            "line_start": start,
            "line_end": start + len(current) - 1,
        })

    return chunks


# ---------------------------------------------------------------------------
# Memory Engine
# ---------------------------------------------------------------------------

class MemoryEngine:
    """Persistent memory with BM25 search for Bridge IDE agents.

    Manages the .agent/ directory structure:
      .agent/
        project/     — Shared project context (PROJECT.md, DECISIONS.md, etc.)
        agents/      — Per-agent private context
        daily/       — Per-agent daily notes
        episodes/    — Task-scoped summaries with JSONL index
    """

    def __init__(self, base_path: Path):
        """Initialize the memory engine.

        Args:
            base_path: Project root path. Memory lives at base_path/.agent/
        """
        self._base = base_path / AGENT_DIR_NAME
        self._lock = threading.Lock()
        self._indices: dict[str, BM25Index] = {}

    @property
    def base_path(self) -> Path:
        return self._base

    # -------------------------------------------------------------------
    # Scaffold
    # -------------------------------------------------------------------

    def scaffold(self) -> dict[str, Any]:
        """Create .agent/ directory structure if it doesn't exist.

        Returns dict with created directories.
        """
        dirs = [
            self._base / PROJECT_SUBDIR,
            self._base / AGENTS_SUBDIR,
            self._base / DAILY_SUBDIR,
            self._base / EPISODES_SUBDIR,
        ]
        created = []
        for d in dirs:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                created.append(str(d))

        # Create default project files if missing
        defaults = {
            self._base / PROJECT_SUBDIR / "PROJECT.md": (
                "# Project Context\n\n"
                "Architecture, stack, and entry points.\n"
            ),
            self._base / PROJECT_SUBDIR / "DECISIONS.md": (
                "# Architecture Decision Records\n\n"
                "| Date | Decision | Rationale |\n"
                "|------|----------|----------|\n"
            ),
        }
        for path, content in defaults.items():
            if not path.exists():
                _atomic_write_text(path, content)
                created.append(str(path))

        return {"created": created, "base": str(self._base)}

    # -------------------------------------------------------------------
    # Read Packet
    # -------------------------------------------------------------------

    def read_packet(
        self,
        agent_id: str,
        max_tokens: int = 600,
        include_episodes: int = 5,
        include_daily_days: int = 2,
    ) -> MemoryPacket:
        """Load combined context for an agent.

        Args:
            agent_id: Agent identifier.
            max_tokens: Token budget (approximate).
            include_episodes: Number of recent episodes to include.
            include_daily_days: Number of days of daily notes (today + yesterday).

        Returns:
            MemoryPacket with all relevant context.
        """
        files_read: list[str] = []

        # Shared project context
        shared_parts: list[str] = []
        project_dir = self._base / PROJECT_SUBDIR
        if project_dir.exists():
            for f in sorted(project_dir.glob("*.md")):
                try:
                    content = f.read_text(encoding="utf-8")
                    shared_parts.append(f"## {f.stem}\n\n{content}")
                    files_read.append(str(f))
                except OSError:
                    pass
        shared_context = "\n\n---\n\n".join(shared_parts)

        # Agent-private context
        agent_file = self._resolve_agent_file(agent_id)
        agent_context = ""
        if agent_file.exists():
            try:
                agent_context = agent_file.read_text(encoding="utf-8")
                files_read.append(str(agent_file))
            except OSError:
                pass

        # Recent episodes with temporal decay
        episodes = self._load_episodes(agent_id=agent_id)
        episodes.sort(key=lambda e: e.timestamp, reverse=True)
        episodes = episodes[:include_episodes]
        episodes = self.apply_temporal_decay(episodes)

        episode_summaries: list[str] = []
        for ep in episodes:
            bullets = "\n".join(f"  - {b}" for b in ep.summary_bullets)
            decay_pct = int(ep.decay_factor * 100)
            episode_summaries.append(
                f"[{ep.timestamp[:10]}] {ep.task} (relevance: {decay_pct}%)\n{bullets}"
            )

        # Daily notes
        daily_notes = self.read_daily_notes(agent_id, days=include_daily_days)

        # Token estimate (rough: 1 token ≈ 0.75 words)
        total_text = shared_context + agent_context + daily_notes + " ".join(episode_summaries)
        token_est = int(len(total_text.split()) / 0.75)

        return MemoryPacket(
            shared_context=shared_context,
            agent_context=agent_context,
            recent_episodes=episode_summaries,
            daily_notes=daily_notes,
            token_estimate=token_est,
            files_read=files_read,
        )

    # -------------------------------------------------------------------
    # Search (BM25)
    # -------------------------------------------------------------------

    def search(
        self,
        query: str,
        agent_id: str,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """BM25 search across all memory files for an agent.

        Indexes shared project files, agent-private file, and recent episodes.
        Index is built lazily and cached per agent.

        Args:
            query: Search query string.
            agent_id: Agent performing the search.
            top_k: Maximum results to return.

        Returns:
            List of SearchResult sorted by relevance.
        """
        with self._lock:
            if agent_id not in self._indices:
                self._build_index(agent_id)

        return self._indices[agent_id].search(query, top_k)

    def invalidate_index(self, agent_id: str | None = None) -> None:
        """Force index rebuild on next search.

        Args:
            agent_id: Specific agent to invalidate, or None for all.
        """
        with self._lock:
            if agent_id is None:
                self._indices.clear()
            else:
                self._indices.pop(agent_id, None)

    def _build_index(self, agent_id: str) -> None:
        """Build BM25 index for an agent. Called under lock."""
        index = BM25Index()

        # Index shared project files
        project_dir = self._base / PROJECT_SUBDIR
        if project_dir.exists():
            for f in project_dir.glob("*.md"):
                for chunk in chunk_file(f):
                    index.add_document(
                        text=chunk["text"],
                        file=chunk["file"],
                        line_start=chunk["line_start"],
                        line_end=chunk["line_end"],
                    )

        # Index agent-private file
        agent_file = self._resolve_agent_file(agent_id)
        if agent_file.exists():
            for chunk in chunk_file(agent_file):
                index.add_document(
                    text=chunk["text"],
                    file=chunk["file"],
                    line_start=chunk["line_start"],
                    line_end=chunk["line_end"],
                )

        # Index recent episodes (last 20)
        episodes = self._load_episodes(agent_id=agent_id)
        episodes.sort(key=lambda e: e.timestamp, reverse=True)
        for ep in episodes[:20]:
            ep_file = self._base / EPISODES_SUBDIR / ep.summary_file
            if ep_file.exists():
                for chunk in chunk_file(ep_file):
                    index.add_document(
                        text=chunk["text"],
                        file=chunk["file"],
                        line_start=chunk["line_start"],
                        line_end=chunk["line_end"],
                    )

        # Index daily notes (last 7 days)
        daily_dir = self._base / DAILY_SUBDIR / agent_id
        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.md"), reverse=True)[:7]:
                for chunk in chunk_file(f):
                    index.add_document(
                        text=chunk["text"],
                        file=chunk["file"],
                        line_start=chunk["line_start"],
                        line_end=chunk["line_end"],
                    )

        index.rebuild()
        self._indices[agent_id] = index

    # -------------------------------------------------------------------
    # Episodes
    # -------------------------------------------------------------------

    def write_episode(
        self,
        agent_id: str,
        summary: str,
        task: str = "",
        bullets: list[str] | None = None,
    ) -> dict[str, Any]:
        """Write a task-scoped episode summary.

        Creates a markdown file and appends to the JSONL index.

        Args:
            agent_id: Author agent.
            summary: Full episode summary text.
            task: Task identifier (e.g., "implement-bm25").
            bullets: Optional bullet-point summary.

        Returns:
            Dict with file path and status.
        """
        episodes_dir = self._base / EPISODES_SUBDIR
        episodes_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        date_str = now.strftime("%Y-%m-%d")

        # Sanitize task name for filename
        safe_task = re.sub(r"[^a-zA-Z0-9_-]", "-", task or "general")[:50]

        # Short hash for uniqueness
        slug = hashlib.md5(
            f"{ts}{agent_id}{task}{summary[:100]}".encode()
        ).hexdigest()[:8]

        filename = f"{date_str}__{safe_task}__{slug}.md"
        filepath = episodes_dir / filename

        # Write markdown file
        md_content = (
            f"# Episode: {task or 'General'}\n\n"
            f"**Agent:** {agent_id}\n"
            f"**Timestamp:** {ts}\n\n"
            f"## Summary\n\n{summary}\n"
        )
        if bullets:
            md_content += "\n## Key Points\n\n"
            md_content += "\n".join(f"- {b}" for b in bullets) + "\n"

        _atomic_write_text(filepath, md_content)

        # Append to JSONL index
        if bullets is None:
            # Extract bullets from summary (first 5 sentences)
            sentences = [s.strip() for s in summary.split(".") if s.strip()]
            bullets = sentences[:5]

        index_entry = {
            "timestamp": ts,
            "agent_id": agent_id,
            "task": task,
            "summary_file": filename,
            "summary_bullets": bullets,
        }

        index_path = episodes_dir / EPISODE_INDEX_FILE
        with self._lock:
            try:
                with open(index_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(index_entry, ensure_ascii=False) + "\n")
            except OSError:
                pass

        # Invalidate search index for this agent
        self.invalidate_index(agent_id)

        return {
            "status": "ok",
            "file": str(filepath),
            "filename": filename,
            "timestamp": ts,
        }

    def _load_episodes(
        self,
        agent_id: str | None = None,
    ) -> list[Episode]:
        """Load episodes from JSONL index.

        Args:
            agent_id: Filter by agent. None = all agents.
        """
        index_path = self._base / EPISODES_SUBDIR / EPISODE_INDEX_FILE
        if not index_path.exists():
            return []

        episodes: list[Episode] = []
        try:
            with open(index_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if agent_id and data.get("agent_id") != agent_id:
                        continue
                    episodes.append(Episode(
                        timestamp=data.get("timestamp", ""),
                        agent_id=data.get("agent_id", ""),
                        task=data.get("task", ""),
                        summary_file=data.get("summary_file", ""),
                        summary_bullets=data.get("summary_bullets", []),
                    ))
        except OSError:
            pass

        return episodes

    def list_episodes(
        self,
        agent_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List recent episodes (for API/UI).

        Returns list of episode dicts (without full content).
        """
        episodes = self._load_episodes(agent_id)
        episodes.sort(key=lambda e: e.timestamp, reverse=True)
        episodes = episodes[:limit]
        episodes = self.apply_temporal_decay(episodes)

        return [
            {
                **ep.to_dict(),
                "decay_factor": round(ep.decay_factor, 4),
                "age_days": round(ep.age_days, 2),
            }
            for ep in episodes
        ]

    # -------------------------------------------------------------------
    # Daily Notes
    # -------------------------------------------------------------------

    def daily_note(self, agent_id: str, content: str) -> dict[str, Any]:
        """Append to today's daily note.

        Creates date-based file automatically. Append-only.

        Args:
            agent_id: Agent writing the note.
            content: Note content to append.

        Returns:
            Dict with file path and status.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_dir = self._base / DAILY_SUBDIR / agent_id
        daily_dir.mkdir(parents=True, exist_ok=True)

        daily_file = daily_dir / f"{today}.md"
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

        entry = f"\n## {ts}\n\n{content}\n"

        # Create file with header if new
        if not daily_file.exists():
            header = f"# Daily Notes — {agent_id} — {today}\n"
            entry = header + entry

        try:
            with open(daily_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except OSError:
            return {"status": "error", "error": "Failed to write daily note"}

        # Invalidate search index
        self.invalidate_index(agent_id)

        return {
            "status": "ok",
            "file": str(daily_file),
            "agent_id": agent_id,
            "date": today,
        }

    def read_daily_notes(self, agent_id: str, days: int = 2) -> str:
        """Load recent daily notes for an agent.

        Args:
            agent_id: Agent whose notes to load.
            days: Number of days to include (today + N-1 previous).

        Returns:
            Combined daily notes as string.
        """
        daily_dir = self._base / DAILY_SUBDIR / agent_id
        if not daily_dir.exists():
            return ""

        notes: list[str] = []
        now = datetime.now(timezone.utc)

        for offset in range(days):
            date = (now - timedelta(days=offset)).strftime("%Y-%m-%d")
            file = daily_dir / f"{date}.md"
            if file.exists():
                try:
                    content = file.read_text(encoding="utf-8")
                    notes.append(content)
                except OSError:
                    pass

        return "\n\n---\n\n".join(notes)

    # -------------------------------------------------------------------
    # Write (generic)
    # -------------------------------------------------------------------

    def write(
        self,
        agent_id: str,
        category: str,
        content: str,
        mode: str = "append",
    ) -> dict[str, Any]:
        """Write to a memory category.

        Args:
            agent_id: Agent performing the write.
            category: "project", "agents", or "episodes".
            content: Content to write.
            mode: "append" or "overwrite".

        Returns:
            Dict with file path and status.
        """
        if category == "project":
            target = self._base / PROJECT_SUBDIR / "PROJECT.md"
        elif category == "agents":
            target = self._resolve_agent_file(agent_id)
        else:
            return {"status": "error", "error": f"Unknown category: {category}"}

        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            if mode == "append":
                with open(target, "a", encoding="utf-8") as f:
                    f.write("\n" + content)
            else:
                _atomic_write_text(target, content)
        except OSError as e:
            return {"status": "error", "error": str(e)}

        self.invalidate_index(agent_id)

        return {"status": "ok", "file": str(target), "mode": mode}

    # -------------------------------------------------------------------
    # Temporal Decay
    # -------------------------------------------------------------------

    def apply_temporal_decay(
        self,
        episodes: list[Episode],
        reference_time: datetime | None = None,
    ) -> list[Episode]:
        """Apply exponential decay to episodes based on age.

        Formula: decay_factor = exp(-LAMBDA * age_days)
        LAMBDA = 0.023 gives 30-day half-life.

        Args:
            episodes: List of episodes to decay.
            reference_time: Reference time (default: now).

        Returns:
            Episodes with decay_factor, age_days, and adjusted score.
        """
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        for ep in episodes:
            try:
                ep_time = datetime.fromisoformat(
                    ep.timestamp.replace("Z", "+00:00")
                )
                age_days = (reference_time - ep_time).total_seconds() / 86400
            except (ValueError, TypeError):
                age_days = 0.0

            decay = math.exp(-DECAY_LAMBDA * max(0.0, age_days))
            ep.decay_factor = decay
            ep.age_days = age_days
            ep.score = ep.score * decay

        return episodes

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return stats about the memory store."""
        result: dict[str, Any] = {
            "base_path": str(self._base),
            "exists": self._base.exists(),
            "agents": {},
            "project_files": [],
            "total_episodes": 0,
            "indices_cached": list(self._indices.keys()),
        }

        if not self._base.exists():
            return result

        # Project files
        project_dir = self._base / PROJECT_SUBDIR
        if project_dir.exists():
            for f in sorted(project_dir.glob("*.md")):
                stat = f.stat()
                result["project_files"].append({
                    "name": f.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                })

        # Agent files
        agents_dir = self._base / AGENTS_SUBDIR
        if agents_dir.exists():
            for f in sorted(agents_dir.glob("*.md")):
                agent_name = f.stem
                stat = f.stat()
                result["agents"][agent_name] = {
                    "context_file_size": stat.st_size,
                }

        # Daily note counts per agent
        daily_dir = self._base / DAILY_SUBDIR
        if daily_dir.exists():
            for agent_dir in sorted(daily_dir.iterdir()):
                if agent_dir.is_dir():
                    name = agent_dir.name
                    if name not in result["agents"]:
                        result["agents"][name] = {}
                    notes = list(agent_dir.glob("*.md"))
                    result["agents"][name]["daily_notes_count"] = len(notes)

        # Episode count
        episodes = self._load_episodes()
        result["total_episodes"] = len(episodes)

        return result

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _resolve_agent_file(self, agent_id: str) -> Path:
        """Resolve the agent's private context file."""
        return self._base / AGENTS_SUBDIR / f"{agent_id}.md"

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate (1 token ≈ 0.75 words)."""
        return int(len(text.split()) / 0.75)
