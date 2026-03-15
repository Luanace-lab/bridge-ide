#!/usr/bin/env python3
"""
bridge_watchdog.py — Cross-platform health watchdog for Bridge Server.

Checks if the Bridge server is reachable. If not, runs start_platform.sh
to bring everything back up. Designed to be called by:
  - cron (Linux/macOS)
  - launchd (macOS)
  - Task Scheduler (Windows)
  - or as a standalone daemon (python3 bridge_watchdog.py --daemon)

Usage:
  python3 bridge_watchdog.py              # Single check (for cron/scheduler)
  python3 bridge_watchdog.py --daemon     # Continuous loop (every 60s)
  python3 bridge_watchdog.py --interval 30 --daemon  # Custom interval
"""

import argparse
import logging
import os
import platform
import subprocess
import time
import urllib.request
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent
LOG_FILE = BRIDGE_DIR / "logs" / "watchdog.log"
HEALTH_URL = os.environ.get("BRIDGE_HEALTH_URL", "http://127.0.0.1:9111/health")
HEALTH_TIMEOUT = 5
DEFAULT_INTERVAL = 60
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB

START_SCRIPT = (
    BRIDGE_DIR / "start_platform.sh"
    if platform.system() != "Windows"
    else BRIDGE_DIR / "start_platform.ps1"
)


def setup_logging() -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_SIZE:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()[-200:]
        LOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    logger = logging.getLogger("bridge_watchdog")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


def is_server_healthy() -> bool:
    try:
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=HEALTH_TIMEOUT) as resp:
            return resp.status == 200
    except Exception:
        return False


def restart_server(log: logging.Logger) -> bool:
    if not START_SCRIPT.exists():
        log.error("Start script not found: %s", START_SCRIPT)
        return False

    log.info("Server DOWN — running %s", START_SCRIPT.name)

    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(START_SCRIPT)],
                cwd=str(BRIDGE_DIR),
                timeout=300,
                capture_output=True,
                text=True,
            )
        else:
            result = subprocess.run(
                ["bash", str(START_SCRIPT)],
                cwd=str(BRIDGE_DIR),
                timeout=300,
                capture_output=True,
                text=True,
            )

        if result.returncode == 0:
            log.info("start_platform completed (exit 0)")
        else:
            log.error(
                "start_platform failed (exit %d): %s",
                result.returncode,
                result.stderr[-500:] if result.stderr else "no stderr",
            )
            return False
    except subprocess.TimeoutExpired:
        log.error("start_platform timed out after 300s")
        return False
    except Exception as exc:
        log.error("start_platform error: %s", exc)
        return False

    # Verify server came back
    time.sleep(3)
    if is_server_healthy():
        log.info("Server recovered successfully")
        return True
    else:
        log.error("Server still unreachable after restart")
        return False


def check_once(log: logging.Logger) -> None:
    if is_server_healthy():
        return
    log.warning("Health check FAILED (%s)", HEALTH_URL)
    # Double-check after 5s to avoid false positives during restarts
    time.sleep(5)
    if is_server_healthy():
        log.info("Server recovered on recheck — false alarm")
        return
    restart_server(log)


def run_daemon(log: logging.Logger, interval: int) -> None:
    log.info("Watchdog daemon started (interval=%ds, pid=%d)", interval, os.getpid())
    pid_file = BRIDGE_DIR / "pids" / "watchdog.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    try:
        while True:
            check_once(log)
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("Watchdog stopped (SIGINT)")
    finally:
        if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
            pid_file.unlink(missing_ok=True)


def print_setup_instructions() -> None:
    system = platform.system()
    script = str(Path(__file__).resolve())

    print("\n=== Bridge Watchdog Setup ===\n")

    if system == "Linux":
        print("# Linux (cron) — check every 2 minutes:")
        print(f'(crontab -l 2>/dev/null; echo "*/2 * * * * python3 {script}") | crontab -')
        print()
        print("# Or as daemon (runs in background):")
        print(f"nohup python3 {script} --daemon > /dev/null 2>&1 &")

    elif system == "Darwin":
        print("# macOS (cron) — check every 2 minutes:")
        print(f'(crontab -l 2>/dev/null; echo "*/2 * * * * python3 {script}") | crontab -')
        print()
        print("# Or as daemon:")
        print(f"nohup python3 {script} --daemon > /dev/null 2>&1 &")

    elif system == "Windows":
        print("# Windows (Task Scheduler) — check every 2 minutes:")
        print(f'schtasks /create /tn "BridgeWatchdog" /tr "python3 {script}" /sc minute /mo 2 /f')
        print()
        print("# Or as daemon (PowerShell):")
        print(f"Start-Process python3 -ArgumentList '{script} --daemon' -WindowStyle Hidden")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge Server health watchdog")
    parser.add_argument("--daemon", action="store_true", help="Run as continuous daemon")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Check interval in seconds (daemon mode)")
    parser.add_argument("--setup", action="store_true", help="Print setup instructions for this platform")
    args = parser.parse_args()

    if args.setup:
        print_setup_instructions()
        return

    log = setup_logging()

    if args.daemon:
        run_daemon(log, args.interval)
    else:
        check_once(log)


if __name__ == "__main__":
    main()
