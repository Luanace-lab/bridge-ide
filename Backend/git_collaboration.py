"""
Git Collaboration Layer for Bridge IDE.

Provides multi-user, multi-agent git workflow primitives:
- Namespaced branches (bridge/<instance_id>/<agent_id>/<feature>)
- Git worktrees for agent isolation
- Advisory branch locks with TTL
- Conflict detection via merge-tree dry-run

Release-Blocker 2: Parallele GitHub-Arbeit (Multi-User Collaboration)
"""

import fcntl
import json
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Branch Namespace
# ---------------------------------------------------------------------------

def format_branch_name(instance_id: str, agent_id: str, feature: str) -> str:
    """Create namespaced branch name: bridge/<instance_id>/<agent_id>/<feature>.

    Raises ValueError if feature is empty.
    Sanitizes feature name (replaces spaces, removes special chars).
    """
    if not feature or not feature.strip():
        raise ValueError("Feature name must not be empty")

    # Sanitize: lowercase, replace spaces/special chars with hyphens
    clean = feature.strip().lower()
    clean = re.sub(r"[^a-z0-9/_-]", "-", clean)
    clean = re.sub(r"-+", "-", clean).strip("-")

    return f"bridge/{instance_id}/{agent_id}/{clean}"


# ---------------------------------------------------------------------------
# Instance ID
# ---------------------------------------------------------------------------

def get_instance_id(config_path: str = "") -> str:
    """Read instance_id from config file. Defaults to hostname."""
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path) as f:
                config = json.load(f)
            iid = config.get("instance_id", "").strip()
            if iid:
                return iid
        except (json.JSONDecodeError, OSError):
            pass
    return socket.gethostname()


# ---------------------------------------------------------------------------
# Branch Create + Worktree
# ---------------------------------------------------------------------------

def git_branch_create(
    repo_dir: str,
    instance_id: str,
    agent_id: str,
    feature: str,
    worktree_base: str,
    from_ref: str = "HEAD",
) -> dict[str, Any]:
    """Create a namespaced branch and associated worktree.

    Returns {"ok": True, "branch": "...", "worktree_path": "..."} on success.
    Returns {"ok": False, "error": "..."} on failure.
    """
    branch = format_branch_name(instance_id, agent_id, feature)
    wt_path = os.path.join(worktree_base, agent_id, feature.strip().lower().replace(" ", "-"))

    # PATH TRAVERSAL protection: ensure worktree stays under worktree_base
    real_wt = os.path.realpath(wt_path)
    real_base = os.path.realpath(worktree_base)
    if not real_wt.startswith(real_base + os.sep) and real_wt != real_base:
        return {"ok": False, "error": "Path traversal detected: worktree path escapes base directory"}

    # Check if branch already exists
    check = subprocess.run(
        ["git", "-C", repo_dir, "rev-parse", "--verify", branch],
        capture_output=True, text=True,
    )
    if check.returncode == 0:
        return {"ok": False, "error": f"Branch '{branch}' already exists"}

    # Create worktree with new branch
    os.makedirs(os.path.dirname(wt_path), exist_ok=True)
    result = subprocess.run(
        ["git", "-C", repo_dir, "worktree", "add", "-b", branch, wt_path, from_ref],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip()}

    # Configure user in worktree (inherit from main repo)
    for key in ["user.email", "user.name"]:
        val = subprocess.run(
            ["git", "-C", repo_dir, "config", key],
            capture_output=True, text=True,
        )
        if val.returncode == 0 and val.stdout.strip():
            subprocess.run(
                ["git", "-C", wt_path, "config", key, val.stdout.strip()],
                capture_output=True,
            )

    return {"ok": True, "branch": branch, "worktree_path": wt_path}


# ---------------------------------------------------------------------------
# Git Commit
# ---------------------------------------------------------------------------

