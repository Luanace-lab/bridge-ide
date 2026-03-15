#!/usr/bin/env python3
"""
doc_trigger.py - Activity-driven documentation trigger daemon.

Primary trigger:
- Poll /activity every 10s.
- Detect editing -> idle transitions (explicit or 30s inactivity timeout).
- On transition, collect tracked file changes since last trigger and notify techwriter.

Fallback trigger:
- Watch tracked paths with watchdog/inotify.
- Debounce for 60s to avoid noisy notifications.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from common import http_get_json, send_message

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - dependency may be missing in some envs
    FileSystemEvent = Any  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment]
    Observer = None  # type: ignore[assignment]

BRIDGE_SERVER = "http://127.0.0.1:9111"
POLL_INTERVAL_SECONDS = 10.0
IDLE_THRESHOLD_SECONDS = 30.0
FALLBACK_DEBOUNCE_SECONDS = 60.0

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
PID_FILE = Path("/tmp/doc_trigger.pid")
LOG_FILE = ROOT_DIR / "Backend" / "logs" / "doc_trigger.log"

AGENT_CONFIG_FILES = {"CLAUDE.md", "SOUL.md"}
FRONTEND_EXTENSIONS = {".html", ".js", ".css"}

_STOP_EVENT = threading.Event()


@dataclass
class AgentState:
    mode: str = "unknown"
    last_activity_ts: float = 0.0
    last_event_ts: float = 0.0
    last_edit_ts: float = 0.0
    last_triggered_edit_ts: float = 0.0


class FallbackAccumulator:
    """Thread-safe container for fallback filesystem changes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._changes: dict[str, str] = {}
        self._last_event_ts: float = 0.0

    def add(self, path: Path) -> None:
        area = classify_path(path)
        if not area:
            return
        rel = to_rel_path(path)
        with self._lock:
            self._changes[rel] = area
            self._last_event_ts = time.time()

    def pop_if_ready(self, now_ts: float, debounce_seconds: float) -> list[tuple[str, str]]:
        with self._lock:
            if not self._changes:
                return []
            if (now_ts - self._last_event_ts) < debounce_seconds:
                return []
            ready = sorted(self._changes.items())
            self._changes.clear()
            self._last_event_ts = 0.0
            return ready


