"""Standard Model Context Protocol (MCP) stdio server for Agent Coordinator."""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from coordinator.repo_init import ensure_repo_instructions, is_repo_initialized, is_git_repo
from coordinator.orchestrator import CoordinatorOrchestrator
from coordinator.schema import AgentType, TaskStatus, TaskReport, Task, TaskPlan
from coordinator.resource import get_gpu_status


def get_tool_definitions() -> List[Dict[str, Any]]:
    """Return JSON schemas for coordinator tools."""
    return [
        {
            "name": "coord_init",
            "description": "Auto-scaffold or verify repository instruction files (AGENTS.md, CLAUDE.md, .agents/AGENTS.md, .gitignore) to enable dual-harness coordination in Git or non-Git projects.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Path to the project repository (defaults to current working directory).",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Overwrite existing instruction files if true.",
                        "default": False,
                    },
                    "create_arch": {
                        "type": "boolean",
                        "description": "Also scaffold docs/ARCHITECTURE.md if true.",
                        "default": False,
                    },
                    "non_git": {
                        "type": "boolean",
                        "description": "Do not run git init if project is not a git repository.",
                        "default": False,
                    },
                },
            },
        },
        {
            "name": "coord_dispatch",
            "description": "Dispatch an implementation task to Antigravity (agy). Runs in an isolated Git worktree or directory workspace without touching Claude's active working tree. Supports long-running tasks without 30-min timeout and optional GPU gating.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Detailed task description, goal, and implementation instructions.",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of files assigned to this task scope.",
                    },
                    "criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Measurable acceptance criteria, targeted test commands, and quality checks.",
                    },
                    "branch_name": {
                        "type": "string",
                        "description": "Custom branch name for the task worktree (defaults to agent/agy/<task_id>).",
                    },
                    "use_worktree": {
                        "type": "boolean",
                        "description": "Use an isolated Git worktree/workspace. Set to false for direct in-place execution.",
                        "default": True,
                    },
                    "auto_merge": {
                        "type": "boolean",
                        "description": "Auto-merge the task branch into the current branch if tests pass.",
                        "default": False,
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds. 0 = no timeout (unlimited, no cutoff). Default is 0.",
                        "default": 0,
                    },
                    "wait_gpu": {
                        "type": "boolean",
                        "description": "Wait until GPU VRAM is free before starting task execution.",
                        "default": False,
                    },
                    "gpu_min_free": {
                        "type": "integer",
                        "description": "Minimum free GPU VRAM in MB required when wait_gpu is true (default 1500).",
                        "default": 1500,
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Path to the project repository.",
                    },
                },
                "required": ["task"],
            },
        },
        {
            "name": "coord_guide",
            "description": "As the Watcher (Claude Code), guide agy on an existing task with review comments or fix instructions. Agy addresses the feedback in the existing workspace and updates the report.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID previously dispatched (e.g. agy-12345).",
                    },
                    "feedback": {
                        "type": "string",
                        "description": "Specific guidance, review comments, failing test details, or required code fixes.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (0 = unlimited).",
                        "default": 0,
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Path to the project repository.",
                    },
                },
                "required": ["task_id", "feedback"],
            },
        },
        {
            "name": "coord_status",
            "description": "Inspect active coordinator worktrees, recent completion reports, GPU availability, and repository instruction readiness.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Path to the project repository.",
                    },
                },
            },
        },
        {
            "name": "coord_gpu_status",
            "description": "Check current NVIDIA GPU availability, free VRAM, and active compute processes (costs 0 LLM tokens).",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "coord_logs",
            "description": "Watch live progress and inspect the recent log tail of an active or recent agy task (costs 0 LLM tokens).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Specific task ID to tail (optional; defaults to the most recent run).",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of recent log lines to view (default 25).",
                        "default": 25,
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Path to the project repository.",
                    },
                },
            },
        },
        {
            "name": "coord_plan",
            "description": "Divide a high-level goal into a multi-agent plan with Claude as Watcher/Architect/Implementer and Agy as Implementer/Reporter.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "High-level goal or feature description.",
                    },
                    "tasks": {
                        "type": "array",
                        "description": "List of subtasks.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "assigned_to": {"type": "string", "enum": ["claude", "agy"]},
                                "files": {"type": "array", "items": {"type": "string"}},
                                "criteria": {"type": "array", "items": {"type": "string"}},
                                "dependencies": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["id", "title", "description", "assigned_to"],
                        },
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Path to the project repository.",
                    },
                },
                "required": ["goal"],
            },
        },
        {
            "name": "coord_merge",
            "description": "Merge a completed task branch from an isolated worktree into the active branch and clean up the worktree.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "branch_name": {
                        "type": "string",
                        "description": "Branch name to merge (e.g. agent/agy/agy-12345).",
                    },
                    "into_branch": {
                        "type": "string",
                        "description": "Target branch to merge into (defaults to current active branch).",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task ID whose worktree should be removed after merge.",
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Path to the project repository.",
                    },
                },
                "required": ["branch_name"],
            },
        },
        {
            "name": "coord_clean",
            "description": "Clean up all coordinator worktrees and temporary task directories.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Path to the project repository.",
                    },
                },
            },
        },
    ]


