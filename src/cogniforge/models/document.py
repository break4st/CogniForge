"""Document model - Document as State"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from cogniforge.core.constants import DocumentType


class Document(BaseModel):
    """
    Document model - represents all system state as documents.

    All state must be persisted as structured documents in Git.
    """

    doc_id: str = Field(description="Unique document identifier, format: {type}-{YYYYMMD}-{seq}")
    doc_type: DocumentType
    title: str
    content: str = ""
    path: str = Field(description="Path in wiki")
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    author: str = Field(default="system")
    metadata: dict = Field(default_factory=dict)

    def update_content(self, new_content: str) -> None:
        """Update document content and increment version"""
        self.content = new_content
        self.version += 1
        self.updated_at = datetime.now()

    def to_markdown(self) -> str:
        """Render document as markdown"""
        lines = [
            f"# {self.title}",
            "",
            f"**ID**: {self.doc_id}",
            f"**Type**: {self.doc_type.value}",
            f"**Version**: {self.version}",
            f"**Author**: {self.author}",
            f"**Created**: {self.created_at.isoformat()}",
            f"**Updated**: {self.updated_at.isoformat()}",
            "",
            "---",
            "",
        ]
        if self.metadata:
            lines.extend(["## Metadata", ""])
            for key, value in self.metadata.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")

        lines.extend(["## Content", "", self.content])
        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, path: str, markdown_content: str) -> "Document":
        """Parse document from markdown content"""
        lines = markdown_content.split("\n")
        metadata = {}
        content_lines = []
        in_content = False

        title = ""
        doc_id = ""
        doc_type = DocumentType.PRD
        version = 1
        author = "system"
        created_at = datetime.now()
        updated_at = datetime.now()

        for i, line in enumerate(lines):
            if i == 0 and line.startswith("# "):
                title = line[2:].strip()
                continue

            if line.startswith("**ID**: "):
                doc_id = line[8:].strip()
            elif line.startswith("**Type**: "):
                doc_type_str = line[10:].strip()
                doc_type = DocumentType(doc_type_str)
            elif line.startswith("**Version**: "):
                version = int(line[12:].strip())
            elif line.startswith("**Author**: "):
                author = line[11:].strip()
            elif line.startswith("**Created**: "):
                created_at = datetime.fromisoformat(line[11:].strip())
            elif line.startswith("**Updated**: "):
                updated_at = datetime.fromisoformat(line[12:].strip())
            elif line.startswith("- **") and ":" in line:
                parts = line[4:].split(":** ", 1)
                if len(parts) == 2:
                    metadata[parts[0]] = parts[1]
            elif line == "## Content":
                in_content = True
            elif in_content:
                content_lines.append(line)

        return cls(
            doc_id=doc_id,
            doc_type=doc_type,
            title=title,
            content="\n".join(content_lines).strip(),
            path=path,
            version=version,
            created_at=created_at,
            updated_at=updated_at,
            author=author,
            metadata=metadata,
        )