class DocEventHandler(FileSystemEventHandler):
    """Collect watchdog events for fallback notifications."""

    def __init__(self, accumulator: FallbackAccumulator) -> None:
        super().__init__()
        self._accumulator = accumulator

    def on_any_event(self, event: FileSystemEvent) -> None:
        if getattr(event, "is_directory", False):
            return
        src_path = getattr(event, "src_path", "")
        if src_path:
            self._accumulator.add(Path(src_path))
        dest_path = getattr(event, "dest_path", "")
        if dest_path:
            self._accumulator.add(Path(dest_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bridge doc trigger daemon")
    parser.add_argument("--server", default=BRIDGE_SERVER, help="Bridge API base URL")
    parser.add_argument("--poll", type=float, default=POLL_INTERVAL_SECONDS, help="Activity poll interval in seconds")
    parser.add_argument("--idle", type=float, default=IDLE_THRESHOLD_SECONDS, help="Idle threshold in seconds")
    parser.add_argument(
        "--fallback-debounce",
        type=float,
        default=FALLBACK_DEBOUNCE_SECONDS,
        help="Fallback debounce interval in seconds",
    )
    return parser.parse_args()


def setup_logger() -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("doc_trigger")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)sZ | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    rotating = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    rotating.setFormatter(formatter)
    logger.addHandler(rotating)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    return logger


def parse_iso_timestamp(ts_value: str | None) -> float:
    if not ts_value:
        return 0.0
    raw = ts_value.strip()
    if not raw:
        return 0.0
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _release_pid_lock() -> None:
    if not PID_FILE.exists():
        return
    try:
        stored_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if stored_pid == os.getpid():
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass


def acquire_pid_lock(logger: logging.Logger) -> None:
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            old_pid = 0
        if old_pid > 0 and _is_pid_alive(old_pid):
            logger.error("doc_trigger already running with PID %s", old_pid)
            raise SystemExit(1)
        logger.warning("stale pid file found at %s, overwriting", PID_FILE)

    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(_release_pid_lock)


def to_rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.name


def should_ignore(path: Path) -> bool:
    name_lower = path.name.lower()
    if "__pycache__" in path.parts:
        return True
    if name_lower.endswith(".pyc"):
        return True
    if ".bak" in name_lower:
        return True
    return False


def classify_path(path: Path) -> str | None:
    try:
        resolved = path.resolve()
        rel = resolved.relative_to(ROOT_DIR)
    except ValueError:
        return None

    if should_ignore(rel):
        return None

    if not rel.parts:
        return None

    top = rel.parts[0]
    suffix = resolved.suffix.lower()

    if top == "Backend" and suffix == ".py":
        return "Backend"
    if top == "Frontend" and suffix in FRONTEND_EXTENSIONS:
        return "Frontend"
    if top == "Architecture" and suffix == ".md":
        return "Architecture"
    if len(rel.parts) == 2 and rel.name in AGENT_CONFIG_FILES:
        return "Agent-Config"
    return None


def iter_tracked_files() -> list[Path]:
    collected: list[Path] = []

    backend_dir = ROOT_DIR / "Backend"
    frontend_dir = ROOT_DIR / "Frontend"
    architecture_dir = ROOT_DIR / "Architecture"

    if backend_dir.exists():
        collected.extend(backend_dir.rglob("*.py"))
    if frontend_dir.exists():
        for ext in FRONTEND_EXTENSIONS:
            collected.extend(frontend_dir.rglob(f"*{ext}"))
    if architecture_dir.exists():
        collected.extend(architecture_dir.rglob("*.md"))

    collected.extend(ROOT_DIR.glob("*/CLAUDE.md"))
    collected.extend(ROOT_DIR.glob("*/SOUL.md"))

    return collected


def collect_changes_since(last_trigger_ts: float) -> list[tuple[str, str]]:
    changed: dict[str, str] = {}
    for candidate in iter_tracked_files():
        try:
            stat = candidate.stat()
        except OSError:
            continue
        if stat.st_mtime <= last_trigger_ts:
            continue
        area = classify_path(candidate)
        if not area:
            continue
        rel = to_rel_path(candidate)
        changed[rel] = area
    return sorted(changed.items())


def fetch_activities(server: str, logger: logging.Logger) -> list[dict[str, Any]]:
    try:
        payload = http_get_json(f"{server.rstrip('/')}/activity", timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to read /activity: %s", exc)
        return []
    activities = payload.get("activities", [])
    if not isinstance(activities, list):
        return []
    return [entry for entry in activities if isinstance(entry, dict)]


def detect_idle_transitions(
    activities: list[dict[str, Any]],
    states: dict[str, AgentState],
    now_ts: float,
    idle_seconds: float,
) -> list[tuple[str, str]]:
    triggers: list[tuple[str, str]] = []

    for entry in activities:
        agent_id = str(entry.get("agent_id", "")).strip()
        if not agent_id:
            continue
        action = str(entry.get("action", "")).strip().lower()
        event_ts = parse_iso_timestamp(str(entry.get("timestamp", "")).strip())
        if event_ts <= 0.0:
            event_ts = now_ts

        state = states.setdefault(agent_id, AgentState())
        if event_ts > state.last_event_ts:
            previous_mode = state.mode
            state.last_event_ts = event_ts
            state.last_activity_ts = event_ts
            state.mode = action or "idle"

            if action == "editing":
                state.last_edit_ts = event_ts
            elif previous_mode == "editing" and state.last_edit_ts > state.last_triggered_edit_ts:
                state.last_triggered_edit_ts = state.last_edit_ts
                triggers.append((agent_id, "activity_transition"))

    for agent_id, state in states.items():
        if state.mode != "editing":
            continue
        if state.last_edit_ts <= state.last_triggered_edit_ts:
            continue
        if (now_ts - state.last_edit_ts) < idle_seconds:
            continue
        state.last_triggered_edit_ts = state.last_edit_ts
        state.mode = "idle_timeout"
        triggers.append((agent_id, "idle_timeout"))

    return triggers


def infer_best_effort_agent(states: dict[str, AgentState], preferred_agent: str | None, now_ts: float) -> str:
    if preferred_agent:
        return preferred_agent

    latest_agent: str | None = None
    latest_ts = 0.0
    for agent_id, state in states.items():
        if state.last_activity_ts > latest_ts:
            latest_ts = state.last_activity_ts
            latest_agent = agent_id

    if latest_agent and (now_ts - latest_ts) <= 300.0:
        return latest_agent
    return "unknown"


def render_content(changes: list[tuple[str, str]], agent_id: str) -> str:
    files = [path for path, _ in changes]
    areas = sorted({area for _, area in changes})
    max_items = 50
    shown = files[:max_items]
    if len(files) > max_items:
        shown.append(f"... +{len(files) - max_items} weitere")
    return (
        f"Aenderungen erkannt: [{', '.join(shown)}], "
        f"Bereich: [{', '.join(areas)}], "
        f"Agent: [{agent_id}]"
    )


def notify_techwriter(
    server: str,
    changes: list[tuple[str, str]],
    agent_id: str,
    source: str,
    logger: logging.Logger,
) -> bool:
    if not changes:
        return False
    content = render_content(changes, agent_id)
    try:
        response = send_message(server, "doc_trigger", "techwriter", content, timeout=15.0)
        msg = response.get("message", {}) if isinstance(response, dict) else {}
        message_id = msg.get("id", "n/a")
        logger.info(
            "notify source=%s msg_id=%s files=%s areas=%s agent=%s",
            source,
            message_id,
            len(changes),
            ",".join(sorted({a for _, a in changes})),
            agent_id,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("notify failed source=%s files=%s agent=%s err=%s", source, len(changes), agent_id, exc)
        return False


def filter_recent_changes(changes: list[tuple[str, str]], since_ts: float) -> list[tuple[str, str]]:
    filtered: list[tuple[str, str]] = []
    for rel_path, area in changes:
        abs_path = ROOT_DIR / rel_path
        try:
            mtime = abs_path.stat().st_mtime
        except OSError:
            continue
        if mtime > since_ts:
            filtered.append((rel_path, area))
    return filtered


def start_fallback_observer(accumulator: FallbackAccumulator, logger: logging.Logger) -> Any | None:
    if Observer is None:
        logger.warning("watchdog dependency missing; inotify fallback disabled")
        return None

    observer = Observer()
    handler = DocEventHandler(accumulator)
    observer.schedule(handler, str(ROOT_DIR), recursive=True)
    observer.start()
    logger.info("fallback observer active on %s", ROOT_DIR)
    return observer


def stop_fallback_observer(observer: Any | None, logger: logging.Logger) -> None:
    if observer is None:
        return
    try:
        observer.stop()
        observer.join(timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to stop fallback observer cleanly: %s", exc)


def install_signal_handlers() -> None:
    def _handle_signal(signum: int, _frame: Any) -> None:
        _STOP_EVENT.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)


def run() -> int:
    args = parse_args()
    logger = setup_logger()
    acquire_pid_lock(logger)
    install_signal_handlers()

    logger.info("doc_trigger started pid=%s", os.getpid())
    logger.info(
        "config server=%s poll=%.1fs idle=%.1fs fallback_debounce=%.1fs",
        args.server,
        args.poll,
        args.idle,
        args.fallback_debounce,
    )

    accumulator = FallbackAccumulator()
    observer = start_fallback_observer(accumulator, logger)
    states: dict[str, AgentState] = {}
    last_trigger_ts = time.time()

    try:
        while not _STOP_EVENT.is_set():
            loop_started = time.time()

            activities = fetch_activities(args.server, logger)
            triggers = detect_idle_transitions(activities, states, loop_started, args.idle)

            for agent_id, reason in triggers:
                changed = collect_changes_since(last_trigger_ts)
                if not changed:
                    logger.info("activity trigger reason=%s agent=%s no tracked changes", reason, agent_id)
                    continue
                best_effort_agent = infer_best_effort_agent(states, agent_id, time.time())
                if notify_techwriter(args.server, changed, best_effort_agent, f"activity:{reason}", logger):
                    last_trigger_ts = time.time()

            fallback_changes = accumulator.pop_if_ready(time.time(), args.fallback_debounce)
            if fallback_changes:
                filtered = filter_recent_changes(fallback_changes, last_trigger_ts)
                if filtered:
                    best_effort_agent = infer_best_effort_agent(states, None, time.time())
                    if notify_techwriter(args.server, filtered, best_effort_agent, "fallback", logger):
                        last_trigger_ts = time.time()
                else:
                    logger.info("fallback trigger ready but no changes newer than last trigger")

            elapsed = time.time() - loop_started
            sleep_for = max(args.poll - elapsed, 0.1)
            _STOP_EVENT.wait(sleep_for)
    finally:
        stop_fallback_observer(observer, logger)
        _release_pid_lock()
        logger.info("doc_trigger stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
