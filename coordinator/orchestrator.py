"""Main Coordinator Orchestrator for managing single and multi-agent runs.
Handles Git worktrees, non-Git workspaces, GPU resource gating, and the Watcher-Implementer guidance loop.
"""

from pathlib import Path
from typing import Dict, Any, Optional, List, Union
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from coordinator.schema import (
    Task,
    TaskPlan,
    TaskReport,
    TaskStatus,
    AgentType,
    ExecutionMode,
)
from coordinator.repo_init import ensure_repo_instructions, is_git_repo, is_repo_initialized
from coordinator.worktree import WorkspaceManager
from coordinator.harness.agy import AntigravityHarness
from coordinator.harness.claude import ClaudeHarness
from coordinator.resource import get_gpu_status


class CoordinatorOrchestrator:
    """Coordinates execution across Claude Code (Watcher/Guide) and Antigravity (Implementer/Reporter)."""

    def __init__(self, repo_path: Union[str, Path], auto_git_init: bool = False):
        self.repo_path = Path(repo_path).resolve()
        self.is_git = is_git_repo(self.repo_path)
        self.coord_dir = self.repo_path / ".coordinator"
        self.coord_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir = self.coord_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.coord_dir / "state.json"

        # 1. Automatically ensure repository instructions exist on every run
        # For non-git directories, auto_git_init=False respects non-git status
        self.init_results = ensure_repo_instructions(self.repo_path, auto_git_init=auto_git_init)

        # 2. Workspace Manager & Harnesses
        self.worktree_mgr = WorkspaceManager(self.repo_path)
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

