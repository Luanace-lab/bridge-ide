"""
skill_manager.py — DEPRECATED (2026-03-07)

Skills functionality has been migrated to server.py:
  - _scan_skills(): Level 1 discovery (name + description)
  - _get_skill_full(): Level 2 full content retrieval
  - _generate_skills_section(): CLAUDE.md section generation
  - GET /skills, GET /skills/{name}/content, GET /skills/{agent_id}/section

This file is kept for reference only. Do not import.

Original: Skill Registry and MCP Server Management.
Manages available skills (SKILL.md files) and MCP server lifecycle.
Progressive disclosure: name+description at startup, full content on activation.

Architecture Reference: R4_Architekturentwurf.md section 3.2.6
Research Reference: R2_Memory_Tools_Skills.md
Phase: B — Capabilities

Features:
  - Filesystem-based skill registry (skills/*/SKILL.md)
  - YAML frontmatter parsing for metadata
  - Progressive disclosure (summary vs. full content)
  - Per-agent skill activation tracking
  - MCP server subprocess lifecycle (start, stop, health check)
  - CLAUDE.md integration (skills section generation)
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class SkillSummary:
    """Lightweight skill info for progressive disclosure Level 1.

    ~100 tokens per skill. Loaded at startup.
    """

    name: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "description": self.description}


@dataclass
class Skill:
    """Full skill definition from SKILL.md.

    Level 2: complete content loaded on activation (<5000 tokens).
    """

    name: str
    description: str
    license: str = ""
    compatibility: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    full_content: str = ""  # Body after YAML frontmatter
    source_path: str = ""   # Path to SKILL.md

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "license": self.license,
            "compatibility": self.compatibility,
            "allowed_tools": self.allowed_tools,
            "metadata": self.metadata,
            "source_path": self.source_path,
            "content_length": len(self.full_content),
        }

    def to_summary(self) -> SkillSummary:
        return SkillSummary(name=self.name, description=self.description)


@dataclass
class MCPServerInfo:
    """MCP server configuration and runtime state."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    running: bool = False
    pid: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "running": self.running,
            "pid": self.pid,
        }


# ---------------------------------------------------------------------------
# YAML Frontmatter Parser (stdlib only, no PyYAML dependency)
# ---------------------------------------------------------------------------

