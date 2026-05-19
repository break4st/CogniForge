"""Architect Agent - System Architecture Agent"""

from __future__ import annotations

import json
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.core.exceptions import AgentError


class ArchitectAgent(BaseAgent):
    """Architect Agent — delegates to Claude Code agent to read PRD,
    generate SAD, and write the output file."""

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
            output_path = f".cogniforge/wiki/sad/{doc_id}.md"

            return self._run_agentic(
                title, system_overview, architecture, components,
                topology, data_flow, doc_id, output_path,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _run_agentic(
        self, title, system_overview, architecture, components,
        topology, data_flow, doc_id, output_path,
    ) -> dict:
        payload = {
            "title": title,
            "system_overview": system_overview,
            "architecture": architecture,
            "components": components,
            "topology": topology,
            "data_flow": data_flow,
        }
        prompt = (
            f"根据以下数据创建一份系统架构文档 (SAD)：\n\n"
            f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
            f"要求：\n"
            f"1. 先阅读 .cogniforge/wiki/prd/ 下的 PRD 了解需求\n"
            f"2. 先阅读 DESIGN.html 了解架构设计规范\n"
            f"3. 生成 SAD 文档写入: {output_path}\n"
            f"4. 包含：系统概述、架构图描述、组件设计、拓扑结构、数据流\n"
            f"5. 使用中文\n"
            f"6. 完成后用中文回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="architect")

        output_abs = Path(self.config.repo_path) / output_path
        if output_abs.exists():
            self.wiki_system.git_storage.repo.index.add([output_path])
            self.wiki_system.git_storage.commit(
                f"feat: add SAD - {title}", "architect_agent"
            )
            return self.format_result(
                status="success",
                message=f"SAD created: {doc_id}",
                artifacts=[output_path],
                reasoning=response.content,
            )
        else:
            return self.format_result(
                status="failed",
                message=f"Claude Code did not produce {output_path}",
            )
