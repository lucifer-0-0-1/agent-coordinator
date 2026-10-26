"""Command Line Interface for Agent Coordinator."""

import argparse
import sys
import json
from pathlib import Path
from typing import List, Optional

from coordinator.repo_init import ensure_repo_instructions, is_repo_initialized
from coordinator.orchestrator import CoordinatorOrchestrator
from coordinator.schema import AgentType, ExecutionMode, Task, TaskPlan, TaskStatus


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agent-coordinator",
        description="Dual-harness coordinator for Claude Code and Antigravity (agy).",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    # init
    init_p = subparsers.add_parser("init", help="Auto-scaffold project instruction files.")
    init_p.add_argument("path", nargs="?", default=".", help="Target project directory")
    init_p.add_argument("--force", action="store_true", help="Overwrite existing instruction files")
    init_p.add_argument("--arch", action="store_true", help="Also generate docs/ARCHITECTURE.md")

    # dispatch
    disp_p = subparsers.add_parser("dispatch", help="Fast dispatch a task to an agent in an isolated worktree.")
    disp_p.add_argument("task", help="Task description or title")
    disp_p.add_argument("--agent", choices=["agy", "claude"], default="agy", help="Target agent harness")
    disp_p.add_argument("--files", help="Comma-separated list of assigned files")
    disp_p.add_argument("--criteria", help="Comma-separated acceptance criteria")
    disp_p.add_argument("--branch", help="Custom branch name")
    disp_p.add_argument("--auto-merge", action="store_true", help="Auto-merge branch if tests pass")
    disp_p.add_argument("--path", default=".", help="Project directory")

    # run
    run_p = subparsers.add_parser("run", help="Run a single or multi-agent task.")
    run_p.add_argument("prompt", help="Goal or task prompt")
    run_p.add_argument("--mode", choices=["single", "multi"], default="single", help="Execution mode")
    run_p.add_argument("--agent", choices=["agy", "claude", "both"], default="agy", help="Agent assignment")
    run_p.add_argument("--files", help="Comma-separated assigned files")
    run_p.add_argument("--criteria", help="Comma-separated acceptance criteria")
    run_p.add_argument("--no-worktree", action="store_true", help="Run in current directory instead of worktree")
    run_p.add_argument("--auto-merge", action="store_true", help="Auto-merge branch if tests pass")
    run_p.add_argument("--path", default=".", help="Project directory")

    # status
    stat_p = subparsers.add_parser("status", help="Show coordinator status, worktrees, and reports.")
    stat_p.add_argument("--path", default=".", help="Project directory")

    # clean
    clean_p = subparsers.add_parser("clean", help="Clean up coordinator worktrees and temporary files.")
    clean_p.add_argument("--path", default=".", help="Project directory")

    return parser.parse_args(args)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if not args.subcommand:
        print("agent-coordinator: No subcommand provided. Use 'agent-coordinator --help' for usage.")
        return 1

    target_path = Path(getattr(args, "path", ".")).resolve()

    if args.subcommand == "init":
        print(f"🔧 Initializing instructions for {target_path}...")
        results = ensure_repo_instructions(target_path, force=args.force, create_arch=args.arch)
        for fname, action in results.items():
            print(f"  [{action.upper()}] {fname}")
        print("✅ Repository instructions ready.")
        return 0

    orchestrator = CoordinatorOrchestrator(target_path)

    if args.subcommand == "dispatch":
        files = [f.strip() for f in args.files.split(",")] if args.files else []
        criteria = [c.strip() for c in args.criteria.split(",")] if args.criteria else []
        print(f"🚀 Dispatching task to {args.agent.upper()} in isolated worktree...")
        print(f"  Task: {args.task}")
        if files:
            print(f"  Files: {files}")

        report = orchestrator.dispatch_agy(
            title=args.task,
            description=args.task,
            files=files,
            criteria=criteria,
            branch_name=args.branch,
            auto_merge=args.auto_merge,
        )

        status_icon = "✅" if report.status == TaskStatus.COMPLETED else "❌"
        print(f"\n{status_icon} Execution finished: {report.status.value.upper()}")
        print(f"  Summary: {report.summary}")
        print(f"  Duration: {report.duration_seconds:.1f}s")
        if report.git_commit:
            print(f"  Commit: {report.git_commit}")
        print(f"  Report written to: .coordinator/reports/{report.task_id}_report.md")
        return 0 if report.status == TaskStatus.COMPLETED else 1

    elif args.subcommand == "run":
        files = [f.strip() for f in args.files.split(",")] if args.files else []
        criteria = [c.strip() for c in args.criteria.split(",")] if args.criteria else []
        agent_type = AgentType(args.agent) if args.agent in ["agy", "claude"] else AgentType.AGY

        print(f"🏃 Running {args.mode.upper()} task with {agent_type.value.upper()}...")
        report = orchestrator.run_single(
            prompt=args.prompt,
            agent=agent_type,
            files=files,
            criteria=criteria,
            use_worktree=not args.no_worktree,
            auto_merge=args.auto_merge,
        )

        status_icon = "✅" if report.status == TaskStatus.COMPLETED else "❌"
        print(f"\n{status_icon} Status: {report.status.value.upper()}")
        print(f"  Summary: {report.summary}")
        print(f"  Report: .coordinator/reports/{report.task_id}_report.md")
        return 0 if report.status == TaskStatus.COMPLETED else 1

    elif args.subcommand == "status":
        print(f"📊 Coordinator Status for {target_path}")
        print(f"  Repo initialized: {'Yes' if is_repo_initialized(target_path) else 'No'}")
        worktrees = orchestrator.worktree_mgr.list_worktrees()
        coord_wts = [w for w in worktrees if ".coordinator/worktrees" in w.get("path", "")]
        print(f"  Active coordinator worktrees: {len(coord_wts)}")
        for wt in coord_wts:
            print(f"    - Branch: {wt.get('branch', 'unknown')}, Path: {wt.get('path')}")

        reports = list(orchestrator.reports_dir.glob("*_report.json"))
        print(f"  Saved reports: {len(reports)}")
        for r in sorted(reports, key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
            try:
                d = json.loads(r.read_text())
                print(f"    - {d.get('task_id')}: {d.get('status')} ({d.get('agent')})")
            except Exception:
                pass
        return 0

    elif args.subcommand == "clean":
        removed = orchestrator.cleanup_all_worktrees()
        print(f"🧹 Cleaned up {removed} coordinator worktrees.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
