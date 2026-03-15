from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import httpx

from ._backend_path import backend_dir

DEFAULT_SERVER_URL = "http://127.0.0.1:9111"


def _backend_script(script_name: str) -> Path:
    script = backend_dir() / script_name
    if not script.exists():
        raise FileNotFoundError(f"Backend script not found: {script}")
    return script


def _default_team_config() -> dict[str, object]:
    return {
        "team": {"name": "bridge-default", "lead": "buddy"},
        "agents": [
            {
                "id": "buddy",
                "role": "assistant",
                "description": "Onboarding and setup helper",
            }
        ],
    }


def _default_agents_conf() -> str:
    return "\n".join(
        [
            "# bridge-ide init generated config",
            "buddy:assistant",
            "",
        ]
    )


def _generate_cred_key() -> str:
    try:
        from cryptography.fernet import Fernet

        return Fernet.generate_key().decode("utf-8")
    except Exception:
        return secrets.token_urlsafe(32)


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    for rel_dir in ("logs", "pids", "messages", "config", ".bridge"):
        (target / rel_dir).mkdir(parents=True, exist_ok=True)

    team_path = target / "team.json"
    if not team_path.exists():
        team_path.write_text(
            json.dumps(_default_team_config(), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    agents_conf = target / "agents.conf"
    if not agents_conf.exists():
        agents_conf.write_text(_default_agents_conf(), encoding="utf-8")

    cred_key_path = target / ".bridge" / "cred_key"
    if not cred_key_path.exists():
        cred_key_path.write_text(_generate_cred_key() + "\n", encoding="utf-8")
        try:
            cred_key_path.chmod(0o600)
        except OSError:
            pass

    print(f"bridge-ide init complete: {target}")
    return 0


def _run_script(script: Path) -> int:
    subprocess.run([str(script)], cwd=str(script.parent), check=True)
    return 0


def cmd_start(_: argparse.Namespace) -> int:
    try:
        return _run_script(_backend_script("start_platform.sh"))
    except FileNotFoundError:
        pass

    server_py = backend_dir() / "server.py"
    if not server_py.exists():
        print(f"bridge-ide start failed: server.py not found at {server_py}", file=sys.stderr)
        return 1
    try:
        print(f"Starting server.py directly: {server_py}")
        subprocess.run(
            [sys.executable, "-u", str(server_py)],
            cwd=str(server_py.parent),
            check=True,
        )
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"bridge-ide start failed with exit code {exc.returncode}", file=sys.stderr)
        return 1


def cmd_stop(_: argparse.Namespace) -> int:
    try:
        return _run_script(_backend_script("stop_platform.sh"))
    except FileNotFoundError:
        pass

    try:
        resp = httpx.post(DEFAULT_SERVER_URL + "/system/shutdown", json={"graceful": True}, timeout=10.0)
        resp.raise_for_status()
        print("Bridge server shutdown initiated.")
        return 0
    except httpx.HTTPError as exc:
        print(f"bridge-ide stop failed: {exc}", file=sys.stderr)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    endpoint = args.url.rstrip("/") + "/status"
    try:
        response = httpx.get(endpoint, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Bridge server not reachable at {endpoint}: {exc}", file=sys.stderr)
        return 1

    print(response.text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bridge-ide", description="Bridge IDE setup CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_init = subparsers.add_parser("init", help="Initialize project scaffolding")
    parser_init.add_argument("path", nargs="?", default=".")
    parser_init.set_defaults(func=cmd_init)

    parser_start = subparsers.add_parser("start", help="Start Bridge platform")
    parser_start.set_defaults(func=cmd_start)

    parser_stop = subparsers.add_parser("stop", help="Stop Bridge platform")
    parser_stop.set_defaults(func=cmd_stop)

    parser_status = subparsers.add_parser("status", help="Show platform status")
    parser_status.add_argument("--url", default=DEFAULT_SERVER_URL)
    parser_status.set_defaults(func=cmd_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
