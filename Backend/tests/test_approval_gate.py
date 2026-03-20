"""
Tests for approval_gate.py — Approval Gate Framework

Tests cover:
  - Action policy classification
  - ApprovalRequest creation and serialization
  - Approval flow (request → approve → result)
  - Denial flow (request → deny → result with reason)
  - Expiry flow (request → timeout → auto-expire)
  - Pending/history queries
  - Thread safety
  - Audit log persistence
  - Callbacks (on_request, on_resolve)
  - Queue cleanup
  - Stats
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from approval_gate import (
    ACTION_POLICIES,
    ApprovalGate,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalResult,
    get_policy,
    needs_approval,
    should_log,
)


class TestActionPolicies(unittest.TestCase):
    """Test action classification."""

    def test_file_ops_are_auto(self):
        self.assertEqual(get_policy("file_read"), ApprovalPolicy.AUTO)
        self.assertEqual(get_policy("file_write"), ApprovalPolicy.AUTO)

    def test_web_ops_are_log(self):
        self.assertEqual(get_policy("web_search"), ApprovalPolicy.LOG)
        self.assertEqual(get_policy("web_fetch"), ApprovalPolicy.LOG)

    def test_external_actions_require_approval(self):
        self.assertEqual(get_policy("phone_call"), ApprovalPolicy.REQUIRE_APPROVAL)
        self.assertEqual(get_policy("email_send"), ApprovalPolicy.REQUIRE_APPROVAL)
        self.assertEqual(get_policy("telegram_send"), ApprovalPolicy.REQUIRE_APPROVAL)
        self.assertEqual(get_policy("purchase"), ApprovalPolicy.REQUIRE_APPROVAL)

    def test_identity_actions_require_approval(self):
        self.assertEqual(get_policy("soul_modification"), ApprovalPolicy.REQUIRE_APPROVAL)
        self.assertEqual(get_policy("permission_change"), ApprovalPolicy.REQUIRE_APPROVAL)

    def test_unknown_actions_default_to_require(self):
        self.assertEqual(get_policy("unknown_action"), ApprovalPolicy.REQUIRE_APPROVAL)
        self.assertEqual(get_policy(""), ApprovalPolicy.REQUIRE_APPROVAL)

    def test_needs_approval_convenience(self):
        self.assertTrue(needs_approval("phone_call"))
        self.assertFalse(needs_approval("file_read"))
        self.assertFalse(needs_approval("web_search"))

    def test_should_log_convenience(self):
        self.assertTrue(should_log("phone_call"))
        self.assertTrue(should_log("web_search"))
        self.assertFalse(should_log("file_read"))


class TestApprovalRequest(unittest.TestCase):
    """Test ApprovalRequest dataclass."""

    def test_create_request(self):
        req = ApprovalRequest(
            request_id="abc123",
            action_type="email_send",
            agent_id="agent_a",
            description="Send email to client",
            preview="To: client@example.com\nSubject: Report",
            created_at=time.time(),
        )
        self.assertEqual(req.status, "pending")
        self.assertEqual(req.timeout_seconds, 300.0)

    def test_to_dict_and_from_dict(self):
        req = ApprovalRequest(
            request_id="rt01",
            action_type="phone_call",
            agent_id="caller",
            description="Call restaurant",
            preview="+49-89-12345",
            created_at=1000.0,
            timeout_seconds=60.0,
            metadata={"phone": "+49-89-12345"},
        )
        d = req.to_dict()
        restored = ApprovalRequest.from_dict(d)

        self.assertEqual(restored.request_id, req.request_id)
        self.assertEqual(restored.action_type, req.action_type)
        self.assertEqual(restored.metadata, req.metadata)

    def test_is_expired_false_when_fresh(self):
        req = ApprovalRequest(
            request_id="fresh",
            action_type="test",
            agent_id="a",
            description="",
            preview="",
            created_at=time.time(),
            timeout_seconds=300.0,
        )
        self.assertFalse(req.is_expired())

    def test_is_expired_true_when_old(self):
        req = ApprovalRequest(
            request_id="old",
            action_type="test",
            agent_id="a",
            description="",
            preview="",
            created_at=time.time() - 400,
            timeout_seconds=300.0,
        )
        self.assertTrue(req.is_expired())

    def test_is_expired_false_when_already_resolved(self):
        req = ApprovalRequest(
            request_id="resolved",
            action_type="test",
            agent_id="a",
            description="",
            preview="",
            created_at=time.time() - 400,
            timeout_seconds=300.0,
            status="approved",
        )
        self.assertFalse(req.is_expired())


class TestApprovalGateBasic(unittest.TestCase):
    """Test basic approval gate operations."""

    def setUp(self):
        self.gate = ApprovalGate()

    def test_request_approval_returns_request(self):
        req = self.gate.request_approval(
            action_type="email_send",
            agent_id="agent_a",
            description="Send report",
            preview="To: boss@example.com",
        )
        self.assertIsNotNone(req.request_id)
        self.assertEqual(req.status, "pending")
        self.assertEqual(req.agent_id, "agent_a")

    def test_approve_returns_result(self):
        req = self.gate.request_approval(
            action_type="phone_call",
            agent_id="caller",
            description="Call Luigi's",
            preview="+49-89-12345",
        )
        result = self.gate.approve(req.request_id, approver="owner")
        self.assertIsNotNone(result)
        self.assertTrue(result.approved)
        self.assertEqual(result.approver, "owner")

    def test_approve_changes_status(self):
        req = self.gate.request_approval(
            action_type="test", agent_id="a",
            description="", preview="",
        )
        self.gate.approve(req.request_id)
        updated = self.gate.get_request(req.request_id)
        self.assertEqual(updated.status, "approved")

    def test_deny_returns_result(self):
        req = self.gate.request_approval(
            action_type="purchase", agent_id="buyer",
            description="Buy coffee", preview="$5.00",
        )
        result = self.gate.deny(req.request_id, approver="owner", reason="Too expensive")
        self.assertIsNotNone(result)
        self.assertFalse(result.approved)
        self.assertEqual(result.reason, "Too expensive")

    def test_deny_changes_status(self):
        req = self.gate.request_approval(
            action_type="test", agent_id="a",
            description="", preview="",
        )
        self.gate.deny(req.request_id, reason="No")
        updated = self.gate.get_request(req.request_id)
        self.assertEqual(updated.status, "denied")
        self.assertEqual(updated.deny_reason, "No")

    def test_approve_nonexistent_returns_none(self):
        result = self.gate.approve("nonexistent")
        self.assertIsNone(result)

    def test_deny_nonexistent_returns_none(self):
        result = self.gate.deny("nonexistent")
        self.assertIsNone(result)

    def test_double_approve_returns_none(self):
        req = self.gate.request_approval(
            action_type="test", agent_id="a",
            description="", preview="",
        )
        self.gate.approve(req.request_id)
        result = self.gate.approve(req.request_id)
        self.assertIsNone(result)


class TestApprovalGateQueries(unittest.TestCase):
    """Test pending/history queries."""

    def setUp(self):
        self.gate = ApprovalGate()

    def test_get_pending_empty(self):
        self.assertEqual(self.gate.get_pending(), [])

    def test_get_pending_returns_pending(self):
        self.gate.request_approval("test", "a", "desc1", "preview1")
        self.gate.request_approval("test", "b", "desc2", "preview2")
        pending = self.gate.get_pending()
        self.assertEqual(len(pending), 2)

    def test_get_pending_filters_by_agent(self):
        self.gate.request_approval("test", "agent_a", "d1", "p1")
        self.gate.request_approval("test", "agent_b", "d2", "p2")
        self.gate.request_approval("test", "agent_a", "d3", "p3")

        pending_a = self.gate.get_pending(agent_id="agent_a")
        self.assertEqual(len(pending_a), 2)

        pending_b = self.gate.get_pending(agent_id="agent_b")
        self.assertEqual(len(pending_b), 1)

    def test_approved_not_in_pending(self):
        req = self.gate.request_approval("test", "a", "d", "p")
        self.gate.approve(req.request_id)
        self.assertEqual(len(self.gate.get_pending()), 0)

    def test_get_history(self):
        req1 = self.gate.request_approval("test", "a", "d1", "p1")
        req2 = self.gate.request_approval("test", "a", "d2", "p2")
        self.gate.approve(req1.request_id)
        self.gate.deny(req2.request_id, reason="No")

        history = self.gate.get_history()
        self.assertEqual(len(history), 2)

    def test_get_history_limit(self):
        for i in range(10):
            req = self.gate.request_approval("test", "a", f"d{i}", f"p{i}")
            self.gate.approve(req.request_id)

        history = self.gate.get_history(limit=5)
        self.assertEqual(len(history), 5)


class TestApprovalGateExpiry(unittest.TestCase):
    """Test request expiry."""

    def test_expire_stale(self):
        gate = ApprovalGate()
        # Create an already-expired request
        req = ApprovalRequest(
            request_id="expired1",
            action_type="test",
            agent_id="a",
            description="old request",
            preview="",
            created_at=time.time() - 400,
            timeout_seconds=300.0,
        )
        gate._queue[req.request_id] = req

        expired = gate.expire_stale()
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0], "expired1")
        self.assertEqual(gate._queue["expired1"].status, "expired")

    def test_expire_does_not_touch_fresh(self):
        gate = ApprovalGate()
        gate.request_approval("test", "a", "fresh", "p")
        expired = gate.expire_stale()
        self.assertEqual(len(expired), 0)


class TestApprovalGateCallbacks(unittest.TestCase):
    """Test callback hooks."""

    def test_on_request_callback(self):
        received = []
        gate = ApprovalGate(on_request=lambda r: received.append(r))
        gate.request_approval("test", "a", "d", "p")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].agent_id, "a")

    def test_on_resolve_callback_approve(self):
        resolved = []
        gate = ApprovalGate(on_resolve=lambda req, res: resolved.append((req, res)))
        req = gate.request_approval("test", "a", "d", "p")
        gate.approve(req.request_id)
        self.assertEqual(len(resolved), 1)
        self.assertTrue(resolved[0][1].approved)

    def test_on_resolve_callback_deny(self):
        resolved = []
        gate = ApprovalGate(on_resolve=lambda req, res: resolved.append((req, res)))
        req = gate.request_approval("test", "a", "d", "p")
        gate.deny(req.request_id, reason="No")
        self.assertEqual(len(resolved), 1)
        self.assertFalse(resolved[0][1].approved)

    def test_on_resolve_callback_expire(self):
        resolved = []
        gate = ApprovalGate(on_resolve=lambda req, res: resolved.append((req, res)))
        # Manually insert expired request
        req = ApprovalRequest(
            request_id="exp", action_type="test", agent_id="a",
            description="", preview="",
            created_at=time.time() - 400, timeout_seconds=300.0,
        )
        gate._queue[req.request_id] = req
        gate.expire_stale()
        self.assertEqual(len(resolved), 1)
        self.assertFalse(resolved[0][1].approved)
        self.assertEqual(resolved[0][1].approver, "system")


class TestApprovalGateAudit(unittest.TestCase):
    """Test audit log persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.audit_dir = Path(self.tmpdir) / "audit"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_audit_log_created(self):
        gate = ApprovalGate(audit_dir=self.audit_dir)
        gate.request_approval("test", "a", "d", "p")
        log_path = self.audit_dir / "approval_audit.jsonl"
        self.assertTrue(log_path.exists())

    def test_audit_log_records_all_events(self):
        gate = ApprovalGate(audit_dir=self.audit_dir)
        req = gate.request_approval("test", "a", "d", "p")
        gate.approve(req.request_id)

        log_path = self.audit_dir / "approval_audit.jsonl"
        lines = log_path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)  # request + approved

        events = [json.loads(line)["event"] for line in lines]
        self.assertIn("request", events)
        self.assertIn("approved", events)

    def test_load_pending_from_audit(self):
        gate1 = ApprovalGate(audit_dir=self.audit_dir)
        req1 = gate1.request_approval("test", "a", "pending1", "p1")
        req2 = gate1.request_approval("test", "a", "pending2", "p2")
        gate1.approve(req1.request_id)
        # req2 is still pending

        # Simulate restart with new gate
        gate2 = ApprovalGate(audit_dir=self.audit_dir)
        restored = gate2.load_pending_from_audit()
        self.assertEqual(restored, 1)  # Only req2 should be restored

        pending = gate2.get_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].description, "pending2")


