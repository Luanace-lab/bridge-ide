"""
approval_gate.py — Approval Queue for Irreversible Agent Actions

Provides a gate between agent intent and action execution for
irreversible real-world operations. Agents request approval,
humans approve/deny, and only then does the action proceed.

Architecture Reference: R4_Architekturentwurf.md section 3.2.7
Phase: A3 — Foundation

Flow:
  1. Agent requests approval → approval_gate queues the request
  2. System notifies human (via WebSocket/UI/Bridge message)
  3. Human approves or denies
  4. If approved: action callback is invoked
  5. If denied: agent is notified with reason
  6. If expired: auto-denied after timeout

Action Classification:
  AUTO             — No approval needed (file ops, messages, code)
  LOG              — No approval needed but logged (web searches)
  REQUIRE_APPROVAL — Human must approve (calls, emails, purchases, soul changes)
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Action Policy — Classifies what needs approval
# ---------------------------------------------------------------------------

class ApprovalPolicy(Enum):
    """Policy for action types."""
    AUTO = "auto"                      # No approval, execute immediately
    LOG = "log"                        # No approval, but log the action
    REQUIRE_APPROVAL = "require"       # Human must approve before execution


# Default policies per action type
ACTION_POLICIES: dict[str, ApprovalPolicy] = {
    # Internal, reversible → Auto
    "file_read": ApprovalPolicy.AUTO,
    "file_write": ApprovalPolicy.AUTO,
    "code_execute": ApprovalPolicy.AUTO,
    "message_send": ApprovalPolicy.AUTO,
    "memory_write": ApprovalPolicy.AUTO,
    "memory_read": ApprovalPolicy.AUTO,

    # External, reversible → Log only
    "web_search": ApprovalPolicy.LOG,
    "web_fetch": ApprovalPolicy.LOG,

    # External, irreversible → Approval Required
    "phone_call": ApprovalPolicy.REQUIRE_APPROVAL,
    "email_send": ApprovalPolicy.REQUIRE_APPROVAL,
    "telegram_send": ApprovalPolicy.REQUIRE_APPROVAL,
    "sms_send": ApprovalPolicy.REQUIRE_APPROVAL,
    "purchase": ApprovalPolicy.REQUIRE_APPROVAL,
    "smart_home_action": ApprovalPolicy.REQUIRE_APPROVAL,
    "social_media_post": ApprovalPolicy.REQUIRE_APPROVAL,
    "git_push": ApprovalPolicy.REQUIRE_APPROVAL,
    "deploy": ApprovalPolicy.REQUIRE_APPROVAL,

    # Identity-critical → Approval Required
    "soul_modification": ApprovalPolicy.REQUIRE_APPROVAL,
    "permission_change": ApprovalPolicy.REQUIRE_APPROVAL,
    "credential_access": ApprovalPolicy.REQUIRE_APPROVAL,
}


def get_policy(action_type: str) -> ApprovalPolicy:
    """Get the approval policy for an action type.

    Unknown actions default to REQUIRE_APPROVAL (fail-safe).
    """
    return ACTION_POLICIES.get(action_type, ApprovalPolicy.REQUIRE_APPROVAL)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ApprovalRequest:
    """A request for human approval of an agent action."""

    request_id: str
    action_type: str
    agent_id: str
    description: str
    preview: str                     # What would happen if approved
    created_at: float                # time.time()
    timeout_seconds: float = 300.0   # 5 minutes default
    status: str = "pending"          # pending | approved | denied | expired
    approver: str = ""
    resolved_at: float = 0.0
    deny_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action_type": self.action_type,
            "agent_id": self.agent_id,
            "description": self.description,
            "preview": self.preview,
            "created_at": self.created_at,
            "created_at_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.created_at)
            ),
            "timeout_seconds": self.timeout_seconds,
            "status": self.status,
            "approver": self.approver,
            "resolved_at": self.resolved_at,
            "deny_reason": self.deny_reason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRequest:
        return cls(
            request_id=data.get("request_id", ""),
            action_type=data.get("action_type", "unknown"),
            agent_id=data.get("agent_id", ""),
            description=data.get("description", ""),
            preview=data.get("preview", ""),
            created_at=data.get("created_at", 0.0),
            timeout_seconds=data.get("timeout_seconds", 300.0),
            status=data.get("status", "pending"),
            approver=data.get("approver", ""),
            resolved_at=data.get("resolved_at", 0.0),
            deny_reason=data.get("deny_reason", ""),
            metadata=data.get("metadata", {}),
        )

    def is_expired(self) -> bool:
        """Check if this request has timed out."""
        if self.status != "pending":
            return False
        return time.time() - self.created_at > self.timeout_seconds


@dataclass
class ApprovalResult:
    """Result of an approval decision."""

    request_id: str
    approved: bool
    approver: str
    reason: str
    resolved_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approved": self.approved,
            "approver": self.approver,
            "reason": self.reason,
            "resolved_at": self.resolved_at,
            "resolved_at_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.resolved_at)
            ),
        }


# ---------------------------------------------------------------------------
# Approval Gate — Thread-safe approval queue
# ---------------------------------------------------------------------------

class ApprovalGate:
    """Approval queue for irreversible agent actions.

    Thread-safe. Persists decisions to audit log.
    Provides hooks for notification (WebSocket/UI).
    """

    def __init__(
        self,
        audit_dir: Path | None = None,
        on_request: Callable[[ApprovalRequest], None] | None = None,
        on_resolve: Callable[[ApprovalRequest, ApprovalResult], None] | None = None,
    ):
        """Initialize the approval gate.

        Args:
            audit_dir: Directory for audit log persistence. None = no persistence.
            on_request: Callback when a new approval request is created.
                        Use this to notify the UI (e.g., WebSocket broadcast).
            on_resolve: Callback when a request is approved/denied.
                        Use this to notify the requesting agent.
        """
        self._queue: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._audit_dir = audit_dir
        self._on_request = on_request
        self._on_resolve = on_resolve

        if audit_dir:
            audit_dir.mkdir(parents=True, exist_ok=True)

    def request_approval(
        self,
        action_type: str,
        agent_id: str,
        description: str,
        preview: str,
        timeout_seconds: float = 300.0,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Submit an action for approval.

        Returns the ApprovalRequest (with request_id).
        The request is added to the queue and the on_request callback is called.
        """
        request = ApprovalRequest(
            request_id=str(uuid.uuid4())[:8],
            action_type=action_type,
            agent_id=agent_id,
            description=description,
            preview=preview,
            created_at=time.time(),
            timeout_seconds=timeout_seconds,
            metadata=metadata or {},
        )

        with self._lock:
            self._queue[request.request_id] = request

        self._audit_log("request", request.to_dict())

        if self._on_request:
            self._on_request(request)

        return request

    def approve(
        self,
        request_id: str,
        approver: str = "user",
    ) -> ApprovalResult | None:
        """Approve a pending request.

        Returns ApprovalResult or None if request not found / not pending.
        """
        with self._lock:
            request = self._queue.get(request_id)
            if not request or request.status != "pending":
                return None

            now = time.time()
            request.status = "approved"
            request.approver = approver
            request.resolved_at = now

        result = ApprovalResult(
            request_id=request_id,
            approved=True,
            approver=approver,
            reason="",
            resolved_at=now,
        )

        self._audit_log("approved", {
            **request.to_dict(),
            "result": result.to_dict(),
        })

        if self._on_resolve:
            self._on_resolve(request, result)

        return result

    def deny(
        self,
        request_id: str,
        approver: str = "user",
        reason: str = "",
    ) -> ApprovalResult | None:
        """Deny a pending request.

        Returns ApprovalResult or None if request not found / not pending.
        """
        with self._lock:
            request = self._queue.get(request_id)
            if not request or request.status != "pending":
                return None

            now = time.time()
            request.status = "denied"
            request.approver = approver
            request.resolved_at = now
            request.deny_reason = reason

        result = ApprovalResult(
            request_id=request_id,
            approved=False,
            approver=approver,
            reason=reason,
            resolved_at=now,
        )

        self._audit_log("denied", {
            **request.to_dict(),
            "result": result.to_dict(),
        })

        if self._on_resolve:
            self._on_resolve(request, result)

        return result

    def get_pending(self, agent_id: str | None = None) -> list[ApprovalRequest]:
        """List all pending approval requests.

        Optionally filter by agent_id.
        """
        with self._lock:
            pending = [
                req for req in self._queue.values()
                if req.status == "pending"
                and (agent_id is None or req.agent_id == agent_id)
            ]
        return sorted(pending, key=lambda r: r.created_at)

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Get a specific request by ID."""
        with self._lock:
            return self._queue.get(request_id)

    def get_history(
        self,
        limit: int = 50,
        agent_id: str | None = None,
    ) -> list[ApprovalRequest]:
        """Get resolved requests (approved + denied + expired).

        Returns most recent first, limited to `limit`.
        """
        with self._lock:
            resolved = [
                req for req in self._queue.values()
                if req.status in ("approved", "denied", "expired")
                and (agent_id is None or req.agent_id == agent_id)
            ]
        resolved.sort(key=lambda r: r.resolved_at, reverse=True)
        return resolved[:limit]

    def expire_stale(self) -> list[str]:
        """Expire requests that have timed out.

        Returns list of expired request IDs.
        Call this periodically (e.g., every 30 seconds).
        """
        expired_ids: list[str] = []
        now = time.time()

        with self._lock:
            for req_id, req in self._queue.items():
                if req.status == "pending" and req.is_expired():
                    req.status = "expired"
                    req.resolved_at = now
                    expired_ids.append(req_id)

        for req_id in expired_ids:
            req = self._queue[req_id]
            self._audit_log("expired", req.to_dict())

            if self._on_resolve:
                result = ApprovalResult(
                    request_id=req_id,
                    approved=False,
                    approver="system",
                    reason="Request expired (timeout)",
                    resolved_at=now,
                )
                self._on_resolve(req, result)

        return expired_ids

    def cleanup(self, max_age_seconds: float = 86400.0) -> int:
        """Remove old resolved requests from memory.

        Keeps audit log on disk. Only clears in-memory queue.
        Returns number of removed entries.
        """
        cutoff = time.time() - max_age_seconds
        removed = 0

        with self._lock:
            to_remove = [
                req_id for req_id, req in self._queue.items()
                if req.status in ("approved", "denied", "expired")
                and req.resolved_at < cutoff
            ]
            for req_id in to_remove:
                del self._queue[req_id]
                removed += 1

        return removed

    def stats(self) -> dict[str, int]:
        """Get queue statistics."""
        with self._lock:
            counts: dict[str, int] = {"pending": 0, "approved": 0, "denied": 0, "expired": 0}
            for req in self._queue.values():
                counts[req.status] = counts.get(req.status, 0) + 1
        return counts

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _audit_log(self, event: str, data: dict[str, Any]) -> None:
        """Append to audit log (JSONL)."""
        if not self._audit_dir:
            return
        entry = {
            "event": event,
            "timestamp": time.time(),
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **data,
        }
        log_path = self._audit_dir / "approval_audit.jsonl"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # Audit log failure should not block approval flow

    def load_pending_from_audit(self) -> int:
        """Reload pending requests from audit log after restart.

        Returns number of pending requests restored.
        """
        if not self._audit_dir:
            return 0

        log_path = self._audit_dir / "approval_audit.jsonl"
        if not log_path.exists():
            return 0

        # Track latest state per request_id
        latest: dict[str, dict[str, Any]] = {}
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                req_id = entry.get("request_id", "")
                if req_id:
                    latest[req_id] = entry
            except json.JSONDecodeError:
                continue

        restored = 0
        for data in latest.values():
            if data.get("status") == "pending":
                req = ApprovalRequest.from_dict(data)
                if not req.is_expired():
                    with self._lock:
                        self._queue[req.request_id] = req
                    restored += 1

        return restored


# ---------------------------------------------------------------------------
# Convenience functions for quick policy checks
# ---------------------------------------------------------------------------

def needs_approval(action_type: str) -> bool:
    """Check if an action type requires human approval."""
    return get_policy(action_type) == ApprovalPolicy.REQUIRE_APPROVAL


def should_log(action_type: str) -> bool:
    """Check if an action type should be logged (but not gated)."""
    return get_policy(action_type) in (ApprovalPolicy.LOG, ApprovalPolicy.REQUIRE_APPROVAL)
