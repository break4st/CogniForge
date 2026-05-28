"""Workflow service — thin wrapper around Workflow state machine."""

from __future__ import annotations

from cogniforge.orchestration.workflow import Workflow
from cogniforge.task_engine.dag import DAGStep


class WorkflowError(Exception):
    """Raised when a workflow operation fails validation."""


class WorkflowService:
    """JSON-safe wrapper around Workflow state machine."""

    def __init__(self, workflow: Workflow):
        self._wf = workflow

    def start(self, project_path: str = "", resume: bool = True) -> dict:
        """Start or resume the workflow."""
        current = self._wf.start(resume=resume)
        return {
            "workflow_id": self._wf.workflow_id,
            "current_step": current.value if current else None,
            "started": True,
            "awaiting_approval": self._wf.is_awaiting_approval,
        }

    def status(self) -> dict:
        """Return current workflow state as JSON-safe dict."""
        return self._wf.get_state()

    def approve(
        self,
        step: str | None = None,
        comment: str = "",
        approver: str = "human",
    ) -> dict:
        """Approve a step."""
        step_enum = DAGStep.from_string(step) if step else None
        ok = self._wf.approve(step=step_enum, comment=comment, approver=approver)
        if not ok:
            raise WorkflowError("No current step or invalid workflow state")
        current = self._wf.current_step
        return {
            "status": "approved",
            "step": step or (current.value if current else None),
        }

    def reject(
        self,
        step: str | None = None,
        comment: str = "",
        approver: str = "human",
    ) -> dict:
        """Reject a step, requiring rework."""
        step_enum = DAGStep.from_string(step) if step else None
        ok = self._wf.reject(step=step_enum, comment=comment, approver=approver)
        if not ok:
            raise WorkflowError("No current step or invalid workflow state")
        current = self._wf.current_step
        return {
            "status": "rejected",
            "step": step or (current.value if current else None),
        }

    def advance(self, result: dict | None = None) -> dict:
        """Advance to next step (current step must be approved)."""
        if not self._wf.can_advance():
            raise WorkflowError("Current step has not been approved yet")
        next_step = self._wf.advance(result=result)
        return {
            "new_step": next_step.value if next_step else None,
            "workflow_complete": next_step is None and self._wf.is_complete(),
        }

    def history(self) -> list[dict]:
        """Return full operation history."""
        return self._wf.get_history()
