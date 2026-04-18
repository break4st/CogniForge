"""Architect Agent - System Architecture Agent"""

from typing import Optional

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.models.document import Document


class ArchitectAgent(BaseAgent):
    """
    Architect Agent - System Architect.

    Responsibilities:
    - Create SAD documents
    - Define system topology
    - Make architectural decisions (ADR)
    """

    def run(self, input_data: dict) -> dict:
        """
        Create or update SAD document.

        Args:
            input_data: {
                "title": str,
                "system_overview": str,
                "architecture": str,
                "components": list[dict],
                "topology": str,
                "data_flow": str,
            }
        """
        try:
            title = input_data.get("title", "System Architecture")
            system_overview = input_data.get("system_overview", "")
            architecture = input_data.get("architecture", "")
            components = input_data.get("components", [])
            topology = input_data.get("topology", "")
            data_flow = input_data.get("data_flow", "")

            content = self._format_sad(
                title, system_overview, architecture, components, topology, data_flow
            )

            existing = self.wiki_system.list_documents(DocumentType.SAD)
            seq = len(existing) + 1
            doc_id = f"sad-{seq:03d}"

            doc = Document(
                doc_id=doc_id,
                doc_type=DocumentType.SAD,
                title=title,
                content=content,
                path=f"wiki/sad/{doc_id}.md",
                author="architect_agent"
            )

            self.write_document(doc, f"feat: add SAD - {title}")

            return self.format_result(
                status="success",
                message=f"SAD created: {doc_id}",
                artifacts=[doc.path]
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )

    def _format_sad(
        self,
        title: str,
        system_overview: str,
        architecture: str,
        components: list,
        topology: str,
        data_flow: str
    ) -> str:
        """Format SAD content"""
        lines = [
            f"# {title}",
            "",
            "## System Overview",
            system_overview,
            "",
            "## Architecture",
            architecture,
        ]

        if components:
            lines.extend(["", "## Components", ""])
            for comp in components:
                lines.append(f"\n### {comp.get('name', 'Component')}")
                lines.append(f"**Type**: {comp.get('type', 'Unknown')}")
                lines.append(f"\n{comp.get('description', '')}")

                if comp.get('responsibilities'):
                    lines.append("\n**Responsibilities:**")
                    for resp in comp['responsibilities']:
                        lines.append(f"- {resp}")

        if topology:
            lines.extend(["", "## System Topology", "", topology])

        if data_flow:
            lines.extend(["", "## Data Flow", "", data_flow])

        return "\n".join(lines)
