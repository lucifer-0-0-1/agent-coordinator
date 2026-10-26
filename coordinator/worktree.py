"""Workspace and worktree isolation manager for multi-harness agent tasks.
Supports both Git repositories (via git worktree) and non-Git directories (via snapshot/in-place workspaces).
"""

from pathlib import Path
from typing import List, Dict, Optional, Tuple, Union, Set
import subprocess
import shutil
import re
import os
import difflib
import hashlib

from coordinator.repo_init import is_git_repo


class WorkspaceManager:
    """Manages isolated workspaces and Git worktrees to prevent agent conflicts."""

    def __init__(self, repo_path: Union[str, Path]):
        self.repo_path = Path(repo_path).resolve()
        self.is_git = is_git_repo(self.repo_path)
        self.coordinator_base = self.repo_path / ".coordinator"
        self.worktrees_base = self.coordinator_base / "worktrees"
        self.workspaces_base = self.coordinator_base / "workspaces"
        self.worktrees_base.mkdir(parents=True, exist_ok=True)
        self.workspaces_base.mkdir(parents=True, exist_ok=True)

    def _run_git(
        self,
        args: List[str],
        cwd: Optional[Path] = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        """Run a git command in the given directory or repository root."""
        if not self.is_git and (cwd is None or not is_git_repo(cwd)):
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="Not a git repository")
        target_cwd = str(cwd or self.repo_path)
        return subprocess.run(
            ["git"] + args,
            cwd=target_cwd,
            capture_output=True,
            text=True,
            check=check,
        )

    def get_current_branch(self) -> str:
        """Get the current branch name of the repository (or 'non-git' if not a git repo)."""
        if not self.is_git:
            return "non-git"
        res = self._run_git(["branch", "--show-current"])
        branch = res.stdout.strip()
        if not branch:
            rev_res = self._run_git(["rev-parse", "--short", "HEAD"])
            branch = rev_res.stdout.strip() or "main"
        return branch

    def has_commits(self) -> bool:
        """Check if repository has at least one commit."""
        if not self.is_git:
            return False
        res = self._run_git(["rev-parse", "--verify", "HEAD"])
        return res.returncode == 0

    def ensure_initial_commit_if_empty(self) -> bool:
        """Create an initial commit if repository is git-controlled and completely empty."""
        if not self.is_git:
            return True
        if not self.has_commits():
            self._run_git(["add", "."])
            res = self._run_git(["commit", "-m", "chore: initial project instructions and setup"])
            return res.returncode == 0
        return True

    def create_workspace(
        self,
        task_id: str,
        use_worktree: bool = True,
        branch_name: Optional[str] = None,
        base_ref: Optional[str] = None,
        assigned_files: Optional[List[str]] = None,
    ) -> Tuple[Path, str]:
        """
        Create an execution workspace for a task.
        - In Git mode with use_worktree=True: creates an isolated git worktree.
        - In non-Git mode (or use_worktree=False): creates an isolated directory workspace or in-place target.
        Returns: (workspace_path, branch_or_workspace_identifier)
        """
        sanitized_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", task_id)

        # 1. Non-git or in-place mode
        if not self.is_git or not use_worktree:
            # If use_worktree is explicitly False, user wants in-place execution in the project directory
            if not use_worktree:
                return self.repo_path, "in-place"

            # Otherwise, non-git directory snapshot isolation
            ws_path = self.workspaces_base / sanitized_id
            if ws_path.exists():
                shutil.rmtree(ws_path, ignore_errors=True)
            ws_path.mkdir(parents=True, exist_ok=True)

            # Copy assigned files or instructions into workspace
            if assigned_files:
                for rel_file in assigned_files:
                    src_f = self.repo_path / rel_file
                    if src_f.exists() and src_f.is_file():
                        dst_f = ws_path / rel_file
                        dst_f.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_f, dst_f)
            # Copy instruction files
            for inst in ["AGENTS.md", "CLAUDE.md"]:
                if (self.repo_path / inst).exists():
                    shutil.copy2(self.repo_path / inst, ws_path / inst)
            if (self.repo_path / ".agents").exists():
                shutil.copytree(self.repo_path / ".agents", ws_path / ".agents", dirs_exist_ok=True)

            return ws_path, f"workspace/{sanitized_id}"

        # 2. Git worktree mode
        self.ensure_initial_commit_if_empty()
        if not branch_name:
            branch_name = f"agent/task-{sanitized_id}"

        worktree_path = self.worktrees_base / sanitized_id

        # Clean existing worktree directory if it was orphaned
        if worktree_path.exists():
            self._run_git(["worktree", "remove", "--force", str(worktree_path)])
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)

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

    # Backward compatibility alias
    create_worktree = create_workspace

    def get_diff(self, workspace_path: Path, base_ref: str = "HEAD~1") -> str:
        """Get diff inside workspace (using Git diff or file comparison fallback)."""
        if self.is_git and is_git_repo(workspace_path):
            res = self._run_git(["diff", base_ref], cwd=workspace_path)
            if res.returncode != 0:
                res = self._run_git(["diff", "HEAD"], cwd=workspace_path)
            return res.stdout

        # Non-git unified diff comparison between workspace and original repo
        if workspace_path != self.repo_path and workspace_path.exists():
            diff_lines = []
            for ws_file in workspace_path.rglob("*"):
                if ws_file.is_file() and ".coordinator" not in ws_file.parts:
                    rel_p = ws_file.relative_to(workspace_path)
                    orig_file = self.repo_path / rel_p
                    if orig_file.exists():
                        try:
                            orig_text = orig_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                            ws_text = ws_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                            udiff = difflib.unified_diff(
                                orig_text, ws_text, fromfile=str(rel_p), tofile=str(rel_p)
                            )
                            diff_lines.extend(udiff)
                        except Exception:
                            pass
                    else:
                        diff_lines.append(f"new file: {rel_p}\n")
            return "".join(diff_lines)

        return "No git diff available (in-place non-git execution)."

    def get_diff_stat(self, workspace_path: Path, base_ref: Optional[str] = None) -> str:
        """Get diffstat summary."""
        if self.is_git and is_git_repo(workspace_path):
            args = ["diff", "--stat"]
            if base_ref:
                args.append(base_ref)
            res = self._run_git(args, cwd=workspace_path)
            return res.stdout.strip()
        diff = self.get_diff(workspace_path)
        if diff and diff != "No git diff available (in-place non-git execution).":
            lines = diff.splitlines()
            return f"{len([l for l in lines if l.startswith('+')])} additions, {len([l for l in lines if l.startswith('-')])} deletions"
        return "In-place modifications."

    def get_head_commit(self, workspace_path: Path) -> Optional[str]:
        """Get HEAD commit SHA in workspace if Git is available."""
        if self.is_git and is_git_repo(workspace_path):
            res = self._run_git(["rev-parse", "--short", "HEAD"], cwd=workspace_path)
            return res.stdout.strip() if res.returncode == 0 else None
        return None

    def get_changed_files(self, workspace_path: Path, base_ref: str = "HEAD~1") -> List[str]:
        """Get list of changed files."""
        if self.is_git and is_git_repo(workspace_path):
            res = self._run_git(["diff", "--name-only", base_ref], cwd=workspace_path)
            if res.returncode != 0:
                res = self._run_git(["status", "--porcelain"], cwd=workspace_path)
                lines = [l[3:].strip() for l in res.stdout.splitlines() if len(l) > 3]
                return lines
            return [l.strip() for l in res.stdout.splitlines() if l.strip()]

        # Non-git workspace comparison
        changed = []
        if workspace_path != self.repo_path and workspace_path.exists():
            for ws_file in workspace_path.rglob("*"):
                if ws_file.is_file() and ".coordinator" not in ws_file.parts:
                    rel_p = str(ws_file.relative_to(workspace_path))
                    orig_file = self.repo_path / rel_p
                    if not orig_file.exists():
                        changed.append(rel_p)
                    else:
                        try:
                            if ws_file.read_bytes() != orig_file.read_bytes():
                                changed.append(rel_p)
                        except Exception:
                            changed.append(rel_p)
        return changed

    def merge_branch(
        self,
        branch_name: str,
        into_branch: Optional[str] = None,
        no_ff: bool = True,
        commit_message: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Merge task branch into destination branch in the main repo."""
        if not self.is_git:
            return True, "Non-git execution; changes are already in place or ready."

        target = into_branch or self.get_current_branch()
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
        """Remove a worktree or directory workspace and clean up metadata."""
        sanitized_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", task_id)
        worktree_path = self.worktrees_base / sanitized_id
        workspace_path = self.workspaces_base / sanitized_id

        # Clean git worktree
        if self.is_git and worktree_path.exists():
            args = ["worktree", "remove"]
            if force:
                args.append("--force")
            args.append(str(worktree_path))
            self._run_git(args)
            self._run_git(["worktree", "prune"])
            if delete_branch:
                branch_name = f"agent/task-{sanitized_id}"
                self._run_git(["branch", "-D" if force else "-d", branch_name])

        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

        if workspace_path.exists():
            shutil.rmtree(workspace_path, ignore_errors=True)

        return True

    def list_worktrees(self) -> List[Dict[str, str]]:
        """List active worktrees and isolated workspaces."""
        workspaces = []
        if self.is_git:
            res = self._run_git(["worktree", "list", "--porcelain"])
            current: Dict[str, str] = {}
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line:
                    if current:
                        workspaces.append(current)
                        current = {}
                    continue
                if line.startswith("worktree "):
                    current["path"] = line.split(" ", 1)[1]
                elif line.startswith("branch "):
                    current["branch"] = line.split(" ", 1)[1]
                elif line.startswith("HEAD "):
                    current["head"] = line.split(" ", 1)[1]
            if current:
                workspaces.append(current)

        # Non-git workspaces
        if self.workspaces_base.exists():
            for p in self.workspaces_base.iterdir():
                if p.is_dir():
                    workspaces.append({
                        "path": str(p),
                        "branch": f"workspace/{p.name}",
                        "head": "snapshot",
                    })

        return workspaces


# Maintain class name compatibility
GitWorktreeManager = WorkspaceManager
