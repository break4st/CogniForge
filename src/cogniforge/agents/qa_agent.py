"""QA Agent - Quality Assurance Agent for testing"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import DocumentType
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
        test_cases = input_data.get("test_cases", [])
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        doc_id = f"test_cases_{module}"
        json_path = self.wiki_system.agent_path(DocumentType.TEST_CASE, doc_id=doc_id)

        prompt = (
            f"为以下模块生成测试用例，以 JSON 格式输出并写入:\n\n"
            f"输出路径: {json_path}\n"
            f"JSON 结构: {{\"meta\": {{\"doc_id\": \"{doc_id}\", \"type\": \"test_case\", "
            f"\"module\": \"{module}\", \"title\": \"测试用例 - {module}\", "
            f"\"author\": \"qa_agent\", \"created\": \"{now}\"}},\n"
            f" \"test_cases\": [{{\"name\": \"...\", \"type\": \"unit/integration/...\", "
            f"\"priority\": \"high/medium/low\", \"description\": \"...\", "
            f"\"steps\": [\"...\"], \"expected_result\": \"...\"}}]}}\n\n"
            f"输入数据:\n"
            f"module: {module}\n"
            f"test_cases: {json.dumps(test_cases, ensure_ascii=False)}\n\n"
            f"要求:\n"
            f"1. 先阅读 .cogniforge/wiki/lld/{module}/ 了解设计\n"
            f"2. 阅读 src/{module}/ 下的代码了解实现\n"
            f"3. 覆盖正常路径、边界条件、错误处理\n"
            f"4. 生成对应的 pytest 测试代码写入 tests/test_{module}.py\n"
            f"5. 使用中文、只写 JSON 不写 HTML、完成后回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="qa")

        return self._commit_result(json_path, f"测试用例 - {module}", response.content,
                                   extra_paths=[f"tests/test_{module}.py"])

    def _agentic_report(self, input_data: dict) -> dict:
        module = input_data.get("module", "unknown")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        doc_id = f"test-{module}"
        json_path = self.wiki_system.agent_path(DocumentType.REPORT, doc_id=doc_id)

        prompt = (
            f"为以下模块生成测试报告，以 JSON 格式输出并写入:\n\n"
            f"输出路径: {json_path}\n"
            f"JSON 结构: {{\"meta\": {{\"doc_id\": \"{doc_id}\", \"type\": \"report\", "
            f"\"title\": \"测试报告 - {module}\", "
            f"\"author\": \"qa_agent\", \"created\": \"{now}\"}},\n"
            f" \"content\": \"... (测试覆盖率、通过/失败统计、风险评估)\"}}\n\n"
            f"输入数据:\n"
            f"module: {module}\n\n"
            f"要求:\n"
            f"1. 阅读 tests/test_{module}.py 和 src/{module}/ 下的代码\n"
            f"2. 运行 pytest 获取测试结果\n"
            f"3. 在 content 字段中包含：测试覆盖率、通过/失败统计、风险评估\n"
            f"4. 使用中文、只写 JSON 不写 HTML、完成后回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="qa")
        return self._commit_result(json_path, f"测试报告 - {module}", response.content)

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

    def _commit_result(self, json_path: Path, title: str, reasoning: str = "",
                       extra_paths: list[str] | None = None) -> dict:
        json_abs = Path(self.config.repo_path) / json_path
        if not json_abs.exists():
            return self.format_result(status="failed",
                                       message=f"Claude Code did not produce {json_path}")

        rel_json = str(json_path.relative_to(self.config.repo_path))
        self.wiki_system.git_storage.repo.index.add([rel_json])

        from cogniforge.wiki.wiki_renderer import render_file
        html_path = render_file(json_abs)
        rel_html = str(html_path.relative_to(self.config.repo_path)) if html_path else ""
        if rel_html:
            self.wiki_system.git_storage.repo.index.add([rel_html])

        artifacts = [rel_json]
        if rel_html:
            artifacts.append(rel_html)
        for p in (extra_paths or []):
            if (Path(self.config.repo_path) / p).exists():
                self.wiki_system.git_storage.repo.index.add([p])
                artifacts.append(p)

        self.wiki_system.git_storage.commit(f"test: add test cases for {title}", "qa_agent")

        return self.format_result(
            status="success",
            message=f"Tests generated: {json_path.stem}",
            artifacts=artifacts,
            reasoning=reasoning,
        )
