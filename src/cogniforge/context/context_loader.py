"""Context loader - deterministic context loading without RAG"""

from pathlib import Path
from typing import Optional

from cogniforge.core.config import Config
from cogniforge.core.exceptions import ContextLoadError


class ContextLoader:
    """
    Deterministic context loader.

    Context is loaded by rules, not semantic search.
    Loading strategy: Global -> Module -> Task -> Code
    """

    def __init__(self, config: Config):
        self.config = config
        self.repo_path = config.repo_path

    def load_context(
        self,
        task_id: Optional[str] = None,
        module: Optional[str] = None,
        include_code: bool = True
    ) -> dict[str, str]:
        """
        Load deterministic context based on rules.

        Args:
            task_id: Optional task ID for task-specific context
            module: Optional module for module-specific context
            include_code: Whether to include code files

        Returns:
            Dict mapping file paths to their contents
        """
        context = {}

        # 1. Load global context (PRD, SAD, ADR)
        context.update(self._load_global_context())

        # 2. Load module context (LLD, module code)
        if module:
            context.update(self._load_module_context(module, include_code))

        # 3. Load task context (task definition)
        if task_id:
            context.update(self._load_task_context(task_id))

        return context

    def _load_global_context(self) -> dict[str, str]:
        """Load global wiki context"""
        context = {}

        for pattern in self.config.context_global_patterns:
            context.update(self._load_by_pattern(pattern))

        return context

    def _load_module_context(self, module: str, include_code: bool) -> dict[str, str]:
        """Load module-specific context"""
        context = {}

        # LLD for the module
        lld_pattern = f".cogniforge/wiki/lld/{module}/*.md"
        context.update(self._load_by_pattern(lld_pattern))

        # Also check wiki/lld/{module}.md for single-file LLD
        single_lld = f".cogniforge/wiki/lld/{module}.md"
        if (self.repo_path / single_lld).exists():
            context[single_lld] = self._read_file(single_lld)

        # Module code if requested
        if include_code:
            code_pattern = f"src/{module}/*.py"
            context.update(self._load_by_pattern(code_pattern))

        return context

    def _load_task_context(self, task_id: str) -> dict[str, str]:
        """Load task-specific context"""
        context = {}

        # Task definition file
        task_file = f".cogniforge/wiki/tasks/{task_id}.md"
        if (self.repo_path / task_file).exists():
            context[task_file] = self._read_file(task_file)

        return context

    def _load_by_pattern(self, pattern: str) -> dict[str, str]:
        """Load files matching a glob pattern"""
        import glob

        context = {}
        full_pattern = str(self.repo_path / pattern)

        for file_path in glob.glob(full_pattern, recursive=True):
            rel_path = Path(file_path).relative_to(self.repo_path).as_posix()
            try:
                content = Path(file_path).read_text(encoding="utf-8")
                context[rel_path] = content
            except Exception:
                # Skip files that can't be read
                pass

        return context

    def _read_file(self, relative_path: str) -> str:
        """Read a single file"""
        file_path = self.repo_path / relative_path
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
        return ""

    def load_document_types(self, doc_types: list[str]) -> dict[str, str]:
        """Load documents of specified types"""
        context = {}

        for doc_type in doc_types:
            # Map doc type to path patterns
            if doc_type == "prd":
                context.update(self._load_by_pattern(".cogniforge/wiki/prd/*.json"))
            elif doc_type == "sad":
                context.update(self._load_by_pattern(".cogniforge/wiki/sad/*.json"))
            elif doc_type == "adr":
                context.update(self._load_by_pattern(".cogniforge/wiki/decisions/*.json"))
            elif doc_type == "lld":
                context.update(self._load_by_pattern(".cogniforge/wiki/lld/**/*.json"))
            elif doc_type == "tasks":
                context.update(self._load_by_pattern(".cogniforge/wiki/tasks/*.json"))
            elif doc_type == "test_case":
                context.update(self._load_by_pattern(".cogniforge/wiki/qa/*.json"))
            elif doc_type == "report":
                context.update(self._load_by_pattern(".cogniforge/wiki/reports/*.json"))

        return context

    def format_context_for_llm(self, context: dict[str, str]) -> str:
        """Format context dict into a string for LLM consumption"""
        if not context:
            return "No context available."

        formatted = ["# Context\n"]

        # Sort by path for consistent ordering
        for path in sorted(context.keys()):
            content = context[path]
            formatted.append(f"\n## {path}\n")
            formatted.append(f"```\n{content}\n```\n")

        return "\n".join(formatted)
