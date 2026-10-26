"""Git worktree isolation manager for multi-harness agent tasks."""

from pathlib import Path
from typing import List, Dict, Optional, Tuple, Union
import subprocess
import shutil
import re
import os


class GitWorktreeManager:
    """Manages isolated Git worktrees to prevent agent conflicts."""

    def __init__(self, repo_path: Union[str, Path]):
        self.repo_path = Path(repo_path).resolve()
        self.worktrees_base = self.repo_path / ".coordinator" / "worktrees"
        self.worktrees_base.mkdir(parents=True, exist_ok=True)

    def _run_git(
        self,
        args: List[str],
        cwd: Optional[Path] = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        """Run a git command in the given directory or repository root."""
        target_cwd = str(cwd or self.repo_path)
        return subprocess.run(
            ["git"] + args,
            cwd=target_cwd,
            capture_output=True,
            text=True,
            check=check,
        )

    def get_current_branch(self) -> str:
        """Get the current branch name of the repository."""
        res = self._run_git(["branch", "--show-current"])
        branch = res.stdout.strip()
        if not branch:
            # Detached HEAD or initial commit
            rev_res = self._run_git(["rev-parse", "--short", "HEAD"])
            branch = rev_res.stdout.strip() or "main"
        return branch

    def has_commits(self) -> bool:
        """Check if repository has at least one commit."""
        res = self._run_git(["rev-parse", "--verify", "HEAD"])
        return res.returncode == 0

    def ensure_initial_commit_if_empty(self) -> bool:
        """Create an initial commit if repository is completely empty."""
        if not self.has_commits():
            # Add existing files and create initial commit
            self._run_git(["add", "."])
            res = self._run_git(["commit", "-m", "chore: initial project instructions and setup"])
            return res.returncode == 0
        return True

    def create_worktree(
        self,
        task_id: str,
        branch_name: Optional[str] = None,
        base_ref: Optional[str] = None,
    ) -> Tuple[Path, str]:
        """
        Create an isolated Git worktree for a task.
        Returns: (worktree_path, branch_name)
        """
        self.ensure_initial_commit_if_empty()
        sanitized_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", task_id)
        if not branch_name:
            branch_name = f"agent/task-{sanitized_id}"

        worktree_path = self.worktrees_base / sanitized_id

        # Clean existing worktree directory if it was orphaned
        if worktree_path.exists():
            self._run_git(["worktree", "remove", "--force", str(worktree_path)])
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)

        # Check if branch exists
        branch_exists_res = self._run_git(["rev-parse", "--verify", branch_name])
        branch_exists = (branch_exists_res.returncode == 0)

        cmd = ["worktree", "add"]
        if branch_exists:
            cmd.extend([str(worktree_path), branch_name])
        else:
            base = base_ref or "HEAD"
            cmd.extend(["-b", branch_name, str(worktree_path), base])

        res = self._run_git(cmd)
        if res.returncode != 0:
            raise RuntimeError(
                f"Failed to create git worktree at {worktree_path} on branch {branch_name}:\n{res.stderr}\n{res.stdout}"
            )

        return worktree_path, branch_name

    def get_diff(self, worktree_path: Path, base_ref: str = "HEAD~1") -> str:
        """Get git diff inside worktree."""
        res = self._run_git(["diff", base_ref], cwd=worktree_path)
        if res.returncode != 0:
            # Fallback to diff against HEAD
            res = self._run_git(["diff", "HEAD"], cwd=worktree_path)
        return res.stdout

    def get_diff_stat(self, worktree_path: Path, base_ref: Optional[str] = None) -> str:
        """Get diffstat summary."""
        args = ["diff", "--stat"]
        if base_ref:
            args.append(base_ref)
        res = self._run_git(args, cwd=worktree_path)
        return res.stdout.strip()

    def get_head_commit(self, worktree_path: Path) -> str:
        """Get HEAD commit SHA in worktree."""
        res = self._run_git(["rev-parse", "--short", "HEAD"], cwd=worktree_path)
        return res.stdout.strip()

    def get_changed_files(self, worktree_path: Path, base_ref: str = "HEAD~1") -> List[str]:
        """Get list of changed files."""
        res = self._run_git(["diff", "--name-only", base_ref], cwd=worktree_path)
        if res.returncode != 0:
            res = self._run_git(["status", "--porcelain"], cwd=worktree_path)
            lines = [l[3:].strip() for l in res.stdout.splitlines() if len(l) > 3]
            return lines
        return [l.strip() for l in res.stdout.splitlines() if l.strip()]

    def merge_branch(
        self,
        branch_name: str,
        into_branch: Optional[str] = None,
        no_ff: bool = True,
        commit_message: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Merge task branch into destination branch in the main repo."""
        target = into_branch or self.get_current_branch()
        # Checkout target branch in main repo
        co_res = self._run_git(["checkout", target])
        if co_res.returncode != 0:
            return False, f"Could not checkout target branch {target}: {co_res.stderr}"

        msg = commit_message or f"merge: integrate task branch {branch_name}"
        merge_args = ["merge"]
        if no_ff:
            merge_args.append("--no-ff")
        merge_args.extend(["-m", msg, branch_name])

        res = self._run_git(merge_args)
        if res.returncode == 0:
            return True, f"Successfully merged {branch_name} into {target}."
        return False, f"Merge failed:\n{res.stderr}\n{res.stdout}"

    def remove_worktree(
        self,
        task_id: str,
        force: bool = False,
        delete_branch: bool = False,
    ) -> bool:
        """Remove a worktree directory and prune git worktree metadata."""
        sanitized_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", task_id)
        worktree_path = self.worktrees_base / sanitized_id

        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(worktree_path))

        res = self._run_git(args)
        self._run_git(["worktree", "prune"])

        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

        if delete_branch:
            branch_name = f"agent/task-{sanitized_id}"
            self._run_git(["branch", "-D" if force else "-d", branch_name])

        return res.returncode == 0 or not worktree_path.exists()

    def list_worktrees(self) -> List[Dict[str, str]]:
        """List active worktrees in porcelain format."""
        res = self._run_git(["worktree", "list", "--porcelain"])
        worktrees = []
        current: Dict[str, str] = {}
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line.split(" ", 1)[1]
            elif line.startswith("branch "):
                current["branch"] = line.split(" ", 1)[1]
            elif line.startswith("HEAD "):
                current["head"] = line.split(" ", 1)[1]
        if current:
            worktrees.append(current)
        return worktrees
