"""OpenX Workflow - workflow orchestration with human approval and persistence"""

from typing import Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import json

from cogniforge.task_engine.dag import DAGStep, DAGDefinition, ApprovalStatus


@dataclass
class StepResult:
    """Result of a workflow step"""
    step: str  # Store as string for JSON serialization
    status: str  # "success", "failed", "skipped"
    artifacts: list[str] = field(default_factory=list)
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    timestamp: str = ""  # ISO format

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @classmethod
    def from_dag_step(cls, step: DAGStep, **kwargs) -> "StepResult":
        return cls(step=step.value, **kwargs)


@dataclass
class ApprovalRecord:
    """Human approval record for a step"""
    step: str  # Store as string for JSON serialization
    status: str  # ApprovalStatus value
    approver: str = "human"
    comment: str = ""
    timestamp: str = ""  # ISO format

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @classmethod
    def from_dag_step(cls, step: DAGStep, status: ApprovalStatus, **kwargs) -> "ApprovalRecord":
        return cls(step=step.value, status=status.value, **kwargs)

    def to_approval_status(self) -> ApprovalStatus:
        return ApprovalStatus(self.status)


@dataclass
class WorkflowState:
    """Persistent workflow state"""
    version: str = "1.0"
    workflow_id: str = ""
    started: bool = False
    current_step: Optional[str] = None
    awaiting_approval: bool = False
    step_results: dict[str, dict] = field(default_factory=dict)
    approval_records: dict[str, dict] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "version": self.version,
            "workflow_id": self.workflow_id,
            "started": self.started,
            "current_step": self.current_step,
            "awaiting_approval": self.awaiting_approval,
            "step_results": self.step_results,
            "approval_records": self.approval_records,
            "history": self.history,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowState":
        """Create from dictionary"""
        if not data:
            return cls()
        return cls(**data)


