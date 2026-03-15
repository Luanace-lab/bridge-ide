"""
Bridge Automation Engine — Hierarchie-Integration.

Manages automation rules: schedule triggers, event listeners, action execution.
Spec: /home/user/bridge/Viktor/AUTOMATION_SPEC.md

Storage:
  - automations.json: Automation definitions (atomic R/W)
  - automation_history.jsonl: Execution log (append-only)

Architecture:
  - In-memory automations dict protected by AUTOMATION_LOCK
  - Atomic persistence via tempfile.mkstemp + os.replace
  - AutomationScheduler thread for cron-based triggers
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from common import build_bridge_auth_headers

try:
    import croniter as _croniter_mod  # noqa: F401
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False
    print("[automation] WARNING: croniter not installed. Schedule triggers disabled.")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUTOMATIONS_FILE = os.path.join(BASE_DIR, "automations.json")
AUTOMATION_HISTORY_FILE = os.path.join(BASE_DIR, "logs", "automation_history.jsonl")

# ---------------------------------------------------------------------------
# In-memory store + lock
# ---------------------------------------------------------------------------
AUTOMATIONS: dict[str, dict[str, Any]] = {}  # id → automation object
AUTOMATION_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Limits (Kai-Review)
# ---------------------------------------------------------------------------
AUTOMATION_SOFT_LIMIT_PER_AGENT = 50
AUTOMATION_WARN_THRESHOLD = 20

# ---------------------------------------------------------------------------
# P0-A: Idle-Only Execution — Pending queue for busy agents
# ---------------------------------------------------------------------------
# NOTE: These dicts are ONLY accessed from AutomationScheduler._tick() (single-threaded).
# No Lock needed — but do NOT read/write from other threads.
_PENDING_AUTOMATIONS: dict[str, list[dict[str, Any]]] = {}  # agent_id → [automation, ...]
_PENDING_RETRY_COUNT: dict[str, int] = {}  # auto_id → retry count
_MAX_IDLE_RETRIES = 5  # Force-fire after this many retries
_MAX_PENDING_PER_AGENT = 50  # Overflow → deactivate automation

# ---------------------------------------------------------------------------
# P1-C: Jitter — deterministic offset per automation
# ---------------------------------------------------------------------------
_JITTER_CAP_SECONDS = 900  # Max 15 minutes
_LEGACY_EVENT_TYPE_MAP = {
    "task_created": "task.created",
    "task_done": "task.done",
    "task_failed": "task.failed",
    "task_escalated": "task.escalated",
    "agent_online": "agent.online",
    "agent_offline": "agent.offline",
    "agent_idle": "agent.idle",
    "agent_mode_changed": "agent.mode_changed",
    "message_received": "message.received",
    "message_sent": "message.sent",
}


def _compute_jitter(auto_id: str, interval_seconds: int) -> int:
    """Deterministic jitter: hash(auto_id) % (10% of interval), capped at 900s."""
    import hashlib
    max_jitter = min(_JITTER_CAP_SECONDS, max(1, int(interval_seconds * 0.1)))
    h = int(hashlib.md5(auto_id.encode()).hexdigest(), 16)
    return h % max_jitter


def _cron_interval_seconds(cron_expr: str) -> int:
    """Estimate interval in seconds from a cron expression for jitter calculation.

    Simple heuristic: parse */N patterns. Falls back to 300s (5min) for complex expressions.
    """
    import re
    parts = cron_expr.strip().split()
    if len(parts) < 5:
        return 300  # fallback

    minute, hour = parts[0], parts[1]

    # */N minutes
    m = re.match(r"^\*/(\d+)$", minute)
    if m:
        return int(m.group(1)) * 60

    # Every minute
    if minute == "*":
        return 60

    # 0 */N hours
    m = re.match(r"^\*/(\d+)$", hour)
    if m and minute in ("0", "00"):
        return int(m.group(1)) * 3600

    # Fixed time (daily) — e.g. "30 14 * * *"
    if minute.isdigit() and hour.isdigit() and parts[2] == "*":
        return 86400  # daily

    return 300  # fallback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id() -> str:
    """Generate unique automation ID (auto_ prefix + 8-char hex)."""
    return f"auto_{uuid.uuid4().hex[:8]}"


def normalize_event_type(event_type: str) -> str:
    """Map legacy underscore event names onto canonical dotted names."""
    raw = str(event_type or "").strip()
    if not raw:
        return raw
    return _LEGACY_EVENT_TYPE_MAP.get(raw, raw)


def _normalize_trigger(trigger: dict[str, Any], auto_id: str) -> dict[str, Any]:
    """Normalize trigger contracts so UI, server and engine share one vocabulary."""
    normalized = copy.deepcopy(trigger) if isinstance(trigger, dict) else {}
    trig_type = str(normalized.get("type", "")).strip()
    if trig_type == "event":
        normalized["event_type"] = normalize_event_type(str(normalized.get("event_type", "")).strip())
    elif trig_type == "webhook":
        webhook_path = str(normalized.get("webhook_path", "")).strip()
        if not webhook_path:
            normalized["webhook_path"] = f"/automations/{auto_id}/webhook"
    elif trig_type == "condition":
        cond = str(normalized.get("condition", "")).strip()
        if cond == "task_overdue" and "threshold_hours" not in normalized:
            try:
                normalized["threshold_hours"] = int(normalized.get("threshold_minutes", normalized.get("threshold", 24)))
            except (TypeError, ValueError):
                normalized["threshold_hours"] = 24
    return normalized


def _matches_filter(payload: dict[str, Any], filter_rules: dict[str, Any] | None) -> bool:
    if not filter_rules:
        return True
    for key, expected in filter_rules.items():
        if payload.get(key) != expected:
            return False
    return True


# ---------------------------------------------------------------------------
# Atomic persistence (same pattern as server.py _persist_tasks)
# ---------------------------------------------------------------------------
def _save_automations_to_disk() -> None:
    """Atomically persist AUTOMATIONS dict to automations.json.

    Must be called while holding AUTOMATION_LOCK.
    """
    data_obj = {"automations": list(AUTOMATIONS.values())}
    data = json.dumps(data_obj, indent=2, ensure_ascii=False) + "\n"
    try:
        fd, tmp = tempfile.mkstemp(
            dir=os.path.dirname(AUTOMATIONS_FILE), suffix=".tmp"
        )
        try:
            os.write(fd, data.encode("utf-8"))
            os.close(fd)
            os.replace(tmp, AUTOMATIONS_FILE)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception as e:
        print(f"[automation] ERROR persisting automations.json: {e}")


def _load_automations_from_disk() -> None:
    """Load automations from automations.json into memory.

    Called at startup. Acquires AUTOMATION_LOCK internally.
    """
    global AUTOMATIONS
    if not os.path.exists(AUTOMATIONS_FILE):
        print("[automation] No automations.json found — starting empty.")
        return
    try:
        with open(AUTOMATIONS_FILE) as f:
            raw = json.load(f)
        automations_list = raw.get("automations", []) if isinstance(raw, dict) else []
        with AUTOMATION_LOCK:
            AUTOMATIONS.clear()
            for auto in automations_list:
                auto_id = auto.get("id")
                if auto_id:
                    AUTOMATIONS[auto_id] = auto
        print(f"[automation] Loaded {len(AUTOMATIONS)} automations from disk.")
    except (json.JSONDecodeError, OSError) as e:
        print(f"[automation] ERROR loading automations.json: {e}")


# ---------------------------------------------------------------------------
# CRUD operations (thread-safe)
# ---------------------------------------------------------------------------
def get_all_automations() -> list[dict[str, Any]]:
    """Return list of all automations (deep copies — safe for caller mutation)."""
    with AUTOMATION_LOCK:
        return [copy.deepcopy(a) for a in AUTOMATIONS.values()]


def get_automation(auto_id: str) -> dict[str, Any] | None:
    """Return single automation by ID (deep copy), or None."""
    with AUTOMATION_LOCK:
        auto = AUTOMATIONS.get(auto_id)
        return copy.deepcopy(auto) if auto else None


def add_automation(data: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Create new automation. Returns (automation, warning_or_none).

    Validates required fields. Generates ID if missing.
    Checks soft-limit per created_by agent.
    """
    auto_id = data.get("id") or _generate_id()
    created_by = data.get("created_by", "unknown")
    trigger = _normalize_trigger(data.get("trigger", {}), auto_id)

    # Build automation object with defaults
    assigned_to = data.get("assigned_to") or created_by  # P0-B: Agent-Routing
    automation: dict[str, Any] = {
        "id": auto_id,
        "name": str(data.get("name", "Unnamed Automation")),
        "description": str(data.get("description", "")),
        "active": bool(data.get("active", True)),
        "paused_until": data.get("paused_until"),  # ISO string or None
        "created_by": created_by,
        "assigned_to": assigned_to,  # P0-B: defaults to created_by
        "trigger": trigger,
        "action": data.get("action", {}),
        "options": _build_options(data.get("options", {}), data.get("action", {})),
        "created_at": _utc_now_iso(),
        "last_run": None,
        "last_result_id": None,
        "next_run": None,
        "run_count": 0,
        "last_status": None,
    }

    warning = None
    with AUTOMATION_LOCK:
        # ID collision check (Kai-Review)
        if auto_id in AUTOMATIONS:
            return None, f"Automation '{auto_id}' already exists"  # type: ignore[return-value]

        # Check soft-limit
        agent_count = sum(
            1 for a in AUTOMATIONS.values() if a.get("created_by") == created_by
        )
        if agent_count >= AUTOMATION_SOFT_LIMIT_PER_AGENT:
            warning = (
                f"Agent '{created_by}' has {agent_count} automations "
                f"(soft limit: {AUTOMATION_SOFT_LIMIT_PER_AGENT})"
            )
        elif agent_count >= AUTOMATION_WARN_THRESHOLD:
            warning = (
                f"Agent '{created_by}' has {agent_count} automations "
                f"(warning threshold: {AUTOMATION_WARN_THRESHOLD})"
            )

        AUTOMATIONS[auto_id] = automation
        _save_automations_to_disk()

    return automation, warning


def update_automation(auto_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Update existing automation. Returns updated automation or None if not found."""
    with AUTOMATION_LOCK:
        existing = AUTOMATIONS.get(auto_id)
        if not existing:
            return None

        # Update allowed fields
        updatable = {
            "name", "description", "active", "paused_until",
            "trigger", "action", "options", "assigned_to",  # P0-B
        }
        for key in updatable:
            if key in data:
                if key == "options":
                    existing["options"] = _build_options(
                        data["options"], existing.get("action", {})
                    )
                elif key == "trigger":
                    existing["trigger"] = _normalize_trigger(data["trigger"], auto_id)
                else:
                    existing[key] = data[key]

        existing["updated_at"] = _utc_now_iso()
        _save_automations_to_disk()
        return existing


def delete_automation(auto_id: str) -> bool:
    """Delete automation by ID. Returns True if found and deleted."""
    with AUTOMATION_LOCK:
        if auto_id not in AUTOMATIONS:
            return False
        del AUTOMATIONS[auto_id]
        _save_automations_to_disk()
        return True


def set_automation_active(auto_id: str, active: bool) -> dict[str, Any] | None:
    """Toggle automation active state. Returns updated automation or None."""
    with AUTOMATION_LOCK:
        existing = AUTOMATIONS.get(auto_id)
        if not existing:
            return None
        existing["active"] = active
        existing["updated_at"] = _utc_now_iso()
        _save_automations_to_disk()
        return existing


def set_automation_pause(
    auto_id: str, paused_until: str | None
) -> dict[str, Any] | None:
    """Set pause-until date (ISO string) or None to unpause."""
    with AUTOMATION_LOCK:
        existing = AUTOMATIONS.get(auto_id)
        if not existing:
            return None
        existing["paused_until"] = paused_until
        existing["updated_at"] = _utc_now_iso()
        _save_automations_to_disk()
        return existing


# ---------------------------------------------------------------------------
# Execution history (append-only JSONL)
# ---------------------------------------------------------------------------
HISTORY_LOCK = threading.Lock()  # Separate lock for history writes (Kai-Review)
def log_execution(
    auto_id: str,
    status: str,
    details: dict[str, Any] | None = None,
    exec_id: str | None = None,
) -> str:
    """Log an automation execution to automation_history.jsonl.

    Args:
        exec_id: Pre-generated ID (optional). Generated if not provided.

    Returns execution ID.
    """
    if not exec_id:
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
    entry = {
        "exec_id": exec_id,
        "automation_id": auto_id,
        "status": status,
        "timestamp": _utc_now_iso(),
        "details": details or {},
    }
    try:
        os.makedirs(os.path.dirname(AUTOMATION_HISTORY_FILE), exist_ok=True)
        with HISTORY_LOCK:
            with open(AUTOMATION_HISTORY_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[automation] ERROR writing history: {e}")
    return exec_id


def get_execution_history(
    auto_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Read last N executions for an automation from history file."""
    results: list[dict[str, Any]] = []
    if not os.path.exists(AUTOMATION_HISTORY_FILE):
        return results
    try:
        with open(AUTOMATION_HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("automation_id") == auto_id:
                        results.append(entry)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    # Return most recent first, limited
    return results[-limit:][::-1]


def get_execution_by_id(exec_id: str) -> dict[str, Any] | None:
    """Fetch single execution entry by exec_id."""
    if not os.path.exists(AUTOMATION_HISTORY_FILE):
        return None
    try:
        with open(AUTOMATION_HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("exec_id") == exec_id:
                        return entry
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------
# Options builder (handles approval defaults per Nova-Review)
# ---------------------------------------------------------------------------
def _build_options(
    options_data: dict[str, Any], action_data: dict[str, Any]
) -> dict[str, Any]:
    """Build options with correct defaults.

    Nova-Review: approval_required defaults to TRUE for set_mode and webhook actions.
    """
    action_type = action_data.get("type", "")

    # Default approval_required based on action type
    default_approval = action_type in ("set_mode", "webhook")

    try:
        max_retries = int(options_data.get("max_retries", 0))
    except (ValueError, TypeError):
        max_retries = 0
    try:
        timeout_seconds = int(options_data.get("timeout_seconds", 1800))
    except (ValueError, TypeError):
        timeout_seconds = 1800

    # P2: catch_up policy
    catch_up = options_data.get("catch_up", "skip")
    if catch_up not in ("skip", "run_once", "run_all"):
        catch_up = "skip"
    try:
        max_catch_up_runs = int(options_data.get("max_catch_up_runs", 10))
    except (ValueError, TypeError):
        max_catch_up_runs = 10

    return {
        "set_mode": options_data.get("set_mode"),
        "restore_mode": options_data.get("restore_mode"),
        "approval_required": options_data.get("approval_required", default_approval),
        "max_retries": max_retries,
        "timeout_seconds": timeout_seconds,
        "notify_on_error": options_data.get("notify_on_error", True),
        "catch_up": catch_up,
        "max_catch_up_runs": max_catch_up_runs,
    }


# ---------------------------------------------------------------------------
# Schedule trigger helpers
# ---------------------------------------------------------------------------
def compute_next_run(cron_expr: str, tz_name: str = "UTC") -> str | None:
    """Compute next run time from cron expression. Returns ISO string or None."""
    if not HAS_CRONITER:
        return None
    try:
        from croniter import croniter as _croniter
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        cron = _croniter(cron_expr, now)
        next_dt = cron.get_next(datetime)
        # Convert to UTC for storage
        return next_dt.astimezone(timezone.utc).isoformat()
    except Exception as e:
        print(f"[automation] ERROR computing next_run: {e}")
        return None


def _is_schedule_due(automation: dict[str, Any]) -> bool:
    """Check if a schedule-triggered automation is due to run now."""
    trigger = automation.get("trigger", {})
    if trigger.get("type") != "schedule":
        return False

    next_run = automation.get("next_run")
    if not next_run:
        return False

    try:
        next_dt = datetime.fromisoformat(next_run)
        now = datetime.now(timezone.utc)
        return now >= next_dt
    except (ValueError, TypeError):
        return False


def _is_paused(automation: dict[str, Any]) -> bool:
    """Check if automation is paused (paused_until in the future)."""
    paused_until = automation.get("paused_until")
    if not paused_until:
        return False
    try:
        pause_dt = datetime.fromisoformat(paused_until)
        return datetime.now(timezone.utc) < pause_dt
    except (ValueError, TypeError):
        return False


def _task_is_open(task: dict[str, Any]) -> bool:
    return str(task.get("state", "")).strip() not in {"done", "failed", "cancelled"}


def _is_condition_due(automation: dict[str, Any], context: dict[str, Any]) -> bool:
    """Evaluate condition triggers against a server-provided runtime context."""
    trigger = automation.get("trigger", {})
    if trigger.get("type") != "condition":
        return False

    agents = context.get("agents", {}) if isinstance(context, dict) else {}
    tasks = context.get("tasks", []) if isinstance(context, dict) else []
    condition = str(trigger.get("condition", "")).strip()
    target_agent = (
        str(trigger.get("agent_id", "")).strip()
        or str(automation.get("assigned_to", "")).strip()
        or str(automation.get("created_by", "")).strip()
    )

    if condition == "agent_offline":
        agent = agents.get(target_agent, {})
        return not bool(agent.get("online"))

    if condition == "agent_idle":
        agent = agents.get(target_agent, {})
        if not agent or not agent.get("online"):
            return False
        if agent.get("busy"):
            return False
        threshold = int(trigger.get("threshold_minutes", trigger.get("threshold", 60)) or 60) * 60
        last_activity_seconds = agent.get("last_activity_seconds")
        if last_activity_seconds is None:
            return True
        try:
            return float(last_activity_seconds) >= threshold
        except (TypeError, ValueError):
            return True

    if condition == "task_count_above":
        threshold = int(trigger.get("threshold", 0) or 0)
        open_tasks = [
            task for task in tasks
            if _task_is_open(task)
            and (not target_agent or str(task.get("assigned_to", "")).strip() == target_agent)
        ]
        return len(open_tasks) > threshold

    if condition == "task_overdue":
        threshold_hours = int(trigger.get("threshold_hours", trigger.get("threshold", 24)) or 24)
        now = datetime.now(timezone.utc)
        for task in tasks:
            if not _task_is_open(task):
                continue
            if target_agent and str(task.get("assigned_to", "")).strip() != target_agent:
                continue
            deadline_raw = str(task.get("deadline", "") or "").strip()
            if deadline_raw:
                try:
                    deadline = datetime.fromisoformat(deadline_raw)
                    if deadline.tzinfo is None:
                        deadline = deadline.replace(tzinfo=timezone.utc)
                    if deadline <= now:
                        return True
                except ValueError:
                    pass
            created_raw = str(task.get("created_at", "") or "").strip()
            if not created_raw:
                continue
            try:
                created_at = datetime.fromisoformat(created_raw)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if (now - created_at).total_seconds() >= threshold_hours * 3600:
                return True
        return False

    return False


# ---------------------------------------------------------------------------
# AutomationScheduler (Thread)
# ---------------------------------------------------------------------------
class AutomationScheduler(threading.Thread):
    """Background thread that checks schedule triggers every 60 seconds.

    Architecture:
      - Runs as daemon thread (stops when server stops)
      - Reads from in-memory AUTOMATIONS (protected by AUTOMATION_LOCK)
      - Calls action_callback for each triggered automation
      - Updates next_run after execution
      - Respects active, paused_until flags
    """

    def __init__(
        self,
        action_callback: Callable[[dict[str, Any]], Any] | None = None,
        check_interval: int = 60,
        idle_check_callback: Callable[[str], bool | None] | None = None,  # P0-A
        condition_context_callback: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(daemon=True, name="AutomationScheduler")
        self._stop_event = threading.Event()
        self._check_interval = check_interval
        self._action_callback = action_callback
        self._idle_check_callback = idle_check_callback  # P0-A: Optional
        self._condition_context_callback = condition_context_callback
        self._running = False

    def stop(self) -> None:
        """Signal the scheduler to stop."""
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        return self._running

    def run(self) -> None:
        """Main scheduler loop."""
        self._running = True
        print(f"[automation] Scheduler started (interval={self._check_interval}s)")

        # Compute initial next_run for all schedule automations
        self._init_next_runs()

        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                print(f"[automation] Scheduler tick error: {e}")

            # Wait for check_interval or until stopped
            self._stop_event.wait(timeout=self._check_interval)

        self._running = False
        print("[automation] Scheduler stopped.")

    def _init_next_runs(self) -> None:
        """Compute next_run for all schedule automations that don't have one."""
        with AUTOMATION_LOCK:
            changed = False
            for auto in AUTOMATIONS.values():
                trigger = auto.get("trigger", {})
                if trigger.get("type") != "schedule":
                    continue
                if auto.get("next_run"):
                    continue  # Already has a next_run
                cron_expr = trigger.get("cron")
                tz_name = trigger.get("timezone", "UTC")
                if cron_expr:
                    next_run = compute_next_run(cron_expr, tz_name)
                    if next_run:
                        # P1-C: Apply deterministic jitter
                        jitter_secs = _compute_jitter(auto.get("id", ""), _cron_interval_seconds(cron_expr))
                        if jitter_secs > 0:
                            from datetime import timedelta
                            nr_dt = datetime.fromisoformat(next_run)
                            next_run = (nr_dt + timedelta(seconds=jitter_secs)).isoformat()
                        auto["next_run"] = next_run
                        changed = True
            if changed:
                _save_automations_to_disk()

    def _tick(self) -> None:
        """Single scheduler tick: check all automations for due triggers.

        P0-A: If idle_check_callback is set, checks agent idle state before firing.
        Busy agents get their automations queued in _PENDING_AUTOMATIONS.
        After 5 retries, force-fires. Overflow (>50 pending) deactivates automation.
        """
        due_automations: list[dict[str, Any]] = []
        condition_context: dict[str, Any] | None = None
        if self._condition_context_callback:
            try:
                condition_context = self._condition_context_callback() or {}
            except Exception as exc:
                print(f"[automation] Condition context callback failed: {exc}")
                condition_context = {}

        with AUTOMATION_LOCK:
            for auto in AUTOMATIONS.values():
                # Skip inactive
                if not auto.get("active", False):
                    continue
                # Skip paused
                if _is_paused(auto):
                    continue
                trigger = auto.get("trigger", {})
                if trigger.get("type") == "schedule" and _is_schedule_due(auto):
                    due_automations.append(copy.deepcopy(auto))  # Deep copy (Kai-Review T2)
                    continue
                if trigger.get("type") == "condition":
                    condition_true = _is_condition_due(auto, condition_context or {})
                    was_active = bool(auto.get("condition_active", False))
                    if condition_true and not was_active:
                        auto["condition_active"] = True
                        due_automations.append(copy.deepcopy(auto))
                    elif not condition_true and was_active:
                        auto["condition_active"] = False

        # P0-A: Process pending automations from previous ticks
        fired_ids: set[str] = set()
        if self._idle_check_callback:
            fired_ids = self._process_pending()

        # Execute outside lock — with idle check if callback set
        for auto in due_automations:
            if auto["id"] in fired_ids:
                continue  # Already fired from pending queue — skip dedup

            if self._idle_check_callback:
                agent_id = auto.get("assigned_to") or auto.get("created_by", "unknown")
                is_idle = self._idle_check_callback(agent_id)

                if is_idle is None or not is_idle:
                    # Agent busy or offline → queue
                    self._queue_pending(auto, agent_id)
                    continue

            self._execute_automation(auto)

    def _queue_pending(self, auto: dict[str, Any], agent_id: str) -> None:
        """P0-A: Queue automation for busy/offline agent."""
        auto_id = auto["id"]
        retry = _PENDING_RETRY_COUNT.get(auto_id, 0) + 1
        _PENDING_RETRY_COUNT[auto_id] = retry

        if retry > _MAX_IDLE_RETRIES:
            # Force-fire after max retries
            print(f"[automation] Force-firing {auto_id} after {_MAX_IDLE_RETRIES} retries (agent {agent_id} still busy)")
            _PENDING_RETRY_COUNT.pop(auto_id, None)
            self._execute_automation(auto)
            return

        # Check pending overflow
        pending = _PENDING_AUTOMATIONS.get(agent_id, [])
        if len(pending) >= _MAX_PENDING_PER_AGENT:
            print(f"[automation] Pending overflow for {agent_id} ({len(pending)} pending). Deactivating {auto_id}.")
            with AUTOMATION_LOCK:
                if auto_id in AUTOMATIONS:
                    AUTOMATIONS[auto_id]["active"] = False
                    _save_automations_to_disk()
            _PENDING_RETRY_COUNT.pop(auto_id, None)
            return

        # Queue it
        if agent_id not in _PENDING_AUTOMATIONS:
            _PENDING_AUTOMATIONS[agent_id] = []
        _PENDING_AUTOMATIONS[agent_id].append(auto)

    def _process_pending(self) -> set[str]:
        """P0-A: Check pending automations and fire if agent is now idle.
        Returns set of fired automation IDs (for dedup in _tick)."""
        fired_ids: set[str] = set()
        if not self._idle_check_callback:
            return fired_ids
        for agent_id in list(_PENDING_AUTOMATIONS.keys()):
            is_idle = self._idle_check_callback(agent_id)
            if is_idle:
                pending = _PENDING_AUTOMATIONS.pop(agent_id, [])
                for auto in pending:
                    _PENDING_RETRY_COUNT.pop(auto["id"], None)
                    self._execute_automation(auto)
                    fired_ids.add(auto["id"])
        return fired_ids

    def _execute_automation(self, automation: dict[str, Any]) -> None:
        """Execute a triggered automation and update its state.

        On error + notify_on_error: sends error message to created_by (Nova-Review).
        """
        auto_id = automation["id"]
        auto_name = automation.get("name", auto_id)
        print(f"[automation] Triggering: {auto_name}")

        error_msg: str | None = None
        if self._action_callback:
            try:
                result = self._action_callback(automation)
                # Check result if it's a dict with ok/error
                if isinstance(result, dict) and not result.get("ok", True):
                    error_msg = result.get("error", "action returned error")
            except Exception as e:
                error_msg = str(e)

        if error_msg:
            print(f"[automation] Action failed for {auto_id}: {error_msg}")
            self._update_after_run(auto_id, "error", error_msg)
            # notify_on_error (Nova-Review: send error to created_by)
            _notify_on_error(automation, error_msg)
        else:
            self._update_after_run(auto_id, "success")

    def _update_after_run(
        self, auto_id: str, status: str, error: str | None = None
    ) -> None:
        """Update automation state after execution."""
        _record_run_result(auto_id, status, error)


# ---------------------------------------------------------------------------
# Action Execution (T5)
# ---------------------------------------------------------------------------
_SERVER_PORT: int = 9111


def set_server_port(port: int) -> None:
    """Set the server port for action execution HTTP calls."""
    global _SERVER_PORT
    _SERVER_PORT = port


def _record_run_result(auto_id: str, status: str, error: str | None = None) -> None:
    """Persist execution result consistently across all trigger paths."""
    exec_id = f"exec_{uuid.uuid4().hex[:8]}"
    details: dict[str, Any] = {}

    with AUTOMATION_LOCK:
        auto = AUTOMATIONS.get(auto_id)
        if not auto:
            return

        now_iso = _utc_now_iso()
        auto["last_run"] = now_iso
        auto["last_status"] = status
        auto["run_count"] = auto.get("run_count", 0) + 1
        auto["last_result_id"] = exec_id
        details = {"automation_name": auto.get("name", "")}
        if error:
            details["error"] = error

        max_runs = auto.get("options", {}).get("max_runs", 0)
        if max_runs and auto["run_count"] >= max_runs:
            auto["active"] = False

        trigger = auto.get("trigger", {})
        if trigger.get("type") == "schedule":
            cron_expr = trigger.get("cron")
            tz_name = trigger.get("timezone", "UTC")
            if cron_expr:
                next_run_iso = compute_next_run(cron_expr, tz_name)
                if next_run_iso:
                    jitter_secs = _compute_jitter(auto_id, _cron_interval_seconds(cron_expr))
                    if jitter_secs > 0:
                        from datetime import timedelta
                        nr_dt = datetime.fromisoformat(next_run_iso)
                        next_run_iso = (nr_dt + timedelta(seconds=jitter_secs)).isoformat()
                auto["next_run"] = next_run_iso

        _save_automations_to_disk()

    log_execution(auto_id, status, details, exec_id=exec_id)


def execute_action(automation: dict[str, Any]) -> dict[str, Any]:
    """Execute an automation's action. Returns result dict.

    Uses HTTP calls to localhost to reuse existing validation.
    """
    action = automation.get("action", {})
    auto_id = automation.get("id", "unknown")
    created_by = automation.get("created_by", "system")
    return _execute_action_spec(action, automation, auto_id, created_by)


def _execute_action_spec(
    action: dict[str, Any],
    automation: dict[str, Any],
    auto_id: str,
    created_by: str,
) -> dict[str, Any]:
    action_type = str(action.get("type", "")).strip()
    if action_type == "create_task":
        return _action_create_task(action, auto_id, created_by)
    if action_type == "send_message":
        return _action_send_message(action, auto_id, created_by)
    if action_type == "set_mode":
        return _action_set_mode(action, auto_id, created_by)
    if action_type == "webhook":
        return _action_webhook(action, auto_id, created_by)
    if action_type == "chain":
        return _action_chain(action, automation, auto_id, created_by)
    if action_type == "prompt_replay":
        return _action_prompt_replay(automation)
    return {"ok": False, "error": f"unsupported action type: {action_type}"}


def _http_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Send JSON to the local Bridge server and parse the JSON response."""
    import urllib.request
    import urllib.error

    url = f"http://127.0.0.1:{_SERVER_PORT}{path}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req_headers = build_bridge_auth_headers(extra_headers={
        "Content-Type": "application/json",
        "X-Bridge-Agent": "automation_engine",
    })
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(
        url,
        data=body,
        headers=req_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        return {"ok": False, "error": f"HTTP {e.code}: {error_body}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _http_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _http_request("POST", path, payload)


def _http_patch(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _http_request("PATCH", path, payload)


def _http_webhook(
    url: str,
    *,
    method: str = "POST",
    body: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute an outbound webhook call."""
    import urllib.request
    import urllib.error

    data = body.encode("utf-8") if isinstance(body, str) else None
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {"ok": True, "status": resp.status, "body": resp.read().decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        return {"ok": False, "status": e.code, "error": error_body or str(e)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _action_create_task(
    action: dict[str, Any], auto_id: str, created_by: str
) -> dict[str, Any]:
    """Execute create_task action via POST /tasks."""
    payload: dict[str, Any] = {
        "type": action.get("task_type", "general"),
        "title": action.get("title", f"Automation {auto_id}"),
        "description": action.get("description", ""),
        "priority": action.get("priority", 1),
        "labels": action.get("labels", ["automation"]),
        "created_by": f"automation:{created_by}",
    }
    assigned_to = action.get("assigned_to", "")
    if assigned_to:
        payload["assigned_to"] = assigned_to
    result = _http_post("/task/create", payload)
    if result.get("ok"):
        print(f"[automation] Task created: {result.get('task_id', '?')} for {auto_id}")
    else:
        print(f"[automation] Task creation failed for {auto_id}: {result.get('error', '?')}")
    return result


def _action_send_message(
    action: dict[str, Any], auto_id: str, created_by: str
) -> dict[str, Any]:
    """Execute send_message action via POST /send."""
    to = action.get("to", created_by)
    content = action.get("content", "")
    if not content:
        return {"ok": False, "error": "send_message action requires 'content'"}
    sender = str(action.get("from", "")).strip() or "system"
    payload = {
        "from": sender,
        "to": to,
        "content": content,
        "meta": {
            "automation_id": auto_id,
            "type": "automation_message",
            "automation_created_by": created_by,
        },
    }
    result = _http_post("/send", payload)
    if result.get("ok"):
        print(f"[automation] Message sent to {to} for {auto_id}")
    else:
        print(f"[automation] Message send failed for {auto_id}: {result.get('error', '?')}")
    return result


def _action_set_mode(
    action: dict[str, Any], auto_id: str, created_by: str
) -> dict[str, Any]:
    agent_id = str(action.get("agent_id", "")).strip()
    mode = str(action.get("mode", "")).strip()
    if not agent_id or not mode:
        return {"ok": False, "error": "set_mode action requires 'agent_id' and 'mode'"}
    result = _http_patch(f"/agents/{agent_id}/mode", {"mode": mode})
    if result.get("ok"):
        print(f"[automation] Mode set: {agent_id} -> {mode} for {auto_id}")
    else:
        print(f"[automation] Mode change failed for {auto_id}: {result.get('error', '?')}")
    return result


def _action_webhook(
    action: dict[str, Any], auto_id: str, created_by: str
) -> dict[str, Any]:
    url = str(action.get("url", "")).strip()
    method = str(action.get("method", "POST")).strip().upper() or "POST"
    headers = action.get("headers")
    body = action.get("body")
    if not url:
        return {"ok": False, "error": "webhook action requires 'url'"}
    result = _http_webhook(
        url,
        method=method,
        body=None if body is None else str(body),
        headers=headers if isinstance(headers, dict) else None,
    )
    if result.get("ok"):
        print(f"[automation] Webhook delivered for {auto_id}: {method} {url}")
    else:
        print(f"[automation] Webhook failed for {auto_id}: {result.get('error', '?')}")
    return result


def _action_chain(
    action: dict[str, Any],
    automation: dict[str, Any],
    auto_id: str,
    created_by: str,
) -> dict[str, Any]:
    actions = action.get("actions")
    if not isinstance(actions, list) or not actions:
        return {"ok": False, "error": "chain action requires non-empty 'actions' list"}
    results: list[dict[str, Any]] = []
    for idx, sub_action in enumerate(actions):
        if not isinstance(sub_action, dict):
            return {"ok": False, "error": f"chain action step {idx + 1} must be an object", "executed": idx}
        result = _execute_action_spec(sub_action, automation, auto_id, created_by)
        results.append(result)
        if not result.get("ok", False):
            return {
                "ok": False,
                "error": result.get("error", f"chain step {idx + 1} failed"),
                "executed": idx,
                "results": results,
            }
    return {"ok": True, "executed": len(results), "results": results}


def dispatch_event(event_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Trigger local event automations from the canonical event bus."""
    normalized_event = normalize_event_type(event_type)
    with AUTOMATION_LOCK:
        candidates = [
            copy.deepcopy(auto)
            for auto in AUTOMATIONS.values()
            if auto.get("active", False)
            and not _is_paused(auto)
            and auto.get("trigger", {}).get("type") == "event"
            and normalize_event_type(auto.get("trigger", {}).get("event_type", "")) == normalized_event
            and _matches_filter(payload, auto.get("trigger", {}).get("filter"))
        ]

    results: list[dict[str, Any]] = []
    callback = _scheduler._action_callback if _scheduler and _scheduler._action_callback else execute_action
    for auto in candidates:
        auto_id = auto["id"]
        try:
            result = callback(auto)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        _record_run_result(auto_id, "success" if result.get("ok", True) else "error", result.get("error"))
        results.append({"automation_id": auto_id, **result})
    return results


def dispatch_webhook(auto_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Trigger a local webhook automation by ID."""
    auto = get_automation(auto_id)
    if not auto:
        return {"ok": False, "error": f"automation '{auto_id}' not found"}
    if auto.get("trigger", {}).get("type") != "webhook":
        return {"ok": False, "error": f"automation '{auto_id}' is not a webhook trigger"}
    callback = _scheduler._action_callback if _scheduler and _scheduler._action_callback else execute_action
    try:
        result = callback(auto)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    _record_run_result(auto_id, "success" if result.get("ok", True) else "error", result.get("error"))
    return {"automation_id": auto_id, **result}


# ---------------------------------------------------------------------------
# P1-B: Prompt-Replay Action (Hybrid: bridge_send + tmux send-keys)
# ---------------------------------------------------------------------------
_PROMPT_REPLAY_MAX_LEN = 4096


def _action_prompt_replay(automation: dict[str, Any]) -> dict[str, Any]:
    """Execute prompt_replay action — 2-tier delivery.

    Stufe 1 (default): bridge_send with [SCHEDULED PROMPT] prefix.
    Stufe 2 (urgent=true): tmux send-keys if agent is at prompt, else fallback to Stufe 1.

    Returns result dict with delivery_method field for history logging.
    """
    action = automation.get("action", {})
    auto_id = automation.get("id", "unknown")
    created_by = automation.get("created_by", "system")
    assigned_to = automation.get("assigned_to", created_by)
    prompt_text = action.get("prompt", action.get("content", ""))
    urgent = action.get("urgent", False)

    if not prompt_text:
        return {"ok": False, "error": "prompt_replay requires 'prompt' or 'content'"}
    if len(prompt_text) > _PROMPT_REPLAY_MAX_LEN:
        return {"ok": False, "error": f"prompt too long ({len(prompt_text)} > {_PROMPT_REPLAY_MAX_LEN})"}

    delivery_method = "bridge_send"

    # Stufe 2: tmux send-keys (only if urgent + agent at prompt)
    if urgent:
        tmux_result = _try_tmux_prompt_replay(assigned_to, prompt_text)
        if tmux_result.get("ok"):
            tmux_result["delivery_method"] = "tmux_send_keys"
            print(f"[automation] Prompt injected via tmux for {auto_id} → {assigned_to}")
            return tmux_result
        # Fallback to Stufe 1
        print(f"[automation] tmux fallback for {auto_id}: {tmux_result.get('reason', '?')}")

    # Stufe 1: bridge_send with scheduled prompt prefix
    scheduled_content = f"[SCHEDULED PROMPT] {prompt_text}"
    payload = {
        "from": "system",
        "to": assigned_to,
        "content": scheduled_content,
        "meta": {
            "automation_id": auto_id,
            "type": "prompt_replay",
            "urgent": urgent,
            "automation_created_by": created_by,
        },
    }
    result = _http_post("/send", payload)
    result["delivery_method"] = delivery_method
    if result.get("ok"):
        print(f"[automation] Prompt sent via bridge_send for {auto_id} → {assigned_to}")
    else:
        print(f"[automation] Prompt send failed for {auto_id}: {result.get('error', '?')}")
    return result


def _try_tmux_prompt_replay(agent_id: str, prompt_text: str) -> dict[str, Any]:
    """Try to inject prompt via tmux send-keys (Stufe 2).

    Pre-checks:
    1. tmux session exists (acw_{agent_id})
    2. Agent is at input prompt (capture-pane regex check)

    Returns {"ok": True} on success, {"ok": False, "reason": ...} on failure.
    Safety: no shell=True, -l flag for literal text (no key-name interpretation).
    """
    import subprocess

    session_name = f"acw_{agent_id}"

    # Check session exists
    try:
        check = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True, timeout=5,
        )
        if check.returncode != 0:
            return {"ok": False, "reason": f"tmux session '{session_name}' not found"}
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"ok": False, "reason": f"tmux check failed: {e}"}

    # Capture pane to check if agent is at prompt
    try:
        capture = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-5"],
            capture_output=True, text=True, timeout=5,
        )
        if capture.returncode != 0:
            return {"ok": False, "reason": "capture-pane failed"}
        pane_text = capture.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"ok": False, "reason": f"capture-pane error: {e}"}

    # Check if agent is at input prompt (last non-empty lines)
    import re
    lines = [ln for ln in pane_text.strip().splitlines() if ln.strip()]
    if not lines:
        return {"ok": False, "reason": "empty pane output"}

    last_lines = "\n".join(lines[-3:])
    # Prompt patterns: "> ", "Human: ", "$ ", input waiting indicators
    prompt_pattern = re.compile(r"(^>\s*$|^❯\s*$|Human:\s*$|╰─\s*$|\$\s*$)", re.MULTILINE)
    if not prompt_pattern.search(last_lines):
        return {"ok": False, "reason": "agent not at prompt"}

    # Inject prompt via tmux send-keys
    # -l flag: literal text (prevents "Enter"/"Escape" etc. from being interpreted as keys)
    # Separate Enter call: actually submits the prompt
    try:
        send_text = subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "-l", prompt_text],
            capture_output=True, timeout=5,
        )
        if send_text.returncode != 0:
            return {"ok": False, "reason": "send-keys -l failed"}
        send_enter = subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "Enter"],
            capture_output=True, timeout=5,
        )
        if send_enter.returncode != 0:
            return {"ok": False, "reason": "send-keys Enter failed"}
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"ok": False, "reason": f"send-keys error: {e}"}

    return {"ok": True}


