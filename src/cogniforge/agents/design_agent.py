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

            # --- Cross-module contract discovery ---
            contract_context = self._build_contract_context(module)

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
                f"{contract_context}\n"
                f"要求:\n"
                f"1. 先阅读 PRD 和 SAD 了解全局上下文\n"
                f"2. 如 SAD 定义了本模块的接口契约（见上方），必须严格按契约定义接口\n"
                f"   - provider 契约: 你必须实现这些接口，不得修改签名\n"
                f"   - consumer 契约: 你的依赖接口签名已确定，请使用契约中的确切字段名\n"
                f"3. 如有其他模块的 LLD 已生成，请阅读它们以确认接口对齐\n"
                f"4. 使用中文、只写 JSON 不写 HTML、完成后回复确认"
            )

            response = self.agent.generate_agentic(prompt, role="design")
            return self._commit_and_result(json_path, title, response.content)

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _build_contract_context(self, module: str) -> str:
        """Read SAD contracts and existing LLDs to build cross-module constraint context."""
        parts: list[str] = []

        # Read SAD contracts relevant to this module
        sad_docs = self.wiki_system.list_documents(DocumentType.SAD)
        if sad_docs:
            sad_data = self.wiki_system.read_json(DocumentType.SAD, doc_id=sad_docs[-1].doc_id)
            if sad_data:
                contracts = sad_data.get("contracts", [])
                provides = [c for c in contracts if c.get("provider") == module]
                consumes = [c for c in contracts if module in c.get("consumers", [])]

                if provides:
                    parts.append("=== 你必须实现的接口契约 (provider) ===")
                    for c in provides:
                        parts.append(json.dumps(c, ensure_ascii=False, indent=2))
                    parts.append("以上接口签名不可修改，consumer 模块将严格按此契约调用。\n")

                if consumes:
                    parts.append("=== 你依赖的接口契约 (consumer) ===")
                    for c in consumes:
                        parts.append(json.dumps(c, ensure_ascii=False, indent=2))
                    parts.append("请在你的 LLD 中引用这些接口的确切签名，不要自造变体。\n")

        # List existing LLDs from other modules for cross-reference
        all_llds = self.wiki_system.list_documents(DocumentType.LLD)
        other_llds = [
            d for d in all_llds
            if d.path.split("/")[3] != module  # lld/{module}/...
        ]
        if other_llds:
            modules_with_lld = sorted(set(
                d.path.split("/")[3] for d in other_llds
            ))
            parts.append(
                "=== 已有 LLD 的其他模块（请阅读以对齐接口） ==="
            )
            for m in modules_with_lld:
                m_llds = [d for d in other_llds if d.path.split("/")[3] == m]
                for d in m_llds:
                    parts.append(f"  {d.path}")

        return "\n".join(parts) if parts else ""

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