class MCPServer:
    """Stdio JSON-RPC MCP server."""

    def __init__(self):
        self.running = True

    def handle_call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        project_path = Path(arguments.get("project_path") or ".").resolve()
        auto_git = not arguments.get("non_git", False)
        orch = CoordinatorOrchestrator(project_path, auto_git_init=auto_git)

        if name == "coord_init":
            results = ensure_repo_instructions(
                project_path,
                force=arguments.get("force", False),
                create_arch=arguments.get("create_arch", False),
                auto_git_init=auto_git,
            )
            text_lines = [f"Repository instructions for {project_path}:"]
            for f, status in results.items():
                text_lines.append(f"- [{status.upper()}] {f}")
            return {"content": [{"type": "text", "text": "\n".join(text_lines)}]}

        elif name == "coord_dispatch":
            task_desc = arguments.get("task", "")
            files = arguments.get("files", [])
            criteria = arguments.get("criteria", [])
            branch = arguments.get("branch_name")
            use_worktree = arguments.get("use_worktree", True)
            auto_merge = arguments.get("auto_merge", False)
            raw_timeout = arguments.get("timeout", 0)
            timeout = None if raw_timeout == 0 else raw_timeout
            wait_gpu = arguments.get("wait_gpu", False)
            min_gpu_free = arguments.get("gpu_min_free", 1500)

            report = orch.dispatch_agy(
                title=task_desc[:80],
                description=task_desc,
                files=files,
                criteria=criteria,
                branch_name=branch,
                use_worktree=use_worktree,
                auto_merge=auto_merge,
                timeout=timeout,
                wait_gpu=wait_gpu,
                min_gpu_free_mb=min_gpu_free,
            )

            status_icon = "✅" if report.status == TaskStatus.COMPLETED else "❌"
            res_text = f"""{status_icon} Task {report.task_id} finished with status: {report.status.value.upper()}
Summary: {report.summary}
Duration: {report.duration_seconds:.1f}s
Git Commit: {report.git_commit or 'None (or non-git)'}
Tests Passed: {report.tests_passed}
Modified Files: {', '.join(report.files_modified) if report.files_modified else 'None'}
Created Files: {', '.join(report.files_created) if report.files_created else 'None'}

Diffstat:
{report.diff_stat or 'No diff recorded'}

Report saved at: .coordinator/reports/{report.task_id}_report.md
"""
            return {"content": [{"type": "text", "text": res_text}]}

        elif name == "coord_guide":
            task_id = arguments["task_id"]
            feedback = arguments["feedback"]
            raw_timeout = arguments.get("timeout", 0)
            timeout = None if raw_timeout == 0 else raw_timeout

            report = orch.guide_agy(task_id=task_id, feedback=feedback, timeout=timeout)
            status_icon = "✅" if report.status == TaskStatus.COMPLETED else "❌"
            res_text = f"""{status_icon} Guidance iteration on {task_id} finished: {report.status.value.upper()}
Summary: {report.summary}
Duration: {report.duration_seconds:.1f}s
Tests Passed: {report.tests_passed}
Updated Diffstat:
{report.diff_stat or 'No diff recorded'}

Updated report saved at: .coordinator/reports/{report.task_id}_report.md
"""
            return {"content": [{"type": "text", "text": res_text}]}

        elif name == "coord_gpu_status":
            stat = get_gpu_status()
            if not stat.get("available"):
                return {"content": [{"type": "text", "text": "No NVIDIA GPU detected or nvidia-smi unavailable."}]}
            lines = ["NVIDIA GPU Status:"]
            for g in stat.get("gpus", []):
                lines.append(f"- GPU {g['index']} ({g['name']}): {g['free_mb']:.0f}MB free / {g['total_mb']:.0f}MB total ({g['utilization_pct']:.0f}% util)")
            compute_apps = stat.get("compute_apps", [])
            lines.append(f"- Active Compute Processes: {len(compute_apps)}")
            for app in compute_apps:
                lines.append(f"  * PID {app['pid']} ({app['process_name']}): {app['used_mb']:.0f}MB VRAM")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        elif name == "coord_logs":
            task_id = arguments.get("task_id")
            num_lines = arguments.get("lines", 25)
            log_info = orch.get_live_logs(task_id=task_id, lines=num_lines)
            if not log_info.get("found"):
                return {"content": [{"type": "text", "text": log_info.get("message", "No active or recent logs found.")]}
            tail_text = "\n".join(log_info.get("tail", []))
            res_text = f"""📄 Log: {log_info.get('log_file')}
Last updated: {log_info.get('modified_seconds_ago', 0):.1f}s ago | Total lines: {log_info.get('total_lines')}

Recent Output:
```text
{tail_text}
```"""
            return {"content": [{"type": "text", "text": res_text}]}

        elif name == "coord_status":
            is_init = is_repo_initialized(project_path)
            is_git = is_git_repo(project_path)
            worktrees = orch.worktree_mgr.list_worktrees()
            coord_wts = [w for w in worktrees if ".coordinator/" in w.get("path", "")]
            reports = list(orch.reports_dir.glob("*_report.json"))

            # GPU status line
            gpu_line = "GPU: None"
            gpu_stat = get_gpu_status()
            if gpu_stat.get("available") and gpu_stat.get("gpus"):
                g0 = gpu_stat["gpus"][0]
                gpu_line = f"GPU: {g0['name']} ({g0['free_mb']:.0f}MB free, {len(gpu_stat.get('compute_apps', []))} apps)"

            res_lines = [
                f"Coordinator Status for: {project_path}",
                f"- Repository instructions initialized: {'Yes' if is_init else 'No'}",
                f"- Git repository: {'Yes' if is_git else 'No (directory mode)'}",
                f"- {gpu_line}",
                f"- Active coordinator workspaces: {len(coord_wts)}",
            ]
            for wt in coord_wts:
                res_lines.append(f"  * Identifier: {wt.get('branch', 'unknown')} (Path: {wt.get('path')})")

            res_lines.append(f"- Recent task reports: {len(reports)}")
            for r in sorted(reports, key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                try:
                    d = json.loads(r.read_text())
                    res_lines.append(f"  * {d.get('task_id')}: {d.get('status')} by {d.get('agent')}")
                except Exception:
                    pass

            return {"content": [{"type": "text", "text": "\n".join(res_lines)}]}

        elif name == "coord_plan":
            goal = arguments.get("goal", "")
            raw_tasks = arguments.get("tasks", [])
            tasks = []
            for t in raw_tasks:
                tasks.append(
                    Task(
                        id=t["id"],
                        title=t["title"],
                        description=t["description"],
                        assigned_to=AgentType(t.get("assigned_to", "agy")),
                        files=t.get("files", []),
                        criteria=t.get("criteria", []),
                        dependencies=t.get("dependencies", []),
                    )
                )
            plan = TaskPlan(goal=goal, tasks=tasks)
            orch._save_state(plan)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Plan saved with {len(tasks)} tasks. State stored at .coordinator/state.json",
                    }
                ]
            }

        elif name == "coord_merge":
            branch = arguments["branch_name"]
            into_branch = arguments.get("into_branch")
            task_id = arguments.get("task_id")

            success, msg = orch.worktree_mgr.merge_branch(branch, into_branch=into_branch)
            if success and task_id:
                orch.worktree_mgr.remove_worktree(task_id, force=True)

            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"{'✅ Merge succeeded' if success else '❌ Merge failed'}: {msg}",
                    }
                ]
            }

        elif name == "coord_clean":
            count = orch.cleanup_all_worktrees()
            return {"content": [{"type": "text", "text": f"Cleaned up {count} coordinator workspaces."}]}

        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

    def run(self):
        """Main stdio loop."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except Exception as e:
                continue

            msg_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})

            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "agent-coordinator", "version": "0.2.0"},
                    },
                }
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": get_tool_definitions()},
                }
            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                try:
                    result = self.handle_call_tool(tool_name, tool_args)
                    response = {"jsonrpc": "2.0", "id": msg_id, "result": result}
                except Exception as exc:
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32603, "message": str(exc)},
                    }
            elif method == "ping":
                response = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def main():
    server = MCPServer()
    server.run()


if __name__ == "__main__":
    main()