## Diffstat
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
        use_worktree: bool = True,
        auto_merge: bool = False,
        timeout: Optional[int] = None,  # None = no timeout (unlimited)
        wait_gpu: bool = False,
        min_gpu_free_mb: int = 1500,
    ) -> TaskReport:
        """
        Fast dispatch of an implementation task to Antigravity (agy).
        - In Git mode with use_worktree=True: runs in an isolated git worktree.
        - In non-Git mode (or use_worktree=False): runs in-place or snapshot workspace.
        - timeout=None: no arbitrary 30-minute cutoff; long jobs are allowed to complete.
        - wait_gpu=True: waits until GPU VRAM is free before launching.
        """
        task_id = f"agy-{int(time.time())}"
        task = Task(
            id=task_id,
            title=title,
            description=description,
            assigned_to=AgentType.AGY,
            files=files or [],
            criteria=criteria or [],
            branch=branch_name or (f"agent/agy/{task_id}" if self.is_git else "in-place"),
        )

        workspace_path, branch = self.worktree_mgr.create_workspace(
            task_id=task.id,
            use_worktree=use_worktree,
            branch_name=task.branch,
            assigned_files=task.files,
        )
        task.worktree_path = str(workspace_path)
        task.status = TaskStatus.RUNNING

        try:
            report = self.agy_harness.run_task(
                task=task,
                worktree_path=workspace_path,
                timeout=timeout,
                wait_gpu=wait_gpu,
                min_gpu_free_mb=min_gpu_free_mb,
            )
            task.status = report.status
            task.completed_at = time.time()
            task.report = report.to_dict()
            self._save_report(report)

            if auto_merge and report.status == TaskStatus.COMPLETED and self.is_git and use_worktree:
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

    def guide_agy(
        self,
        task_id: str,
        feedback: str,
        timeout: Optional[int] = None,
    ) -> TaskReport:
        """
        Claude (Watcher) provides feedback to guide agy on an existing task.
        Agy re-inspects the workspace, addresses the review comments, and updates the report.
        """
        # Find previous report
        json_file = self.reports_dir / f"{task_id}_report.json"
        previous_data = {}
        if json_file.exists():
            try:
                previous_data = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Locate existing workspace or worktree
        sanitized_id = task_id.replace("agent/task-", "").replace("agy-", "")
        wt_candidate = self.worktree_mgr.worktrees_base / task_id
        ws_candidate = self.worktree_mgr.workspaces_base / task_id
        if wt_candidate.exists():
            target_path = wt_candidate
        elif ws_candidate.exists():
            target_path = ws_candidate
        else:
            target_path = self.repo_path

        task = Task(
            id=task_id,
            title=f"Guided iteration on {task_id}",
            description=f"Addressing Watcher (Claude) review comments",
            assigned_to=AgentType.AGY,
            files=previous_data.get("files_modified", []),
        )

        report = self.agy_harness.run_task(
            task=task,
            worktree_path=target_path,
            timeout=timeout,
            guidance_feedback=feedback,
        )
        self._save_report(report)
        return report

    def run_single(
        self,
        prompt: str,
        agent: AgentType = AgentType.AGY,
        files: Optional[List[str]] = None,
        criteria: Optional[List[str]] = None,
        use_worktree: bool = True,
        auto_merge: bool = False,
        timeout: Optional[int] = None,
        wait_gpu: bool = False,
        min_gpu_free_mb: int = 1500,
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

        workspace_path, branch = self.worktree_mgr.create_workspace(
            task_id=task.id,
            use_worktree=use_worktree,
            assigned_files=files,
        )
        task.worktree_path = str(workspace_path)
        task.branch = branch

        if agent == AgentType.AGY:
            report = self.agy_harness.run_task(
                task=task,
                worktree_path=workspace_path,
                timeout=timeout,
                wait_gpu=wait_gpu,
                min_gpu_free_mb=min_gpu_free_mb,
            )
        else:
            report = self.claude_harness.run_task(task, workspace_path)

        self._save_report(report)

        if use_worktree and auto_merge and report.status == TaskStatus.COMPLETED and self.is_git and task.branch:
            self.worktree_mgr.merge_branch(task.branch)
            self.worktree_mgr.remove_worktree(task.id, force=True)

        return report

    def get_live_logs(self, task_id: Optional[str] = None, lines: int = 30) -> Dict[str, Any]:
        """
        Inspect live progress and recent logs of an agy task without spending LLM tokens.
        """
        all_logs = []
        # Search coordinator logs and worktree logs
        log_dirs = [self.coord_dir / "logs"]
        wt_base = self.coord_dir / "worktrees"
        if wt_base.exists():
            for p in wt_base.iterdir():
                if p.is_dir() and (p / ".coordinator" / "logs").exists():
                    log_dirs.append(p / ".coordinator" / "logs")

        for ld in log_dirs:
            if ld.exists():
                for f in ld.glob("*.log"):
                    all_logs.append(f)

        if not all_logs:
            return {"found": False, "message": "No log files found."}

        # Filter by task_id if provided
        target_log = None
        if task_id:
            for l in all_logs:
                if task_id in l.name:
                    target_log = l
                    break
        if not target_log:
            # Most recent log
            target_log = max(all_logs, key=lambda p: p.stat().st_mtime)

        try:
            content = target_log.read_text(encoding="utf-8", errors="replace").splitlines()
            tail_lines = content[-lines:] if len(content) > lines else content
            return {
                "found": True,
                "log_file": str(target_log),
                "total_lines": len(content),
                "tail": tail_lines,
                "modified_seconds_ago": time.time() - target_log.stat().st_mtime,
            }
        except Exception as e:
            return {"found": False, "error": str(e)}

    def cleanup_all_worktrees(self) -> int:
        """Clean up all coordinator worktrees and temporary workspaces."""
        count = 0
        worktrees = self.worktree_mgr.list_worktrees()
        for wt in worktrees:
            path_str = wt.get("path", "")
            if ".coordinator/worktrees" in path_str or ".coordinator/workspaces" in path_str:
                task_id = Path(path_str).name
                self.worktree_mgr.remove_worktree(task_id, force=True)
                count += 1
        return count
