"""
Tests for delegation.py — Hierarchical Delegation and Sub-Agent Spawning

Tests cover:
  - TaskState and TaskPriority enums
  - DelegationTask dataclass
  - DelegationResult dataclass
  - LaneQueue (acquire, release, promote, remove)
  - Task creation (success, validation)
  - Task lifecycle (submit, start, complete, cancel, timeout)
  - Timeout checking
  - Queries (get task, children, results, counts)
  - Status reporting
  - Thread safety
"""

import os
import sys
import threading
import time
import unittest

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delegation import (
    DelegationManager,
    DelegationResult,
    DelegationTask,
    LaneQueue,
    TaskPriority,
    TaskState,
)


class TestTaskState(unittest.TestCase):
    """Test TaskState enum."""

    def test_all_states(self):
        expected = {
            "pending", "queued", "assigned", "working",
            "completed", "failed", "timed_out", "cancelled",
        }
        actual = {s.value for s in TaskState}
        self.assertEqual(actual, expected)


class TestTaskPriority(unittest.TestCase):
    """Test TaskPriority enum."""

    def test_ordering(self):
        self.assertLess(TaskPriority.LOW.value, TaskPriority.NORMAL.value)
        self.assertLess(TaskPriority.NORMAL.value, TaskPriority.HIGH.value)
        self.assertLess(TaskPriority.HIGH.value, TaskPriority.CRITICAL.value)


class TestDelegationTask(unittest.TestCase):
    """Test DelegationTask dataclass."""

    def test_defaults(self):
        t = DelegationTask(
            task_id="dt_1", parent_agent="lead",
            description="Do something",
        )
        self.assertEqual(t.state, TaskState.PENDING)
        self.assertEqual(t.engine, "claude")
        self.assertGreater(t.created_at, 0)

    def test_to_dict(self):
        t = DelegationTask(
            task_id="dt_1", parent_agent="lead",
            description="Task", engine="echo",
            priority=TaskPriority.HIGH,
        )
        d = t.to_dict()
        self.assertEqual(d["task_id"], "dt_1")
        self.assertEqual(d["priority"], "high")
        self.assertEqual(d["state"], "pending")

    def test_is_terminal(self):
        t = DelegationTask(task_id="1", parent_agent="a", description="d")
        self.assertFalse(t.is_terminal)
        t.state = TaskState.COMPLETED
        self.assertTrue(t.is_terminal)

    def test_elapsed_not_started(self):
        t = DelegationTask(task_id="1", parent_agent="a", description="d")
        self.assertEqual(t.elapsed_seconds, 0.0)

    def test_elapsed_running(self):
        t = DelegationTask(
            task_id="1", parent_agent="a", description="d",
            state=TaskState.WORKING,
            started_at=time.time() - 5.0,
        )
        self.assertGreaterEqual(t.elapsed_seconds, 4.0)


class TestDelegationResult(unittest.TestCase):
    """Test DelegationResult dataclass."""

    def test_to_dict(self):
        r = DelegationResult(
            task_id="dt_1", agent_id="sub_1",
            success=True, content="Done!",
            elapsed_seconds=10.5,
        )
        d = r.to_dict()
        self.assertEqual(d["task_id"], "dt_1")
        self.assertTrue(d["success"])
        self.assertEqual(d["elapsed_seconds"], 10.5)


class TestLaneQueue(unittest.TestCase):
    """Test LaneQueue concurrency control."""

    def test_acquire_within_limit(self):
        lq = LaneQueue(max_concurrent=2)
        self.assertTrue(lq.try_acquire("t1"))
        self.assertTrue(lq.try_acquire("t2"))
        self.assertEqual(lq.active_count, 2)

    def test_acquire_at_limit_queues(self):
        lq = LaneQueue(max_concurrent=1)
        self.assertTrue(lq.try_acquire("t1"))
        self.assertFalse(lq.try_acquire("t2"))
        self.assertEqual(lq.active_count, 1)
        self.assertEqual(lq.queued_count, 1)

    def test_release_promotes_queued(self):
        lq = LaneQueue(max_concurrent=1)
        lq.try_acquire("t1")
        lq.try_acquire("t2")
        promoted = lq.release("t1")
        self.assertEqual(promoted, "t2")
        self.assertEqual(lq.active_count, 1)
        self.assertEqual(lq.queued_count, 0)

    def test_release_no_queue(self):
        lq = LaneQueue(max_concurrent=2)
        lq.try_acquire("t1")
        promoted = lq.release("t1")
        self.assertIsNone(promoted)
        self.assertEqual(lq.active_count, 0)

    def test_remove_from_active(self):
        lq = LaneQueue(max_concurrent=2)
        lq.try_acquire("t1")
        self.assertTrue(lq.remove("t1"))
        self.assertEqual(lq.active_count, 0)

    def test_remove_from_queue(self):
        lq = LaneQueue(max_concurrent=1)
        lq.try_acquire("t1")
        lq.try_acquire("t2")
        self.assertTrue(lq.remove("t2"))
        self.assertEqual(lq.queued_count, 0)

    def test_remove_not_found(self):
        lq = LaneQueue(max_concurrent=2)
        self.assertFalse(lq.remove("missing"))

    def test_available_slots(self):
        lq = LaneQueue(max_concurrent=3)
        self.assertEqual(lq.available_slots, 3)
        lq.try_acquire("t1")
        self.assertEqual(lq.available_slots, 2)

    def test_status(self):
        lq = LaneQueue(max_concurrent=2)
        lq.try_acquire("t1")
        s = lq.status()
        self.assertEqual(s["max_concurrent"], 2)
        self.assertEqual(s["active_count"], 1)
        self.assertEqual(s["available_slots"], 1)


