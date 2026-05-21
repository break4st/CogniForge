"""Tech Lead Agent - Schedules tasks and governs execution"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import DocumentType, TaskPriority
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
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        task_id = f"wbs_{module}"
        json_path = self.wiki_system.agent_path(DocumentType.TASK, task_id=task_id)

        prompt = (
            f"根据以下信息创建工作分解结构 (WBS)，以 JSON 格式输出并写入:\n\n"
            f"输出路径: {json_path}\n"
            f"JSON 结构: {{\"meta\": {{\"doc_id\": \"{task_id}\", \"type\": \"task\", "
            f"\"title\": \"WBS - {module}\", "
            f"\"author\": \"techlead_agent\", \"created\": \"{now}\"}},\n"
            f" \"tasks\": [{{\"name\": \"...\", \"description\": \"...\", "
            f"\"deps\": [\"...\"], \"priority\": 1, \"assignee\": \"dev\", "
            f"\"estimated_hours\": 4, \"category\": \"service\"}}]}}\n\n"
            f"输入数据:\n"
            f"module: {module}\n"
            f"tasks: {json.dumps(tasks, ensure_ascii=False, indent=2)}\n\n"
            f"要求:\n"
            f"1. 先阅读 .cogniforge/wiki/prd/、.cogniforge/wiki/sad/、.cogniforge/wiki/lld/{module}/ 了解上下文\n"
            f"2. 每个任务粒度: 2-8 小时，对应一个可验证的产出物 (文件、函数、API 端点、测试套件)\n"
            f"3. 按依赖关系拓扑排序，标注优先级 (0=阻塞 1=高 2=中 3=低) 和预估工时\n"
            f"4. 每个任务必须指定 category: model | service | endpoint | test | config | migration | doc | fix\n"
            f"5. 使用中文、只写 JSON 不写 HTML、完成后回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="techlead")

        # Read back the generated WBS JSON and create individual tasks
        if hasattr(self, "task_engine") and json_path.exists():
            try:
                wbs_data = json.loads(json_path.read_text(encoding="utf-8"))
                wbs_tasks = wbs_data.get("tasks", [])
                for i, t in enumerate(wbs_tasks):
                    try:
                        self.task_engine.create_task(
                            name=t.get("name", f"task-{i}"),
                            module=module,
                            description=t.get("description", ""),
                            deps=t.get("deps", []),
                            priority=TaskPriority(t.get("priority", 2)),
                            assignee=t.get("assignee"),
                            estimated_hours=t.get("estimated_hours"),
                            category=t.get("category"),
                        )
                    except Exception:
                        pass
            except (json.JSONDecodeError, IOError):
                pass

        return self._commit_result(json_path, f"WBS - {module}", "techlead_agent",
                                   f"feat: add WBS for {module}", response.content)

    def _agentic_evaluate_quality(self, input_data: dict) -> dict:
        module = input_data.get("module", "unknown")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        doc_id = f"quality-{module}"
        json_path = self.wiki_system.agent_path(DocumentType.REPORT, doc_id=doc_id)

        prompt = (
            f"评估以下模块的质量门禁，以 JSON 格式输出并写入:\n\n"
            f"输出路径: {json_path}\n"
            f"JSON 结构: {{\"meta\": {{\"doc_id\": \"{doc_id}\", \"type\": \"report\", "
            f"\"title\": \"质量评估 - {module}\", "
            f"\"author\": \"techlead_agent\", \"created\": \"{now}\"}},\n"
            f" \"content\": \"... (包含 PASS/FAIL 结论及各检查项结果)\"}}\n\n"
            f"输入数据:\n"
            f"module: {module}\n\n"
            f"要求:\n"
            f"1. 阅读该模块的 LLD、代码、CR 报告、测试报告\n"
            f"2. 检查：CR 是否通过、测试是否通过、代码是否符合设计\n"
            f"3. 在 content 字段中明确给出 PASS/FAIL 结论\n"
            f"4. 使用中文、只写 JSON 不写 HTML、完成后回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="techlead")
        return self._commit_result(json_path, f"质量评估 - {module}", "techlead_agent",
                                   f"docs: quality evaluation for {module}", response.content)

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

    def _commit_result(self, json_path: Path, title: str, author: str,
                       commit_msg: str, reasoning: str = "") -> dict:
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

        self.wiki_system.git_storage.commit(commit_msg, author)

        return self.format_result(
            status="success",
            message=f"Document created: {json_path.stem}",
            artifacts=artifacts,
            reasoning=reasoning,
        )