# ---------------------------------------------------------------------------
# Error notification (Nova-Review: notify_on_error)
# ---------------------------------------------------------------------------
def _notify_on_error(automation: dict[str, Any], error_msg: str) -> None:
    """Send error notification to created_by if notify_on_error is enabled."""
    options = automation.get("options", {})
    if not options.get("notify_on_error", True):
        return
    created_by = automation.get("created_by", "user")
    auto_name = automation.get("name", automation.get("id", "unknown"))
    content = (
        f"[Automation Fehler] '{auto_name}' ist fehlgeschlagen.\n"
        f"Fehler: {error_msg}"
    )
    try:
        _http_post("/send", {
            "from": "system",
            "to": created_by,
            "content": content,
            "meta": {
                "automation_id": automation.get("id", ""),
                "type": "automation_error",
            },
        })
    except Exception as e:
        print(f"[automation] Failed to send error notification: {e}")


# ---------------------------------------------------------------------------
# P2: Catch-Up Policy — run missed automations when agent comes online
# ---------------------------------------------------------------------------
_MAX_CATCH_UP_DEFAULT = 10


def check_catch_up(agent_id: str) -> list[dict[str, Any]]:
    """P2: Check and execute catch-up for missed automation runs.

    Called when an agent comes online (e.g. after /register).
    Returns list of catch-up results [{automation_id, runs, policy}].

    Policies:
      - "skip" (default): Do nothing for missed runs
      - "run_once": Execute one catch-up run for the most recent missed window
      - "run_all": Execute all missed runs (capped by max_catch_up_runs)
    """
    results: list[dict[str, Any]] = []

    with AUTOMATION_LOCK:
        candidates = [
            copy.deepcopy(auto) for auto in AUTOMATIONS.values()
            if auto.get("active", False)
            and not _is_paused(auto)
            and (auto.get("assigned_to") or auto.get("created_by")) == agent_id
            and auto.get("trigger", {}).get("type") == "schedule"
        ]

    now = datetime.now(timezone.utc)

    for auto in candidates:
        options = auto.get("options", {})
        policy = options.get("catch_up", "skip")
        if policy == "skip":
            continue

        # Calculate missed runs since last_run
        missed = _count_missed_runs(auto, now)
        if missed <= 0:
            continue

        max_catch_up = options.get("max_catch_up_runs", _MAX_CATCH_UP_DEFAULT)
        if policy == "run_once":
            runs_to_execute = 1
        else:  # run_all
            runs_to_execute = min(missed, max_catch_up)

        auto_id = auto["id"]
        print(f"[automation] Catch-up: {auto_id} missed={missed}, policy={policy}, executing={runs_to_execute}")

        executed = 0
        scheduler = get_scheduler()
        for _ in range(runs_to_execute):
            if scheduler and scheduler._action_callback:
                try:
                    result = scheduler._action_callback(auto)
                    ok = isinstance(result, dict) and result.get("ok", True)
                except Exception as exc:
                    ok = False
                    _catch_up_error = str(exc)
                else:
                    _catch_up_error = None
                # BUG-2 Fix: Log catch-up execution to history
                _catch_up_details: dict[str, Any] = {"catch_up": True, "policy": policy}
                if _catch_up_error:
                    _catch_up_details["error"] = _catch_up_error
                    print(f"[automation] Catch-up execution failed for {auto_id}: {_catch_up_error}")
                log_execution(auto_id, "success" if ok else "error", _catch_up_details)
                if ok:
                    executed += 1
                else:
                    break  # Stop on first failure

        # Update last_run + next_run (BUG-1 Fix: recalculate next_run to prevent re-fire)
        with AUTOMATION_LOCK:
            live_auto = AUTOMATIONS.get(auto_id)
            if live_auto:
                live_auto["last_run"] = now.isoformat()
                live_auto["run_count"] = live_auto.get("run_count", 0) + executed
                # BUG-1 Fix: Recalculate next_run (same logic as _update_after_run)
                trigger = live_auto.get("trigger", {})
                cron_expr = trigger.get("cron")
                if cron_expr:
                    tz_name = trigger.get("timezone", "UTC")
                    next_run_iso = compute_next_run(cron_expr, tz_name)
                    if next_run_iso:
                        jitter_secs = _compute_jitter(auto_id, _cron_interval_seconds(cron_expr))
                        if jitter_secs > 0:
                            from datetime import timedelta
                            nr_dt = datetime.fromisoformat(next_run_iso)
                            next_run_iso = (nr_dt + timedelta(seconds=jitter_secs)).isoformat()
                    live_auto["next_run"] = next_run_iso
                _save_automations_to_disk()

        results.append({
            "automation_id": auto_id,
            "missed": missed,
            "executed": executed,
            "policy": policy,
        })

    return results


