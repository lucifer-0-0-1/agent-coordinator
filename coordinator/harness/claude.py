"""Claude Code execution and watcher harness."""

from pathlib import Path
from typing import Dict, Any, Optional, List
import subprocess
import json
import time
import shutil

from coordinator.harness.base import BaseHarness
from coordinator.schema import Task, TaskReport, TaskStatus, AgentType


class ClaudeHarness(BaseHarness):
    """Harness for Claude Code (headless runs or watcher instructions)."""

    def __init__(self, claude_bin: Optional[str] = None):
        self.claude_bin = claude_bin or shutil.which("claude")

    def build_task_prompt(self, task: Task) -> str:
        """Construct the prompt for Claude Code."""
        files_str = "\n".join(f"- {f}" for f in task.files) if task.files else "Any relevant files."
        criteria_str = "\n".join(f"- {c}" for c in task.criteria) if task.criteria else "Verify all tests pass."

        prompt = f"""You are the primary implementation agent (Claude Code).

Task ID: {task.id}
Title: {task.title}

Description:
{task.description}

Assigned File Scope:
{files_str}

Acceptance Criteria:
{criteria_str}

Instructions:
1. Read AGENTS.md and CLAUDE.md for project conventions.
2. Inspect only the files in your assigned scope.
3. Implement the feature or fix.
4. Add or update targeted unit tests.
5. Verify tests are passing.
6. Commit your changes with an imperative commit message.
7. Write TASK_REPORT.json summarizing status, changes, and tests.
"""
        return prompt.strip()

    def run_task(self, task: Task, worktree_path: Path) -> TaskReport:
        """Execute task with Claude Code."""
        start_time = time.time()
        log_dir = worktree_path / ".coordinator" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"claude_{task.id}_{int(start_time)}.log"

        prompt = self.build_task_prompt(task)

        if not self.claude_bin:
            # If claude is not in PATH for headless runs, write the briefing file for interactive Claude
            briefing_file = worktree_path / f"TASK_{task.id}_BRIEF.md"
            briefing_file.write_text(prompt, encoding="utf-8")
            return TaskReport(
                task_id=task.id,
                agent=AgentType.CLAUDE,
                status=TaskStatus.PENDING,
                summary=f"Briefing written to {briefing_file} for interactive execution.",
                notes=["Claude CLI was not found in PATH for headless mode; briefing prepared for interactive Claude."],
                duration_seconds=time.time() - start_time,
            )

        cmd = [self.claude_bin, "-p", prompt, "--dangerously-skip-permissions"]

        with open(log_file, "w", encoding="utf-8") as lf:
            lf.write(f"=== CLAUDE EXECUTION START FOR TASK {task.id} ===\n")
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(worktree_path),
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=1800,
                )
                returncode = proc.returncode
            except Exception as e:
                lf.write(f"[ERROR]: {str(e)}\n")
                returncode = 1

        duration = time.time() - start_time
        task_status = TaskStatus.COMPLETED if returncode == 0 else TaskStatus.FAILED
        return TaskReport(
            task_id=task.id,
            agent=AgentType.CLAUDE,
            status=task_status,
            summary=f"Claude execution finished with code {returncode}.",
            duration_seconds=duration,
        )
