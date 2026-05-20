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
                f"JSON 结构:\n"
                f"{{\n"
                f"  \"meta\": {{\"doc_id\": \"{doc_id}\", \"type\": \"lld\",\n"
                f"    \"module\": \"{module}\", \"title\": \"{title}\",\n"
                f"    \"author\": \"design_agent\", \"created\": \"{now}\"}},\n"
                f"  \"overview\": {{\n"
                f"    \"description\": \"模块概述（string）\",\n"
                f"    \"dependencies\": [\"依赖的模块名\"],\n"
                f"    \"tech_stack\": [\"技术栈\"]\n"
                f"  }},\n"
                f"  \"data_models\": [\n"
                f"    {{\"name\": \"模型名\", \"type\": \"table|interface|struct|store|config\",\n"
                f"      \"description\": \"说明\",\n"
                f"      \"fields\": [\n"
                f"        {{\"name\": \"字段名\", \"type\": \"类型\",\n"
                f"          \"required\": true, \"description\": \"说明\"}}\n"
                f"      ]}}\n"
                f"  ],\n"
                f"  \"interfaces\": [\n"
                f"    {{\"name\": \"接口名称\",\n"
                f"      \"method\": \"GET|POST|PUT|DELETE|INTERNAL\",\n"
                f"      \"endpoint\": \"/api/...（不含 HTTP 方法前缀）\",\n"
                f"      \"description\": \"接口说明\",\n"
                f"      \"parameters\": [\n"
                f"        {{\"name\": \"参数名\", \"type\": \"类型\", \"description\": \"说明\"}}\n"
                f"      ],\n"
                f"      \"response\": {{\n"
                f"        \"status\": 200,\n"
                f"        \"body\": {{\"字段名\": \"类型\"}}\n"
                f"      }},\n"
                f"      \"error_codes\": [\n"
                f"        {{\"code\": 400, \"message\": \"错误说明\"}}\n"
                f"      ]}}\n"
                f"  ],\n"
                f"  \"error_handling\": \"错误处理策略描述\"\n"
                f"}}\n\n"
                f"重要:\n"
                f"- interfaces[].method 与 endpoint 分开填写，method 为 HTTP 方法或 INTERNAL\n"
                f"- interfaces[].response.body 的字段名与类型与 SAD 契约严格一致，不可修改\n"
                f"- data_models[].type 使用 table（数据库表）/interface（TS 接口）/struct（Go 结构体）/store（前端状态）/config（配置）\n"
                f"- 前端模块的 interfaces 使用 frontend 作为 method 值，endpoint 填写路由路径\n"
                f"- overview.tech_stack 必须从 SAD tech_stack 中选取本模块相关的技术子集，不可引入未声明的技术\n\n"
                f"输入数据:\n"
                f"module: {module}\n"
                f"overview: {overview}\n"
                f"data_models: {json.dumps(data_models, ensure_ascii=False)}\n"
                f"interfaces: {json.dumps(interfaces, ensure_ascii=False)}\n"
                f"error_handling: {error_handling}\n\n"
                f"{contract_context}\n"
                f"要求:\n"
                f"1. 以上 prompt 已包含本模块 SAD 定义、接口契约、邻模块接口签名，无需额外读取\n"
                f"2. 如需更完整背景（PRD 全文、其他模块完整 LLD），可选择性 Read 相关文件\n"
                f"3. 接口契约约束:\n"
                f"   - provider 契约: 你必须实现这些接口，response body 字段名与类型不可修改\n"
                f"   - consumer 契约: 引用这些接口的确切 endpoint 与字段，不要自造变体\n"
                f"4. 使用中文、只写 JSON 不写 HTML、完成后回复确认"
            )

            response = self.agent.generate_agentic(prompt, role="design")
            return self._commit_and_result(json_path, title, response.content)

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _build_contract_context(self, module: str) -> str:
        """Assemble self-contained context from SAD + existing LLDs.

        The MDE agent receives everything it needs inline — no mandatory
        file reads.  The LLM CAN still open files for extra detail but the
        prompt already contains the binding constraints.
        """
        parts: list[str] = []
        sad_data = None
        all_llds = self.wiki_system.list_documents(DocumentType.LLD)
        lld_index = _lld_index_by_module(all_llds)

        # ── 1. Read SAD ──
        sad_docs = self.wiki_system.list_documents(DocumentType.SAD)
        if sad_docs:
            sad_data = self.wiki_system.read_json(DocumentType.SAD, doc_id=sad_docs[-1].doc_id)

        # ── 2. Module self-definition from SAD ──
        if sad_data:
            components = sad_data.get("components", [])
            my_comp = next((c for c in components if c.get("name") == module), None)
            if my_comp:
                parts.append("=== 本模块 SAD 定义 ===")
                parts.append(f"模块: {module}")
                parts.append(f"类型: {my_comp.get('type', 'unknown')}")
                parts.append(f"描述: {my_comp.get('description', '')}")
                resps = my_comp.get("responsibilities", [])
                if resps:
                    parts.append(f"职责: {', '.join(resps)}")
                parts.append("")

        # ── 3. Contracts filtered for this module ──
        contracts = sad_data.get("contracts", []) if sad_data else []
        provides = [c for c in contracts if c.get("provider") == module]
        consumes = [c for c in contracts if module in c.get("consumers", [])]

        if provides:
            parts.append("=== 你必须实现的接口契约 (provider) ===")
            parts.append("以下接口由 SAD 定义，签名不可修改。consumer 将严格按此调用：")
            parts.append("")
            for c in provides:
                parts.append(json.dumps(c, ensure_ascii=False, indent=2))
            parts.append("")

        if consumes:
            parts.append("=== 你依赖的接口契约 (consumer) ===")
            parts.append("以下接口由其他模块提供。你的 LLD 必须引用确切签名：")
            parts.append("")
            for c in consumes:
                parts.append(json.dumps(c, ensure_ascii=False, indent=2))
                # Extract the actual interface from the provider's LLD if available
                provider = c.get("provider", "")
                endpoint = c.get("endpoint", "")
                if provider in lld_index and endpoint:
                    prov_lld = _read_lld_json(lld_index[provider])
                    if prov_lld:
                        matched = _find_iface_by_endpoint(
                            prov_lld.get("interfaces", []), endpoint
                        )
                        if matched:
                            parts.append(
                                f"  ← {provider} 的 LLD 实际定义为:\n"
                                f"     {json.dumps(matched, ensure_ascii=False)}"
                            )
            parts.append("")

        # ── 4. Neighbor LLDs with already-defined interfaces ──
        other_llds = [
            d for d in all_llds
            if d.path.split("/")[3] != module
        ]
        if other_llds:
            parts.append("=== 其他模块已生成的接口（供交叉参考） ===")
            for d in other_llds:
                mod_name = d.path.split("/")[3]
                lld_data = _read_lld_json(d.path)
                if not lld_data:
                    continue
                for iface in lld_data.get("interfaces", []):
                    # Only show interfaces that are part of a SAD contract
                    ep = iface.get("endpoint", "")
                    if ep and _endpoint_in_contracts(ep, contracts):
                        parts.append(f"[{mod_name}] {iface.get('endpoint','')}")
                        parts.append(f"  response body: {json.dumps(iface.get('response',{}), ensure_ascii=False)}")
                        params = iface.get("parameters", [])
                        if params:
                            parts.append(f"  parameters: {json.dumps(params, ensure_ascii=False)}")
            parts.append("")

        # ── 5. System architecture context (layers + data flows) ──
        if sad_data:
            arch = sad_data.get("architecture", {})
            flow = sad_data.get("data_flow", [])
            has_arch = isinstance(arch, dict) and arch
            has_flow = isinstance(flow, list) and flow

            if has_arch or has_flow:
                parts.append("=== 系统全局架构上下文 ===")
                if has_arch:
                    layers = arch.get("layers", [])
                    connections = arch.get("connections", [])
                    if layers:
                        layer_lines = []
                        for i, layer in enumerate(layers):
                            comps = ", ".join(layer.get("components", []))
                            layer_lines.append(f"  {layer.get('name', '?')}: [{comps}]")
                            if i < len(layers) - 1 and i < len(connections):
                                layer_lines.append(f"    ↕ {connections[i].get('protocol', '')}")
                        parts.append("分层拓扑:")
                        parts.extend(layer_lines)
                if has_flow:
                    flow_lines = []
                    for i, f in enumerate(flow):
                        name = f.get("name", f"Flow {i + 1}")
                        steps = " → ".join(f.get("steps", []))
                        flow_lines.append(f"  {i + 1}. {name}: {steps}")
                    parts.append("数据流:")
                    parts.extend(flow_lines)
                parts.append("")

        # ── 6. Global tech stack from SAD ──
        if sad_data:
            tech_stack = sad_data.get("tech_stack", {})
            if tech_stack:
                parts.append("=== 全局技术选型 (SAD tech_stack) ===")
                parts.append("以下为系统全局技术栈，各模块 LLD 的 overview.tech_stack 必须从中选取本模块相关的子集，不可使用未在此声明的技术：")
                parts.append(json.dumps(tech_stack, ensure_ascii=False, indent=2))
                parts.append("")

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


