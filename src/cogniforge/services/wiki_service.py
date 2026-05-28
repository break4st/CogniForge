"""Wiki document service — read, list, and search wiki documents."""

from __future__ import annotations

import json
from pathlib import Path

from cogniforge.core.constants import DocumentType


class WikiService:
    """Read-only wrapper around the wiki document store."""

    def __init__(self, wiki_system, repo_path: Path | None = None):
        self._wiki = wiki_system
        self._repo_path = repo_path or getattr(wiki_system, "repo_path", Path.cwd())

    def list(self, doc_type_str: str = "") -> list[dict]:
        """List wiki entries, optionally filtered by document type."""
        entries: list[dict] = []
        types_to_list = (
            [DocumentType(doc_type_str)] if doc_type_str
            else list(DocumentType)
        )
        for dt in types_to_list:
            try:
                docs = self._wiki.list_documents(dt)
            except Exception:
                continue
            for doc in docs:
                updated = ""
                if hasattr(doc, "updated_at"):
                    ua = doc.updated_at
                    updated = ua.isoformat() if hasattr(ua, "isoformat") else str(ua)
                entries.append({
                    "doc_id": getattr(doc, "doc_id", ""),
                    "type": dt.value,
                    "title": getattr(doc, "title", ""),
                    "author": getattr(doc, "author", ""),
                    "path": getattr(doc, "path", ""),
                    "updated_at": updated,
                })
        return entries

    def read(self, path: str) -> dict:
        """Read a wiki document by relative path."""
        full_path = self._repo_path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        data = json.loads(full_path.read_text(encoding="utf-8"))
        return {
            "path": path,
            "content": data,
            "meta": data.get("meta", {}),
        }

    def search(self, query: str) -> list[dict]:
        """Simple text search across all wiki JSON files."""
        results: list[dict] = []
        wiki_dir = self._repo_path / ".cogniforge" / "wiki"
        if not wiki_dir.exists():
            return results

        q = query.lower()
        for fpath in wiki_dir.rglob("*.json"):
            try:
                text = fpath.read_text(encoding="utf-8")
                if q in text.lower():
                    rel = fpath.relative_to(self._repo_path).as_posix()
                    results.append({
                        "path": rel,
                        "type": fpath.parent.name,
                        "snippet": _extract_snippet(text, q, 120),
                    })
            except Exception:
                pass
        return results


def _extract_snippet(text: str, query: str, max_len: int = 120) -> str:
    """Extract a short snippet around the first match of query."""
    idx = text.lower().find(query.lower())
    if idx == -1:
        return text[:max_len]
    start = max(0, idx - max_len // 2)
    end = min(len(text), idx + len(query) + max_len // 2)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet
