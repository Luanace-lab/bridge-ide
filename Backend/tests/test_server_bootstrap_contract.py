from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server_bootstrap


class TestServerBootstrapContract(unittest.TestCase):
    def tearDown(self) -> None:
        import server as srv

        server_bootstrap.init(
            http_request_queue_size_getter=lambda: srv.HTTP_REQUEST_QUEUE_SIZE,
            http_server_instance_getter=lambda: srv._HTTP_SERVER_INSTANCE,
        )

    def test_init_applies_request_queue_size_to_server_class(self) -> None:
        server_bootstrap.init(
            http_request_queue_size_getter=lambda: 512,
            http_server_instance_getter=lambda: None,
        )

        self.assertEqual(server_bootstrap.BridgeThreadingHTTPServer.request_queue_size, 512)
        self.assertTrue(server_bootstrap.BridgeThreadingHTTPServer.daemon_threads)
        self.assertTrue(server_bootstrap.BridgeThreadingHTTPServer.allow_reuse_address)

    def test_signal_handler_exits_when_no_server_instance(self) -> None:
        server_bootstrap.init(
            http_request_queue_size_getter=lambda: 256,
            http_server_instance_getter=lambda: None,
        )

        with self.assertRaises(SystemExit):
            server_bootstrap._server_signal_handler(15, None)

    def test_signal_handler_spawns_shutdown_thread_for_live_server(self) -> None:
        class DummyServer:
            def __init__(self) -> None:
                self.shutdown_called = False

            def shutdown(self) -> None:
                self.shutdown_called = True

        dummy = DummyServer()
        created: list[dict[str, object]] = []

        class FakeThread:
            def __init__(self, *, target, daemon, name):
                created.append({"target": target, "daemon": daemon, "name": name, "started": False})

            def start(self) -> None:
                created[-1]["started"] = True
                created[-1]["target"]()

        server_bootstrap.init(
            http_request_queue_size_getter=lambda: 256,
            http_server_instance_getter=lambda: dummy,
        )

        with mock.patch("threading.Thread", FakeThread):
            server_bootstrap._server_signal_handler(15, None)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["name"], "server-sigterm-shutdown")
        self.assertIs(created[0]["daemon"], True)
        self.assertIs(created[0]["started"], True)
        self.assertTrue(dummy.shutdown_called)


if __name__ == "__main__":
    unittest.main()
