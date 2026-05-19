"""Design Agent - MDE Agent for detailed design"""

from __future__ import annotations

import json
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.core.exceptions import AgentError


class DesignAgent(BaseAgent):
    """Design Agent (MDE) — delegates to Claude Code agent to read PRD + SAD,
    generate LLD, and write the output file."""

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
            output_path = f".cogniforge/wiki/lld/{module}/{doc_id}.md"

            return self._run_agentic(
                title, overview, data_models, interfaces, error_handling,
                module, doc_id, output_path,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _run_agentic(
        self, title, overview, data_models, interfaces, error_handling,
        module, doc_id, output_path,
    ) -> dict:
        payload = {
            "title": title,
            "overview": overview,
            "data_models": data_models,
            "interfaces": interfaces,
            "error_handling": error_handling,
        }
        prompt = (
            f"根据以下数据创建一份详细设计文档 (LLD)：\n\n"
            f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
            f"要求：\n"
            f"1. 先阅读 .cogniforge/wiki/prd/ 和 .cogniforge/wiki/sad/ 了解上下文\n"
            f"2. 生成 LLD 文档写入: {output_path}\n"
            f"3. 包含: 模块概述、数据模型、接口定义、错误处理策略\n"
            f"4. 使用中文\n"
            f"5. 完成后用中文回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="design")

        output_abs = Path(self.config.repo_path) / output_path
        if output_abs.exists():
            self.wiki_system.git_storage.repo.index.add([output_path])
            self.wiki_system.git_storage.commit(
                f"feat: add LLD - {title}", "design_agent"
            )
            return self.format_result(
                status="success",
                message=f"LLD created: {doc_id}",
                artifacts=[output_path],
                reasoning=response.content,
            )
        else:
            return self.format_result(
                status="failed",
                message=f"Claude Code did not produce {output_path}",
            )
