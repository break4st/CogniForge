"""Tech Lead Agent - Schedules tasks and governs execution"""

from __future__ import annotations

import json
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.exceptions import AgentError


class TechLeadAgent(BaseAgent):
    """Tech Lead Agent — delegates WBS creation and quality evaluation to
    Claude Code agent.  Flow control decisions stay operational."""

    def run(self, input_data: dict) -> dict:
        try:
            action = input_data.get("action", "create_wbs")

            if action == "decide_next":
                return self._decide_next(input_data)

            if action == "control_flow":
                return self._control_flow(input_data)

            if self.agent is None:
                raise AgentError("TechLeadAgent requires a Claude Code agent for this action")

            if action == "create_wbs":
                return self._agentic_create_wbs(input_data)
            elif action == "evaluate_quality":
                return self._agentic_evaluate_quality(input_data)
            else:
                return self.format_result(
                    status="failed", message=f"Unknown action: {action}"
                )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _agentic_create_wbs(self, input_data: dict) -> dict:
        module = input_data.get("module", "unknown")
        tasks = input_data.get("tasks", [])
        output_path = f".cogniforge/wiki/tasks/wbs_{module}.md"

        prompt = (
            f"根据以下信息创建工作分解结构 (WBS):\n\n"
            f"模块: {module}\n"
            f"任务列表: {json.dumps(tasks, ensure_ascii=False, indent=2)}\n\n"
            f"要求：\n"
            f"1. 先阅读 .cogniforge/wiki/prd/、.cogniforge/wiki/sad/、.cogniforge/wiki/lld/{module}/ 了解上下文\n"
            f"2. 生成 WBS 文档写入: {output_path}\n"
            f"3. 按依赖关系排序，标注优先级和预估工时\n"
            f"4. 使用中文\n"
            f"5. 完成后用中文回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="techlead")

        artifacts = []
        output_abs = Path(self.config.repo_path) / output_path
        if output_abs.exists():
            artifacts.append(output_path)
            self.wiki_system.git_storage.repo.index.add([output_path])

        # Create tasks in task_engine if provided
        if hasattr(self, "task_engine"):
            for t in tasks:
                try:
                    self.task_engine.create_task(
                        name=t.get("name", "task"),
                        module=module,
                        description=t.get("description", ""),
                    )
                except Exception:
                    pass

        if artifacts:
            self.wiki_system.git_storage.commit(f"feat: add WBS for {module}", "techlead_agent")

        return self.format_result(
            status="success",
            message=f"WBS created for {module}",
            artifacts=artifacts,
            reasoning=response.content,
        )

    def _agentic_evaluate_quality(self, input_data: dict) -> dict:
        module = input_data.get("module", "unknown")
        output_path = f".cogniforge/wiki/reports/quality-{module}.md"

        prompt = (
            f"评估以下模块的质量门禁:\n\n"
            f"模块: {module}\n\n"
            f"要求：\n"
            f"1. 阅读该模块的 LLD、代码、CR 报告、测试报告\n"
            f"2. 检查：CR 是否通过、测试是否通过、代码是否符合设计\n"
            f"3. 生成质量评估报告写入: {output_path}\n"
            f"4. 明确给出 PASS/FAIL 结论\n"
            f"5. 使用中文\n"
        )

        response = self.agent.generate_agentic(prompt, role="techlead")

        output_abs = Path(self.config.repo_path) / output_path
        if output_abs.exists():
            self.wiki_system.git_storage.repo.index.add([output_path])
            self.wiki_system.git_storage.commit(
                f"docs: quality evaluation for {module}", "techlead_agent"
            )
            return self.format_result(
                status="success",
                message=f"Quality evaluation completed for {module}",
                artifacts=[output_path],
                reasoning=response.content,
            )
        return self.format_result(
            status="failed", message=f"Quality report not produced for {module}"
        )

    def _decide_next(self, input_data: dict) -> dict:
        return self.format_result(
            status="success",
            message="Decision deferred to Tech Lead",
            data={"next_action": "advance"},
        )

    def _control_flow(self, input_data: dict) -> dict:
        return self.format_result(
            status="success",
            message="Flow control active",
            data={"status": "ok"},
        )
