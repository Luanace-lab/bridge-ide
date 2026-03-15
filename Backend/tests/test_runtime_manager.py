"""
Tests for runtime_manager.py — Agent Runtime & Factory

Tests cover:
  - AgentState enum values
  - AgentInfo dataclass (to_dict, uptime_seconds)
  - Agent creation (success, duplicate, slot limit)
  - Agent removal (success, running agent, not found)
  - Lifecycle transitions (start, stop, restart)
  - Heartbeat recording
  - Error marking
  - Agent queries (get, list, filter, count)
  - Health monitoring (check_health, cleanup_stale)
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

from runtime_manager import AgentInfo, AgentState, RuntimeManager


class TestAgentState(unittest.TestCase):
    """Test AgentState enum."""

    def test_all_states(self):
        expected = {"creating", "starting", "running", "stopping", "stopped", "error"}
        actual = {s.value for s in AgentState}
        self.assertEqual(actual, expected)

    def test_state_values(self):
        self.assertEqual(AgentState.CREATING.value, "creating")
        self.assertEqual(AgentState.RUNNING.value, "running")
        self.assertEqual(AgentState.ERROR.value, "error")


class TestAgentInfo(unittest.TestCase):
    """Test AgentInfo dataclass."""

    def test_defaults(self):
        info = AgentInfo(agent_id="a1", role="tester", engine="claude")
        self.assertEqual(info.agent_id, "a1")
        self.assertEqual(info.state, AgentState.STOPPED)
        self.assertEqual(info.created_at, 0.0)
        self.assertEqual(info.error, "")
        self.assertEqual(info.skills, [])
        self.assertEqual(info.metadata, {})

    def test_to_dict(self):
        info = AgentInfo(
            agent_id="a1",
            role="tester",
            engine="echo",
            state=AgentState.RUNNING,
            skills=["pdf", "excel"],
            metadata={"key": "value"},
        )
        d = info.to_dict()
        self.assertEqual(d["agent_id"], "a1")
        self.assertEqual(d["role"], "tester")
        self.assertEqual(d["engine"], "echo")
        self.assertEqual(d["state"], "running")
        self.assertEqual(d["skills"], ["pdf", "excel"])
        self.assertEqual(d["metadata"], {"key": "value"})

    def test_to_dict_keys(self):
        info = AgentInfo(agent_id="a1", role="r", engine="e")
        d = info.to_dict()
        expected_keys = {
            "agent_id", "role", "engine", "state",
            "created_at", "started_at", "stopped_at",
            "last_heartbeat", "error", "skills", "metadata",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_uptime_stopped(self):
        info = AgentInfo(agent_id="a1", role="r", engine="e")
        self.assertEqual(info.uptime_seconds, 0.0)

    def test_uptime_running(self):
        info = AgentInfo(
            agent_id="a1", role="r", engine="e",
            state=AgentState.RUNNING,
            started_at=time.time() - 10.0,
        )
        self.assertGreaterEqual(info.uptime_seconds, 9.0)
        self.assertLessEqual(info.uptime_seconds, 12.0)

    def test_uptime_running_no_start_time(self):
        info = AgentInfo(
            agent_id="a1", role="r", engine="e",
            state=AgentState.RUNNING,
            started_at=0,
        )
        self.assertEqual(info.uptime_seconds, 0.0)


class TestAgentCreation(unittest.TestCase):
    """Test agent creation."""

    def setUp(self):
        self.rm = RuntimeManager(max_agents=3)

    def test_create_agent(self):
        info = self.rm.create_agent("a1", "tester")
        self.assertEqual(info.agent_id, "a1")
        self.assertEqual(info.role, "tester")
        self.assertEqual(info.engine, "claude")
        self.assertEqual(info.state, AgentState.CREATING)
        self.assertGreater(info.created_at, 0)

    def test_create_with_engine(self):
        info = self.rm.create_agent("a1", "tester", engine="echo")
        self.assertEqual(info.engine, "echo")

    def test_create_with_skills(self):
        info = self.rm.create_agent("a1", "tester", skills=["pdf", "excel"])
        self.assertEqual(info.skills, ["pdf", "excel"])

    def test_create_with_metadata(self):
        info = self.rm.create_agent("a1", "tester", metadata={"team": "alpha"})
        self.assertEqual(info.metadata, {"team": "alpha"})

    def test_create_duplicate_raises(self):
        self.rm.create_agent("a1", "tester")
        with self.assertRaises(ValueError) as ctx:
            self.rm.create_agent("a1", "another")
        self.assertIn("already exists", str(ctx.exception))

    def test_create_slot_limit(self):
        rm = RuntimeManager(max_agents=2)
        rm.create_agent("a1", "r1")
        rm.start_agent("a1")
        rm.create_agent("a2", "r2")
        rm.start_agent("a2")
        with self.assertRaises(ValueError) as ctx:
            rm.create_agent("a3", "r3")
        self.assertIn("slot limit", str(ctx.exception))

    def test_create_after_stop_frees_slot(self):
        rm = RuntimeManager(max_agents=1)
        rm.create_agent("a1", "r1")
        rm.start_agent("a1")
        rm.stop_agent("a1")
        # Stopped agent doesn't count against slot limit
        info = rm.create_agent("a2", "r2")
        self.assertIsNotNone(info)

    def test_create_defaults_empty_skills(self):
        info = self.rm.create_agent("a1", "tester")
        self.assertEqual(info.skills, [])

    def test_create_defaults_empty_metadata(self):
        info = self.rm.create_agent("a1", "tester")
        self.assertEqual(info.metadata, {})


class TestAgentRemoval(unittest.TestCase):
    """Test agent removal."""

    def setUp(self):
        self.rm = RuntimeManager()

    def test_remove_stopped_agent(self):
        self.rm.create_agent("a1", "tester")
        self.assertTrue(self.rm.remove_agent("a1"))
        self.assertIsNone(self.rm.get_agent("a1"))

    def test_remove_not_found(self):
        self.assertFalse(self.rm.remove_agent("missing"))

    def test_remove_running_raises(self):
        self.rm.create_agent("a1", "tester")
        self.rm.start_agent("a1")
        with self.assertRaises(ValueError) as ctx:
            self.rm.remove_agent("a1")
        self.assertIn("running", str(ctx.exception))

    def test_remove_creating_agent(self):
        self.rm.create_agent("a1", "tester")
        # CREATING state — should be removable
        self.assertTrue(self.rm.remove_agent("a1"))


class TestLifecycle(unittest.TestCase):
    """Test agent lifecycle transitions."""

    def setUp(self):
        self.rm = RuntimeManager()

    def test_start_agent(self):
        self.rm.create_agent("a1", "tester")
        self.assertTrue(self.rm.start_agent("a1"))
        info = self.rm.get_agent("a1")
        self.assertEqual(info.state, AgentState.RUNNING)
        self.assertGreater(info.started_at, 0)
        self.assertGreater(info.last_heartbeat, 0)

    def test_start_already_running(self):
        self.rm.create_agent("a1", "tester")
        self.rm.start_agent("a1")
        self.assertTrue(self.rm.start_agent("a1"))  # Idempotent

    def test_start_not_found(self):
        self.assertFalse(self.rm.start_agent("missing"))

    def test_stop_agent(self):
        self.rm.create_agent("a1", "tester")
        self.rm.start_agent("a1")
        self.assertTrue(self.rm.stop_agent("a1"))
        info = self.rm.get_agent("a1")
        self.assertEqual(info.state, AgentState.STOPPED)
        self.assertGreater(info.stopped_at, 0)

    def test_stop_already_stopped(self):
        self.rm.create_agent("a1", "tester")
        self.assertTrue(self.rm.stop_agent("a1"))  # CREATING -> stop -> STOPPED

    def test_stop_not_found(self):
        self.assertFalse(self.rm.stop_agent("missing"))

    def test_restart_agent(self):
        self.rm.create_agent("a1", "tester")
        self.rm.start_agent("a1")
        self.assertTrue(self.rm.restart_agent("a1"))
        info = self.rm.get_agent("a1")
        self.assertEqual(info.state, AgentState.RUNNING)

    def test_start_from_error_state(self):
        self.rm.create_agent("a1", "tester")
        self.rm.start_agent("a1")
        self.rm.mark_error("a1", "test error")
        self.assertTrue(self.rm.start_agent("a1"))
        info = self.rm.get_agent("a1")
        self.assertEqual(info.state, AgentState.RUNNING)
        self.assertEqual(info.error, "")

    def test_start_clears_error(self):
        self.rm.create_agent("a1", "tester")
        self.rm.mark_error("a1", "broken")
        self.rm.start_agent("a1")
        self.assertEqual(self.rm.get_agent("a1").error, "")


class TestHeartbeat(unittest.TestCase):
    """Test heartbeat recording."""

    def setUp(self):
        self.rm = RuntimeManager()

    def test_heartbeat_running(self):
        self.rm.create_agent("a1", "tester")
        self.rm.start_agent("a1")
        time.sleep(0.01)
        old_hb = self.rm.get_agent("a1").last_heartbeat
        self.assertTrue(self.rm.heartbeat("a1"))
        new_hb = self.rm.get_agent("a1").last_heartbeat
        self.assertGreaterEqual(new_hb, old_hb)

    def test_heartbeat_stopped(self):
        self.rm.create_agent("a1", "tester")
        self.assertFalse(self.rm.heartbeat("a1"))

    def test_heartbeat_not_found(self):
        self.assertFalse(self.rm.heartbeat("missing"))


class TestMarkError(unittest.TestCase):
    """Test error marking."""

    def setUp(self):
        self.rm = RuntimeManager()

    def test_mark_error(self):
        self.rm.create_agent("a1", "tester")
        self.rm.start_agent("a1")
        self.assertTrue(self.rm.mark_error("a1", "connection lost"))
        info = self.rm.get_agent("a1")
        self.assertEqual(info.state, AgentState.ERROR)
        self.assertEqual(info.error, "connection lost")

    def test_mark_error_not_found(self):
        self.assertFalse(self.rm.mark_error("missing", "error"))


class TestQueries(unittest.TestCase):
    """Test agent queries."""

    def setUp(self):
        self.rm = RuntimeManager()
        self.rm.create_agent("a1", "role1")
        self.rm.create_agent("a2", "role2")
        self.rm.create_agent("a3", "role3")
        self.rm.start_agent("a1")
        self.rm.start_agent("a2")
        # a3 stays in CREATING

    def test_get_agent(self):
        info = self.rm.get_agent("a1")
        self.assertIsNotNone(info)
        self.assertEqual(info.agent_id, "a1")

    def test_get_agent_not_found(self):
        self.assertIsNone(self.rm.get_agent("missing"))

    def test_list_all_agents(self):
        agents = self.rm.list_agents()
        self.assertEqual(len(agents), 3)

    def test_list_agents_sorted(self):
        agents = self.rm.list_agents()
        ids = [a.agent_id for a in agents]
        self.assertEqual(ids, sorted(ids))

    def test_list_agents_by_state(self):
        running = self.rm.list_agents(state=AgentState.RUNNING)
        self.assertEqual(len(running), 2)
        creating = self.rm.list_agents(state=AgentState.CREATING)
        self.assertEqual(len(creating), 1)

    def test_count_running(self):
        self.assertEqual(self.rm.count_running(), 2)

    def test_count_slots_available(self):
        rm = RuntimeManager(max_agents=5)
        rm.create_agent("a1", "r1")
        rm.start_agent("a1")
        self.assertEqual(rm.count_slots_available(), 4)


class TestHealthMonitoring(unittest.TestCase):
    """Test health monitoring and stale cleanup."""

    def setUp(self):
        self.rm = RuntimeManager()

    def test_check_health_all_healthy(self):
        self.rm.create_agent("a1", "r1")
        self.rm.start_agent("a1")
        unhealthy = self.rm.check_health(timeout_seconds=120.0)
        self.assertEqual(len(unhealthy), 0)

    def test_check_health_stale_agent(self):
        self.rm.create_agent("a1", "r1")
        self.rm.start_agent("a1")
        # Manually set old heartbeat
        self.rm.get_agent("a1").last_heartbeat = time.time() - 200
        unhealthy = self.rm.check_health(timeout_seconds=120.0)
        self.assertEqual(len(unhealthy), 1)
        self.assertEqual(unhealthy[0].agent_id, "a1")

    def test_check_health_ignores_stopped(self):
        self.rm.create_agent("a1", "r1")
        # Not running — should not appear in unhealthy
        unhealthy = self.rm.check_health(timeout_seconds=1.0)
        self.assertEqual(len(unhealthy), 0)

    def test_cleanup_stale(self):
        self.rm.create_agent("a1", "r1")
        self.rm.start_agent("a1")
        self.rm.get_agent("a1").last_heartbeat = time.time() - 400
        marked = self.rm.cleanup_stale(timeout_seconds=300.0)
        self.assertEqual(marked, ["a1"])
        self.assertEqual(self.rm.get_agent("a1").state, AgentState.ERROR)
        self.assertIn("timeout", self.rm.get_agent("a1").error)

    def test_cleanup_stale_ignores_healthy(self):
        self.rm.create_agent("a1", "r1")
        self.rm.start_agent("a1")
        marked = self.rm.cleanup_stale(timeout_seconds=300.0)
        self.assertEqual(marked, [])


class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def test_status_empty(self):
        rm = RuntimeManager(max_agents=5)
        status = rm.status()
        self.assertEqual(status["max_agents"], 5)
        self.assertEqual(status["total_agents"], 0)
        self.assertEqual(status["running"], 0)
        self.assertEqual(status["slots_available"], 5)
        self.assertEqual(status["agents"], [])

    def test_status_with_agents(self):
        rm = RuntimeManager(max_agents=10)
        rm.create_agent("a1", "r1")
        rm.start_agent("a1")
        rm.create_agent("a2", "r2")
        status = rm.status()
        self.assertEqual(status["total_agents"], 2)
        self.assertEqual(status["running"], 1)
        self.assertEqual(status["slots_available"], 9)
        self.assertIn("running", status["agents_by_state"])
        self.assertEqual(len(status["agents"]), 2)

    def test_status_project_path(self):
        rm = RuntimeManager()
        status = rm.status()
        self.assertIn("project_path", status)


class TestThreadSafety(unittest.TestCase):
    """Test thread safety of RuntimeManager."""

    def test_concurrent_create(self):
        rm = RuntimeManager(max_agents=100)
        errors = []

        def create_agent(idx):
            try:
                rm.create_agent(f"agent_{idx}", f"role_{idx}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=create_agent, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(rm.list_agents()), 50)

    def test_concurrent_start_stop(self):
        rm = RuntimeManager(max_agents=20)
        for i in range(10):
            rm.create_agent(f"a{i}", f"r{i}")

        def start_stop(idx):
            rm.start_agent(f"a{idx}")
            time.sleep(0.001)
            rm.stop_agent(f"a{idx}")

        threads = [threading.Thread(target=start_stop, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should be stopped
        for i in range(10):
            info = rm.get_agent(f"a{i}")
            self.assertEqual(info.state, AgentState.STOPPED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
