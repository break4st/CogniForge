"""Design Agent - MDE Agent for detailed design"""

from __future__ import annotations

import functools
import json
import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType, ModuleType
from cogniforge.core.exceptions import AgentError
from cogniforge.wiki.wiki_renderer import repair_truncated_json


# ---------------------------------------------------------------------------
# Per-module-type JSON schema fragments for the LLM prompt
# Loaded from schemas/agents/lld/*.json
# ---------------------------------------------------------------------------

_SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "schemas" / "agents" / "lld"


@functools.lru_cache(maxsize=32)
def _load_schema_text(name: str) -> str:
    """Load an LLD schema fragment from schemas/agents/lld/{name}.json."""
    path = _SCHEMA_DIR / f"{name}.json"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").rstrip()


_SCHEMA_BASE = _load_schema_text("lld-base")
_SCHEMA_DATA_MODELS = _load_schema_text("lld-data-models")
_SCHEMA_INTERFACES = _load_schema_text("lld-interfaces")
_SCHEMA_ERROR = _load_schema_text("lld-error-handling")
_SCHEMA_WORKFLOW = _load_schema_text("lld-workflow")
_SCHEMA_DOMAIN_OBJECTS = _load_schema_text("lld-domain-objects")
_SCHEMA_SERVICE_CONTRACTS = _load_schema_text("lld-service-contracts")
_SCHEMA_BUSINESS_RULES = _load_schema_text("lld-business-rules")
_SCHEMA_COMPONENT_TREE = _load_schema_text("lld-component-tree")
_SCHEMA_STATE_DESIGN = _load_schema_text("lld-state-design")
_SCHEMA_ROUTE_DESIGN = _load_schema_text("lld-route-design")
_SCHEMA_INTERACTION_FLOWS = _load_schema_text("lld-interaction-flows")
_SCHEMA_API_INTEGRATION = _load_schema_text("lld-api-integration")
_SCHEMA_GATEWAY = _load_schema_text("lld-gateway")
_SCHEMA_DATABASE = _load_schema_text("lld-database")
_SCHEMA_INFRA = _load_schema_text("lld-infrastructure")

# ---------------------------------------------------------------------------
# Ownership rules per module_type
# ---------------------------------------------------------------------------

