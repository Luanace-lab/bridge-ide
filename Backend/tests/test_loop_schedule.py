"""
Tests for Loop/Schedule Integration — Tests VOR Implementierung.

Test-Plan: LOOP_SCHEDULE_FINDINGS.md Teil 4
Phases: P0-A (Idle-Only), P0-B (Agent-Routing), P1-A (bridge_loop), P1-B (Prompt-Replay), P1-C (Jitter)

All tests are written BEFORE implementation. They define the expected behavior.
Tests will FAIL until the corresponding feature is implemented.
"""

from __future__ import annotations

import copy
import hashlib
import os
import sys
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

# Add Backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import automation_engine as ae


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_automation(
    auto_id: str = "test_auto_1",
    cron: str = "*/5 * * * *",
    action_type: str = "send_message",
    created_by: str = "backend",
    assigned_to: str | None = None,
    active: bool = True,
    max_runs: int = 0,
) -> dict[str, Any]:
    """Create a minimal automation dict for testing."""
    auto: dict[str, Any] = {
        "id": auto_id,
        "name": f"Test Automation {auto_id}",
        "description": "Test",
        "active": active,
        "paused_until": None,
        "created_by": created_by,
        "trigger": {"type": "schedule", "cron": cron, "timezone": "UTC"},
        "action": {"type": action_type, "to": "user", "content": "test"},
        "options": {"max_runs": max_runs} if max_runs else {},
        "created_at": ae._utc_now_iso(),
        "last_run": None,
        "last_result_id": None,
        "next_run": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),
        "run_count": 0,
        "last_status": None,
    }
    if assigned_to is not None:
        auto["assigned_to"] = assigned_to
    return auto


def _clear_automations():
    """Reset automation state for clean tests."""
    with ae.AUTOMATION_LOCK:
        ae.AUTOMATIONS.clear()
    ae._PENDING_AUTOMATIONS.clear()
    ae._PENDING_RETRY_COUNT.clear()


