"""
Tests for Git Collaboration Layer (Release-Blocker 2).

Tests cover:
- bridge_git_branch_create: namespaced branch creation + worktree
- bridge_git_commit: commit in agent worktree
- bridge_git_push: push with lock check
- bridge_git_conflict_check: dry-run merge conflict detection
- bridge_git_lock / bridge_git_unlock: advisory branch locks with TTL
- Instance-ID from config
- Worktree cleanup
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class GitCollabTestBase(unittest.TestCase):
    """Base class that creates a temporary git repo for testing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="bridge_git_test_")
        self.repo_dir = os.path.join(self.test_dir, "repo")
        os.makedirs(self.repo_dir)

        # Init bare-like repo with initial commit
        subprocess.run(["git", "init", self.repo_dir], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.repo_dir, "config", "user.email", "test@bridge.local"], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.repo_dir, "config", "user.name", "Test"], check=True, capture_output=True)

        # Create initial commit on main
        readme = os.path.join(self.repo_dir, "README.md")
        with open(readme, "w") as f:
            f.write("# Test Repo\n")
        subprocess.run(["git", "-C", self.repo_dir, "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.repo_dir, "commit", "-m", "init"], check=True, capture_output=True)

        # Ensure we're on main
        subprocess.run(["git", "-C", self.repo_dir, "branch", "-M", "main"], check=True, capture_output=True)

        # Config
        self.instance_id = "test-instance"
        self.agent_id = "test-agent"
        self.worktree_base = os.path.join(self.test_dir, "worktrees")
        os.makedirs(self.worktree_base, exist_ok=True)

        # Lock file
        self.lock_file = os.path.join(self.test_dir, "git_locks.json")

    def tearDown(self):
        # Clean up worktrees before removing dir
        try:
            result = subprocess.run(
                ["git", "-C", self.repo_dir, "worktree", "list", "--porcelain"],
                capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if line.startswith("worktree ") and line.strip() != f"worktree {self.repo_dir}":
                    wt_path = line.split(" ", 1)[1]
                    subprocess.run(
                        ["git", "-C", self.repo_dir, "worktree", "remove", "--force", wt_path],
                        capture_output=True
                    )
        except Exception:
            pass
        shutil.rmtree(self.test_dir, ignore_errors=True)


class TestBranchNamespace(GitCollabTestBase):
    """Test branch naming convention: bridge/<instance_id>/<agent_id>/<feature>"""

    def test_branch_name_format(self):
        """Branch name follows namespace convention."""
        from git_collaboration import format_branch_name
        name = format_branch_name("test-instance", "backend", "add-auth")
        self.assertEqual(name, "bridge/test-instance/backend/add-auth")

    def test_branch_name_sanitizes_special_chars(self):
        """Special characters in feature name are sanitized."""
        from git_collaboration import format_branch_name
        name = format_branch_name("inst", "agent", "fix bug #123")
        self.assertNotIn(" ", name)
        self.assertNotIn("#", name)

    def test_branch_name_rejects_empty_feature(self):
        """Empty feature name raises ValueError."""
        from git_collaboration import format_branch_name
        with self.assertRaises(ValueError):
            format_branch_name("inst", "agent", "")


class TestBranchCreate(GitCollabTestBase):
    """Test bridge_git_branch_create: creates namespaced branch + worktree."""

    def test_creates_branch_and_worktree(self):
        """Branch is created and worktree points to it."""
        from git_collaboration import git_branch_create
        result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="test-feature",
            worktree_base=self.worktree_base,
        )
        self.assertTrue(result["ok"])
        self.assertIn("branch", result)
        self.assertIn("worktree_path", result)
        self.assertTrue(os.path.isdir(result["worktree_path"]))

        # Verify branch exists
        branches = subprocess.run(
            ["git", "-C", self.repo_dir, "branch", "--list", result["branch"]],
            capture_output=True, text=True
        )
        self.assertIn(result["branch"], branches.stdout)

    def test_creates_branch_from_specific_ref(self):
        """Branch can be created from a specific ref."""
        from git_collaboration import git_branch_create
        result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="from-main",
            worktree_base=self.worktree_base,
            from_ref="main",
        )
        self.assertTrue(result["ok"])

    def test_duplicate_branch_fails(self):
        """Creating same branch twice fails gracefully."""
        from git_collaboration import git_branch_create
        git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="dupe",
            worktree_base=self.worktree_base,
        )
        result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="dupe",
            worktree_base=self.worktree_base,
        )
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


