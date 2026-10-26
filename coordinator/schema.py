"""Data structures and schemas for Agent Coordinator."""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Optional, Any
import json
import time


class AgentType(str, Enum):
    CLAUDE = "claude"
    AGY = "agy"
    AUTO = "auto"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REVIEWED = "reviewed"


class ExecutionMode(str, Enum):
    SINGLE = "single"
    MULTI = "multi"


@dataclass
class Task:
    id: str
    title: str
    description: str
    assigned_to: AgentType
    files: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    criteria: List[str] = field(default_factory=list)
    branch: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    worktree_path: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    report: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["assigned_to"] = self.assigned_to.value if isinstance(self.assigned_to, AgentType) else self.assigned_to
        d["status"] = self.status.value if isinstance(self.status, TaskStatus) else self.status
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        data_copy = dict(data)
        if "assigned_to" in data_copy and isinstance(data_copy["assigned_to"], str):
            data_copy["assigned_to"] = AgentType(data_copy["assigned_to"])
        if "status" in data_copy and isinstance(data_copy["status"], str):
            data_copy["status"] = TaskStatus(data_copy["status"])
        return cls(**data_copy)


@dataclass
class TaskReport:
    task_id: str
    agent: AgentType
    status: TaskStatus
    summary: str
    files_modified: List[str] = field(default_factory=list)
    files_created: List[str] = field(default_factory=list)
    tests_run: List[str] = field(default_factory=list)
    tests_passed: bool = True
    git_commit: Optional[str] = None
    diff_stat: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["agent"] = self.agent.value if isinstance(self.agent, AgentType) else self.agent
        d["status"] = self.status.value if isinstance(self.status, TaskStatus) else self.status
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskReport":
        data_copy = dict(data)
        if "agent" in data_copy and isinstance(data_copy["agent"], str):
            data_copy["agent"] = AgentType(data_copy["agent"])
        if "status" in data_copy and isinstance(data_copy["status"], str):
            data_copy["status"] = TaskStatus(data_copy["status"])
        return cls(**data_copy)


@dataclass
class TaskPlan:
    goal: str
    tasks: List[Task] = field(default_factory=list)
    mode: ExecutionMode = ExecutionMode.MULTI
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "mode": self.mode.value if isinstance(self.mode, ExecutionMode) else self.mode,
            "created_at": self.created_at,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskPlan":
        tasks = [Task.from_dict(t) for t in data.get("tasks", [])]
        mode = ExecutionMode(data.get("mode", ExecutionMode.MULTI.value))
        return cls(
            goal=data.get("goal", ""),
            tasks=tasks,
            mode=mode,
            created_at=data.get("created_at", time.time()),
        )
