from __future__ import annotations

import os
import sys
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import daemons.maintenance as maint


class TestMaintenanceDaemonContract(unittest.TestCase):
    def setUp(self) -> None:
        self.scope_cleanup_calls = 0
        self.whiteboard_cleanup_calls = 0
        self.task_timeout_calls = 0
        maint.init(
            cleanup_expired_scope_locks=self._cleanup_expired_scope_locks,
            cleanup_expired_whiteboard=self._cleanup_expired_whiteboard,
            check_task_timeouts=self._check_task_timeouts,
        )

    def _cleanup_expired_scope_locks(self) -> int:
        self.scope_cleanup_calls += 1
        return 2

    def _cleanup_expired_whiteboard(self) -> int:
        self.whiteboard_cleanup_calls += 1
        return 3

    def _check_task_timeouts(self) -> None:
        self.task_timeout_calls += 1

    def test_maintenance_cleanup_tick_returns_both_counts(self) -> None:
        removed = maint._maintenance_cleanup_tick()
        self.assertEqual(removed, (2, 3))
        self.assertEqual(self.scope_cleanup_calls, 1)
        self.assertEqual(self.whiteboard_cleanup_calls, 1)

    def test_task_timeout_tick_calls_checker_once(self) -> None:
        maint._task_timeout_tick()
        self.assertEqual(self.task_timeout_calls, 1)