class TestGitCommit(GitCollabTestBase):
    """Test bridge_git_commit: commit in agent worktree."""

    def test_commit_in_worktree(self):
        """Files can be committed in an agent worktree."""
        from git_collaboration import git_branch_create, git_commit
        branch_result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="commit-test",
            worktree_base=self.worktree_base,
        )
        wt = branch_result["worktree_path"]

        # Create a file in the worktree
        test_file = os.path.join(wt, "new_file.py")
        with open(test_file, "w") as f:
            f.write("print('hello')\n")

        result = git_commit(
            worktree_path=wt,
            message="Add new_file.py",
            files=["new_file.py"],
        )
        self.assertTrue(result["ok"])
        self.assertIn("commit_hash", result)
        self.assertEqual(len(result["commit_hash"]), 40)  # Full SHA

    def test_commit_empty_fails(self):
        """Commit with no changes fails."""
        from git_collaboration import git_branch_create, git_commit
        branch_result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="empty-commit",
            worktree_base=self.worktree_base,
        )
        result = git_commit(
            worktree_path=branch_result["worktree_path"],
            message="Empty",
            files=[],
        )
        self.assertFalse(result["ok"])


class TestGitPush(GitCollabTestBase):
    """Test bridge_git_push: push with lock check."""

    def _setup_remote(self):
        """Create a bare remote repo for push tests."""
        self.remote_dir = os.path.join(self.test_dir, "remote.git")
        subprocess.run(["git", "init", "--bare", self.remote_dir], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", self.repo_dir, "remote", "add", "origin", self.remote_dir],
            check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", self.repo_dir, "push", "-u", "origin", "main"],
            check=True, capture_output=True
        )

    def test_push_succeeds_when_no_lock(self):
        """Push works when branch is not locked by another agent."""
        self._setup_remote()
        from git_collaboration import git_branch_create, git_commit, git_push
        branch_result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="push-test",
            worktree_base=self.worktree_base,
        )
        wt = branch_result["worktree_path"]
        with open(os.path.join(wt, "file.txt"), "w") as f:
            f.write("data\n")
        git_commit(worktree_path=wt, message="add file", files=["file.txt"])

        result = git_push(
            worktree_path=wt,
            lock_file=self.lock_file,
            agent_id=self.agent_id,
        )
        self.assertTrue(result["ok"])

    def test_push_blocked_when_locked_by_other(self):
        """Push fails when branch is locked by another agent."""
        self._setup_remote()
        from git_collaboration import git_branch_create, git_commit, git_push, acquire_lock

        branch_result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="locked-push",
            worktree_base=self.worktree_base,
        )
        wt = branch_result["worktree_path"]
        branch = branch_result["branch"]

        # Lock by another agent
        acquire_lock(self.lock_file, branch, "other-agent", "other-instance")

        with open(os.path.join(wt, "file.txt"), "w") as f:
            f.write("data\n")
        git_commit(worktree_path=wt, message="add file", files=["file.txt"])

        result = git_push(
            worktree_path=wt,
            lock_file=self.lock_file,
            agent_id=self.agent_id,
        )
        self.assertFalse(result["ok"])
        self.assertIn("locked", result.get("error", ""))


class TestConflictCheck(GitCollabTestBase):
    """Test bridge_git_conflict_check: dry-run merge detection."""

    def test_clean_merge_detected(self):
        """No conflicts when branches don't touch same files."""
        from git_collaboration import git_branch_create, git_commit, git_conflict_check

        # Create branch and add a new file
        branch_result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="clean-merge",
            worktree_base=self.worktree_base,
        )
        wt = branch_result["worktree_path"]
        with open(os.path.join(wt, "new_feature.py"), "w") as f:
            f.write("# new feature\n")
        git_commit(worktree_path=wt, message="add feature", files=["new_feature.py"])

        result = git_conflict_check(
            repo_dir=self.repo_dir,
            branch=branch_result["branch"],
            target="main",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["clean"])
        self.assertEqual(result["conflicts"], [])

    def test_conflict_detected(self):
        """Conflict detected when both branches modify same file."""
        from git_collaboration import git_branch_create, git_commit, git_conflict_check

        # Modify README on a branch
        branch_result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="conflict-test",
            worktree_base=self.worktree_base,
        )
        wt = branch_result["worktree_path"]
        with open(os.path.join(wt, "README.md"), "w") as f:
            f.write("# Modified by branch\n")
        git_commit(worktree_path=wt, message="modify readme", files=["README.md"])

        # Modify same file on main
        with open(os.path.join(self.repo_dir, "README.md"), "w") as f:
            f.write("# Modified on main\n")
        subprocess.run(["git", "-C", self.repo_dir, "add", "README.md"], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.repo_dir, "commit", "-m", "modify readme on main"], check=True, capture_output=True)

        result = git_conflict_check(
            repo_dir=self.repo_dir,
            branch=branch_result["branch"],
            target="main",
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["clean"])
        self.assertIn("README.md", result["conflicts"])


