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
            data_flow = input_data.get("data_flow", "")

            existing = self.wiki_system.list_documents(DocumentType.SAD)
            seq = len(existing) + 1
            doc_id = f"sad-{seq:03d}"
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            json_path = self.wiki_system.agent_path(DocumentType.SAD, doc_id=doc_id)

            prompt = (
                f"根据以下数据创建一份系统架构文档 (SAD)，以 JSON 格式输出并写入:\n\n"
                f"输出路径: {json_path}\n"
                f"JSON 结构如下（system_overview/architecture 为对象，data_flow 为数组）:\n\n"
                f"{{\n"
                f"  \"meta\": {{\"doc_id\": \"{doc_id}\", \"type\": \"sad\",\n"
                f"    \"title\": \"{title}\", \"author\": \"architect_agent\", \"created\": \"{now}\"}},\n"
                f"  \"system_overview\": {{\n"
                f"    \"description\": \"系统整体描述（string）\",\n"
                f"    \"roles\": [\n"
                f"      {{\"name\": \"角色名\",\n"
                f"        \"permissions\": [\"权限1\", \"权限2\", ...]}}\n"
                f"    ]\n"
                f"  }},\n"
                f"  \"architecture\": {{\n"
                f"    \"style\": \"架构风格（如 微服务架构）\",\n"
                f"    \"description\": \"架构设计描述（string）\",\n"
                f"    \"layers\": [\n"
                f"      {{\"name\": \"层名（如 接入层/网关层/服务层/数据层）\",\n"
                f"        \"components\": [\"该层包含的组件名（与 components[].name 一致）\", ...]}}\n"
                f"    ],\n"
                f"    \"connections\": [\n"
                f"      {{\"protocol\": \"层间通信协议（如 HTTPS / REST / SQL / AMQP）\"}}\n"
                f"    ],\n"
                f"    \"features\": [\"架构特征1\", \"架构特征2\", ...]\n"
                f"  }},\n"
                f"  \"tech_stack\": {{\n"
                f"    \"backend\": {{\"language\": \"编程语言\", \"framework\": \"框架\"}},\n"
                f"    \"frontend\": {{\"framework\": \"前端框架\", \"ui_library\": \"UI组件库\"}},\n"
                f"    \"database\": \"数据库\",\n"
                f"    \"cache\": \"缓存\",\n"
                f"    \"mq\": \"消息队列\",\n"
                f"    \"...\": \"按需增删字段\"\n"
                f"  }},\n"
                f"  \"components\": [\n"
                f"    {{\"name\": \"组件名\", \"type\": \"frontend|gateway|service|database|infrastructure\",\n"
                f"      \"description\": \"组件描述\", \"responsibilities\": [\"职责1\", ...]}}\n"
                f"  ],\n"
                f"  \"contracts\": [\n"
                f"    {{\"interface\": \"接口名称\", \"provider\": \"提供者（必须与 components[].name 一致）\",\n"
                f"      \"consumers\": [\"消费者1\", ...], \"type\": \"REST|gRPC|MQ\",\n"
                f"      \"endpoint\": \"GET/POST /api/...\",\n"
                f"      \"request\": {{\"path_params\": [], \"query_params\": [], \"body\": {{}}}},\n"
                f"      \"response\": {{\"status\": 200, \"body\": {{}}}},\n"
                f"      \"description\": \"接口说明\"}}\n"
                f"  ],\n"
                f"  \"data_flow\": [\n"
                f"    {{\"name\": \"数据流名称\",\n"
                f"      \"steps\": [\"步骤1\", \"步骤2\", ...]}},\n"
                f"    ...\n"
                f"  ]\n"
                f"}}\n\n"
                f"重要说明:\n"
                f"- system_overview.roles: 从 PRD 中提取用户角色及其权限\n"
                f"- architecture.layers: 按系统分层列出每层包含的组件（组件名与 components[].name 一致）\n"
                f"- architecture.connections: 相邻层之间的通信协议，数组长度 = layers 数量 - 1\n"
                f"- architecture.features: 列出架构的关键技术特征，每项一个短语\n"
                f"- tech_stack: 根据架构设计明确定义技术选型（语言/框架/数据库/缓存/消息队列等），字段按需增删\n"
                f"- components: 每个组件需要 name/type/description/responsibilities\n"
                f"- data_flow: 每条数据流用 steps 数组描述从起点到终点的步骤序列\n"
                f"- contracts: 每个需要跨模块调用的接口必须定义，是 MDE 生成 LLD 的强制约束\n"
                f"- request/response: 精确的字段名、类型，MDE 将以此为准\n\n"
                f"参考输入数据:\n"
                f"system_overview: {system_overview}\n"
                f"architecture: {architecture}\n"
                f"components: {json.dumps(components, ensure_ascii=False)}\n"
                f"data_flow: {data_flow}\n\n"
                f"要求: 先阅读 PRD、使用中文、只写 JSON 不写 HTML、完成后回复确认"
            )

            response = self.agent.generate_agentic(prompt, role="architect")
            return self._commit_and_result(json_path, title, response.content)

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    # Canonical component type values expected by downstream consumers
    _COMPONENT_TYPE_CANONICAL: dict[str, str] = {
        # Canonical
        "frontend": "frontend", "gateway": "gateway", "service": "service",
        "database": "database", "infrastructure": "infrastructure",
        # LLM common variants → canonical
        "db": "database", "DB": "database", "Database": "database",
        "cache": "infrastructure", "redis": "infrastructure",
        "mq": "infrastructure", "message_queue": "infrastructure",
        "file_storage": "infrastructure", "storage": "infrastructure",
        "api_gateway": "gateway", "web": "frontend", "ui": "frontend",
    }

    @classmethod
    def _normalize_component_type(cls, raw: str) -> str:
        return cls._COMPONENT_TYPE_CANONICAL.get(raw, "service")

    def _commit_and_result(self, json_path: Path, title: str, reasoning: str = "") -> dict:
        json_abs = Path(self.config.repo_path) / json_path
        if not json_abs.exists():
            return self.format_result(status="failed",
                                       message=f"Claude Code did not produce {json_path}")

        # Normalize component types before commit
        try:
            data = json.loads(json_abs.read_text(encoding="utf-8"))
            components = data.get("components", [])
            fixed = 0
            for c in components:
                raw = c.get("type", "service")
                canonical = self._normalize_component_type(raw)
                if canonical != raw:
                    c["type"] = canonical
                    fixed += 1
            if fixed:
                json_abs.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
        except Exception:
            pass  # Don't block on normalization failure

        rel_json = json_path.relative_to(self.config.repo_path).as_posix()
        self.wiki_system.git_storage.repo.index.add([rel_json])

        from cogniforge.wiki.wiki_renderer import render_file
        html_path = render_file(json_abs)
        rel_html = html_path.relative_to(self.config.repo_path).as_posix() if html_path else ""
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
