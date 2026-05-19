"""Base agent - abstract base class for all agents with audit trail"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Any, TYPE_CHECKING
import time

from cogniforge.core.config import Config
from cogniforge.core.constants import AgentRole
from cogniforge.core.exceptions import AgentError
from cogniforge.models.agent import AgentDefinition, get_agent_definition
from cogniforge.context.context_loader import ContextLoader
from cogniforge.wiki.wiki_system import WikiSystem
from cogniforge.models.document import Document
from cogniforge.audit.audit_log import AuditLog

if TYPE_CHECKING:
    from cogniforge.llm.base import BaseLLMAdapter


class BaseAgent(ABC):
    """
    Base class for all agents with audit trail.

    Design principles:
    - Single responsibility
    - Clear input/output
    - Must read/write documents
    - Cannot modify outside allowed paths
    - All outputs are auditable
    """

    def __init__(
        self,
        role: AgentRole,
        wiki_system: WikiSystem,
        context_loader: ContextLoader,
        config: Optional[Config] = None,
        audit_log: Optional[AuditLog] = None,
        agent: Optional["BaseLLMAdapter"] = None,
    ):
        self.role = role
        self.wiki_system = wiki_system
        self.context_loader = context_loader
        self.config = config or Config()
        self.definition = get_agent_definition(role)
        self.audit_log = audit_log or AuditLog(self.config)
        self.agent = agent

        if not self.definition:
            raise AgentError(f"No definition found for role {role}")

    @abstractmethod
    def run(self, input_data: dict) -> dict:
        """
        Execute agent logic.

        Args:
            input_data: Input data containing task, context, etc.

        Returns:
            Result dict with status and artifacts
        """
        pass

    def run_with_audit(self, input_data: dict) -> dict:
        """
        Execute agent logic with full audit trail.

        This method wraps run() and automatically logs:
        - Input context
        - Operation details
        - Output artifacts
        - Duration

        Returns:
            Result dict with status and artifacts
        """
        start_time = time.time()

        # Capture input context
        input_context = self._capture_input_context(input_data)

        try:
            # Execute the actual agent logic
            result = self.run(input_data)

            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)

            # Log the operation to audit trail
            self._log_operation(
                input_data=input_context,
                output_artifacts=result.get("artifacts", []),
                output_summary=result.get("message", ""),
                reasoning=result.get("reasoning", ""),
                decisions=result.get("decisions", []),
                duration_ms=duration_ms,
                status=result.get("status", "success"),
                error=result.get("error")
            )

            return result

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)

            # Log failed operation
            self._log_operation(
                input_data=input_context,
                output_artifacts=[],
                output_summary="",
                reasoning="",
                decisions=[],
                duration_ms=duration_ms,
                status="failed",
                error=str(e)
            )

            raise

    def _capture_input_context(self, input_data: dict) -> dict:
        """Capture what was provided to the agent"""
        context = {
            "input_keys": list(input_data.keys()),
        }

        # Include task info if present
        if "task" in input_data:
            task = input_data["task"]
            context["task_id"] = getattr(task, "task_id", None)
            context["task_name"] = getattr(task, "name", None)
            context["task_module"] = getattr(task, "module", None)

        # Include module info
        if "module" in input_data:
            context["module"] = input_data["module"]

        # Include relevant documents from wiki
        if hasattr(self, "wiki_system"):
            context["available_docs"] = self._list_available_docs()

        return context

    def _list_available_docs(self) -> list[str]:
        """List documents that were used as context"""
        # This would return the docs that were loaded for context
        return []

    def _log_operation(
        self,
        input_data: dict,
        output_artifacts: list,
        output_summary: str,
        reasoning: str,
        decisions: list,
        duration_ms: int,
        status: str,
        error: Optional[str]
    ) -> None:
        """Log operation to audit trail"""
        self.audit_log.log(
            agent_role=self.role.value,
            operation=self._get_operation_name(),
            input_context=input_data,
            input_prompt=self._get_input_prompt(input_data),
            output_artifacts=output_artifacts,
            output_summary=output_summary,
            reasoning=reasoning,
            decisions=decisions,
            duration_ms=duration_ms,
            status=status,
            error=error
        )

    def _get_operation_name(self) -> str:
        """Get operation name for audit log"""
        return f"{self.role.value}_run"

    def _get_input_prompt(self, input_data: dict) -> str:
        """Format input data as prompt string for audit"""
        lines = [f"Agent: {self.role.value}"]
        lines.append(f"Operation: {self._get_operation_name()}")

        if "task" in input_data:
            task = input_data["task"]
            lines.append(f"\nTask: {getattr(task, 'name', 'N/A')}")
            lines.append(f"Description: {getattr(task, 'description', 'N/A')}")

        if "module" in input_data:
            lines.append(f"\nModule: {input_data['module']}")

        return "\n".join(lines)

    def load_context(
        self,
        task_id: Optional[str] = None,
        module: Optional[str] = None,
        include_code: bool = True
    ) -> dict[str, str]:
        """Load deterministic context"""
        return self.context_loader.load_context(
            task_id=task_id,
            module=module,
            include_code=include_code
        )

    def read_document(
        self,
        doc_type: str,
        doc_id: Optional[str] = None,
        module: Optional[str] = None
    ) -> Optional[Document]:
        """Read a document from wiki"""
        from cogniforge.core.constants import DocumentType

        try:
            doc_type_enum = DocumentType(doc_type)
        except ValueError:
            return None

        return self.wiki_system.read_document(
            doc_type=doc_type_enum,
            doc_id=doc_id,
            module=module
        )

    def write_document(
        self,
        doc: Document,
        commit_message: Optional[str] = None
    ) -> None:
        """Write a document to wiki"""
        self._check_allowed_path(doc.path)
        self.wiki_system.write_document(doc, commit_message)

    def _check_allowed_path(self, path: str) -> None:
        """Check if path is in allowed modification paths"""
        allowed = self.definition.allowed_modify
        if not allowed:
            raise AgentError(f"Agent {self.role.value} is not allowed to modify any paths")

        # Normalize path
        path = path.replace("\\", "/")

        for allowed_path in allowed:
            allowed_path = allowed_path.replace("\\", "/")
            if path.startswith(allowed_path):
                return

        raise AgentError(
            f"Agent {self.role.value} is not allowed to modify {path}. "
            f"Allowed paths: {allowed}"
        )

    def format_result(
        self,
        status: str,
        message: str = "",
        artifacts: list[str] = None,
        data: dict = None,
        reasoning: str = "",
        decisions: list[str] = None
    ) -> dict:
        """Format agent execution result"""
        return {
            "status": status,
            "message": message,
            "artifacts": artifacts or [],
            "data": data or {},
            "agent": self.role.value,
            "reasoning": reasoning,
            "decisions": decisions or [],
        }
