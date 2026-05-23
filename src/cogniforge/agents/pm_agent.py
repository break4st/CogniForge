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
                raise AgentError("PMAgent requires an LLM agent")

            existing = self.wiki_system.list_documents(DocumentType.PRD)
            seq = len(existing) + 1
            doc_id = f"prd-{seq:03d}"
            cb = input_data.pop("_progress_callback", None)

            # Raw NL mode: pass user's natural language directly to agent
            raw_text = input_data.get("raw_text", "")
            if raw_text:
                if cb:
                    cb("PM 正在分析需求，提取项目信息...")
                return self._run_agentic_raw(raw_text, doc_id, progress_callback=cb)

            # Structured mode (legacy wizard path)
            title = input_data.get("title", "未命名PRD")
            overview = input_data.get("overview", "")
            requirements = input_data.get("requirements", [])
            user_stories = input_data.get("user_stories", [])
            priorities = input_data.get("priorities", {})

            return self._run_agentic(
                title, overview, requirements, user_stories, priorities, doc_id,
                progress_callback=cb,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _run_agentic_raw(self, raw_text: str, doc_id: str,
                         progress_callback: callable = None) -> dict:
        """Generate PRD directly from the user's natural language."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        json_path = self.wiki_system.agent_path(DocumentType.PRD, doc_id=doc_id)

        prompt = (
            f"根据以下用户描述，创建一份完整的产品需求文档 (PRD)。\n"
            f"充分理解用户意图，提取项目名称、撰写详细概述、"
            f"梳理功能需求（含验收条件）、推导用户故事、标注优先级。\n\n"
            f"用户描述:\n{raw_text}\n\n"
            f"输出 JSON 结构:\n"
            f'{{"meta": {{"doc_id": "{doc_id}", "type": "prd", '
            f'"title": "...", "author": "pm_agent", "created": "{now}", '
            f'"version": 1}},\n'
            f' "overview": "项目概述文本（3-5句）",\n'
            f' "requirements": [{{"name": "需求名", "description": "描述", '
            f'"acceptance_criteria": ["条件1", "条件2"]}}],\n'
            f' "user_stories": [{{"role": "角色", "action": "动作", "goal": "目标"}}],\n'
            f' "priorities": {{"需求名": "高/中/低"}}\n'
            f"}}\n\n"
            f"要求:\n"
            f"1. 将完整的 JSON 写入: {json_path}\n"
            f"2. 所有文字使用中文\n"
            f"3. 不要写入 .html 文件（HTML 由系统自动渲染）\n"
            f"4. 完成后用中文回复确认"
        )

        response = self.agent.generate_agentic(
            prompt, role="pm", progress_callback=progress_callback,
        )
        return self._handle_result(response, json_path, doc_id)

    def _run_agentic(
        self, title, overview, requirements, user_stories, priorities, doc_id: str,
        progress_callback: callable = None,
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
            f"1. 将完整的 JSON 写入: {json_path}\n"
            f"2. 所有文字使用中文\n"
            f"3. 不要写入 .html 文件（HTML 由系统自动渲染）\n"
            f"4. 完成后用中文回复确认"
        )

        response = self.agent.generate_agentic(
            prompt, role="pm", progress_callback=progress_callback,
        )
        return self._handle_result(response, json_path, doc_id)

    def _handle_result(self, response, json_path: str, doc_id: str) -> dict:
        json_abs = Path(self.config.repo_path) / json_path
        if json_abs.exists():
            self.wiki_system.git_storage.repo.index.add(
                [json_path.relative_to(self.config.repo_path).as_posix()]
            )
            from cogniforge.wiki.wiki_renderer import render_file
            html_path = render_file(json_abs)
            html_rel = html_path.relative_to(self.config.repo_path).as_posix() if html_path else ""
            if html_rel:
                self.wiki_system.git_storage.repo.index.add([html_rel])

            # Extract title from generated JSON for commit message
            import json as _json
            try:
                data = _json.loads(json_abs.read_text(encoding="utf-8"))
                title = data.get("meta", {}).get("title", "未命名PRD")
            except Exception:
                title = "未命名PRD"

            self.wiki_system.git_storage.commit(
                f"feat: add PRD - {title}", "pm_agent"
            )

            artifacts = [json_path.relative_to(self.config.repo_path).as_posix()]
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
                message=f"Agent did not produce {json_path}",
            )
