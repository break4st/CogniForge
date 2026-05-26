"""Wiki system — two-tier document management.

Agent Format:  ``.cogniforge/wiki/{type}/{id}.json`` — structured JSON,
    the source of truth.  Agents read from and write to this format.

User Format:   ``.cogniforge/html/{type}/{id}.html`` — self-contained HTML,
    auto-rendered from the JSON by WikiRenderer.  Humans read this.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from cogniforge.core.config import Config
from cogniforge.core.constants import DocumentType
from cogniforge.models.document import Document
from cogniforge.storage.git_storage import GitStorage


class WikiSystem:
    """Wiki document system with two-tier format support."""

    # Primary path: Agent JSON format (source of truth)
    _AGENT_PATHS = {
        DocumentType.PRD:       ".cogniforge/wiki/prd/{doc_id}.json",
        DocumentType.SAD:       ".cogniforge/wiki/sad/{doc_id}.json",
        DocumentType.LLD:       ".cogniforge/wiki/lld/{module}/{doc_id}.json",
        DocumentType.ADR:       ".cogniforge/wiki/decisions/{doc_id}.json",
        DocumentType.TASK:      ".cogniforge/wiki/tasks/{task_id}.json",
        DocumentType.TEST_CASE: ".cogniforge/wiki/qa/{doc_id}.json",
        DocumentType.REPORT:    ".cogniforge/wiki/reports/{doc_id}.json",
        DocumentType.DEPLOY:    ".cogniforge/wiki/ops/{doc_id}.json",
    }

    def __init__(self, config: Config, git_storage: GitStorage):
        self.config = config
        self.git_storage = git_storage
        self.repo_path = config.repo_path
        self._ensure_wiki_repo()
        self._ensure_structure()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def agent_path(self, doc_type: DocumentType, *, doc_id: str = "",
                   module: str = "", task_id: str = "") -> Path:
        """Return the path for the agent-format JSON file."""
        template = self._AGENT_PATHS[doc_type]
        return self.repo_path / template.format(
            doc_id=doc_id, module=module, task_id=task_id)

    def user_path(self, doc_type: DocumentType, *, doc_id: str = "",
                  module: str = "", task_id: str = "") -> Path:
        """Return the path for the user-format HTML file (under html/ subdir)."""
        agent_p = self.agent_path(doc_type, doc_id=doc_id, module=module, task_id=task_id)
        # Map: .cogniforge/wiki/{type}/...json → .cogniforge/html/{type}/...html
        rel = agent_p.relative_to(self.repo_path)
        parts = rel.parts  # ['.cogniforge', 'wiki', 'prd', 'prd-001.json']
        html_parts = [parts[0], "html"] + list(parts[2:])
        html_rel = Path(*html_parts)
        return (self.repo_path / html_rel).with_suffix(".html")

    # ------------------------------------------------------------------
    # Read / Write (two-tier)
    # ------------------------------------------------------------------

    def read_json(self, doc_type: DocumentType, *, doc_id: str = "",
                  module: str = "", task_id: str = "") -> dict | None:
        """Read agent-format JSON.  Returns parsed dict or None."""
        path = self.agent_path(doc_type, doc_id=doc_id, module=module, task_id=task_id)
        if not path.exists():
            return None
        try:
            from cogniforge.wiki.wiki_renderer import load_json_with_repair
            return load_json_with_repair(path)
        except (json.JSONDecodeError, ValueError):
            return None

    def write_json(self, doc_type: DocumentType, data: dict, *,
                   doc_id: str = "", module: str = "", task_id: str = "",
                   commit_message: str | None = None, render: bool = True) -> Path:
        """Write agent-format JSON, optionally render user HTML, git stage."""
        path = self.agent_path(doc_type, doc_id=doc_id, module=module, task_id=task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        rel = path.relative_to(self.repo_path).as_posix()
        self.git_storage.repo.index.add([rel])

        html_rel = None
        if render:
            from cogniforge.wiki.wiki_renderer import render_file
            html_path = render_file(path)
            if html_path is not None:
                html_rel = html_path.relative_to(self.repo_path).as_posix()
                self.git_storage.repo.index.add([html_rel])

        if self.config.wiki.auto_commit or commit_message:
            author = data.get("meta", {}).get("author", "agent")
            msg = commit_message or f"{self.config.wiki.auto_commit_prefix}: {doc_type.value}: {doc_id or task_id}"
            staged = [rel]
            if html_rel:
                staged.append(html_rel)
            self.git_storage.commit_wiki(staged, msg, author)
            if self.config.wiki.auto_push:
                self.git_storage.push_wiki()

        return path

    # ------------------------------------------------------------------
    # Legacy read / write (for existing .md / .html files)
    # ------------------------------------------------------------------

    def read_document(
        self, doc_type: DocumentType, doc_id: Optional[str] = None,
        module: Optional[str] = None, task_id: Optional[str] = None,
    ) -> Optional[Document]:
        """Read a document — tries JSON first, falls back to legacy formats."""
        data = self.read_json(doc_type, doc_id=doc_id or "",
                              module=module or "", task_id=task_id or "")
        if data is not None:
            meta = data.get("meta", {})
            return Document(
                doc_id=meta.get("doc_id", doc_id or ""),
                doc_type=doc_type,
                title=meta.get("title", ""),
                content=json.dumps(data, ensure_ascii=False),
                path=str(self.agent_path(doc_type, doc_id=doc_id or "",
                                         module=module or "", task_id=task_id or "")),
                author=meta.get("author", ""),
            )
        return self._read_legacy(doc_type, doc_id, module, task_id)

    def _read_legacy(
        self, doc_type: DocumentType, doc_id: str | None,
        module: str | None, task_id: str | None,
    ) -> Optional[Document]:
        """Fallback: read old .md or .html files."""
        # Try old-style paths
        if doc_type == DocumentType.PRD:
            path = self.repo_path / f".cogniforge/wiki/prd/{doc_id or 'prd-001'}.html"
        elif doc_type == DocumentType.SAD:
            path = self.repo_path / f".cogniforge/wiki/sad/{doc_id or 'sad-001'}.md"
        else:
            return None

        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        return Document(
            doc_id=doc_id or path.stem,
            doc_type=doc_type,
            title=doc_id or path.stem,
            content=content,
            path=path.relative_to(self.repo_path).as_posix(),
            author="agent",
        )

    def write_document(
        self, doc: Document, commit_message: Optional[str] = None,
    ) -> None:
        """Legacy write — persists the Document as-is (used by non-agentic paths)."""
        doc_path = self.repo_path / doc.path
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        if doc_path.suffix == ".html":
            doc_path.write_text(doc.content, encoding="utf-8")
        else:
            doc_path.write_text(doc.to_markdown(), encoding="utf-8")
        self.git_storage.repo.index.add([doc.path])
        if self.config.wiki.auto_commit or commit_message:
            msg = commit_message or f"{self.config.wiki.auto_commit_prefix}: {doc.doc_type.value}: {doc.doc_id}"
            self.git_storage.commit_wiki([doc.path], msg, doc.author)
            if self.config.wiki.auto_push:
                self.git_storage.push_wiki()

    # ------------------------------------------------------------------
    # List / delete
    # ------------------------------------------------------------------

    def list_documents(self, doc_type: DocumentType, module: Optional[str] = None) -> list[Document]:
        """List all documents — uses JSON files as source of truth."""
        import glob

        documents = []
        dir_path = self._AGENT_PATHS[doc_type].split("/{")[0]
        pattern = f"{dir_path}/*.json"

        if module and doc_type == DocumentType.LLD:
            pattern = f".cogniforge/wiki/lld/{module}/*.json"

        full_pattern = str(self.repo_path / pattern)
        for file_path in glob.glob(full_pattern):
            try:
                data = json.loads(Path(file_path).read_text(encoding="utf-8"))
                meta = data.get("meta", {})
                rel = Path(file_path).relative_to(self.repo_path).as_posix()
                documents.append(Document(
                    doc_id=meta.get("doc_id", Path(file_path).stem),
                    doc_type=doc_type,
                    title=meta.get("title", ""),
                    content=json.dumps(data, ensure_ascii=False),
                    path=rel,
                    author=meta.get("author", ""),
                ))
            except Exception:
                pass

        return documents

    def document_exists(self, doc_type: DocumentType, doc_id: Optional[str] = None,
                        module: Optional[str] = None) -> bool:
        path = self.agent_path(doc_type, doc_id=doc_id or "", module=module or "")
        return path.exists()

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def _ensure_wiki_repo(self) -> None:
        """确保 wiki 目录是独立 git 仓库，不是则自动初始化。"""
        self.git_storage._wiki_repo()  # 懒初始化：非 git repo 时自动 git init

    def _ensure_structure(self) -> None:
        dirs = {p.split("/{")[0] for p in self._AGENT_PATHS.values()}
        for d in dirs:
            (self.repo_path / d).mkdir(parents=True, exist_ok=True)
            # Ensure corresponding html/ subdir: .cogniforge/wiki/{type} → .cogniforge/html/{type}
            html_d = str(Path(d).parent.parent / "html" / Path(d).name)
            (self.repo_path / html_d).mkdir(parents=True, exist_ok=True)
