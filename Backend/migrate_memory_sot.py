#!/usr/bin/env python3
"""One-time migration: consolidate dual agent memory directories into canonical SoT.

Usage:
    python3 migrate_memory_sot.py --dry-run    # Preview changes
    python3 migrate_memory_sot.py              # Execute migration
    python3 migrate_memory_sot.py --verify     # Verify all symlinks are correct

The script reads team.json for agent definitions, computes the deterministic
SoT memory path for each agent, finds all alternative memory directories,
merges content into SoT, and replaces alternatives with symlinks.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
TEAM_JSON = BACKEND_DIR / "team.json"
# team.json home_dirs are relative to BACKEND_DIR (server CWD = BRIDGE/Backend/)
PROJECT_BASE = BACKEND_DIR


def _mangle_cwd(cwd: str) -> str:
    """Match Claude Code internal project directory naming."""
    return re.sub(r"[^a-zA-Z0-9-]", "-", str(cwd))


def _resolve_layout(home_dir: str, agent_id: str) -> dict[str, str]:
    """Resolve home_dir vs workspace for an agent.  All paths are absolute."""
    home_path = Path(home_dir).expanduser().resolve()
    if home_path.name == agent_id and home_path.parent.name == ".agent_sessions":
        workspace = home_path
        project_root = home_path.parent.parent
    else:
        workspace = home_path / ".agent_sessions" / agent_id
        project_root = home_path
    return {
        "home_dir": str(home_path),
        "workspace": str(workspace),
        "project_root": str(project_root),
    }


def _compute_sot(layout: dict[str, str], config_dir: str) -> str:
    """Compute the SoT memory directory path.  Uses resolved absolute paths."""
    home_dir = layout["home_dir"]
    workspace = layout["workspace"]
    config_base = Path(config_dir) if config_dir else Path.home() / ".claude"

    if Path(home_dir).resolve() == Path(workspace).resolve():
        mangled = _mangle_cwd(str(Path(workspace).resolve()))
    else:
        mangled = _mangle_cwd(str(Path(home_dir).resolve()))

    return str(config_base / "projects" / mangled / "memory")


def _find_all_memory_dirs(agent_id: str, config_bases: list[str]) -> list[str]:
    """Find all memory directories that could belong to this agent."""
    found: list[str] = []
    for base in config_bases:
        projects_dir = Path(base) / "projects"
        if not projects_dir.is_dir():
            continue
        # Glob for any project dir containing this agent_id.
        # agent_id may contain underscores (sec_dns) which get mangled to hyphens (sec-dns).
        mangled_id = _mangle_cwd(agent_id)
        for pattern in [f"*-{agent_id}", f"*-{mangled_id}", f"*-{agent_id}-*", f"*-{mangled_id}-*", f"*--agent-sessions-{agent_id}", f"*--agent-sessions-{mangled_id}"]:
            for match in glob.glob(str(projects_dir / pattern / "memory")):
                if os.path.isdir(match) or os.path.islink(match):
                    real = str(Path(match))
                    if real not in found:
                        found.append(real)
    return found


def _merge_memory_dir(source: str, target: str, dry_run: bool) -> int:
    """Merge files from source into target. Returns count of merged files."""
    merged = 0
    source_path = Path(source)
    target_path = Path(target)

    if not source_path.is_dir():
        return 0

    for item in source_path.iterdir():
        if not item.is_file():
            continue
        dest = target_path / item.name
        if not dest.exists():
            if dry_run:
                print(f"  COPY {item.name} → SoT")
            else:
                shutil.copy2(str(item), str(dest))
            merged += 1
        elif item.name == "MEMORY.md":
            # Larger MEMORY.md wins (more accumulated knowledge)
            if item.stat().st_size > dest.stat().st_size:
                if dry_run:
                    print(f"  OVERWRITE MEMORY.md ({item.stat().st_size}B > {dest.stat().st_size}B)")
                else:
                    shutil.copy2(str(item), str(dest))
                merged += 1
            else:
                if dry_run:
                    print(f"  SKIP MEMORY.md (SoT is larger: {dest.stat().st_size}B >= {item.stat().st_size}B)")
        else:
            # Other .md files: keep SoT version (newer usually)
            if item.stat().st_mtime > dest.stat().st_mtime:
                if dry_run:
                    print(f"  OVERWRITE {item.name} (source newer)")
                else:
                    shutil.copy2(str(item), str(dest))
                merged += 1
    return merged


def _fix_broken_symlinks(config_bases: list[str], dry_run: bool) -> int:
    """Find and remove broken memory symlinks."""
    fixed = 0
    for base in config_bases:
        projects_dir = Path(base) / "projects"
        if not projects_dir.is_dir():
            continue
        for mem_link in projects_dir.glob("*/memory"):
            if mem_link.is_symlink() and not mem_link.resolve().exists():
                print(f"  BROKEN SYMLINK: {mem_link} → {os.readlink(str(mem_link))}")
                if not dry_run:
                    mem_link.unlink()
                fixed += 1
    return fixed


def run_migration(dry_run: bool = True) -> None:
    """Run the full memory consolidation migration."""
    if not TEAM_JSON.exists():
        print(f"ERROR: {TEAM_JSON} not found", file=sys.stderr)
        sys.exit(1)

    with open(TEAM_JSON) as f:
        data = json.load(f)

    agents = data.get("agents", [])
    print(f"{'[DRY RUN] ' if dry_run else ''}Memory SoT Migration")
    print(f"Agents in team.json: {len(agents)}")
    print()

    # Collect all config bases
    config_bases = list(dict.fromkeys([
        str(Path.home() / ".claude"),
        str(Path.home() / ".claude-sub2"),
    ] + [
        a.get("config_dir", "")
        for a in agents if a.get("config_dir")
    ]))

    # Phase 0: Fix broken symlinks
    print("=== Phase 0: Broken Symlinks ===")
    broken = _fix_broken_symlinks(config_bases, dry_run)
    print(f"  Fixed: {broken}")
    print()

    # Phase 1: Per-agent consolidation
    print("=== Phase 1: Per-Agent Memory Consolidation ===")
    stats = {"consolidated": 0, "already_ok": 0, "no_memory": 0, "errors": 0}

    for agent in agents:
        agent_id = agent.get("id", "")
        home_dir_raw = agent.get("home_dir", "")
        config_dir = agent.get("config_dir", "")

        if not agent_id or not home_dir_raw:
            continue

        # Resolve absolute home_dir
        if os.path.isabs(home_dir_raw):
            home_dir_abs = home_dir_raw
        else:
            home_dir_abs = str(PROJECT_BASE / home_dir_raw)

        layout = _resolve_layout(home_dir_abs, agent_id)
        sot_dir = _compute_sot(layout, config_dir)

        # Find all alternative memory dirs
        search_bases = [config_dir] if config_dir else config_bases
        all_dirs = _find_all_memory_dirs(agent_id, search_bases)

        # Filter out SoT itself and symlinks already pointing to SoT
        alternatives = []
        for d in all_dirs:
            if os.path.realpath(d) == os.path.realpath(sot_dir):
                continue
            if os.path.islink(d):
                try:
                    if Path(d).resolve() == Path(sot_dir).resolve():
                        continue
                except OSError:
                    pass
            alternatives.append(d)

        if not alternatives and not os.path.isdir(sot_dir):
            stats["no_memory"] += 1
            continue

        if not alternatives:
            stats["already_ok"] += 1
            continue

        print(f"\n[{agent_id}] SoT: {sot_dir}")
        print(f"  Alternatives: {len(alternatives)}")

        try:
            # Ensure SoT exists
            if not dry_run:
                os.makedirs(sot_dir, exist_ok=True)

            for alt in alternatives:
                print(f"  Merging: {alt}")
                if os.path.islink(alt):
                    print(f"    Symlink → {os.readlink(alt)} (removing broken link)")
                    if not dry_run:
                        os.unlink(alt)
                elif os.path.isdir(alt):
                    merged = _merge_memory_dir(alt, sot_dir, dry_run)
                    if not dry_run:
                        shutil.rmtree(alt)
                        # Create parent dir if needed for symlink
                        os.makedirs(os.path.dirname(alt), exist_ok=True)
                        os.symlink(sot_dir, alt)
                    print(f"    Merged {merged} files, {'would create' if dry_run else 'created'} symlink")

            stats["consolidated"] += 1
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            stats["errors"] += 1

    print(f"\n=== Summary ===")
    print(f"  Consolidated: {stats['consolidated']}")
    print(f"  Already OK:   {stats['already_ok']}")
    print(f"  No memory:    {stats['no_memory']}")
    print(f"  Errors:       {stats['errors']}")


def run_verify() -> None:
    """Verify that all agents have correct memory symlinks."""
    if not TEAM_JSON.exists():
        print(f"ERROR: {TEAM_JSON} not found", file=sys.stderr)
        sys.exit(1)

    with open(TEAM_JSON) as f:
        data = json.load(f)

    agents = data.get("agents", [])
    issues = 0

    for agent in agents:
        agent_id = agent.get("id", "")
        home_dir_raw = agent.get("home_dir", "")
        config_dir = agent.get("config_dir", "")

        if not agent_id or not home_dir_raw:
            continue

        if os.path.isabs(home_dir_raw):
            home_dir_abs = home_dir_raw
        else:
            home_dir_abs = str(PROJECT_BASE / home_dir_raw)

        layout = _resolve_layout(home_dir_abs, agent_id)
        home_dir = layout["home_dir"]
        workspace = layout["workspace"]

        if Path(home_dir).resolve() == Path(workspace).resolve():
            continue  # No dual path possible

        config_base = Path(config_dir) if config_dir else Path.home() / ".claude"
        mangled_ws = _mangle_cwd(workspace)
        ws_memory = config_base / "projects" / mangled_ws / "memory"

        sot_dir = _compute_sot(layout, config_dir)

        if ws_memory.exists() and not ws_memory.is_symlink():
            print(f"ISSUE [{agent_id}]: {ws_memory} is a real directory, not a symlink to {sot_dir}")
            issues += 1
        elif ws_memory.is_symlink():
            target = str(ws_memory.resolve())
            expected = str(Path(sot_dir).resolve())
            if target != expected:
                print(f"ISSUE [{agent_id}]: Symlink points to {target}, expected {expected}")
                issues += 1

    if issues == 0:
        print("VERIFY OK: All agents have correct memory configuration.")
    else:
        print(f"\nVERIFY FAILED: {issues} issue(s) found.")
    sys.exit(0 if issues == 0 else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate agent memory directories into canonical SoT.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    parser.add_argument("--verify", action="store_true", help="Verify all symlinks are correct")
    args = parser.parse_args()

    if args.verify:
        run_verify()
    else:
        run_migration(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