def _count_missed_runs(automation: dict[str, Any], now: datetime) -> int:
    """Count how many scheduled runs were missed since last_run."""
    if not HAS_CRONITER:
        return 0

    trigger = automation.get("trigger", {})
    cron_expr = trigger.get("cron")
    if not cron_expr:
        return 0

    last_run_str = automation.get("last_run")
    if not last_run_str:
        # Never ran — count from created_at
        last_run_str = automation.get("created_at")
        if not last_run_str:
            return 0

    try:
        from croniter import croniter as _croniter
        tz_name = trigger.get("timezone", "UTC")
        tz = ZoneInfo(tz_name)
        last_run = datetime.fromisoformat(last_run_str)
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)

        cron = _croniter(cron_expr, last_run.astimezone(tz))
        missed = 0
        while True:
            next_time = cron.get_next(datetime)
            if next_time.astimezone(timezone.utc) > now:
                break
            missed += 1
            if missed > 1000:  # Safety cap
                print(f"[automation] WARNING: _count_missed_runs hit 1000 cap for cron={cron_expr}")
                break
        return missed
    except Exception as exc:
        print(f"[automation] WARNING: _count_missed_runs failed for automation: {exc}")
        return 0


# ---------------------------------------------------------------------------
# Module-level scheduler instance
# ---------------------------------------------------------------------------
_scheduler: AutomationScheduler | None = None


