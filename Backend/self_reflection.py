"""
self_reflection.py — Self-Reflection and Memory Distillation

Enables agents to reflect on their experiences and distill
raw episodes into curated lessons. Two tiers:
  1. Session-end reflection (immediate)
  2. Periodic distillation (background, 24h cycle)

Architecture Reference: R5_Integration_Roadmap.md D5
                        R1_Agent_Soul_Identity.md (Growth Protocol)
Phase: D — Scale

Features:
  - Session-end reflection prompt generation
  - Episode distillation (raw episodes -> curated lessons)
  - Heuristic extraction from experiences
  - Growth proposal generation for Soul Engine
  - MEMORY.md management (read/write curated knowledge)
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from persistence_utils import ensure_agent_memory_file, find_agent_memory_path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DISTILLATION_INTERVAL_HOURS = 24
MAX_EPISODES_PER_DISTILLATION = 50
MAX_LESSON_LENGTH = 2000
MAX_REFLECTION_LENGTH = 5000


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class Lesson:
    """A distilled lesson from raw episodes."""

    title: str
    content: str
    source_episodes: list[str] = field(default_factory=list)
    category: str = "general"     # general, technical, collaboration, process
    confidence: float = 1.0       # 0.0 - 1.0
    created_at: float = 0.0
    agent_id: str = ""

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "source_episodes": self.source_episodes,
            "category": self.category,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "agent_id": self.agent_id,
        }

    def to_markdown(self) -> str:
        """Format as markdown section for MEMORY.md."""
        lines = [
            f"### {self.title}",
            f"*Category: {self.category} | "
            f"Confidence: {self.confidence:.0%} | "
            f"Agent: {self.agent_id}*",
            "",
            self.content,
            "",
        ]
        if self.source_episodes:
            lines.append(f"*Sources: {', '.join(self.source_episodes)}*")
            lines.append("")
        return "\n".join(lines)


@dataclass
class ReflectionPrompt:
    """A reflection prompt for session-end review."""

    agent_id: str
    questions: list[str]
    context: str = ""             # Summary of what happened this session
    session_duration: float = 0.0
    tasks_completed: int = 0

    def to_text(self) -> str:
        """Format as text prompt for the agent."""
        lines = ["## Session Reflection", ""]
        if self.context:
            lines.append(f"**Session Summary:** {self.context}")
            lines.append("")
        if self.session_duration > 0:
            hours = self.session_duration / 3600
            lines.append(f"**Duration:** {hours:.1f} hours")
        if self.tasks_completed > 0:
            lines.append(f"**Tasks Completed:** {self.tasks_completed}")
        lines.append("")
        lines.append("Please reflect on the following:")
        lines.append("")
        for i, q in enumerate(self.questions, 1):
            lines.append(f"{i}. {q}")
        lines.append("")
        lines.append(
            "Write your reflections as a daily note or episode summary."
        )
        return "\n".join(lines)


@dataclass
class GrowthProposal:
    """A proposal for updating an agent's soul/identity."""

    agent_id: str
    category: str        # "strength" | "weakness" | "preference" | "insight"
    description: str
    evidence: str        # What led to this proposal
    confidence: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "category": self.category,
            "description": self.description,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Reflection Categories
# ---------------------------------------------------------------------------

REFLECTION_QUESTIONS = {
    "technical": [
        "What technical patterns or approaches worked well?",
        "What technical mistakes did I make, and what would I do differently?",
        "What new tools or techniques did I learn?",
    ],
    "collaboration": [
        "How effectively did I communicate with other agents?",
        "Were there any misunderstandings or coordination issues?",
        "What could improve our team workflow?",
    ],
    "process": [
        "Did I follow the established processes correctly?",
        "Were there any bottlenecks or inefficiencies?",
        "What process improvements would I suggest?",
    ],
    "general": [
        "What were the most important outcomes of this session?",
        "What did I learn that I should remember for future sessions?",
        "What should I prioritize next time?",
    ],
}

LESSON_CATEGORIES = frozenset({
    "general", "technical", "collaboration", "process",
})


# ---------------------------------------------------------------------------
# Self-Reflection Engine
# ---------------------------------------------------------------------------

