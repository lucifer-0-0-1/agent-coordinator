"""Command Line Interface for Agent Coordinator."""

import argparse
import sys
import json
from pathlib import Path
from typing import List, Optional

from coordinator.repo_init import ensure_repo_instructions, is_repo_initialized, is_git_repo
from coordinator.orchestrator import CoordinatorOrchestrator
from coordinator.schema import AgentType, ExecutionMode, Task, TaskPlan, TaskStatus
from coordinator.resource import get_gpu_status


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agent-coordinator",
        description="Dual-harness coordinator for Claude Code (Watcher/Guide) and Antigravity (Implementer/Reporter).",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    # init
    init_p = subparsers.add_parser("init", help="Auto-scaffold project instruction files.")
    init_p.add_argument("path", nargs="?", default=".", help="Target project directory")
    init_p.add_argument("--force", action="store_true", help="Overwrite existing instruction files")
    init_p.add_argument("--arch", action="store_true", help="Also generate docs/ARCHITECTURE.md")
    init_p.add_argument("--non-git", action="store_true", help="Do not run git init if not a Git repo")

    # dispatch
    disp_p = subparsers.add_parser("dispatch", help="Fast dispatch a task to an agent in an isolated workspace.")
    disp_p.add_argument("task", help="Task description or title")
    disp_p.add_argument("--agent", choices=["agy", "claude"], default="agy", help="Target agent harness")
    disp_p.add_argument("--files", help="Comma-separated list of assigned files")
    disp_p.add_argument("--criteria", help="Comma-separated acceptance criteria")
    disp_p.add_argument("--branch", help="Custom branch name")
    disp_p.add_argument("--no-worktree", action="store_true", help="Run directly in directory instead of isolated worktree")
    disp_p.add_argument("--auto-merge", action="store_true", help="Auto-merge branch if tests pass")
    disp_p.add_argument("--timeout", type=int, default=0, help="Timeout in seconds (0 = unlimited, default no timeout)")
    disp_p.add_argument("--wait-gpu", action="store_true", help="Wait until GPU is free before starting")
    disp_p.add_argument("--gpu-min-free", type=int, default=1500, help="Minimum free GPU VRAM in MB required (default 1500)")
    disp_p.add_argument("--path", default=".", help="Project directory")

    # guide
    guide_p = subparsers.add_parser("guide", help="Provide Watcher feedback to guide agy on an existing task.")
    guide_p.add_argument("task_id", help="Task ID to guide (e.g. agy-12345)")
    guide_p.add_argument("feedback", help="Guidance, review feedback, or fix instructions for agy")
    guide_p.add_argument("--timeout", type=int, default=0, help="Timeout in seconds (0 = unlimited)")
    guide_p.add_argument("--path", default=".", help="Project directory")

    # run
    run_p = subparsers.add_parser("run", help="Run a single or multi-agent task.")
    run_p.add_argument("prompt", help="Goal or task prompt")
    run_p.add_argument("--mode", choices=["single", "multi"], default="single", help="Execution mode")
    run_p.add_argument("--agent", choices=["agy", "claude", "both"], default="agy", help="Agent assignment")
    run_p.add_argument("--files", help="Comma-separated assigned files")
    run_p.add_argument("--criteria", help="Comma-separated acceptance criteria")
    run_p.add_argument("--no-worktree", action="store_true", help="Run in current directory instead of worktree")
    run_p.add_argument("--auto-merge", action="store_true", help="Auto-merge branch if tests pass")
    run_p.add_argument("--timeout", type=int, default=0, help="Timeout in seconds (0 = unlimited)")
    run_p.add_argument("--wait-gpu", action="store_true", help="Wait until GPU is free before starting")
    run_p.add_argument("--gpu-min-free", type=int, default=1500, help="Minimum free GPU VRAM in MB")
    run_p.add_argument("--path", default=".", help="Project directory")

    # status
    stat_p = subparsers.add_parser("status", help="Show coordinator status, worktrees, GPU health, and reports.")
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
        auto_git = not getattr(args, "non_git", False)
        results = ensure_repo_instructions(
            target_path,
            force=args.force,
            create_arch=args.arch,
            auto_git_init=auto_git,
        )
        for fname, action in results.items():
            print(f"  [{action.upper()}] {fname}")
        print("✅ Repository instructions ready.")
        return 0

    orchestrator = CoordinatorOrchestrator(target_path, auto_git_init=False)

    if args.subcommand == "dispatch":
        files = [f.strip() for f in args.files.split(",")] if args.files else []
        criteria = [c.strip() for c in args.criteria.split(",")] if args.criteria else []
        timeout_val = None if args.timeout == 0 else args.timeout

        print(f"🚀 Dispatching task to {args.agent.upper()}...")
        print(f"  Task: {args.task}")
        if files:
            print(f"  Files: {files}")
        if args.no_worktree:
            print("  Mode: in-place (no worktree)")
        if args.wait_gpu:
            print(f"  GPU Gate: waiting for {args.gpu_min_free}MB free VRAM")
        print(f"  Timeout: {'unlimited (no cutoff)' if timeout_val is None else f'{timeout_val}s'}")

        report = orchestrator.dispatch_agy(
            title=args.task,
            description=args.task,
            files=files,
            criteria=criteria,
            branch_name=args.branch,
            use_worktree=not args.no_worktree,
            auto_merge=args.auto_merge,
            timeout=timeout_val,
            wait_gpu=args.wait_gpu,
            min_gpu_free_mb=args.gpu_min_free,
        )

        status_icon = "✅" if report.status == TaskStatus.COMPLETED else "❌"
        print(f"\n{status_icon} Execution finished: {report.status.value.upper()}")
        print(f"  Summary: {report.summary}")
        print(f"  Duration: {report.duration_seconds:.1f}s")
        if report.git_commit:
            print(f"  Commit: {report.git_commit}")
        print(f"  Report written to: .coordinator/reports/{report.task_id}_report.md")
        return 0 if report.status == TaskStatus.COMPLETED else 1

    elif args.subcommand == "guide":
        timeout_val = None if args.timeout == 0 else args.timeout
        print(f"🧭 Guiding agy on task {args.task_id} with Watcher feedback...")
        report = orchestrator.guide_agy(
            task_id=args.task_id,
            feedback=args.feedback,
            timeout=timeout_val,
        )
        status_icon = "✅" if report.status == TaskStatus.COMPLETED else "❌"
        print(f"\n{status_icon} Guidance iteration finished: {report.status.value.upper()}")
        print(f"  Summary: {report.summary}")
        print(f"  Duration: {report.duration_seconds:.1f}s")
        print(f"  Updated Report: .coordinator/reports/{report.task_id}_report.md")
        return 0 if report.status == TaskStatus.COMPLETED else 1

    elif args.subcommand == "run":
        files = [f.strip() for f in args.files.split(",")] if args.files else []
        criteria = [c.strip() for c in args.criteria.split(",")] if args.criteria else []
        agent_type = AgentType(args.agent) if args.agent in ["agy", "claude"] else AgentType.AGY
        timeout_val = None if args.timeout == 0 else args.timeout

        print(f"🏃 Running {args.mode.upper()} task with {agent_type.value.upper()}...")
        report = orchestrator.run_single(
            prompt=args.prompt,
            agent=agent_type,
            files=files,
            criteria=criteria,
            use_worktree=not args.no_worktree,
            auto_merge=args.auto_merge,
            timeout=timeout_val,
            wait_gpu=args.wait_gpu,
            min_gpu_free_mb=args.gpu_min_free,
        )

        status_icon = "✅" if report.status == TaskStatus.COMPLETED else "❌"
        print(f"\n{status_icon} Status: {report.status.value.upper()}")
        print(f"  Summary: {report.summary}")
        print(f"  Report: .coordinator/reports/{report.task_id}_report.md")
        return 0 if report.status == TaskStatus.COMPLETED else 1

    elif args.subcommand == "status":
        print(f"📊 Coordinator Status for {target_path}")
        print(f"  Repo initialized: {'Yes' if is_repo_initialized(target_path) else 'No'}")
        print(f"  Git repository: {'Yes' if is_git_repo(target_path) else 'No (directory mode)'}")

        # GPU health check
        gpu_stat = get_gpu_status()
        if gpu_stat.get("available"):
            gpus = gpu_stat.get("gpus", [])
            gpu_desc = ", ".join(f"{g['name']} ({g['free_mb']:.0f}MB free)" for g in gpus)
            compute_desc = f"{len(gpu_stat.get('compute_apps', []))} apps running"
            print(f"  GPU Status: {gpu_desc} | {compute_desc}")
        else:
            print("  GPU Status: No NVIDIA GPU detected")

        worktrees = orchestrator.worktree_mgr.list_worktrees()
        coord_wts = [w for w in worktrees if ".coordinator/" in w.get("path", "")]
        print(f"  Active coordinator workspaces: {len(coord_wts)}")
        for wt in coord_wts:
            print(f"    - Identifier: {wt.get('branch', 'unknown')}, Path: {wt.get('path')}")

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
        print(f"🧹 Cleaned up {removed} coordinator workspaces/worktrees.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
