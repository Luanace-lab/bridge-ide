"""Federation runtime helpers extracted from server.py (Slice 13).

This module owns:
- federation runtime init/stop/health/outbound helpers
- inbound federation message projection to the local message stream
- federation runtime config constants and runtime state

Anti-circular-import strategy:
  All cross-domain callbacks are injected via init().
  This module NEVER imports from server.
  Direct imports only from: federation_runtime.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

try:
    from federation_runtime import FederationRuntime, is_federated_target

    HAS_FEDERATION_RUNTIME = True
except Exception as _federation_import_exc:  # noqa: BLE001
    FederationRuntime = None  # type: ignore[assignment]
    HAS_FEDERATION_RUNTIME = False
    _FEDERATION_IMPORT_ERROR = str(_federation_import_exc)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    lowered = str(raw).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


BRIDGE_FEDERATION_ENABLED = _env_flag("BRIDGE_FEDERATION_ENABLED", True)
BRIDGE_FEDERATION_DIR = os.path.expanduser(os.environ.get("BRIDGE_FEDERATION_DIR", "~/.bridge/federation"))
BRIDGE_FEDERATION_PEERS_FILE = os.path.expanduser(
    os.environ.get("BRIDGE_FEDERATION_PEERS_FILE", "~/.bridge/federation/peers.json")
)
BRIDGE_FEDERATION_RELAY_URL = os.environ.get("BRIDGE_FEDERATION_RELAY_URL", "").strip()

_FEDERATION_RUNTIME_LOCK = threading.RLock()
_FEDERATION_RUNTIME: Any = None
_FEDERATION_RUNTIME_ERROR = ""

_append_message: Callable[..., Any] | None = None
_emit_message_received: Callable[..., Any] | None = None


def init(
    *,
    append_message_fn: Callable[..., Any],
    emit_message_received_fn: Callable[..., Any],
) -> None:
    global _append_message, _emit_message_received

    _append_message = append_message_fn
    _emit_message_received = emit_message_received_fn


def _is_federation_target(recipient: str) -> bool:
    if not HAS_FEDERATION_RUNTIME:
        return False
    try:
        return bool(is_federated_target(recipient))
    except Exception:
        return False


def _federation_runtime_health() -> dict[str, Any]:
    if not BRIDGE_FEDERATION_ENABLED:
        return {"enabled": False, "reason": "disabled by config"}
    if not HAS_FEDERATION_RUNTIME:
        return {
            "enabled": False,
            "reason": globals().get("_FEDERATION_IMPORT_ERROR", "federation runtime unavailable"),
        }

    with _FEDERATION_RUNTIME_LOCK:
        runtime = _FEDERATION_RUNTIME
        err = _FEDERATION_RUNTIME_ERROR
    if runtime is None:
        if err:
            return {"enabled": False, "reason": err}
        return {"enabled": False, "reason": "not initialized"}
    return runtime.health()


def _handle_federation_inbound(message: dict[str, Any]) -> None:
    sender = str(message.get("from", "")).strip()
    recipient = str(message.get("to", "")).strip()
    content = str(message.get("content", ""))
    if not sender or not recipient:
        return
    if "@" not in sender:
        return
    _system_only_recipients = {"system", "watcher"}
    if recipient in _system_only_recipients:
        return
    meta = message.get("meta") if isinstance(message.get("meta"), dict) else None
    _append_message(sender, recipient, content, meta=meta)  # type: ignore[misc]
    _emit_message_received(sender, recipient, "federation")  # type: ignore[misc]


def _init_federation_runtime() -> None:
    global _FEDERATION_RUNTIME, _FEDERATION_RUNTIME_ERROR
    if not BRIDGE_FEDERATION_ENABLED:
        _FEDERATION_RUNTIME_ERROR = "disabled by config"
        return
    if not HAS_FEDERATION_RUNTIME:
        _FEDERATION_RUNTIME_ERROR = globals().get("_FEDERATION_IMPORT_ERROR", "federation runtime unavailable")
        print(f"[federation] disabled: {_FEDERATION_RUNTIME_ERROR}")
        return

    try:
        runtime = FederationRuntime.from_local_files(
            base_dir=BRIDGE_FEDERATION_DIR,
            peers_file=BRIDGE_FEDERATION_PEERS_FILE,
            relay_url_override=BRIDGE_FEDERATION_RELAY_URL,
        )
        runtime.start(_handle_federation_inbound)
    except Exception as exc:  # noqa: BLE001
        with _FEDERATION_RUNTIME_LOCK:
            _FEDERATION_RUNTIME = None
            _FEDERATION_RUNTIME_ERROR = str(exc)
        print(f"[federation] init failed: {exc}")
        return

    with _FEDERATION_RUNTIME_LOCK:
        _FEDERATION_RUNTIME = runtime
        _FEDERATION_RUNTIME_ERROR = ""
    relay_mode = "enabled" if runtime.relay_client is not None else "not configured"
    print(f"[federation] initialized (instance_id={runtime.config.get('instance_id', '')}, relay={relay_mode})")


def _stop_federation_runtime() -> None:
    global _FEDERATION_RUNTIME
    with _FEDERATION_RUNTIME_LOCK:
        runtime = _FEDERATION_RUNTIME
        _FEDERATION_RUNTIME = None
    if runtime is None:
        return
    try:
        runtime.stop()
    except Exception as exc:  # noqa: BLE001
        print(f"[federation] stop warning: {exc}")


def _federation_send_outbound(sender: str, recipient: str, content: str) -> dict[str, Any]:
    if not BRIDGE_FEDERATION_ENABLED:
        raise RuntimeError("federation routing is disabled")
    if not _is_federation_target(recipient):
        raise ValueError("recipient is not a federation target")

    with _FEDERATION_RUNTIME_LOCK:
        runtime = _FEDERATION_RUNTIME
        init_error = _FEDERATION_RUNTIME_ERROR
    if runtime is None:
        reason = init_error or "federation runtime is not initialized"
        raise RuntimeError(reason)

    frame = runtime.send_text(sender_agent=sender, target=recipient, content=content)
    return {
        "direction": "outbound",
        "federation_msg_id": str(frame.get("federation_msg_id", "")),
        "from_instance": str(frame.get("from_instance", "")),
        "to_instance": str(frame.get("to_instance", "")),
        "to_agent": str(frame.get("to_agent", "")),
        "relay_configured": runtime.relay_client is not None,
    }
