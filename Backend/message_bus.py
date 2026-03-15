"""
message_bus.py — Thread-safe Message Store with Typed Events

Extracted, typed, thread-safe messaging core for the Bridge platform.
Separates messaging infrastructure from server business logic.

Architecture Reference: R4_Architekturentwurf.md section 3.2.2
Phase: D — Scale

Features:
  - Typed Message dataclass (chat, control, approval, system, etc.)
  - Thread-safe append with cursor-based delivery
  - Long-poll receive with threading.Condition
  - JSONL persistence (append-only log)
  - Paginated history
  - In-memory cap with FIFO eviction
  - Broadcast callback for WebSocket integration
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MESSAGE_TYPES = frozenset({
    "chat",                # Agent-to-agent or user-to-agent conversation
    "control",             # TeamLead control commands (start, stop, etc.)
    "approval_request",    # Agent requests approval for action
    "approval_response",   # User/approver grants or denies approval
    "system",              # System notifications (agent joined, etc.)
    "memory_update",       # Memory write notification
    "task_completion",     # Task finished
})

DEFAULT_MEMORY_CAP = 50_000   # Max messages in memory
DEFAULT_WAIT = 15.0           # Default long-poll wait seconds
DEFAULT_LIMIT = 50            # Default receive/history limit
MAX_CONTENT_LENGTH = 200_000  # Max message content length (chars)
MAX_SENDER_LENGTH = 128       # Max sender/recipient ID length


# ---------------------------------------------------------------------------
# Message Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """Typed message with metadata."""

    id: int
    sender: str
    recipient: str                    # agent_id | "all"
    content: str
    timestamp: str                    # ISO 8601
    message_type: str = "chat"        # One of MESSAGE_TYPES
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """Create Message from dictionary."""
        return cls(
            id=data.get("id", 0),
            sender=data.get("sender", data.get("from", "")),
            recipient=data.get("recipient", data.get("to", "")),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", ""),
            message_type=data.get("message_type", "chat"),
            meta=data.get("meta", {}),
        )


# ---------------------------------------------------------------------------
# Message Bus
# ---------------------------------------------------------------------------

class MessageBus:
    """Thread-safe message store with typed events and delivery tracking.

    Central messaging infrastructure for the Bridge platform.
    Supports append, long-poll receive, paginated history, and
    JSONL persistence.
    """

    def __init__(
        self,
        persist_path: Path | None = None,
        memory_cap: int = DEFAULT_MEMORY_CAP,
        broadcast_fn: Callable[[Message], None] | None = None,
    ):
        """Initialize the message bus.

        Args:
            persist_path: Path to JSONL file for persistence. None = no persistence.
            memory_cap: Maximum messages kept in memory (FIFO eviction).
            broadcast_fn: Optional callback called on every new message
                          (for WebSocket broadcast integration).
        """
        self._messages: list[Message] = []
        self._cursors: dict[str, int] = {}  # agent_id -> last seen message ID
        self._next_id: int = 1
        self._memory_cap = memory_cap
        self._persist_path = persist_path
        self._broadcast_fn = broadcast_fn

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

        # Hooks: list of callbacks for specific message types
        self._hooks: dict[str, list[Callable[[Message], None]]] = {}

        # Load persisted messages if path exists
        if persist_path and persist_path.exists():
            self._load_from_disk(persist_path)

    # -------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------

    def append(
        self,
        sender: str,
        recipient: str,
        content: str,
        message_type: str = "chat",
        meta: dict[str, Any] | None = None,
    ) -> Message:
        """Append a new message.

        Creates a Message, stores it, persists to disk, broadcasts,
        and triggers registered hooks.

        Args:
            sender: Agent ID of sender.
            recipient: Agent ID of recipient, or "all" for broadcast.
            content: Message content.
            message_type: One of MESSAGE_TYPES.
            meta: Optional metadata dict.

        Returns:
            The created Message.

        Raises:
            ValueError: If sender/recipient/content invalid.
        """
        # Validation
        if not sender or len(sender) > MAX_SENDER_LENGTH:
            raise ValueError(f"Invalid sender: must be 1-{MAX_SENDER_LENGTH} chars")
        if not recipient or len(recipient) > MAX_SENDER_LENGTH:
            raise ValueError(f"Invalid recipient: must be 1-{MAX_SENDER_LENGTH} chars")
        if not content:
            raise ValueError("Content must not be empty")
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Content exceeds max length ({MAX_CONTENT_LENGTH} chars)"
            )

        with self._cond:
            msg = Message(
                id=self._next_id,
                sender=sender,
                recipient=recipient,
                content=content,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                message_type=message_type,
                meta=meta or {},
            )
            self._next_id += 1
            self._messages.append(msg)

            # FIFO eviction if over cap
            if len(self._messages) > self._memory_cap:
                overflow = len(self._messages) - self._memory_cap
                self._messages = self._messages[overflow:]

            # Wake up any long-polling receivers
            self._cond.notify_all()

        # Persist (outside lock for I/O)
        if self._persist_path:
            self._persist_message(msg)

        # Broadcast callback (outside lock)
        if self._broadcast_fn:
            try:
                self._broadcast_fn(msg)
            except Exception:
                pass  # Broadcast errors must not crash the bus

        # Trigger hooks (outside lock)
        self._trigger_hooks(msg)

        return msg

    def receive(
        self,
        agent_id: str,
        wait: float = DEFAULT_WAIT,
        limit: int = DEFAULT_LIMIT,
    ) -> list[Message]:
        """Receive messages for an agent with long-poll support.

        Returns messages addressed to agent_id (or "all") that the
        agent hasn't seen yet, based on cursor tracking.

        Args:
            agent_id: Agent requesting messages.
            wait: Max seconds to wait for new messages (long-poll).
            limit: Max messages to return.

        Returns:
            List of new messages for this agent.
        """
        deadline = time.time() + wait

        with self._cond:
            while True:
                new_msgs = self._get_new_messages(agent_id)
                if new_msgs:
                    # Update cursor to latest message ID
                    result = new_msgs[:limit]
                    if result:
                        self._cursors[agent_id] = result[-1].id
                    return result

                # No new messages — wait
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []

                self._cond.wait(timeout=remaining)

    def receive_nowait(
        self,
        agent_id: str,
        limit: int = DEFAULT_LIMIT,
    ) -> list[Message]:
        """Non-blocking receive (no long-poll).

        Returns immediately with available messages.
        """
        with self._lock:
            new_msgs = self._get_new_messages(agent_id)
            result = new_msgs[:limit]
            if result:
                self._cursors[agent_id] = result[-1].id
            return result

    def history(
        self,
        limit: int = DEFAULT_LIMIT,
        after_id: int = 0,
    ) -> list[Message]:
        """Get message history.

        Args:
            limit: Number of messages to return.
            after_id: Return messages with ID > after_id (0 = from end).

        Returns:
            List of messages, most recent last.
        """
        with self._lock:
            if after_id > 0:
                msgs = [m for m in self._messages if m.id > after_id]
                return msgs[:limit]
            else:
                # Return last N messages
                return self._messages[-limit:]

    # -------------------------------------------------------------------
    # Cursor Management
    # -------------------------------------------------------------------

    def reset_cursor(self, agent_id: str) -> None:
        """Reset an agent's cursor (will receive all messages again)."""
        with self._lock:
            self._cursors.pop(agent_id, None)

    def get_cursor(self, agent_id: str) -> int:
        """Get an agent's current cursor position."""
        return self._cursors.get(agent_id, 0)

    def set_cursor(self, agent_id: str, message_id: int) -> None:
        """Set an agent's cursor to a specific message ID."""
        with self._lock:
            self._cursors[agent_id] = message_id

    # -------------------------------------------------------------------
    # Hooks
    # -------------------------------------------------------------------

    def register_hook(
        self,
        message_type: str,
        callback: Callable[[Message], None],
    ) -> None:
        """Register a callback for a specific message type.

        Hooks are called outside the lock after each append().
        """
        if message_type not in self._hooks:
            self._hooks[message_type] = []
        self._hooks[message_type].append(callback)

    def unregister_hooks(self, message_type: str) -> None:
        """Remove all hooks for a message type."""
        self._hooks.pop(message_type, None)

    # -------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------

    def count(self) -> int:
        """Total messages in memory."""
        return len(self._messages)

    def count_for(self, agent_id: str) -> int:
        """Count unread messages for an agent."""
        with self._lock:
            return len(self._get_new_messages(agent_id))

    def get_message(self, message_id: int) -> Message | None:
        """Get a single message by ID."""
        with self._lock:
            for msg in reversed(self._messages):
                if msg.id == message_id:
                    return msg
                if msg.id < message_id:
                    break
            return None

    # -------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------

    def clear(self) -> int:
        """Clear all in-memory messages. Returns count cleared.

        Does NOT clear the persistence file.
        """
        with self._lock:
            count = len(self._messages)
            self._messages.clear()
            self._cursors.clear()
            return count

    def prune(self, keep: int) -> int:
        """Keep only the last N messages. Returns count pruned."""
        with self._lock:
            if len(self._messages) <= keep:
                return 0
            pruned = len(self._messages) - keep
            self._messages = self._messages[-keep:]
            return pruned

    # -------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return bus status summary."""
        with self._lock:
            type_counts: dict[str, int] = {}
            for msg in self._messages:
                type_counts[msg.message_type] = (
                    type_counts.get(msg.message_type, 0) + 1
                )

            return {
                "total_messages": len(self._messages),
                "memory_cap": self._memory_cap,
                "next_id": self._next_id,
                "active_cursors": len(self._cursors),
                "cursors": dict(self._cursors),
                "message_types": type_counts,
                "persist_path": str(self._persist_path) if self._persist_path else None,
                "hooks_registered": {
                    k: len(v) for k, v in self._hooks.items()
                },
            }

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    def _get_new_messages(self, agent_id: str) -> list[Message]:
        """Get messages for agent_id that haven't been seen (by cursor).

        Must be called while holding self._lock.
        """
        cursor = self._cursors.get(agent_id, 0)
        return [
            m for m in self._messages
            if m.id > cursor
            and (m.recipient == agent_id or m.recipient == "all")
        ]

    def _persist_message(self, msg: Message) -> None:
        """Append a message to the JSONL persistence file."""
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            pass  # Persistence errors must not crash the bus

    def _load_from_disk(self, path: Path) -> None:
        """Load messages from JSONL persistence file."""
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        msg = Message.from_dict(data)
                        self._messages.append(msg)
                        if msg.id >= self._next_id:
                            self._next_id = msg.id + 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError:
            pass

        # Apply memory cap after loading
        if len(self._messages) > self._memory_cap:
            self._messages = self._messages[-self._memory_cap:]

    def _trigger_hooks(self, msg: Message) -> None:
        """Trigger registered hooks for a message's type."""
        hooks = self._hooks.get(msg.message_type, [])
        for hook in hooks:
            try:
                hook(msg)
            except Exception:
                pass  # Hook errors must not crash the bus
