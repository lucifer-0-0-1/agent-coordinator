# Agent Coordinator: Multi-Harness Orchestrator

A lightweight, deterministic orchestrator for **Claude Code** and Google **Antigravity (`agy`)** CLI on Linux.

## Core Philosophy

1. **Role Specialization**:
   - **Claude Code**: Watcher, Architect, and Interactive Implementer. Claude drives overall planning, coordinates tasks, inspects completion reports, and reviews diffs.
   - **Antigravity (`agy`)**: Autonomous Implementer and Reporter. `agy` executes scoped, well-defined implementation tasks in isolated Git worktrees and generates structured completion reports (`TASK_REPORT.json`).
2. **Harness Non-Interference**:
   - Each background task runs in an isolated Git worktree (`.coordinator/worktrees/<task-id>`) on a dedicated branch (`agent/<agent>/<task-id>`).
   - The active working directory, unstaged edits, and Git index of the primary harness are **never touched or disturbed**.
3. **Automatic Repo Scaffolding**:
   - Automatically initializes and verifies project instruction files (`AGENTS.md`, `CLAUDE.md`, `.agents/AGENTS.md`, `.gitignore`) whenever the coordinator runs in any repository.
4. **Token Optimization**:
   - Diff-based reviews rather than whole-repo ingestion.
   - Concise JSON handoffs and test logs rather than endless conversation histories.

---

## Quick Start

### 1. Auto-Scaffold Any Repository
From inside any repository:
```bash
agent-coordinator init
# Or using the alias:
coord init
```
This generates:
- `AGENTS.md`: Canonical project instructions, dual-harness roles, token-efficiency rules, and reporting standards.
- `CLAUDE.md`: Claude Code watcher/implementer instructions.
- `.agents/AGENTS.md`: Antigravity instructions referencing the root `AGENTS.md`.
- `.gitignore`: Ensures `.coordinator/` worktrees and logs are ignored.

### 2. Fast Dispatch to Antigravity (`agy`)
When you (or Claude Code) want to offload an implementation task to `agy` in the background without disturbing the current working tree:
```bash
coord dispatch "Implement CAN frame parser in src/can/parser.c" \
    --files "src/can/parser.c,tests/test_parser.py" \
    --criteria "All tests in pytest tests/test_parser.py must pass"
```
`agy` will:
1. Spin up an isolated Git worktree.
2. Implement the assigned feature in its scope.
3. Run tests and commit on its task branch.
4. Output `TASK_REPORT.json` and `.coordinator/reports/<task_id>_report.md`.
5. Exit cleanly without modifying your unstaged work.

### 3. Check Status & Active Worktrees
```bash
coord status
```

### 4. Cleanup Worktrees
```bash
coord clean
```

---

## CLI Reference

| Command | Description |
|---|---|
| `coord init [path] [--force] [--arch]` | Auto-create or verify repo instruction files |
| `coord dispatch "<task>" [--agent agy\|claude] [--files "..."] [--criteria "..."]` | Run task in isolated worktree and produce structured report |
| `coord run "<prompt>" [--mode single\|multi] [--agent agy\|claude]` | Run single or multi-agent task |
| `coord status` | View active worktrees, repo health, and recent reports |
| `coord clean` | Remove completed coordinator worktrees |
