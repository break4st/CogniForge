"""Design Agent - MDE Agent for detailed design"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.core.exceptions import AgentError


class DesignAgent(BaseAgent):
    """Design Agent (MDE) — delegates to Claude Code to generate LLD JSON."""

    def run(self, input_data: dict) -> dict:
        try:
            if self.agent is None:
                raise AgentError("DesignAgent requires a Claude Code agent")

            module = input_data.get("module", "unknown")
            title = input_data.get("title", f"LLD - {module}")
            overview = input_data.get("overview", "")
            data_models = input_data.get("data_models", [])
            interfaces = input_data.get("interfaces", [])
            error_handling = input_data.get("error_handling", "")

            existing = self.wiki_system.list_documents(DocumentType.LLD, module=module)
            seq = len(existing) + 1
            doc_id = f"lld-{module}-{seq:03d}"
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            json_path = self.wiki_system.agent_path(DocumentType.LLD, doc_id=doc_id, module=module)

            prompt = (
                f"根据以下数据创建一份详细设计文档 (LLD)，以 JSON 格式输出并写入:\n\n"
                f"输出路径: {json_path}\n"
                f"JSON 结构: {{\"meta\": {{\"doc_id\": \"{doc_id}\", \"type\": \"lld\", "
                f"\"module\": \"{module}\", \"title\": \"{title}\", "
                f"\"author\": \"design_agent\", \"created\": \"{now}\"}},\n"
                f" \"overview\": \"...\",\n"
                f" \"data_models\": [{{\"name\": \"...\", \"type\": \"table/api/...\", "
                f"\"fields\": [{{\"name\": \"...\", \"type\": \"...\", \"description\": \"...\"}}]}}],\n"
                f" \"interfaces\": [{{\"name\": \"...\", \"endpoint\": \"...\", "
                f"\"description\": \"...\", \"parameters\": [{{\"name\": \"...\", \"type\": \"...\", \"description\": \"...\"}}]}}],\n"
                f" \"error_handling\": \"...\"}}\n\n"
                f"输入数据:\n"
                f"module: {module}\n"
                f"overview: {overview}\n"
                f"data_models: {json.dumps(data_models, ensure_ascii=False)}\n"
                f"interfaces: {json.dumps(interfaces, ensure_ascii=False)}\n"
                f"error_handling: {error_handling}\n\n"
                f"要求: 先阅读 PRD 和 SAD、使用中文、只写 JSON 不写 HTML、完成后回复确认"
            )

            response = self.agent.generate_agentic(prompt, role="design")
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

        self.wiki_system.git_storage.commit(f"feat: add LLD - {title}", "design_agent")

        artifacts = [rel_json]
        if rel_html:
            artifacts.append(rel_html)

        return self.format_result(
            status="success",
            message=f"LLD created: {json_path.stem}",
            artifacts=artifacts,
            reasoning=reasoning,
        )
