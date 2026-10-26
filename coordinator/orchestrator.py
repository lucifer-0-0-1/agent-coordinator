"""Main Coordinator Orchestrator for managing single and multi-agent runs."""

from pathlib import Path
from typing import Dict, Any, Optional, List, Union
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from coordinator.schema import (
    Task,
    TaskPlan,
    TaskReport,
    TaskStatus,
    AgentType,
    ExecutionMode,
)
from coordinator.repo_init import ensure_repo_instructions
from coordinator.worktree import GitWorktreeManager
from coordinator.harness.agy import AntigravityHarness
from coordinator.harness.claude import ClaudeHarness


class CoordinatorOrchestrator:
    """Coordinates execution across Claude Code and Antigravity (agy)."""

    def __init__(self, repo_path: Union[str, Path]):
        self.repo_path = Path(repo_path).resolve()
        self.coord_dir = self.repo_path / ".coordinator"
        self.coord_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir = self.coord_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.coord_dir / "state.json"

        # 1. Automatically ensure repository instructions exist on every run
        self.init_results = ensure_repo_instructions(self.repo_path)

        # 2. Worktree & Harnesses
        self.worktree_mgr = GitWorktreeManager(self.repo_path)
        self.agy_harness = AntigravityHarness()
        self.claude_harness = ClaudeHarness()

    def _save_state(self, plan: TaskPlan):
        """Save plan state to .coordinator/state.json."""
        self.state_file.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")

    def _save_report(self, report: TaskReport):
        """Save report to JSON and Markdown format."""
        json_file = self.reports_dir / f"{report.task_id}_report.json"
        json_file.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

        md_file = self.reports_dir / f"{report.task_id}_report.md"
        md_content = f"""# Task Report: {report.task_id}
- **Agent**: {report.agent.value}
- **Status**: {report.status.value.upper()}
- **Duration**: {report.duration_seconds:.1f}s
- **Git Commit**: `{report.git_commit or 'None'}`
- **Tests Passed**: {'✅ Yes' if report.tests_passed else '❌ No'}

## Summary
{report.summary}

## Files Modified
{chr(10).join(f'- `{f}`' for f in report.files_modified) if report.files_modified else 'None recorded'}

## Files Created
{chr(10).join(f'- `{f}`' for f in report.files_created) if report.files_created else 'None recorded'}

## Tests Executed
{chr(10).join(f'- {t}' for t in report.tests_run) if report.tests_run else 'None recorded'}

## Git Diffstat
```text
{report.diff_stat or 'No diff recorded'}
```

## Notes
{chr(10).join(f'- {n}' for n in report.notes) if report.notes else 'None'}
"""
        md_file.write_text(md_content, encoding="utf-8")

    def dispatch_agy(
        self,
        title: str,
        description: str,
        files: Optional[List[str]] = None,
        criteria: Optional[List[str]] = None,
        branch_name: Optional[str] = None,
        auto_merge: bool = False,
    ) -> TaskReport:
        """
        Fast dispatch of an implementation task to Antigravity (agy).
        Executes in an isolated worktree so Claude's active working tree is never disturbed.
        """
        task_id = f"agy-{int(time.time())}"
        task = Task(
            id=task_id,
            title=title,
            description=description,
            assigned_to=AgentType.AGY,
            files=files or [],
            criteria=criteria or [],
            branch=branch_name or f"agent/agy/{task_id}",
        )

        worktree_path, branch = self.worktree_mgr.create_worktree(
            task_id=task.id,
            branch_name=task.branch,
        )
        task.worktree_path = str(worktree_path)
        task.status = TaskStatus.RUNNING

        try:
            report = self.agy_harness.run_task(task, worktree_path)
            task.status = report.status
            task.completed_at = time.time()
            task.report = report.to_dict()
            self._save_report(report)

            if auto_merge and report.status == TaskStatus.COMPLETED:
                merged, msg = self.worktree_mgr.merge_branch(branch)
                report.notes.append(f"Auto-merge result: {msg}")
                self.worktree_mgr.remove_worktree(task.id, force=True)
                self._save_report(report)

            return report
        except Exception as e:
            err_report = TaskReport(
                task_id=task.id,
                agent=AgentType.AGY,
                status=TaskStatus.FAILED,
                summary=f"Exception during agy dispatch: {str(e)}",
                notes=[str(e)],
            )
            self._save_report(err_report)
            return err_report

    def run_single(
        self,
        prompt: str,
        agent: AgentType = AgentType.AGY,
        files: Optional[List[str]] = None,
        criteria: Optional[List[str]] = None,
        use_worktree: bool = True,
        auto_merge: bool = False,
    ) -> TaskReport:
        """Execute a single-agent task without disturbing other harnesses."""
        task_id = f"{agent.value}-{int(time.time())}"
        task = Task(
            id=task_id,
            title=prompt[:80],
            description=prompt,
            assigned_to=agent,
            files=files or [],
            criteria=criteria or [],
        )

        if use_worktree:
            worktree_path, branch = self.worktree_mgr.create_worktree(task.id)
            task.worktree_path = str(worktree_path)
            task.branch = branch
        else:
            worktree_path = self.repo_path

        if agent == AgentType.AGY:
            report = self.agy_harness.run_task(task, worktree_path)
        else:
            report = self.claude_harness.run_task(task, worktree_path)

        self._save_report(report)

        if use_worktree and auto_merge and report.status == TaskStatus.COMPLETED and task.branch:
            self.worktree_mgr.merge_branch(task.branch)
            self.worktree_mgr.remove_worktree(task.id, force=True)

        return report

    def run_multi(
        self,
        plan: TaskPlan,
        max_workers: int = 2,
        auto_merge: bool = False,
    ) -> Dict[str, TaskReport]:
        """
        Execute a multi-agent plan.
        Runs independent tasks in parallel across isolated worktrees.
        """
        self._save_state(plan)
        reports: Dict[str, TaskReport] = {}
        completed_task_ids = set()

        tasks_by_id = {t.id: t for t in plan.tasks}
        pending_tasks = list(plan.tasks)

        while pending_tasks:
            # Find tasks whose dependencies are satisfied
            ready_tasks = [
                t for t in pending_tasks
                if all(dep in completed_task_ids for dep in t.dependencies)
            ]

            if not ready_tasks:
                # Deadlock or circular dependency
                break

            # Execute ready tasks in parallel
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_task = {}
                for t in ready_tasks:
                    worktree_path, branch = self.worktree_mgr.create_worktree(t.id)
                    t.worktree_path = str(worktree_path)
                    t.branch = branch
                    t.status = TaskStatus.RUNNING

                    harness = self.agy_harness if t.assigned_to == AgentType.AGY else self.claude_harness
                    future = executor.submit(harness.run_task, t, worktree_path)
                    future_to_task[future] = t

                for future in as_completed(future_to_task):
                    t = future_to_task[future]
                    try:
                        report = future.result()
                        reports[t.id] = report
                        t.status = report.status
                        t.completed_at = time.time()
                        t.report = report.to_dict()
                        self._save_report(report)

                        if report.status == TaskStatus.COMPLETED:
                            completed_task_ids.add(t.id)
                            if auto_merge and t.branch:
                                self.worktree_mgr.merge_branch(t.branch)
                                self.worktree_mgr.remove_worktree(t.id, force=True)
                    except Exception as exc:
                        t.status = TaskStatus.FAILED
                        err_rep = TaskReport(
                            task_id=t.id,
                            agent=t.assigned_to,
                            status=TaskStatus.FAILED,
                            summary=f"Exception: {str(exc)}",
                        )
                        reports[t.id] = err_rep
                        self._save_report(err_rep)

            # Remove finished tasks from pending
            pending_tasks = [t for t in pending_tasks if t not in ready_tasks]
            self._save_state(plan)

        return reports

    def cleanup_all_worktrees(self) -> int:
        """Clean up all coordinator worktrees."""
        count = 0
        worktrees = self.worktree_mgr.list_worktrees()
        for wt in worktrees:
            path_str = wt.get("path", "")
            if ".coordinator/worktrees" in path_str:
                task_id = Path(path_str).name
                self.worktree_mgr.remove_worktree(task_id, force=True)
                count += 1
        return count
