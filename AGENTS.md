# Project Instructions & Agent Guidelines

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