class TestLockMechanism(GitCollabTestBase):
    """Test advisory lock acquire/release with TTL."""

    def test_acquire_lock(self):
        """Lock can be acquired on a branch."""
        from git_collaboration import acquire_lock
        result = acquire_lock(self.lock_file, "feature/x", "agent-a", "inst-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["lock"]["branch"], "feature/x")
        self.assertEqual(result["lock"]["agent_id"], "agent-a")

    def test_lock_blocks_second_acquire(self):
        """Second lock attempt by different agent fails."""
        from git_collaboration import acquire_lock
        acquire_lock(self.lock_file, "feature/x", "agent-a", "inst-1")
        result = acquire_lock(self.lock_file, "feature/x", "agent-b", "inst-1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "already_locked")
        self.assertEqual(result["holder"]["agent_id"], "agent-a")

    def test_same_agent_can_reacquire(self):
        """Same agent can refresh its own lock."""
        from git_collaboration import acquire_lock
        acquire_lock(self.lock_file, "feature/x", "agent-a", "inst-1")
        result = acquire_lock(self.lock_file, "feature/x", "agent-a", "inst-1")
        self.assertTrue(result["ok"])

    def test_unlock(self):
        """Lock can be released by owner."""
        from git_collaboration import acquire_lock, release_lock
        acquire_lock(self.lock_file, "feature/x", "agent-a", "inst-1")
        result = release_lock(self.lock_file, "feature/x", "agent-a")
        self.assertTrue(result["ok"])

    def test_unlock_by_non_owner_fails(self):
        """Non-owner cannot release lock."""
        from git_collaboration import acquire_lock, release_lock
        acquire_lock(self.lock_file, "feature/x", "agent-a", "inst-1")
        result = release_lock(self.lock_file, "feature/x", "agent-b")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_owner")

    def test_unlock_nonexistent_fails(self):
        """Releasing non-existent lock fails."""
        from git_collaboration import release_lock
        result = release_lock(self.lock_file, "feature/x", "agent-a")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_locked")

    def test_expired_lock_auto_released(self):
        """Expired locks are cleaned up on next acquire."""
        from git_collaboration import acquire_lock
        # Acquire with very short TTL
        result = acquire_lock(self.lock_file, "feature/x", "agent-a", "inst-1", ttl_seconds=1)
        self.assertTrue(result["ok"])

        time.sleep(1.5)

        # Different agent should be able to acquire now
        result = acquire_lock(self.lock_file, "feature/x", "agent-b", "inst-2")
        self.assertTrue(result["ok"])
        self.assertEqual(result["lock"]["agent_id"], "agent-b")

    def test_list_locks(self):
        """All active locks can be listed."""
        from git_collaboration import acquire_lock, list_locks
        acquire_lock(self.lock_file, "branch-1", "agent-a", "inst-1")
        acquire_lock(self.lock_file, "branch-2", "agent-b", "inst-1")
        locks = list_locks(self.lock_file)
        self.assertEqual(len(locks), 2)
        branches = {l["branch"] for l in locks}
        self.assertEqual(branches, {"branch-1", "branch-2"})


class TestPathTraversalProtection(GitCollabTestBase):
    """Test that path traversal in feature names is blocked."""

    def test_traversal_with_dotdot_blocked(self):
        """Feature name with ../.. is blocked."""
        from git_collaboration import git_branch_create
        result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="../../etc/passwd",
            worktree_base=self.worktree_base,
        )
        self.assertFalse(result["ok"])
        self.assertIn("traversal", result["error"].lower())

    def test_normal_feature_allowed(self):
        """Normal feature names pass traversal check."""
        from git_collaboration import git_branch_create
        result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="valid-feature",
            worktree_base=self.worktree_base,
        )
        self.assertTrue(result["ok"])