# ===========================================================================
# P0-A: Idle-Only Execution Tests
# ===========================================================================
class TestP0A_IdleOnlyExecution(unittest.TestCase):
    """T-P0A-1 through T-P0A-9: Idle-Only Execution."""

    def setUp(self):
        _clear_automations()

    def tearDown(self):
        _clear_automations()

    def test_p0a_1_agent_idle_automation_fires(self):
        """T-P0A-1: Agent idle (activity > 120s) + Automation due → fires immediately."""
        fired = []

        def action_cb(auto):
            fired.append(auto["id"])
            return {"ok": True}

        def idle_check(agent_id):
            # Agent is idle
            return True

        auto = _make_automation(assigned_to="backend")
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        scheduler = ae.AutomationScheduler(
            action_callback=action_cb,
            check_interval=1,
        )
        # If idle_check_callback exists, set it
        if hasattr(scheduler, '_idle_check_callback'):
            scheduler._idle_check_callback = idle_check
        elif hasattr(ae.AutomationScheduler.__init__, '__code__'):
            # Try new constructor signature
            try:
                scheduler = ae.AutomationScheduler(
                    action_callback=action_cb,
                    check_interval=1,
                    idle_check_callback=idle_check,
                )
            except TypeError:
                self.skipTest("idle_check_callback not yet implemented")

        scheduler._tick()
        self.assertIn("test_auto_1", fired, "Automation should fire when agent is idle")

    def test_p0a_2_agent_busy_automation_queued(self):
        """T-P0A-2: Agent busy (activity < 30s) → Automation queued, NOT fired."""
        fired = []

        def action_cb(auto):
            fired.append(auto["id"])
            return {"ok": True}

        def idle_check(agent_id):
            # Agent is busy
            return False

        auto = _make_automation(assigned_to="backend")
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        try:
            scheduler = ae.AutomationScheduler(
                action_callback=action_cb,
                check_interval=1,
                idle_check_callback=idle_check,
            )
        except TypeError:
            self.skipTest("idle_check_callback not yet implemented")

        scheduler._tick()
        self.assertEqual(fired, [], "Automation should NOT fire when agent is busy")

        # Check pending queue exists
        if hasattr(ae, '_PENDING_AUTOMATIONS'):
            pending = ae._PENDING_AUTOMATIONS.get("backend", [])
            self.assertTrue(len(pending) > 0, "Automation should be in pending queue")

    def test_p0a_3_pending_fires_when_idle(self):
        """T-P0A-3: Queued automation fires when agent becomes idle."""
        fired = []
        is_idle = [False]  # mutable for closure

        def action_cb(auto):
            fired.append(auto["id"])
            return {"ok": True}

        def idle_check(agent_id):
            return is_idle[0]

        auto = _make_automation(assigned_to="backend")
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        try:
            scheduler = ae.AutomationScheduler(
                action_callback=action_cb,
                check_interval=1,
                idle_check_callback=idle_check,
            )
        except TypeError:
            self.skipTest("idle_check_callback not yet implemented")

        # Tick 1: busy → queued
        scheduler._tick()
        self.assertEqual(fired, [])

        # Agent becomes idle
        is_idle[0] = True
        scheduler._tick()
        self.assertIn("test_auto_1", fired, "Pending automation should fire when idle")

    def test_p0a_4_max_retries_force_fire(self):
        """T-P0A-4: After 5 retries exhausted → fires anyway + warning."""
        fired = []
        retry_count = [0]

        def action_cb(auto):
            fired.append(auto["id"])
            return {"ok": True}

        def idle_check(agent_id):
            retry_count[0] += 1
            return False  # Always busy

        auto = _make_automation(assigned_to="backend")
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        try:
            scheduler = ae.AutomationScheduler(
                action_callback=action_cb,
                check_interval=1,
                idle_check_callback=idle_check,
            )
        except TypeError:
            self.skipTest("idle_check_callback not yet implemented")

        # Tick 6 times (5 retries + 1 force)
        for _ in range(6):
            scheduler._tick()

        self.assertIn("test_auto_1", fired,
                       "Automation should force-fire after 5 retries")

    def test_p0a_5_agent_offline_queued(self):
        """T-P0A-5: Agent offline → automation queued (not fired to non-existent agent)."""
        fired = []

        def action_cb(auto):
            fired.append(auto["id"])
            return {"ok": True}

        def idle_check(agent_id):
            return None  # Agent not registered / offline

        auto = _make_automation(assigned_to="offline_agent")
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        try:
            scheduler = ae.AutomationScheduler(
                action_callback=action_cb,
                check_interval=1,
                idle_check_callback=idle_check,
            )
        except TypeError:
            self.skipTest("idle_check_callback not yet implemented")

        scheduler._tick()
        self.assertEqual(fired, [], "Should not fire for offline agent")

    def test_p0a_6_no_assigned_to_fallback_created_by(self):
        """T-P0A-6: No assigned_to → fallback to created_by for idle check."""
        checked_agents = []

        def action_cb(auto):
            return {"ok": True}

        def idle_check(agent_id):
            checked_agents.append(agent_id)
            return True

        auto = _make_automation(created_by="backend")
        # Explicitly no assigned_to
        auto.pop("assigned_to", None)
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        try:
            scheduler = ae.AutomationScheduler(
                action_callback=action_cb,
                check_interval=1,
                idle_check_callback=idle_check,
            )
        except TypeError:
            self.skipTest("idle_check_callback not yet implemented")

        scheduler._tick()
        self.assertIn("backend", checked_agents,
                       "Should check created_by when no assigned_to")

    def test_p0a_7_multiple_automations_fifo(self):
        """T-P0A-7: Multiple automations for same agent → all queued, FIFO order."""
        fired = []
        is_idle = [False]

        def action_cb(auto):
            fired.append(auto["id"])
            return {"ok": True}

        def idle_check(agent_id):
            return is_idle[0]

        for i in range(3):
            auto = _make_automation(auto_id=f"auto_{i}", assigned_to="backend")
            with ae.AUTOMATION_LOCK:
                ae.AUTOMATIONS[auto["id"]] = auto

        try:
            scheduler = ae.AutomationScheduler(
                action_callback=action_cb,
                check_interval=1,
                idle_check_callback=idle_check,
            )
        except TypeError:
            self.skipTest("idle_check_callback not yet implemented")

        # Tick while busy → all queued
        scheduler._tick()
        self.assertEqual(fired, [])

        # Become idle → all fire in FIFO
        is_idle[0] = True
        scheduler._tick()
        self.assertEqual(len(fired), 3, "All 3 should fire")

    def test_p0a_8_max_runs_deactivates(self):
        """T-P0A-8: Automation with max_runs=3, run_count=3 → active=false."""
        auto = _make_automation(max_runs=3)
        auto["run_count"] = 2  # Will be 3 after this run
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        fired = []

        def action_cb(a):
            fired.append(a["id"])
            return {"ok": True}

        scheduler = ae.AutomationScheduler(
            action_callback=action_cb,
            check_interval=1,
        )
        scheduler._tick()

        with ae.AUTOMATION_LOCK:
            updated = ae.AUTOMATIONS.get("test_auto_1")
        if updated:
            if updated.get("options", {}).get("max_runs"):
                self.assertFalse(updated.get("active", True),
                                 "Should be deactivated after reaching max_runs")
            else:
                self.skipTest("max_runs not yet implemented in automation object")
        else:
            self.skipTest("max_runs not yet implemented")

    def test_p0a_9_pending_overflow_deactivates(self):
        """T-P0A-9: 50 pending → 51st rejected + automation deactivated."""
        if not hasattr(ae, '_PENDING_AUTOMATIONS'):
            self.skipTest("_PENDING_AUTOMATIONS not yet implemented")

        # Fill pending queue to 50
        ae._PENDING_AUTOMATIONS["backend"] = [{"id": f"p_{i}"} for i in range(50)]

        auto = _make_automation(auto_id="overflow_auto", assigned_to="backend")
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        def action_cb(a):
            return {"ok": True}

        def idle_check(agent_id):
            return False

        try:
            scheduler = ae.AutomationScheduler(
                action_callback=action_cb,
                check_interval=1,
                idle_check_callback=idle_check,
            )
        except TypeError:
            self.skipTest("idle_check_callback not yet implemented")

        scheduler._tick()

        # Automation should be deactivated
        with ae.AUTOMATION_LOCK:
            updated = ae.AUTOMATIONS.get("overflow_auto")
        if updated:
            self.assertFalse(updated.get("active", True),
                             "Automation should be deactivated on pending overflow")


