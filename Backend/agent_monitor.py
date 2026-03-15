"""
agent_monitor.py — Agent Monitoring and Metrics Aggregation

Collects, aggregates, and reports metrics for all managed agents.
Provides per-agent and fleet-wide views of status, token usage,
cost, uptime, and health.

Architecture Reference: R4_Architekturentwurf.md section 3.2
                        R5_Integration_Roadmap.md D3
Phase: D — Scale

Features:
  - Per-agent metric tracking (tokens, cost, messages, errors)
  - Fleet-wide aggregation (totals, averages, distributions)
  - Alert thresholds (stale heartbeat, memory, rate limits)
  - Model pricing for cost calculation
  - Metric snapshots for time-series analysis
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Alert thresholds
STALE_THRESHOLD_SECONDS = 60.0       # Agent considered stale
DISCONNECT_THRESHOLD_SECONDS = 180.0  # Agent considered disconnected
MAX_MEMORY_MB = 100                   # Memory limit per agent
MAX_MESSAGES_PER_MINUTE = 200         # Rate limit per agent

# Model pricing (USD per 1M tokens)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0},
    "claude-haiku-3.5": {"input": 0.80, "output": 4.0},
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-pro": {"input": 1.25, "output": 5.0},
}


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class AgentMetrics:
    """Metrics for a single agent."""

    agent_id: str
    tokens_input: int = 0
    tokens_output: int = 0
    total_messages_sent: int = 0
    total_messages_received: int = 0
    total_errors: int = 0
    total_tasks_completed: int = 0
    model: str = ""
    last_heartbeat: float = 0.0
    started_at: float = 0.0
    memory_bytes: int = 0

    @property
    def total_tokens(self) -> int:
        return self.tokens_input + self.tokens_output

    @property
    def uptime_seconds(self) -> float:
        if self.started_at == 0:
            return 0.0
        return time.time() - self.started_at

    @property
    def cost_usd(self) -> float:
        """Calculate cost based on model pricing."""
        pricing = MODEL_PRICING.get(self.model)
        if pricing is None:
            return 0.0
        input_cost = (self.tokens_input / 1_000_000) * pricing["input"]
        output_cost = (self.tokens_output / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "total_tokens": self.total_tokens,
            "total_messages_sent": self.total_messages_sent,
            "total_messages_received": self.total_messages_received,
            "total_errors": self.total_errors,
            "total_tasks_completed": self.total_tasks_completed,
            "model": self.model,
            "cost_usd": round(self.cost_usd, 6),
            "uptime_seconds": round(self.uptime_seconds, 1),
            "memory_bytes": self.memory_bytes,
            "last_heartbeat": self.last_heartbeat,
        }


@dataclass
class Alert:
    """A monitoring alert."""

    agent_id: str
    level: str           # "warning" | "critical"
    category: str        # "heartbeat" | "memory" | "rate" | "error"
    message: str
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "level": self.level,
            "category": self.category,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass
class FleetSummary:
    """Aggregated fleet-wide metrics."""

    total_agents: int = 0
    running_agents: int = 0
    stale_agents: int = 0
    disconnected_agents: int = 0
    errored_agents: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_messages: int = 0
    total_errors: int = 0
    total_tasks_completed: int = 0
    alerts: list[Alert] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_agents": self.total_agents,
            "running_agents": self.running_agents,
            "stale_agents": self.stale_agents,
            "disconnected_agents": self.disconnected_agents,
            "errored_agents": self.errored_agents,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_messages": self.total_messages,
            "total_errors": self.total_errors,
            "total_tasks_completed": self.total_tasks_completed,
            "active_alerts": len(self.alerts),
        }


# ---------------------------------------------------------------------------
# Agent Monitor
# ---------------------------------------------------------------------------

class AgentMonitor:
    """Collects and aggregates agent metrics.

    Thread-safe for concurrent metric updates from multiple agents.
    """

    def __init__(
        self,
        stale_threshold: float = STALE_THRESHOLD_SECONDS,
        disconnect_threshold: float = DISCONNECT_THRESHOLD_SECONDS,
        max_alerts: int = 1000,
    ):
        """Initialize the monitor.

        Args:
            stale_threshold: Seconds before agent is considered stale.
            disconnect_threshold: Seconds before agent is disconnected.
            max_alerts: Max alerts to keep in memory.
        """
        self._metrics: dict[str, AgentMetrics] = {}
        self._alerts: list[Alert] = []
        self._max_alerts = max_alerts
        self._stale_threshold = stale_threshold
        self._disconnect_threshold = disconnect_threshold
        self._lock = threading.Lock()
        self._snapshots: list[dict[str, Any]] = []
        self._max_snapshots = 100

    # -------------------------------------------------------------------
    # Agent Registration
    # -------------------------------------------------------------------

    def register_agent(
        self,
        agent_id: str,
        model: str = "",
    ) -> AgentMetrics:
        """Register an agent for monitoring.

        Args:
            agent_id: Unique agent ID.
            model: Model name for cost calculation.

        Returns:
            AgentMetrics instance.
        """
        with self._lock:
            if agent_id not in self._metrics:
                self._metrics[agent_id] = AgentMetrics(
                    agent_id=agent_id,
                    model=model,
                    started_at=time.time(),
                    last_heartbeat=time.time(),
                )
            return self._metrics[agent_id]

    def unregister_agent(self, agent_id: str) -> bool:
        """Remove an agent from monitoring.

        Returns True if removed.
        """
        with self._lock:
            return self._metrics.pop(agent_id, None) is not None

    # -------------------------------------------------------------------
    # Metric Recording
    # -------------------------------------------------------------------

    def record_tokens(
        self,
        agent_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Record token usage for an agent."""
        with self._lock:
            m = self._metrics.get(agent_id)
            if m is None:
                return
            m.tokens_input += input_tokens
            m.tokens_output += output_tokens

    def record_message_sent(self, agent_id: str) -> None:
        """Record that an agent sent a message."""
        with self._lock:
            m = self._metrics.get(agent_id)
            if m:
                m.total_messages_sent += 1

    def record_message_received(self, agent_id: str) -> None:
        """Record that an agent received a message."""
        with self._lock:
            m = self._metrics.get(agent_id)
            if m:
                m.total_messages_received += 1

    def record_error(self, agent_id: str) -> None:
        """Record an error for an agent."""
        with self._lock:
            m = self._metrics.get(agent_id)
            if m:
                m.total_errors += 1

    def record_task_completed(self, agent_id: str) -> None:
        """Record a task completion."""
        with self._lock:
            m = self._metrics.get(agent_id)
            if m:
                m.total_tasks_completed += 1

    def record_heartbeat(self, agent_id: str) -> None:
        """Record a heartbeat for an agent."""
        with self._lock:
            m = self._metrics.get(agent_id)
            if m:
                m.last_heartbeat = time.time()

    def record_memory(self, agent_id: str, memory_bytes: int) -> None:
        """Record memory usage for an agent."""
        with self._lock:
            m = self._metrics.get(agent_id)
            if m:
                m.memory_bytes = memory_bytes

    # -------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------

    def get_metrics(self, agent_id: str) -> AgentMetrics | None:
        """Get metrics for a specific agent."""
        return self._metrics.get(agent_id)

    def get_all_metrics(self) -> list[AgentMetrics]:
        """Get metrics for all agents."""
        return list(self._metrics.values())

    def get_cost(self, agent_id: str) -> float:
        """Get cost for a specific agent."""
        m = self._metrics.get(agent_id)
        if m is None:
            return 0.0
        return m.cost_usd

    def get_total_cost(self) -> float:
        """Get total cost across all agents."""
        return sum(m.cost_usd for m in self._metrics.values())

    def get_total_tokens(self) -> int:
        """Get total tokens across all agents."""
        return sum(m.total_tokens for m in self._metrics.values())

    # -------------------------------------------------------------------
    # Health Checks
    # -------------------------------------------------------------------

    def check_health(self) -> list[Alert]:
        """Run health checks and generate alerts.

        Checks:
          - Stale heartbeat (> stale_threshold)
          - Disconnected (> disconnect_threshold)
          - Memory limit (> MAX_MEMORY_MB)

        Returns:
            List of new alerts generated.
        """
        now = time.time()
        new_alerts: list[Alert] = []

        with self._lock:
            for m in self._metrics.values():
                if m.last_heartbeat == 0:
                    continue

                age = now - m.last_heartbeat

                # Disconnected check (critical)
                if age > self._disconnect_threshold:
                    alert = Alert(
                        agent_id=m.agent_id,
                        level="critical",
                        category="heartbeat",
                        message=(
                            f"Agent disconnected: no heartbeat for "
                            f"{age:.0f}s (threshold: "
                            f"{self._disconnect_threshold:.0f}s)"
                        ),
                    )
                    new_alerts.append(alert)

                # Stale check (warning)
                elif age > self._stale_threshold:
                    alert = Alert(
                        agent_id=m.agent_id,
                        level="warning",
                        category="heartbeat",
                        message=(
                            f"Agent stale: no heartbeat for "
                            f"{age:.0f}s (threshold: "
                            f"{self._stale_threshold:.0f}s)"
                        ),
                    )
                    new_alerts.append(alert)

                # Memory check
                memory_mb = m.memory_bytes / (1024 * 1024)
                if memory_mb > MAX_MEMORY_MB:
                    alert = Alert(
                        agent_id=m.agent_id,
                        level="warning",
                        category="memory",
                        message=(
                            f"Memory usage {memory_mb:.1f}MB exceeds "
                            f"limit {MAX_MEMORY_MB}MB"
                        ),
                    )
                    new_alerts.append(alert)

            # Store alerts (with cap)
            self._alerts.extend(new_alerts)
            if len(self._alerts) > self._max_alerts:
                self._alerts = self._alerts[-self._max_alerts:]

        return new_alerts

    def get_alerts(
        self,
        agent_id: str | None = None,
        level: str | None = None,
        limit: int = 50,
    ) -> list[Alert]:
        """Get alerts, optionally filtered.

        Args:
            agent_id: Filter by agent.
            level: Filter by level ("warning" | "critical").
            limit: Max alerts to return.

        Returns:
            List of alerts, newest first.
        """
        alerts = list(reversed(self._alerts))
        if agent_id:
            alerts = [a for a in alerts if a.agent_id == agent_id]
        if level:
            alerts = [a for a in alerts if a.level == level]
        return alerts[:limit]

    def clear_alerts(self) -> int:
        """Clear all alerts. Returns count cleared."""
        with self._lock:
            count = len(self._alerts)
            self._alerts.clear()
            return count

    # -------------------------------------------------------------------
    # Fleet Summary
    # -------------------------------------------------------------------

    def fleet_summary(self) -> FleetSummary:
        """Generate fleet-wide summary."""
        now = time.time()
        summary = FleetSummary()

        with self._lock:
            summary.total_agents = len(self._metrics)
            summary.alerts = list(self._alerts)

            for m in self._metrics.values():
                summary.total_tokens += m.total_tokens
                summary.total_cost_usd += m.cost_usd
                summary.total_messages += (
                    m.total_messages_sent + m.total_messages_received
                )
                summary.total_errors += m.total_errors
                summary.total_tasks_completed += m.total_tasks_completed

                # Classify agent state
                if m.last_heartbeat == 0:
                    summary.running_agents += 1
                    continue

                age = now - m.last_heartbeat
                if age > self._disconnect_threshold:
                    summary.disconnected_agents += 1
                elif age > self._stale_threshold:
                    summary.stale_agents += 1
                else:
                    summary.running_agents += 1

                if m.total_errors > 0:
                    summary.errored_agents += 1

        return summary

    # -------------------------------------------------------------------
    # Snapshots
    # -------------------------------------------------------------------

    def take_snapshot(self) -> dict[str, Any]:
        """Take a point-in-time snapshot of all metrics.

        Snapshots are stored for time-series analysis.

        Returns:
            Snapshot dict with timestamp and all agent metrics.
        """
        snapshot = {
            "timestamp": time.time(),
            "agents": {
                aid: m.to_dict()
                for aid, m in self._metrics.items()
            },
            "fleet": self.fleet_summary().to_dict(),
        }

        with self._lock:
            self._snapshots.append(snapshot)
            if len(self._snapshots) > self._max_snapshots:
                self._snapshots = self._snapshots[-self._max_snapshots:]

        return snapshot

    def get_snapshots(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent snapshots."""
        return self._snapshots[-limit:]

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return monitor status."""
        fleet = self.fleet_summary()
        return {
            "total_agents_monitored": len(self._metrics),
            "total_tokens": self.get_total_tokens(),
            "total_cost_usd": round(self.get_total_cost(), 6),
            "active_alerts": len(self._alerts),
            "snapshots_stored": len(self._snapshots),
            "fleet": fleet.to_dict(),
            "agents": [m.to_dict() for m in self._metrics.values()],
        }