def git_commit(
    worktree_path: str,
    message: str,
    files: list[str] | None = None,
) -> dict[str, Any]:
    """Commit specified files in the given worktree.

    Returns {"ok": True, "commit_hash": "..."} on success.
    """
    if not files:
        return {"ok": False, "error": "No files specified"}

    # Stage files
    for f in files:
        result = subprocess.run(
            ["git", "-C", worktree_path, "add", f],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return {"ok": False, "error": f"Failed to stage '{f}': {result.stderr.strip()}"}

    # Check if there's anything staged
    diff = subprocess.run(
        ["git", "-C", worktree_path, "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    if diff.returncode == 0:
        return {"ok": False, "error": "Nothing to commit (no staged changes)"}

    # Commit
    result = subprocess.run(
        ["git", "-C", worktree_path, "commit", "-m", message],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip()}

    # Get commit hash
    rev = subprocess.run(
        ["git", "-C", worktree_path, "rev-parse", "HEAD"],
        capture_output=True, text=True,
    )
    commit_hash = rev.stdout.strip()

    return {"ok": True, "commit_hash": commit_hash}


# ---------------------------------------------------------------------------
# Advisory Locks (file-based, with TTL)
# ---------------------------------------------------------------------------

def _lock_dir_ensure(lock_file: str) -> str:
    """Ensure lock file directory exists, return directory path."""
    lock_dir = os.path.dirname(lock_file) if os.path.dirname(lock_file) else "."
    os.makedirs(lock_dir, exist_ok=True)
    return lock_dir


def _load_locks_raw(lock_file: str) -> list[dict]:
    """Load locks from JSON file, filtering expired ones. Caller must hold file lock."""
    if not os.path.exists(lock_file):
        return []
    try:
        with open(lock_file) as f:
            locks = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    now = time.time()
    return [l for l in locks if l.get("expires_at_epoch", 0) > now]


def _load_locks(lock_file: str) -> list[dict]:
    """Load locks from JSON file, filtering expired ones (with file lock)."""
    _lock_dir_ensure(lock_file)
    flock_path = lock_file + ".flock"
    try:
        fd = os.open(flock_path, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            return _load_locks_raw(lock_file)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    except OSError:
        return _load_locks_raw(lock_file)


def _save_locks(lock_file: str, locks: list[dict]) -> None:
    """Save locks to JSON file (atomic write via tempfile + os.replace)."""
    import tempfile as _tempfile
    lock_dir = _lock_dir_ensure(lock_file)
    fd, tmp = _tempfile.mkstemp(dir=lock_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(locks, f, indent=2)
        os.replace(tmp, lock_file)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _with_file_lock(lock_file: str, fn):
    """Execute fn() while holding an exclusive file lock on lock_file.flock."""
    _lock_dir_ensure(lock_file)
    flock_path = lock_file + ".flock"
    fd = os.open(flock_path, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fn()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def acquire_lock(
    lock_file: str,
    branch: str,
    agent_id: str,
    instance_id: str,
    ttl_seconds: int = 1800,
) -> dict[str, Any]:
    """Acquire advisory lock on a branch.

    Returns {"ok": True, "lock": {...}} on success.
    Returns {"ok": False, "error": "already_locked", "holder": {...}} if locked by another.
    Same agent can refresh its own lock.
    Uses fcntl.flock() to prevent race conditions.
    """
    def _do():
        return _acquire_lock_inner(lock_file, branch, agent_id, instance_id, ttl_seconds)
    return _with_file_lock(lock_file, _do)


def _acquire_lock_inner(
    lock_file: str,
    branch: str,
    agent_id: str,
    instance_id: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    """Inner acquire_lock logic — must be called under file lock."""
    locks = _load_locks_raw(lock_file)
    now = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()

    for lock in locks:
        if lock["branch"] == branch:
            if lock["agent_id"] == agent_id:
                # Refresh own lock
                lock["acquired_at"] = now_iso
                lock["ttl_seconds"] = ttl_seconds
                lock["expires_at_epoch"] = now + ttl_seconds
                lock["expires_at"] = datetime.fromtimestamp(
                    now + ttl_seconds, tz=timezone.utc
                ).isoformat()
                _save_locks(lock_file, locks)
                return {"ok": True, "lock": lock}
            else:
                return {
                    "ok": False,
                    "error": "already_locked",
                    "holder": {
                        "agent_id": lock["agent_id"],
                        "instance_id": lock["instance_id"],
                        "acquired_at": lock["acquired_at"],
                        "expires_at": lock["expires_at"],
                    },
                }

    # No existing lock — create new
    new_lock = {
        "branch": branch,
        "agent_id": agent_id,
        "instance_id": instance_id,
        "acquired_at": now_iso,
        "ttl_seconds": ttl_seconds,
        "expires_at_epoch": now + ttl_seconds,
        "expires_at": datetime.fromtimestamp(
            now + ttl_seconds, tz=timezone.utc
        ).isoformat(),
    }
    locks.append(new_lock)
    _save_locks(lock_file, locks)
    return {"ok": True, "lock": new_lock}


def release_lock(lock_file: str, branch: str, agent_id: str) -> dict[str, Any]:
    """Release advisory lock. Only owner can release.

    Returns {"ok": True} on success.
    Returns {"ok": False, "error": "not_locked"|"not_owner"} on failure.
    Uses fcntl.flock() to prevent race conditions.
    """
    def _do():
        locks = _load_locks_raw(lock_file)
        for i, lock in enumerate(locks):
            if lock["branch"] == branch:
                if lock["agent_id"] != agent_id:
                    return {"ok": False, "error": "not_owner"}
                locks.pop(i)
                _save_locks(lock_file, locks)
                return {"ok": True}
        return {"ok": False, "error": "not_locked"}
    return _with_file_lock(lock_file, _do)


def list_locks(lock_file: str) -> list[dict]:
    """List all active (non-expired) locks."""
    return _load_locks(lock_file)


# ---------------------------------------------------------------------------
# Git Push (with lock check)
# ---------------------------------------------------------------------------

def git_push(
    worktree_path: str,
    lock_file: str,
    agent_id: str,
    remote: str = "origin",
) -> dict[str, Any]:
    """Push current branch. Checks that branch is not locked by another agent.

    Returns {"ok": True} on success.
    """
    # Get current branch name
    branch_result = subprocess.run(
        ["git", "-C", worktree_path, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    if branch_result.returncode != 0:
        return {"ok": False, "error": "Could not determine current branch"}

    branch = branch_result.stdout.strip()

    # Check locks
    locks = _load_locks(lock_file)
    for lock in locks:
        if lock["branch"] == branch and lock["agent_id"] != agent_id:
            return {
                "ok": False,
                "error": f"Branch '{branch}' is locked by agent '{lock['agent_id']}'",
            }

    # Push
    result = subprocess.run(
        ["git", "-C", worktree_path, "push", "-u", remote, branch],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip()}

    return {"ok": True, "branch": branch}


# ---------------------------------------------------------------------------
# Conflict Check (dry-run merge)
# ---------------------------------------------------------------------------

def git_conflict_check(
    repo_dir: str,
    branch: str,
    target: str = "main",
) -> dict[str, Any]:
    """Check if merging branch into target would cause conflicts.

    Uses git merge-tree for a true dry-run (no worktree mutation).
    Returns {"ok": True, "clean": bool, "conflicts": [...]}.
    """
    # Get SHAs
    def _rev(ref: str) -> str | None:
        r = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", ref],
            capture_output=True, text=True,
        )
        return r.stdout.strip() if r.returncode == 0 else None

    branch_sha = _rev(branch)
    target_sha = _rev(target)

    if not branch_sha or not target_sha:
        return {"ok": False, "error": f"Could not resolve refs: branch={branch_sha}, target={target_sha}"}

    # Find merge base
    base_result = subprocess.run(
        ["git", "-C", repo_dir, "merge-base", target_sha, branch_sha],
        capture_output=True, text=True,
    )
    if base_result.returncode != 0:
        return {"ok": False, "error": "No merge base found"}

    base_sha = base_result.stdout.strip()

    # git merge-tree (three-way merge simulation)
    mt = subprocess.run(
        ["git", "-C", repo_dir, "merge-tree", base_sha, target_sha, branch_sha],
        capture_output=True, text=True,
    )

    # Parse output for conflicts
    conflicts = []
    for line in mt.stdout.splitlines():
        # merge-tree outputs conflict markers with file info
        if line.startswith("changed in both"):
            # Extract filename from next lines
            continue
        # Look for "our" / "their" / conflict markers
        if "merge conflict" in line.lower() or line.startswith("+<<<<<<"):
            continue
        # Simple heuristic: lines with file paths after "changed in both"
        match = re.search(r"^\s+(\S+)$", line)
        if match and mt.returncode != 0:
            conflicts.append(match.group(1))

    # Better approach: check if output contains conflict markers
    has_conflicts = "<<<<<<" in mt.stdout or mt.returncode != 0

    if has_conflicts and not conflicts:
        # Try to extract filenames from the merge-tree output
        # Format: "changed in both\n  base   ... <sha> <file>\n  our    ...\n  their  ..."
        for m in re.finditer(r"(?:base|our|their)\s+\d+\s+[0-9a-f]+\s+(.+)", mt.stdout):
            fname = m.group(1).strip()
            if fname and fname not in conflicts:
                conflicts.append(fname)

    clean = not has_conflicts

    return {"ok": True, "clean": clean, "conflicts": list(set(conflicts))}


# ---------------------------------------------------------------------------
# Worktree Ownership Validation
# ---------------------------------------------------------------------------

def validate_worktree_ownership(
    worktree_path: str,
    agent_id: str,
    worktree_base: str = "",
) -> dict[str, Any]:
    """Validate that a worktree belongs to the given agent.

    Checks two things (defense in depth):
    1. Path check: worktree_path must be under <worktree_base>/<agent_id>/
    2. Branch check: the branch checked out in the worktree must contain the agent_id
       in its namespace (bridge/<instance>/<agent_id>/...)

    Returns {"ok": True} if ownership is confirmed.
    Returns {"ok": False, "error": "..."} if validation fails.
    """
    real_wt = os.path.realpath(worktree_path)

    # Check 1: Path must exist and be a directory
    if not os.path.isdir(real_wt):
        return {"ok": False, "error": f"Worktree path does not exist: {worktree_path}"}

    # Check 2: If worktree_base is provided, ensure path is under <base>/<agent_id>/
    if worktree_base:
        real_base = os.path.realpath(worktree_base)
        expected_prefix = os.path.join(real_base, agent_id) + os.sep
        if not real_wt.startswith(expected_prefix) and real_wt != os.path.join(real_base, agent_id):
            return {
                "ok": False,
                "error": f"Worktree path '{worktree_path}' is not owned by agent '{agent_id}' "
                         f"(expected under {expected_prefix})",
            }

    # Check 3: Branch name must contain agent_id in namespace
    branch_result = subprocess.run(
        ["git", "-C", real_wt, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    if branch_result.returncode != 0:
        return {"ok": False, "error": "Could not determine branch in worktree"}

    branch = branch_result.stdout.strip()

    # Branch should match pattern: bridge/<instance>/<agent_id>/<feature>
    # or at minimum contain /<agent_id>/ in the path
    if f"/{agent_id}/" not in branch:
        return {
            "ok": False,
            "error": f"Branch '{branch}' is not namespaced to agent '{agent_id}' "
                     f"(expected '.../{agent_id}/...' in branch name)",
        }

    return {"ok": True, "branch": branch}


# ---------------------------------------------------------------------------
# Worktree Cleanup
# ---------------------------------------------------------------------------

def cleanup_worktree(repo_dir: str, worktree_path: str) -> dict[str, Any]:
    """Remove a git worktree. Safe no-op if path doesn't exist.

    Returns {"ok": True} always (cleanup is best-effort).
    """
    if not os.path.exists(worktree_path):
        return {"ok": True, "note": "worktree path does not exist"}

    result = subprocess.run(
        ["git", "-C", repo_dir, "worktree", "remove", "--force", worktree_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Fallback: manual removal
        import shutil
        try:
            shutil.rmtree(worktree_path)
            # Prune stale worktree references
            subprocess.run(
                ["git", "-C", repo_dir, "worktree", "prune"],
                capture_output=True,
            )
        except OSError:
            pass

    return {"ok": True}


# ---------------------------------------------------------------------------
# Pre-push Hook (Lock Enforcement)
# ---------------------------------------------------------------------------

_PRE_PUSH_HOOK_TEMPLATE = '''#!/usr/bin/env bash
# Bridge IDE pre-push hook — enforces advisory branch locks.
# Generated by git_collaboration.py. Do not edit manually.
# Queries the Bridge server to check if the branch is locked by another agent.

BRIDGE_URL="${BRIDGE_SERVER_URL:-http://127.0.0.1:9111}"

while read local_ref local_sha remote_ref remote_sha; do
    # Extract branch name from remote ref
    branch="${remote_ref#refs/heads/}"

    # Query lock status from Bridge server
    response=$(curl -sf "$BRIDGE_URL/git/locks" 2>/dev/null)
    if [ $? -ne 0 ]; then
        echo "[Bridge pre-push] WARNING: Could not reach Bridge server at $BRIDGE_URL — push allowed (best-effort)"
        exit 0
    fi

    # Check if this branch is locked by another agent
    lock_agent=$(echo "$response" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for lock in data.get('locks', []):
    if lock.get('branch') == '$branch':
        print(lock.get('agent_id', 'unknown'))
        break
" 2>/dev/null)

    # Allow push if no lock found or this is our own lock
    my_agent="${BRIDGE_AGENT_ID:-}"
    if [ -n "$lock_agent" ] && [ -n "$my_agent" ] && [ "$lock_agent" != "$my_agent" ]; then
        echo "[Bridge pre-push] BLOCKED: Branch '$branch' is locked by agent '$lock_agent'."
        echo "[Bridge pre-push] Use bridge_git_lock/unlock or wait for lock expiry."
        exit 1
    fi
done

exit 0
'''


def generate_pre_push_hook() -> str:
    """Return the content of a pre-push hook that enforces advisory locks.

    The hook queries the Bridge server before allowing pushes.
    If the branch is locked by a different agent, the push is rejected.
    If the Bridge server is unreachable, the push is allowed (best-effort).
    """
    return _PRE_PUSH_HOOK_TEMPLATE


def install_pre_push_hook(repo_dir: str) -> dict[str, Any]:
    """Install the Bridge pre-push hook in a git repository.

    Returns {"ok": True, "hook_path": "..."} on success.
    Returns {"ok": False, "error": "..."} on failure.

    Will NOT overwrite an existing pre-push hook unless it was generated
    by Bridge (identified by the marker comment).
    """
    hooks_dir = os.path.join(repo_dir, ".git", "hooks")
    if not os.path.isdir(hooks_dir):
        return {"ok": False, "error": f"Not a git repository or hooks dir missing: {hooks_dir}"}

    hook_path = os.path.join(hooks_dir, "pre-push")

    # Check if existing hook is non-Bridge
    if os.path.exists(hook_path):
        try:
            with open(hook_path) as f:
                existing = f.read()
            if "Bridge IDE pre-push hook" not in existing:
                return {
                    "ok": False,
                    "error": "Existing pre-push hook found (not Bridge-generated). "
                             "Remove it manually or merge the hooks.",
                }
        except OSError:
            pass

    # Write hook
    try:
        with open(hook_path, "w") as f:
            f.write(_PRE_PUSH_HOOK_TEMPLATE)
        os.chmod(hook_path, 0o755)
    except OSError as e:
        return {"ok": False, "error": f"Failed to write hook: {e}"}

    return {"ok": True, "hook_path": hook_path}
