"""Audit log - records all AI operations for human review"""

from datetime import datetime
from typing import Optional, Any
from dataclasses import dataclass, field
from pathlib import Path
import json

from cogniforge.core.config import Config


@dataclass
class AuditEntry:
    """Single audit log entry"""

    # Who/What
    agent_role: str
    operation: str

    # When
    timestamp: datetime = field(default_factory=datetime.now)

    # Input (what was given to AI)
    input_context: dict = field(default_factory=dict)
    input_prompt: str = ""

    # Output (what AI produced)
    output_artifacts: list[str] = field(default_factory=list)
    output_summary: str = ""

    # Decision/Reasoning
    reasoning: str = ""
    decisions: list[str] = field(default_factory=list)

    # Metadata
    duration_ms: int = 0
    status: str = "success"  # success, failed, partial
    error: Optional[str] = None

    # Human review
    reviewed: bool = False
    reviewer: str = ""
    review_comment: str = ""
    review_timestamp: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "agent_role": self.agent_role,
            "operation": self.operation,
            "timestamp": self.timestamp.isoformat(),
            "input_context": self.input_context,
            "input_prompt": self.input_prompt,
            "output_artifacts": self.output_artifacts,
            "output_summary": self.output_summary,
            "reasoning": self.reasoning,
            "decisions": self.decisions,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "reviewed": self.reviewed,
            "reviewer": self.reviewer,
            "review_comment": self.review_comment,
            "review_timestamp": self.review_timestamp.isoformat() if self.review_timestamp else None,
        }


