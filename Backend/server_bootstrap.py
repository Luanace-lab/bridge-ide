from __future__ import annotations

import errno
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any, Callable

_http_server_instance_getter: Callable[[], ThreadingHTTPServer | None] | None = None


class BridgeThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 256


def init(
    *,
    http_request_queue_size_getter: Callable[[], int],
    http_server_instance_getter: Callable[[], ThreadingHTTPServer | None],
) -> None:
    global _http_server_instance_getter

    BridgeThreadingHTTPServer.request_queue_size = int(http_request_queue_size_getter())
    _http_server_instance_getter = http_server_instance_getter


def _is_address_in_use(exc: OSError) -> bool:
    if getattr(exc, "errno", None) == errno.EADDRINUSE:
        return True
    return "Address already in use" in str(exc)


def _create_http_server_with_retry(
    server_cls: Callable[[tuple[str, int], type[Any]], ThreadingHTTPServer],
    bind_addr: tuple[str, int],
    handler_cls: type[Any],
    *,
    attempts: int = 20,
    delay_seconds: float = 0.5,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ThreadingHTTPServer:
    bounded_attempts = max(1, int(attempts))
    bounded_delay = max(0.05, float(delay_seconds))
    host, port = bind_addr
    for attempt in range(1, bounded_attempts + 1):
        try:
            return server_cls(bind_addr, handler_cls)
        except OSError as exc:
            if not _is_address_in_use(exc) or attempt >= bounded_attempts:
                raise
            print(
                f"[server] HTTP bind {host}:{port} still busy "
                f"(attempt {attempt}/{bounded_attempts}); retrying in {bounded_delay:.2f}s..."
            )
            sleep_fn(bounded_delay)
    raise RuntimeError("unreachable")


def _server_signal_handler(signum: int, _frame: Any) -> None:
    if _http_server_instance_getter is None:
        raise RuntimeError("server_bootstrap not initialized")

    server_ref = _http_server_instance_getter()
    print(f"[server] Received signal {signum}. Starting graceful shutdown...")
    if server_ref is None:
        raise SystemExit(0)

    def _shutdown_server() -> None:
        try:
            server_ref.shutdown()
        except Exception as exc:  # noqa: BLE001
            print(f"[server] Graceful shutdown failed: {exc}")

    threading.Thread(target=_shutdown_server, daemon=True, name="server-sigterm-shutdown").start()
