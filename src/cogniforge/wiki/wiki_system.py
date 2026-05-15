"""Wiki system - document management"""

from pathlib import Path
from typing import Optional

from cogniforge.core.config import Config
from cogniforge.core.constants import DocumentType
from cogniforge.core.exceptions import DocumentNotFoundError, DocumentExistsError
from cogniforge.models.document import Document
from cogniforge.storage.git_storage import GitStorage


class WikiSystem:
    """
    Wiki document system.

    Responsibilities:
    - Document CRUD operations
    - Directory structure maintenance
    - Version management
    """

    WIKI_STRUCTURE = {
        DocumentType.PRD: ".cogniforge/wiki/prd/{doc_id}.md",
        DocumentType.SAD: ".cogniforge/wiki/sad/{doc_id}.md",
        DocumentType.LLD: ".cogniforge/wiki/lld/{module}/{doc_id}.md",
        DocumentType.ADR: ".cogniforge/wiki/decisions/{doc_id}.md",
        DocumentType.TASK: ".cogniforge/wiki/tasks/{task_id}.md",
        DocumentType.TEST_CASE: ".cogniforge/wiki/qa/test_cases.md",
        DocumentType.REPORT: ".cogniforge/wiki/reports/{doc_id}.md",
        DocumentType.DEPLOY: ".cogniforge/wiki/ops/deploy.md",
    }

    def __init__(self, config: Config, git_storage: GitStorage):
        self.config = config
        self.git_storage = git_storage
        self.repo_path = config.repo_path
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        """Ensure wiki directory structure exists"""
        dirs = set()
        for path_template in self.WIKI_STRUCTURE.values():
            # Extract directory from template
            dir_path = path_template.split("/{")[0]
            dirs.add(dir_path)

            # Also handle module-based paths
            if "{module}" in path_template:
                # Create a placeholder for module directories
                pass

        for dir_path in dirs:
            full_path = self.repo_path / dir_path
            full_path.mkdir(parents=True, exist_ok=True)

    def read_document(
        self,
        doc_type: DocumentType,
        doc_id: Optional[str] = None,
        module: Optional[str] = None,
        task_id: Optional[str] = None
    ) -> Optional[Document]:
        """Read a document from wiki"""
        path_template = self.WIKI_STRUCTURE[doc_type]

        # Build kwargs for path formatting
        kwargs = {}
        if doc_id:
            kwargs["doc_id"] = doc_id
        if module:
            kwargs["module"] = module
        if task_id:
            kwargs["task_id"] = task_id

        # For documents that don't use doc_id in path
        if doc_type == DocumentType.TEST_CASE:
            path = self.repo_path / ".cogniforge/wiki/qa/test_cases.md"
        elif not kwargs:
            path = self.repo_path / path_template.format(**{"doc_id": doc_id or ""})
        else:
            path = self.repo_path / path_template.format(**kwargs)

        if not path.exists():
            return None

        content = path.read_text(encoding="utf-8")
        return Document.from_markdown(str(path.relative_to(self.repo_path)), content)

    def write_document(
        self,
        doc: Document,
        commit_message: Optional[str] = None
    ) -> None:
        """Write a document to wiki"""
        # Ensure parent directory exists
        doc_path = self.repo_path / doc.path
        doc_path.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        markdown = doc.to_markdown()
        doc_path.write_text(markdown, encoding="utf-8")

        # Stage in Git
        self.git_storage.repo.index.add([doc.path])

        # Commit if message provided
        if commit_message:
            self.git_storage.commit(commit_message, doc.author)

    def delete_document(
        self,
        doc_type: DocumentType,
        doc_id: Optional[str] = None,
        module: Optional[str] = None,
        commit_message: Optional[str] = None
    ) -> None:
        """Delete a document from wiki"""
        path_template = self.WIKI_STRUCTURE[doc_type]

        kwargs = {}
        if doc_id:
            kwargs["doc_id"] = doc_id
        if module:
            kwargs["module"] = module

        if not kwargs:
            kwargs["doc_id"] = ""

        path = self.repo_path / path_template.format(**kwargs)

        if not path.exists():
            return

        path.unlink()
        self.git_storage.repo.index.remove([str(path.relative_to(self.repo_path))])

        if commit_message:
            self.git_storage.commit(commit_message)

    def list_documents(self, doc_type: DocumentType, module: Optional[str] = None) -> list[Document]:
        """List all documents of a given type"""
        import glob

        documents = []

        if doc_type == DocumentType.TEST_CASE:
            pattern = ".cogniforge/wiki/qa/*.md"
        elif module and doc_type == DocumentType.LLD:
            pattern = f".cogniforge/wiki/lld/{module}/*.md"
        else:
            dir_path = self.WIKI_STRUCTURE[doc_type].split("/{")[0]
            pattern = f"{dir_path}/*.md"

        full_pattern = str(self.repo_path / pattern)

        for file_path in glob.glob(full_pattern):
            rel_path = str(Path(file_path).relative_to(self.repo_path))
            content = Path(file_path).read_text(encoding="utf-8")
            try:
                doc = Document.from_markdown(rel_path, content)
                documents.append(doc)
            except Exception:
                # Skip files that can't be parsed
                pass

        return documents

    def document_exists(
        self,
        doc_type: DocumentType,
        doc_id: Optional[str] = None,
        module: Optional[str] = None
    ) -> bool:
        """Check if a document exists"""
        path_template = self.WIKI_STRUCTURE[doc_type]

        kwargs = {}
        if doc_id:
            kwargs["doc_id"] = doc_id
        if module:
            kwargs["module"] = module

        if not kwargs:
            kwargs["doc_id"] = ""

        path = self.repo_path / path_template.format(**kwargs)
        return path.exists()
