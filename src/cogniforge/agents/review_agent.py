"""Review Agent - Code Review Agent"""

from __future__ import annotations

from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.exceptions import AgentError


class ReviewAgent(BaseAgent):
    """Review Agent — delegates to Claude Code agent to review code
    and generate CR reports."""

    def run(self, input_data: dict) -> dict:
        try:
            if self.agent is None:
                raise AgentError("ReviewAgent requires a Claude Code agent")

            module = input_data.get("module", "unknown")
            files = input_data.get("files", [])

            return self._run_agentic(module, files)

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _run_agentic(self, module: str, files: list) -> dict:
        doc_id = f"cr-{module}"
        output_path = f".cogniforge/wiki/reports/{doc_id}.md"

        prompt = (
            f"对以下模块进行代码评审:\n\n"
            f"模块: {module}\n"
            f"文件: {', '.join(files) if files else '所有变更文件'}\n\n"
            f"要求：\n"
            f"1. 先阅读 .cogniforge/wiki/lld/{module}/ 下的 LLD 了解设计意图\n"
            f"2. 阅读相关代码文件\n"
            f"3. 检查：代码是否符合设计、是否安全、是否简洁\n"
            f"4. 检查 CLAUDE.md 中列出的行为准则是否被遵守\n"
            f"5. 生成 CR 报告写入: {output_path}\n"
            f"6. 报告中使用 PASS/FAIL 标注每项检查\n"
            f"7. 使用中文\n"
        )

        response = self.agent.generate_agentic(prompt, role="reviewer")

        output_abs = Path(self.config.repo_path) / output_path
        if output_abs.exists():
            self.wiki_system.git_storage.repo.index.add([output_path])
            self.wiki_system.git_storage.commit(
                f"feat: code review for {module}", "review_agent"
            )
            return self.format_result(
                status="success",
                message=f"CR completed for {module}",
                artifacts=[output_path],
                reasoning=response.content,
            )
        return self.format_result(
            status="failed", message=f"CR report not produced for {module}"
        )