# ------------------------------------------------------------------ helpers

def _lld_index_by_module(lld_docs: list) -> dict[str, str]:
    """Return {module_name: absolute_disk_path} for the latest LLD per module."""
    index: dict[str, str] = {}
    for d in lld_docs:
        mod = d.path.split("/")[3] if len(d.path.split("/")) > 3 else ""
        if mod:
            index[mod] = d.path  # last-wins (sorted by doc_id)
    return index


def _read_lld_json(rel_path: str) -> dict | None:
    """Read and parse an LLD JSON file from its repo-relative path."""
    from pathlib import Path as _Path
    abs_path = _Path.cwd() / rel_path
    if not abs_path.exists():
        return None
    try:
        return json.loads(abs_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_iface_by_endpoint(interfaces: list[dict], endpoint: str) -> dict | None:
    """Find an interface dict whose endpoint matches the given contract endpoint."""
    target = endpoint.strip().lower()
    for iface in interfaces:
        if target in iface.get("endpoint", "").strip().lower():
            return iface
    return None


def _endpoint_in_contracts(endpoint: str, contracts: list[dict]) -> bool:
    """Check whether an endpoint string appears in any SAD contract."""
    target = endpoint.strip().lower()
    for c in contracts:
        if target in c.get("endpoint", "").strip().lower():
            return True
    return False
