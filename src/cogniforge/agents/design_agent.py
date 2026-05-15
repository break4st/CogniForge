"""Design Agent - MDE Agent for detailed design"""

from typing import Optional

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.models.document import Document


class DesignAgent(BaseAgent):
    """
    Design Agent - MDE (Methodology Design Engineer).

    Responsibilities:
    - Write LLD documents
    - Define data models
    - Specify interfaces
    """

    def run(self, input_data: dict) -> dict:
        """
        Create or update LLD document.

        Args:
            input_data: {
                "module": str,
                "title": str,
                "overview": str,
                "data_models": list[dict],
                "interfaces": list[dict],
                "error_handling": str,
            }
        """
        try:
            module = input_data.get("module", "unknown")
            title = input_data.get("title", f"LLD - {module}")
            overview = input_data.get("overview", "")
            data_models = input_data.get("data_models", [])
            interfaces = input_data.get("interfaces", [])
            error_handling = input_data.get("error_handling", "")

            content = self._format_lld(
                title, overview, data_models, interfaces, error_handling
            )

            doc_id = f"lld-{module}"
            doc = Document(
                doc_id=doc_id,
                doc_type=DocumentType.LLD,
                title=title,
                content=content,
                path=f".cogniforge/wiki/lld/{module}/{doc_id}.md",
                author="design_agent",
                metadata={"module": module}
            )

            self.write_document(doc, f"feat: add LLD for {module}")

            return self.format_result(
                status="success",
                message=f"LLD created for module: {module}",
                artifacts=[doc.path],
                data={"module": module}
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )

    def _format_lld(
        self,
        title: str,
        overview: str,
        data_models: list,
        interfaces: list,
        error_handling: str
    ) -> str:
        """Format LLD content"""
        lines = [
            f"# {title}",
            "",
            "## Overview",
            overview,
        ]

        if data_models:
            lines.extend(["", "## Data Models", ""])
            for model in data_models:
                lines.append(f"\n### {model.get('name', 'Model')}")
                lines.append(f"\n**Type**: {model.get('type', 'entity')}")

                if model.get('fields'):
                    lines.append("\n**Fields:**")
                    lines.append("| Field | Type | Description |")
                    lines.append("|--------|------|-------------|")
                    for field in model['fields']:
                        lines.append(
                            f"| {field.get('name', '')} | "
                            f"{field.get('type', '')} | "
                            f"{field.get('description', '')} |"
                        )

        if interfaces:
            lines.extend(["", "## Interfaces", ""])
            for iface in interfaces:
                lines.append(f"\n### {iface.get('name', 'Interface')}")
                lines.append(f"\n**Endpoint**: {iface.get('endpoint', 'N/A')}")
                lines.append(f"\n{iface.get('description', '')}")

                if iface.get('parameters'):
                    lines.append("\n**Parameters:**")
                    for param in iface['parameters']:
                        lines.append(f"- {param.get('name', '')}: {param.get('type', '')} - {param.get('description', '')}")

        if error_handling:
            lines.extend(["", "## Error Handling", "", error_handling])

        return "\n".join(lines)
