"""Unit tests for WorkflowService."""

import pytest
from unittest.mock import MagicMock
from cogniforge.services.workflow_service import WorkflowService, WorkflowError


@pytest.fixture
def mock_workflow():
    wf = MagicMock()
    wf.workflow_id = "wf-test-001"
    wf.is_awaiting_approval = False
    wf.current_step = MagicMock()
    wf.current_step.value = "prd"
    wf.is_started = False
    wf.can_advance.return_value = False
    wf.get_state.return_value = {
        "workflow_id": "wf-test-001",
        "started": False,
        "current_step": None,
        "awaiting_approval": False,
        "history": [],
    }
    return wf


class TestWorkflowService:
    def test_status(self, mock_workflow):
        svc = WorkflowService(mock_workflow)
        result = svc.status()
        assert result["workflow_id"] == "wf-test-001"
        assert result["started"] is False

    def test_start(self, mock_workflow):
        mock_workflow.start.return_value = MagicMock()
        mock_workflow.start.return_value.value = "prd"
        mock_workflow.workflow_id = "wf-new"
        mock_workflow.is_awaiting_approval = False

        svc = WorkflowService(mock_workflow)
        result = svc.start()

        assert result["workflow_id"] == "wf-new"
        assert result["current_step"] == "prd"
        assert result["started"] is True

    def test_approve_succeeds(self, mock_workflow):
        mock_workflow.approve.return_value = True

        svc = WorkflowService(mock_workflow)
        result = svc.approve(step="prd", comment="LGTM")

        assert result["status"] == "approved"
        assert result["step"] == "prd"

    def test_approve_fails(self, mock_workflow):
        mock_workflow.approve.return_value = False

        svc = WorkflowService(mock_workflow)
        with pytest.raises(WorkflowError):
            svc.approve()

    def test_advance_not_approved(self, mock_workflow):
        mock_workflow.can_advance.return_value = False

        svc = WorkflowService(mock_workflow)
        with pytest.raises(WorkflowError, match="not been approved"):
            svc.advance()

    def test_history(self, mock_workflow):
        mock_workflow.get_history.return_value = [
            {"action": "start", "timestamp": "..."},
        ]
        svc = WorkflowService(mock_workflow)
        result = svc.history()
        assert len(result) == 1
        assert result[0]["action"] == "start"
