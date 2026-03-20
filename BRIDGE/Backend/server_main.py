from __future__ import annotations

import os
import signal
from typing import Any, Callable


_BUILD_SESSION_NAME_MAP: Callable[[], None] = lambda: None
_LOAD_HISTORY: Callable[[], None] = lambda: None
_LOAD_TASKS_FROM_DISK: Callable[[], None] = lambda: None
_LOAD_ESCALATION_STATE_FROM_DISK: Callable[[], None] = lambda: None
_LOAD_SCOPE_LOCKS_FROM_DISK: Callable[[], None] = lambda: None
_LOAD_WHITEBOARD_FROM_DISK: Callable[[], None] = lambda: None
_EVENT_BUS_LOAD_SUBSCRIPTIONS: Callable[[], None] = lambda: None
_EVENT_BUS_LOAD_N8N_WEBHOOKS: Callable[[], None] = lambda: None
_LOAD_WORKFLOW_REGISTRY: Callable[[], None] = lambda: None
_RESTORE_WORKFLOW_TOOLS_FROM_REGISTRY: Callable[[], None] = lambda: None
_TOOL_STORE_SCAN: Callable[[], None] = lambda: None
_INIT_FEDERATION_RUNTIME: Callable[[], None] = lambda: None
_START_BACKGROUND_SERVICES: Callable[[], None] = lambda: None
_HTTP_HOST_GETTER: Callable[[], str] = lambda: "127.0.0.1"
_PORT_GETTER: Callable[[], int] = lambda: 9111
_STRICT_AUTH_GETTER: Callable[[], bool] = lambda: False
_TOKEN_CONFIG_FILE_GETTER: Callable[[], str] = lambda: ""
_HTTP_REQUEST_QUEUE_SIZE_GETTER: Callable[[], int] = lambda: 256
_UI_SESSION_TOKEN_GETTER: Callable[[], str] = lambda: ""
_LOG_FILE_GETTER: Callable[[], str] = lambda: ""
_MESSAGES_GETTER: Callable[[], list[dict[str, Any]]] = lambda: []
_HTTP_SERVER_CLASS_GETTER: Callable[[], Any] = lambda: None
_BRIDGE_HANDLER_GETTER: Callable[[], Any] = lambda: None
_CREATE_HTTP_SERVER_WITH_RETRY: Callable[..., Any] = lambda *args, **kwargs: None
_HTTP_SERVER_INSTANCE_SETTER: Callable[[Any], None] = lambda _instance: None
_SERVER_SIGNAL_HANDLER: Callable[[int, Any], None] = lambda _signum, _frame: None
_STOP_FEDERATION_RUNTIME: Callable[[], None] = lambda: None


def init(
    *,
    build_session_name_map_fn: Callable[[], None],
    load_history_fn: Callable[[], None],
    load_tasks_from_disk_fn: Callable[[], None],
    load_escalation_state_from_disk_fn: Callable[[], None],
    load_scope_locks_from_disk_fn: Callable[[], None],
    load_whiteboard_from_disk_fn: Callable[[], None],
    event_bus_load_subscriptions_fn: Callable[[], None],
    event_bus_load_n8n_webhooks_fn: Callable[[], None],
    load_workflow_registry_fn: Callable[[], None],
    restore_workflow_tools_from_registry_fn: Callable[[], None],
    tool_store_scan_fn: Callable[[], None],
    init_federation_runtime_fn: Callable[[], None],
    start_background_services_fn: Callable[[], None],
    http_host_getter: Callable[[], str],
    port_getter: Callable[[], int],
    strict_auth_getter: Callable[[], bool],
    token_config_file_getter: Callable[[], str],
    http_request_queue_size_getter: Callable[[], int],
    ui_session_token_getter: Callable[[], str],
    log_file_getter: Callable[[], str],
    messages_getter: Callable[[], list[dict[str, Any]]],
    http_server_class_getter: Callable[[], Any],
    bridge_handler_getter: Callable[[], Any],
    create_http_server_with_retry_fn: Callable[..., Any],
    http_server_instance_setter: Callable[[Any], None],
    server_signal_handler_fn: Callable[[int, Any], None],
    stop_federation_runtime_fn: Callable[[], None],
) -> None:
    global _BUILD_SESSION_NAME_MAP, _LOAD_HISTORY, _LOAD_TASKS_FROM_DISK
    global _LOAD_ESCALATION_STATE_FROM_DISK, _LOAD_SCOPE_LOCKS_FROM_DISK
    global _LOAD_WHITEBOARD_FROM_DISK, _EVENT_BUS_LOAD_SUBSCRIPTIONS
    global _EVENT_BUS_LOAD_N8N_WEBHOOKS, _LOAD_WORKFLOW_REGISTRY
    global _RESTORE_WORKFLOW_TOOLS_FROM_REGISTRY, _TOOL_STORE_SCAN
    global _INIT_FEDERATION_RUNTIME, _START_BACKGROUND_SERVICES
    global _HTTP_HOST_GETTER, _PORT_GETTER, _STRICT_AUTH_GETTER
    global _TOKEN_CONFIG_FILE_GETTER, _HTTP_REQUEST_QUEUE_SIZE_GETTER
    global _UI_SESSION_TOKEN_GETTER, _LOG_FILE_GETTER, _MESSAGES_GETTER
    global _HTTP_SERVER_CLASS_GETTER, _BRIDGE_HANDLER_GETTER
    global _CREATE_HTTP_SERVER_WITH_RETRY, _HTTP_SERVER_INSTANCE_SETTER
    global _SERVER_SIGNAL_HANDLER, _STOP_FEDERATION_RUNTIME

    _BUILD_SESSION_NAME_MAP = build_session_name_map_fn
    _LOAD_HISTORY = load_history_fn
    _LOAD_TASKS_FROM_DISK = load_tasks_from_disk_fn
    _LOAD_ESCALATION_STATE_FROM_DISK = load_escalation_state_from_disk_fn
    _LOAD_SCOPE_LOCKS_FROM_DISK = load_scope_locks_from_disk_fn
    _LOAD_WHITEBOARD_FROM_DISK = load_whiteboard_from_disk_fn
    _EVENT_BUS_LOAD_SUBSCRIPTIONS = event_bus_load_subscriptions_fn
    _EVENT_BUS_LOAD_N8N_WEBHOOKS = event_bus_load_n8n_webhooks_fn
    _LOAD_WORKFLOW_REGISTRY = load_workflow_registry_fn
    _RESTORE_WORKFLOW_TOOLS_FROM_REGISTRY = restore_workflow_tools_from_registry_fn
    _TOOL_STORE_SCAN = tool_store_scan_fn
    _INIT_FEDERATION_RUNTIME = init_federation_runtime_fn
    _START_BACKGROUND_SERVICES = start_background_services_fn
    _HTTP_HOST_GETTER = http_host_getter
    _PORT_GETTER = port_getter
    _STRICT_AUTH_GETTER = strict_auth_getter
    _TOKEN_CONFIG_FILE_GETTER = token_config_file_getter
    _HTTP_REQUEST_QUEUE_SIZE_GETTER = http_request_queue_size_getter
    _UI_SESSION_TOKEN_GETTER = ui_session_token_getter
    _LOG_FILE_GETTER = log_file_getter
    _MESSAGES_GETTER = messages_getter
    _HTTP_SERVER_CLASS_GETTER = http_server_class_getter
    _BRIDGE_HANDLER_GETTER = bridge_handler_getter
    _CREATE_HTTP_SERVER_WITH_RETRY = create_http_server_with_retry_fn
    _HTTP_SERVER_INSTANCE_SETTER = http_server_instance_setter
    _SERVER_SIGNAL_HANDLER = server_signal_handler_fn
    _STOP_FEDERATION_RUNTIME = stop_federation_runtime_fn


