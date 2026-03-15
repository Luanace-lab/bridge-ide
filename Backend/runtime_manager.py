"""
runtime_manager.py — Agent Runtime & Factory for Bridge IDE

Orchestrates agent lifecycle using all platform modules:
  - Engine selection (engine_abc)
  - Identity (soul_engine)
  - Memory (memory_engine)
  - Skills (skill_manager)
  - Credentials (credential_vault)
  - Approvals (approval_gate)
  - Configuration (config)

Architecture Reference: R4_Architekturentwurf.md section 3.2.9
Phase: D — Scale

Features:
  - Dynamic agent creation (spawn, configure, start)
  - Agent lifecycle (start, stop, restart, status)
  - Slot management (max concurrent agents)
  - Agent registry with health monitoring
  - Integration with all Phase A-C modules
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from config import cfg


# ---------------------------------------------------------------------------
# Agent State
# ---------------------------------------------------------------------------

class AgentState(Enum):
    """Agent lifecycle states."""

    CREATING = "creating"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class AgentInfo:
    """Runtime information about a managed agent."""

    agent_id: str
    role: str
    engine: str                          # Engine name (registry key)
    state: AgentState = AgentState.STOPPED
    created_at: float = 0.0
    started_at: float = 0.0
    stopped_at: float = 0.0
    last_heartbeat: float = 0.0
    error: str = ""
    skills: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "engine": self.engine,
            "state": self.state.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "last_heartbeat": self.last_heartbeat,
            "error": self.error,
            "skills": self.skills,
            "metadata": self.metadata,
        }

    @property
    def uptime_seconds(self) -> float:
        if self.state != AgentState.RUNNING or self.started_at == 0:
            return 0.0
        return time.time() - self.started_at


# ---------------------------------------------------------------------------
# Runtime Manager
# ---------------------------------------------------------------------------

class RuntimeManager:
    """Manages agent lifecycle and coordinates platform modules.

    Central orchestrator that ties together:
      - Engine adapters (engine_abc)
      - Agent identity (soul_engine)
      - Persistent memory (memory_engine)
      - Skill registry (skill_manager)
      - Configuration (config)

    Thread-safe for concurrent agent operations.
    """

    def __init__(
        self,
        max_agents: int = 10,
        project_path: Path | None = None,
    ):
        """Initialize the runtime manager.

        Args:
            max_agents: Maximum concurrent agents (slot limit).
            project_path: Project root path. Defaults to config.
        """
        self._max_agents = max_agents
        self._project_path = project_path or cfg.PROJECT_PATH
        self._agents: dict[str, AgentInfo] = {}
        self._lock = threading.Lock()

    # -------------------------------------------------------------------
    # Agent Creation
    # -------------------------------------------------------------------

    def create_agent(
        self,
        agent_id: str,
        role: str,
        engine: str = "claude",
        skills: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentInfo:
        """Create a new agent (does not start it).

        Args:
            agent_id: Unique agent identifier.
            role: Agent role description.
            engine: Engine name from registry.
            skills: Skills to activate.
            metadata: Additional metadata.

        Returns:
            AgentInfo for the created agent.

        Raises:
            ValueError: If agent_id already exists or slots full.
        """
        with self._lock:
            if agent_id in self._agents:
                raise ValueError(f"Agent '{agent_id}' already exists")

            active = sum(
                1 for a in self._agents.values()
                if a.state in (AgentState.RUNNING, AgentState.STARTING)
            )
            if active >= self._max_agents:
                raise ValueError(
                    f"Agent slot limit reached ({self._max_agents}). "
                    f"Stop an agent before creating a new one."
                )

            info = AgentInfo(
                agent_id=agent_id,
                role=role,
                engine=engine,
                state=AgentState.CREATING,
                created_at=time.time(),
                skills=skills or [],
                metadata=metadata or {},
            )
            self._agents[agent_id] = info
            return info

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent from the registry.

        Agent must be stopped first.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            info = self._agents.get(agent_id)
            if info is None:
                return False
            if info.state in (AgentState.RUNNING, AgentState.STARTING):
                raise ValueError(
                    f"Agent '{agent_id}' is {info.state.value}. Stop it first."
                )
            del self._agents[agent_id]
            return True

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    def start_agent(self, agent_id: str) -> bool:
        """Start a created agent.

        This transitions the agent to RUNNING state. In a full
        implementation, this would call the engine adapter's start()
        and configure soul, memory, skills.

        Args:
            agent_id: Agent to start.

        Returns:
            True if started successfully.
        """
        with self._lock:
            info = self._agents.get(agent_id)
            if info is None:
                return False
            if info.state == AgentState.RUNNING:
                return True  # Already running
            if info.state not in (AgentState.CREATING, AgentState.STOPPED, AgentState.ERROR):
                return False

            info.state = AgentState.STARTING

        # Transition to running (engine start would happen here)
        with self._lock:
            info.state = AgentState.RUNNING
            info.started_at = time.time()
            info.last_heartbeat = time.time()
            info.error = ""

        return True

    def stop_agent(self, agent_id: str) -> bool:
        """Stop a running agent.

        Args:
            agent_id: Agent to stop.

        Returns:
            True if stopped successfully.
        """
        with self._lock:
            info = self._agents.get(agent_id)
            if info is None:
                return False
            if info.state == AgentState.STOPPED:
                return True

            info.state = AgentState.STOPPING

        # Engine stop would happen here
        with self._lock:
            info.state = AgentState.STOPPED
            info.stopped_at = time.time()

        return True

    def restart_agent(self, agent_id: str) -> bool:
        """Restart an agent (stop + start).

        Returns True if restarted successfully.
        """
        self.stop_agent(agent_id)
        return self.start_agent(agent_id)

    def heartbeat(self, agent_id: str) -> bool:
        """Record a heartbeat for an agent.

        Returns True if agent exists and is running.
        """
        with self._lock:
            info = self._agents.get(agent_id)
            if info is None:
                return False
            if info.state != AgentState.RUNNING:
                return False
            info.last_heartbeat = time.time()
            return True

    def mark_error(self, agent_id: str, error: str) -> bool:
        """Mark an agent as errored.

        Returns True if marked.
        """
        with self._lock:
            info = self._agents.get(agent_id)
            if info is None:
                return False
            info.state = AgentState.ERROR
            info.error = error
            return True

    # -------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------

    def get_agent(self, agent_id: str) -> AgentInfo | None:
        """Get agent info by ID."""
        return self._agents.get(agent_id)

    def list_agents(
        self,
        state: AgentState | None = None,
    ) -> list[AgentInfo]:
        """List all agents, optionally filtered by state."""
        agents = list(self._agents.values())
        if state is not None:
            agents = [a for a in agents if a.state == state]
        return sorted(agents, key=lambda a: a.agent_id)

    def count_running(self) -> int:
        """Count currently running agents."""
        return sum(
            1 for a in self._agents.values()
            if a.state == AgentState.RUNNING
        )

    def count_slots_available(self) -> int:
        """Count available agent slots."""
        return self._max_agents - self.count_running()

    # -------------------------------------------------------------------
    # Health Monitoring
    # -------------------------------------------------------------------

    def check_health(
        self,
        timeout_seconds: float = 120.0,
    ) -> list[AgentInfo]:
        """Check for agents that haven't sent a heartbeat recently.

        Args:
            timeout_seconds: Heartbeat timeout threshold.

        Returns:
            List of agents that are unhealthy (stale heartbeat).
        """
        now = time.time()
        unhealthy: list[AgentInfo] = []

        with self._lock:
            for info in self._agents.values():
                if info.state != AgentState.RUNNING:
                    continue
                if info.last_heartbeat == 0:
                    continue
                if now - info.last_heartbeat > timeout_seconds:
                    unhealthy.append(info)

        return unhealthy

    def cleanup_stale(
        self,
        timeout_seconds: float = 300.0,
    ) -> list[str]:
        """Mark stale agents as errored.

        Args:
            timeout_seconds: Timeout before marking as error.

        Returns:
            List of agent_ids that were marked as error.
        """
        marked: list[str] = []
        now = time.time()

        with self._lock:
            for info in self._agents.values():
                if info.state != AgentState.RUNNING:
                    continue
                if info.last_heartbeat == 0:
                    continue
                if now - info.last_heartbeat > timeout_seconds:
                    info.state = AgentState.ERROR
                    info.error = f"Heartbeat timeout ({timeout_seconds}s)"
                    marked.append(info.agent_id)

        return marked

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return runtime status summary."""
        agents_by_state: dict[str, int] = {}
        for info in self._agents.values():
            state_str = info.state.value
            agents_by_state[state_str] = agents_by_state.get(state_str, 0) + 1

        return {
            "max_agents": self._max_agents,
            "total_agents": len(self._agents),
            "running": self.count_running(),
            "slots_available": self.count_slots_available(),
            "agents_by_state": agents_by_state,
            "agents": [a.to_dict() for a in self.list_agents()],
            "project_path": str(self._project_path),
        }
