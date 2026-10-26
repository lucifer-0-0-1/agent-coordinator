"""Comprehensive unit tests for agent_coordinator."""

import unittest
import tempfile
import shutil
from pathlib import Path
import subprocess

from coordinator.repo_init import ensure_repo_instructions, is_repo_initialized
from coordinator.worktree import GitWorktreeManager
from coordinator.schema import Task, TaskReport, TaskStatus, AgentType, TaskPlan
from coordinator.orchestrator import CoordinatorOrchestrator
from coordinator.cli import parse_args, main


class TestRepoInit(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_ensure_repo_instructions(self):
        results = ensure_repo_instructions(self.test_dir, create_arch=True)
        self.assertEqual(results["AGENTS.md"], "created")
        self.assertEqual(results["CLAUDE.md"], "created")
        self.assertEqual(results[".agents/AGENTS.md"], "created")
        self.assertTrue((self.test_dir / "AGENTS.md").exists())
        self.assertTrue((self.test_dir / "CLAUDE.md").exists())
        self.assertTrue((self.test_dir / ".agents" / "AGENTS.md").exists())
        self.assertTrue((self.test_dir / "docs" / "ARCHITECTURE.md").exists())
        self.assertTrue((self.test_dir / ".gitignore").exists())
        self.assertTrue(is_repo_initialized(self.test_dir))

        # Re-running should verify, not overwrite unless forced
        results2 = ensure_repo_instructions(self.test_dir)
        self.assertEqual(results2["AGENTS.md"], "verified")
        self.assertEqual(results2["CLAUDE.md"], "verified")
        self.assertEqual(results2[".agents/AGENTS.md"], "verified")


class TestWorktreeManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        # Init git repo with initial commit
        subprocess.run(["git", "init"], cwd=str(self.test_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(self.test_dir), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(self.test_dir), check=True)
        test_file = self.test_dir / "README.md"
        test_file.write_text("# Test Repo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=str(self.test_dir), check=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(self.test_dir), check=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_create_and_remove_worktree(self):
        mgr = GitWorktreeManager(self.test_dir)
        worktree_path, branch = mgr.create_worktree("t1")
        self.assertTrue(worktree_path.exists())
        self.assertTrue(branch.startswith("agent/task-t1"))

        # Make a change in worktree
        new_file = worktree_path / "hello.txt"
        new_file.write_text("Hello from worktree", encoding="utf-8")
        subprocess.run(["git", "add", "hello.txt"], cwd=str(worktree_path), check=True)
        subprocess.run(["git", "commit", "-m", "add hello"], cwd=str(worktree_path), check=True)

        # Check diff in worktree
        diff = mgr.get_diff(worktree_path, base_ref="HEAD~1")
        self.assertIn("Hello from worktree", diff)

        # Merge branch back to main
        success, msg = mgr.merge_branch(branch)
        self.assertTrue(success, msg)
        self.assertTrue((self.test_dir / "hello.txt").exists())

        # Remove worktree
        removed = mgr.remove_worktree("t1", force=True, delete_branch=True)
        self.assertTrue(removed)
        self.assertFalse(worktree_path.exists())


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init"], cwd=str(self.test_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(self.test_dir), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(self.test_dir), check=True)
        (self.test_dir / "file.txt").write_text("content\n")
        subprocess.run(["git", "add", "."], cwd=str(self.test_dir), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(self.test_dir), check=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cli_init_and_status(self):
        # Test init
        exit_code = main(["init", str(self.test_dir)])
        self.assertEqual(exit_code, 0)
        self.assertTrue((self.test_dir / "AGENTS.md").exists())

        # Test status
        exit_code = main(["status", "--path", str(self.test_dir)])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
