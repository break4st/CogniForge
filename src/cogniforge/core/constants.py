"""Constants for CogniForge"""

from enum import Enum


class DocumentType(str, Enum):
    """Document types in the wiki system"""
    PRD = "prd"
    SAD = "sad"
    LLD = "lld"
    ADR = "adr"
    TASK = "task"
    TEST_CASE = "test_case"
    REPORT = "report"
    DEPLOY = "deploy"


class TaskStatus(str, Enum):
    """Task status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"


class TaskPriority(int, Enum):
    """Task priority"""
    P0 = 0  # Blocking
    P1 = 1  # High
    P2 = 2  # Medium
    P3 = 3  # Low


class AgentRole(str, Enum):
    """Agent roles"""
    PM = "pm"
    ARCHITECT = "architect"
    DESIGN = "design"
    TECHLEAD = "techlead"
    DEV = "dev"
    REVIEWER = "reviewer"
    QA = "qa"
    DEVOPS = "devops"


# DAG workflow steps
DAG_STEPS = [
    "prd",
    "req_review",
    "sad",
    "arch_review",
    "lld",
    "design_review",
    "wbs",
    "coding",
    "code_review",
    "test",
    "fix",
    "uat",
    "retro",
]

# Wiki directory structure
WIKI_STRUCTURE = {
    DocumentType.PRD: ".cogniforge/wiki/prd",
    DocumentType.SAD: ".cogniforge/wiki/sad",
    DocumentType.LLD: ".cogniforge/wiki/lld",
    DocumentType.ADR: ".cogniforge/wiki/decisions",
    DocumentType.TASK: ".cogniforge/wiki/tasks",
    DocumentType.TEST_CASE: ".cogniforge/wiki/qa",
    DocumentType.REPORT: ".cogniforge/wiki/reports",
    DocumentType.DEPLOY: ".cogniforge/wiki/ops",
}

# Gate requirements for quality control
GATE_REQUIREMENTS = {
    "code_review": ["cr_passed"],
    "test": ["tests_passed"],
    "uat": ["uat_passed"],
}

# Git commit message prefixes
GIT_COMMIT_PREFIXES = {
    "feat": "New feature",
    "fix": "Bug fix",
    "docs": "Documentation",
    "refactor": "Code refactoring",
    "test": "Tests",
    "chore": "Maintenance",
}
