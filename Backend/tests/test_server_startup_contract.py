from __future__ import annotations

import os
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server_startup


class FakeThread:
    created: list[dict[str, object]] = []

    def __init__(self, *, target, daemon, name):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        FakeThread.created.append(
            {"target": target, "daemon": daemon, "name": name, "thread": self}
        )

    def start(self) -> None:
        self.started = True


class TestServerStartupContract(unittest.TestCase):
    def tearDown(self) -> None:
        import server as srv

        server_startup.init(
            registered_agents=srv.REGISTERED_AGENTS,
            agent_busy=srv.AGENT_BUSY,
            agent_activities=srv.AGENT_ACTIVITIES,
            agent_state_lock=srv.AGENT_STATE_LOCK,
            tasks=srv.TASKS,
            task_lock=srv.TASK_LOCK,
            port_getter=lambda: srv.PORT,
            agent_is_live_fn=srv._agent_is_live,
            auto_gen_watcher_fn=srv._auto_gen_watcher,
            agent_health_checker_fn=srv._agent_health_checker,
            health_monitor_loop_fn=srv._health_monitor_loop,
            cli_output_monitor_loop_fn=srv._cli_output_monitor_loop,
            rate_limit_resume_loop_fn=srv._rate_limit_resume_loop,
            v3_cleanup_loop_fn=srv._v3_cleanup_loop,
            task_timeout_loop_fn=srv._task_timeout_loop,
            heartbeat_prompt_loop_fn=srv._heartbeat_prompt_loop,
            codex_hook_loop_fn=srv._codex_hook_loop,
            distillation_daemon_loop_fn=srv._distillation_daemon_loop,
            idle_agent_task_pusher_fn=srv._idle_agent_task_pusher,
            idle_watchdog_auto_assign_fn=srv._idle_watchdog_auto_assign,
            buddy_knowledge_loop_fn=srv._buddy_knowledge_loop,
            run_websocket_server_fn=srv.run_websocket_server,
            restart_wake_enabled_fn=srv._restart_wake_enabled,
            start_restart_wake_thread_fn=srv._start_restart_wake_thread,
            start_supervisor_daemon_fn=srv._start_supervisor_daemon,
        )

    def test_is_agent_idle_reports_offline_busy_and_idle_states(self) -> None:
        now = datetime.now(timezone.utc)
        server_startup.init(
            registered_agents={"busy": {}, "stale": {}, "active": {}, "idle": {}},
            agent_busy={"busy": True, "stale": False, "active": False, "idle": False},
            agent_activities={
                "stale": {"timestamp": (now - timedelta(minutes=3)).isoformat()},
                "active": {"timestamp": now.isoformat(), "action": "thinking"},
                "idle": {"timestamp": now.isoformat(), "action": "idle"},
            },
            agent_state_lock=threading.RLock(),
            tasks={},
            task_lock=threading.RLock(),
            port_getter=lambda: 9111,
            agent_is_live_fn=lambda _aid, stale_seconds=120.0, reg=None: True,
            auto_gen_watcher_fn=lambda: None,
            agent_health_checker_fn=lambda: None,
            health_monitor_loop_fn=lambda: None,
            cli_output_monitor_loop_fn=lambda: None,
            rate_limit_resume_loop_fn=lambda: None,
            v3_cleanup_loop_fn=lambda: None,
            task_timeout_loop_fn=lambda: None,
            heartbeat_prompt_loop_fn=lambda: None,
            codex_hook_loop_fn=lambda: None,
            distillation_daemon_loop_fn=lambda: None,
            idle_agent_task_pusher_fn=lambda: None,
            idle_watchdog_auto_assign_fn=lambda: None,
            buddy_knowledge_loop_fn=lambda: None,
            run_websocket_server_fn=lambda: None,
            restart_wake_enabled_fn=lambda: False,
            start_restart_wake_thread_fn=lambda: None,
            start_supervisor_daemon_fn=lambda: None,
        )

        self.assertIsNone(server_startup._is_agent_idle("offline"))
        self.assertFalse(server_startup._is_agent_idle("busy"))
        self.assertTrue(server_startup._is_agent_idle("stale"))
        self.assertFalse(server_startup._is_agent_idle("active"))
        self.assertTrue(server_startup._is_agent_idle("idle"))

    def test_automation_condition_context_snapshots_agents_and_tasks(self) -> None:
        now = datetime.now(timezone.utc)
        tasks = {"t1": {"task_id": "t1", "state": "created"}}
        server_startup.init(
            registered_agents={"alpha": {"status": "online"}},
            agent_busy={"alpha": False},
            agent_activities={"alpha": {"timestamp": (now - timedelta(seconds=30)).isoformat()}},
            agent_state_lock=threading.RLock(),
            tasks=tasks,
            task_lock=threading.RLock(),
            port_getter=lambda: 9111,
            agent_is_live_fn=lambda agent_id, stale_seconds=120.0, reg=None: agent_id == "alpha",
            auto_gen_watcher_fn=lambda: None,
            agent_health_checker_fn=lambda: None,
            health_monitor_loop_fn=lambda: None,
            cli_output_monitor_loop_fn=lambda: None,
            rate_limit_resume_loop_fn=lambda: None,
            v3_cleanup_loop_fn=lambda: None,
            task_timeout_loop_fn=lambda: None,
            heartbeat_prompt_loop_fn=lambda: None,
            codex_hook_loop_fn=lambda: None,
            distillation_daemon_loop_fn=lambda: None,
            idle_agent_task_pusher_fn=lambda: None,
            idle_watchdog_auto_assign_fn=lambda: None,
            buddy_knowledge_loop_fn=lambda: None,
            run_websocket_server_fn=lambda: None,
            restart_wake_enabled_fn=lambda: False,
            start_restart_wake_thread_fn=lambda: None,
            start_supervisor_daemon_fn=lambda: None,
        )

        ctx = server_startup._automation_condition_context()

        self.assertIn("alpha", ctx["agents"])
        self.assertTrue(ctx["agents"]["alpha"]["online"])
        self.assertFalse(ctx["agents"]["alpha"]["busy"])
        self.assertIsInstance(ctx["agents"]["alpha"]["last_activity_seconds"], float)
        self.assertEqual(ctx["tasks"], [{"task_id": "t1", "state": "created"}])
        tasks["t1"]["state"] = "done"
        self.assertEqual(ctx["tasks"][0]["state"], "created")

    def test_start_background_services_starts_expected_threads_and_scheduler(self) -> None:
        FakeThread.created.clear()
        start_restart_wake = mock.Mock()
        start_supervisor = mock.Mock()
        with mock.patch("threading.Thread", FakeThread), mock.patch("automation_engine.init_automations") as init_auto:
            server_startup.init(
                registered_agents={},
                agent_busy={},
                agent_activities={},
                agent_state_lock=threading.RLock(),
                tasks={},
                task_lock=threading.RLock(),
                port_getter=lambda: 9111,
                agent_is_live_fn=lambda _aid, stale_seconds=120.0, reg=None: True,
                auto_gen_watcher_fn=lambda: None,
                agent_health_checker_fn=lambda: None,
                health_monitor_loop_fn=lambda: None,
                cli_output_monitor_loop_fn=lambda: None,
                rate_limit_resume_loop_fn=lambda: None,
                v3_cleanup_loop_fn=lambda: None,
                task_timeout_loop_fn=lambda: None,
                heartbeat_prompt_loop_fn=lambda: None,
                codex_hook_loop_fn=lambda: None,
                distillation_daemon_loop_fn=lambda: None,
                idle_agent_task_pusher_fn=lambda: None,
                idle_watchdog_auto_assign_fn=lambda: None,
                buddy_knowledge_loop_fn=lambda: None,
                run_websocket_server_fn=lambda: None,
                restart_wake_enabled_fn=lambda: True,
                start_restart_wake_thread_fn=start_restart_wake,
                start_supervisor_daemon_fn=start_supervisor,
            )

            threads = server_startup.start_background_services()

        self.assertEqual(
            [entry["name"] for entry in FakeThread.created],
            [
                "auto-gen-watcher",
                "agent-health-checker",
                "health-monitor",
                "cli-output-monitor",
                "rate-limit-resume",
                "v3-cleanup",
                "task-timeout-checker",
                "heartbeat-prompter",
                "codex-cli-hook",
                "distillation-daemon",
                "task-pusher",
                "auto-assign",
                "buddy-knowledge",
                "websocket-server",
            ],
        )
        self.assertTrue(all(entry["daemon"] is True for entry in FakeThread.created))
        self.assertTrue(all(entry["thread"].started for entry in FakeThread.created))
        self.assertEqual(len(threads), 14)
        init_auto.assert_called_once()
        kwargs = init_auto.call_args.kwargs
        self.assertEqual(kwargs["server_port"], 9111)
        self.assertIs(kwargs["idle_check_callback"], server_startup._is_agent_idle)
        self.assertIs(
            kwargs["condition_context_callback"],
            server_startup._automation_condition_context,
        )
        start_restart_wake.assert_called_once_with()
        start_supervisor.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