_OWNERSHIP_RULES: dict[str, str] = {
    "database": """\
数据模型所有权规则 (module_type=database):
- 你是所有数据库表的唯一权威定义者
- data_models 中所有 type=table 的模型必须使用 ownership=canonical
- 每个 canonical 表必须包含完整的字段定义和索引定义 (indexes 数组)
- 其他服务需要的表也在此统一定义，不要遗漏
- 额外章节需要填写:
  index_strategy: 按表汇总索引（与 data_models 中 indexes 保持一致，这里是总览）
  migration_strategy: 迁移工具和策略
  capacity_estimation: 容量估算
  connection_contracts: 各服务连接账号和权限矩阵""",

    "service": """\
数据模型所有权规则 (module_type=service):
- 不可以重新定义数据库表结构
- 需要数据库表时，使用 type=reference + ownership=derived
- source 指向 Primary Database LLD (doc_id: lld-Primary Database-001)
- 只列出本服务关心的字段视图
- 服务内部专用的 config/struct 使用 ownership=owned
- 接口 response body 必须完整展开字段，不写 {}

额外章节要求:
  domain_objects: ★ 核心——定义本服务的领域实体/DTO/值对象/枚举
    - entity: 业务实体，标注每个属性的 source (db透传/computed/input/derived)
    - dto: 请求/响应 DTO 的字段和校验约束
    - value_object: 不可变值对象
    - enum: 枚举类型的所有合法值
    - 每个 domain_object 的 attributes 具体到类型级别（如 String, Long, DateTime）
  service_contracts: ★ 核心——服务层公开方法签名
    - 每个方法的 signature 必须完整：参数名+类型+返回类型
    - precondition/postcondition 必须写（是什么为真，不只是"调用前需认证"）
    - exceptions 必须列出所有可能的异常名+触发条件+HTTP 映射
    - repository_dependencies: 声明需要哪些数据查询能力（按名+签名列出）
  business_rules:
    - invariants: 必须始终为真的业务约束
    - state_machines: 本服务管理的实体状态机（状态+转换+不可逆规则+并发控制）
    - cross_service_rules: 涉及其他服务的协同规则""",

    "gateway": """\
数据模型所有权规则 (module_type=gateway):
- 所有模型使用 ownership=owned（网关自身的路由规则、认证模型等）
- API 契约自包含：每个透传接口的 response body 必须完整展开
- 不可以写 {} 或"参考下游服务"——前端开发者只读你的 LLD
- 在 description 中注明 routes_to 指向哪个下游服务

额外章节要求:
  route_table: 每个 path pattern → upstream 映射，完整列出
  middleware_chain: 请求经过的中间件序列（顺序敏感）
  auth_policy: 公开端点、认证方式、角色-路径映射矩阵、Token 策略
  rate_limiting: 全局/用户/特殊端点的限流规则""",

    "frontend": """\
数据模型所有权规则 (module_type=frontend):
- 所有模型使用 ownership=owned（组件状态、Store 等）
- 不定义数据库表
- interfaces 的 method 使用 frontend，endpoint 填写路由路径
- 写明每个页面调用的 API endpoint

额外章节要求:
  component_tree: ★ 核心——页面组件树及每个组件的接口定义
    - 每个组件: name, path, props (name+type+required+description)
    - events (事件名+payload_type) 和 state (状态字段名+类型+说明)
    - behavior: 交互行为列表（mount/事件/状态变化的响应）
    - edge_cases: 边界/异常情况的处理方式
  state_design: 全局状态 vs 页面级状态的划分，缓存策略
  route_design: 路由表（path→page→layout→权限）
  interaction_flows: 关键用户旅程的步骤序列
  api_integration: 页面→API 映射表""",

    "infrastructure": """\
数据模型所有权规则 (module_type=infrastructure):
- 所有模型使用 ownership=owned（Redis key 模式、MQ 队列定义等中间件数据结构）
- 不定义业务数据库表

额外章节要求——按子类型选择:
  消息队列 (RabbitMQ/...):
    topology: exchanges + queues + bindings + producer/consumer 映射
    message_contracts: 每条消息的 schema、必填字段、大小上限
    reliability_strategy: ack 模式、重试、死信、幂等
  缓存 (Redis/...):
    topology: namespace、key_patterns、expiry 策略、pub/sub 频道
    connection_contracts: 连接池、超时
  文件存储 (MinIO/S3/...):
    topology: buckets + path convention
    connection_contracts: endpoint、认证方式、超时""",
}


