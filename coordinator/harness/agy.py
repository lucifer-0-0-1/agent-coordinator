"""Antigravity (agy) CLI execution harness."""

from pathlib import Path
from typing import Dict, Any, Optional, List
import subprocess
import json
import time
import shutil

from coordinator.harness.base import BaseHarness
from coordinator.schema import Task, TaskReport, TaskStatus, AgentType


class AntigravityHarness(BaseHarness):
    """Executes tasks autonomously using Google Antigravity CLI (agy)."""

    def __init__(
        self,
        model: str = "gemini-3.8-flash-high",
        effort: str = "high",
        mode: str = "accept-edits",
        skip_permissions: bool = True,
        agy_bin: Optional[str] = None,
    ):
        self.model = model
        self.effort = effort
        self.mode = mode
        self.skip_permissions = skip_permissions
        self.agy_bin = agy_bin or self._find_agy()

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
6. Commit your changes cleanly on your task branch with an imperative message.
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

    def run_task(self, task: Task, worktree_path: Path) -> TaskReport:
        """Run the task inside the given worktree using agy."""
        start_time = time.time()
        log_dir = worktree_path / ".coordinator" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"agy_{task.id}_{int(start_time)}.log"

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

        with open(log_file, "w", encoding="utf-8") as lf:
            lf.write(f"=== AGY EXECUTION START FOR TASK {task.id} ===\n")
            lf.write(f"Command: {' '.join(cmd)}\n")
            lf.write(f"Worktree: {worktree_path}\n\n")
            lf.flush()

            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(worktree_path),
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=1800,  # 30 minute safety timeout
                )
                returncode = proc.returncode
            except subprocess.TimeoutExpired:
                lf.write("\n\n[ERROR]: Antigravity execution timed out after 30 minutes.\n")
                returncode = 124
            except Exception as e:
                lf.write(f"\n\n[ERROR]: Failed to launch agy: {str(e)}\n")
                returncode = 1

        duration = time.time() - start_time
        return self._extract_report(task, worktree_path, returncode, duration)

    def _extract_report(
        self,
        task: Task,
        worktree_path: Path,
        returncode: int,
        duration: float,
    ) -> TaskReport:
        """Parse TASK_REPORT.json or construct a fallback report from git state."""
        report_json_path = worktree_path / "TASK_REPORT.json"
        report_data: Dict[str, Any] = {}

        if report_json_path.exists():
            try:
                report_data = json.loads(report_json_path.read_text(encoding="utf-8"))
            except Exception:
                report_data = {}

        # Inspect git commit and diff
        git_commit = None
        diff_stat = None
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

        # Check modified files via git
        changed_res = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
        )
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
