"""Task model - DAG nodes"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from cogniforge.core.constants import TaskStatus, TaskPriority


# ── MDE→DEV traceability models ──

class LLDReference(BaseModel):
    """Points to a specific artifact in an LLD document."""
    module: str = ""
    doc_id: str = ""
    section: str = ""           # e.g. "service_contracts", "interfaces"
    item_name: str = ""         # e.g. "KeyStorageService", "POST /api/v1/keys"
    artifact_type: str = ""     # "service_method" | "endpoint" | "data_model" | "domain_object" | "business_rule" | "state_machine"
    sub_item: Optional[str] = None  # e.g. method name when item_name is a service class


class AcceptanceCriterion(BaseModel):
    """Verifiable acceptance criterion derived from LLD contracts."""
    source_section: str = ""
    source_item: str = ""
    description: str = ""
    verification_type: str = ""  # "http_status" | "precondition" | "postcondition" | "invariant" | "state_transition" | "field_definition"
    expected: str = ""


class TaskScope(BaseModel):
    """The subset of LLD data this task is responsible for implementing."""
    data_models: list[dict] = Field(default_factory=list)
    domain_objects: list[dict] = Field(default_factory=list)
    interfaces: list[dict] = Field(default_factory=list)
    service_contracts: list[dict] = Field(default_factory=list)
    business_rules: dict = Field(default_factory=dict)
    error_handling: dict = Field(default_factory=dict)
    extra_sections: dict = Field(default_factory=dict)


class TaskContext(BaseModel):
    """Structured context that DEV Agent consumes directly — no need to re-read LLD."""
    module_type: str = ""
    lld_path: str = ""
    module_overview: str = ""
    scope: TaskScope = Field(default_factory=TaskScope)
    external_contracts: list[dict] = Field(default_factory=list)
    cross_module_deps: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    upstream_artifacts: list[dict] = Field(default_factory=list,
        description="Artifacts from completed upstream tasks: [{task_id, name, files, category}]")


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

    # ── MDE→DEV traceability (new, all optional for backward compat) ──
    lld_refs: list[LLDReference] = Field(default_factory=list,
        description="LLD artifacts this task implements")
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list,
        description="Verifiable criteria from LLD contracts")
    context: Optional[TaskContext] = Field(default=None,
        description="Structured context for DEV Agent consumption")
    expected_output_files: list[str] = Field(default_factory=list,
        description="Expected output file paths declared at WBS time")
    layer: int = Field(default=0,
        description="Decomposition layer: 0=model, 1=service, 2=endpoint, 3=test")

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
