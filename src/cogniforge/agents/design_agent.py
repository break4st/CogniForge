"""Design Agent - MDE Agent for detailed design"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType, ModuleType
from cogniforge.core.exceptions import AgentError


# ---------------------------------------------------------------------------
# Per-module-type JSON schema fragments for the LLM prompt
# ---------------------------------------------------------------------------

_SCHEMA_BASE = """\
{{
  "meta": {{
    "doc_id": "{doc_id}", "type": "lld",
    "module_type": "{module_type}", "module": "{module}",
    "title": "{title}", "author": "design_agent", "created": "{now}"
  }},
  "overview": {{
    "description": "模块概述（string）",
    "dependencies": ["依赖的模块名"],
    "tech_stack": ["技术栈"]
  }}"""

_SCHEMA_DATA_MODELS = """\
  "data_models": [
    {{
      "name": "模型名",
      "type": "table|reference|struct|store|config",
      "ownership": "canonical|derived|owned",
      // ownership=derived 时必须:
      "source": {{"doc_id": "lld-Primary Database-001", "model_name": "表名"}},
      "description": "说明",
      "fields": [
        {{"name": "字段名", "type": "类型", "required": true, "description": "说明"}}
      ],
      // type=table 时必须:
      "indexes": [
        {{"name": "索引名", "unique": false, "columns": ["列名"]}}
      ]
    }}
  ]"""

_SCHEMA_INTERFACES = """\
  "interfaces": [
    {{
      "name": "接口名称",
      "method": "GET|POST|PUT|DELETE|INTERNAL|MQ|WS|frontend",
      "endpoint": "/api/...（不含 HTTP 方法前缀，method 与 endpoint 必须分别填写）",
      "description": "接口说明",
      "parameters": [
        {{"name": "参数名", "type": "类型", "description": "说明"}}
      ],
      "response": {{
        "status": 200,
        "body": {{"字段名": "类型"}}
      }},
      "error_codes": [
        {{"code": 400, "message": "错误说明"}}
      ]
    }}
  ]"""

_SCHEMA_ERROR = """\
  "error_handling": {{
    "strategy": "总体错误处理策略（1-2句）",
    "response_format": {{
      "body": {{"code": "integer", "error": "string", "detail": "string"}}
    }},
    "categories": [
      {{"code": "4xx 或 5xx", "name": "分类名", "description": "触发条件和处理方式"}}
    ]
  }}"""

# ── Module-type-specific sections ──

_SCHEMA_DOMAIN_OBJECTS = """\
  "domain_objects": [
    {{
      "name": "对象名",
      "object_type": "entity|value_object|dto|enum",
      "description": "说明",
      // object_type=entity|value_object|dto 时:
      "attributes": [
        {{"name": "属性名", "type": "类型", "required": true,
          "source": "db|computed|input|derived",
          "description": "说明"}}
      ],
      // object_type=enum 时:
      "values": ["合法值1", "合法值2"],
      // object_type=dto 时:
      "maps_to_entity": "对应的实体名（可选）"
    }}
  ]"""

_SCHEMA_SERVICE_CONTRACTS = """\
  "service_contracts": [
    {{
      "name": "服务类名（如 ProjectService）",
      "description": "服务职责（一句话）",
      "methods": [
        {{
          "name": "方法名（驼峰）",
          "signature": "(param: Type, ...) -> ReturnType",
          "precondition": "调用前必须满足的条件",
          "postcondition": "调用后的结果",
          "description": "行为描述（一句话）",
          "exceptions": [
            {{"name": "异常类名", "trigger": "触发条件", "http_status": 409}}
          ]
        }}
      ],
      "repository_dependencies": [
        "findByNameAndCreatedBy(name, userId) -> Project?",
        "existsActiveDeployment(projectId) -> boolean"
      ]
    }}
  ]"""

_SCHEMA_BUSINESS_RULES = """\
  "business_rules": {{
    "invariants": [
      "必须始终为真的业务规则描述"
    ],
    "state_machines": [
      {{
        "entity": "实体名",
        "states": ["状态1", "状态2"],
        "transitions": [
          {{"from": "状态1", "to": "状态2", "trigger": "触发事件", "actor": "执行者"}}
        ],
        "irreversible_rules": ["不可逆的状态转换规则"],
        "concurrency": "并发控制说明"
      }}
    ],
    "cross_service_rules": [
      "跨服务协同规则描述"
    ]
  }}"""

# ── Frontend-specific ──

_SCHEMA_COMPONENT_TREE = """\
  "component_tree": [
    {{
      "name": "组件名",
      "path": "所在路由",
      "description": "组件职责（一句话）",
      "props": [
        {{"name": "prop名", "type": "类型", "required": true, "description": "说明"}}
      ],
      "events": [
        {{"name": "事件名", "payload_type": "载荷类型"}}
      ],
      "state": [
        {{"name": "状态字段名", "type": "类型", "description": "说明"}}
      ],
      "behavior": [
        "交互行为描述（如 mount 时发起请求）"
      ],
      "edge_cases": [
        "边界情况处理描述"
      ],
      "children": [
        // 递归同结构
      ]
    }}
  ]"""

_SCHEMA_STATE_DESIGN = """\
  "state_design": {{
    "global": [
      {{"name": "状态名", "type": "类型", "description": "说明",
        "consumers": ["消费该状态的组件名"]}}
    ],
    "caching_strategy": "缓存策略描述"
  }}"""

_SCHEMA_ROUTE_DESIGN = """\
  "route_design": [
    {{
      "path": "/路由路径",
      "page": "页面组件名",
      "title": "页面标题",
      "auth": "all|admin,operator|admin",
      "layout": "default|blank"
    }}
  ]"""

_SCHEMA_INTERACTION_FLOWS = """\
  "interaction_flows": [
    {{
      "name": "流程名（如：一键部署流程）",
      "description": "流程概述",
      "steps": [
        "步骤1: 具体操作描述"
      ]
    }}
  ]"""

_SCHEMA_API_INTEGRATION = """\
  "api_integration": [
    {{
      "page": "页面组件名",
      "endpoint": "GET /api/...",
      "maps_to": "目标组件或状态字段"
    }}
  ]"""

# ── Gateway-specific ──

_SCHEMA_GATEWAY = """\
  "route_table": [
    {{
      "path_pattern": "/api/projects/**",
      "upstream": "上游服务名",
      "description": "说明"
    }}
  ],
  "middleware_chain": [
    "Request → Auth → RateLimiter → Router → Upstream"
  ],
  "auth_policy": {{
    "public_endpoints": ["/api/login", "/api/health"],
    "auth_method": "JWT Bearer Token",
    "role_path_map": [
      {{"path": "GET /api/audit-logs", "roles": ["admin"]}},
      {{"path": "POST /api/keys", "roles": ["admin", "operator"]}}
    ],
    "token_expiry": "access 2h, refresh 7d"
  }},
  "rate_limiting": {{
    "global": "每 IP 100 req/s",
    "per_user": "每 user 1000 req/min",
    "special_endpoints": [
      {{"endpoint": "POST /api/deployments", "limit": "每 user 10 req/min"}}
    ]
  }}"""

# ── Database-specific ──

_SCHEMA_DATABASE = """\
  "index_strategy": [
    {{
      "table": "表名",
      "indexes": [
        {{"name": "idx_xxx", "columns": ["col1", "col2"], "unique": false,
          "type": "B-tree|GIN|GIST", "purpose": "用途"}}
      ]
    }}
  ],
  "migration_strategy": {{
    "tool": "Flyway|Liquibase|Alembic",
    "naming": "V{序号}__{描述}.sql",
    "rollback": "回滚策略说明"
  }},
  "capacity_estimation": {{
    "estimated_rows_1y": "预估1年数据量",
    "estimated_rows_3y": "预估3年数据量",
    "hot_tables": ["高频读写表名"],
    "partition_strategy": "分区策略（如有）"
  }},
  "connection_contracts": {{
    "pool_size": "连接池大小",
    "timeout": "连接超时",
    "service_accounts": [
      {{"service": "服务名", "db_user": "账号", "privileges": ["SELECT", "INSERT"]}}
    ]
  }}"""

# ── Infrastructure-specific ──

_SCHEMA_INFRA = """\
  // 消息队列类:
  "topology": {{
    "exchanges": [
      {{"name": "exchange名", "type": "direct|topic|fanout", "durable": true,
        "bindings": [{{"queue": "队列名", "routing_key": "routing key"}}]}}
    ],
    "queues": [
      {{"name": "队列名", "durable": true, "ttl_seconds": 86400, "max_length": 10000}}
    ],
    "producer_consumer_map": [
      {{"producer": "生产者服务", "consumer": "消费者服务", "exchange": "exchange名"}}
    ]
  }},
  "message_contracts": [
    {{
      "name": "消息名",
      "exchange": "exchange名",
      "routing_key": "routing key",
      "schema": {{"字段名": "类型"}},
      "required_fields": ["必填字段"],
      "max_size_bytes": 1048576
    }}
  ],
  "reliability_strategy": {{
    "ack_mode": "manual",
    "retry": {{"max_retries": 3, "backoff": "exponential"}},
    "dead_letter": "死信队列名",
    "idempotency": "幂等性保证方式"
  }}
  // 缓存类:
  // "topology": {{"namespaces": [...], "key_patterns": [...], "expiry_strategy": "..."}},
  // "connection_contracts": {{...}}
  // 文件存储类:
  // "topology": {{"buckets": [...], "path_conventions": "..."}},
  // "connection_contracts": {{...}}
"""

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

            module_type = self._resolve_module_type(module)
            contract_context = self._build_contract_context(module, module_type)
            ownership_rules = _OWNERSHIP_RULES.get(module_type, _OWNERSHIP_RULES["service"])
            conditional_schema = _build_conditional_schema(module_type)

            prompt = (
                f"根据以下数据创建一份详细设计文档 (LLD)，以 JSON 格式输出并写入:\n\n"
                f"输出路径: {json_path}\n"
                f"JSON 结构:\n"
                f"{_SCHEMA_BASE}\n"
                f"{_SCHEMA_DATA_MODELS}\n"
                f"{_SCHEMA_INTERFACES}\n"
                f"{_SCHEMA_ERROR}\n"
                + (f"{conditional_schema}\n" if conditional_schema else "")
                + f"\n重要:\n"
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
                f"1. 以上 prompt 已包含本模块 SAD 定义、接口契约、邻模块接口签名，无需额外读取\n"
                f"2. 如需更完整背景（PRD 全文、其他模块完整 LLD），可选择性 Read 相关文件\n"
                f"3. 接口契约约束:\n"
                f"   - provider 契约: 你必须实现这些接口，response body 字段名与类型不可修改\n"
                f"   - consumer 契约: 引用这些接口的确切 endpoint 与字段，不要自造变体\n"
                f"4. 各模块类型要求的章节必须完整填写，不可省略\n"
                + _type_specific_hints(module_type)
                + f"使用中文、只写 JSON 不写 HTML、完成后回复确认"
            )

            response = self.agent.generate_agentic(prompt, role="design")

            # ── Validation loop (max 2 retries) ──
            correction_attempts = 0
            max_corrections = 2
            validation_report = ""

            while correction_attempts <= max_corrections:
                json_abs = Path(self.config.repo_path) / json_path
                if not json_abs.exists():
                    return self.format_result(
                        status="failed",
                        message=f"LLM did not produce {json_path}"
                    )

                from cogniforge.lld_validator import validate_lld_json, format_validation_report
                validation = validate_lld_json(json_abs)
                validation_report = format_validation_report(validation)

                if validation["passed"]:
                    break

                if correction_attempts < max_corrections:
                    correction_attempts += 1
                    fix_prompt = (
                        f"你刚才生成的 LLD JSON 校验未通过：\n\n"
                        f"{validation_report}\n\n"
                        f"请修正以上所有问题，重新输出完整的 JSON 到路径: {json_path}\n"
                        f"只输出修正后的完整 JSON，保留所有章节，不要省略。"
                    )
                    response = self.agent.generate_agentic(fix_prompt, role="design")
                else:
                    break

            return self._commit_and_result(
                json_path, title, response.content,
                validation=validation_report,
                correction_attempts=correction_attempts,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

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
            try:
                return ModuleType(my_comp.get("type", "service"))
            except ValueError:
                return ModuleType.SERVICE
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
                           validation: str = "", correction_attempts: int = 0) -> dict:
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