class SelfReflection:
    """Manages agent self-reflection and memory distillation.

    Two-tier reflection system:
      1. Session-end: Generate reflection prompts, process responses
      2. Periodic: Distill raw episodes into curated lessons
    """

    def __init__(
        self,
        base_path: Path,
        agent_configs: dict[str, dict[str, Any]] | None = None,
    ):
        """Initialize self-reflection engine.

        Args:
            base_path: Base path (typically .agent/ directory).
            agent_configs: Optional explicit agent identity/config mapping.
                When provided, this is preferred over implicit team.json lookup.
        """
        self._base = base_path
        self._lessons_dir = base_path / "lessons"
        self._last_distillation: dict[str, float] = {}  # agent_id -> timestamp
        self._team_config_path = self._discover_team_config_path(base_path)
        self._agent_state_dir = self._discover_agent_state_dir(base_path)
        self._seed_agent_configs = agent_configs or {}
        self._agent_configs: dict[str, dict[str, Any]] | None = None

    # -------------------------------------------------------------------
    # Session-End Reflection
    # -------------------------------------------------------------------

    def generate_reflection_prompt(
        self,
        agent_id: str,
        categories: list[str] | None = None,
        context: str = "",
        session_duration: float = 0.0,
        tasks_completed: int = 0,
    ) -> ReflectionPrompt:
        """Generate a reflection prompt for session-end review.

        Args:
            agent_id: Agent to generate prompt for.
            categories: Question categories to include (default: all).
            context: Session summary context.
            session_duration: Session length in seconds.
            tasks_completed: Number of tasks completed.

        Returns:
            ReflectionPrompt with questions.
        """
        cats = categories or list(REFLECTION_QUESTIONS.keys())
        questions: list[str] = []
        for cat in cats:
            if cat in REFLECTION_QUESTIONS:
                questions.extend(REFLECTION_QUESTIONS[cat])

        return ReflectionPrompt(
            agent_id=agent_id,
            questions=questions,
            context=context,
            session_duration=session_duration,
            tasks_completed=tasks_completed,
        )

    # -------------------------------------------------------------------
    # Lesson Management
    # -------------------------------------------------------------------

    def add_lesson(
        self,
        agent_id: str,
        title: str,
        content: str,
        category: str = "general",
        source_episodes: list[str] | None = None,
        confidence: float = 1.0,
    ) -> Lesson:
        """Add a curated lesson from reflection or distillation.

        Args:
            agent_id: Agent who learned this.
            title: Lesson title.
            content: Lesson content.
            category: One of LESSON_CATEGORIES.
            source_episodes: Episode IDs that led to this lesson.
            confidence: Confidence level (0.0-1.0).

        Returns:
            The created Lesson.

        Raises:
            ValueError: If inputs invalid.
        """
        if not title:
            raise ValueError("Lesson title must not be empty")
        if not content:
            raise ValueError("Lesson content must not be empty")
        if len(content) > MAX_LESSON_LENGTH:
            raise ValueError(
                f"Lesson content exceeds max length ({MAX_LESSON_LENGTH})"
            )
        if category not in LESSON_CATEGORIES:
            raise ValueError(
                f"Invalid category: {category}. "
                f"Valid: {', '.join(sorted(LESSON_CATEGORIES))}"
            )
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")

        lesson = Lesson(
            title=title,
            content=content,
            source_episodes=source_episodes or [],
            category=category,
            confidence=confidence,
            agent_id=agent_id,
        )

        # Persist to MEMORY.md
        self._append_to_memory(agent_id, lesson)

        return lesson

    def get_lessons(
        self,
        agent_id: str,
        category: str | None = None,
    ) -> list[Lesson]:
        """Get lessons for an agent from MEMORY.md.

        Parses the agent's MEMORY.md file for lesson entries.

        Args:
            agent_id: Agent ID.
            category: Optional category filter.

        Returns:
            List of Lesson objects.
        """
        memory_path = self._get_memory_path(agent_id)
        if not memory_path.exists():
            return []

        try:
            content = memory_path.read_text(encoding="utf-8")
        except OSError:
            return []

        lessons = self._parse_lessons(content, agent_id)

        if category:
            lessons = [l for l in lessons if l.category == category]

        return lessons

    # -------------------------------------------------------------------
    # Distillation
    # -------------------------------------------------------------------

    def needs_distillation(
        self,
        agent_id: str,
        interval_hours: float = DISTILLATION_INTERVAL_HOURS,
    ) -> bool:
        """Check if an agent needs periodic distillation.

        Returns True if enough time has passed since last distillation.
        """
        last = self._last_distillation.get(agent_id, 0)
        if last == 0:
            return True
        elapsed_hours = (time.time() - last) / 3600
        return elapsed_hours >= interval_hours

    def mark_distilled(self, agent_id: str) -> None:
        """Mark that distillation was performed for an agent."""
        self._last_distillation[agent_id] = time.time()

    def prepare_distillation_input(
        self,
        agent_id: str,
        episodes_dir: Path,
        max_episodes: int = MAX_EPISODES_PER_DISTILLATION,
    ) -> dict[str, Any]:
        """Prepare input data for distillation.

        Reads raw episodes and formats them for LLM processing.

        Args:
            agent_id: Agent to distill for.
            episodes_dir: Path to episodes directory.
            max_episodes: Max episodes to include.

        Returns:
            Dict with episodes text, count, and metadata.
        """
        index_path = episodes_dir / "index.jsonl"
        if not index_path.exists():
            return {
                "agent_id": agent_id,
                "episode_count": 0,
                "episodes_text": "",
                "existing_lessons": len(self.get_lessons(agent_id)),
            }

        import json

        episodes: list[dict[str, Any]] = []
        try:
            with open(index_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ep = json.loads(line)
                        if ep.get("agent_id") == agent_id:
                            episodes.append(ep)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

        # Take most recent episodes
        episodes = episodes[-max_episodes:]

        # Format as text
        lines: list[str] = []
        for ep in episodes:
            lines.append(f"## Episode: {ep.get('task', 'Untitled')}")
            lines.append(f"Date: {ep.get('timestamp', 'unknown')}")
            lines.append(f"Summary: {ep.get('summary', '')}")
            if ep.get("bullets"):
                for b in ep["bullets"]:
                    lines.append(f"- {b}")
            lines.append("")

        return {
            "agent_id": agent_id,
            "episode_count": len(episodes),
            "episodes_text": "\n".join(lines),
            "existing_lessons": len(self.get_lessons(agent_id)),
        }

    def generate_distillation_prompt(
        self,
        distillation_input: dict[str, Any],
    ) -> str:
        """Generate a prompt for the LLM to distill episodes.

        Args:
            distillation_input: Output from prepare_distillation_input().

        Returns:
            Prompt string for the distillation LLM call.
        """
        agent_id = distillation_input["agent_id"]
        episode_count = distillation_input["episode_count"]
        episodes_text = distillation_input["episodes_text"]
        existing_count = distillation_input["existing_lessons"]

        if episode_count == 0:
            return ""

        return (
            f"You are reviewing {episode_count} episodes from agent "
            f"'{agent_id}' (who already has {existing_count} lessons).\n\n"
            f"## Episodes\n\n{episodes_text}\n\n"
            f"## Task\n\n"
            f"Extract 1-5 key lessons from these episodes. For each lesson:\n"
            f"1. Title (short, actionable)\n"
            f"2. Content (1-3 sentences)\n"
            f"3. Category (technical / collaboration / process / general)\n"
            f"4. Confidence (high / medium / low)\n\n"
            f"Format each lesson as:\n"
            f"### [Title]\n"
            f"Category: [category]\n"
            f"Confidence: [confidence]\n"
            f"[Content]\n"
        )

    # -------------------------------------------------------------------
    # Growth Proposals
    # -------------------------------------------------------------------

    def generate_growth_proposal(
        self,
        agent_id: str,
        category: str,
        description: str,
        evidence: str,
        confidence: float = 0.8,
    ) -> GrowthProposal:
        """Create a growth proposal for the Soul Engine.

        Args:
            agent_id: Agent proposing growth.
            category: "strength", "weakness", "preference", "insight".
            description: What the agent learned about itself.
            evidence: What experiences led to this insight.
            confidence: How confident the agent is.

        Returns:
            GrowthProposal to submit to Soul Engine.

        Raises:
            ValueError: If inputs invalid.
        """
        valid_categories = {"strength", "weakness", "preference", "insight"}
        if category not in valid_categories:
            raise ValueError(
                f"Invalid growth category: {category}. "
                f"Valid: {', '.join(sorted(valid_categories))}"
            )
        if not description:
            raise ValueError("Description must not be empty")
        if not evidence:
            raise ValueError("Evidence must not be empty")

        return GrowthProposal(
            agent_id=agent_id,
            category=category,
            description=description,
            evidence=evidence,
            confidence=confidence,
        )

    # -------------------------------------------------------------------
    # MEMORY.md Management
    # -------------------------------------------------------------------

    def read_memory(self, agent_id: str) -> str:
        """Read an agent's MEMORY.md content.

        Returns empty string if file doesn't exist.
        """
        path = self._get_memory_path(agent_id)
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def write_memory(self, agent_id: str, content: str) -> dict[str, Any]:
        """Replace an agent's MEMORY.md content.

        Args:
            agent_id: Agent ID.
            content: Full new content.

        Returns:
            Result dict with path and size.
        """
        path = self._get_memory_path(agent_id, create=True)
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        # Atomic write via temp file + os.replace()
        fd, tmp = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, str(path))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "agent_id": agent_id,
        }

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    def _get_memory_path(self, agent_id: str, *, create: bool = False) -> Path:
        """Get the MEMORY.md path for an agent.

        When running inside the Bridge backend, prefer the same CLI-backed
        memory location used by restore/health. Otherwise fall back to the
        legacy local reflection store.
        """
        cli_path = self._resolve_cli_memory_path(agent_id, create=create)
        if cli_path is not None:
            return cli_path
        return self._legacy_memory_path(agent_id)

    def _append_to_memory(self, agent_id: str, lesson: Lesson) -> None:
        """Append a lesson to an agent's MEMORY.md."""
        path = self._get_memory_path(agent_id, create=True)
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)

        if not path.exists():
            # Atomic create via temp file + os.replace()
            header = f"# Memory — {agent_id}\n\n## Lessons\n\n"
            fd, tmp = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(header)
                os.replace(tmp, str(path))
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

        with open(path, "a", encoding="utf-8") as f:
            f.write(lesson.to_markdown())

    def _parse_lessons(
        self,
        content: str,
        agent_id: str,
    ) -> list[Lesson]:
        """Parse lessons from MEMORY.md content.

        Looks for ### headers followed by category/confidence metadata.
        """
        lessons: list[Lesson] = []
        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # Look for lesson headers (### Title)
            if line.startswith("### ") and not line.startswith("#### "):
                title = line[4:].strip()
                category = "general"
                confidence = 1.0
                content_lines: list[str] = []

                i += 1
                # Parse metadata line
                if i < len(lines) and lines[i].startswith("*Category:"):
                    meta_line = lines[i]
                    if "Category:" in meta_line:
                        cat_part = meta_line.split("Category:")[1].split("|")[0].strip()
                        if cat_part in LESSON_CATEGORIES:
                            category = cat_part
                    if "Confidence:" in meta_line:
                        conf_part = meta_line.split("Confidence:")[1].split("|")[0].strip()
                        conf_part = conf_part.rstrip("*").rstrip("%").strip()
                        try:
                            confidence = float(conf_part) / 100 if float(conf_part) > 1 else float(conf_part)
                        except ValueError:
                            pass
                    i += 1

                # Collect content until next ### or end
                while i < len(lines):
                    if lines[i].startswith("### ") and not lines[i].startswith("#### "):
                        break
                    if lines[i].startswith("*Sources:"):
                        i += 1
                        continue
                    content_lines.append(lines[i])
                    i += 1

                lesson_content = "\n".join(content_lines).strip()
                if title and lesson_content:
                    lessons.append(Lesson(
                        title=title,
                        content=lesson_content,
                        category=category,
                        confidence=confidence,
                        agent_id=agent_id,
                    ))
            else:
                i += 1

        return lessons

    def _legacy_memory_path(self, agent_id: str) -> Path:
        return self._base / "agents" / agent_id / "MEMORY.md"

    def _resolve_cli_memory_path(
        self,
        agent_id: str,
        *,
        create: bool = False,
    ) -> Path | None:
        agent_config = self._get_agent_config(agent_id)
        if not agent_config:
            return None

        agent_home = str(agent_config.get("home_dir", "")).strip()
        if not agent_home:
            return None

        config_dir = str(agent_config.get("config_dir", "")).strip()
        resolved = find_agent_memory_path(agent_id, agent_home, config_dir)
        if not resolved and create:
            agent_role = str(agent_config.get("role", "")).strip()
            resolved = ensure_agent_memory_file(
                agent_id,
                agent_role,
                agent_home,
                config_dir,
            )

        if resolved:
            return Path(resolved)
        return None

    def _get_agent_config(self, agent_id: str) -> dict[str, Any] | None:
        config = self._load_agent_configs().get(agent_id)
        if config is not None:
            return config

        runtime_config = self._load_runtime_agent_config(agent_id)
        if runtime_config is not None:
            self._load_agent_configs()[agent_id] = runtime_config
        return runtime_config

    def _load_agent_configs(self) -> dict[str, dict[str, Any]]:
        if self._agent_configs is None:
            self._agent_configs = {}
            for seed_id, agent in self._seed_agent_configs.items():
                resolved_id, normalized = self._normalize_agent_config(seed_id, agent)
                if resolved_id and resolved_id not in self._agent_configs:
                    self._agent_configs[resolved_id] = normalized
            if self._team_config_path is not None:
                try:
                    payload = json.loads(
                        self._team_config_path.read_text(encoding="utf-8"),
                    )
                except (OSError, json.JSONDecodeError):
                    payload = {}
                for agent in payload.get("agents", []):
                    resolved_id, normalized = self._normalize_agent_config("", agent)
                    if resolved_id and resolved_id not in self._agent_configs:
                        self._agent_configs[resolved_id] = normalized
        return self._agent_configs

    def _normalize_agent_config(
        self,
        fallback_agent_id: str,
        agent: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any]]:
        payload = dict(agent or {})
        resolved_id = str(payload.get("id", fallback_agent_id)).strip()
        if resolved_id:
            payload["id"] = resolved_id
        workspace = str(payload.get("workspace", "")).strip()
        if workspace and not str(payload.get("home_dir", "")).strip():
            payload["home_dir"] = workspace
        return resolved_id, payload

    def _discover_team_config_path(self, base_path: Path) -> Path | None:
        for candidate in (base_path / "team.json", base_path.parent / "team.json"):
            if candidate.is_file():
                return candidate
        return None

    def _discover_agent_state_dir(self, base_path: Path) -> Path | None:
        for candidate in (base_path / "agent_state", base_path.parent / "agent_state"):
            if candidate.is_dir():
                return candidate
        return None

    def _load_runtime_agent_config(self, agent_id: str) -> dict[str, Any] | None:
        if self._agent_state_dir is None:
            return None

        state_path = self._agent_state_dir / f"{agent_id}.json"
        if not state_path.is_file():
            return None

        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        resolved_id, normalized = self._normalize_agent_config(agent_id, payload)
        if resolved_id != agent_id:
            return None
        return normalized

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return self-reflection engine status."""
        agent_memories: dict[str, int] = {}

        for agent_id in sorted(self._load_agent_configs().keys()):
            memory_path = self._resolve_cli_memory_path(agent_id)
            if memory_path is None or not memory_path.exists():
                continue
            try:
                agent_memories[agent_id] = memory_path.stat().st_size
            except OSError:
                continue

        agents_dir = self._base / "agents"
        if agents_dir.exists():
            for agent_dir in agents_dir.iterdir():
                if not agent_dir.is_dir():
                    continue
                memory_path = agent_dir / "MEMORY.md"
                if memory_path.exists():
                    agent_memories.setdefault(
                        agent_dir.name,
                        memory_path.stat().st_size,
                    )

        return {
            "base_path": str(self._base),
            "lessons_dir": str(self._lessons_dir),
            "agents_with_memory": list(agent_memories.keys()),
            "memory_sizes": agent_memories,
            "last_distillation": dict(self._last_distillation),
            "reflection_categories": list(REFLECTION_QUESTIONS.keys()),
            "lesson_categories": sorted(LESSON_CATEGORIES),
        }
