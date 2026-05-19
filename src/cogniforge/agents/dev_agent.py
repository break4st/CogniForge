"""Dev Agent - Developer Agent for code implementation"""

from __future__ import annotations

from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.exceptions import AgentError


class DevAgent(BaseAgent):
    """Dev Agent — delegates to Claude Code agent to read LLD + context,
    write code, and run tests end-to-end."""

    def run(self, input_data: dict) -> dict:
        try:
            if self.agent is None:
                raise AgentError("DevAgent requires a Claude Code agent")

            task = input_data.get("task")
            module = input_data.get("module", task.module if task else "unknown")
            code = input_data.get("code", "")

            # If code is already provided, write it directly (operational)
            if code:
                return self._write_direct(module, task, code)

            return self._run_agentic(task, module)

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _run_agentic(self, task, module: str) -> dict:
        task_name = task.name if task else module
        task_desc = getattr(task, "description", "") if task else ""

        prompt = (
            f"实现以下开发任务：\n\n"
            f"模块: {module}\n"
            f"任务: {task_name}\n"
            f"描述: {task_desc}\n\n"
            f"要求：\n"
            f"1. 先阅读 .cogniforge/wiki/lld/{module}/ 下的 LLD 了解详细设计\n"
            f"2. 编写代码到 src/{module}/ 目录\n"
            f"3. 遵循 Python 最佳实践，使用 type hints\n"
            f"4. 编写对应的单元测试到 tests/ 目录\n"
            f"5. 代码写完后运行 pytest 验证\n"
            f"6. 完成后用中文回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="dev")

        code_dir = Path(self.config.repo_path) / "src" / module
        artifacts = [
            str(p.relative_to(self.config.repo_path))
            for p in code_dir.rglob("*.py")
        ] if code_dir.exists() else []

        return self.format_result(
            status="success",
            message=f"Code generated for {module}",
            artifacts=artifacts,
            reasoning=response.content,
        )

    def _write_direct(self, module: str, task, code: str) -> dict:
        module_path = self.config.repo_path / "src" / module
        module_path.mkdir(parents=True, exist_ok=True)
        filename = f"{module}_{task.name.replace('-', '_').replace(' ', '_')}.py" if task else f"{module}.py"
        file_path = module_path / filename
        file_path.write_text(code, encoding="utf-8")
        rel = f"src/{module}/{filename}"
        self.wiki_system.git_storage.repo.index.add([rel])
        return self.format_result(
            status="success", message=f"Code written: {rel}",
            artifacts=[rel],
        )
