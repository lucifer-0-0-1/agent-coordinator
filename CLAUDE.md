# Claude Code Instructions

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