class Workflow:
    """
    OpenX Workflow orchestrator with human approval gates and persistence.

    Responsibilities:
    - Manage DAG workflow
    - Track step status
    - Handle human approval (NOT auto-continue)
    - Persist state to disk for recovery after interruption
    - Full audit trail of all operations
    """

    STATE_FILE = Path(".cogniforge") / "workflow_state.json"

    def __init__(self, dag: Optional[DAGDefinition] = None, repo_path: Optional[Path] = None):
        self.dag = dag or DAGDefinition()
        self.repo_path = repo_path or Path.cwd()
        self.state_file = self.repo_path / self.STATE_FILE

        # Initialize state
        self._state = WorkflowState(
            workflow_id=self._generate_workflow_id()
        )

        # Try to load existing state
        self._load_state()

    def _generate_workflow_id(self) -> str:
        """Generate unique workflow ID"""
        return f"wf-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def _load_state(self) -> bool:
        """Load state from disk"""
        if not self.state_file.exists():
            return False

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._state = WorkflowState.from_dict(data)

            # Restore step enums from strings
            if self._state.current_step:
                self._state.current_step = DAGStep.from_string(self._state.current_step).value if DAGStep.from_string(self._state.current_step) else None

            return True
        except Exception as e:
            # If load fails, start fresh
            return False

    def _save_state(self) -> None:
        """Save state to disk"""
        self._state.updated_at = datetime.now().isoformat()

        # Ensure directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self._state.to_dict(), f, indent=2, ensure_ascii=False)

    def _record_history(self, action: str, details: dict = None) -> None:
        """Record action in history for audit"""
        entry = {
            "action": action,
            "timestamp": datetime.now().isoformat(),
            "current_step": self._state.current_step,
            "details": details or {}
        }
        self._state.history.append(entry)

    @property
    def current_step(self) -> Optional[DAGStep]:
        """Get current step"""
        if not self._state.current_step:
            return None
        return DAGStep.from_string(self._state.current_step)

    @property
    def is_started(self) -> bool:
        """Check if workflow has started"""
        return self._state.started

    @property
    def is_awaiting_approval(self) -> bool:
        """Check if workflow is waiting for human approval"""
        return self._state.awaiting_approval

    @property
    def workflow_id(self) -> str:
        """Get workflow ID"""
        return self._state.workflow_id

    def start(self, resume: bool = True) -> DAGStep:
        """
        Start the workflow from the beginning.

        Args:
            resume: If True and existing state found, resume from saved state
        """
        if resume and self._load_state() and self._state.started:
            # Resume from existing state
            self._record_history("resume", {"step": self._state.current_step})
            self._save_state()
            return self.current_step

        # Start fresh
        self._state = WorkflowState(workflow_id=self._generate_workflow_id())
        self._state.started = True
        self._state.current_step = DAGStep.PRD.value
        self._state.awaiting_approval = False

        self._record_history("start", {"step": DAGStep.PRD.value})
        self._save_state()

        return DAGStep.PRD

    def get_next_step(self) -> Optional[DAGStep]:
        """Get next step in workflow"""
        if not self._state.current_step:
            return DAGStep.PRD

        next_steps = self.dag.get_next_steps(self._state.current_step)

        if not next_steps:
            return None

        return DAGStep.from_string(next_steps[0])

    def approve(
        self,
        step: Optional[DAGStep] = None,
        comment: str = "",
        approver: str = "human"
    ) -> bool:
        """
        Approve a step to proceed.

        Args:
            step: Step to approve (defaults to current step)
            comment: Approval comment
            approver: Approver identifier

        Returns:
            True if approved successfully
        """
        target_step = step or self.current_step

        if target_step is None:
            return False

        target_step_value = target_step.value

        # Record approval
        self._state.approval_records[target_step_value] = {
            "step": target_step_value,
            "status": ApprovalStatus.APPROVED.value,
            "approver": approver,
            "comment": comment,
            "timestamp": datetime.now().isoformat()
        }

        self._state.awaiting_approval = False

        self._record_history("approve", {
            "step": target_step_value,
            "approver": approver,
            "comment": comment
        })
        self._save_state()

        return True

    def reject(
        self,
        step: Optional[DAGStep] = None,
        comment: str = "",
        approver: str = "human"
    ) -> bool:
        """
        Reject a step, requiring rework.

        Args:
            step: Step to reject (defaults to current step)
            comment: Rejection reason
            approver: Rejector identifier

        Returns:
            True if rejected successfully
        """
        target_step = step or self.current_step

        if target_step is None:
            return False

        target_step_value = target_step.value

        self._state.approval_records[target_step_value] = {
            "step": target_step_value,
            "status": ApprovalStatus.REJECTED.value,
            "approver": approver,
            "comment": comment,
            "timestamp": datetime.now().isoformat()
        }

        self._state.awaiting_approval = False

        self._record_history("reject", {
            "step": target_step_value,
            "approver": approver,
            "comment": comment
        })
        self._save_state()

        return True

    def advance(self, result: Optional[dict] = None) -> Optional[DAGStep]:
        """
        Advance workflow to next step after approval.

        This only advances if current step is approved.
        """
        if not self.can_advance():
            return None

        current = self.current_step
        if not current:
            return None

        # Record step result
        if result:
            self._state.step_results[current.value] = {
                "step": current.value,
                "status": result.get("status", "success"),
                "artifacts": result.get("artifacts", []),
                "error": result.get("error"),
                "timestamp": datetime.now().isoformat()
            }

        # Determine next step
        if result and result.get("status") == "failed":
            if current == DAGStep.TEST:
                next_step = DAGStep.FIX
            elif current == DAGStep.FIX:
                next_step = DAGStep.CR
            else:
                next_step = self.get_next_step()
        else:
            next_step = self.get_next_step()

        # Move to next step
        if next_step:
            self._state.current_step = next_step.value
            self._state.awaiting_approval = True
        else:
            # Workflow complete
            self._state.current_step = None
            self._state.awaiting_approval = False

        self._record_history("advance", {
            "from": current.value,
            "to": next_step.value if next_step else None
        })
        self._save_state()

        return next_step

    def go_to_step(self, step: DAGStep, require_approval: bool = True) -> None:
        """
        Jump to a specific step (for recovery or manual control).

        Args:
            step: Target step
            require_approval: Whether approval is required to proceed further
        """
        old_step = self._state.current_step
        self._state.current_step = step.value
        self._state.awaiting_approval = require_approval

        self._record_history("goto", {
            "from": old_step,
            "to": step.value,
            "require_approval": require_approval
        })
        self._save_state()

    def get_state(self) -> dict:
        """Get current workflow state"""
        # Get current approval status
        current_approval = None
        if self._state.current_step and self._state.current_step in self._state.approval_records:
            approval = self._state.approval_records[self._state.current_step]
            current_approval = approval.copy()
            current_approval["status"] = approval["status"]

        return {
            "workflow_id": self._state.workflow_id,
            "started": self._state.started,
            "current_step": self._state.current_step,
            "awaiting_approval": self._state.awaiting_approval,
            "current_approval": current_approval,
            "completed_steps": list(self._state.step_results.keys()),
            "approval_records": self._state.approval_records,
            "step_results": self._state.step_results,
            "history": self._state.history,
            "created_at": self._state.created_at,
            "updated_at": self._state.updated_at,
        }

    def get_approval_prompt(self) -> str:
        """Get human approval prompt for current step"""
        if not self._state.started:
            return "请启动工作流 (workflow start)"

        if not self._state.current_step:
            return "工作流已完成"

        current_step = DAGStep.from_string(self._state.current_step)
        if not current_step:
            return "未知步骤"

        # Check approval status
        approval = self._state.approval_records.get(self._state.current_step)

        if not approval:
            return (
                f"步骤 [{current_step.value}] 需要审批\n"
                f"{current_step.get_approval_prompt()}\n\n"
                f"使用 'cogniforge approve --comment \"同意\"' 审批\n"
                f"或 'cogniforge reject --comment \"原因\"' 拒绝"
            )

        status = ApprovalStatus(approval["status"])

        if status == ApprovalStatus.APPROVED:
            next_step = self.get_next_step()
            if next_step:
                return (
                    f"✓ 步骤 [{current_step.value}] 已审批通过\n"
                    f"审批人: {approval['approver']}\n"
                    f"使用 'cogniforge advance' 进入下一步: {next_step.value}"
                )
            return f"✓ 步骤 [{current_step.value}] 已完成，工作流结束"

        if status == ApprovalStatus.REJECTED:
            return (
                f"✗ 步骤 [{current_step.value}] 被拒绝\n"
                f"拒绝原因: {approval['comment']}\n"
                f"需要修复后重新审批"
            )

        return "未知审批状态"

    def get_pending_approvals(self) -> list[str]:
        """Get list of steps pending approval"""
        pending = []

        for step in DAGStep:
            step_value = step.value

            # Already has approval record
            if step_value in self._state.approval_records:
                continue

            # Check if prerequisites are met
            prev_steps = self.dag.get_prev_steps(step_value)
            all_prev_approved = True

            for ps in prev_steps:
                ps_status = self._state.approval_records.get(ps, {}).get("status")
                if ps_status != ApprovalStatus.APPROVED.value:
                    all_prev_approved = False
                    break

            if all_prev_approved:
                pending.append(step_value)

        return pending

    def is_complete(self) -> bool:
        """Check if workflow is complete"""
        return (
            self._state.started and
            self._state.current_step is None and
            DAGStep.RETRO.value in self._state.step_results
        )

    def can_advance(self) -> bool:
        """Check if workflow can advance (current step has approval)"""
        if not self._state.current_step:
            return False

        approval = self._state.approval_records.get(self._state.current_step)
        if not approval:
            return False

        return approval["status"] == ApprovalStatus.APPROVED.value

    def reset(self) -> None:
        """Reset workflow to initial state"""
        self._state = WorkflowState(workflow_id=self._generate_workflow_id())
        self._save_state()

    def get_history(self) -> list[dict]:
        """Get full operation history"""
        return self._state.history

    def get_step_approval(self, step: DAGStep) -> Optional[dict]:
        """Get approval record for a specific step"""
        return self._state.approval_records.get(step.value)
