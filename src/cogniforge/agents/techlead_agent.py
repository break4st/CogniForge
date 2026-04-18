"""Tech Lead Agent - Schedules tasks and governs execution"""

from typing import Optional

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType, TaskStatus, TaskPriority
from cogniforge.models.document import Document
from cogniforge.task_engine.task_engine import TaskEngine
from cogniforge.task_engine.dag import DAGStep, dag


class TechLeadAgent(BaseAgent):
    """
    Tech Lead Agent.

    Responsibilities:
    - Create WBS (Work Breakdown Structure)
    - Schedule tasks
    - Evaluate quality
    - Decide next steps
    - Control flow
    """

    def __init__(self, *args, task_engine: Optional[TaskEngine] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.task_engine = task_engine

    def run(self, input_data: dict) -> dict:
        """
        Execute tech lead responsibilities.

        Args:
            input_data: {
                "action": str,  # "create_wbs", "evaluate_quality", "decide_next", "control_flow"
                ... action-specific fields
            }
        """
        action = input_data.get("action", "create_wbs")

        if action == "create_wbs":
            return self._create_wbs(input_data)
        elif action == "evaluate_quality":
            return self._evaluate_quality(input_data)
        elif action == "decide_next":
            return self._decide_next(input_data)
        elif action == "control_flow":
            return self._control_flow(input_data)
        else:
            return self.format_result(
                status="failed",
                message=f"Unknown action: {action}"
            )

    def _create_wbs(self, input_data: dict) -> dict:
        """Create Work Breakdown Structure from LLD"""
        try:
            module = input_data.get("module", "unknown")
            tasks = input_data.get("tasks", [])

            created_tasks = []
            for task_def in tasks:
                task = self.task_engine.create_task(
                    name=task_def.get("name", "Untitled Task"),
                    module=module,
                    description=task_def.get("description", ""),
                    deps=task_def.get("deps", []),
                    priority=TaskPriority(task_def.get("priority", 2)),
                    assignee=task_def.get("assignee"),
                    commit_message=f"feat: create WBS task - {task_def.get('name', 'untitled')}"
                )
                created_tasks.append(task.task_id)

            return self.format_result(
                status="success",
                message=f"Created {len(created_tasks)} tasks for module {module}",
                artifacts=created_tasks,
                data={"tasks": created_tasks}
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )

    def _evaluate_quality(self, input_data: dict) -> dict:
        """Evaluate quality of deliverables"""
        try:
            step = input_data.get("step", "coding")
            artifacts = input_data.get("artifacts", [])

            # Check gate requirements for the step
            gate_reqs = dag.get_gate_requirements(step)

            # For now, just check if artifacts exist
            quality_checks = []
            for req in gate_reqs:
                quality_checks.append({
                    "check": req,
                    "passed": len(artifacts) > 0
                })

            all_passed = all(c["passed"] for c in quality_checks)

            # Generate quality report
            content = f"# Quality Evaluation Report\n\n"
            content += f"**Step**: {step}\n\n"
            content += "## Checks\n\n"
            for check in quality_checks:
                status = "PASS" if check["passed"] else "FAIL"
                content += f"- [{status}] {check['check']}\n"

            doc_id = f"quality-{step}"
            doc = Document(
                doc_id=doc_id,
                doc_type=DocumentType.REPORT,
                title=f"Quality Report - {step}",
                content=content,
                path=f"wiki/reports/{doc_id}.md",
                author="techlead_agent",
                metadata={"step": step, "passed": all_passed}
            )

            self.write_document(doc, f"docs: quality evaluation for {step}")

            return self.format_result(
                status="success" if all_passed else "failed",
                message=f"Quality evaluation: {'PASSED' if all_passed else 'FAILED'}",
                artifacts=[doc.path],
                data={"checks": quality_checks, "all_passed": all_passed}
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )

    def _decide_next(self, input_data: dict) -> dict:
        """Decide next step based on current state"""
        try:
            current_step = input_data.get("current_step", "coding")
            results = input_data.get("results", {})

            # Determine next step based on DAG
            next_steps = dag.get_next_steps(current_step)

            # Simple logic: if there are multiple next steps, use results to decide
            decision = {
                "current_step": current_step,
                "possible_next": next_steps,
                "decision": next_steps[0] if next_steps else None
            }

            # If test failed, go to fix
            if current_step == "test" and not results.get("passed", True):
                decision["decision"] = "fix"

            return self.format_result(
                status="success",
                message=f"Decision: move to {decision['decision']}",
                data=decision
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )

    def _control_flow(self, input_data: dict) -> dict:
        """Control workflow execution flow"""
        try:
            action = input_data.get("flow_action", "status")

            if action == "status":
                stats = self.task_engine.get_statistics()
                return self.format_result(
                    status="success",
                    message=f"Tasks: {stats['done']}/{stats['total']} completed",
                    data=stats
                )
            elif action == "advance":
                # Advance to next step
                current = input_data.get("current_step", "prd")
                next_steps = dag.get_next_steps(current)

                return self.format_result(
                    status="success",
                    message=f"From {current} can advance to: {next_steps}",
                    data={"current": current, "next_options": next_steps}
                )
            else:
                return self.format_result(
                    status="failed",
                    message=f"Unknown flow action: {action}"
                )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )
