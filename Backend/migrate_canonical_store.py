#!/usr/bin/env python3
"""One-time migration: seed canonical agent store from existing artifacts.

Usage:
    python3 migrate_canonical_store.py --dry-run    # Preview
    python3 migrate_canonical_store.py              # Execute
    python3 migrate_canonical_store.py --verify     # Verify
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
TEAM_JSON = BACKEND_DIR / "team.json"

sys.path.insert(0, str(BACKEND_DIR))
import canonical_store
from persistence_utils import find_agent_memory_path, resolve_agent_cli_layout
from writeback_engine import writeback_memory_delta


def _find_best_soul(agent_id: str, agent_home: str) -> str | None:
    """Find the best existing SOUL.md for an agent (largest + newest)."""
    layout = resolve_agent_cli_layout(agent_home, agent_id)
    candidates = [
        os.path.join(layout["workspace"], "SOUL.md"),
        os.path.join(layout["project_root"], "SOUL.md"),
        os.path.join(layout["home_dir"], "SOUL.md"),
    ]

    # Also search in common locations
    for pattern in [
        str(BACKEND_DIR / "**" / f"*{agent_id}*" / "SOUL.md"),
        str(BACKEND_DIR.parent.parent / agent_id.capitalize() / "**" / "SOUL.md"),
    ]:
        candidates.extend(glob.glob(pattern, recursive=True))

    best_path = ""
    best_size = 0
    for c in candidates:
        try:
            size = os.path.getsize(c)
            if size > best_size:
                best_size = size
                best_path = c
        except OSError:
            continue

    if not best_path:
        return None
    try:
        return Path(best_path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _find_best_context_bridge(agent_id: str, agent_home: str) -> str | None:
    """Find the newest CONTEXT_BRIDGE.md for an agent."""
    layout = resolve_agent_cli_layout(agent_home, agent_id)
    candidates = [
        os.path.join(layout["workspace"], "CONTEXT_BRIDGE.md"),
        os.path.join(layout["home_dir"], "CONTEXT_BRIDGE.md"),
    ]

    best_path = ""
    best_mtime = 0.0
    for c in candidates:
        try:
            mtime = os.path.getmtime(c)
            if mtime > best_mtime:
                best_mtime = mtime
                best_path = c
        except OSError:
            continue

    if not best_path:
        return None
    try:
        return Path(best_path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def run_migration(dry_run: bool = True) -> None:
    if not TEAM_JSON.exists():
        print(f"ERROR: {TEAM_JSON} not found", file=sys.stderr)
        sys.exit(1)

    with open(TEAM_JSON) as f:
        data = json.load(f)

    agents = data.get("agents", [])
    print(f"{'[DRY RUN] ' if dry_run else ''}Canonical Store Migration")
    print(f"Agents: {len(agents)}")
    print()

    stats = {"seeded": 0, "identity": 0, "soul": 0, "memory": 0, "context_bridge": 0}

    for agent in agents:
        agent_id = agent.get("id", "")
        home_dir_raw = agent.get("home_dir", "")
        config_dir = agent.get("config_dir", "")

        if not agent_id or not home_dir_raw:
            continue

        home_dir_abs = str((BACKEND_DIR / home_dir_raw).resolve()) if not os.path.isabs(home_dir_raw) else home_dir_raw

        print(f"[{agent_id}]")

        if not dry_run:
            canonical_store.init_canonical_dir(agent_id)

        # Identity
        if not dry_run:
            canonical_store.sync_identity_from_team(agent_id, data)
        stats["identity"] += 1
        print(f"  identity.json: synced")

        # Soul
        soul_content = _find_best_soul(agent_id, home_dir_abs)
        if soul_content:
            existing = canonical_store.read_canonical_soul(agent_id)
            if not existing or (not dry_run and len(soul_content) > len(existing or "")):
                if not dry_run:
                    canonical_store.write_canonical_soul(agent_id, soul_content)
                stats["soul"] += 1
                print(f"  soul.md: {'would seed' if dry_run else 'seeded'} ({len(soul_content)} chars)")
            else:
                print(f"  soul.md: already exists ({len(existing or '')} chars)")
        else:
            print(f"  soul.md: no source found")

        # Context Bridge
        cb_content = _find_best_context_bridge(agent_id, home_dir_abs)
        if cb_content:
            if not dry_run:
                canonical_store.write_canonical_context_bridge(agent_id, cb_content)
            stats["context_bridge"] += 1
            print(f"  context_bridge.md: {'would seed' if dry_run else 'seeded'} ({len(cb_content)} chars)")
        else:
            print(f"  context_bridge.md: no source found")

        # Memory writeback
        if not dry_run:
            try:
                new_entries = writeback_memory_delta(agent_id, home_dir_abs, config_dir)
                if new_entries > 0:
                    stats["memory"] += new_entries
                    print(f"  memory.jsonl: {new_entries} entries extracted")
                else:
                    print(f"  memory.jsonl: no new entries")
            except Exception as exc:
                print(f"  memory.jsonl: ERROR {exc}")
        else:
            mem_path = find_agent_memory_path(agent_id, home_dir_abs, config_dir)
            if mem_path:
                print(f"  memory.jsonl: would extract from {mem_path}")
            else:
                print(f"  memory.jsonl: no MEMORY.md found")

        stats["seeded"] += 1

    print(f"\n=== Summary ===")
    print(f"  Agents seeded:     {stats['seeded']}")
    print(f"  Identities synced: {stats['identity']}")
    print(f"  Souls seeded:      {stats['soul']}")
    print(f"  Memory entries:    {stats['memory']}")
    print(f"  Context Bridges:   {stats['context_bridge']}")


def run_verify() -> None:
    if not TEAM_JSON.exists():
        print(f"ERROR: {TEAM_JSON} not found", file=sys.stderr)
        sys.exit(1)

    with open(TEAM_JSON) as f:
        data = json.load(f)

    agents = data.get("agents", [])
    issues = 0
    ok = 0

    for agent in agents:
        agent_id = agent.get("id", "")
        if not agent_id:
            continue

        d = canonical_store.canonical_dir(agent_id)
        has_identity = (d / "identity.json").is_file()
        has_soul = (d / "soul.md").is_file()

        if not d.is_dir():
            print(f"MISSING [{agent_id}]: No canonical directory")
            issues += 1
        elif not has_identity:
            print(f"MISSING [{agent_id}]: No identity.json")
            issues += 1
        else:
            ok += 1

    print(f"\nVERIFY: {ok} OK, {issues} issues")
    sys.exit(0 if issues == 0 else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed canonical agent store from existing artifacts.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    if args.verify:
        run_verify()
    else:
        run_migration(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
