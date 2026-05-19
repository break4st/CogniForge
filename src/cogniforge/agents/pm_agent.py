"""PM Agent - Product Manager Agent for PRD creation"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.core.exceptions import AgentError


class PMAgent(BaseAgent):
    """PM Agent — delegates to Claude Code agent to generate the PRD JSON
    (Agent Format), then WikiRenderer auto-generates User Format HTML."""

    def run(self, input_data: dict) -> dict:
        try:
            if self.agent is None:
                raise AgentError("PMAgent requires a Claude Code agent")

            title = input_data.get("title", "未命名PRD")
            overview = input_data.get("overview", "")
            requirements = input_data.get("requirements", [])
            user_stories = input_data.get("user_stories", [])
            priorities = input_data.get("priorities", {})

            existing = self.wiki_system.list_documents(DocumentType.PRD)
            seq = len(existing) + 1
            doc_id = f"prd-{seq:03d}"

            return self._run_agentic(
                title, overview, requirements, user_stories, priorities, doc_id,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _run_agentic(
        self, title, overview, requirements, user_stories, priorities, doc_id: str,
    ) -> dict:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        json_path = self.wiki_system.agent_path(DocumentType.PRD, doc_id=doc_id)

        prompt = (
            f"根据以下数据创建一份产品需求文档 (PRD)，以 JSON 格式输出并写入指定文件。\n\n"
            f"项目名称: {title}\n"
            f"项目概述: {overview}\n"
            f"功能需求: {json.dumps(requirements, ensure_ascii=False)}\n"
            f"用户故事: {json.dumps(user_stories, ensure_ascii=False)}\n"
            f"优先级: {json.dumps(priorities, ensure_ascii=False)}\n\n"
            f"输出 JSON 结构:\n"
            f'{{"meta": {{"doc_id": "{doc_id}", "type": "prd", '
            f'"title": "{title}", "author": "pm_agent", "created": "{now}", '
            f'"version": 1}},\n'
            f' "overview": "项目概述文本",\n'
            f' "requirements": [{{"name": "需求名", "description": "描述", '
            f'"acceptance_criteria": ["条件1", "条件2"]}}],\n'
            f' "user_stories": [{{"role": "角色", "action": "动作", "goal": "目标"}}],\n'
            f' "priorities": {{"需求名": "高/中/低"}}\n'
            f"}}\n\n"
            f"要求:\n"
            f"1. 先阅读 DESIGN.html 了解项目视觉风格\n"
            f"2. 将完整的 JSON 写入: {json_path}\n"
            f"3. 所有文字使用中文\n"
            f"4. 不要写入 .html 文件（HTML 由系统自动渲染）\n"
            f"5. 完成后用中文回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="pm")

        json_abs = Path(self.config.repo_path) / json_path
        if json_abs.exists():
            # Render user-facing HTML from the JSON
            self.wiki_system.git_storage.repo.index.add(
                [str(json_path.relative_to(self.config.repo_path))]
            )
            from cogniforge.wiki.wiki_renderer import render_file
            html_path = render_file(json_abs)
            html_rel = str(html_path.relative_to(self.config.repo_path)) if html_path else ""
            if html_rel:
                self.wiki_system.git_storage.repo.index.add([html_rel])

            self.wiki_system.git_storage.commit(
                f"feat: add PRD - {title}", "pm_agent"
            )

            artifacts = [str(json_path.relative_to(self.config.repo_path))]
            if html_rel:
                artifacts.append(html_rel)

            return self.format_result(
                status="success",
                message=f"PRD created: {doc_id}",
                artifacts=artifacts,
                reasoning=response.content,
            )
        else:
            return self.format_result(
                status="failed",
                message=f"Claude Code did not produce {json_path}",
            )
