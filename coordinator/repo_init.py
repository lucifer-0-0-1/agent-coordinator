"""Repository instruction auto-initialization module."""

from pathlib import Path
from typing import Dict, Optional
import subprocess

from coordinator.templates import (
    AGENTS_MD_TEMPLATE,
    CLAUDE_MD_TEMPLATE,
    AGENTS_SUBDIR_TEMPLATE,
    ARCHITECTURE_MD_TEMPLATE,
)


def is_git_repo(path: Path) -> bool:
    """Return True if path is inside a Git repository."""
    git_dir = path / ".git"
    if git_dir.exists():
        return True
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path),
            capture_output=True,
            text=True,
        )
        return res.returncode == 0 and res.stdout.strip() == "true"
    except Exception:
        return False


def ensure_git_repo(repo_path: Path, auto_init: bool = True) -> bool:
    """Ensure repo_path is a git repository if auto_init is True."""
    if is_git_repo(repo_path):
        return True
    if auto_init:
        try:
            res = subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, text=True)
            return res.returncode == 0
        except Exception:
            return False
    return False


def ensure_gitignore(repo_path: Path) -> str:
    """Ensure .gitignore excludes coordinator artifacts and worktrees."""
    gitignore_path = repo_path / ".gitignore"
    required_entries = [
        ".coordinator/",
        ".worktrees/",
        "TASK_REPORT.json",
        "*.agent-log",
    ]

    existing_lines = []
    if gitignore_path.exists():
        try:
            existing_lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            existing_lines = []

    missing_entries = [e for e in required_entries if e not in existing_lines]
    if not missing_entries:
        return "verified"

    try:
        with open(gitignore_path, "a", encoding="utf-8") as f:
            if existing_lines and existing_lines[-1].strip() != "":
                f.write("\n")
            f.write("# Agent Coordinator artifacts\n")
            for entry in missing_entries:
                f.write(f"{entry}\n")
        return "updated" if existing_lines else "created"
    except Exception:
        return "skipped"


def ensure_repo_instructions(
    repo_path: Path,
    force: bool = False,
    create_arch: bool = False,
    auto_git_init: bool = True,
) -> Dict[str, str]:
    """
    Auto-create and verify all necessary repository instruction files.
    Works seamlessly for both Git repositories and non-Git directories.
    Ensures:
      - AGENTS.md (Root shared guidelines)
      - CLAUDE.md (Claude watcher/implementer guidelines)
      - .agents/AGENTS.md (Antigravity implementer/reporter guidelines)
      - .gitignore entries (if git is used or present)
      - Optional docs/ARCHITECTURE.md
    """
    repo_path = repo_path.resolve()
    results: Dict[str, str] = {}

    # Check git repository
    is_git = ensure_git_repo(repo_path, auto_init=auto_git_init)
    results["git"] = "initialized" if is_git else "skipped (non-git)"

    # 1. AGENTS.md (Root)
    agents_root = repo_path / "AGENTS.md"
    if not agents_root.exists() or force:
        agents_root.write_text(AGENTS_MD_TEMPLATE.strip() + "\n", encoding="utf-8")
        results["AGENTS.md"] = "created"
    else:
        results["AGENTS.md"] = "verified"

    # 2. CLAUDE.md (Root)
    claude_md = repo_path / "CLAUDE.md"
    if not claude_md.exists() or force:
        claude_md.write_text(CLAUDE_MD_TEMPLATE.strip() + "\n", encoding="utf-8")
        results["CLAUDE.md"] = "created"
    else:
        results["CLAUDE.md"] = "verified"

    # 3. .agents/AGENTS.md
    agents_dir = repo_path / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agents_sub = agents_dir / "AGENTS.md"
    if not agents_sub.exists() or force:
        agents_sub.write_text(AGENTS_SUBDIR_TEMPLATE.strip() + "\n", encoding="utf-8")
        results[".agents/AGENTS.md"] = "created"
    else:
        results[".agents/AGENTS.md"] = "verified"

    # 4. .gitignore
    results[".gitignore"] = ensure_gitignore(repo_path)

    # 5. Optional docs/ARCHITECTURE.md
    if create_arch:
        docs_dir = repo_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        arch_md = docs_dir / "ARCHITECTURE.md"
        if not arch_md.exists() or force:
            arch_md.write_text(ARCHITECTURE_MD_TEMPLATE.strip() + "\n", encoding="utf-8")
            results["docs/ARCHITECTURE.md"] = "created"
        else:
            results["docs/ARCHITECTURE.md"] = "verified"

    return results


def is_repo_initialized(repo_path: Path) -> bool:
    """Return True if all core instruction files exist."""
    repo = repo_path.resolve()
    return (
        (repo / "AGENTS.md").exists()
        and (repo / "CLAUDE.md").exists()
        and (repo / ".agents" / "AGENTS.md").exists()
    )