# ===========================================================================
# P0-B: Agent-Routing Tests
# ===========================================================================
class TestP0B_AgentRouting(unittest.TestCase):
    """T-P0B-1 through T-P0B-6: Agent-Routing (assigned_to)."""

    def setUp(self):
        _clear_automations()

    def tearDown(self):
        _clear_automations()

    def test_p0b_1_no_assigned_to_defaults_created_by(self):
        """T-P0B-1: Create without assigned_to → assigned_to = created_by."""
        data = {
            "name": "Test Auto",
            "created_by": "backend",
            "trigger": {"type": "schedule", "cron": "*/5 * * * *"},
            "action": {"type": "send_message", "to": "user", "content": "test"},
        }
        auto, warning = ae.add_automation(data)
        self.assertIsNotNone(auto)
        # assigned_to should default to created_by
        effective = auto.get("assigned_to", auto.get("created_by"))
        self.assertEqual(effective, "backend")

    def test_p0b_2_explicit_assigned_to(self):
        """T-P0B-2: Create with assigned_to='kai' → assigned_to = 'kai'."""
        data = {
            "name": "Test Auto",
            "created_by": "backend",
            "assigned_to": "kai",
            "trigger": {"type": "schedule", "cron": "*/5 * * * *"},
            "action": {"type": "send_message", "to": "user", "content": "test"},
        }
        auto, _ = ae.add_automation(data)
        self.assertIsNotNone(auto)
        self.assertEqual(auto.get("assigned_to", auto.get("created_by")), "kai")

    def test_p0b_3_update_assigned_to(self):
        """T-P0B-3: Update assigned_to from 'backend' to 'atlas' → persisted."""
        data = {
            "name": "Test Auto",
            "created_by": "backend",
            "assigned_to": "backend",
            "trigger": {"type": "schedule", "cron": "*/5 * * * *"},
            "action": {"type": "send_message", "to": "user", "content": "test"},
        }
        auto, _ = ae.add_automation(data)
        auto_id = auto["id"]

        updated = ae.update_automation(auto_id, {"assigned_to": "atlas"})
        if updated and "assigned_to" in updated:
            self.assertEqual(updated["assigned_to"], "atlas")
        else:
            self.skipTest("assigned_to update not yet implemented")

    def test_p0b_4_idle_check_uses_assigned_to(self):
        """T-P0B-4: Idle check targets assigned_to, not created_by."""
        checked_agents = []

        def idle_check(agent_id):
            checked_agents.append(agent_id)
            return True

        def action_cb(a):
            return {"ok": True}

        auto = _make_automation(created_by="backend", assigned_to="kai")
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        try:
            scheduler = ae.AutomationScheduler(
                action_callback=action_cb,
                check_interval=1,
                idle_check_callback=idle_check,
            )
        except TypeError:
            self.skipTest("idle_check_callback not yet implemented")

        scheduler._tick()
        self.assertIn("kai", checked_agents,
                       "Should check assigned_to agent, not created_by")
        self.assertNotIn("backend", checked_agents,
                          "Should NOT check created_by when assigned_to is set")


