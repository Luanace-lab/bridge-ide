#!/usr/bin/env python3
"""Minimal Bridge liveness supervisor for long-running agent loops.

The supervisor does not invent a new recovery path. It only observes Bridge
state and uses the existing POST /agents/{id}/start endpoint, which already
implements the canonical "start or nudge" behavior on the server side.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from common import build_bridge_auth_headers


DEFAULT_BRIDGE_URL = "http://127.0.0.1:9111"
DEFAULT_INTERVAL_SECONDS = 60.0
DEFAULT_STALE_SECONDS = 120.0
DEFAULT_COOLDOWN_SECONDS = 300.0
DEFAULT_DURATION_SECONDS = 8 * 60 * 60
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_LOG_FILE = Path(__file__).resolve().parent / "logs" / "agent_liveness_supervisor.log"
DEFAULT_PID_FILE = Path(__file__).resolve().parent / "pids" / "agent_liveness_supervisor.pid"
DISCONNECTED_STATUSES = {"disconnected", "offline", "dead"}


@dataclass(slots=True)
class AgentSnapshot:
    agent_id: str
    status: str
    online: bool
    tmux_alive: bool
    last_heartbeat_age: float | None
    last_activity_age: float | None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(ts_raw: Any) -> datetime | None:
    text = str(ts_raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _activity_age_seconds(payload: dict[str, Any], now_ts: float | None = None) -> float | None:
    entries = payload.get("activities")
    if not isinstance(entries, list) or not entries:
        return None
    newest: datetime | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        parsed = _parse_timestamp(entry.get("timestamp"))
        if parsed is None:
            continue
        if newest is None or parsed > newest:
            newest = parsed
    if newest is None:
        return None
    if now_ts is None:
        now_ts = time.time()
    return max(now_ts - newest.timestamp(), 0.0)


def decide_agent_action(
    snapshot: AgentSnapshot,
    *,
    stale_seconds: float,
    cooldown_seconds: float,
    now_ts: float,
    last_action_at: float | None,
) -> str:
    """Return one of: healthy, cooldown, start_or_nudge."""
    if last_action_at is not None and (now_ts - last_action_at) < cooldown_seconds:
        return "cooldown"
    if not snapshot.online:
        return "start_or_nudge"
    if snapshot.status.strip().lower() in DISCONNECTED_STATUSES:
        return "start_or_nudge"
    if not snapshot.tmux_alive:
        return "start_or_nudge"
    if snapshot.last_heartbeat_age is None:
        return "healthy"
    if snapshot.last_heartbeat_age >= stale_seconds:
        return "start_or_nudge"
    return "healthy"


class BridgeApiClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BRIDGE_URL,
        operator_id: str = "user",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.operator_id = str(operator_id).strip() or "user"
        self.timeout_seconds = max(float(timeout_seconds), 1.0)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_payload = None
        headers = build_bridge_auth_headers(agent_id=self.operator_id)
        if payload is not None:
            raw_payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = Request(
            f"{self.base_url}{path}",
            data=raw_payload,
            method=method,
            headers=headers,
        )
        with urlopen(req, timeout=self.timeout_seconds) as response:  # noqa: S310
            body = response.read().decode("utf-8")
        return json.loads(body)

    def get_runtime_agent_ids(self) -> list[str]:
        payload = self._request_json("GET", "/runtime")
        ids = payload.get("agent_ids")
        if isinstance(ids, list):
            return [str(item).strip() for item in ids if str(item).strip()]
        agents = payload.get("agents")
        if not isinstance(agents, list):
            return []
        result: list[str] = []
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            agent_id = str(agent.get("id", "")).strip()
            if agent_id:
                result.append(agent_id)
        return result

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/agents/{quote(agent_id)}")

    def get_activity(self, agent_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/activity?agent_id={quote(agent_id)}")

    def start_or_nudge(self, agent_id: str) -> dict[str, Any]:
        return self._request_json("POST", f"/agents/{quote(agent_id)}/start", payload={"from": self.operator_id})


class AgentLivenessSupervisor:
    def __init__(
        self,
        client: BridgeApiClient,
        *,
        stale_seconds: float = DEFAULT_STALE_SECONDS,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        log_file: Path = DEFAULT_LOG_FILE,
    ) -> None:
        self.client = client
        self.stale_seconds = max(float(stale_seconds), 1.0)
        self.cooldown_seconds = max(float(cooldown_seconds), 0.0)
        self.log_file = Path(log_file)
        self._last_actions: dict[str, float] = {}

    def _log(self, event: dict[str, Any]) -> None:
        event.setdefault("timestamp", _utc_now_iso())
        line = json.dumps(event, ensure_ascii=False)
        print(line, flush=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def snapshot_agent(self, agent_id: str, *, now_ts: float | None = None) -> AgentSnapshot:
        if now_ts is None:
            now_ts = time.time()
        agent_payload = self.client.get_agent(agent_id)
        activity_payload = self.client.get_activity(agent_id)
        last_hb_raw = agent_payload.get("last_heartbeat_age")
        try:
            last_hb_age = float(last_hb_raw) if last_hb_raw is not None else None
        except (TypeError, ValueError):
            last_hb_age = None
        return AgentSnapshot(
            agent_id=agent_id,
            status=str(agent_payload.get("status", "") or "").strip(),
            online=bool(agent_payload.get("online", agent_payload.get("active", False))),
            tmux_alive=bool(agent_payload.get("tmux_alive", False)),
            last_heartbeat_age=last_hb_age,
            last_activity_age=_activity_age_seconds(activity_payload, now_ts=now_ts),
        )

    def run_once(self, agent_ids: list[str], *, now_ts: float | None = None) -> list[dict[str, Any]]:
        if now_ts is None:
            now_ts = time.time()
        results: list[dict[str, Any]] = []
        for agent_id in agent_ids:
            snapshot = self.snapshot_agent(agent_id, now_ts=now_ts)
            last_action_at = self._last_actions.get(agent_id)
            action = decide_agent_action(
                snapshot,
                stale_seconds=self.stale_seconds,
                cooldown_seconds=self.cooldown_seconds,
                now_ts=now_ts,
                last_action_at=last_action_at,
            )
            result: dict[str, Any] = {
                "agent_id": agent_id,
                "action": action,
                "status": snapshot.status,
                "online": snapshot.online,
                "tmux_alive": snapshot.tmux_alive,
                "last_heartbeat_age": snapshot.last_heartbeat_age,
                "last_activity_age": snapshot.last_activity_age,
            }
            if action == "start_or_nudge":
                result["start_result"] = self.client.start_or_nudge(agent_id)
                self._last_actions[agent_id] = now_ts
            elif action == "cooldown":
                result["cooldown_remaining"] = round(
                    max(self.cooldown_seconds - (now_ts - float(last_action_at or 0.0)), 0.0),
                    1,
                )
            self._log({"type": "agent_supervisor_iteration", **result})
            results.append(result)
        return results


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minimal Bridge agent liveness supervisor")
    parser.add_argument("--server", default=DEFAULT_BRIDGE_URL, help=f"Bridge HTTP base URL (default: {DEFAULT_BRIDGE_URL})")
    parser.add_argument("--operator-id", default="user", help="Caller identity for authenticated Bridge requests (default: user)")
    parser.add_argument("--agent", action="append", default=[], help="Agent ID to supervise. Repeat flag for multiple agents.")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS, help=f"Loop interval in seconds (default: {DEFAULT_INTERVAL_SECONDS})")
    parser.add_argument("--stale-seconds", type=float, default=DEFAULT_STALE_SECONDS, help=f"Heartbeat age before start-or-nudge (default: {DEFAULT_STALE_SECONDS})")
    parser.add_argument("--cooldown-seconds", type=float, default=DEFAULT_COOLDOWN_SECONDS, help=f"Per-agent cooldown after an action (default: {DEFAULT_COOLDOWN_SECONDS})")
    parser.add_argument("--duration-seconds", type=float, default=DEFAULT_DURATION_SECONDS, help=f"Maximum runtime in seconds (default: {DEFAULT_DURATION_SECONDS})")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS, help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS})")
    parser.add_argument("--log-file", default=str(DEFAULT_LOG_FILE), help=f"JSONL log path (default: {DEFAULT_LOG_FILE})")
    parser.add_argument("--pid-file", default=str(DEFAULT_PID_FILE), help=f"PID lock path (default: {DEFAULT_PID_FILE})")
    parser.add_argument("--once", action="store_true", help="Run exactly one supervisor iteration")
    return parser.parse_args(argv)


def _resolve_agent_ids(client: BridgeApiClient, explicit_agent_ids: list[str]) -> list[str]:
    if explicit_agent_ids:
        return [agent_id for agent_id in (str(item).strip() for item in explicit_agent_ids) if agent_id]
    return client.get_runtime_agent_ids()


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_pid_lock(pid_file: str | Path) -> tuple[Path, bool]:
    path = Path(pid_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing_pid = int(path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            existing_pid = 0
        if _pid_is_alive(existing_pid):
            return path, False
        try:
            path.unlink()
        except OSError:
            pass
    path.write_text(str(os.getpid()), encoding="utf-8")
    return path, True


def release_pid_lock(pid_file: str | Path) -> None:
    path = Path(pid_file)
    try:
        if path.exists() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    client = BridgeApiClient(
        base_url=args.server,
        operator_id=args.operator_id,
        timeout_seconds=args.timeout_seconds,
    )
    supervisor = AgentLivenessSupervisor(
        client,
        stale_seconds=args.stale_seconds,
        cooldown_seconds=args.cooldown_seconds,
        log_file=Path(args.log_file),
    )
    pid_file, acquired = acquire_pid_lock(args.pid_file)
    if not acquired:
        print(json.dumps({"ok": False, "error": f"supervisor already running: {pid_file}"}), file=sys.stderr)
        return 3
    atexit.register(release_pid_lock, pid_file)

    should_stop = False

    def _handle_signal(_signum: int, _frame: Any) -> None:
        nonlocal should_stop
        should_stop = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    explicit_agent_ids = _resolve_agent_ids(client, args.agent)
    if args.agent and not explicit_agent_ids:
        print(json.dumps({"ok": False, "error": "no explicit agent ids resolved"}), file=sys.stderr)
        return 2

    started_at = time.time()
    interval = max(float(args.interval), 1.0)
    deadline = None if args.once else started_at + max(float(args.duration_seconds), 1.0)

    while not should_stop:
        try:
            agent_ids = explicit_agent_ids or client.get_runtime_agent_ids()
            if not agent_ids:
                supervisor._log({
                    "type": "agent_supervisor_runtime_empty",
                    "reason": "no runtime agents resolved",
                })
            else:
                supervisor.run_once(agent_ids)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            supervisor._log({
                "type": "agent_supervisor_error",
                "error": str(exc),
                "agent_ids": explicit_agent_ids,
            })
            if args.once:
                return 1
        if args.once:
            break
        if deadline is not None and time.time() >= deadline:
            break
        time.sleep(interval)

    supervisor._log({
        "type": "agent_supervisor_exit",
        "agent_ids": explicit_agent_ids,
        "uptime_seconds": round(time.time() - started_at, 1),
        "stopped": should_stop,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
