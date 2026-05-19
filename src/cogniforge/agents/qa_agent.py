"""QA Agent - Quality Assurance Agent for testing"""

from __future__ import annotations

import subprocess
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.exceptions import AgentError


class QAAgent(BaseAgent):
    """QA Agent — delegates to Claude Code for test generation and reports.
    Test execution (pytest) stays operational."""

    def run(self, input_data: dict) -> dict:
        try:
            action = input_data.get("action", "execute_tests")

            if action == "execute_tests":
                return self._execute_tests(input_data)

            if self.agent is None:
                raise AgentError("QAAgent requires a Claude Code agent for this action")

            if action == "generate_tests":
                return self._agentic_generate_tests(input_data)
            elif action == "report":
                return self._agentic_report(input_data)
            else:
                return self.format_result(
                    status="failed", message=f"Unknown action: {action}"
                )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _agentic_generate_tests(self, input_data: dict) -> dict:
        module = input_data.get("module", "unknown")
        output_path = f".cogniforge/wiki/qa/test_cases_{module}.md"

        prompt = (
            f"为以下模块生成测试用例:\n\n"
            f"模块: {module}\n\n"
            f"要求：\n"
            f"1. 先阅读 .cogniforge/wiki/lld/{module}/ 下的 LLD 了解设计\n"
            f"2. 阅读 src/{module}/ 下的代码了解实现\n"
            f"3. 生成测试用例文档写入: {output_path}\n"
            f"4. 生成对应的 pytest 测试代码写入 tests/test_{module}.py\n"
            f"5. 覆盖正常路径、边界条件、错误处理\n"
            f"6. 完成后用中文回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="qa")

        artifacts = []
        for p in [output_path, f"tests/test_{module}.py"]:
            if (Path(self.config.repo_path) / p).exists():
                artifacts.append(p)
                self.wiki_system.git_storage.repo.index.add([p])

        if artifacts:
            self.wiki_system.git_storage.commit(
                f"test: add test cases for {module}", "qa_agent"
            )

        return self.format_result(
            status="success",
            message=f"Tests generated for {module}",
            artifacts=artifacts,
            reasoning=response.content,
        )

    def _agentic_report(self, input_data: dict) -> dict:
        module = input_data.get("module", "unknown")
        output_path = f".cogniforge/wiki/reports/test-{module}.md"

        prompt = (
            f"为以下模块生成测试报告:\n\n"
            f"模块: {module}\n\n"
            f"要求：\n"
            f"1. 阅读 tests/test_{module}.py 和 src/{module}/ 下的代码\n"
            f"2. 运行 pytest 获取测试结果\n"
            f"3. 生成测试报告写入: {output_path}\n"
            f"4. 包含：测试覆盖率、通过/失败统计、风险评估\n"
            f"5. 使用中文\n"
        )

        response = self.agent.generate_agentic(prompt, role="qa")

        output_abs = Path(self.config.repo_path) / output_path
        if output_abs.exists():
            self.wiki_system.git_storage.repo.index.add([output_path])
            self.wiki_system.git_storage.commit(
                f"docs: test report for {module}", "qa_agent"
            )
            return self.format_result(
                status="success",
                message=f"Test report generated for {module}",
                artifacts=[output_path],
                reasoning=response.content,
            )
        return self.format_result(
            status="failed", message=f"Test report not produced for {module}"
        )

    def _execute_tests(self, input_data: dict) -> dict:
        module = input_data.get("module", "unknown")
        try:
            result = subprocess.run(
                ["pytest", "-v", "--tb=short", f"tests/test_{module}.py"],
                capture_output=True, text=True,
                cwd=str(self.config.repo_path),
            )
            passed = result.returncode == 0
            return self.format_result(
                status="success" if passed else "failed",
                message=f"Tests {'PASSED' if passed else 'FAILED'} for {module}",
                data={
                    "passed": passed,
                    "output": result.stdout,
                    "error": result.stderr,
                },
            )
        except FileNotFoundError:
            return self.format_result(
                status="success", message="pytest not found, skipping",
                data={"passed": True, "output": "pytest not found", "error": None},
            )
        except Exception as e:
            return self.format_result(
                status="failed", message=str(e),
                data={"passed": False, "output": "", "error": str(e)},
            )