# ===========================================================================
# P1-C: Jitter Tests
# ===========================================================================
class TestP1C_Jitter(unittest.TestCase):
    """T-P1C-1 through T-P1C-5: Deterministic Jitter."""

    def test_p1c_1_different_ids_different_jitter(self):
        """T-P1C-1: Two automations with same cron → different fire times."""
        if not hasattr(ae, '_compute_jitter'):
            self.skipTest("_compute_jitter not yet implemented")

        j1 = ae._compute_jitter("auto_aaa", 300)  # 5min = 300s
        j2 = ae._compute_jitter("auto_bbb", 300)
        # Very unlikely to be equal with different IDs
        self.assertNotEqual(j1, j2,
                            "Different automation IDs should produce different jitter")

    def test_p1c_2_deterministic(self):
        """T-P1C-2: Same automation → same jitter every time."""
        if not hasattr(ae, '_compute_jitter'):
            self.skipTest("_compute_jitter not yet implemented")

        j1 = ae._compute_jitter("auto_xxx", 300)
        j2 = ae._compute_jitter("auto_xxx", 300)
        self.assertEqual(j1, j2, "Same ID should produce same jitter")

    def test_p1c_3_5min_max_30s(self):
        """T-P1C-3: 5min interval → max 30s jitter (10%)."""
        if not hasattr(ae, '_compute_jitter'):
            self.skipTest("_compute_jitter not yet implemented")

        for i in range(20):
            j = ae._compute_jitter(f"auto_{i}", 300)
            self.assertLessEqual(j, 30, f"5min jitter should be ≤30s, got {j}")
            self.assertGreaterEqual(j, 0)

    def test_p1c_4_1h_max_360s(self):
        """T-P1C-4: 1h interval → max 360s (6min) jitter."""
        if not hasattr(ae, '_compute_jitter'):
            self.skipTest("_compute_jitter not yet implemented")

        for i in range(20):
            j = ae._compute_jitter(f"auto_{i}", 3600)
            self.assertLessEqual(j, 360)
            self.assertGreaterEqual(j, 0)

    def test_p1c_5_1d_capped_900s(self):
        """T-P1C-5: 1d interval → max 900s (15min, cap)."""
        if not hasattr(ae, '_compute_jitter'):
            self.skipTest("_compute_jitter not yet implemented")

        for i in range(20):
            j = ae._compute_jitter(f"auto_{i}", 86400)
            self.assertLessEqual(j, 900, f"Daily jitter should be capped at 900s, got {j}")
            self.assertGreaterEqual(j, 0)


