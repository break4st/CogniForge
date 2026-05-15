"""PM Agent - Product Manager Agent for PRD creation"""

from typing import Optional

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.models.document import Document


class PMAgent(BaseAgent):
    """
    PM Agent - Product Manager.

    Responsibilities:
    - Write PRD documents
    - Define user stories
    - Prioritize requirements
    """

    def run(self, input_data: dict) -> dict:
        """
        Create or update PRD document.

        Args:
            input_data: {
                "title": str,
                "overview": str,
                "requirements": list[dict],
                "user_stories": list[dict],
                "priorities": dict,
            }
        """
        try:
            title = input_data.get("title", "Untitled PRD")
            overview = input_data.get("overview", "")
            requirements = input_data.get("requirements", [])
            user_stories = input_data.get("user_stories", [])
            priorities = input_data.get("priorities", {})

            content = self._format_prd(title, overview, requirements, user_stories, priorities)

            # Generate doc_id
            existing = self.wiki_system.list_documents(DocumentType.PRD)
            seq = len(existing) + 1
            doc_id = f"prd-{seq:03d}"

            doc = Document(
                doc_id=doc_id,
                doc_type=DocumentType.PRD,
                title=title,
                content=content,
                path=f".cogniforge/wiki/prd/{doc_id}.md",
                author="pm_agent"
            )

            self.write_document(doc, f"feat: add PRD - {title}")

            return self.format_result(
                status="success",
                message=f"PRD created: {doc_id}",
                artifacts=[doc.path]
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )

    def _format_prd(
        self,
        title: str,
        overview: str,
        requirements: list,
        user_stories: list,
        priorities: dict
    ) -> str:
        """Format PRD content"""
        lines = [
            f"# {title}",
            "",
            "## Overview",
            overview,
            "",
            "## Requirements",
        ]

        for i, req in enumerate(requirements, 1):
            lines.append(f"\n### {i}. {req.get('name', 'Requirement')}")
            lines.append(f"\n{req.get('description', '')}")

            if req.get('acceptance_criteria'):
                lines.append("\n**Acceptance Criteria:**")
                for ac in req['acceptance_criteria']:
                    lines.append(f"- {ac}")

        if user_stories:
            lines.extend(["", "## User Stories", ""])
            for story in user_stories:
                lines.append(f"### As a {story.get('role', 'user')}, I want to {story.get('action', 'do something')}")
                lines.append(f"**So that**: {story.get('goal', '')}")

        if priorities:
            lines.extend(["", "## Priorities", ""])
            for item, priority in priorities.items():
                lines.append(f"- **{item}**: {priority}")

        return "\n".join(lines)
