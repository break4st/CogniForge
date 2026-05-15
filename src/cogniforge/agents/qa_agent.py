"""QA Agent - Quality Assurance Agent"""

import subprocess
from typing import Optional

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.models.document import Document


class QAAgent(BaseAgent):
    """
    QA Agent - Quality Assurance.

    Responsibilities:
    - Write test cases
    - Execute tests
    - Generate test reports
    """

    def run(self, input_data: dict) -> dict:
        """
        Execute QA activities.

        Args:
            input_data: {
                "action": str,  # "generate_tests", "execute_tests", "report"
                "module": str,
                "test_cases": list[dict],  # For generate_tests
            }
        """
        action = input_data.get("action", "execute_tests")
        module = input_data.get("module", "unknown")

        if action == "generate_tests":
            return self._generate_tests(input_data)
        elif action == "execute_tests":
            return self._execute_tests(input_data)
        elif action == "report":
            return self._generate_test_report(input_data)
        else:
            return self.format_result(
                status="failed",
                message=f"Unknown action: {action}"
            )

    def _generate_tests(self, input_data: dict) -> dict:
        """Generate test cases"""
        try:
            module = input_data.get("module", "unknown")
            test_cases = input_data.get("test_cases", [])

            content = self._format_test_cases(module, test_cases)

            doc = Document(
                doc_id=f"test-{module}",
                doc_type=DocumentType.TEST_CASE,
                title=f"Test Cases - {module}",
                content=content,
                path=f".cogniforge/wiki/qa/test_cases.md",
                author="qa_agent",
                metadata={"module": module, "count": len(test_cases)}
            )

            # Write test cases to wiki
            self.write_document(doc, f"feat: add test cases for {module}")

            # Also write actual test file
            self._write_test_file(module, test_cases)

            return self.format_result(
                status="success",
                message=f"Generated {len(test_cases)} test cases for {module}",
                artifacts=[doc.path, f"tests/test_{module}.py"],
                data={"count": len(test_cases)}
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )

    def _write_test_file(self, module: str, test_cases: list) -> None:
        """Write test file"""
        test_path = self.config.repo_path / "tests" / f"test_{module}.py"
        test_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            f'"""Tests for {module} module"""',
            "",
            "import pytest",
            "",
            "",
        ]

        for i, tc in enumerate(test_cases, 1):
            test_name = tc.get("name", f"test_case_{i}").replace(" ", "_").lower()
            lines.append(f"def test_{test_name}():")
            lines.append(f'    """{tc.get("description", "")}"""')
            lines.append("    # TODO: Implement test")
            lines.append("    pass")
            lines.append("")

        test_path.write_text("\n".join(lines), encoding="utf-8")

        self.git_storage.repo.index.add([f"tests/test_{module}.py"])

    def _format_test_cases(self, module: str, test_cases: list) -> str:
        """Format test cases document"""
        lines = [
            f"# Test Cases - {module}",
            "",
            f"**Total**: {len(test_cases)} test cases",
            "",
            "---",
            ""
        ]

        for i, tc in enumerate(test_cases, 1):
            lines.append(f"\n## {i}. {tc.get('name', f'Test Case {i}')}")
            lines.append(f"\n**Type**: {tc.get('type', 'Functional')}")
            lines.append(f"\n**Priority**: {tc.get('priority', 'Medium')}")
            lines.append(f"\n### Description\n\n{tc.get('description', '')}")
            lines.append(f"\n### Preconditions\n\n{tc.get('preconditions', 'None')}")
            lines.append(f"\n### Test Steps\n")

            for j, step in enumerate(tc.get('steps', []), 1):
                lines.append(f"{j}. {step}")

            lines.append(f"\n### Expected Result\n\n{tc.get('expected_result', '')}")

        return "\n".join(lines)

    def _execute_tests(self, input_data: dict) -> dict:
        """Execute tests"""
        try:
            module = input_data.get("module", "unknown")

            result = subprocess.run(
                ["pytest", "-v", "--tb=short", f"tests/test_{module}.py"],
                capture_output=True,
                text=True,
                cwd=str(self.config.repo_path)
            )

            passed = result.returncode == 0

            return self.format_result(
                status="success" if passed else "failed",
                message=f"Tests {'PASSED' if passed else 'FAILED'} for {module}",
                data={
                    "passed": passed,
                    "output": result.stdout,
                    "error": result.stderr
                }
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )

    def _generate_test_report(self, input_data: dict) -> dict:
        """Generate test execution report"""
        try:
            module = input_data.get("module", "unknown")
            test_results = input_data.get("results", {})

            content = f"# Test Report - {module}\n\n"
            content += f"**Status**: {test_results.get('passed', False) and 'PASS' or 'FAIL'}\n\n"
            content += f"```\n{test_results.get('output', 'No output')}\n```\n"

            if test_results.get("error"):
                content += f"\n## Errors\n\n```\n{test_results['error']}\n```\n"

            doc_id = f"test-report-{module}"
            doc = Document(
                doc_id=doc_id,
                doc_type=DocumentType.REPORT,
                title=f"Test Report - {module}",
                content=content,
                path=f".cogniforge/wiki/reports/{doc_id}.md",
                author="qa_agent",
                metadata={"module": module, "passed": test_results.get("passed", False)}
            )

            self.write_document(doc, f"docs: test report for {module}")

            return self.format_result(
                status="success",
                message=f"Test report generated for {module}",
                artifacts=[doc.path]
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )
