"""
Bridge Event Bus — Webhook-based event emission for n8n integration.

Emits Bridge events to registered webhook subscribers (n8n, external services).
Subscriptions are persisted in event_subscriptions.json.

Architecture:
  - In-memory subscription registry protected by _SUB_LOCK
  - Atomic persistence via tempfile.mkstemp + os.replace
  - Fire-and-forget webhook delivery in daemon threads
  - Wildcard "*" subscriptions receive all events

Spec: /home/leo/Desktop/CC/Viktor/N8N_INTEGRATION_SPEC.md
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("event_bus")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBSCRIPTIONS_FILE = os.path.join(BASE_DIR, "event_subscriptions.json")
N8N_WEBHOOKS_FILE = os.path.join(BASE_DIR, "n8n_webhooks.json")
FAILED_DELIVERIES_FILE = os.path.join(BASE_DIR, "logs", "failed_webhooks.jsonl")

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
_SUBSCRIPTIONS: dict[str, dict[str, Any]] = {}  # sub_id → subscription object
_SUB_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WEBHOOK_TIMEOUT = 10.0        # seconds per webhook call
MAX_RETRIES = 2               # retry failed webhooks
RETRY_DELAY = 2.0             # seconds between retries
RATE_LIMIT_PER_TYPE = 100     # max events per type per minute
_RATE_COUNTERS: dict[str, list[float]] = {}  # event_type → list of timestamps
_RATE_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Known event types (documentation + validation)
# ---------------------------------------------------------------------------
KNOWN_EVENTS = {
    "task.created",
    "task.claimed",
    "task.done",
    "task.failed",
    "task.escalated",
    "message.received",
    "message.sent",
    "agent.online",
    "agent.offline",
    "agent.idle",
    "agent.mode_changed",
    "approval.requested",
    "approval.decided",
    "whiteboard.alert",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_sub_id() -> str:
    return f"sub_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Persistence (atomic writes)
# ---------------------------------------------------------------------------
def _save_subscriptions() -> None:
    """Persist subscriptions to disk. Must hold _SUB_LOCK."""
    data = json.dumps(
        {"subscriptions": list(_SUBSCRIPTIONS.values())},
        indent=2, ensure_ascii=False,
    ) + "\n"
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(
            dir=BASE_DIR, prefix=".event_subs_", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, SUBSCRIPTIONS_FILE)
    except Exception as exc:
        log.error("Failed to persist subscriptions: %s", exc)
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def load_subscriptions() -> None:
    """Load subscriptions from disk into memory. Call once at startup."""
    global _SUBSCRIPTIONS
    if not os.path.isfile(SUBSCRIPTIONS_FILE):
        return
    try:
        with open(SUBSCRIPTIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        with _SUB_LOCK:
            _SUBSCRIPTIONS.clear()
            for sub in data.get("subscriptions", []):
                sid = sub.get("id")
                if sid:
                    _SUBSCRIPTIONS[sid] = sub
        log.info("Loaded %d event subscriptions", len(_SUBSCRIPTIONS))
    except Exception as exc:
        log.error("Failed to load subscriptions: %s", exc)


def load_n8n_webhooks() -> int:
    """Load webhook subscriptions from n8n_webhooks.json config file.

    File format:
    {
      "webhooks": [
        {"event": "task.done", "url": "http://localhost:5678/webhook/..."},
        {"event": "agent.offline", "url": "http://localhost:5678/webhook/...", "label": "Agent down alert"},
        {"event": "*", "url": "http://localhost:5678/webhook/all-events"}
      ]
    }

    Also supports N8N_WEBHOOK_URL env var for a single catch-all webhook.
    Skips entries whose URL is already registered (idempotent).
    Returns number of new subscriptions created.
    """
    created = 0

    # File-based config
    if os.path.isfile(N8N_WEBHOOKS_FILE):
        try:
            with open(N8N_WEBHOOKS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            webhooks = data.get("webhooks", [])
            if not isinstance(webhooks, list):
                log.warning("n8n_webhooks.json: 'webhooks' must be a list")
                webhooks = []
            for entry in webhooks:
                url = str(entry.get("url", "")).strip()
                event_type = str(entry.get("event", "*")).strip()
                label = str(entry.get("label", "")).strip() or f"n8n-config: {event_type}"
                if not url:
                    continue
                # Skip if URL+event already registered
                if _is_webhook_registered(event_type, url):
                    continue
                subscribe(event_type, url, created_by="n8n-config", label=label)
                created += 1
            if created:
                log.info("Loaded %d new webhooks from n8n_webhooks.json", created)
        except Exception as exc:
            log.error("Failed to load n8n_webhooks.json: %s", exc)

    # Environment variable fallback: N8N_WEBHOOK_URL
    env_url = os.environ.get("N8N_WEBHOOK_URL", "").strip()
    if env_url and not _is_webhook_registered("*", env_url):
        subscribe("*", env_url, created_by="env-var", label="N8N_WEBHOOK_URL catch-all")
        created += 1
        log.info("Registered catch-all webhook from N8N_WEBHOOK_URL env var")

    return created


def _is_webhook_registered(event_type: str, url: str) -> bool:
    """Check if a webhook with this event_type+url combo already exists."""
    with _SUB_LOCK:
        for sub in _SUBSCRIPTIONS.values():
            if sub.get("webhook_url") == url and sub.get("event_type") == event_type:
                return True
    return False


def _log_failed_delivery(event: dict[str, Any], url: str, error: str) -> None:
    """Append failed delivery to JSONL log for retry/debugging."""
    entry = {
        "timestamp": _utc_now_iso(),
        "webhook_url": url,
        "event_type": event.get("event", ""),
        "error": str(error)[:500],
        "event_data": event.get("data", {}),
    }
    try:
        os.makedirs(os.path.dirname(FAILED_DELIVERIES_FILE), exist_ok=True)
        with open(FAILED_DELIVERIES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Subscription CRUD
# ---------------------------------------------------------------------------
def subscribe(
    event_type: str,
    webhook_url: str,
    created_by: str = "system",
    filter_rules: dict[str, Any] | None = None,
    label: str = "",
) -> dict[str, Any]:
    """Register a webhook URL for an event type. Returns subscription object."""
    if event_type != "*" and event_type not in KNOWN_EVENTS:
        log.warning("Subscribing to unknown event type: %s", event_type)

    sub_id = _generate_sub_id()
    sub = {
        "id": sub_id,
        "event_type": event_type,
        "webhook_url": webhook_url,
        "created_by": created_by,
        "filter": filter_rules or {},
        "label": label,
        "active": True,
        "created_at": _utc_now_iso(),
        "stats": {"deliveries": 0, "failures": 0, "last_delivery": None},
    }
    with _SUB_LOCK:
        _SUBSCRIPTIONS[sub_id] = sub
        _save_subscriptions()
    log.info("Subscription %s: %s → %s (by %s)", sub_id, event_type, webhook_url, created_by)
    return sub


def unsubscribe(sub_id: str) -> bool:
    """Remove a subscription by ID. Returns True if found."""
    with _SUB_LOCK:
        if sub_id in _SUBSCRIPTIONS:
            del _SUBSCRIPTIONS[sub_id]
            _save_subscriptions()
            log.info("Unsubscribed %s", sub_id)
            return True
    return False


def list_subscriptions(created_by: str | None = None) -> list[dict[str, Any]]:
    """List all subscriptions, optionally filtered by creator."""
    with _SUB_LOCK:
        subs = list(_SUBSCRIPTIONS.values())
    if created_by:
        subs = [s for s in subs if s.get("created_by") == created_by]
    return subs


def get_subscription(sub_id: str) -> dict[str, Any] | None:
    """Get a single subscription by ID."""
    with _SUB_LOCK:
        return _SUBSCRIPTIONS.get(sub_id)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
def _check_rate_limit(event_type: str) -> bool:
    """Returns True if event is within rate limit."""
    now = time.monotonic()
    with _RATE_LOCK:
        if event_type not in _RATE_COUNTERS:
            _RATE_COUNTERS[event_type] = []
        # Remove entries older than 60 seconds
        _RATE_COUNTERS[event_type] = [
            t for t in _RATE_COUNTERS[event_type] if now - t < 60.0
        ]
        if len(_RATE_COUNTERS[event_type]) >= RATE_LIMIT_PER_TYPE:
            return False
        _RATE_COUNTERS[event_type].append(now)
        return True


# ---------------------------------------------------------------------------
# Filter matching
# ---------------------------------------------------------------------------
def _matches_filter(payload: dict[str, Any], filter_rules: dict[str, Any]) -> bool:
    """Check if event payload matches subscription filter rules.

    Filter rules are key-value pairs. All must match (AND logic).
    Example: {"priority": 1, "assigned_to": "viktor"}
    """
    if not filter_rules:
        return True
    for key, expected in filter_rules.items():
        actual = payload.get(key)
        if actual != expected:
            return False
    return True


# ---------------------------------------------------------------------------
# Webhook delivery
# ---------------------------------------------------------------------------
def _deliver_webhook(
    sub: dict[str, Any], event: dict[str, Any]
) -> None:
    """Send event to webhook URL with retries. Runs in daemon thread."""
    url = sub["webhook_url"]
    sub_id = sub["id"]

    # Lazy import to avoid circular dependencies
    try:
        import httpx
    except ImportError:
        import urllib.request
        # Fallback to urllib
        for attempt in range(MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(event).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT) as resp:
                    if resp.status < 400:
                        with _SUB_LOCK:
                            if sub_id in _SUBSCRIPTIONS:
                                _SUBSCRIPTIONS[sub_id]["stats"]["deliveries"] += 1
                                _SUBSCRIPTIONS[sub_id]["stats"]["last_delivery"] = _utc_now_iso()
                        return
            except Exception as exc:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    log.warning("Webhook %s failed after %d attempts: %s", url, MAX_RETRIES + 1, exc)
                    with _SUB_LOCK:
                        if sub_id in _SUBSCRIPTIONS:
                            _SUBSCRIPTIONS[sub_id]["stats"]["failures"] += 1
                    _log_failed_delivery(event, url, str(exc))
        return

    # httpx path (preferred)
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = httpx.post(url, json=event, timeout=WEBHOOK_TIMEOUT)
            if resp.status_code < 400:
                with _SUB_LOCK:
                    if sub_id in _SUBSCRIPTIONS:
                        _SUBSCRIPTIONS[sub_id]["stats"]["deliveries"] += 1
                        _SUBSCRIPTIONS[sub_id]["stats"]["last_delivery"] = _utc_now_iso()
                return
            log.warning("Webhook %s returned %d", url, resp.status_code)
        except Exception as exc:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                log.warning("Webhook %s failed after %d attempts: %s", url, MAX_RETRIES + 1, exc)
                with _SUB_LOCK:
                    if sub_id in _SUBSCRIPTIONS:
                        _SUBSCRIPTIONS[sub_id]["stats"]["failures"] += 1
                _log_failed_delivery(event, url, str(exc))


# ---------------------------------------------------------------------------
# Event emission (main API)
# ---------------------------------------------------------------------------
def emit(event_type: str, payload: dict[str, Any]) -> int:
    """Emit an event to all matching subscribers.

    Returns the number of webhooks triggered.
    Fire-and-forget: delivery happens in background threads.
    """
    if not _check_rate_limit(event_type):
        log.warning("Rate limit exceeded for event type: %s", event_type)
        return 0

    # Build event envelope
    event = {
        "event": event_type,
        "timestamp": _utc_now_iso(),
        "data": payload,
    }

    # Find matching subscriptions
    triggered = 0
    with _SUB_LOCK:
        candidates = list(_SUBSCRIPTIONS.values())

    for sub in candidates:
        if not sub.get("active", True):
            continue
        sub_type = sub.get("event_type", "")
        if sub_type != "*" and sub_type != event_type:
            continue
        if not _matches_filter(payload, sub.get("filter", {})):
            continue

        # Deliver in background thread
        threading.Thread(
            target=_deliver_webhook,
            args=(sub, event),
            daemon=True,
        ).start()
        triggered += 1

    if triggered > 0:
        log.debug("Event %s emitted to %d subscribers", event_type, triggered)

    try:
        import automation_engine
        local_results = automation_engine.dispatch_event(event_type, payload)
        if local_results:
            log.debug("Event %s triggered %d local automations", event_type, len(local_results))
    except Exception as exc:
        log.warning("Local automation dispatch failed for %s: %s", event_type, exc)

    return triggered


# ---------------------------------------------------------------------------
# Convenience emitters (type-safe wrappers)
# ---------------------------------------------------------------------------
def emit_task_created(task_id: str, title: str, assigned_to: str, priority: int, created_by: str) -> int:
    return emit("task.created", {
        "task_id": task_id, "title": title, "assigned_to": assigned_to,
        "priority": priority, "created_by": created_by,
    })

def emit_task_done(task_id: str, agent_id: str, result: str = "") -> int:
    return emit("task.done", {"task_id": task_id, "agent_id": agent_id, "result": result})

def emit_task_failed(task_id: str, agent_id: str, reason: str = "") -> int:
    return emit("task.failed", {"task_id": task_id, "agent_id": agent_id, "reason": reason})

def emit_agent_online(agent_id: str, role: str = "") -> int:
    return emit("agent.online", {"agent_id": agent_id, "role": role})

def emit_agent_offline(agent_id: str, reason: str = "") -> int:
    return emit("agent.offline", {"agent_id": agent_id, "reason": reason})

def emit_agent_mode_changed(agent_id: str, mode: str) -> int:
    return emit("agent.mode_changed", {"agent_id": agent_id, "mode": mode})

def emit_message_received(sender: str, recipient: str, channel: str = "work") -> int:
    return emit("message.received", {"from": sender, "to": recipient, "channel": channel})

def emit_message_sent(sender: str, recipient: str, channel: str = "work") -> int:
    return emit("message.sent", {"from": sender, "to": recipient, "channel": channel})
