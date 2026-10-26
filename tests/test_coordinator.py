"""Comprehensive unit tests for agent_coordinator including non-git and resource tests."""

import unittest
import tempfile
import shutil
from pathlib import Path
import subprocess

from coordinator.repo_init import ensure_repo_instructions, is_repo_initialized, is_git_repo
from coordinator.worktree import WorkspaceManager
from coordinator.schema import Task, TaskReport, TaskStatus, AgentType, TaskPlan
from coordinator.orchestrator import CoordinatorOrchestrator
from coordinator.resource import get_gpu_status, wait_for_gpu
from coordinator.cli import parse_args, main


class TestRepoInit(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_ensure_repo_instructions_git(self):
        results = ensure_repo_instructions(self.test_dir, auto_git_init=True, create_arch=True)
        self.assertEqual(results["AGENTS.md"], "created")
        self.assertEqual(results["CLAUDE.md"], "created")
        self.assertEqual(results[".agents/AGENTS.md"], "created")
        self.assertTrue((self.test_dir / "AGENTS.md").exists())
        self.assertTrue((self.test_dir / "CLAUDE.md").exists())
        self.assertTrue((self.test_dir / ".agents" / "AGENTS.md").exists())
        self.assertTrue((self.test_dir / "docs" / "ARCHITECTURE.md").exists())
        self.assertTrue((self.test_dir / ".gitignore").exists())
        self.assertTrue(is_repo_initialized(self.test_dir))

    def test_ensure_repo_instructions_nongit(self):
        # Auto git init disabled (non-git mode)
        results = ensure_repo_instructions(self.test_dir, auto_git_init=False)
        self.assertIn("non-git", results["git"])
        self.assertTrue((self.test_dir / "AGENTS.md").exists())
        self.assertTrue((self.test_dir / "CLAUDE.md").exists())
        self.assertTrue((self.test_dir / ".agents" / "AGENTS.md").exists())
        self.assertFalse(is_git_repo(self.test_dir))


class TestWorkspaceManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_git_worktree_lifecycle(self):
        subprocess.run(["git", "init"], cwd=str(self.test_dir), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(self.test_dir), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(self.test_dir), check=True)
        test_file = self.test_dir / "README.md"
        test_file.write_text("# Test Repo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=str(self.test_dir), check=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(self.test_dir), check=True)

        mgr = WorkspaceManager(self.test_dir)
        worktree_path, branch = mgr.create_workspace("t1", use_worktree=True)
        self.assertTrue(worktree_path.exists())
        self.assertTrue(branch.startswith("agent/task-t1"))

        # Make a change in worktree
        new_file = worktree_path / "hello.txt"
        new_file.write_text("Hello from worktree", encoding="utf-8")
        subprocess.run(["git", "add", "hello.txt"], cwd=str(worktree_path), check=True)
        subprocess.run(["git", "commit", "-m", "add hello"], cwd=str(worktree_path), check=True)

        diff = mgr.get_diff(worktree_path, base_ref="HEAD~1")
        self.assertIn("Hello from worktree", diff)

        success, msg = mgr.merge_branch(branch)
        self.assertTrue(success, msg)
        self.assertTrue((self.test_dir / "hello.txt").exists())

        mgr.remove_worktree("t1", force=True, delete_branch=True)
        self.assertFalse(worktree_path.exists())

    def test_nongit_workspace(self):
        # Non-git directory
        (self.test_dir / "code.py").write_text("print('hello')\n")
        mgr = WorkspaceManager(self.test_dir)
        self.assertFalse(mgr.is_git)

        # In-place mode
        inplace_path, ident = mgr.create_workspace("t2", use_worktree=False)
        self.assertEqual(inplace_path, self.test_dir)
        self.assertEqual(ident, "in-place")

        # Isolated directory mode
        ws_path, ident2 = mgr.create_workspace("t3", use_worktree=True, assigned_files=["code.py"])
        self.assertTrue(ws_path.exists())
        self.assertTrue((ws_path / "code.py").exists())


class TestResourceAndGuidance(unittest.TestCase):
    def test_gpu_check(self):
        status = get_gpu_status()
        self.assertIn("available", status)
        self.assertIn("gpus", status)

    def test_guidance_prompt_building(self):
        from coordinator.harness.agy import AntigravityHarness
        harness = AntigravityHarness()
        task = Task(id="test-1", title="CAN Parser", description="Parse CAN frames", assigned_to=AgentType.AGY)
        prompt = harness.build_guidance_prompt(task, "Bitmask is off for 29-bit frames")
        self.assertIn("Bitmask is off for 29-bit frames", prompt)
        self.assertIn("Watcher (Claude Code)", prompt)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cli_init_nongit_and_status(self):
        exit_code = main(["init", str(self.test_dir), "--non-git"])
        self.assertEqual(exit_code, 0)
        self.assertTrue((self.test_dir / "AGENTS.md").exists())

        exit_code = main(["status", "--path", str(self.test_dir)])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
