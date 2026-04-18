"""Execution engine - step-based execution with human approval"""

from typing import Optional
import logging

from cogniforge.core.config import Config
from cogniforge.core.constants import TaskStatus, AgentRole
from cogniforge.core.exceptions import GateCheckFailedError
from cogniforge.agents.base import BaseAgent
from cogniforge.agents.dev_agent import DevAgent
from cogniforge.agents.review_agent import ReviewAgent
from cogniforge.agents.qa_agent import QAAgent
from cogniforge.task_engine.task_engine import TaskEngine
from cogniforge.task_engine.dag import DAGStep, dag, ApprovalStatus
from cogniforge.execution.worker_pool import WorkerPool


class ExecutionEngine:
    """
    Execution engine with step-based human approval.

    IMPORTANT: This engine NEVER auto-continues. Each step requires
    human approval before proceeding.

    Execution flow:
    1. Pause at step, wait for human
    2. Human executes agent commands
    3. Human approves step
    4. Human calls advance
    5. Goto step 1
    """

    def __init__(
        self,
        config: Config,
        task_engine: TaskEngine,
        agents: dict[str, BaseAgent],
        worker_pool: Optional[WorkerPool] = None
    ):
        self.config = config
        self.task_engine = task_engine
        self.agents = agents
        self.worker_pool = worker_pool or WorkerPool(config=config)
        self.logger = logging.getLogger(__name__)

        self._current_step: Optional[DAGStep] = None
        self._step_results: dict[str, dict] = {}

    def run_step(self) -> dict:
        """
        Execute current step (but do NOT auto-continue).

        Returns step execution info for human to review.
        """
        if self._current_step is None:
            self._current_step = DAGStep.PRD

        # Get ready tasks for this step
        ready_tasks = self.task_engine.get_ready_tasks()

        step_info = {
            "step": self._current_step.value,
            "ready_tasks": [t.task_id for t in ready_tasks],
            "task_count": len(ready_tasks),
            "requires_approval": self._current_step.requires_approval(),
            "approval_prompt": self._current_step.get_approval_prompt(),
        }

        # Check if there are previous results
        if self._current_step.value in self._step_results:
            step_info["previous_result"] = self._step_results[self._current_step.value]

        return step_info

    def execute_tasks_for_step(self) -> dict:
        """
        Execute all ready tasks for current step.

        Returns execution results, but does NOT auto-advance.
        Human must approve and advance manually.
        """
        if self._current_step is None:
            return {"error": "No current step"}

        ready_tasks = self.task_engine.get_ready_tasks()

        if not ready_tasks:
            return {
                "step": self._current_step.value,
                "executed": False,
                "reason": "No ready tasks"
            }

        # Execute tasks (could be parallel for coding steps)
        results = []

        for task in ready_tasks:
            agent = self._select_agent(task)

            if not agent:
                continue

            try:
                result = agent.run({"task": task, "module": task.module})
                results.append({
                    "task_id": task.task_id,
                    "agent": agent.role.value,
                    "result": result
                })

                # Update task status
                if result.get("status") == "success":
                    self.task_engine.update_task_status(
                        task.task_id,
                        TaskStatus.DONE,
                        result=result,
                        commit_message=f"feat: complete {task.task_id}"
                    )
                else:
                    self.task_engine.update_task_status(
                        task.task_id,
                        TaskStatus.FAILED,
                        error=result.get("message", "Unknown error"),
                        commit_message=f"fix: {task.task_id} failed"
                    )

            except Exception as e:
                self.logger.error(f"Task {task.task_id} failed: {e}")
                self.task_engine.update_task_status(
                    task.task_id,
                    TaskStatus.FAILED,
                    error=str(e)
                )

        # Store step results
        self._step_results[self._current_step.value] = {
            "executed": True,
            "task_count": len(results),
            "results": results
        }

        return {
            "step": self._current_step.value,
            "executed": True,
            "task_count": len(results),
            "results": results
        }

    def _select_agent(self, task) -> Optional[BaseAgent]:
        """Select appropriate agent for task based on current step"""
        step_agent_map = {
            DAGStep.PRD: AgentRole.PM,
            DAGStep.SAD: AgentRole.ARCHITECT,
            DAGStep.LLD: AgentRole.DESIGN,
            DAGStep.WBS: AgentRole.TECHLEAD,
            DAGStep.CODING: AgentRole.DEV,
            DAGStep.CR: AgentRole.REVIEWER,
            DAGStep.TEST: AgentRole.QA,
            DAGStep.FIX: AgentRole.DEV,
            DAGStep.UAT: AgentRole.QA,
            DAGStep.RETRO: AgentRole.TECHLEAD,
        }

        role = step_agent_map.get(self._current_step)
        if role:
            return self.agents.get(role.value)

        return self.agents.get(AgentRole.DEV.value)

    def check_gate(self) -> dict:
        """
        Check if quality gate is satisfied for current step.

        Returns gate check result, does NOT block or retry.
        """
        if not self._current_step:
            return {"passed": False, "reason": "No current step"}

        gate_reqs = dag.get_gate_requirements(self._current_step.value)

        if not gate_reqs:
            return {"passed": True, "requirements": []}

        # Check each gate requirement
        checks = []
        all_passed = True

        # Get task results
        done_tasks = self.task_engine.list_tasks(status=TaskStatus.DONE)
        failed_tasks = self.task_engine.list_tasks(status=TaskStatus.FAILED)

        for req in gate_reqs:
            if req == "cr_passed":
                # Check if CR was passed
                passed = len(failed_tasks) == 0
                checks.append({"check": req, "passed": passed})
                all_passed = all_passed and passed
            elif req == "tests_passed":
                # Check if tests passed
                passed = len(failed_tasks) == 0
                checks.append({"check": req, "passed": passed})
                all_passed = all_passed and passed
            elif req == "uat_passed":
                # UAT requires manual verification
                checks.append({"check": req, "passed": False, "note": "Manual verification required"})
                all_passed = False

        return {
            "step": self._current_step.value,
            "passed": all_passed,
            "requirements": gate_reqs,
            "checks": checks
        }

    def get_status(self) -> dict:
        """Get current execution status"""
        return {
            "current_step": self._current_step.value if self._current_step else None,
            "task_stats": self.task_engine.get_statistics(),
            "pending_tasks": self.worker_pool.pending_count,
            "completed_tasks": self.worker_pool.completed_count,
            "step_results": self._step_results,
            "requires_approval": self._current_step.requires_approval() if self._current_step else True,
        }

    def set_step(self, step: DAGStep) -> None:
        """Set current step"""
        self._current_step = step

    def get_step_result(self) -> Optional[dict]:
        """Get result of current step execution"""
        if self._current_step:
            return self._step_results.get(self._current_step.value)
        return None