def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like frontmatter from SKILL.md content.

    Simple parser for the subset we use (key: value, lists, nested dicts).
    Does NOT handle full YAML spec — just what we need.

    Args:
        content: Full file content.

    Returns:
        (frontmatter_dict, body_text)
    """
    lines = content.split("\n")

    # Check for frontmatter delimiters
    if not lines or lines[0].strip() != "---":
        return {}, content

    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx == -1:
        return {}, content

    # Parse frontmatter lines
    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1:]).strip()

    fm: dict[str, Any] = {}
    current_key = ""

    for line in fm_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Detect indentation (nested content under current_key)
        indent = len(line) - len(line.lstrip())
        is_indented = indent > 0 and current_key

        if stripped.startswith("- ") and current_key:
            # List item under current key
            item = stripped[2:].strip()
            if isinstance(fm.get(current_key), dict):
                fm[current_key] = []
            if isinstance(fm.get(current_key), list):
                fm[current_key].append(item)
        elif is_indented and ":" in stripped:
            # Nested key under current dict
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if isinstance(fm.get(current_key), dict):
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                fm[current_key][key] = value
        elif ":" in stripped:
            # Top-level key-value pair
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if value:
                # Remove quotes
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                fm[key] = value
                current_key = ""
            else:
                # Value on next lines (list or nested)
                fm[key] = {}
                current_key = key

    return fm, body


# ---------------------------------------------------------------------------
# Skill Manager
# ---------------------------------------------------------------------------

class SkillManager:
    """Manages skill registry, activation, and MCP server lifecycle.

    Skills are discovered from filesystem:
      skills_dir/
        pdf/SKILL.md
        excel/SKILL.md
        ...

    MCP servers are configured via .mcp.json or code.
    """

    def __init__(
        self,
        skills_dir: Path,
        mcp_config_path: Path | None = None,
    ):
        """Initialize the skill manager.

        Args:
            skills_dir: Directory containing skill subdirectories.
            mcp_config_path: Path to .mcp.json for MCP server config.
        """
        self._skills_dir = skills_dir
        self._mcp_config_path = mcp_config_path
        self._skills_cache: dict[str, Skill] = {}
        self._active_skills: dict[str, set[str]] = {}  # agent_id -> set of skill names
        self._mcp_servers: dict[str, MCPServerInfo] = {}
        self._mcp_processes: dict[str, subprocess.Popen[bytes]] = {}

        # Load MCP config if provided
        if mcp_config_path and mcp_config_path.exists():
            self._load_mcp_config(mcp_config_path)

    # -------------------------------------------------------------------
    # Skill Discovery
    # -------------------------------------------------------------------

    def list_skills(self) -> list[SkillSummary]:
        """List all available skills (name + description only).

        Progressive disclosure Level 1: ~100 tokens per skill.
        Scans skills_dir for SKILL.md files.
        """
        skills: list[SkillSummary] = []

        if not self._skills_dir.exists():
            return skills

        for skill_dir in sorted(self._skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            # Load from cache or parse
            skill = self._load_skill(skill_dir.name)
            if skill:
                skills.append(skill.to_summary())

        return skills

    def get_skill(self, name: str) -> Skill | None:
        """Load full skill definition (Level 2: complete content).

        Args:
            name: Skill name (directory name under skills_dir).

        Returns:
            Full Skill object, or None if not found.
        """
        return self._load_skill(name)

    def _load_skill(self, name: str) -> Skill | None:
        """Load and cache a skill from filesystem."""
        if name in self._skills_cache:
            return self._skills_cache[name]

        skill_file = self._skills_dir / name / "SKILL.md"
        if not skill_file.exists():
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")
        except OSError:
            return None

        fm, body = _parse_frontmatter(content)

        # Parse allowed-tools (space-separated string)
        allowed_tools_raw = fm.get("allowed-tools", "")
        allowed_tools = []
        if isinstance(allowed_tools_raw, str) and allowed_tools_raw:
            allowed_tools = allowed_tools_raw.split()
        elif isinstance(allowed_tools_raw, list):
            allowed_tools = allowed_tools_raw

        skill = Skill(
            name=fm.get("name", name),
            description=fm.get("description", ""),
            license=fm.get("license", ""),
            compatibility=fm.get("compatibility", ""),
            allowed_tools=allowed_tools,
            metadata=fm.get("metadata", {}),
            full_content=body,
            source_path=str(skill_file),
        )

        self._skills_cache[name] = skill
        return skill

    def invalidate_cache(self, name: str | None = None) -> None:
        """Clear skill cache. None = all."""
        if name is None:
            self._skills_cache.clear()
        else:
            self._skills_cache.pop(name, None)

    # -------------------------------------------------------------------
    # Skill Activation
    # -------------------------------------------------------------------

    def activate_skill(self, name: str, agent_id: str) -> bool:
        """Activate a skill for an agent.

        Args:
            name: Skill name.
            agent_id: Agent to activate for.

        Returns:
            True if activated, False if skill not found.
        """
        skill = self.get_skill(name)
        if skill is None:
            return False

        if agent_id not in self._active_skills:
            self._active_skills[agent_id] = set()
        self._active_skills[agent_id].add(name)
        return True

    def deactivate_skill(self, name: str, agent_id: str) -> bool:
        """Deactivate a skill for an agent.

        Returns True if was active and now deactivated.
        """
        if agent_id not in self._active_skills:
            return False
        if name not in self._active_skills[agent_id]:
            return False
        self._active_skills[agent_id].discard(name)
        return True

    def get_active_skills(self, agent_id: str) -> list[SkillSummary]:
        """List active skills for an agent."""
        active_names = self._active_skills.get(agent_id, set())
        result = []
        for name in sorted(active_names):
            skill = self.get_skill(name)
            if skill:
                result.append(skill.to_summary())
        return result

    def is_active(self, name: str, agent_id: str) -> bool:
        """Check if a skill is active for an agent."""
        return name in self._active_skills.get(agent_id, set())

    # -------------------------------------------------------------------
    # CLAUDE.md Integration
    # -------------------------------------------------------------------

    def generate_skills_section(self, agent_id: str) -> str:
        """Generate the skills section for CLAUDE.md embedding.

        Lists all available skills (summaries only) and marks
        which ones are active. Active skills get full content injected.

        Args:
            agent_id: Agent to generate for.

        Returns:
            Markdown string for CLAUDE.md.
        """
        all_skills = self.list_skills()
        active_names = self._active_skills.get(agent_id, set())

        if not all_skills:
            return ""

        lines = ["## Available Skills", ""]
        lines.append("| Skill | Description | Status |")
        lines.append("|-------|-------------|--------|")

        for s in all_skills:
            status = "ACTIVE" if s.name in active_names else "available"
            lines.append(f"| {s.name} | {s.description} | {status} |")

        lines.append("")

        # Inject full content for active skills
        for name in sorted(active_names):
            skill = self.get_skill(name)
            if skill and skill.full_content:
                lines.append(f"### Skill: {skill.name}")
                lines.append("")
                lines.append(skill.full_content)
                lines.append("")

        return "\n".join(lines)

    # -------------------------------------------------------------------
    # MCP Server Management
    # -------------------------------------------------------------------

    def list_mcp_servers(self) -> list[MCPServerInfo]:
        """List all configured MCP servers."""
        return list(self._mcp_servers.values())

    def add_mcp_server(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """Register an MCP server configuration."""
        self._mcp_servers[name] = MCPServerInfo(
            name=name,
            command=command,
            args=args or [],
            env=env or {},
        )

    def start_mcp_server(self, name: str) -> bool:
        """Start an MCP server as a subprocess.

        Args:
            name: Registered MCP server name.

        Returns:
            True if started, False if not found or already running.
        """
        server = self._mcp_servers.get(name)
        if server is None:
            return False

        if server.running and server.pid:
            # Check if actually still running
            if self._is_process_alive(server.pid):
                return True

        cmd = [server.command] + server.args
        env = {**os.environ, **server.env}

        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            server.running = True
            server.pid = proc.pid
            self._mcp_processes[name] = proc
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    def stop_mcp_server(self, name: str, timeout: float = 5.0) -> bool:
        """Stop a running MCP server.

        Sends SIGTERM, waits for timeout, then SIGKILL.

        Returns True if stopped.
        """
        server = self._mcp_servers.get(name)
        if server is None:
            return False

        proc = self._mcp_processes.get(name)
        if proc is None:
            server.running = False
            server.pid = None
            return True

        try:
            proc.terminate()
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2.0)
        except OSError:
            pass

        server.running = False
        server.pid = None
        self._mcp_processes.pop(name, None)
        return True

    def health_check_mcp(self, name: str) -> bool:
        """Check if an MCP server is responsive.

        Returns True if process is alive.
        """
        server = self._mcp_servers.get(name)
        if server is None or server.pid is None:
            return False

        alive = self._is_process_alive(server.pid)
        server.running = alive
        return alive

    def _load_mcp_config(self, config_path: Path) -> None:
        """Load MCP server configs from .mcp.json."""
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        servers = data.get("mcpServers", {})
        for name, cfg in servers.items():
            self.add_mcp_server(
                name=name,
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
            )

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        """Check if a process is alive by PID."""
        try:
            os.kill(pid, 0)  # Signal 0 = check existence
            return True
        except OSError:
            return False

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return status of skill registry and MCP servers."""
        return {
            "skills_dir": str(self._skills_dir),
            "skills_dir_exists": self._skills_dir.exists(),
            "total_skills": len(self.list_skills()),
            "cached_skills": len(self._skills_cache),
            "active_skills": {
                agent: list(skills)
                for agent, skills in self._active_skills.items()
            },
            "mcp_servers": [s.to_dict() for s in self._mcp_servers.values()],
        }
