from __future__ import annotations

import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestFederationInboundGuards(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_append_message = srv.append_message
        self._orig_emit = srv.event_bus.emit_message_received
        self.calls: list[tuple[str, tuple, dict]] = []

        def _append_message(*args, **kwargs):
            self.calls.append(("append", args, kwargs))

        def _emit_message_received(*args, **kwargs):
            self.calls.append(("emit", args, kwargs))

        srv.append_message = _append_message
        srv.event_bus.emit_message_received = _emit_message_received

    def tearDown(self) -> None:
        srv.append_message = self._orig_append_message
        srv.event_bus.emit_message_received = self._orig_emit

    def test_drops_inbound_without_namespaced_sender(self) -> None:
        srv._handle_federation_inbound(
            {
                "from": "system",
                "to": "backend",
                "content": "spoof",
            }
        )
        self.assertEqual(self.calls, [])

    def test_accepts_namespaced_sender(self) -> None:
        srv._handle_federation_inbound(
            {
                "from": "agent_x@inst-jp",
                "to": "backend",
                "content": "hello",
                "meta": {"federation": {"direction": "inbound"}},
            }
        )

        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][0], "append")
        self.assertEqual(self.calls[0][1][0], "agent_x@inst-jp")
        self.assertEqual(self.calls[0][1][1], "backend")
        self.assertEqual(self.calls[1][0], "emit")


if __name__ == "__main__":
    unittest.main()
