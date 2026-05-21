"""Task model - DAG nodes"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from cogniforge.core.constants import TaskStatus, TaskPriority


class Task(BaseModel):
    """Task model - represents a unit of work in the DAG."""

    task_id: str = Field(description="Unique task identifier, format: {module}-{seq}")
    name: str
    description: str = ""
    module: str = Field(description="Module this task belongs to")
    deps: list[str] = Field(default_factory=list, description="List of dependent task IDs")
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = Field(default=TaskPriority.P2)
    assignee: Optional[str] = None
    estimated_hours: Optional[float] = Field(default=None, description="Estimated effort in hours")
    actual_hours: Optional[float] = Field(default=None, description="Actual effort in hours")
    category: Optional[str] = Field(default=None, description="Task category")
    changed_files: list[str] = Field(default_factory=list, description="Files modified by this task")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    result: Optional[dict] = None
    error: Optional[str] = None

    def mark_in_progress(self) -> None:
        self.status = TaskStatus.IN_PROGRESS
        self.updated_at = datetime.now()

    def mark_done(self, result: Optional[dict] = None, changed_files: list[str] | None = None) -> None:
        self.status = TaskStatus.DONE
        self.updated_at = datetime.now()
        if result:
            self.result = result
        if changed_files:
            self.changed_files = changed_files

    def mark_failed(self, error: str) -> None:
        self.status = TaskStatus.FAILED
        self.updated_at = datetime.now()
        self.error = error

    def mark_blocked(self) -> None:
        self.status = TaskStatus.BLOCKED
        self.updated_at = datetime.now()

    def to_json(self) -> dict:
        """Serialize task as JSON-serializable dict."""
        data = self.model_dump(mode="json")
        data["status"] = self.status.value
        data["priority"] = self.priority.value
        if isinstance(data.get("assignee"), str) and data["assignee"] == "None":
            data["assignee"] = None
        return data

    @classmethod
    def from_json_dict(cls, data: dict) -> "Task":
        """Parse task from a JSON dict."""
        # Ensure status and priority are enum values
        if isinstance(data.get("status"), str):
            data["status"] = TaskStatus(data["status"])
        if isinstance(data.get("priority"), int):
            data["priority"] = TaskPriority(data["priority"])
        return cls.model_validate(data)