class TestRaceConditionProtection(GitCollabTestBase):
    """Test that lock operations use file locking."""

    def test_concurrent_locks_no_corruption(self):
        """Multiple rapid lock operations don't corrupt the lock file."""
        import threading
        from git_collaboration import acquire_lock, release_lock

        results = []

        def lock_unlock(agent_num):
            branch = f"branch-{agent_num}"
            r = acquire_lock(self.lock_file, branch, f"agent-{agent_num}", "inst-1", ttl_seconds=60)
            results.append(r)
            if r["ok"]:
                release_lock(self.lock_file, branch, f"agent-{agent_num}")

        threads = [threading.Thread(target=lock_unlock, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed (different branches)
        self.assertEqual(len(results), 10)
        self.assertTrue(all(r["ok"] for r in results))


class TestInstanceId(unittest.TestCase):
    """Test instance ID resolution from config."""

    def test_instance_id_from_config(self):
        """Instance ID is read from bridge_config.json."""
        from git_collaboration import get_instance_id
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"instance_id": "my-bridge"}, f)
            f.flush()
            instance_id = get_instance_id(config_path=f.name)
        os.unlink(f.name)
        self.assertEqual(instance_id, "my-bridge")

    def test_instance_id_defaults_to_hostname(self):
        """Without config, instance ID defaults to hostname."""
        import socket
        from git_collaboration import get_instance_id
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            f.flush()
            instance_id = get_instance_id(config_path=f.name)
        os.unlink(f.name)
        self.assertEqual(instance_id, socket.gethostname())

    def test_instance_id_missing_config_uses_hostname(self):
        """Missing config file defaults to hostname."""
        import socket
        from git_collaboration import get_instance_id
        instance_id = get_instance_id(config_path="/nonexistent/path.json")
        self.assertEqual(instance_id, socket.gethostname())


class TestWorktreeOwnership(GitCollabTestBase):
    """Test worktree ownership validation (security hardening)."""

    def _create_agent_worktree(self, agent_id, feature):
        """Helper: create a worktree for a specific agent."""
        from git_collaboration import git_branch_create
        return git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=agent_id,
            feature=feature,
            worktree_base=self.worktree_base,
        )

    def test_ownership_valid_for_own_worktree(self):
        """Agent can validate ownership of its own worktree."""
        from git_collaboration import validate_worktree_ownership
        result = self._create_agent_worktree("agent-a", "my-feature")
        self.assertTrue(result["ok"])

        ownership = validate_worktree_ownership(
            worktree_path=result["worktree_path"],
            agent_id="agent-a",
            worktree_base=self.worktree_base,
        )
        self.assertTrue(ownership["ok"])

    def test_ownership_rejected_for_other_agents_worktree(self):
        """Agent cannot claim ownership of another agent's worktree."""
        from git_collaboration import validate_worktree_ownership
        result = self._create_agent_worktree("agent-a", "their-feature")
        self.assertTrue(result["ok"])

        ownership = validate_worktree_ownership(
            worktree_path=result["worktree_path"],
            agent_id="agent-b",
            worktree_base=self.worktree_base,
        )
        self.assertFalse(ownership["ok"])
        self.assertIn("not owned", ownership["error"].lower())

    def test_ownership_rejected_for_nonexistent_path(self):
        """Nonexistent worktree path is rejected."""
        from git_collaboration import validate_worktree_ownership
        ownership = validate_worktree_ownership(
            worktree_path="/tmp/nonexistent-worktree-xyz",
            agent_id="agent-a",
        )
        self.assertFalse(ownership["ok"])
        self.assertIn("does not exist", ownership["error"])

    def test_ownership_branch_check_rejects_cross_agent(self):
        """Branch namespace check catches cross-agent access even without worktree_base."""
        from git_collaboration import validate_worktree_ownership
        # Create worktree for agent-a
        result = self._create_agent_worktree("agent-a", "secret-work")
        self.assertTrue(result["ok"])

        # agent-b tries to use it WITHOUT worktree_base (only branch check)
        ownership = validate_worktree_ownership(
            worktree_path=result["worktree_path"],
            agent_id="agent-b",
        )
        self.assertFalse(ownership["ok"])
        self.assertIn("not namespaced", ownership["error"].lower())

    def test_ownership_path_traversal_rejected(self):
        """Path traversal attempt to escape worktree_base is rejected."""
        from git_collaboration import validate_worktree_ownership
        # Create a legit worktree first
        result = self._create_agent_worktree("agent-a", "legit")
        self.assertTrue(result["ok"])

        # Try to claim the repo dir itself as a worktree
        ownership = validate_worktree_ownership(
            worktree_path=self.repo_dir,
            agent_id="agent-a",
            worktree_base=self.worktree_base,
        )
        self.assertFalse(ownership["ok"])

    def test_ownership_valid_returns_branch_name(self):
        """Successful ownership check returns the branch name."""
        from git_collaboration import validate_worktree_ownership
        result = self._create_agent_worktree("agent-a", "info-test")
        self.assertTrue(result["ok"])

        ownership = validate_worktree_ownership(
            worktree_path=result["worktree_path"],
            agent_id="agent-a",
            worktree_base=self.worktree_base,
        )
        self.assertTrue(ownership["ok"])
        self.assertIn("branch", ownership)
        self.assertIn("agent-a", ownership["branch"])