def get_scheduler() -> AutomationScheduler | None:
    """Return the running scheduler instance, or None."""
    return _scheduler


# ---------------------------------------------------------------------------
# Init (called by server.py at startup)
# ---------------------------------------------------------------------------
def init_automations(
    action_callback: Callable[[dict[str, Any]], Any] | None = None,
    server_port: int = 9111,
    idle_check_callback: Callable[[str], bool | None] | None = None,  # P0-A
    condition_context_callback: Callable[[], dict[str, Any]] | None = None,
) -> AutomationScheduler:
    """Load automations from disk and start scheduler. Called once at server startup.

    Args:
        action_callback: Function to call when an automation triggers.
                        Receives the automation dict. Defaults to execute_action().
        server_port: Local server port for HTTP action calls.
        idle_check_callback: Optional function that checks if an agent is idle.
                           Returns True (idle), False (busy), None (offline). P0-A.
        condition_context_callback: Optional function returning runtime context for
                           local condition-trigger evaluation.

    Returns:
        The running AutomationScheduler instance.
    """
    global _scheduler
    set_server_port(server_port)
    _load_automations_from_disk()

    callback = action_callback or execute_action
    _scheduler = AutomationScheduler(
        action_callback=callback,
        idle_check_callback=idle_check_callback,
        condition_context_callback=condition_context_callback,
    )
    _scheduler.start()
    return _scheduler
