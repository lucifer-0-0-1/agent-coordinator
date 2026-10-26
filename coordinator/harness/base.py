"""Abstract base class for execution harnesses."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional

from coordinator.schema import Task, TaskReport, TaskStatus


class BaseHarness(ABC):
    """Base interface for agent CLI harnesses."""

    @abstractmethod
    def run_task(self, task: Task, worktree_path: Path) -> TaskReport:
        """Execute a task in the specified worktree and return a completion report."""
        pass