class DesignAgent(BaseAgent):
    """Design Agent (MDE) — dual-JSON: initial generation + patch-based iteration."""

    def run(self, input_data: dict, progress_callback: Callable[[str], None] | None = None) -> dict:
        try:
            if self.agent is None:
                raise AgentError("DesignAgent requires an LLM agent")

            def _progress(phase: str) -> None:
                if progress_callback:
                    progress_callback(phase)

            # ── Interactive modification mode ──
            mde_request = input_data.get("mde_request")
            if mde_request:
                _progress("MDE 正在分析上游变更...")
                return self.modify_interactive(
                    mde_request=mde_request,
                    progress_callback=_progress,
                )

            # ── Initial creation mode ──

            module = input_data.get("module", "unknown")
            title = input_data.get("title", f"LLD - {module}")
            overview = input_data.get("overview", "")
            data_models = input_data.get("data_models", [])
            interfaces = input_data.get("interfaces", [])
            error_handling = input_data.get("error_handling", "")

            _progress("组装提示词")

            existing = self.wiki_system.list_documents(DocumentType.LLD, module=module)
            seq = len(existing) + 1
            doc_id = f"lld-{module}-{seq:03d}"
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            json_path = self.wiki_system.agent_path(DocumentType.LLD, doc_id=doc_id, module=module)

            module_type = self._resolve_module_type(module)
            contract_context = self._build_contract_context(module, module_type)
            ownership_rules = _OWNERSHIP_RULES.get(module_type, _OWNERSHIP_RULES["service"])
            conditional_schema = _build_conditional_schema(module_type)

            prompt = (
                f"根据以下数据创建一份详细设计文档 (LLD):\n\n"
                f"JSON 结构:\n"
                f"{_SCHEMA_BASE}\n"
                f"{_SCHEMA_DATA_MODELS}\n"
                f"{_SCHEMA_INTERFACES}\n"
                f"{_SCHEMA_ERROR}\n"
                f"{_SCHEMA_WORKFLOW}\n"
                + (f"{conditional_schema}\n" if conditional_schema else "")
                + f"\n重要:\n"
                f"- data_models 中每个模型必须分配唯一 id（DM-001, DM-002...）\n"
                f"- interfaces 中每个接口必须分配唯一 id（IF-001, IF-002...）\n"
                f"- interfaces[].method 与 endpoint 分开填写，method 为 HTTP 方法或 INTERNAL/MQ/WS/frontend\n"
                f"- interfaces[].response.body 的字段名与类型与 SAD 契约严格一致，不可修改\n"
                f"- 前端模块的 interfaces 使用 frontend 作为 method 值，endpoint 填写路由路径\n"
                f"- overview.tech_stack 必须从 SAD tech_stack 中选取本模块相关的技术子集\n"
                f"- gateway 模块的 API 契约必须自包含：完整的 request/response body\n"
                f"- JSON 字符串值内的双引号必须转义为 \\\"，中文引号请使用「」代替 \"\"\n\n"
                f"{ownership_rules}\n"
                f"输入数据:\n"
                f"module: {module}\n"
                f"module_type: {module_type}\n"
                f"overview: {overview}\n"
                f"data_models: {json.dumps(data_models, ensure_ascii=False)}\n"
                f"interfaces: {json.dumps(interfaces, ensure_ascii=False)}\n"
                f"error_handling: {error_handling}\n\n"
                f"{contract_context}\n"
                f"要求:\n"
                f"1. 以上 prompt 已包含本模块 SAD 定义、接口契约、邻模块接口签名\n"
                f"2. 接口契约约束:\n"
                f"   - provider 契约: 你必须实现这些接口，response body 字段名与类型不可修改\n"
                f"   - consumer 契约: 引用这些接口的确切 endpoint 与字段，不要自造变体\n"
                f"3. 各模块类型要求的章节必须完整填写，不可省略\n"
                + _type_specific_hints(module_type)
                + f"使用中文"
            )

            _progress("LLM 生成中")
            max_retries = 2
            last_error = None
            for attempt in range(max_retries + 1):
                if attempt > 0:
                    _progress(f"JSON 解析失败，正在重试 ({attempt}/{max_retries})...")
                    prompt = (
                        f"你上一次输出的 JSON 有语法错误，无法解析：\n"
                        f"错误: {last_error}\n\n"
                        f"请重新生成。确保 JSON 格式正确，输出纯 JSON。\n\n"
                        f"原始任务:\n{prompt}"
                    )
                response = self.agent.generate_think_then_json(
                    prompt, role="design", max_tokens=8192,
                    progress_callback=_progress,
                )
                json_text = _extract_json(response.content)
                try:
                    data, incomplete = repair_truncated_json(json_text)
                    break
                except ValueError as e:
                    last_error = str(e)
                    if attempt == max_retries:
                        return self.format_result(
                            status="failed",
                            message=f"JSON 解析失败（已重试 {max_retries} 次）: {last_error}",
                            reasoning=response.content,
                        )

            # Assign stable IDs to data_models and interfaces
            # (data already assigned by repair_truncated_json inside the loop)
            if incomplete and _progress:
                _progress("警告: LLM 输出被截断，已自动修复 JSON 结构")
            data["data_models"] = self._assign_ids(data.get("data_models", []), "DM")
            data["interfaces"] = self._assign_ids(data.get("interfaces", []), "IF")
            json_text = json.dumps(data, ensure_ascii=False, indent=2)

            json_abs = Path(self.config.repo_path) / json_path
            json_abs.parent.mkdir(parents=True, exist_ok=True)
            json_abs.write_text(json_text, encoding="utf-8")

            # Validate written JSON
            json.loads(json_abs.read_text(encoding="utf-8"))

            # ── Validation loop (max 2 retries) ──
            correction_attempts = 0
            max_corrections = 2
            validation_report = ""

            while correction_attempts <= max_corrections:
                if not json_abs.exists():
                    return self.format_result(
                        status="failed",
                        message=f"LLM did not produce {json_path}"
                    )

                _progress("校验 JSON")
                from cogniforge.lld_validator import validate_lld_json, format_validation_report
                validation = validate_lld_json(json_abs)
                validation_report = format_validation_report(validation)

                if validation["passed"]:
                    break

                if correction_attempts < max_corrections:
                    correction_attempts += 1
                    _progress("LLM 修正中")
                    current_json = json_abs.read_text(encoding="utf-8")
                    fix_prompt = (
                        f"你刚才生成的 LLD JSON 校验未通过：\n\n"
                        f"{validation_report}\n\n"
                        f"当前 JSON:\n{current_json[:6000]}\n\n"
                        f"请修正以上所有问题，返回完整的修正后 JSON。"
                        f"只返回纯 JSON 对象，不要 markdown 代码块包裹。"
                    )
                    from cogniforge.llm.base import LLMMessage
                    fix_response = self.agent.generate_messages([
                        LLMMessage(role="system", content="你是 CogniForge 系统的 Design Agent。职责: 生成 LLD JSON。"),
                        LLMMessage(role="user", content=fix_prompt),
                    ], max_tokens=8192)
                    json_text = _extract_json(fix_response.content)
                    json_abs.write_text(json_text, encoding="utf-8")
                else:
                    break

            return self._commit_and_result(
                json_path, title, response.content,
                validation=validation_report,
                correction_attempts=correction_attempts,
                progress_callback=_progress,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    # SAD component type → ModuleType mapping
    # SAD component types are normalized to canonical values by ArchitectAgent
    _SAD_TYPE_MAP: dict[str, str] = {
        "database": ModuleType.DATABASE,
        "infrastructure": ModuleType.INFRASTRUCTURE,
        "service": ModuleType.SERVICE,
        "gateway": ModuleType.GATEWAY,
        "frontend": ModuleType.FRONTEND,
    }

    @staticmethod
    def _assign_ids(items: list[dict], prefix: str) -> list[dict]:
        """Assign stable serial IDs (DM-001, IF-001, etc.) to items lacking them."""
        max_num = 0
        for item in items:
            item_id = item.get("id", "")
            if item_id.startswith(f"{prefix}-"):
                try:
                    num = int(item_id.split("-", 1)[1])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
        next_num = max_num + 1
        assigned = []
        for item in items:
            item_id = item.get("id", "")
            if not item_id or not item_id.startswith(f"{prefix}-"):
                item["id"] = f"{prefix}-{next_num:03d}"
                next_num += 1
            assigned.append(item)
        return assigned

    def _resolve_module_type(self, module: str) -> str:
        sad_docs = self.wiki_system.list_documents(DocumentType.SAD)
        if not sad_docs:
            return ModuleType.SERVICE
        sad_data = self.wiki_system.read_json(DocumentType.SAD, doc_id=sad_docs[-1].doc_id)
        if not sad_data:
            return ModuleType.SERVICE
        components = sad_data.get("components", [])
        my_comp = next((c for c in components if c.get("name") == module), None)
        if my_comp:
            sad_type = my_comp.get("type", "service")
            return self._SAD_TYPE_MAP.get(sad_type, ModuleType.SERVICE)
        return ModuleType.SERVICE

    def _build_contract_context(self, module: str, module_type: str = "service") -> str:
        parts: list[str] = []
        sad_data = None
        all_llds = self.wiki_system.list_documents(DocumentType.LLD)
        lld_index = _lld_index_by_module(all_llds)

        sad_docs = self.wiki_system.list_documents(DocumentType.SAD)
        if sad_docs:
            sad_data = self.wiki_system.read_json(DocumentType.SAD, doc_id=sad_docs[-1].doc_id)

        # 1. Module self-definition
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

        # 2. Contracts
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

        # 3. Neighbor LLDs
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
                    ep = iface.get("endpoint", "")
                    if ep and _endpoint_in_contracts(ep, contracts):
                        parts.append(f"[{mod_name}] {iface.get('endpoint','')}")
                        parts.append(f"  response body: {json.dumps(iface.get('response',{}), ensure_ascii=False)}")
                        params = iface.get("parameters", [])
                        if params:
                            parts.append(f"  parameters: {json.dumps(params, ensure_ascii=False)}")
            parts.append("")

        # 4. System architecture
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

        # 5. Primary Database canonical tables
        if module_type in ("service", "gateway"):
            db_llds = self.wiki_system.list_documents(DocumentType.LLD, module="Primary Database")
            if db_llds:
                db_data = _read_lld_json(db_llds[-1].path)
                if db_data:
                    tables = [m for m in db_data.get("data_models", []) if m.get("type") == "table"]
                    if tables:
                        parts.append("=== Primary Database 权威表定义 (只能引用，不可重新定义) ===")
                        parts.append("以下数据库表已在 Primary Database LLD 中权威定义。")
                        parts.append("你的 LLD 中如需使用这些表，必须用 type=reference + ownership=derived + source 引用，不得重新定义字段。")
                        parts.append("")
                        for t in tables:
                            parts.append(f"  表名: {t['name']}")
                            parts.append(f"  字段: {json.dumps(t.get('fields', []), ensure_ascii=False)}")
                            idx_info = t.get("indexes", [])
                            if idx_info:
                                parts.append(f"  索引: {json.dumps(idx_info, ensure_ascii=False)}")
                            parts.append("")
                        parts.append("")

        # 6. Global tech stack
        if sad_data:
            tech_stack = sad_data.get("tech_stack", {})
            if tech_stack:
                parts.append("=== 全局技术选型 (SAD tech_stack) ===")
                parts.append("以下为系统全局技术栈，各模块 LLD 的 overview.tech_stack 必须从中选取本模块相关的子集，不可使用未在此声明的技术：")
                parts.append(json.dumps(tech_stack, ensure_ascii=False, indent=2))
                parts.append("")

        return "\n".join(parts) if parts else ""

    def _commit_and_result(self, json_path: Path, title: str, reasoning: str = "",
                           validation: str = "", correction_attempts: int = 0,
                           progress_callback: Callable[[str], None] | None = None) -> dict:
        def _progress(phase: str) -> None:
            if progress_callback:
                progress_callback(phase)

        json_abs = Path(self.config.repo_path) / json_path
        if not json_abs.exists():
            return self.format_result(status="failed",
                                       message=f"Claude Code did not produce {json_path}")

        rel_json = json_abs.relative_to(self.config.repo_path).as_posix()

        _progress("渲染 HTML")
        from cogniforge.wiki.wiki_renderer import render_file
        html_path = render_file(json_abs)
        rel_html = html_path.relative_to(self.config.repo_path).as_posix() if html_path else ""

        _progress("Git 提交")
        with self.wiki_system.git_storage.atomic_write():
            self.wiki_system.git_storage.repo.index.add([rel_json])
            if rel_html:
                self.wiki_system.git_storage.repo.index.add([rel_html])
            self.wiki_system.git_storage.commit(f"feat: add LLD - {title}", "design_agent")

        artifacts = [rel_json]
        if rel_html:
            artifacts.append(rel_html)

        decisions = [f"validation_passed={validation.startswith('✓')}"]
        if correction_attempts > 0:
            decisions.append(f"correction_attempts={correction_attempts}")

        return self.format_result(
            status="success",
            message=f"LLD created: {json_path.stem}",
            artifacts=artifacts,
            reasoning=f"{reasoning}\n{validation}" if validation else reasoning,
            decisions=decisions,
        )

    # ------------------------------------------------------------------
    # Interactive modification — patch-based iteration
    # ------------------------------------------------------------------

    def modify_interactive(
        self,
        mde_request: dict,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict:
        """Execute a single MDE modification turn."""
        try:
            t0 = time.time()
            target = mde_request.get("target_module", {})
            module = target.get("module", "unknown")
            module_type = target.get("module_type", "service")

            existing_docs = self.wiki_system.list_documents(DocumentType.LLD, module=module)
            if existing_docs:
                lld_path = self.config.repo_path / Path(existing_docs[-1].path)
            else:
                seq = 1
                doc_id = f"lld-{module}-{seq:03d}"
                lld_path = self.wiki_system.agent_path(DocumentType.LLD, doc_id=doc_id, module=module)

            current_lld = self._load_current_lld(module)
            lld_before_version = current_lld.get("meta", {}).get("version", 0) if current_lld else 0
            current_lld_json = json.dumps(current_lld, ensure_ascii=False, indent=2) if current_lld else "{}"

            prd_slice_json = json.dumps(mde_request.get("prd_slice", {}), ensure_ascii=False, indent=2)
            sad_slice_json = json.dumps(mde_request.get("sad_slice", {}), ensure_ascii=False, indent=2)
            upstream_json = json.dumps(mde_request.get("upstream_change", {}), ensure_ascii=False, indent=2)

            turn_schema_path = self.config.repo_path / "schemas" / "mde-turn-result-schema.json"
            turn_schema = None
            if turn_schema_path.exists():
                turn_schema = json.loads(turn_schema_path.read_text(encoding="utf-8"))

            system_prompt = (
                "你是 CogniForge 系统的 MDE (Design) Agent。\n"
                f"职责: 维护模块 '{module}' ({module_type}) 的详细设计文档 (LLD)。\n"
                "规则:\n"
                "1. 不要直接输出完整 LLD 文档，只输出包含 patches 数组的变更结果 JSON。\n"
                "2. 保留所有已有的 DM-ID、IF-ID、DO-ID、SC-ID 不变。\n"
                "3. 新增对象时分配新的 ID（下一个可用编号）。\n"
                "4. 修改已有对象时，version +1 并追加 change_history。\n"
                "5. 你只能设计本模块范围内的内容，不可越界设计其他模块。\n"
                "6. SAD contract 由本模块实现时，在 interfaces[] 中建立对应 interface 并填写 source_contract_id。\n"
                "7. 只消费 contract 时，在 api_integration/connection_contracts 中引用。\n"
                "8. SAD contract 不完整或不一致时，不可擅自修改——在 upstream_issues 中反馈。\n"
                "9. 每次 LLD 有变化，meta.version +1。\n"
                "10. patches 使用 RFC 6902 JSON Pointer 格式路径。\n"
                "11. 在 implementation_handoff 和 test_handoff 中给出下游任务提示。\n"
                "所有文字使用中文。"
            )

            user_prompt = (
                f"## PRD 切片（本模块相关需求）\n```json\n{prd_slice_json}\n```\n\n"
                f"## SAD 切片（本模块相关组件/接口）\n```json\n{sad_slice_json}\n```\n\n"
                f"## 上游变更摘要\n```json\n{upstream_json}\n```\n\n"
                f"## 当前 LLD 状态\n```json\n{current_lld_json}\n```\n\n"
                f"请根据上游变更，生成 mde-turn-result JSON。"
            )

            if progress_callback:
                progress_callback("MDE 正在分析设计影响...")

            if hasattr(self.agent, "generate_interactive_patch"):
                response = self.agent.generate_interactive_patch(
                    current_document=current_lld_json,
                    user_request=user_prompt,
                    system_prompt=system_prompt,
                    turn_schema=turn_schema,
                )
            else:
                response = self.agent.generate_interactive(
                    current_document=current_lld_json,
                    user_request=user_prompt,
                    system_prompt=system_prompt,
                )
            llm_timings = response.timings

            raw_content = response.content if hasattr(response, "content") else str(response)
            json_text = _extract_json(raw_content)

            try:
                turn_data = json.loads(json_text)
            except json.JSONDecodeError as e:
                return self.format_result(status="failed",
                    message=f"LLM 输出的 JSON 无法解析: {e}", reasoning=raw_content)

            if turn_schema:
                turn_errors = self._validate_with_schema(turn_data, turn_schema_path)
                if turn_errors:
                    return self.format_result(status="failed",
                        message=f"MDE turn result schema error: {'; '.join(turn_errors[:3])}",
                        reasoning=raw_content)

            status = turn_data.get("status", "updated")
            if status == "no_change":
                return self.format_result(status="success",
                    message=turn_data.get("message", "无需修改设计。"), reasoning=raw_content)
            if status == "need_clarification":
                return self.format_result(status="success",
                    message=turn_data.get("message", "需要更多信息。"),
                    data={"open_questions": turn_data.get("open_questions", [])},
                    reasoning=raw_content)
            if status == "rejected":
                return self.format_result(status="failed",
                    message=turn_data.get("message", "设计变更请求被拒绝。"),
                    reasoning=raw_content)

            t_apply_start = time.time()
            patches = turn_data.get("patches", [])
            if not patches:
                return self.format_result(status="failed",
                    message="Turn returned 'updated' status but no patches.",
                    reasoning=raw_content)

            updated_lld = self._apply_patches(current_lld or {}, patches)

            lld_schema_path = self.config.repo_path / "schemas" / "lld-schema.json"
            schema_errors = self._validate_with_schema(updated_lld, lld_schema_path)
            if schema_errors:
                return self.format_result(status="failed",
                    message=f"Updated LLD schema error: {'; '.join(schema_errors[:3])}",
                    reasoning=raw_content)

            lld_path.parent.mkdir(parents=True, exist_ok=True)
            lld_path.write_text(
                json.dumps(updated_lld, ensure_ascii=False, indent=2), encoding="utf-8")
            rel_lld = lld_path.relative_to(self.config.repo_path).as_posix()

            from cogniforge.wiki.wiki_renderer import render_file
            html_path = render_file(lld_path)
            rel_html = html_path.relative_to(self.config.repo_path).as_posix() if html_path else ""

            operation = turn_data.get("operation", "modify")
            with self.wiki_system.git_storage.atomic_write():
                self.wiki_system.git_storage.repo.index.add([rel_lld])
                if rel_html:
                    self.wiki_system.git_storage.repo.index.add([rel_html])
                self.wiki_system.git_storage.commit(
                    f"docs: update LLD {module} - {operation}", "design_agent")

            artifacts = [rel_lld]
            if html_path:
                artifacts.append(html_path.relative_to(self.config.repo_path).as_posix())

            t_apply = time.time() - t_apply_start
            t_total = time.time() - t0
            timings = []
            if llm_timings:
                timings.extend(llm_timings)
            timings.append({"phase": "应用变更", "duration_s": round(t_apply, 1)})
            timings.append({"phase": "总计", "duration_s": round(t_total, 1)})

            return self.format_result(
                status="success",
                message=turn_data.get("message", "LLD updated."),
                artifacts=artifacts,
                data={
                    "open_questions": turn_data.get("open_questions", []),
                    "upstream_issues": turn_data.get("upstream_issues", []),
                    "affected_lld_objects": turn_data.get("affected_lld_objects", []),
                    "implementation_handoff": turn_data.get("implementation_handoff", []),
                    "test_handoff": turn_data.get("test_handoff", []),
                    "new_version": updated_lld["meta"].get("version", 1),
                    "timings": timings,
                },
                reasoning=raw_content,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    # ------------------------------------------------------------------
    # Document I/O helpers
    # ------------------------------------------------------------------

    def _load_current_lld(self, module: str) -> dict | None:
        """Load the latest LLD JSON for a module from the wiki path."""
        docs = self.wiki_system.list_documents(DocumentType.LLD, module=module)
        if not docs:
            return None
        latest = docs[-1]
        try:
            return json.loads((self.config.repo_path / Path(latest.path)).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _apply_patches(doc: dict, patches: list[dict]) -> dict:
        """Apply RFC 6902 JSON Patch operations to doc dict."""
        from jsonpatch import JsonPatch
        patch = JsonPatch(patches)
        return patch.apply(doc)

    @staticmethod
    def _validate_with_schema(data: dict, schema_path: Path) -> list[str]:
        """Validate dict against JSON schema. Returns list of error messages."""
        if not schema_path.exists():
            return []
        try:
            import jsonschema
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            validator = jsonschema.Draft7Validator(schema)
            errors = list(validator.iter_errors(data))
            return [e.message for e in errors]
        except ImportError:
            return []
        except Exception as e:
            return [f"Schema validation error: {e}"]

    # SAD component type → ModuleType mapping


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Conditional schema assembler
# ---------------------------------------------------------------------------

_HINTS: dict[str, str] = {
    "service": (
        "- domain_objects 中 entity 的每个 attribute 必须标注 source (db/computed/input/derived)\n"
        "- service_contracts 中每个 method 必须有 precondition/postcondition/exceptions\n"
        "- business_rules 中如有状态实体必须定义状态机，含转换图和不可逆规则\n"
    ),
    "frontend": (
        "- component_tree 中每个组件必须定义 props、events、state、behavior、edge_cases\n"
        "- state_design 必须划分全局状态 vs 页面局部状态\n"
        "- interaction_flows 必须覆盖关键用户旅程\n"
        "- api_integration 必须列出每个页面调用的确切 API endpoint\n"
    ),
    "gateway": (
        "- route_table 必须完整列出每个 path pattern → upstream 映射\n"
        "- middleware_chain 必须标注顺序\n"
        "- auth_policy 的 role_path_map 必须覆盖所有受保护路径\n"
        "- rate_limiting 必须区分全局、每用户、特殊端点三级\n"
    ),
    "database": (
        "- index_strategy 按表列出所有索引的名称、列、类型、用途\n"
        "- migration_strategy 必须声明工具、命名规范和回滚策略\n"
        "- capacity_estimation 必须给出 1 年和 3 年预估数据量\n"
        "- connection_contracts 必须列出各服务账号及其权限矩阵\n"
    ),
    "infrastructure": (
        "- topology 必须包含 exchanges/queues/bindings（MQ）或 namespaces/key_patterns（缓存）或 buckets（文件存储）\n"
        "- 消息队列必须有 message_contracts 和 reliability_strategy\n"
        "- reliability_strategy 必须包含 ack 模式、重试策略、死信和幂等说明\n"
    ),
}


def _type_specific_hints(module_type: str) -> str:
    """Return type-specific prompt hints based on module_type."""
    hints = _HINTS.get(module_type, "")
    if hints:
        return hints + "\n"
    return ""


def _build_conditional_schema(module_type: str) -> str:
    """Return the extra JSON schema sections for the given module type."""
    if module_type == "service":
        return "\n".join([
            _SCHEMA_DOMAIN_OBJECTS,
            _SCHEMA_SERVICE_CONTRACTS,
            _SCHEMA_BUSINESS_RULES,
        ])
    elif module_type == "gateway":
        return _SCHEMA_GATEWAY
    elif module_type == "frontend":
        return "\n".join([
            _SCHEMA_COMPONENT_TREE,
            _SCHEMA_STATE_DESIGN,
            _SCHEMA_ROUTE_DESIGN,
            _SCHEMA_INTERACTION_FLOWS,
            _SCHEMA_API_INTEGRATION,
        ])
    elif module_type == "database":
        return _SCHEMA_DATABASE
    elif module_type == "infrastructure":
        return _SCHEMA_INFRA
    return ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lld_index_by_module(lld_docs: list) -> dict[str, str]:
    """Return {module_name: absolute_disk_path} for the latest LLD per module."""
    index: dict[str, str] = {}
    for d in lld_docs:
        mod = d.path.split("/")[3] if len(d.path.split("/")) > 3 else ""
        if mod:
            index[mod] = d.path
    return index


def _read_lld_json(rel_path: str) -> dict | None:
    from pathlib import Path as _Path
    abs_path = _Path.cwd() / rel_path
    if not abs_path.exists():
        return None
    try:
        from cogniforge.wiki.wiki_renderer import load_json_with_repair
        return load_json_with_repair(abs_path)
    except Exception:
        return None


def _find_iface_by_endpoint(interfaces: list[dict], endpoint: str) -> dict | None:
    target = endpoint.strip().lower()
    for iface in interfaces:
        if target in iface.get("endpoint", "").strip().lower():
            return iface
    return None


def _endpoint_in_contracts(endpoint: str, contracts: list[dict]) -> bool:
    target = endpoint.strip().lower()
    for c in contracts:
        if target in c.get("endpoint", "").strip().lower():
            return True
    return False