def preload_runtime_state() -> None:
    _BUILD_SESSION_NAME_MAP()
    _LOAD_HISTORY()
    _LOAD_TASKS_FROM_DISK()
    _LOAD_ESCALATION_STATE_FROM_DISK()
    _LOAD_SCOPE_LOCKS_FROM_DISK()
    _LOAD_WHITEBOARD_FROM_DISK()
    _EVENT_BUS_LOAD_SUBSCRIPTIONS()
    _EVENT_BUS_LOAD_N8N_WEBHOOKS()
    _LOAD_WORKFLOW_REGISTRY()
    _RESTORE_WORKFLOW_TOOLS_FROM_REGISTRY()
    _TOOL_STORE_SCAN()
    _INIT_FEDERATION_RUNTIME()


def serve_http_server() -> None:
    bind_retry_attempts = max(1, int(os.environ.get("BRIDGE_HTTP_BIND_RETRIES", "20")))
    bind_retry_delay = max(0.05, float(os.environ.get("BRIDGE_HTTP_BIND_RETRY_DELAY", "0.5")))
    server = _CREATE_HTTP_SERVER_WITH_RETRY(
        _HTTP_SERVER_CLASS_GETTER(),
        (_HTTP_HOST_GETTER(), _PORT_GETTER()),
        _BRIDGE_HANDLER_GETTER(),
        attempts=bind_retry_attempts,
        delay_seconds=bind_retry_delay,
    )
    _HTTP_SERVER_INSTANCE_SETTER(server)
    signal.signal(signal.SIGTERM, _SERVER_SIGNAL_HANDLER)
    print(f"Bridge server listening on http://{_HTTP_HOST_GETTER()}:{_PORT_GETTER()}")
    print(f"Strict auth mode: {_STRICT_AUTH_GETTER()}")
    if not _STRICT_AUTH_GETTER():
        print("  WARNING: Auth enforcement is OFF. Set BRIDGE_STRICT_AUTH=true for production.")
    print(f"Auth tokens: {_TOKEN_CONFIG_FILE_GETTER()}")
    print(f"HTTP request queue size: {_HTTP_REQUEST_QUEUE_SIZE_GETTER()}")
    print(f"UI session token: {_UI_SESSION_TOKEN_GETTER()[:8]}... (injected into HTML)")
    print(f"Message log: {_LOG_FILE_GETTER()}")
    print(f"Loaded messages: {len(_MESSAGES_GETTER())}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _STOP_FEDERATION_RUNTIME()
        _HTTP_SERVER_INSTANCE_SETTER(None)
        server.server_close()
        print("Bridge server stopped.")


def run_server_main() -> None:
    preload_runtime_state()
    _START_BACKGROUND_SERVICES()
    serve_http_server()