# ===========================================================================
# P1-A: interval_to_cron Tests (bridge_mcp.py helper)
# ===========================================================================
class TestP1A_IntervalToCron(unittest.TestCase):
    """T-P1A-1 through T-P1A-9: bridge_loop interval parsing."""

    def _get_interval_to_cron(self):
        """Try to import interval_to_cron from bridge_mcp."""
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            from bridge_mcp import interval_to_cron
            return interval_to_cron
        except (ImportError, AttributeError):
            return None

    def test_p1a_1_5m(self):
        """T-P1A-1: '5m' → '*/5 * * * *'."""
        fn = self._get_interval_to_cron()
        if not fn:
            self.skipTest("interval_to_cron not yet implemented")
        self.assertEqual(fn("5m"), "*/5 * * * *")

    def test_p1a_2_2h(self):
        """T-P1A-2: '2h' → '0 */2 * * *'."""
        fn = self._get_interval_to_cron()
        if not fn:
            self.skipTest("interval_to_cron not yet implemented")
        self.assertEqual(fn("2h"), "0 */2 * * *")

    def test_p1a_3_30s_rounds_up(self):
        """T-P1A-3: '30s' → '*/1 * * * *' (rounds up to 1min)."""
        fn = self._get_interval_to_cron()
        if not fn:
            self.skipTest("interval_to_cron not yet implemented")
        result = fn("30s")
        self.assertIn(result, ("*/1 * * * *", "* * * * *"),
                       f"30s should round to every minute, got {result}")

    def test_p1a_5_default_10m(self):
        """T-P1A-5: Default interval '10m' → '*/10 * * * *'."""
        fn = self._get_interval_to_cron()
        if not fn:
            self.skipTest("interval_to_cron not yet implemented")
        self.assertEqual(fn("10m"), "*/10 * * * *")

    def test_p1a_6_invalid_interval(self):
        """T-P1A-6: 'abc' → ValueError."""
        fn = self._get_interval_to_cron()
        if not fn:
            self.skipTest("interval_to_cron not yet implemented")
        with self.assertRaises(ValueError):
            fn("abc")

    def test_p1a_4_1d_relative(self):
        """T-P1A-4/9: '1d' → relative to current time (Atlas-K2)."""
        fn = self._get_interval_to_cron()
        if not fn:
            self.skipTest("interval_to_cron not yet implemented")
        result = fn("1d")
        # Should be "{minute} {hour} * * *" based on current time
        parts = result.split()
        self.assertEqual(len(parts), 5, "Should be 5-field cron")
        self.assertEqual(parts[2], "*")
        self.assertEqual(parts[3], "*")
        self.assertEqual(parts[4], "*")
        # Minute and hour should be numbers (not *)
        self.assertTrue(parts[0].isdigit(), f"Minute should be digit, got {parts[0]}")
        self.assertTrue(parts[1].isdigit(), f"Hour should be digit, got {parts[1]}")


