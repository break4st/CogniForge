"""ADR manager - Architecture Decision Records"""

from datetime import datetime
from typing import Optional

from cogniforge.models.document import Document, DocumentType
from cogniforge.wiki.wiki_system import WikiSystem


class ADRManager:
    """
    Architecture Decision Records manager.

    ADR format:
    # ADR-{序号}: {标题}
    - Status: Proposed|Accepted|Deprecated
    - Date: {日期}
    - Context: {背景}
    - Decision: {决策}
    - Consequences: {后果}
    """

    def __init__(self, wiki_system: WikiSystem):
        self.wiki_system = wiki_system

    def create_adr(
        self,
        title: str,
        context: str,
        decision: str,
        consequences: str,
        status: str = "Proposed",
        author: str = "system"
    ) -> Document:
        """Create a new ADR"""
        adr_id = self._generate_adr_id()
        content = self._format_adr(
            adr_id, title, context, decision, consequences, status
        )

        doc = Document(
            doc_id=adr_id,
            doc_type=DocumentType.ADR,
            title=f"ADR-{adr_id}: {title}",
            content=content,
            path=f"wiki/decisions/ADR-{adr_id}.md",
            author=author
        )

        return doc

    def _generate_adr_id(self) -> str:
        """Generate next ADR ID"""
        existing = self.wiki_system.list_documents(DocumentType.ADR)

        max_num = 0
        for doc in existing:
            # Extract number from ADR-{number}: format
            if doc.doc_id.startswith("ADR-"):
                try:
                    num = int(doc.doc_id.split("-")[1])
                    max_num = max(max_num, num)
                except (ValueError, IndexError):
                    pass

        return f"{max_num + 1:03d}"

    def _format_adr(
        self,
        adr_id: str,
        title: str,
        context: str,
        decision: str,
        consequences: str,
        status: str
    ) -> str:
        """Format ADR content"""
        date = datetime.now().strftime("%Y-%m-%d")

        return f"""# ADR-{adr_id}: {title}

**Status**: {status}
**Date**: {date}

---

## Context

{context}

---

## Decision

{decision}

---

## Consequences

{consequences}
"""

    def update_status(
        self,
        adr_id: str,
        new_status: str,
        author: str = "system"
    ) -> Optional[Document]:
        """Update ADR status"""
        # Parse adr_id to get the number
        adr_num = adr_id.replace("ADR-", "").replace("ADR", "")

        doc = self.wiki_system.read_document(DocumentType.ADR, doc_id=adr_num)
        if not doc:
            return None

        # Update status in content
        lines = doc.content.split("\n")
        new_lines = []
        for line in lines:
            if line.startswith("**Status**: "):
                new_lines.append(f"**Status**: {new_status}")
            else:
                new_lines.append(line)

        doc.update_content("\n".join(new_lines))
        doc.author = author

        return doc

    def get_adr(self, adr_id: str) -> Optional[Document]:
        """Get an ADR by ID"""
        adr_num = adr_id.replace("ADR-", "").replace("ADR", "")
        return self.wiki_system.read_document(DocumentType.ADR, doc_id=adr_num)

    def list_adrs(self) -> list[Document]:
        """List all ADRs"""
        return self.wiki_system.list_documents(DocumentType.ADR)

    def get_adr_count(self) -> int:
        """Get total number of ADRs"""
        return len(self.list_adrs())