class TestTaskCreation(unittest.TestCase):
    """Test task creation."""

    def setUp(self):
        self.dm = DelegationManager()

    def test_create_task(self):
        task = self.dm.create_task("lead", "Do something")
        self.assertTrue(task.task_id.startswith("dt_"))
        self.assertEqual(task.parent_agent, "lead")
        self.assertEqual(task.state, TaskState.PENDING)

    def test_create_with_options(self):
        task = self.dm.create_task(
            "lead", "Research",
            engine="gemini",
            priority=TaskPriority.HIGH,
            timeout=1800,
            metadata={"topic": "AI"},
        )
        self.assertEqual(task.engine, "gemini")
        self.assertEqual(task.priority, TaskPriority.HIGH)
        self.assertEqual(task.timeout, 1800)
        self.assertEqual(task.metadata, {"topic": "AI"})

    def test_create_empty_parent_raises(self):
        with self.assertRaises(ValueError):
            self.dm.create_task("", "description")

    def test_create_empty_description_raises(self):
        with self.assertRaises(ValueError):
            self.dm.create_task("lead", "")

    def test_create_tracks_children(self):
        self.dm.create_task("lead", "Task 1")
        self.dm.create_task("lead", "Task 2")
        children = self.dm.get_children("lead")
        self.assertEqual(len(children), 2)


class TestTaskLifecycle(unittest.TestCase):
    """Test task lifecycle transitions."""

    def setUp(self):
        self.dm = DelegationManager()

    def test_submit_acquires_slot(self):
        task = self.dm.create_task("lead", "Task")
        acquired = self.dm.submit_task(task.task_id)
        self.assertTrue(acquired)
        self.assertEqual(task.state, TaskState.ASSIGNED)

    def test_submit_queued_when_full(self):
        dm = DelegationManager(sub_lane_limit=1)
        t1 = dm.create_task("lead", "Task 1")
        t2 = dm.create_task("lead", "Task 2")
        dm.submit_task(t1.task_id)
        acquired = dm.submit_task(t2.task_id)
        self.assertFalse(acquired)
        self.assertEqual(t2.state, TaskState.QUEUED)

    def test_start_task(self):
        task = self.dm.create_task("lead", "Task")
        self.dm.submit_task(task.task_id)
        self.assertTrue(self.dm.start_task(task.task_id, "sub_1"))
        self.assertEqual(task.state, TaskState.WORKING)
        self.assertEqual(task.assigned_agent, "sub_1")
        self.assertGreater(task.started_at, 0)

    def test_complete_task(self):
        task = self.dm.create_task("lead", "Task")
        self.dm.submit_task(task.task_id)
        self.dm.start_task(task.task_id, "sub_1")
        result = self.dm.complete_task(task.task_id, "Done!")
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.content, "Done!")
        self.assertEqual(task.state, TaskState.COMPLETED)

    def test_complete_with_failure(self):
        task = self.dm.create_task("lead", "Task")
        self.dm.submit_task(task.task_id)
        self.dm.start_task(task.task_id, "sub_1")
        result = self.dm.complete_task(task.task_id, "Error!", success=False)
        self.assertFalse(result.success)
        self.assertEqual(task.state, TaskState.FAILED)
        self.assertEqual(task.error, "Error!")

    def test_complete_promotes_queued(self):
        dm = DelegationManager(sub_lane_limit=1)
        t1 = dm.create_task("lead", "Task 1")
        t2 = dm.create_task("lead", "Task 2")
        dm.submit_task(t1.task_id)
        dm.submit_task(t2.task_id)  # Queued
        dm.start_task(t1.task_id, "sub_1")
        dm.complete_task(t1.task_id, "Done")
        # t2 should now be ASSIGNED
        self.assertEqual(t2.state, TaskState.ASSIGNED)

    def test_cancel_task(self):
        task = self.dm.create_task("lead", "Task")
        self.dm.submit_task(task.task_id)
        self.assertTrue(self.dm.cancel_task(task.task_id))
        self.assertEqual(task.state, TaskState.CANCELLED)

    def test_cancel_completed_fails(self):
        task = self.dm.create_task("lead", "Task")
        self.dm.submit_task(task.task_id)
        self.dm.start_task(task.task_id, "sub_1")
        self.dm.complete_task(task.task_id, "Done")
        self.assertFalse(self.dm.cancel_task(task.task_id))

    def test_timeout_task(self):
        task = self.dm.create_task("lead", "Task")
        self.dm.submit_task(task.task_id)
        self.dm.start_task(task.task_id, "sub_1")
        self.assertTrue(self.dm.timeout_task(task.task_id))
        self.assertEqual(task.state, TaskState.TIMED_OUT)


