from __future__ import annotations

import os
import signal
import sys
import unittest
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server_main


class _DummyServer:
    def __init__(self, raise_interrupt: bool = False) -> None:
        self.raise_interrupt = raise_interrupt
        self.serve_calls: list[float] = []
        self.closed = False

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        self.serve_calls.append(poll_interval)
        if self.raise_interrupt:
            raise KeyboardInterrupt

    def server_close(self) -> None:
        self.closed = True


class TestServerMainContract(unittest.TestCase):
    def tearDown(self) -> None:
        import server as srv

        server_main.init(
            build_session_name_map_fn=srv._build_session_name_map,
            load_history_fn=srv.load_history,
            load_tasks_from_disk_fn=srv._load_tasks_from_disk,
            load_escalation_state_from_disk_fn=srv._load_escalation_state_from_disk,
            load_scope_locks_from_disk_fn=srv._load_scope_locks_from_disk,
            load_whiteboard_from_disk_fn=srv._load_whiteboard_from_disk,
            event_bus_load_subscriptions_fn=srv.event_bus.load_subscriptions,
            event_bus_load_n8n_webhooks_fn=srv.event_bus.load_n8n_webhooks,
            load_workflow_registry_fn=srv._load_workflow_registry,
            restore_workflow_tools_from_registry_fn=srv._restore_workflow_tools_from_registry,
            tool_store_scan_fn=lambda: srv.tool_store.scan_tools(force=True),
            init_federation_runtime_fn=srv._init_federation_runtime,
            start_background_services_fn=srv.start_background_services,
            http_host_getter=lambda: srv.HTTP_HOST,
            port_getter=lambda: srv.PORT,
            strict_auth_getter=lambda: srv.BRIDGE_STRICT_AUTH,
            token_config_file_getter=lambda: srv._TOKEN_CONFIG_FILE,
            http_request_queue_size_getter=lambda: srv.HTTP_REQUEST_QUEUE_SIZE,
            ui_session_token_getter=lambda: srv._UI_SESSION_TOKEN,
            log_file_getter=lambda: srv.LOG_FILE,
            messages_getter=lambda: srv.MESSAGES,
            http_server_class_getter=lambda: srv.BridgeThreadingHTTPServer,
            bridge_handler_getter=lambda: srv.BridgeHandler,
            create_http_server_with_retry_fn=srv._create_http_server_with_retry,
            http_server_instance_setter=lambda instance: setattr(srv, "_HTTP_SERVER_INSTANCE", instance),
            server_signal_handler_fn=srv._server_signal_handler,
            stop_federation_runtime_fn=srv._stop_federation_runtime,
        )

    def test_preload_runtime_state_executes_expected_sequence(self) -> None:
        calls: list[str] = []

        def mark(name: str):
            return lambda: calls.append(name)

        server_main.init(
            build_session_name_map_fn=mark("session_map"),
            load_history_fn=mark("history"),
            load_tasks_from_disk_fn=mark("tasks"),
            load_escalation_state_from_disk_fn=mark("escalations"),
            load_scope_locks_from_disk_fn=mark("scope"),
            load_whiteboard_from_disk_fn=mark("whiteboard"),
            event_bus_load_subscriptions_fn=mark("subscriptions"),
            event_bus_load_n8n_webhooks_fn=mark("webhooks"),
            load_workflow_registry_fn=mark("workflow_registry"),
            restore_workflow_tools_from_registry_fn=mark("workflow_tools"),
            tool_store_scan_fn=mark("tool_scan"),
            init_federation_runtime_fn=mark("federation"),
            start_background_services_fn=mark("background"),
            http_host_getter=lambda: "127.0.0.1",
            port_getter=lambda: 9111,
            strict_auth_getter=lambda: True,
            token_config_file_getter=lambda: "tokens.json",
            http_request_queue_size_getter=lambda: 256,
            ui_session_token_getter=lambda: "ui-token",
            log_file_getter=lambda: "bridge.jsonl",
            messages_getter=lambda: [],
            http_server_class_getter=lambda: object,
            bridge_handler_getter=lambda: object,
            create_http_server_with_retry_fn=lambda *args, **kwargs: None,
            http_server_instance_setter=lambda _instance: None,
            server_signal_handler_fn=lambda _signum, _frame: None,
            stop_federation_runtime_fn=lambda: None,
        )

        server_main.preload_runtime_state()

        self.assertEqual(
            calls,
            [
                "session_map",
                "history",
                "tasks",
                "escalations",
                "scope",
                "whiteboard",
                "subscriptions",
                "webhooks",
                "workflow_registry",
                "workflow_tools",
                "tool_scan",
                "federation",
            ],
        )

    def test_serve_http_server_binds_and_closes_cleanly(self) -> None:
        created: list[tuple[object, tuple[str, int], object, int, float]] = []
        instances: list[object | None] = []
        dummy = _DummyServer()
        stop_federation = mock.Mock()

        def create_server(server_cls, address, handler_cls, *, attempts, delay_seconds):
            created.append((server_cls, address, handler_cls, attempts, delay_seconds))
            return dummy

        server_main.init(
            build_session_name_map_fn=lambda: None,
            load_history_fn=lambda: None,
            load_tasks_from_disk_fn=lambda: None,
            load_escalation_state_from_disk_fn=lambda: None,
            load_scope_locks_from_disk_fn=lambda: None,
            load_whiteboard_from_disk_fn=lambda: None,
            event_bus_load_subscriptions_fn=lambda: None,
            event_bus_load_n8n_webhooks_fn=lambda: None,
            load_workflow_registry_fn=lambda: None,
            restore_workflow_tools_from_registry_fn=lambda: None,
            tool_store_scan_fn=lambda: None,
            init_federation_runtime_fn=lambda: None,
            start_background_services_fn=lambda: None,
            http_host_getter=lambda: "127.0.0.1",
            port_getter=lambda: 9111,
            strict_auth_getter=lambda: False,
            token_config_file_getter=lambda: "/tmp/tokens.json",
            http_request_queue_size_getter=lambda: 256,
            ui_session_token_getter=lambda: "abcdef123456",
            log_file_getter=lambda: "/tmp/bridge.jsonl",
            messages_getter=lambda: [{"id": 1}],
            http_server_class_getter=lambda: "SERVERCLS",
            bridge_handler_getter=lambda: "HANDLERCLS",
            create_http_server_with_retry_fn=create_server,
            http_server_instance_setter=lambda instance: instances.append(instance),
            server_signal_handler_fn=lambda _signum, _frame: None,
            stop_federation_runtime_fn=stop_federation,
        )

        with mock.patch("signal.signal") as signal_mock:
            server_main.serve_http_server()

        self.assertEqual(created, [("SERVERCLS", ("127.0.0.1", 9111), "HANDLERCLS", 20, 0.5)])
        self.assertEqual(dummy.serve_calls, [0.5])
        self.assertTrue(dummy.closed)
        self.assertEqual(instances, [dummy, None])
        self.assertEqual(signal_mock.call_args[0][0], signal.SIGTERM)
        stop_federation.assert_called_once_with()

    def test_run_server_main_calls_preload_background_and_serve_in_order(self) -> None:
        calls: list[str] = []
        with mock.patch.object(server_main, "preload_runtime_state", side_effect=lambda: calls.append("preload")), \
             mock.patch.object(server_main, "_START_BACKGROUND_SERVICES", side_effect=lambda: calls.append("background")), \
             mock.patch.object(server_main, "serve_http_server", side_effect=lambda: calls.append("serve")):
            server_main.run_server_main()

        self.assertEqual(calls, ["preload", "background", "serve"])


if __name__ == "__main__":
    unittest.main()
