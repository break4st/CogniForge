"""PM Agent - Product Manager Agent for PRD creation"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.core.exceptions import AgentError


class PMAgent(BaseAgent):
    """PM Agent — delegates to Claude Code agent to read context,
    generate PRD HTML, and write the output file."""

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
            output_path = f".cogniforge/wiki/prd/{doc_id}.html"

            return self._run_agentic(
                title, overview, requirements, user_stories, priorities,
                doc_id, output_path,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _run_agentic(
        self, title, overview, requirements, user_stories, priorities,
        doc_id: str, output_path: str,
    ) -> dict:
        payload = {
            "title": title,
            "overview": overview,
            "requirements": requirements,
            "user_stories": user_stories,
            "priorities": priorities,
        }
        prompt = (
            f"根据以下数据创建一份产品需求文档 (PRD)：\n\n"
            f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
            f"要求：\n"
            f"1. 先阅读 DESIGN.html 了解项目视觉风格\n"
            f"2. 先阅读 .cogniforge/wiki/prd/ 下已有的 PRD 了解文档格式\n"
            f"3. 生成一个自包含的 HTML 文件，写入路径: {output_path}\n"
            f"4. 使用与 DESIGN.html 一致的暗色主题（CSS 变量、卡片式布局、渐变标题）\n"
            f"5. 文档 ID 为 {doc_id}，所有标题和标签使用中文\n"
            f"6. 确保 HTML 完整可独立在浏览器打开\n"
            f"7. 完成后用中文回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="pm")

        output_abs = Path(self.config.repo_path) / output_path
        if output_abs.exists():
            self.wiki_system.git_storage.repo.index.add([output_path])
            self.wiki_system.git_storage.commit(
                f"feat: add PRD - {title}", "pm_agent"
            )
            return self.format_result(
                status="success",
                message=f"PRD created: {doc_id}",
                artifacts=[output_path],
                reasoning=response.content,
            )
        else:
            return self.format_result(
                status="failed",
                message=f"Claude Code did not produce {output_path}",
            )
