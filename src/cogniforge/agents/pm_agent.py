"""PM Agent - Product Manager Agent for PRD creation"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.core.exceptions import AgentError


class PMAgent(BaseAgent):
    """PM Agent — uses two-step thinking→JSON to generate PRD."""

    def run(self, input_data: dict) -> dict:
        try:
            if self.agent is None:
                raise AgentError("PMAgent requires an LLM agent")

            existing = self.wiki_system.list_documents(DocumentType.PRD)
            seq = len(existing) + 1
            doc_id = f"prd-{seq:03d}"
            cb = input_data.pop("_progress_callback", None)

            raw_text = input_data.get("raw_text", "")
            if raw_text:
                if cb:
                    cb("PM 正在分析需求，提取项目信息...")
                return self._run_raw(raw_text, doc_id)

            title = input_data.get("title", "未命名PRD")
            overview = input_data.get("overview", "")
            requirements = input_data.get("requirements", [])
            user_stories = input_data.get("user_stories", [])
            priorities = input_data.get("priorities", {})

            return self._run_structured(
                title, overview, requirements, user_stories, priorities, doc_id,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _run_raw(self, raw_text: str, doc_id: str) -> dict:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        json_path = self.wiki_system.agent_path(DocumentType.PRD, doc_id=doc_id)

        prompt = (
            f"根据以下用户描述，创建一份完整的产品需求文档 (PRD)。\n"
            f"充分理解用户意图，提取项目名称、撰写详细概述、"
            f"梳理功能需求（含验收条件）、推导用户故事、标注优先级。\n\n"
            f"用户描述:\n{raw_text}\n\n"
            f"预期输出 JSON 结构参考:\n"
            f'{{"meta": {{"doc_id": "{doc_id}", "type": "prd", '
            f'"title": "...", "author": "pm_agent", "created": "{now}", '
            f'"version": 1}},\n'
            f' "overview": "项目概述文本（3-5句）",\n'
            f' "requirements": [{{"name": "需求名", "description": "描述", '
            f'"acceptance_criteria": ["条件1", "条件2"]}}],\n'
            f' "user_stories": [{{"role": "角色", "action": "动作", "goal": "目标"}}],\n'
            f' "priorities": {{"需求名": "高/中/低"}}\n'
            f"}}\n\n"
            f"要求: 所有文字使用中文"
        )

        response = self.agent.generate_think_then_json(
            prompt, role="pm", max_tokens=8192,
        )
        return self._write_and_commit(json_path, doc_id, response.content)

    def _run_structured(
        self, title, overview, requirements, user_stories, priorities, doc_id: str,
    ) -> dict:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        json_path = self.wiki_system.agent_path(DocumentType.PRD, doc_id=doc_id)

        prompt = (
            f"根据以下数据创建一份产品需求文档 (PRD)。\n\n"
            f"项目名称: {title}\n"
            f"项目概述: {overview}\n"
            f"功能需求: {json.dumps(requirements, ensure_ascii=False)}\n"
            f"用户故事: {json.dumps(user_stories, ensure_ascii=False)}\n"
            f"优先级: {json.dumps(priorities, ensure_ascii=False)}\n\n"
            f"预期输出 JSON 结构参考:\n"
            f'{{"meta": {{"doc_id": "{doc_id}", "type": "prd", '
            f'"title": "{title}", "author": "pm_agent", "created": "{now}", '
            f'"version": 1}},\n'
            f' "overview": "项目概述文本",\n'
            f' "requirements": [{{"name": "需求名", "description": "描述", '
            f'"acceptance_criteria": ["条件1", "条件2"]}}],\n'
            f' "user_stories": [{{"role": "角色", "action": "动作", "goal": "目标"}}],\n'
            f' "priorities": {{"需求名": "高/中/低"}}\n'
            f"}}\n\n"
            f"要求: 所有文字使用中文"
        )

        response = self.agent.generate_think_then_json(
            prompt, role="pm", max_tokens=8192,
        )
        return self._write_and_commit(json_path, doc_id, response.content)

    def _write_and_commit(self, json_path: str, doc_id: str, raw_content: str) -> dict:
        """Extract JSON from LLM response, write file, commit to git."""
        json_text = _extract_json(raw_content)
        json_abs = Path(self.config.repo_path) / json_path
        json_abs.parent.mkdir(parents=True, exist_ok=True)
        json_abs.write_text(json_text, encoding="utf-8")

        rel_json = json_abs.relative_to(self.config.repo_path).as_posix()
        self.wiki_system.git_storage.repo.index.add([rel_json])

        from cogniforge.wiki.wiki_renderer import render_file
        html_path = render_file(json_abs)
        rel_html = html_path.relative_to(self.config.repo_path).as_posix() if html_path else ""
        if rel_html:
            self.wiki_system.git_storage.repo.index.add([rel_html])

        try:
            data = json.loads(json_text)
            title = data.get("meta", {}).get("title", "未命名PRD")
        except Exception:
            title = "未命名PRD"

        self.wiki_system.git_storage.commit(f"feat: add PRD - {title}", "pm_agent")

        artifacts = [rel_json]
        if rel_html:
            artifacts.append(rel_html)

        return self.format_result(
            status="success",
            message=f"PRD created: {doc_id}",
            artifacts=artifacts,
            reasoning=raw_content,
        )


def _extract_json(text: str) -> str:
    """Strip markdown code fences, return bare JSON."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text
