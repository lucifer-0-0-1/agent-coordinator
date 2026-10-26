"""Standard instruction templates for auto-scaffolding repository rules."""

AGENTS_MD_TEMPLATE = """# Project Instructions & Agent Guidelines

## 1. Dual-Harness Roles & Workflow
- **Claude Code**: Watcher, Architect, and Interactive Implementer. Claude oversees overall project architecture, coordinates multi-agent goals, inspects reports, reviews diffs, and implements interactive tasks.
- **Antigravity (`agy`)**: Implementer and Reporter. Antigravity runs bounded, well-specified implementation tasks in isolated Git worktrees, executes targeted tests, and provides structured completion reports.
- **Git Worktree Isolation**: Neither harness may modify the active working directory of the other. All autonomous background runs must occur inside a dedicated Git worktree branch (`agent/<agent>/<task-id>`).

## 2. Token Efficiency Guidelines
- **Targeted File Inspection**: Only read files directly related to the assigned task. Never scan the entire repository tree.
- **Diff-Based Review**: Review only git diffs (`git diff HEAD~1` or between task branch and base branch), not entire files or full histories.
- **Do Not Duplicate Context**: Use concise summaries when passing messages or reports between harnesses.
- **No LLM Over-Orchestration**: Use deterministic file and git commands for checks, builds, tests, and branch management.

## 3. Implementation & Testing Protocol
1. **Scope Boundaries**: Modify ONLY the files assigned to the task.
2. **Interface First**: When adding dependencies between modules, establish interfaces/signatures before writing implementations.
3. **Targeted Tests**: Always add or update unit tests covering the newly added logic or edge cases.
4. **Pre-Commit Verification**: Run the relevant test suite before reporting completion.
5. **Clean Commits**: Commit changes on the task branch with clear imperative messages (e.g., `feat(module): implement parser logic`).

## 4. Completion & Reporting Standard
When completing a task, the implementer (especially `agy`) must generate a `TASK_REPORT.json` (or standard markdown report) at the worktree root containing:
```json
{
  "task_id": "<task-id>",
  "status": "completed | failed",
  "summary": "Brief explanation of what was implemented",
  "files_modified": ["path/to/file1"],
  "files_created": ["path/to/new_file"],
  "tests_run": ["command or test name"],
  "tests_passed": true,
  "git_commit": "<commit-hash>",
  "notes": ["any edge cases or assumptions"]
}
```
"""

CLAUDE_MD_TEMPLATE = """# Claude Code Instructions

Read the repository-root `AGENTS.md` for shared project rules and multi-agent protocols.

## Claude's Role
You are the **Watcher, Architect, and Primary Implementer** for this workspace.

### Working with Antigravity (`agy`):
- When a task can be parallelized or offloaded, dispatch it to `agy` using the coordinator:
  ```bash
  agent-coordinator dispatch "Implement module X" --files "src/x.py,tests/test_x.py" --criteria "Pass pytest"
  ```
- `agy` will execute in an isolated Git worktree (`.coordinator/worktrees/agy-...`) so your active working tree and uncommitted files are completely undisturbed.
- When `agy` completes, inspect its concise report (`TASK_REPORT.json`) and git diff. Do NOT re-read all files if the diff and test passes are clean.
- Merge the task branch after verifying the acceptance criteria.

## General Preferences
- Respect `AGENTS.md` constraints.
- Keep diffs tight, focused, and tested.
"""

AGENTS_SUBDIR_TEMPLATE = """# Antigravity CLI Instructions

Read the repository-root `AGENTS.md` for shared project rules and multi-agent protocols.

## Antigravity's Role
You are an **Autonomous Implementer and Reporter**.

### Execution Rules:
1. Work only within your assigned worktree and task scope.
2. Do not modify files outside your assigned list.
3. Add and run targeted tests for your changes.
4. When finished, produce a valid `TASK_REPORT.json` at the root of your working directory summarizing:
   - status (completed/failed)
   - summary of changes
   - files_modified and files_created
   - tests_run and test result
5. Commit your changes cleanly before reporting done.
"""

ARCHITECTURE_MD_TEMPLATE = """# Project Architecture & Component Boundaries

## System Overview
High-level description of this repository, its core modules, and data flow.

## Key Modules & Ownership
- `src/`: Main application source code.
- `tests/`: Automated unit and integration test suites.
- `docs/`: Architecture decisions, task plans, and reference docs.

## Multi-Agent Boundaries
- Shared interfaces must be documented before parallel implementation.
- Modules should remain loosely coupled to allow concurrent agent development.
"""