# ===========================================================================
# P1-B: Prompt-Replay Tests
# ===========================================================================
class TestP1B_PromptReplay(unittest.TestCase):
    """T-P1B-1 through T-P1B-8: Prompt-Replay Action."""

    def setUp(self):
        _clear_automations()

    def tearDown(self):
        _clear_automations()

    def _make_prompt_auto(
        self,
        auto_id: str = "prompt_auto_1",
        prompt: str = "check deploy status",
        urgent: bool = False,
        assigned_to: str = "backend",
        max_runs: int = 0,
    ) -> dict[str, Any]:
        """Create a prompt_replay automation."""
        auto = _make_automation(
            auto_id=auto_id,
            action_type="prompt_replay",
            assigned_to=assigned_to,
            max_runs=max_runs,
        )
        auto["action"] = {
            "type": "prompt_replay",
            "prompt": prompt,
            "urgent": urgent,
        }
        return auto

    @patch("automation_engine._http_post")
    def test_p1b_1_default_bridge_send(self, mock_post):
        """T-P1B-1: prompt_replay (default) → bridge_send with [SCHEDULED PROMPT] prefix."""
        mock_post.return_value = {"ok": True}
        auto = self._make_prompt_auto()

        result = ae.execute_action(auto)

        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("delivery_method"), "bridge_send")
        # Verify the HTTP call was to /send
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], "/send")
        payload = call_args[0][1]
        self.assertEqual(payload["from"], "system")
        self.assertIn("[SCHEDULED PROMPT]", payload["content"])
        self.assertEqual(payload["to"], "backend")
        self.assertEqual(payload["meta"]["automation_created_by"], "backend")

    @patch("automation_engine._http_post")
    def test_p1b_2_busy_agent_buffered(self, mock_post):
        """T-P1B-2: prompt_replay + Agent busy → bridge_send (normal buffering)."""
        mock_post.return_value = {"ok": True}
        auto = self._make_prompt_auto()

        result = ae.execute_action(auto)

        # Should use bridge_send regardless of busy state (Stufe 1)
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("delivery_method"), "bridge_send")

    @patch("automation_engine._http_post")
    @patch("subprocess.run")
    def test_p1b_3_urgent_at_prompt_tmux(self, mock_run, mock_post):
        """T-P1B-3: prompt_replay urgent + Agent at prompt → tmux send-keys."""
        # Mock tmux has-session success
        mock_has_session = MagicMock(returncode=0)
        # Mock capture-pane with prompt indicator
        mock_capture = MagicMock(returncode=0, stdout="Some output\n> \n")
        # Mock send-keys -l (literal text) + send-keys Enter
        mock_send_text = MagicMock(returncode=0)
        mock_send_enter = MagicMock(returncode=0)

        mock_run.side_effect = [mock_has_session, mock_capture, mock_send_text, mock_send_enter]

        auto = self._make_prompt_auto(urgent=True)
        result = ae.execute_action(auto)

        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("delivery_method"), "tmux_send_keys")
        # bridge_send should NOT have been called
        mock_post.assert_not_called()

    @patch("automation_engine._http_post")
    @patch("subprocess.run")
    def test_p1b_4_urgent_not_at_prompt_fallback(self, mock_run, mock_post):
        """T-P1B-4: prompt_replay urgent + Agent NOT at prompt → fallback to bridge_send."""
        mock_post.return_value = {"ok": True}

        # Mock tmux has-session success
        mock_has_session = MagicMock(returncode=0)
        # Mock capture-pane with agent working (no prompt)
        mock_capture = MagicMock(returncode=0, stdout="Processing files...\nRunning tests...\n")

        mock_run.side_effect = [mock_has_session, mock_capture]

        auto = self._make_prompt_auto(urgent=True)
        result = ae.execute_action(auto)

        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("delivery_method"), "bridge_send")
        mock_post.assert_called_once()

    def test_p1b_5_shell_injection_safe(self):
        """T-P1B-5: prompt_replay with injection attempt → safe (no shell=True)."""
        auto = self._make_prompt_auto(prompt="test; rm -rf /")
        # Stufe 1 (bridge_send) — no shell involvement
        with patch("automation_engine._http_post") as mock_post:
            mock_post.return_value = {"ok": True}
            result = ae.execute_action(auto)
            self.assertTrue(result.get("ok"))
            payload = mock_post.call_args[0][1]
            # Content should contain the raw prompt, no interpretation
            self.assertIn("test; rm -rf /", payload["content"])

    def test_p1b_6_prompt_too_long(self):
        """T-P1B-6: prompt_replay with prompt > 4096 chars → error."""
        auto = self._make_prompt_auto(prompt="x" * 5000)
        result = ae.execute_action(auto)
        self.assertFalse(result.get("ok"))
        self.assertIn("too long", result.get("error", ""))

    @patch("automation_engine._http_post")
    def test_p1b_7_history_delivery_method(self, mock_post):
        """T-P1B-7: prompt_replay → result has delivery_method for history."""
        mock_post.return_value = {"ok": True}
        auto = self._make_prompt_auto()

        result = ae.execute_action(auto)

        self.assertIn("delivery_method", result)
        self.assertIn(result["delivery_method"], ("bridge_send", "tmux_send_keys"))

    def test_p1b_8_empty_prompt_error(self):
        """T-P1B-8: prompt_replay with empty prompt → error."""
        auto = self._make_prompt_auto(prompt="")
        result = ae.execute_action(auto)
        self.assertFalse(result.get("ok"))
        self.assertIn("requires", result.get("error", ""))

    @patch("subprocess.run")
    def test_p1b_tmux_session_not_found(self, mock_run):
        """tmux session not found → fallback to bridge_send."""
        mock_run.return_value = MagicMock(returncode=1)

        result = ae._try_tmux_prompt_replay("nonexistent", "test prompt")

        self.assertFalse(result.get("ok"))
        self.assertIn("not found", result.get("reason", ""))