class TestApprovalGateCleanup(unittest.TestCase):
    """Test queue cleanup and stats."""

    def test_cleanup_removes_old_resolved(self):
        gate = ApprovalGate()
        req = gate.request_approval("test", "a", "d", "p")
        gate.approve(req.request_id)

        # Hack resolved_at to be old
        gate._queue[req.request_id].resolved_at = time.time() - 100000

        removed = gate.cleanup(max_age_seconds=3600)
        self.assertEqual(removed, 1)
        self.assertEqual(len(gate._queue), 0)

    def test_cleanup_keeps_recent(self):
        gate = ApprovalGate()
        req = gate.request_approval("test", "a", "d", "p")
        gate.approve(req.request_id)

        removed = gate.cleanup(max_age_seconds=3600)
        self.assertEqual(removed, 0)
        self.assertEqual(len(gate._queue), 1)

    def test_stats(self):
        gate = ApprovalGate()
        gate.request_approval("test", "a", "d1", "p1")
        req2 = gate.request_approval("test", "a", "d2", "p2")
        req3 = gate.request_approval("test", "a", "d3", "p3")
        gate.approve(req2.request_id)
        gate.deny(req3.request_id)

        stats = gate.stats()
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["approved"], 1)
        self.assertEqual(stats["denied"], 1)


class TestApprovalGateThreadSafety(unittest.TestCase):
    """Test thread safety of approval gate operations."""

    def test_concurrent_requests(self):
        gate = ApprovalGate()
        errors = []

        def make_requests():
            try:
                for i in range(50):
                    gate.request_approval("test", f"agent_{i}", f"d{i}", f"p{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=make_requests) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(gate._queue), 200)

    def test_concurrent_approve_deny(self):
        gate = ApprovalGate()
        requests = []
        for i in range(100):
            req = gate.request_approval("test", "a", f"d{i}", f"p{i}")
            requests.append(req)

        errors = []

        def approve_half():
            try:
                for i in range(0, 100, 2):
                    gate.approve(requests[i].request_id)
            except Exception as e:
                errors.append(e)

        def deny_half():
            try:
                for i in range(1, 100, 2):
                    gate.deny(requests[i].request_id)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=approve_half)
        t2 = threading.Thread(target=deny_half)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(errors), 0)
        stats = gate.stats()
        self.assertEqual(stats["approved"], 50)
        self.assertEqual(stats["denied"], 50)
        self.assertEqual(stats["pending"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
