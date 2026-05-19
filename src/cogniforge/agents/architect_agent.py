"""Architect Agent - System Architecture Agent"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.core.exceptions import AgentError


class ArchitectAgent(BaseAgent):
    """Architect Agent — delegates to Claude Code to generate SAD JSON."""

    def run(self, input_data: dict) -> dict:
        try:
            if self.agent is None:
                raise AgentError("ArchitectAgent requires a Claude Code agent")

            title = input_data.get("title", "System Architecture")
            system_overview = input_data.get("system_overview", "")
            architecture = input_data.get("architecture", "")
            components = input_data.get("components", [])
            topology = input_data.get("topology", "")
            data_flow = input_data.get("data_flow", "")

            existing = self.wiki_system.list_documents(DocumentType.SAD)
            seq = len(existing) + 1
            doc_id = f"sad-{seq:03d}"
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            json_path = self.wiki_system.agent_path(DocumentType.SAD, doc_id=doc_id)

            prompt = (
                f"根据以下数据创建一份系统架构文档 (SAD)，以 JSON 格式输出并写入:\n\n"
                f"输出路径: {json_path}\n"
                f"JSON 结构: {{\"meta\": {{\"doc_id\": \"{doc_id}\", \"type\": \"sad\", "
                f"\"title\": \"{title}\", \"author\": \"architect_agent\", \"created\": \"{now}\"}},\n"
                f" \"system_overview\": \"...\", \"architecture\": \"...\",\n"
                f" \"components\": [{{\"name\": \"...\", \"type\": \"service\", "
                f"\"description\": \"...\", \"responsibilities\": [\"...\"]}}],\n"
                f" \"topology\": \"...\", \"data_flow\": \"...\"}}\n\n"
                f"输入数据:\n"
                f"system_overview: {system_overview}\n"
                f"architecture: {architecture}\n"
                f"components: {json.dumps(components, ensure_ascii=False)}\n"
                f"topology: {topology}\n"
                f"data_flow: {data_flow}\n\n"
                f"要求: 先阅读 PRD、使用中文、只写 JSON 不写 HTML、完成后回复确认"
            )

            response = self.agent.generate_agentic(prompt, role="architect")
            return self._commit_and_result(json_path, title, response.content)

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _commit_and_result(self, json_path: Path, title: str, reasoning: str = "") -> dict:
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

        self.wiki_system.git_storage.commit(f"feat: add SAD - {title}", "architect_agent")

        artifacts = [rel_json]
        if rel_html:
            artifacts.append(rel_html)

        return self.format_result(
            status="success",
            message=f"SAD created: {json_path.stem}",
            artifacts=artifacts,
            reasoning=reasoning,
        )