class AuditLog:
    """
    Audit log for tracking all AI operations.

    All AI outputs must be reviewable by humans.
    Each operation is recorded with input, output, and reasoning.
    """

    def __init__(self, config: Config):
        self.config = config
        self.entries: list[AuditEntry] = []
        self._audit_dir = config.repo_path / ".cogniforge" / "wiki" / "reports" / "audit"
        self._ensure_audit_dir()

    def _ensure_audit_dir(self) -> None:
        """Ensure audit directory exists"""
        self._audit_dir.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        agent_role: str,
        operation: str,
        input_context: dict = None,
        input_prompt: str = "",
        output_artifacts: list = None,
        output_summary: str = "",
        reasoning: str = "",
        decisions: list = None,
        duration_ms: int = 0,
        status: str = "success",
        error: str = None
    ) -> AuditEntry:
        """
        Log an AI operation.

        Args:
            agent_role: Role of the agent (e.g., "dev", "qa")
            operation: Operation performed (e.g., "generate_code", "write_prd")
            input_context: Context provided to AI (documents, task, etc.)
            input_prompt: Prompt sent to AI
            output_artifacts: Files produced by AI
            output_summary: Summary of AI output
            reasoning: AI's reasoning/decision process
            decisions: Key decisions made by AI
            duration_ms: Operation duration
            status: Operation status
            error: Error message if failed

        Returns:
            Created audit entry
        """
        entry = AuditEntry(
            agent_role=agent_role,
            operation=operation,
            input_context=input_context or {},
            input_prompt=input_prompt,
            output_artifacts=output_artifacts or [],
            output_summary=output_summary,
            reasoning=reasoning,
            decisions=decisions or [],
            duration_ms=duration_ms,
            status=status,
            error=error
        )

        self.entries.append(entry)
        self._save_entry(entry)

        return entry

    def _save_entry(self, entry: AuditEntry) -> None:
        """Save entry to disk"""
        # Create filename from timestamp and operation
        timestamp_str = entry.timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp_str}_{entry.agent_role}_{entry.operation}.json"
        filepath = self._audit_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(entry.to_dict(), f, indent=2, ensure_ascii=False)

    def mark_reviewed(
        self,
        entry_index: int,
        reviewer: str,
        comment: str
    ) -> bool:
        """
        Mark an audit entry as reviewed by human.

        Args:
            entry_index: Index of entry in self.entries
            reviewer: Name/ID of reviewer
            comment: Review comment

        Returns:
            True if successful
        """
        if entry_index < 0 or entry_index >= len(self.entries):
            return False

        entry = self.entries[entry_index]
        entry.reviewed = True
        entry.reviewer = reviewer
        entry.review_comment = comment
        entry.review_timestamp = datetime.now()

        # Update the file
        self._save_entry(entry)

        return True

    def get_unreviewed(self) -> list[AuditEntry]:
        """Get all unreviewed entries"""
        return [e for e in self.entries if not e.reviewed]

    def get_by_agent(self, agent_role: str) -> list[AuditEntry]:
        """Get all entries for a specific agent role"""
        return [e for e in self.entries if e.agent_role == agent_role]

    def get_by_operation(self, operation: str) -> list[AuditEntry]:
        """Get all entries for a specific operation"""
        return [e for e in self.entries if e.operation == operation]

    def generate_review_report(self) -> str:
        """
        Generate a human-readable review report of all AI outputs.

        Returns:
            Markdown formatted report
        """
        lines = [
            "# AI 输出审核报告",
            "",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"总操作数: {len(self.entries)}",
            f"已审核: {len([e for e in self.entries if e.reviewed])}",
            f"待审核: {len(self.get_unreviewed())}",
            "",
            "---",
            ""
        ]

        # Unreviewed entries first
        unreviewed = self.get_unreviewed()
        if unreviewed:
            lines.extend([
                "## 待审核项",
                ""
            ])
            for i, entry in enumerate(unreviewed):
                lines.extend(self._format_entry(entry, self.entries.index(entry)))
            lines.append("")

        # Reviewed entries
        reviewed = [e for e in self.entries if e.reviewed]
        if reviewed:
            lines.extend([
                "## 已审核项",
                ""
            ])
            for entry in reviewed:
                lines.extend(self._format_entry(entry, self.entries.index(entry)))
            lines.append("")

        return "\n".join(lines)

    def _format_entry(self, entry: AuditEntry, index: int) -> list[str]:
        """Format single entry for report"""
        lines = [
            f"### [{index}] {entry.agent_role} - {entry.operation}",
            "",
            f"**时间**: {entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**状态**: {entry.status}",
            f"**耗时**: {entry.duration_ms}ms",
            "",
        ]

        if entry.input_context:
            lines.extend([
                "**输入上下文**:",
                "```json",
                json.dumps(entry.input_context, indent=2, ensure_ascii=False),
                "```",
                ""
            ])

        if entry.input_prompt:
            lines.extend([
                "**输入 Prompt**:",
                "```",
                entry.input_prompt[:500] + "..." if len(entry.input_prompt) > 500 else entry.input_prompt,
                "```",
                ""
            ])

        if entry.output_artifacts:
            lines.append(f"**产出文件**: {', '.join(entry.output_artifacts)}")
            lines.append("")

        if entry.output_summary:
            lines.extend([
                "**输出摘要**:",
                entry.output_summary[:500] + "..." if len(entry.output_summary) > 500 else entry.output_summary,
                ""
            ])

        if entry.reasoning:
            lines.extend([
                "**AI 推理过程**:",
                entry.reasoning[:500] + "..." if len(entry.reasoning) > 500 else entry.reasoning,
                ""
            ])

        if entry.decisions:
            lines.extend([
                "**关键决策**:",
            ])
            for decision in entry.decisions:
                lines.append(f"- {decision}")
            lines.append("")

        if entry.status == "failed" and entry.error:
            lines.extend([
                "**错误**:",
                f"```\n{entry.error}\n```",
                ""
            ])

        lines.extend([
            f"**已审核**: {'✓ 是' if entry.reviewed else '✗ 否'}",
        ])

        if entry.reviewed:
            lines.extend([
                f"**审核人**: {entry.reviewer}",
                f"**审核意见**: {entry.review_comment}",
            ])

        lines.append("")
        return lines

    def save_review_report(self) -> Path:
        """Save review report to file and return path"""
        report = self.generate_review_report()
        report_path = self._audit_dir / "review_report.md"
        report_path.write_text(report, encoding="utf-8")
        return report_path