class TestWorktreeCleanup(GitCollabTestBase):
    """Test worktree cleanup on agent stop."""

    def test_cleanup_removes_worktree(self):
        """cleanup_worktree removes the agent's worktree and branch."""
        from git_collaboration import git_branch_create, cleanup_worktree
        branch_result = git_branch_create(
            repo_dir=self.repo_dir,
            instance_id=self.instance_id,
            agent_id=self.agent_id,
            feature="cleanup-test",
            worktree_base=self.worktree_base,
        )
        wt = branch_result["worktree_path"]
        self.assertTrue(os.path.isdir(wt))

        cleanup_worktree(repo_dir=self.repo_dir, worktree_path=wt)
        self.assertFalse(os.path.isdir(wt))

    def test_cleanup_nonexistent_is_noop(self):
        """Cleaning up non-existent worktree doesn't error."""
        from git_collaboration import cleanup_worktree
        # Should not raise
        cleanup_worktree(repo_dir=self.repo_dir, worktree_path="/nonexistent/path")


class TestPrePushHook(GitCollabTestBase):
    """Test pre-push hook generation and installation."""

    def test_generate_hook_returns_bash_script(self):
        """Hook content is a valid bash script."""
        from git_collaboration import generate_pre_push_hook
        hook = generate_pre_push_hook()
        self.assertTrue(hook.startswith("#!/usr/bin/env bash"))
        self.assertIn("Bridge IDE pre-push hook", hook)
        self.assertIn("BRIDGE_URL", hook)
        self.assertIn("git/locks", hook)

    def test_install_hook_in_repo(self):
        """Hook can be installed in a git repo."""
        from git_collaboration import install_pre_push_hook
        result = install_pre_push_hook(self.repo_dir)
        self.assertTrue(result["ok"])
        self.assertIn("hook_path", result)
        self.assertTrue(os.path.isfile(result["hook_path"]))
        # Check executable
        import stat
        mode = os.stat(result["hook_path"]).st_mode
        self.assertTrue(mode & stat.S_IXUSR)

    def test_install_hook_idempotent(self):
        """Installing hook twice works (Bridge hook is overwritten)."""
        from git_collaboration import install_pre_push_hook
        install_pre_push_hook(self.repo_dir)
        result = install_pre_push_hook(self.repo_dir)
        self.assertTrue(result["ok"])

    def test_install_hook_refuses_non_bridge_hook(self):
        """Non-Bridge existing hook is not overwritten."""
        from git_collaboration import install_pre_push_hook
        hook_path = os.path.join(self.repo_dir, ".git", "hooks", "pre-push")
        os.makedirs(os.path.dirname(hook_path), exist_ok=True)
        with open(hook_path, "w") as f:
            f.write("#!/bin/bash\n# Custom hook\nexit 0\n")
        result = install_pre_push_hook(self.repo_dir)
        self.assertFalse(result["ok"])
        self.assertIn("not Bridge-generated", result["error"])

    def test_install_hook_invalid_repo(self):
        """Installing in non-git directory fails."""
        from git_collaboration import install_pre_push_hook
        result = install_pre_push_hook("/tmp/not-a-repo-xyz")
        self.assertFalse(result["ok"])
        self.assertIn("hooks dir missing", result["error"])


if __name__ == "__main__":
    unittest.main()
