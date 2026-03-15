"""
delegation.py — Hierarchical Delegation and Sub-Agent Spawning

Enables parent agents to decompose tasks, spawn sub-agents,
track progress, and collect results. Lane-Queue system controls
concurrency.

Architecture Reference: R5_Integration_Roadmap.md D6
Phase: D — Scale

Features:
  - Parent-child agent relationships
  - Task decomposition and assignment
  - Lane-Queue concurrency control (main + sub-agent lanes)
  - Result collection and aggregation
  - Timeout management
  - Task lifecycle tracking
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAIN_LANE_LIMIT = 4       # Max concurrent main-level tasks
DEFAULT_SUB_LANE_LIMIT = 8        # Max concurrent sub-agents
DEFAULT_TASK_TIMEOUT = 3600.0     # 1 hour default timeout


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskState(Enum):
    """Task lifecycle states."""

    PENDING = "pending"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Task priority levels."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class DelegationTask:
    """A task delegated to a sub-agent."""

    task_id: str
    parent_agent: str
    description: str
    engine: str = "claude"
    priority: TaskPriority = TaskPriority.NORMAL
    timeout: float = DEFAULT_TASK_TIMEOUT
    state: TaskState = TaskState.PENDING
    assigned_agent: str = ""
    created_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    result: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at == 0:
            return 0.0
        end = self.completed_at if self.completed_at > 0 else time.time()
        return end - self.started_at

    @property
    def is_terminal(self) -> bool:
        return self.state in (
            TaskState.COMPLETED, TaskState.FAILED,
            TaskState.TIMED_OUT, TaskState.CANCELLED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "parent_agent": self.parent_agent,
            "description": self.description,
            "engine": self.engine,
            "priority": self.priority.name.lower(),
            "timeout": self.timeout,
            "state": self.state.value,
            "assigned_agent": self.assigned_agent,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class DelegationResult:
    """Result from a completed sub-agent task."""

    task_id: str
    agent_id: str
    success: bool
    content: str
    elapsed_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "success": self.success,
            "content": self.content,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Lane Queue
# ---------------------------------------------------------------------------

class LaneQueue:
    """FIFO queue with priority and concurrency limit.

    Analog to OpenClaw's Lane-Queue pattern.
    """

    def __init__(self, max_concurrent: int):
        """Initialize lane queue.

        Args:
            max_concurrent: Maximum concurrent items.
        """
        self._max = max_concurrent
        self._active: list[str] = []      # Active task IDs
        self._queue: deque[str] = deque()  # Waiting task IDs (FIFO)
        self._lock = threading.Lock()

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def queued_count(self) -> int:
        return len(self._queue)

    @property
    def available_slots(self) -> int:
        return max(0, self._max - len(self._active))

    def try_acquire(self, task_id: str) -> bool:
        """Try to acquire a slot for a task.

        Returns True if slot acquired (task can start).
        Returns False if at capacity (task queued).
        """
        with self._lock:
            if len(self._active) < self._max:
                self._active.append(task_id)
                return True
            else:
                self._queue.append(task_id)
                return False

    def release(self, task_id: str) -> str | None:
        """Release a slot. Returns next queued task_id if any."""
        with self._lock:
            if task_id in self._active:
                self._active.remove(task_id)

            # Promote next queued item
            if self._queue and len(self._active) < self._max:
                next_id = self._queue.popleft()
                self._active.append(next_id)
                return next_id

            return None

    def remove(self, task_id: str) -> bool:
        """Remove a task from queue or active list."""
        with self._lock:
            if task_id in self._active:
                self._active.remove(task_id)
                return True
            try:
                self._queue.remove(task_id)
                return True
            except ValueError:
                return False

    def status(self) -> dict[str, Any]:
        return {
            "max_concurrent": self._max,
            "active": list(self._active),
            "active_count": len(self._active),
            "queued": list(self._queue),
            "queued_count": len(self._queue),
            "available_slots": self.available_slots,
        }


# ---------------------------------------------------------------------------
# Delegation Manager
# ---------------------------------------------------------------------------

class DelegationManager:
    """Manages hierarchical task delegation and sub-agent spawning.

    Coordinates parent-child agent relationships, task lifecycle,
    and concurrency via Lane-Queue system.
    """

    def __init__(
        self,
        main_lane_limit: int = DEFAULT_MAIN_LANE_LIMIT,
        sub_lane_limit: int = DEFAULT_SUB_LANE_LIMIT,
    ):
        """Initialize delegation manager.

        Args:
            main_lane_limit: Max concurrent main-level tasks.
            sub_lane_limit: Max concurrent sub-agent tasks.
        """
        self._tasks: dict[str, DelegationTask] = {}
        self._main_lane = LaneQueue(main_lane_limit)
        self._sub_lane = LaneQueue(sub_lane_limit)
        self._results: dict[str, DelegationResult] = {}
        self._children: dict[str, list[str]] = {}  # parent -> [task_ids]
        self._lock = threading.Lock()

    # -------------------------------------------------------------------
    # Task Creation
    # -------------------------------------------------------------------

    def create_task(
        self,
        parent_agent: str,
        description: str,
        engine: str = "claude",
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: float = DEFAULT_TASK_TIMEOUT,
        metadata: dict[str, Any] | None = None,
    ) -> DelegationTask:
        """Create a new delegation task.

        Args:
            parent_agent: Agent creating/delegating the task.
            description: Task description/specification.
            engine: Engine for the sub-agent.
            priority: Task priority.
            timeout: Max execution time in seconds.
            metadata: Additional metadata.

        Returns:
            Created DelegationTask.

        Raises:
            ValueError: If inputs invalid.
        """
        if not parent_agent:
            raise ValueError("Parent agent must not be empty")
        if not description:
            raise ValueError("Task description must not be empty")

        task_id = f"dt_{uuid.uuid4().hex[:12]}"

        task = DelegationTask(
            task_id=task_id,
            parent_agent=parent_agent,
            description=description,
            engine=engine,
            priority=priority,
            timeout=timeout,
            metadata=metadata or {},
        )

        with self._lock:
            self._tasks[task_id] = task
            if parent_agent not in self._children:
                self._children[parent_agent] = []
            self._children[parent_agent].append(task_id)

        return task

    # -------------------------------------------------------------------
    # Task Lifecycle
    # -------------------------------------------------------------------

    def submit_task(self, task_id: str) -> bool:
        """Submit a task to the lane queue for execution.

        Returns True if task acquired a slot immediately,
        False if queued (waiting for slot).
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.state != TaskState.PENDING:
            return False

        acquired = self._sub_lane.try_acquire(task_id)
        if acquired:
            task.state = TaskState.ASSIGNED
        else:
            task.state = TaskState.QUEUED

        return acquired

    def start_task(self, task_id: str, agent_id: str) -> bool:
        """Mark a task as started by a sub-agent.

        Args:
            task_id: Task to start.
            agent_id: Sub-agent executing the task.

        Returns:
            True if started successfully.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.state not in (TaskState.ASSIGNED, TaskState.QUEUED):
            return False

        task.state = TaskState.WORKING
        task.assigned_agent = agent_id
        task.started_at = time.time()
        return True

    def complete_task(
        self,
        task_id: str,
        result: str,
        success: bool = True,
    ) -> DelegationResult | None:
        """Mark a task as completed and store result.

        Args:
            task_id: Task to complete.
            result: Result content.
            success: Whether task succeeded.

        Returns:
            DelegationResult, or None if task not found.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.is_terminal:
            return None

        task.state = TaskState.COMPLETED if success else TaskState.FAILED
        task.completed_at = time.time()
        task.result = result
        if not success:
            task.error = result

        # Create result object
        dr = DelegationResult(
            task_id=task_id,
            agent_id=task.assigned_agent,
            success=success,
            content=result,
            elapsed_seconds=task.elapsed_seconds,
        )

        with self._lock:
            self._results[task_id] = dr

        # Release lane slot, promote queued task
        promoted = self._sub_lane.release(task_id)
        if promoted:
            promoted_task = self._tasks.get(promoted)
            if promoted_task:
                promoted_task.state = TaskState.ASSIGNED

        return dr

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or queued task.

        Returns True if cancelled.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.is_terminal:
            return False

        task.state = TaskState.CANCELLED
        task.completed_at = time.time()
        self._sub_lane.remove(task_id)
        return True

    def timeout_task(self, task_id: str) -> bool:
        """Mark a task as timed out.

        Returns True if marked.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.is_terminal:
            return False

        task.state = TaskState.TIMED_OUT
        task.completed_at = time.time()
        task.error = f"Timeout after {task.timeout}s"

        self._sub_lane.release(task_id)
        return True

    # -------------------------------------------------------------------
    # Timeout Checking
    # -------------------------------------------------------------------

    def check_timeouts(self) -> list[str]:
        """Check for timed-out tasks.

        Returns list of task_ids that were timed out.
        """
        now = time.time()
        timed_out: list[str] = []

        for task in self._tasks.values():
            if task.state != TaskState.WORKING:
                continue
            if task.started_at == 0:
                continue
            if now - task.started_at > task.timeout:
                self.timeout_task(task.task_id)
                timed_out.append(task.task_id)

        return timed_out

    # -------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------

    def get_task(self, task_id: str) -> DelegationTask | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def get_result(self, task_id: str) -> DelegationResult | None:
        """Get a task result."""
        return self._results.get(task_id)

    def get_children(self, parent_agent: str) -> list[DelegationTask]:
        """Get all tasks created by a parent agent."""
        task_ids = self._children.get(parent_agent, [])
        return [
            self._tasks[tid] for tid in task_ids
            if tid in self._tasks
        ]

    def get_pending_results(self, parent_agent: str) -> list[DelegationResult]:
        """Get completed results for a parent agent."""
        children = self.get_children(parent_agent)
        results: list[DelegationResult] = []
        for task in children:
            if task.task_id in self._results:
                results.append(self._results[task.task_id])
        return results

    def count_active(self, parent_agent: str | None = None) -> int:
        """Count active (non-terminal) tasks."""
        tasks = self._tasks.values()
        if parent_agent:
            task_ids = set(self._children.get(parent_agent, []))
            tasks = [t for t in tasks if t.task_id in task_ids]
        return sum(1 for t in tasks if not t.is_terminal)

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return delegation status summary."""
        state_counts: dict[str, int] = {}
        for task in self._tasks.values():
            s = task.state.value
            state_counts[s] = state_counts.get(s, 0) + 1

        return {
            "total_tasks": len(self._tasks),
            "total_results": len(self._results),
            "tasks_by_state": state_counts,
            "parents": list(self._children.keys()),
            "main_lane": self._main_lane.status(),
            "sub_lane": self._sub_lane.status(),
        }
