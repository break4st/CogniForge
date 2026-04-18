"""DAG definition - workflow steps and edges with human approval points"""

from enum import Enum
from typing import Optional

from cogniforge.core.constants import GATE_REQUIREMENTS


class DAGStep(str, Enum):
    """
    DAG workflow steps.

    Flow:
    PRD → REQ_REVIEW → SAD → ARCH_REVIEW → LLD → DES_REVIEW
    → WBS → CODING → CR → TEST → FIX → UAT → RETRO

    Each step requires human approval before proceeding.
    """

    PRD = "prd"
    REQ_REVIEW = "req_review"
    SAD = "sad"
    ARCH_REVIEW = "arch_review"
    LLD = "lld"
    DES_REVIEW = "design_review"
    WBS = "wbs"
    CODING = "coding"
    CR = "code_review"
    TEST = "test"
    FIX = "fix"
    UAT = "uat"
    RETRO = "retro"

    @classmethod
    def from_string(cls, value: str) -> Optional["DAGStep"]:
        """Parse step from string"""
        try:
            return cls(value.lower())
        except ValueError:
            return None

    def requires_approval(self) -> bool:
        """All steps require human approval before proceeding"""
        return True

    def get_approval_prompt(self) -> str:
        """Get human approval prompt for this step"""
        prompts = {
            "prd": "审批产品需求文档 (PRD)",
            "req_review": "审批需求评审",
            "sad": "审批系统架构文档 (SAD)",
            "arch_review": "审批架构评审",
            "lld": "审批详细设计文档 (LLD)",
            "design_review": "审批设计评审",
            "wbs": "审批工作分解结构 (WBS)",
            "coding": "审批代码实现",
            "code_review": "审批代码评审 (CR)",
            "test": "审批测试结果",
            "fix": "审批缺陷修复",
            "uat": "审批用户验收测试 (UAT)",
            "retro": "审批复盘总结",
        }
        return prompts.get(self.value, f"审批步骤: {self.value}")


class ApprovalStatus(str, Enum):
    """Human approval status"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class DAGDefinition:
    """
    DAG workflow definition with human approval gates.

    All steps require explicit human approval before proceeding.
    """

    # Directed edges representing workflow
    EDGES = [
        ("prd", "req_review"),
        ("req_review", "sad"),
        ("sad", "arch_review"),
        ("arch_review", "lld"),
        ("lld", "design_review"),
        ("design_review", "wbs"),
        ("wbs", "coding"),
        ("coding", "code_review"),
        ("code_review", "test"),
        ("test", "fix"),        # Failure path
        ("test", "uat"),        # Success path
        ("fix", "code_review"), # After fix, re-review
        ("uat", "retro"),      # UAT passed
    ]

    # Step to DAGStep enum mapping
    STEP_MAP = {step.value: step for step in DAGStep}

    # Gate requirements for quality control
    GATE_REQUIREMENTS = GATE_REQUIREMENTS

    def __init__(self):
        self._adjacency_list: dict[str, list[str]] = {}
        self._reverse_adjacency: dict[str, list[str]] = {}

        for from_step, to_step in self.EDGES:
            if from_step not in self._adjacency_list:
                self._adjacency_list[from_step] = []
            self._adjacency_list[from_step].append(to_step)

            if to_step not in self._reverse_adjacency:
                self._reverse_adjacency[to_step] = []
            self._reverse_adjacency[to_step].append(from_step)

    def get_next_steps(self, current_step: str) -> list[str]:
        """Get next steps from current step"""
        return self._adjacency_list.get(current_step, [])

    def get_prev_steps(self, step: str) -> list[str]:
        """Get previous steps to reach this step"""
        return self._reverse_adjacency.get(step, [])

    def is_valid_transition(self, from_step: str, to_step: str) -> bool:
        """Check if transition from one step to another is valid"""
        return to_step in self._adjacency_list.get(from_step, [])

    def get_gate_requirements(self, step: str) -> list[str]:
        """Get gate requirements for a step"""
        return self.GATE_REQUIREMENTS.get(step, [])

    def has_gate(self, step: str) -> bool:
        """Check if step has gate requirements"""
        return step in self.GATE_REQUIREMENTS

    def get_step_order(self) -> list[str]:
        """Get steps in topological order"""
        in_degree = {}
        adj_list = {}

        for step in DAGStep:
            in_degree[step.value] = 0
            adj_list[step.value] = []

        for from_step, to_step in self.EDGES:
            adj_list[from_step].append(to_step)
            in_degree[to_step] += 1

        queue = [step for step, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            for neighbor in adj_list[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def get_step_by_role(self, role: str) -> Optional[DAGStep]:
        """Map agent role to initial DAG step"""
        role_to_step = {
            "pm": DAGStep.PRD,
            "architect": DAGStep.SAD,
            "design": DAGStep.LLD,
            "techlead": DAGStep.WBS,
            "dev": DAGStep.CODING,
            "reviewer": DAGStep.CR,
            "qa": DAGStep.TEST,
            "devops": DAGStep.UAT,
        }
        return role_to_step.get(role.lower())


# Global DAG instance
dag = DAGDefinition()
