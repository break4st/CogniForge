"""Decomposition rules — one rule-set per module_type.

Each rule-set defines how to map LLDArtifactRegistry entries into TaskStub
skeletons.  Rules are pure (no LLM, no I/O) and independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cogniforge.wbs.lld_artifact_registry import LLDArtifactRegistry


@dataclass
class TaskStub:
    """Mechanically-derived task skeleton — LLM fills in the details later."""
    suggested_name: str
    category: str                        # TaskCategory value
    lld_refs: list[dict] = field(default_factory=list)
    description_guide: str = ""
    section_data: dict = field(default_factory=dict)
    inferred_deps: list[str] = field(default_factory=list)  # stub names, resolved later
    confidence: str = "high"
    expected_output_files: list[str] = field(default_factory=list)
    layer: int = 0                       # 0=model, 1=service, 2=endpoint, 3=test


def _mk_ref(entry) -> dict:
    """Build a dict suitable for LLDReference construction from an ArtifactEntry."""
    return {
        "section": entry.section,
        "item_name": entry.item_name,
        "artifact_type": entry.artifact_type,
    }


def decompose(registry: "LLDArtifactRegistry") -> list[TaskStub]:
    """Dispatch to the correct rule-set based on module_type."""
    mt = registry.module_type
    dispatcher = {
        "service":        _service_rules,
        "database":       _database_rules,
        "gateway":        _gateway_rules,
        "frontend":       _frontend_rules,
        "infrastructure": _infra_rules,
    }
    handler = dispatcher.get(mt, _service_rules)
    return handler(registry)


# ═══════════════════════════════════════════════════════════════════════
# Service
# ═══════════════════════════════════════════════════════════════════════

def _service_rules(reg) -> list[TaskStub]:
    stubs: list[TaskStub] = []

    # ── Layer 0: data_models (owned / non-derived) ──
    dm_stubs = []
    for e in reg.iter_section("data_models"):
        if e.ownership == "derived":
            continue  # derived models live with the canonical owner's task
        st = TaskStub(
            suggested_name=f"定义 {e.item_name} 数据模型",
            category="model",
            lld_refs=[_mk_ref(e)],
            description_guide=f"实现 {e.item_name} 结构体/类，字段: {', '.join(e.sub_items[:8])}",
            section_data={"data_model": e.item_data},
            expected_output_files=[f"src/{_safe_module(reg.module)}/models/{_safe_file(e.item_name)}.go"],
            layer=0,
        )
        dm_stubs.append(st)
    stubs.extend(dm_stubs)

    # ── Layer 0: domain_objects ──
    do_stubs = []
    enums: list[dict] = []
    for e in reg.iter_section("domain_objects"):
        if "enum" in e.artifact_type:
            enums.append(e)
            continue
        layer = 0
        files = [f"src/{_safe_module(reg.module)}/models/{_safe_file(e.item_name)}.go"]
        do_stubs.append(TaskStub(
            suggested_name=f"定义 {e.item_name} 领域对象",
            category="model",
            lld_refs=[_mk_ref(e)],
            description_guide=f"实现 {e.item_name} ({e.artifact_type}), 属性: {', '.join(e.sub_items[:10])}",
            section_data={"domain_object": e.item_data},
            expected_output_files=files,
            layer=layer,
        ))
    # Merge enums into one task
    if enums:
        do_stubs.append(TaskStub(
            suggested_name="定义枚举类型",
            category="model",
            lld_refs=[_mk_ref(e) for e in enums],
            description_guide="定义所有枚举类型: " + ", ".join(e.item_name for e in enums),
            section_data={"enums": [e.item_data for e in enums]},
            expected_output_files=[f"src/{_safe_module(reg.module)}/models/enums.go"],
            layer=0,
        ))
    stubs.extend(do_stubs)

    # ── Layer 1: service_contracts ──
    svc_stubs = []
    for e in reg.iter_section("service_contracts"):
        methods = e.item_data.get("methods", [])
        n_methods = len(methods)
        if n_methods <= 3:
            svc_stubs.append(_svc_stub(reg, e, methods))
        else:
            # Split by groups of ~3 methods
            for i in range(0, n_methods, 3):
                chunk = methods[i:i + 3]
                svc_stubs.append(_svc_stub(reg, e, chunk, suffix=f" (part {i // 3 + 1})"))
    stubs.extend(svc_stubs)

    # ── Layer 1: business rules (invariants + state machines) ──
    br_stubs = []
    inv_entries = [e for e in reg.iter_section("business_rules") if e.artifact_type == "business_rule_invariant"]
    if inv_entries:
        br_stubs.append(TaskStub(
            suggested_name="实现业务不变量校验",
            category="service",
            lld_refs=[_mk_ref(e) for e in inv_entries],
            description_guide="实现以下业务规则:\n" + "\n".join(f"  - {e.item_data.get('rule','')}" for e in inv_entries),
            section_data={"invariants": [e.item_data.get("rule", "") for e in inv_entries]},
            inferred_deps=[s.suggested_name for s in svc_stubs],
            expected_output_files=[f"src/{_safe_module(reg.module)}/service/validation.go"],
            layer=1,
        ))

    sm_entries = [e for e in reg.iter_section("business_rules") if e.artifact_type == "state_machine"]
    for sm in sm_entries:
        br_stubs.append(TaskStub(
            suggested_name=f"实现 {sm.item_name} 状态机",
            category="service",
            lld_refs=[_mk_ref(sm)],
            description_guide=(
                f"实现 {sm.item_name} 状态机: "
                f"状态={sm.item_data.get('states', [])}, "
                f"转换={sm.sub_items}"
            ),
            section_data={"state_machine": sm.item_data},
            inferred_deps=[s.suggested_name for s in svc_stubs],
            expected_output_files=[f"src/{_safe_module(reg.module)}/service/state_machine.go"],
            layer=1,
        ))
    stubs.extend(br_stubs)

    # ── Layer 2: interfaces ──
    iface_stubs = []
    for e in reg.iter_section("interfaces"):
        iface_stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name} 接口",
            category="endpoint",
            lld_refs=[_mk_ref(e)],
            description_guide=(
                f"实现 {e.item_data.get('method','')} {e.item_data.get('endpoint','')}: "
                f"{e.item_data.get('description','')}"
            ),
            section_data={"interface": e.item_data},
            inferred_deps=[s.suggested_name for s in svc_stubs],
            expected_output_files=[f"src/{_safe_module(reg.module)}/handler/{_safe_file(e.item_name)}.go"],
            layer=2,
        ))
    stubs.extend(iface_stubs)

    # ── Layer 2: cross-service rules ──
    csr_entries = [e for e in reg.iter_section("business_rules") if e.artifact_type == "cross_service_rule"]
    if csr_entries:
        stubs.append(TaskStub(
            suggested_name="实现跨服务协同规则",
            category="service",
            lld_refs=[_mk_ref(e) for e in csr_entries],
            description_guide="实现跨服务规则:\n" + "\n".join(f"  - {e.item_data.get('rule','')}" for e in csr_entries),
            section_data={"cross_service_rules": [e.item_data.get("rule", "") for e in csr_entries]},
            inferred_deps=[s.suggested_name for s in iface_stubs],
            expected_output_files=[],
            layer=2,
        ))

    # ── Layer 3: tests (one per implementation stub) ──
    impl_stubs = [s for s in stubs if s.category in ("model", "service", "endpoint")]
    for s in impl_stubs:
        test_name = f"测试 {s.suggested_name}"
        test_file = _test_file_from(s.expected_output_files)
        stubs.append(TaskStub(
            suggested_name=test_name,
            category="test",
            lld_refs=list(s.lld_refs),  # share refs
            description_guide=f"为 {s.suggested_name} 编写单元测试，覆盖正常路径和边界情况",
            section_data={},
            inferred_deps=[s.suggested_name],
            expected_output_files=test_file,
            layer=3,
        ))

    return stubs


def _svc_stub(reg, entry, methods, suffix="") -> TaskStub:
    names = [m.get("name", "?") for m in methods]
    return TaskStub(
        suggested_name=f"实现 {entry.item_name}{suffix}",
        category="service",
        lld_refs=[_mk_ref(entry)],
        description_guide=(
            f"实现 {entry.item_name} 服务方法: {', '.join(names)}\n"
            + "\n".join(
                f"  - {m.get('name','')}: {m.get('signature','')} "
                f"pre={m.get('precondition','')[:60]}"
                for m in methods
            )
        ),
        section_data={"service_contract": entry.item_data, "methods": methods},
        expected_output_files=[f"src/{_safe_module(reg.module)}/service/{_safe_file(entry.item_name)}.go"],
        layer=1,
    )


# ═══════════════════════════════════════════════════════════════════════
# Database
# ═══════════════════════════════════════════════════════════════════════

def _database_rules(reg) -> list[TaskStub]:
    stubs: list[TaskStub] = []

    # tables
    table_entries = list(reg.iter_section("data_models"))
    for e in table_entries:
        if e.ownership != "canonical":
            continue
        stubs.append(TaskStub(
            suggested_name=f"创建 {e.item_name} 表",
            category="migration",
            lld_refs=[_mk_ref(e)],
            description_guide=f"编写 {e.item_name} 表的 migration 脚本, 字段: {', '.join(e.sub_items[:10])}",
            section_data={"table": e.item_data},
            expected_output_files=[f"migrations/V001__{_safe_file(e.item_name)}.sql"],
            layer=0,
        ))

    # indexes
    idx_entries = list(reg.iter_section("index_strategy"))
    for e in idx_entries:
        stubs.append(TaskStub(
            suggested_name=f"创建 {e.item_name} 索引",
            category="migration",
            lld_refs=[_mk_ref(e)],
            description_guide=f"为 {e.item_name} 创建索引: {', '.join(e.sub_items)}",
            section_data={"indexes": e.item_data},
            expected_output_files=[f"migrations/V002__{_safe_file(e.item_name)}_indexes.sql"],
            layer=1,
            inferred_deps=[f"创建 {e.item_name} 表"],
        ))

    # migration framework init
    for e in reg.iter_section("migration_strategy"):
        stubs.append(TaskStub(
            suggested_name="配置数据库迁移框架",
            category="config",
            lld_refs=[_mk_ref(e)],
            description_guide=f"配置 {e.item_data.get('tool','')} 迁移工具, 命名规范: {e.item_data.get('naming','')}",
            section_data={"migration_strategy": e.item_data},
            expected_output_files=[],
            layer=0,
        ))

    # connection contracts
    for e in reg.iter_section("connection_contracts"):
        stubs.append(TaskStub(
            suggested_name="配置数据库连接和服务账号",
            category="config",
            lld_refs=[_mk_ref(e)],
            description_guide=f"配置连接池: {e.item_data.get('pool_size','')}, 超时: {e.item_data.get('timeout','')}",
            section_data={"connection_contracts": e.item_data},
            expected_output_files=[],
            layer=0,
        ))

    # capacity doc
    for e in reg.iter_section("capacity_estimation"):
        stubs.append(TaskStub(
            suggested_name="编写容量预估文档",
            category="doc",
            lld_refs=[_mk_ref(e)],
            description_guide=f"1年预估: {e.item_data.get('estimated_rows_1y','')}, 3年预估: {e.item_data.get('estimated_rows_3y','')}",
            section_data={"capacity": e.item_data},
            expected_output_files=[],
            layer=1,
        ))

    # test stubs
    impl_stubs = [s for s in stubs if s.category in ("migration", "config")]
    for s in impl_stubs:
        stubs.append(TaskStub(
            suggested_name=f"测试 {s.suggested_name}",
            category="test",
            lld_refs=list(s.lld_refs),
            description_guide=f"验证 {s.suggested_name} 是否正确执行",
            section_data={},
            inferred_deps=[s.suggested_name],
            expected_output_files=[],
            layer=3,
        ))

    return stubs


# ═══════════════════════════════════════════════════════════════════════
# Gateway
# ═══════════════════════════════════════════════════════════════════════

def _gateway_rules(reg) -> list[TaskStub]:
    stubs: list[TaskStub] = []

    # routes
    route_entries = list(reg.iter_section("route_table"))
    if route_entries:
        stubs.append(TaskStub(
            suggested_name="配置网关路由表",
            category="service",
            lld_refs=[_mk_ref(e) for e in route_entries],
            description_guide=f"配置 {len(route_entries)} 条路由规则",
            section_data={"route_table": [e.item_data for e in route_entries]},
            expected_output_files=[f"src/{_safe_module(reg.module)}/routes.go"],
            layer=0,
        ))

    # middleware
    for e in reg.iter_section("middleware_chain"):
        stubs.append(TaskStub(
            suggested_name="实现中间件链",
            category="service",
            lld_refs=[_mk_ref(e)],
            description_guide=f"实现中间件链: {e.item_data.get('chain', [])}",
            section_data={"middleware_chain": e.item_data},
            expected_output_files=[f"src/{_safe_module(reg.module)}/middleware.go"],
            layer=0,
        ))

    # auth
    for e in reg.iter_section("auth_policy"):
        stubs.append(TaskStub(
            suggested_name="实现认证授权策略",
            category="service",
            lld_refs=[_mk_ref(e)],
            description_guide=f"认证方式: {e.item_data.get('auth_method','')}, 公开端点: {e.sub_items}",
            section_data={"auth_policy": e.item_data},
            expected_output_files=[f"src/{_safe_module(reg.module)}/auth.go"],
            layer=1,
        ))

    # rate limiting
    for e in reg.iter_section("rate_limiting"):
        stubs.append(TaskStub(
            suggested_name="实现限流策略",
            category="config",
            lld_refs=[_mk_ref(e)],
            description_guide=f"全局限流: {e.item_data.get('global','')}, 用户限流: {e.item_data.get('per_user','')}",
            section_data={"rate_limiting": e.item_data},
            expected_output_files=[f"src/{_safe_module(reg.module)}/rate_limiter.go"],
            layer=1,
        ))

    # interfaces
    for e in reg.iter_section("interfaces"):
        stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name}",
            category="endpoint",
            lld_refs=[_mk_ref(e)],
            description_guide=f"实现 {e.item_data.get('method','')} {e.item_data.get('endpoint','')}",
            section_data={"interface": e.item_data},
            expected_output_files=[f"src/{_safe_module(reg.module)}/handler/{_safe_file(e.item_name)}.go"],
            layer=2,
        ))

    # tests
    impl_stubs = [s for s in stubs if s.category != "test"]
    for s in impl_stubs:
        stubs.append(TaskStub(
            suggested_name=f"测试 {s.suggested_name}",
            category="test",
            lld_refs=list(s.lld_refs),
            description_guide=f"验证 {s.suggested_name}",
            section_data={},
            inferred_deps=[s.suggested_name],
            expected_output_files=[],
            layer=3,
        ))

    return stubs


# ═══════════════════════════════════════════════════════════════════════
# Frontend
# ═══════════════════════════════════════════════════════════════════════

def _frontend_rules(reg) -> list[TaskStub]:
    stubs: list[TaskStub] = []

    for e in reg.iter_section("component_tree"):
        stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name} 组件",
            category="service",
            lld_refs=[_mk_ref(e)],
            description_guide=f"实现 {e.item_name} 组件, props: {e.item_data.get('props', [])}",
            section_data={"component": e.item_data},
            expected_output_files=[],
            layer=0,
        ))

    for e in reg.iter_section("state_design"):
        stubs.append(TaskStub(
            suggested_name="实现全局状态管理",
            category="service",
            lld_refs=[_mk_ref(e)],
            description_guide=f"实现状态管理, 缓存策略: {e.item_data.get('caching_strategy','')}",
            section_data={"state_design": e.item_data},
            expected_output_files=[],
            layer=0,
        ))

    for e in reg.iter_section("route_design"):
        stubs.append(TaskStub(
            suggested_name=f"配置路由 {e.item_name}",
            category="config",
            lld_refs=[_mk_ref(e)],
            description_guide=f"配置路由 {e.item_name}, 页面: {e.item_data.get('page','')}",
            section_data={"route": e.item_data},
            expected_output_files=[],
            layer=1,
        ))

    for e in reg.iter_section("interaction_flows"):
        stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name} 交互流程",
            category="service",
            lld_refs=[_mk_ref(e)],
            description_guide=f"实现交互流程, 步骤: {e.item_data.get('steps', [])}",
            section_data={"interaction_flow": e.item_data},
            expected_output_files=[],
            layer=1,
        ))

    for e in reg.iter_section("api_integration"):
        stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name} API 集成",
            category="endpoint",
            lld_refs=[_mk_ref(e)],
            description_guide=f"集成 API: {e.item_data.get('endpoint','')}",
            section_data={"api_integration": e.item_data},
            expected_output_files=[],
            layer=2,
        ))

    # tests
    impl_stubs = [s for s in stubs if s.category != "test"]
    for s in impl_stubs:
        stubs.append(TaskStub(
            suggested_name=f"测试 {s.suggested_name}",
            category="test",
            lld_refs=list(s.lld_refs),
            description_guide=f"验证 {s.suggested_name}",
            section_data={},
            inferred_deps=[s.suggested_name],
            expected_output_files=[],
            layer=3,
        ))

    return stubs


# ═══════════════════════════════════════════════════════════════════════
# Infrastructure
# ═══════════════════════════════════════════════════════════════════════

def _infra_rules(reg) -> list[TaskStub]:
    stubs: list[TaskStub] = []

    # topology
    for e in reg.iter_section("topology"):
        atype = e.artifact_type
        label = {"exchange": "Exchange", "queue": "Queue", "namespace": "Namespace", "bucket": "Bucket"}.get(atype, atype)
        stubs.append(TaskStub(
            suggested_name=f"定义 {label} {e.item_name}",
            category="config",
            lld_refs=[_mk_ref(e)],
            description_guide=f"定义 {label} {e.item_name}",
            section_data={"topology_item": e.item_data},
            expected_output_files=[],
            layer=0,
        ))

    # message contracts
    for e in reg.iter_section("message_contracts"):
        stubs.append(TaskStub(
            suggested_name=f"定义消息契约 {e.item_name}",
            category="service",
            lld_refs=[_mk_ref(e)],
            description_guide=f"定义消息 schema: {e.item_data.get('schema', {})}",
            section_data={"message_contract": e.item_data},
            expected_output_files=[],
            layer=0,
        ))

    # reliability strategy
    for e in reg.iter_section("reliability_strategy"):
        stubs.append(TaskStub(
            suggested_name="实现消息可靠性策略",
            category="service",
            lld_refs=[_mk_ref(e)],
            description_guide=f"ack模式: {e.item_data.get('ack_mode','')}, 重试: {e.item_data.get('retry',{})}",
            section_data={"reliability": e.item_data},
            expected_output_files=[],
            layer=1,
        ))

    # data_models (config type)
    for e in reg.iter_section("data_models"):
        stubs.append(TaskStub(
            suggested_name=f"定义 {e.item_name} 配置",
            category="config",
            lld_refs=[_mk_ref(e)],
            description_guide=f"定义 {e.item_name} 配置结构",
            section_data={"data_model": e.item_data},
            expected_output_files=[],
            layer=0,
        ))

    # interfaces
    for e in reg.iter_section("interfaces"):
        stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name}",
            category="endpoint",
            lld_refs=[_mk_ref(e)],
            description_guide=f"实现 {e.item_data.get('method','')} {e.item_data.get('endpoint','')}",
            section_data={"interface": e.item_data},
            expected_output_files=[],
            layer=2,
        ))

    # tests
    impl_stubs = [s for s in stubs if s.category != "test"]
    for s in impl_stubs:
        stubs.append(TaskStub(
            suggested_name=f"测试 {s.suggested_name}",
            category="test",
            lld_refs=list(s.lld_refs),
            description_guide=f"验证 {s.suggested_name}",
            section_data={},
            inferred_deps=[s.suggested_name],
            expected_output_files=[],
            layer=3,
        ))

    return stubs


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _safe_module(module: str) -> str:
    """Convert Chinese module name to a filesystem-safe slug."""
    return module.lower().replace(" ", "_").replace("（", "").replace("）", "")


def _safe_file(name: str) -> str:
    """Convert an artifact name to a safe file name stem."""
    return name.lower().replace(" ", "_").replace("/", "_").replace("（", "").replace("）", "")


def _test_file_from(output_files: list[str]) -> list[str]:
    """Derive test file paths from implementation file paths."""
    tests: list[str] = []
    for f in output_files:
        if f.startswith("src/"):
            rel = f[4:]  # strip src/
            parts = rel.split("/")
            tests.append(f"tests/{'/'.join(parts[:-1])}/{parts[-1].replace('.go', '_test.go')}")
        else:
            tests.append(f)
    return tests