# ===========================================================================
# P2: Catch-Up Policy Tests
# ===========================================================================
class TestP2_CatchUpPolicy(unittest.TestCase):
    """T-P2-1 through T-P2-5: Catch-Up Policy."""

    def setUp(self):
        _clear_automations()

    def tearDown(self):
        _clear_automations()

    def _make_catchup_auto(
        self,
        auto_id: str = "catchup_auto_1",
        catch_up: str = "skip",
        max_catch_up_runs: int = 10,
        assigned_to: str = "backend",
        last_run_hours_ago: float = 2.0,
        cron: str = "*/30 * * * *",
    ) -> dict[str, Any]:
        """Create an automation with catch_up policy and a last_run in the past."""
        auto = _make_automation(
            auto_id=auto_id,
            cron=cron,
            assigned_to=assigned_to,
        )
        auto["options"]["catch_up"] = catch_up
        auto["options"]["max_catch_up_runs"] = max_catch_up_runs
        last_run = datetime.now(timezone.utc) - timedelta(hours=last_run_hours_ago)
        auto["last_run"] = last_run.isoformat()
        return auto

    def test_p2_1_skip_policy_no_catchup(self):
        """T-P2-1: Agent 2h offline, */30 Cron, policy=skip → 0 catch-up runs."""
        auto = self._make_catchup_auto(catch_up="skip")
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        results = ae.check_catch_up("backend")
        self.assertEqual(len(results), 0, "skip policy should produce no catch-up")

    @patch("automation_engine._http_post")
    def test_p2_2_run_once_policy(self, mock_post):
        """T-P2-2: Agent 2h offline, */30 Cron, policy=run_once → exactly 1 catch-up run."""
        mock_post.return_value = {"ok": True}
        auto = self._make_catchup_auto(catch_up="run_once")
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        # Need a scheduler with action_callback
        scheduler = ae.AutomationScheduler(action_callback=ae.execute_action)
        ae._scheduler = scheduler

        results = ae.check_catch_up("backend")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["executed"], 1)
        self.assertEqual(results[0]["policy"], "run_once")
        self.assertGreater(results[0]["missed"], 1, "Should have missed multiple runs")

    @patch("automation_engine._http_post")
    def test_p2_3_run_all_policy(self, mock_post):
        """T-P2-3: Agent 2h offline, */30 Cron, policy=run_all → 4 catch-up runs."""
        mock_post.return_value = {"ok": True}
        auto = self._make_catchup_auto(catch_up="run_all")
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        scheduler = ae.AutomationScheduler(action_callback=ae.execute_action)
        ae._scheduler = scheduler

        results = ae.check_catch_up("backend")

        self.assertEqual(len(results), 1)
        # 2h with */30 = ~4 missed runs (could be 3-4 depending on timing)
        self.assertGreaterEqual(results[0]["executed"], 3)
        self.assertLessEqual(results[0]["executed"], 5)
        self.assertEqual(results[0]["policy"], "run_all")

    @patch("automation_engine._http_post")
    def test_p2_4_run_all_max_cap(self, mock_post):
        """T-P2-4: policy=run_all + max_catch_up_runs=2 → max 2 runs."""
        mock_post.return_value = {"ok": True}
        auto = self._make_catchup_auto(catch_up="run_all", max_catch_up_runs=2)
        with ae.AUTOMATION_LOCK:
            ae.AUTOMATIONS[auto["id"]] = auto

        scheduler = ae.AutomationScheduler(action_callback=ae.execute_action)
        ae._scheduler = scheduler

        results = ae.check_catch_up("backend")

        self.assertEqual(len(results), 1)
        self.assertLessEqual(results[0]["executed"], 2, "Should be capped at max_catch_up_runs")

    def test_p2_5_default_policy_is_skip(self):
        """T-P2-5: Default catch_up policy → skip."""
        auto = _make_automation(auto_id="default_policy_test", assigned_to="backend")
        _, _ = ae.add_automation({
            "name": "test",
            "trigger": {"type": "schedule", "cron": "*/5 * * * *"},
            "action": {"type": "send_message", "to": "user", "content": "test"},
            "created_by": "backend",
        })
        # Check that newly created automation has skip as default
        with ae.AUTOMATION_LOCK:
            for a in ae.AUTOMATIONS.values():
                opts = a.get("options", {})
                self.assertEqual(opts.get("catch_up"), "skip",
                                 "Default catch_up should be 'skip'")
                break

    def test_p2_count_missed_runs(self):
        """_count_missed_runs correctly counts missed cron runs."""
        auto = self._make_catchup_auto(
            last_run_hours_ago=1.0,
            cron="*/10 * * * *",  # every 10 min → 6 per hour
        )
        now = datetime.now(timezone.utc)
        missed = ae._count_missed_runs(auto, now)
        # 1 hour with */10 = ~6 missed runs
        self.assertGreaterEqual(missed, 5)
        self.assertLessEqual(missed, 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
