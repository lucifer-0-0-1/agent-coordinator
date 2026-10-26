"""Antigravity (agy) CLI execution harness.
Supports long-running tasks without arbitrary timeouts, GPU resource gating, and guided iterations.
"""

from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
import subprocess
import json
import time
import shutil
import os

from coordinator.harness.base import BaseHarness
from coordinator.schema import Task, TaskReport, TaskStatus, AgentType
from coordinator.resource import wait_for_gpu, is_nvidia_gpu_available


class AntigravityHarness(BaseHarness):
    """Executes tasks autonomously using Google Antigravity CLI (agy)."""

    def __init__(
        self,
        model: str = "gemini-3.8-flash-high",
        effort: str = "high",
        mode: str = "accept-edits",
        skip_permissions: bool = True,
        agy_bin: Optional[str] = None,
        default_timeout: Optional[int] = None,  # None = no timeout (unlimited)
    ):
        self.model = model
        self.effort = effort
        self.mode = mode
        self.skip_permissions = skip_permissions
        self.agy_bin = agy_bin or self._find_agy()
        self.default_timeout = default_timeout

    def _find_agy(self) -> str:
        """Locate agy executable."""
        found = shutil.which("agy")
        if found:
            return found
        default_local = Path.home() / ".local" / "bin" / "agy"
        if default_local.exists() and os.access(default_local, os.X_OK):
            return str(default_local)
        return "agy"

    def build_task_prompt(self, task: Task) -> str:
        """Construct the prompt sent to Antigravity CLI."""
        files_str = "\n".join(f"- {f}" for f in task.files) if task.files else "Any relevant files for this task."
        criteria_str = "\n".join(f"- {c}" for c in task.criteria) if task.criteria else "All existing and new tests must pass."

        prompt = f"""You are an autonomous implementation and reporting agent.

Task ID: {task.id}
Title: {task.title}

Description:
{task.description}

Assigned File Scope:
{files_str}

Acceptance Criteria:
{criteria_str}

Instructions:
1. Read AGENTS.md for project rules.
2. Inspect only the files in your assigned scope.
3. Implement the requested functionality or fix.
4. Add or update targeted unit tests covering your changes.
5. Run the relevant test suite to ensure green checks.
6. Commit your changes cleanly on your task branch with an imperative message (if in a Git repo).
7. MANDATORY COMPLETION REPORT:
   Before finishing, write a valid JSON file named TASK_REPORT.json in your current working directory with the following structure:
   {{
     "task_id": "{task.id}",
     "status": "completed",
     "summary": "Brief summary of what was implemented",
     "files_modified": ["list", "of", "modified", "files"],
     "files_created": ["list", "of", "created", "files"],
     "tests_run": ["list", "of", "tests", "executed"],
     "tests_passed": true,
     "notes": ["any relevant assumptions or edge cases"]
   }}

Do not modify files outside your assigned scope. Start now.
"""
        return prompt.strip()

    def build_guidance_prompt(self, task: Task, feedback: str) -> str:
        """Construct a prompt for a guided follow-up iteration from Claude Code."""
        files_str = "\n".join(f"- {f}" for f in task.files) if task.files else "Assigned task files."
        criteria_str = "\n".join(f"- {c}" for c in task.criteria) if task.criteria else "Verify all checks pass."

        prompt = f"""You are the autonomous implementation and reporting agent.

Follow-up on Task ID: {task.id} ({task.title})

The Watcher (Claude Code) has inspected your previous implementation/report and provided this feedback:
--------------------------------------------------
{feedback}
--------------------------------------------------

Assigned Scope:
{files_str}

Criteria:
{criteria_str}

Instructions:
1. Inspect the existing code in this workspace.
2. Address the Watcher's feedback directly. Do NOT re-implement unrelated parts.
3. Re-run the relevant test suite to confirm the fix.
4. Update the TASK_REPORT.json file in your working directory with updated status, tests, and summary.
5. If in a Git repo, commit your changes with an imperative commit message (e.g. `fix: address review feedback`).

Start fixing now.
"""
        return prompt.strip()

    def run_task(
        self,
        task: Task,
        worktree_path: Path,
        timeout: Optional[int] = None,
        wait_gpu: bool = False,
        min_gpu_free_mb: int = 1500,
        guidance_feedback: Optional[str] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> TaskReport:
        """
        Run the task inside the given worktree/workspace using agy.
        - timeout=None or 0: runs indefinitely without cutoff.
        - wait_gpu=True: waits until the GPU is free before starting.
        """
        start_time = time.time()
        log_dir = worktree_path / ".coordinator" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"agy_{task.id}_{int(start_time)}.log"

        def _log(msg: str):
            if log_callback:
                log_callback(msg)
            with open(log_file, "a", encoding="utf-8") as lf:
                lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
                lf.flush()

        # 1. Wait for GPU if requested
        if wait_gpu:
            _log(f"Checking GPU readiness (min {min_gpu_free_mb}MB free required)...")
            wait_for_gpu(
                min_free_mb=min_gpu_free_mb,
                poll_interval=10,
                log_fn=_log,
            )

        # 2. Build prompt
        if guidance_feedback:
            prompt = self.build_guidance_prompt(task, guidance_feedback)
        else:
            prompt = self.build_task_prompt(task)

        cmd = [
            self.agy_bin,
            "-p",
            prompt,
            "--model",
            self.model,
            "--effort",
            self.effort,
            "--mode",
            self.mode,
        ]

        if self.skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        effective_timeout = timeout if timeout is not None else self.default_timeout
        # 0 or None means no timeout
        if effective_timeout == 0:
            effective_timeout = None

        _log(f"=== AGY EXECUTION START FOR TASK {task.id} ===")
        _log(f"Command: {' '.join(cmd)}")
        _log(f"Working Directory: {worktree_path}")
        _log(f"Timeout: {'unlimited (no cutoff)' if effective_timeout is None else f'{effective_timeout}s'}")

        with open(log_file, "a", encoding="utf-8") as lf:
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(worktree_path),
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=effective_timeout,
                )
                returncode = proc.returncode
            except subprocess.TimeoutExpired:
                _log(f"[ERROR]: Antigravity execution timed out after {effective_timeout}s.")
                returncode = 124
            except Exception as e:
                _log(f"[ERROR]: Failed to launch agy: {str(e)}")
                returncode = 1

        duration = time.time() - start_time
        _log(f"=== AGY EXECUTION END (exit {returncode}, duration {duration:.1f}s) ===")
        return self._extract_report(task, worktree_path, returncode, duration)

    def _extract_report(
        self,
        task: Task,
        worktree_path: Path,
        returncode: int,
        duration: float,
    ) -> TaskReport:
        """Parse TASK_REPORT.json or construct a fallback report from git or workspace state."""
        report_json_path = worktree_path / "TASK_REPORT.json"
        report_data: Dict[str, Any] = {}

        if report_json_path.exists():
            try:
                report_data = json.loads(report_json_path.read_text(encoding="utf-8"))
            except Exception:
                report_data = {}

        # Inspect git commit and diff if Git repo
        git_commit = None
        diff_stat = None
        changed_files = []

        is_git = (worktree_path / ".git").exists() or shutil.which("git") is not None
        if is_git:
            rev_res = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
            )
            if rev_res.returncode == 0:
                git_commit = rev_res.stdout.strip()

            stat_res = subprocess.run(
                ["git", "diff", "--stat", "HEAD~1"],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
            )
            if stat_res.returncode == 0:
                diff_stat = stat_res.stdout.strip()

            changed_res = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~1"],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
            )
            if changed_res.returncode == 0:
                changed_files = [l.strip() for l in changed_res.stdout.splitlines() if l.strip()]

        status_str = report_data.get("status", "completed" if returncode == 0 else "failed")
        task_status = TaskStatus.COMPLETED if status_str == "completed" and returncode == 0 else TaskStatus.FAILED

        return TaskReport(
            task_id=task.id,
            agent=AgentType.AGY,
            status=task_status,
            summary=report_data.get("summary", f"Agy execution finished with exit code {returncode}."),
            files_modified=report_data.get("files_modified", changed_files),
            files_created=report_data.get("files_created", []),
            tests_run=report_data.get("tests_run", []),
            tests_passed=report_data.get("tests_passed", returncode == 0),
            git_commit=git_commit,
            diff_stat=diff_stat,
            notes=report_data.get("notes", []),
            duration_seconds=duration,
        )
