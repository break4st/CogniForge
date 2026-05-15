"""Agent model - Agent role definitions"""

from typing import Optional

from pydantic import BaseModel, Field

from cogniforge.core.constants import AgentRole


class AgentDefinition(BaseModel):
    """
    Agent role definition.

    Defines the responsibilities, inputs, and outputs for each agent role.
    """

    role: AgentRole
    name: str
    description: str
    responsibilities: list[str] = Field(default_factory=list)
    input_docs: list[str] = Field(default_factory=list, description="Document types this agent reads")
    output_docs: list[str] = Field(default_factory=list, description="Document types this agent produces")
    allowed_modify: list[str] = Field(default_factory=list, description="Paths this agent is allowed to modify")


# Predefined agent definitions
AGENT_DEFINITIONS: dict[AgentRole, AgentDefinition] = {
    AgentRole.PM: AgentDefinition(
        role=AgentRole.PM,
        name="Product Manager Agent",
        description="Defines product requirements and user stories",
        responsibilities=[
            "Write PRD documents",
            "Define user stories",
            "Prioritize requirements",
        ],
        input_docs=[],
        output_docs=["prd"],
        allowed_modify=[".cogniforge/wiki/prd/"],
    ),
    AgentRole.ARCHITECT: AgentDefinition(
        role=AgentRole.ARCHITECT,
        name="System Architect Agent",
        description="Designs system architecture",
        responsibilities=[
            "Create SAD documents",
            "Define system topology",
            "Make architectural decisions",
        ],
        input_docs=["prd"],
        output_docs=["sad", "adr"],
        allowed_modify=[".cogniforge/wiki/sad/", ".cogniforge/wiki/decisions/"],
    ),
    AgentRole.DESIGN: AgentDefinition(
        role=AgentRole.DESIGN,
        name="MDE Agent",
        description="Produces detailed design and data models",
        responsibilities=[
            "Write LLD documents",
            "Define data models",
            "Specify interfaces",
        ],
        input_docs=["prd", "sad"],
        output_docs=["lld"],
        allowed_modify=[".cogniforge/wiki/lld/"],
    ),
    AgentRole.TECHLEAD: AgentDefinition(
        role=AgentRole.TECHLEAD,
        name="Tech Lead Agent",
        description="Schedules tasks and governs execution",
        responsibilities=[
            "Create WBS",
            "Schedule tasks",
            "Evaluate quality",
            "Decide next steps",
            "Control flow",
        ],
        input_docs=["prd", "sad", "lld", "tasks"],
        output_docs=["tasks"],
        allowed_modify=[".cogniforge/wiki/tasks/"],
    ),
    AgentRole.DEV: AgentDefinition(
        role=AgentRole.DEV,
        name="Developer Agent",
        description="Implements code and tests",
        responsibilities=[
            "Write code",
            "Write unit tests",
            "Fix bugs",
        ],
        input_docs=["lld", "tasks", "decisions"],
        output_docs=["code", "test"],
        allowed_modify=["src/", "tests/"],
    ),
    AgentRole.REVIEWER: AgentDefinition(
        role=AgentRole.REVIEWER,
        name="Code Reviewer Agent",
        description="Enforces code quality through reviews",
        responsibilities=[
            "Review code changes",
            "Generate CR reports",
            "Ensure quality gates pass",
        ],
        input_docs=["code", "lld"],
        output_docs=["report"],
        allowed_modify=[".cogniforge/wiki/reports/"],
    ),
    AgentRole.QA: AgentDefinition(
        role=AgentRole.QA,
        name="QA Agent",
        description="Validates functionality through testing",
        responsibilities=[
            "Write test cases",
            "Execute tests",
            "Generate test reports",
        ],
        input_docs=["lld", "tasks"],
        output_docs=["test_case", "report"],
        allowed_modify=[".cogniforge/wiki/qa/", ".cogniforge/wiki/reports/"],
    ),
    AgentRole.DEVOPS: AgentDefinition(
        role=AgentRole.DEVOPS,
        name="DevOps Agent",
        description="Handles infrastructure and deployment",
        responsibilities=[
            "Write deployment configs",
            "Prepare infrastructure",
            "Deploy releases",
        ],
        input_docs=["sad", "lld"],
        output_docs=["deploy"],
        allowed_modify=[".cogniforge/wiki/ops/", "infra/"],
    ),
}


def get_agent_definition(role: AgentRole) -> AgentDefinition:
    """Get agent definition by role"""
    return AGENT_DEFINITIONS.get(role)