class TestTimeoutChecking(unittest.TestCase):
    """Test automatic timeout detection."""

    def test_check_timeouts(self):
        dm = DelegationManager()
        task = dm.create_task("lead", "Task", timeout=0.01)
        dm.submit_task(task.task_id)
        dm.start_task(task.task_id, "sub_1")
        time.sleep(0.02)
        timed_out = dm.check_timeouts()
        self.assertEqual(len(timed_out), 1)
        self.assertEqual(task.state, TaskState.TIMED_OUT)

    def test_check_no_timeouts(self):
        dm = DelegationManager()
        task = dm.create_task("lead", "Task", timeout=3600)
        dm.submit_task(task.task_id)
        dm.start_task(task.task_id, "sub_1")
        timed_out = dm.check_timeouts()
        self.assertEqual(len(timed_out), 0)


class TestQueries(unittest.TestCase):
    """Test query methods."""

    def setUp(self):
        self.dm = DelegationManager()
        self.t1 = self.dm.create_task("lead", "Task 1")
        self.t2 = self.dm.create_task("lead", "Task 2")
        self.t3 = self.dm.create_task("other", "Task 3")

    def test_get_task(self):
        task = self.dm.get_task(self.t1.task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task.description, "Task 1")

    def test_get_task_not_found(self):
        self.assertIsNone(self.dm.get_task("missing"))

    def test_get_children(self):
        children = self.dm.get_children("lead")
        self.assertEqual(len(children), 2)

    def test_get_children_empty(self):
        children = self.dm.get_children("nobody")
        self.assertEqual(children, [])

    def test_get_result(self):
        self.dm.submit_task(self.t1.task_id)
        self.dm.start_task(self.t1.task_id, "sub_1")
        self.dm.complete_task(self.t1.task_id, "Done")
        result = self.dm.get_result(self.t1.task_id)
        self.assertIsNotNone(result)
        self.assertEqual(result.content, "Done")

    def test_get_pending_results(self):
        self.dm.submit_task(self.t1.task_id)
        self.dm.start_task(self.t1.task_id, "sub_1")
        self.dm.complete_task(self.t1.task_id, "Done")
        results = self.dm.get_pending_results("lead")
        self.assertEqual(len(results), 1)

    def test_count_active(self):
        self.dm.submit_task(self.t1.task_id)
        self.dm.start_task(self.t1.task_id, "sub_1")
        active = self.dm.count_active("lead")
        self.assertEqual(active, 2)  # t1 working + t2 pending

    def test_count_active_after_complete(self):
        self.dm.submit_task(self.t1.task_id)
        self.dm.start_task(self.t1.task_id, "sub_1")
        self.dm.complete_task(self.t1.task_id, "Done")
        active = self.dm.count_active("lead")
        self.assertEqual(active, 1)  # Only t2 pending


class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def test_status(self):
        dm = DelegationManager()
        dm.create_task("lead", "Task 1")
        dm.create_task("lead", "Task 2")
        s = dm.status()
        self.assertEqual(s["total_tasks"], 2)
        self.assertIn("lead", s["parents"])
        self.assertIn("main_lane", s)
        self.assertIn("sub_lane", s)


class TestThreadSafety(unittest.TestCase):
    """Test thread safety."""

    def test_concurrent_create(self):
        dm = DelegationManager()
        errors = []

        def creator(agent_id):
            try:
                for i in range(20):
                    dm.create_task(agent_id, f"Task {i}")
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=creator, args=(f"agent_{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(dm.status()["total_tasks"], 100)

    def test_concurrent_lifecycle(self):
        dm = DelegationManager(sub_lane_limit=20)
        tasks = [dm.create_task("lead", f"Task {i}") for i in range(20)]
        errors = []

        def lifecycle(task):
            try:
                dm.submit_task(task.task_id)
                dm.start_task(task.task_id, f"sub_{task.task_id}")
                time.sleep(0.001)
                dm.complete_task(task.task_id, "Done")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=lifecycle, args=(t,)) for t in tasks]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        # All tasks should be completed
        completed = sum(
            1 for t in tasks
            if t.state == TaskState.COMPLETED
        )
        self.assertEqual(completed, 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
