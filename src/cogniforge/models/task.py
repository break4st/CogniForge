"""Task model - DAG nodes"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from cogniforge.core.constants import TaskStatus, TaskPriority


class Task(BaseModel):
    """
    Task model - represents a unit of work in the DAG.

    Tasks are the execution units in the workflow.
    """

    task_id: str = Field(description="Unique task identifier, format: {module}-{seq}")
    name: str
    description: str = ""
    module: str = Field(description="Module this task belongs to")
    deps: list[str] = Field(default_factory=list, description="List of dependent task IDs")
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = Field(default=TaskPriority.P2)
    assignee: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    result: Optional[dict] = None
    error: Optional[str] = None

    def mark_in_progress(self) -> None:
        """Mark task as in progress"""
        self.status = TaskStatus.IN_PROGRESS
        self.updated_at = datetime.now()

    def mark_done(self, result: Optional[dict] = None) -> None:
        """Mark task as done"""
        self.status = TaskStatus.DONE
        self.updated_at = datetime.now()
        if result:
            self.result = result

    def mark_failed(self, error: str) -> None:
        """Mark task as failed"""
        self.status = TaskStatus.FAILED
        self.updated_at = datetime.now()
        self.error = error

    def mark_blocked(self) -> None:
        """Mark task as blocked"""
        self.status = TaskStatus.BLOCKED
        self.updated_at = datetime.now()

    def to_markdown(self) -> str:
        """Render task as markdown"""
        lines = [
            f"# {self.name}",
            "",
            f"**Task ID**: {self.task_id}",
            f"**Module**: {self.module}",
            f"**Status**: {self.status.value}",
            f"**Priority**: P{self.priority.value}",
            f"**Created**: {self.created_at.isoformat()}",
            f"**Updated**: {self.updated_at.isoformat()}",
        ]

        if self.assignee:
            lines.append(f"**Assignee**: {self.assignee}")

        if self.deps:
            lines.append(f"**Dependencies**: {', '.join(self.deps)}")

        lines.extend(["", "---", "", "## Description", "", self.description])

        if self.result:
            lines.extend(["", "## Result", ""])
            for key, value in self.result.items():
                lines.append(f"- **{key}**: {value}")

        if self.error:
            lines.extend(["", "## Error", "", f"```\n{self.error}\n```"])

        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, path: str, markdown_content: str) -> "Task":
        """Parse task from markdown content"""
        lines = markdown_content.split("\n")
        deps = []
        result = None
        error = None
        in_result = False
        result_lines = []
        in_error = False
        error_lines = []
        in_description = False
        description_lines = []

        name = ""
        task_id = ""
        module = ""
        status = TaskStatus.PENDING
        priority = TaskPriority.P2
        assignee = None
        created_at = datetime.now()
        updated_at = datetime.now()

        for line in lines:
            if line.startswith("# ") and not name:
                name = line[2:].strip()
                continue

            if line.startswith("**Task ID**: "):
                task_id = line[12:].strip()
            elif line.startswith("**Module**: "):
                module = line[11:].strip()
            elif line.startswith("**Status**: "):
                status = TaskStatus(line[11:].strip())
            elif line.startswith("**Priority**: "):
                priority = TaskPriority(int(line[12:].strip()[1]))
            elif line.startswith("**Assignee**: "):
                assignee = line[12:].strip()
            elif line.startswith("**Dependencies**: "):
                dep_str = line[17:].strip()
                if dep_str:
                    deps = [d.strip() for d in dep_str.split(",")]
            elif line.startswith("**Created**: "):
                created_at = datetime.fromisoformat(line[11:].strip())
            elif line.startswith("**Updated**: "):
                updated_at = datetime.fromisoformat(line[12:].strip())
            elif line == "## Result":
                in_result = True
                in_error = False
                in_description = False
            elif line == "## Error":
                in_error = True
                in_result = False
                in_description = False
            elif line == "## Description":
                in_description = True
                in_result = False
                in_error = False
            elif in_result and line.startswith("- **"):
                parts = line[4:].split(":** ", 1)
                if len(parts) == 2:
                    result_lines.append((parts[0], parts[1]))
            elif in_error:
                error_lines.append(line)
            elif in_description:
                description_lines.append(line)

        if result_lines:
            result = dict(result_lines)

        if error_lines:
            error = "\n".join(error_lines).strip()

        description = "\n".join(description_lines).strip()

        return cls(
            task_id=task_id,
            name=name,
            module=module,
            description=description,
            deps=deps,
            status=status,
            priority=priority,
            assignee=assignee,
            created_at=created_at,
            updated_at=updated_at,
            result=result,
            error=error,
        )
