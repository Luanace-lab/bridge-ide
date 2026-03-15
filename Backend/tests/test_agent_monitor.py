"""
Tests for agent_monitor.py — Agent Monitoring and Metrics Aggregation

Tests cover:
  - AgentMetrics (tokens, cost, uptime, to_dict)
  - Alert dataclass
  - FleetSummary dataclass
  - Agent registration/unregistration
  - Metric recording (tokens, messages, errors, tasks, heartbeat, memory)
  - Queries (get_metrics, cost, totals)
  - Health checks (stale, disconnected, memory)
  - Alert management (get, filter, clear)
  - Fleet summary aggregation
  - Snapshots
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

from agent_monitor import (
    AgentMetrics,
    AgentMonitor,
    Alert,
    FleetSummary,
    MODEL_PRICING,
)


class TestAgentMetrics(unittest.TestCase):
    """Test AgentMetrics dataclass."""

    def test_defaults(self):
        m = AgentMetrics(agent_id="a1")
        self.assertEqual(m.tokens_input, 0)
        self.assertEqual(m.tokens_output, 0)
        self.assertEqual(m.total_tokens, 0)
        self.assertEqual(m.cost_usd, 0.0)

    def test_total_tokens(self):
        m = AgentMetrics(agent_id="a1", tokens_input=100, tokens_output=50)
        self.assertEqual(m.total_tokens, 150)

    def test_cost_calculation(self):
        m = AgentMetrics(
            agent_id="a1", model="claude-sonnet-4",
            tokens_input=1_000_000, tokens_output=500_000,
        )
        # input: 1M * $3/M = $3.00, output: 0.5M * $15/M = $7.50
        self.assertAlmostEqual(m.cost_usd, 10.5, places=2)

    def test_cost_unknown_model(self):
        m = AgentMetrics(agent_id="a1", model="unknown-model", tokens_input=1000)
        self.assertEqual(m.cost_usd, 0.0)

    def test_uptime(self):
        m = AgentMetrics(agent_id="a1", started_at=time.time() - 10)
        self.assertGreaterEqual(m.uptime_seconds, 9.0)
        self.assertLessEqual(m.uptime_seconds, 12.0)

    def test_uptime_not_started(self):
        m = AgentMetrics(agent_id="a1")
        self.assertEqual(m.uptime_seconds, 0.0)

    def test_to_dict(self):
        m = AgentMetrics(agent_id="a1", model="gpt-4o", tokens_input=100)
        d = m.to_dict()
        self.assertEqual(d["agent_id"], "a1")
        self.assertEqual(d["model"], "gpt-4o")
        self.assertEqual(d["tokens_input"], 100)
        self.assertIn("cost_usd", d)
        self.assertIn("uptime_seconds", d)


class TestAlert(unittest.TestCase):
    """Test Alert dataclass."""

    def test_create(self):
        a = Alert(agent_id="a1", level="warning", category="heartbeat", message="stale")
        self.assertEqual(a.agent_id, "a1")
        self.assertGreater(a.timestamp, 0)

    def test_to_dict(self):
        a = Alert(agent_id="a1", level="critical", category="memory", message="over limit")
        d = a.to_dict()
        self.assertEqual(d["level"], "critical")
        self.assertEqual(d["category"], "memory")


class TestFleetSummary(unittest.TestCase):
    """Test FleetSummary dataclass."""

    def test_defaults(self):
        f = FleetSummary()
        self.assertEqual(f.total_agents, 0)
        self.assertEqual(f.total_cost_usd, 0.0)

    def test_to_dict(self):
        f = FleetSummary(total_agents=5, running_agents=3, total_tokens=1000)
        d = f.to_dict()
        self.assertEqual(d["total_agents"], 5)
        self.assertEqual(d["running_agents"], 3)
        self.assertEqual(d["total_tokens"], 1000)


class TestRegistration(unittest.TestCase):
    """Test agent registration."""

    def setUp(self):
        self.monitor = AgentMonitor()

    def test_register(self):
        m = self.monitor.register_agent("a1", model="claude-sonnet-4")
        self.assertEqual(m.agent_id, "a1")
        self.assertEqual(m.model, "claude-sonnet-4")
        self.assertGreater(m.started_at, 0)

    def test_register_duplicate_returns_existing(self):
        m1 = self.monitor.register_agent("a1")
        m2 = self.monitor.register_agent("a1")
        self.assertIs(m1, m2)

    def test_unregister(self):
        self.monitor.register_agent("a1")
        self.assertTrue(self.monitor.unregister_agent("a1"))
        self.assertIsNone(self.monitor.get_metrics("a1"))

    def test_unregister_not_found(self):
        self.assertFalse(self.monitor.unregister_agent("missing"))


class TestMetricRecording(unittest.TestCase):
    """Test metric recording."""

    def setUp(self):
        self.monitor = AgentMonitor()
        self.monitor.register_agent("a1", model="claude-sonnet-4")

    def test_record_tokens(self):
        self.monitor.record_tokens("a1", input_tokens=100, output_tokens=50)
        m = self.monitor.get_metrics("a1")
        self.assertEqual(m.tokens_input, 100)
        self.assertEqual(m.tokens_output, 50)

    def test_record_tokens_cumulative(self):
        self.monitor.record_tokens("a1", input_tokens=100)
        self.monitor.record_tokens("a1", input_tokens=200)
        m = self.monitor.get_metrics("a1")
        self.assertEqual(m.tokens_input, 300)

    def test_record_tokens_unknown_agent(self):
        # Should not crash
        self.monitor.record_tokens("missing", input_tokens=100)

    def test_record_message_sent(self):
        self.monitor.record_message_sent("a1")
        self.monitor.record_message_sent("a1")
        m = self.monitor.get_metrics("a1")
        self.assertEqual(m.total_messages_sent, 2)

    def test_record_message_received(self):
        self.monitor.record_message_received("a1")
        m = self.monitor.get_metrics("a1")
        self.assertEqual(m.total_messages_received, 1)

    def test_record_error(self):
        self.monitor.record_error("a1")
        m = self.monitor.get_metrics("a1")
        self.assertEqual(m.total_errors, 1)

    def test_record_task_completed(self):
        self.monitor.record_task_completed("a1")
        self.monitor.record_task_completed("a1")
        m = self.monitor.get_metrics("a1")
        self.assertEqual(m.total_tasks_completed, 2)

    def test_record_heartbeat(self):
        old_hb = self.monitor.get_metrics("a1").last_heartbeat
        time.sleep(0.01)
        self.monitor.record_heartbeat("a1")
        new_hb = self.monitor.get_metrics("a1").last_heartbeat
        self.assertGreater(new_hb, old_hb)

    def test_record_memory(self):
        self.monitor.record_memory("a1", 1024 * 1024 * 50)  # 50MB
        m = self.monitor.get_metrics("a1")
        self.assertEqual(m.memory_bytes, 1024 * 1024 * 50)


class TestQueries(unittest.TestCase):
    """Test query methods."""

    def setUp(self):
        self.monitor = AgentMonitor()
        self.monitor.register_agent("a1", model="claude-sonnet-4")
        self.monitor.register_agent("a2", model="gpt-4o")
        self.monitor.record_tokens("a1", input_tokens=1000, output_tokens=500)
        self.monitor.record_tokens("a2", input_tokens=2000, output_tokens=1000)

    def test_get_metrics(self):
        m = self.monitor.get_metrics("a1")
        self.assertEqual(m.tokens_input, 1000)

    def test_get_metrics_not_found(self):
        self.assertIsNone(self.monitor.get_metrics("missing"))

    def test_get_all_metrics(self):
        all_m = self.monitor.get_all_metrics()
        self.assertEqual(len(all_m), 2)

    def test_get_cost(self):
        cost = self.monitor.get_cost("a1")
        self.assertGreater(cost, 0)

    def test_get_total_cost(self):
        total = self.monitor.get_total_cost()
        self.assertGreater(total, 0)
        # Should be sum of both agents
        self.assertAlmostEqual(
            total,
            self.monitor.get_cost("a1") + self.monitor.get_cost("a2"),
            places=6,
        )

    def test_get_total_tokens(self):
        self.assertEqual(self.monitor.get_total_tokens(), 4500)


class TestHealthChecks(unittest.TestCase):
    """Test health check alerts."""

    def setUp(self):
        self.monitor = AgentMonitor(
            stale_threshold=2.0,
            disconnect_threshold=5.0,
        )

    def test_healthy_no_alerts(self):
        self.monitor.register_agent("a1")
        alerts = self.monitor.check_health()
        self.assertEqual(len(alerts), 0)

    def test_stale_alert(self):
        self.monitor.register_agent("a1")
        self.monitor.get_metrics("a1").last_heartbeat = time.time() - 3.0
        alerts = self.monitor.check_health()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, "warning")
        self.assertEqual(alerts[0].category, "heartbeat")

    def test_disconnect_alert(self):
        self.monitor.register_agent("a1")
        self.monitor.get_metrics("a1").last_heartbeat = time.time() - 10.0
        alerts = self.monitor.check_health()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, "critical")

    def test_memory_alert(self):
        self.monitor.register_agent("a1")
        self.monitor.record_memory("a1", 200 * 1024 * 1024)  # 200MB > 100MB limit
        alerts = self.monitor.check_health()
        memory_alerts = [a for a in alerts if a.category == "memory"]
        self.assertEqual(len(memory_alerts), 1)


class TestAlertManagement(unittest.TestCase):
    """Test alert querying and management."""

    def setUp(self):
        self.monitor = AgentMonitor(stale_threshold=1.0, disconnect_threshold=3.0)
        self.monitor.register_agent("a1")
        self.monitor.register_agent("a2")
        # Make a1 stale, a2 disconnected
        self.monitor.get_metrics("a1").last_heartbeat = time.time() - 2.0
        self.monitor.get_metrics("a2").last_heartbeat = time.time() - 5.0
        self.monitor.check_health()

    def test_get_all_alerts(self):
        alerts = self.monitor.get_alerts()
        self.assertEqual(len(alerts), 2)

    def test_get_alerts_by_agent(self):
        alerts = self.monitor.get_alerts(agent_id="a1")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].agent_id, "a1")

    def test_get_alerts_by_level(self):
        critical = self.monitor.get_alerts(level="critical")
        self.assertEqual(len(critical), 1)
        self.assertEqual(critical[0].agent_id, "a2")

    def test_get_alerts_limit(self):
        alerts = self.monitor.get_alerts(limit=1)
        self.assertEqual(len(alerts), 1)

    def test_clear_alerts(self):
        count = self.monitor.clear_alerts()
        self.assertEqual(count, 2)
        self.assertEqual(len(self.monitor.get_alerts()), 0)


class TestFleetSummaryAggregation(unittest.TestCase):
    """Test fleet-wide summary."""

    def setUp(self):
        self.monitor = AgentMonitor(stale_threshold=2.0, disconnect_threshold=5.0)
        self.monitor.register_agent("a1", model="claude-sonnet-4")
        self.monitor.register_agent("a2", model="gpt-4o")
        self.monitor.record_tokens("a1", input_tokens=1000, output_tokens=500)
        self.monitor.record_tokens("a2", input_tokens=2000, output_tokens=1000)
        self.monitor.record_message_sent("a1")
        self.monitor.record_message_received("a2")
        self.monitor.record_task_completed("a1")

    def test_fleet_counts(self):
        summary = self.monitor.fleet_summary()
        self.assertEqual(summary.total_agents, 2)
        self.assertEqual(summary.running_agents, 2)

    def test_fleet_tokens(self):
        summary = self.monitor.fleet_summary()
        self.assertEqual(summary.total_tokens, 4500)

    def test_fleet_cost(self):
        summary = self.monitor.fleet_summary()
        self.assertGreater(summary.total_cost_usd, 0)

    def test_fleet_messages(self):
        summary = self.monitor.fleet_summary()
        self.assertEqual(summary.total_messages, 2)

    def test_fleet_with_stale(self):
        self.monitor.get_metrics("a2").last_heartbeat = time.time() - 3.0
        summary = self.monitor.fleet_summary()
        self.assertEqual(summary.stale_agents, 1)
        self.assertEqual(summary.running_agents, 1)

    def test_fleet_to_dict(self):
        d = self.monitor.fleet_summary().to_dict()
        self.assertIn("total_agents", d)
        self.assertIn("total_cost_usd", d)


class TestSnapshots(unittest.TestCase):
    """Test metric snapshots."""

    def setUp(self):
        self.monitor = AgentMonitor()
        self.monitor.register_agent("a1")

    def test_take_snapshot(self):
        snap = self.monitor.take_snapshot()
        self.assertIn("timestamp", snap)
        self.assertIn("agents", snap)
        self.assertIn("fleet", snap)
        self.assertIn("a1", snap["agents"])

    def test_snapshot_stored(self):
        self.monitor.take_snapshot()
        self.monitor.take_snapshot()
        snaps = self.monitor.get_snapshots()
        self.assertEqual(len(snaps), 2)

    def test_snapshot_limit(self):
        snaps = self.monitor.get_snapshots(limit=1)
        self.assertLessEqual(len(snaps), 1)


class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def test_status(self):
        monitor = AgentMonitor()
        monitor.register_agent("a1", model="claude-sonnet-4")
        monitor.record_tokens("a1", input_tokens=1000)
        s = monitor.status()
        self.assertEqual(s["total_agents_monitored"], 1)
        self.assertIn("fleet", s)
        self.assertIn("agents", s)


class TestModelPricing(unittest.TestCase):
    """Test model pricing table."""

    def test_known_models(self):
        self.assertIn("claude-opus-4", MODEL_PRICING)
        self.assertIn("claude-sonnet-4", MODEL_PRICING)
        self.assertIn("gpt-4o", MODEL_PRICING)
        self.assertIn("gemini-2.0-flash", MODEL_PRICING)

    def test_pricing_structure(self):
        for model, pricing in MODEL_PRICING.items():
            self.assertIn("input", pricing, f"Missing input price for {model}")
            self.assertIn("output", pricing, f"Missing output price for {model}")
            self.assertGreater(pricing["input"], 0, f"Zero input price for {model}")
            self.assertGreater(pricing["output"], 0, f"Zero output price for {model}")


class TestThreadSafety(unittest.TestCase):
    """Test thread safety."""

    def test_concurrent_recording(self):
        monitor = AgentMonitor()
        for i in range(10):
            monitor.register_agent(f"a{i}")

        errors = []

        def record(agent_id):
            try:
                for _ in range(50):
                    monitor.record_tokens(agent_id, input_tokens=10, output_tokens=5)
                    monitor.record_message_sent(agent_id)
                    monitor.record_heartbeat(agent_id)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=record, args=(f"a{i}",))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        # Each agent: 50 iterations * 10 input = 500 input tokens
        for i in range(10):
            m = monitor.get_metrics(f"a{i}")
            self.assertEqual(m.tokens_input, 500)
            self.assertEqual(m.total_messages_sent, 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
