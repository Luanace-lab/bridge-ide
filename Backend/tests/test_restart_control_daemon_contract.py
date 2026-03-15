from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.restart_control as restart_control


class FakeTimer:
    def __init__(self, interval, target, args=None):
        self.interval = interval
        self.target = target
        self.args = tuple(args or ())
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


class TestRestartControlDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.append_message = mock.Mock()
        self.ws_broadcast = mock.Mock()
        self.interrupt_agent = mock.Mock(return_value={"ok": True})
        self.team_config: dict | None = {"agents": []}
        self.registered_agents: dict[str, dict] = {}
        self._tmpdir = tempfile.TemporaryDirectory()
        self.restart_marker = os.path.join(self._tmpdir.name, "restart_requested")
        self.warn_marker = os.path.join(self._tmpdir.name, "restart_warn")
        self._reset_state()

    def tearDown(self) -> None:
        restart_control._cancel_restart_timers()
        self._reset_state()
        self._tmpdir.cleanup()

        import server as srv

        restart_control.init(
            registered_agents_snapshot=srv._registered_agents_snapshot,
            agent_is_live=lambda agent_id: srv._agent_is_live(agent_id, stale_seconds=120.0),
            get_agent_engine=lambda agent_id: srv._get_agent_engine(agent_id),
            append_message=lambda *args, **kwargs: srv.append_message(*args, **kwargs),
            ws_broadcast=lambda event_type, payload: srv.ws_broadcast(event_type, payload),
            utc_now_iso=srv.utc_now_iso,
            interrupt_agent=lambda agent_id, engine: srv.interrupt_agent(agent_id, engine=engine),
            team_config_getter=lambda: srv.TEAM_CONFIG,
        )

    def _reset_state(self) -> None:
        restart_control.RESTART_STATE.clear()
        restart_control.RESTART_STATE.update({
            "phase": None,
            "started_at": None,
            "checkpoints": {},
            "warn_seconds": 60,
            "stop_seconds": 30,
            "reason": "",
            "restart_id": None,
            "agents_mode": "restart",
        })
        restart_control._RESTART_TIMERS.clear()

    def _init(self, **overrides: object) -> None:
        cfg = {
            "registered_agents_snapshot": lambda: self.registered_agents,
            "agent_is_live": lambda _agent_id: True,
            "get_agent_engine": lambda _agent_id: "claude",
            "append_message": self.append_message,
            "ws_broadcast": self.ws_broadcast,
            "utc_now_iso": lambda: "2026-03-14T00:00:00+00:00",
            "interrupt_agent": self.interrupt_agent,
            "team_config_getter": lambda: self.team_config,
        }
        cfg.update(overrides)
        restart_control.init(**cfg)

    def test_restart_warn_phase_sets_state_and_schedules_stop(self) -> None:
        self.registered_agents = {"alpha": {}}
        self._init()

        with mock.patch.object(restart_control, "_RESTART_WARN_MARKER", self.warn_marker), \
             mock.patch("threading.Timer", FakeTimer):
            restart_control._restart_warn_phase("maintenance", 5, 7)

        self.assertEqual(restart_control.RESTART_STATE["phase"], "warn")
        self.assertEqual(restart_control.RESTART_STATE["reason"], "maintenance")
        self.assertTrue(os.path.exists(self.warn_marker))
        self.append_message.assert_called()
        self.ws_broadcast.assert_called_once()
        timer = restart_control._RESTART_TIMERS["warn_to_stop"]
        self.assertEqual(timer.interval, 5)
        self.assertIs(timer.target, restart_control._restart_stop_phase)
        self.assertEqual(timer.args, (7,))
        self.assertTrue(timer.started)

    def test_check_all_checkpoints_saved_advances_to_stop(self) -> None:
        self.registered_agents = {"alpha": {}, "beta": {}}
        self._init()
        restart_control.RESTART_STATE["phase"] = "warn"
        restart_control.RESTART_STATE["stop_seconds"] = 11
        restart_control.RESTART_STATE["checkpoints"] = {
            "alpha": "2026-03-14T00:00:00+00:00",
            "beta": "2026-03-14T00:00:00+00:00",
        }

        with mock.patch.object(restart_control, "_restart_stop_phase") as stop_phase:
            advanced = restart_control._check_all_checkpoints_saved()

        self.assertTrue(advanced)
        stop_phase.assert_called_once_with(11)

    def test_restart_force_skips_warn_and_enters_stop(self) -> None:
        self._init()
        restart_control.RESTART_STATE["phase"] = "warn"
        fake_timer = FakeTimer(10, lambda: None)
        restart_control._RESTART_TIMERS["warn_to_stop"] = fake_timer

        with mock.patch.object(restart_control, "_restart_stop_phase") as stop_phase:
            result = restart_control._restart_force(9)

        self.assertEqual(result, {"ok": True, "phase": "stop", "seconds": 9})
        self.assertTrue(fake_timer.cancelled)
        stop_phase.assert_called_once_with(9)

    def test_restart_kill_phase_sets_restarting_and_uses_sigterm(self) -> None:
        self.registered_agents = {"alpha": {}}
        self.team_config = {"agents": [{"id": "alpha", "engine": "claude"}]}
        self._init()
        restart_control.RESTART_STATE["phase"] = "stop"
        restart_control.RESTART_STATE["reason"] = "slice29"

        with mock.patch.object(restart_control, "RESTART_MARKER", self.restart_marker), \
             mock.patch.object(restart_control, "_RESTART_WARN_MARKER", self.warn_marker), \
             mock.patch("os.kill") as kill_mock, \
             mock.patch("os.getpid", return_value=12345):
            restart_control._restart_kill_phase()

        self.assertEqual(restart_control.RESTART_STATE["phase"], "restarting")
        self.interrupt_agent.assert_called_once_with("alpha", engine="claude")
        kill_mock.assert_called_once_with(12345, restart_control.signal.SIGTERM)
        with open(self.restart_marker, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "slice29")

    def test_restart_cancel_clears_state_and_broadcasts(self) -> None:
        self._init()
        restart_control.RESTART_STATE["phase"] = "warn"
        restart_control.RESTART_STATE["restart_id"] = "r1"
        restart_control.RESTART_STATE["checkpoints"] = {"alpha": "ts"}
        restart_control.RESTART_STATE["reason"] = "maintenance"
        fake_timer = FakeTimer(5, lambda: None)
        restart_control._RESTART_TIMERS["warn_to_stop"] = fake_timer
        with open(self.warn_marker, "w", encoding="utf-8") as handle:
            handle.write("5")

        with mock.patch.object(restart_control, "_RESTART_WARN_MARKER", self.warn_marker):
            result = restart_control._restart_cancel()

        self.assertEqual(result, {"ok": True, "cancelled_phase": "warn"})
        self.assertEqual(restart_control.RESTART_STATE["phase"], None)
        self.assertTrue(fake_timer.cancelled)
        self.append_message.assert_called_once()
        self.ws_broadcast.assert_called_once_with("restart_cancel", {"cancelled_phase": "warn"})
        self.assertFalse(os.path.exists(self.warn_marker))


if __name__ == "__main__":
    unittest.main()
