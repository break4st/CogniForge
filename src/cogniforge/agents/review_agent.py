"""Review Agent - Code Review Agent"""

from typing import Optional

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.models.document import Document


class ReviewAgent(BaseAgent):
    """
    Review Agent - Code Reviewer.

    Responsibilities:
    - Review code changes
    - Generate CR reports
    - Ensure quality gates pass
    """

    def run(self, input_data: dict) -> dict:
        """
        Perform code review.

        Args:
            input_data: {
                "module": str,
                "files": list[str],  # Files to review
                "cr_report": str,  # Optional: pre-generated CR
            }
        """
        try:
            module = input_data.get("module", "unknown")
            files = input_data.get("files", [])
            cr_report = input_data.get("cr_report", "")

            # Load context for review
            context = self.load_context(module=module, include_code=True)

            # Generate or use provided CR report
            if not cr_report:
                cr_report = self._generate_cr_report(module, files, context)

            # Evaluate quality
            quality_checks = self._evaluate_quality(cr_report, files)
            all_passed = all(c["passed"] for c in quality_checks)

            # Create CR report document
            content = self._format_cr_report(module, files, cr_report, quality_checks)

            doc_id = f"cr-{module}"
            doc = Document(
                doc_id=doc_id,
                doc_type=DocumentType.REPORT,
                title=f"Code Review Report - {module}",
                content=content,
                path=f".cogniforge/wiki/reports/{doc_id}.md",
                author="review_agent",
                metadata={"module": module, "passed": all_passed, "files": files}
            )

            self.write_document(doc, f"feat: code review for {module}")

            return self.format_result(
                status="success" if all_passed else "failed",
                message=f"CR {'PASSED' if all_passed else 'FAILED'} for {module}",
                artifacts=[doc.path],
                data={"checks": quality_checks, "all_passed": all_passed}
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )

    def _generate_cr_report(self, module: str, files: list, context: dict) -> str:
        """Generate code review report using context"""
        # In real implementation, this would use LLM
        report = f"# Code Review for {module}\n\n"
        report += f"**Files reviewed**: {len(files)}\n\n"

        for file in files:
            report += f"\n## {file}\n"
            if file in context:
                report += f"Content length: {len(context[file])} characters\n"
            report += "- No issues found\n"

        return report

    def _evaluate_quality(self, cr_report: str, files: list) -> list:
        """Evaluate code quality"""
        checks = []

        # Check 1: Files reviewed
        checks.append({
            "check": "files_reviewed",
            "description": "All files have been reviewed",
            "passed": len(files) > 0
        })

        # Check 2: CR report exists
        checks.append({
            "check": "report_generated",
            "description": "CR report has been generated",
            "passed": len(cr_report) > 0
        })

        # Check 3: No critical issues (placeholder)
        checks.append({
            "check": "no_critical_issues",
            "description": "No critical issues in code",
            "passed": "CRITICAL" not in cr_report.upper()
        })

        return checks

    def _format_cr_report(
        self,
        module: str,
        files: list,
        cr_report: str,
        quality_checks: list
    ) -> str:
        """Format CR report"""
        lines = [
            f"# Code Review Report - {module}",
            "",
            f"**Files reviewed**: {', '.join(files)}",
            "",
            "---",
            "",
            cr_report,
            "",
            "---",
            "",
            "## Quality Checks",
            ""
        ]

        for check in quality_checks:
            status = "PASS" if check["passed"] else "FAIL"
            lines.append(f"- [{status}] {check['description']}")

        return "\n".join(lines)
