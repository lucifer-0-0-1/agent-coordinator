# Agent Coordinator: Dual-Harness Orchestrator

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-brightgreen.svg)](https://www.python.org/)
[![Harness: Claude Code & Antigravity](https://img.shields.io/badge/Harness-Claude%20Code%20%7C%20Antigravity-orange.svg)](https://github.com/)

A lightweight, deterministic multi-agent coordinator that orchestrates **Claude Code** and Google **Antigravity (`agy`)** CLI on Linux.

It enables **parallel multi-agent development and background task offloading with zero token waste**, strictly preventing either harness from disturbing the other's active working tree.

---

## 📖 Table of Contents
1. [Core Architecture & Philosophy](#-core-architecture--philosophy)
2. [Why Zero Token Waste Matters](#-why-zero-token-waste-matters)
3. [All the Ways to Use This Tool](#-all-the-ways-to-use-this-tool)
   - [Mode 1: Conversational Prompts via Claude Code (MCP)](#mode-1-conversational-prompts-via-claude-code-mcp)
   - [Mode 2: Fast Slash Command (`/coord`)](#mode-2-fast-slash-command-coord)
   - [Mode 3: Conversational Prompts via Antigravity (`agy`)](#mode-3-conversational-prompts-via-antigravity-agy)
   - [Mode 4: Standalone Terminal CLI (`coord` / `agent-coordinator`)](#mode-4-standalone-terminal-cli-coord--agent-coordinator)
   - [Mode 5: Direct Python API & Scripting](#mode-5-direct-python-api--scripting)
   - [Mode 6: Headless CI/CD & Automated Hooks](#mode-6-headless-cicd--automated-hooks)
4. [Auto-Scaffolded Project Instructions](#-auto-scaffolded-project-instructions)
5. [CLI Reference & Commands](#-cli-reference--commands)
6. [MCP Server Tool Reference](#-mcp-server-tool-reference)
7. [Further Upgrades & Roadmap](#-further-upgrades--roadmap)

---

## 🏛 Core Architecture & Philosophy

```
                              USER
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
       CLAUDE CODE                         ANTIGRAVITY CLI
 (Watcher / Architect / Implementer)    (Implementer / Reporter)
            │                                     │
            │          MCP / CLI Bridge           │
            └──────────────► ◄────────────────────┘
                             │
                  AGENT-COORDINATOR HARNESS
                             │
     ┌───────────────────────┼───────────────────────┐
     ▼                       ▼                       ▼
AUTO-INIT REPO       WORKTREE ISOLATION       STRUCTURED REPORT
(AGENTS.md, etc.)   (.coordinator/worktrees) (TASK_REPORT.json)
```

1. **Role Specialization**:
   - **Claude Code**: Watcher, Architect, and Interactive Implementer. Claude oversees overall project architecture, coordinates multi-agent goals, inspects reports, reviews diffs, and implements interactive tasks.
   - **Antigravity (`agy`)**: Autonomous Implementer and Reporter. `agy` runs bounded, well-specified implementation tasks in isolated Git worktrees and generates structured completion reports (`TASK_REPORT.json`).
2. **Harness Non-Interference**:
   - Neither harness ever modifies the active working directory of the other.
   - Background tasks run in dedicated Git worktrees (`.coordinator/worktrees/<task-id>`) on isolated branches (`agent/<agent>/<task-id>`). Your working tree, unstaged changes, and Git index remain **100% untouched**.
3. **Automatic Repo Scaffolding**:
   - Whenever invoked in any repository, the coordinator automatically checks for and creates `AGENTS.md`, `CLAUDE.md`, `.agents/AGENTS.md`, and `.gitignore` entries.
4. **Deterministic Orchestration**:
   - Scheduling, branching, worktree lifecycles, and status tracking run via standard Python (`subprocess`), costing **zero LLM tokens**.

---

## ⚡ Why Zero Token Waste Matters

Standard multi-agent frameworks often explode in token costs due to whole-repo re-scans, full conversation transcript copies, and file contention loops. This coordinator enforces zero token waste by design:

| Wasteful Multi-Agent Anti-Pattern | How Agent Coordinator Solves It |
|---|---|
| **Whole-Repo Re-Scanning** | Dispatches enforce strict file scopes (`--files "..."`). Agents are forbidden from reading unassigned files. |
| **Transcript Bleed** | Claude never ingests `agy`'s multi-turn internal chatter. It receives only a compact (~100 token) JSON report. |
| **Working-Tree Collisions** | Worktrees isolate git indexes and files, eliminating mid-turn broken states and conflicting file edits. |
| **Full File Re-Reading** | Claude reviews only the patch (`git diff HEAD~1`) on the task branch, cutting inspection tokens by 80–90%. |
| **LLM Over-Orchestration** | Branching, merging, testing, and worktree lifecycles cost 0 LLM tokens. |

---

## 🚀 All the Ways to Use This Tool

### Mode 1: Conversational Prompts via Claude Code (MCP)
The coordinator is registered as a native MCP server (`coordinator`) connected to Claude Code. You can trigger actions in plain English:

- **Auto-initialize a repository**:
  > *"Initialize this project for multi-agent coordination."*  
  *(Claude calls `coord_init` to auto-create `AGENTS.md`, `CLAUDE.md`, `.agents/AGENTS.md`, and `.gitignore`)*

- **Dispatch an implementation task to `agy`**:
  > *"Have agy implement the CAN frame parser in `src/can/parser.c` with tests in `tests/test_parser.py`."*  
  *(Claude calls `coord_dispatch`; `agy` executes in an isolated worktree while you continue interactive coding with Claude)*

- **Check status & active tasks**:
  > *"What's the status of running coordinator tasks?"*  
  *(Claude calls `coord_status` to view active worktrees and recent reports)*

- **Review, Guide, and Merge**:
  > *"Inspect agy's report, verify tests, and merge the branch."*  
  *(Claude reviews the diff and calls `coord_merge`)*
  > *"The CAN parser fails edge cases for 29-bit frames; guide agy to fix the bitmask in `src/can/parser.c`."*  
  *(Claude calls `coord_guide` to pass targeted review comments; agy fixes the issue in the existing workspace without Claude having to rewrite the code)*

- **GPU Resource Gating**:
  > *"Dispatch the VGGT evaluation task to agy with GPU gating."*  
  *(Claude calls `coord_dispatch` with `wait_gpu=True`; the coordinator queries nvidia-smi and waits until VRAM is free before launching)*

---

### Mode 2: Fast Slash Command (`/coord`)
When working inside Claude Code, use the installed slash command for concise execution:

```text
/coord "Implement telemetry logging in src/telemetry/logger.py and pass pytest"
```

Or for dividing tasks:
```text
/coord divide: implement backend SQLite storage with agy while we build the UI here
```

---

### Mode 3: Conversational Prompts via Antigravity (`agy`)
The coordinator is also registered as an MCP server and Skill in Antigravity:

- Ask `agy` to use the skill:
  > *"Use the agent-coordinator skill to divide this feature and dispatch worker tasks."*
- `agy` calls `coord_dispatch` or `coord_plan` to delegate secondary modules into isolated worktrees, ensuring your main directory remains clean.

---

### Mode 4: Standalone Terminal CLI (`coord` / `agent-coordinator`)
Both `coord` and `agent-coordinator` are available in your system `$PATH`:

```bash
# 1. Initialize instruction files (supports Git and non-Git folders)
coord init /path/to/project [--non-git]

# 2. Dispatch a task to agy without timeout (0 = unlimited, default no timeout)
coord dispatch "Implement CAN frame parser" \
    --files "src/can/parser.c,tests/test_parser.py" \
    --criteria "pytest tests/test_parser.py must pass" \
    --timeout 0

# 3. Dispatch for GPU tasks (waits until GPU is free before starting)
coord dispatch "Run VGGT evaluation" --wait-gpu --gpu-min-free 2000 --timeout 0

# 4. In-place / non-worktree mode (for remote-host tasks or directory scripts)
coord dispatch "Run evaluation on remote host" --no-worktree --timeout 0

# 5. Guide agy with Watcher feedback (Watcher -> Implementer iteration loop)
coord guide agy-12345 "The bitmask fails for 29-bit frames; fix in src/can/parser.c"

# 6. Dispatch with auto-merge if tests pass
coord dispatch "Add healthcheck endpoint" --auto-merge

# 7. Check active coordinator worktrees, non-git workspaces, and GPU status
coord status

# 8. Clean up finished worktrees
coord clean
```

---

### Mode 5: Direct Python API & Scripting
You can import the coordinator inside custom Python scripts:

```python
from coordinator.orchestrator import CoordinatorOrchestrator
from coordinator.schema import AgentType

orchestrator = CoordinatorOrchestrator("/home/lucifer/my-project")

# 1. Auto-scaffold repo instruction files
orchestrator.ensure_repo_instructions()

# 2. Dispatch task to agy in an isolated worktree
report = orchestrator.dispatch_agy(
    title="CAN Parser Implementation",
    description="Implement CAN message decoder and unit tests",
    files=["src/can/parser.c", "tests/test_parser.py"],
    criteria=["pytest tests/test_parser.py"],
    auto_merge=True
)

print(f"Status: {report.status}")
print(f"Summary: {report.summary}")
print(f"Commit: {report.git_commit}")
```

---

### Mode 6: Headless CI/CD & Automated Hooks
Incorporate the coordinator into CI pipelines or pre-commit hooks to automate autonomous background fixes or reviews:

```bash
# In CI pipeline / Git pre-commit hook:
coord run "Run linters, fix formatting errors, and update docs" \
    --agent agy \
    --auto-merge
```

---

## 📄 Auto-Scaffolded Project Instructions

When running `coord init` or any coordinator dispatch, the following files are automatically verified or created:

1. **`AGENTS.md` (Project Root)**: Canonical rules for all agents:
   - Claude = Watcher, Architect, Interactive Implementer.
   - Antigravity = Autonomous Implementer, Reporter.
   - Token efficiency guidelines (scoped files, diff-based reviews).
   - Mandatory `TASK_REPORT.json` schema.
2. **`CLAUDE.md` (Project Root)**: Tailored instructions for Claude Code:
   - Directives on delegating tasks to `agy` via `coord dispatch`.
   - Worktree isolation awareness.
3. **`.agents/AGENTS.md`**: Specialized instructions for Antigravity:
   - Strictly references root `AGENTS.md`.
   - Directs `agy` to work only within its assigned scope and write `TASK_REPORT.json`.
4. **`.gitignore`**:
   - Automatically appends `.coordinator/`, `.worktrees/`, `TASK_REPORT.json`, and `*.agent-log`.

---

## 🛠 CLI Reference & Commands

| Command | Arguments / Flags | Description |
|---|---|---|
| `coord init [path]` | `--force`, `--arch`, `--non-git` | Auto-scaffold or verify `AGENTS.md`, `CLAUDE.md`, `.agents/AGENTS.md`, and `.gitignore` in Git or non-Git projects. |
| `coord dispatch "<task>"` | `--agent agy\|claude`<br>`--files "f1,f2"`<br>`--criteria "c1,c2"`<br>`--branch "<name>"`<br>`--no-worktree`<br>`--auto-merge`<br>`--timeout <sec>`<br>`--wait-gpu`<br>`--gpu-min-free <mb>` | Fast background dispatch to an isolated workspace or worktree; supports unlimited runtime (0 = no timeout) and GPU resource waiting. |
| `coord guide <task_id> "<feedback>"` | `--timeout <sec>` | Pass Watcher review comments to guide agy on an existing task, updating code and report. |
| `coord run "<prompt>"` | `--mode single\|multi`<br>`--agent agy\|claude`<br>`--no-worktree`<br>`--auto-merge`<br>`--timeout <sec>`<br>`--wait-gpu` | Run a single-agent or multi-agent task. |
| `coord status` | `--path [dir]` | Display active worktrees/workspaces, GPU health & VRAM, repo initialization, and recent reports. |
| `coord clean` | `--path [dir]` | Remove completed coordinator worktrees/workspaces and prune metadata. |

---

## 🔌 MCP Server Tool Reference

When using Claude Code or Antigravity, the `coordinator` MCP server exposes:

- **`coord_init(project_path, force, create_arch, non_git)`**: Scaffolds instruction files.
- **`coord_dispatch(task, files, criteria, branch_name, use_worktree, auto_merge, timeout, wait_gpu, gpu_min_free, project_path)`**: Runs task in isolated worktree or in-place without timeout.
- **`coord_guide(task_id, feedback, timeout, project_path)`**: Watcher passes review comments to guide agy on an existing task.
- **`coord_gpu_status()`**: Checks GPU name, free VRAM, utilization, and running compute processes (0 LLM tokens).
- **`coord_status(project_path)`**: Lists active workspaces, GPU status, and reports.
- **`coord_plan(goal, tasks, project_path)`**: Saves multi-agent task breakdown.
- **`coord_merge(branch_name, into_branch, task_id, project_path)`**: Integrates branch and cleans up worktree.
- **`coord_clean(project_path)`**: Cleans up all coordinator worktrees.

---

## 🔮 Further Upgrades & Roadmap

Here are high-impact enhancements planned for subsequent iterations:

### 1. Interactive Review TUI & Web Dashboard
- **Feature**: A lightweight terminal UI (`textual` / `rich`) or local web dashboard (`localhost:8989`).
- **Benefit**: Visual task dependency graph, real-time live log tailing for `agy`, interactive diff side-by-side comparison, and one-click "Approve & Merge" buttons.

### 2. Automated Cross-Agent Review & Feedback Loop
- **Feature**: Ping-pong review workflow:
  1. `agy` finishes implementing in its worktree.
  2. Claude automatically audits the generated diff against security, architecture, and linting rules.
  3. If Claude finds issues, it automatically feeds feedback into the worktree for `agy` to patch before proposing merge.

### 3. Adaptive Model Routing & Token Budgeting
- **Feature**: Intelligent model assignment based on task complexity:
  - Simple boilerplate/tests: `gemini-3.8-flash-high`.
  - Complex architectural refactors: `gemini-pro` or `claude-opus`.
  - Configurable hard token budget caps per task.

### 4. Monorepo & Multi-Subdirectory Pinning
- **Feature**: Specialized worktree support for monorepos (e.g. `REAM-Project/`, `MonitorApp/`, `Jira-clone/`):
  - Support sparse checkouts and subfolder-level worktree isolation so agents only check out the specific project subfolder.

### 5. Desktop Notifications & WebSocket Live Events
- **Feature**: System tray notifications (via `notify-send` / Linux desktop notifications) and WebSocket event emitter.
- **Benefit**: Notifies you immediately when a background `agy` run completes or requires review.

### 6. Automated Rollback & Stash Resilience
- **Feature**: Safety gates that take a pre-merge stash snapshot, run integration regression tests in a detached container or sandbox, and auto-rollback if regressions occur.
