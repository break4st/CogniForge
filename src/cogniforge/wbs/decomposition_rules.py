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

    # ── New: hard constraints (rule-generated, never touched by LLM) ──
    source: dict | None = None           # Traceability: {prd_doc_id, sad_doc_id, lld_doc_id, ...}
    allowed_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    acceptance_criteria: list[dict] = field(default_factory=list)
    validation_commands: list[dict] = field(default_factory=list)
    file_locks: list[str] = field(default_factory=list)


# Note: _mk_ref now uses registry info for module + doc_id.
# Regenerated below; kept here for doc reference.




def _mk_ref(entry, registry=None) -> dict:
    """Build a dict suitable for LLDReference construction from an ArtifactEntry.

    When registry is provided, module and doc_id are sourced from it.
    """
    ref = {
        "section": entry.section,
        "item_name": entry.item_name,
        "artifact_type": entry.artifact_type,
    }
    if registry is not None:
        ref["module"] = registry.module
        ref["doc_id"] = registry.doc_id
    return ref


DEFAULT_FORBIDDEN_PATHS = [
    ".cogniforge/wiki/",
    "schemas/",
    "CLAUDE.md",
    "DESIGN.html",
    "FLOWCHARTS.html",
    "README.md",
]


def _default_forbidden_paths() -> list[str]:
    """Paths that no DEV task should ever modify."""
    return list(DEFAULT_FORBIDDEN_PATHS)


def decompose(registry: "LLDArtifactRegistry",
              conventions: dict | None = None) -> list[TaskStub]:
    """Dispatch to the correct rule-set based on module_type."""
    if conventions is None:
        conventions = _default_conventions()
    mt = registry.module_type
    dispatcher = {
        "service":        _service_rules,
        "database":       _database_rules,
        "gateway":        _gateway_rules,
        "frontend":       _frontend_rules,
        "infrastructure": _infra_rules,
    }
    handler = dispatcher.get(mt, _service_rules)
    return handler(registry, conventions)


def _default_conventions() -> dict:
    """Minimal conventions dict for backward compatibility when none is provided."""
    return {
        "language": "python",
        "src_dir": "src",
        "test_dir": "tests",
        "file_ext": ".py",
        "migration_dir": "migrations",
    }


# ═══════════════════════════════════════════════════════════════════════
# Service
# ═══════════════════════════════════════════════════════════════════════

def _service_rules(reg, conventions: dict) -> list[TaskStub]:
    stubs: list[TaskStub] = []
    safe_mod = _safe_module(reg.module)
    src = conventions.get("src_dir", "src")
    test = conventions.get("test_dir", "tests")
    ext = conventions.get("file_ext", ".py")
    doc_id = reg.doc_id

    # ── Layer 0: data_models (owned / non-derived) ──
    dm_stubs = []
    for e in reg.iter_section("data_models"):
        if e.ownership == "derived":
            continue
        ofiles = _output_file("model", reg.module, e.item_name, conventions)
        st = TaskStub(
            suggested_name=f"定义 {e.item_name} 数据模型",
            category="model",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"实现 {e.item_name} 结构体/类，字段: {', '.join(e.sub_items[:8])}",
            section_data={"data_model": e.item_data},
            expected_output_files=ofiles,
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-{e.item_name}",
                "source_section": "data_models",
                "source_item": e.item_name,
                "description": f"{e.item_name} 包含所有必需字段: {', '.join(e.sub_items[:8])}",
                "verification_type": "unit_test",
                "expected": "所有字段可正常读写",
            }],
            validation_commands=[{
                "name": f"测试 {e.item_name} 模型",
                "command": f"pytest {test}/{safe_mod}/test_{_safe_file(e.item_name)}{ext} -v",
                "timeout_seconds": 60,
            }],
        )
        dm_stubs.append(st)
    stubs.extend(dm_stubs)

    # ── Layer 0: domain_objects ──
    do_stubs = []
    enums: list = []
    for e in reg.iter_section("domain_objects"):
        if "enum" in e.artifact_type:
            enums.append(e)
            continue
        ofiles = _output_file("model", reg.module, e.item_name, conventions)
        do_stubs.append(TaskStub(
            suggested_name=f"定义 {e.item_name} 领域对象",
            category="model",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"实现 {e.item_name} ({e.artifact_type}), 属性: {', '.join(e.sub_items[:10])}",
            section_data={"domain_object": e.item_data},
            expected_output_files=ofiles,
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-{e.item_name}",
                "source_section": "domain_objects",
                "source_item": e.item_name,
                "description": f"{e.item_name} 领域对象属性完整且类型正确",
                "verification_type": "unit_test",
                "expected": "所有属性按设计类型存取",
            }],
            validation_commands=[{
                "name": f"测试 {e.item_name}",
                "command": f"pytest {test}/{safe_mod}/test_{_safe_file(e.item_name)}{ext} -v",
                "timeout_seconds": 60,
            }],
        ))
    if enums:
        ofile = [f"{src}/{safe_mod}/models/enums{ext}"]
        do_stubs.append(TaskStub(
            suggested_name="定义枚举类型",
            category="model",
            lld_refs=[_mk_ref(e, reg) for e in enums],
            description_guide="定义所有枚举类型: " + ", ".join(e.item_name for e in enums),
            section_data={"enums": [e.item_data for e in enums]},
            expected_output_files=ofile,
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofile,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofile),
            acceptance_criteria=[{
                "id": "AC-enums",
                "source_section": "domain_objects",
                "source_item": "enums",
                "description": f"枚举值集合完整: {', '.join(e.item_name for e in enums)}",
                "verification_type": "unit_test",
                "expected": "所有枚举值可正常创建和比较",
            }],
            validation_commands=[{
                "name": "测试枚举类型",
                "command": f"pytest {test}/{safe_mod}/test_enums{ext} -v",
                "timeout_seconds": 60,
            }],
        ))
    stubs.extend(do_stubs)

    # ── Layer 1: service_contracts ──
    svc_stubs = []
    for e in reg.iter_section("service_contracts"):
        methods = e.item_data.get("methods", [])
        n_methods = len(methods)
        if n_methods <= 3:
            svc_stubs.append(_svc_stub(reg, e, methods, conventions))
        else:
            for i in range(0, n_methods, 3):
                chunk = methods[i:i + 3]
                svc_stubs.append(_svc_stub(reg, e, chunk, conventions, suffix=f" (part {i // 3 + 1})"))
    stubs.extend(svc_stubs)

    # ── Layer 1: business rules (invariants + state machines) ──
    br_stubs = []
    inv_entries = [e for e in reg.iter_section("business_rules") if e.artifact_type == "business_rule_invariant"]
    if inv_entries:
        ofile = [f"{src}/{safe_mod}/services/validation{ext}"]
        br_stubs.append(TaskStub(
            suggested_name="实现业务不变量校验",
            category="service",
            lld_refs=[_mk_ref(e, reg) for e in inv_entries],
            description_guide="实现以下业务规则:\n" + "\n".join(f"  - {e.item_data.get('rule','')}" for e in inv_entries),
            section_data={"invariants": [e.item_data.get("rule", "") for e in inv_entries]},
            inferred_deps=[s.suggested_name for s in svc_stubs],
            expected_output_files=ofile,
            layer=1,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofile,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofile),
            acceptance_criteria=[{
                "id": f"AC-invariant-{i}",
                "source_section": "business_rules",
                "source_item": e.item_name,
                "description": f"不变量校验: {e.item_data.get('rule','')}",
                "verification_type": "unit_test",
                "expected": "违反不变量的操作被拒绝",
            } for i, e in enumerate(inv_entries)],
            validation_commands=[{
                "name": "测试业务规则",
                "command": f"pytest {test}/{safe_mod}/test_validation{ext} -v",
                "timeout_seconds": 120,
            }],
        ))

    sm_entries = [e for e in reg.iter_section("business_rules") if e.artifact_type == "state_machine"]
    for sm in sm_entries:
        ofile = [f"{src}/{safe_mod}/services/{_safe_file(sm.item_name)}_sm{ext}"]
        br_stubs.append(TaskStub(
            suggested_name=f"实现 {sm.item_name} 状态机",
            category="service",
            lld_refs=[_mk_ref(sm, reg)],
            description_guide=(
                f"实现 {sm.item_name} 状态机: "
                f"状态={sm.item_data.get('states', [])}, "
                f"转换={sm.sub_items}"
            ),
            section_data={"state_machine": sm.item_data},
            inferred_deps=[s.suggested_name for s in svc_stubs],
            expected_output_files=ofile,
            layer=1,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofile,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofile),
            acceptance_criteria=[{
                "id": f"AC-{sm.item_name}",
                "source_section": "business_rules",
                "source_item": sm.item_name,
                "description": f"状态机: 所有 {len(sm.sub_items)} 个转换均可触发且状态一致",
                "verification_type": "unit_test",
                "expected": "每个合法转换成功，非法转换被拒绝",
            }],
            validation_commands=[{
                "name": f"测试 {sm.item_name} 状态机",
                "command": f"pytest {test}/{safe_mod}/test_{_safe_file(sm.item_name)}_sm{ext} -v",
                "timeout_seconds": 120,
            }],
        ))
    stubs.extend(br_stubs)

    # ── Layer 2: interfaces ──
    iface_stubs = []
    for e in reg.iter_section("interfaces"):
        ofiles = _output_file("endpoint", reg.module, e.item_name, conventions)
        iface_stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name} 接口",
            category="endpoint",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=(
                f"实现 {e.item_data.get('method','')} {e.item_data.get('endpoint','')}: "
                f"{e.item_data.get('description','')}"
            ),
            section_data={"interface": e.item_data},
            inferred_deps=[s.suggested_name for s in svc_stubs],
            expected_output_files=ofiles,
            layer=2,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-{e.item_name}",
                "source_section": "interfaces",
                "source_item": e.item_name,
                "description": f"{e.item_data.get('method','')} {e.item_data.get('endpoint','')} 返回预期状态码和响应体",
                "verification_type": "integration_test",
                "expected": "状态码和响应体匹配 LLD 定义",
            }],
            validation_commands=[{
                "name": f"测试 {e.item_name}",
                "command": f"pytest {test}/{safe_mod}/test_{_safe_file(e.item_name)}{ext} -v",
                "timeout_seconds": 120,
            }],
        ))
    stubs.extend(iface_stubs)

    # ── Layer 2: cross-service rules ──
    csr_entries = [e for e in reg.iter_section("business_rules") if e.artifact_type == "cross_service_rule"]
    if csr_entries:
        stubs.append(TaskStub(
            suggested_name="实现跨服务协同规则",
            category="service",
            lld_refs=[_mk_ref(e, reg) for e in csr_entries],
            description_guide="实现跨服务规则:\n" + "\n".join(f"  - {e.item_data.get('rule','')}" for e in csr_entries),
            section_data={"cross_service_rules": [e.item_data.get("rule", "") for e in csr_entries]},
            inferred_deps=[s.suggested_name for s in iface_stubs],
            expected_output_files=[],
            layer=2,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            forbidden_paths=_default_forbidden_paths(),
            acceptance_criteria=[{
                "id": f"AC-csr-{i}",
                "source_section": "business_rules",
                "source_item": e.item_name,
                "description": f"跨服务规则: {e.item_data.get('rule','')}",
                "verification_type": "integration_test",
                "expected": "跨服务调用按规则执行",
            } for i, e in enumerate(csr_entries)],
            validation_commands=[{
                "name": "测试跨服务协同",
                "command": f"pytest {test}/{safe_mod}/test_cross_service{ext} -v",
                "timeout_seconds": 120,
            }],
        ))

    # ── Layer 3: tests (one per implementation stub) ──
    impl_stubs = [s for s in stubs if s.category in ("model", "service", "endpoint")]
    for s in impl_stubs:
        test_name = f"测试 {s.suggested_name}"
        test_files = _test_file_from(s.expected_output_files, conventions)
        stubs.append(TaskStub(
            suggested_name=test_name,
            category="test",
            lld_refs=list(s.lld_refs),
            description_guide=f"为 {s.suggested_name} 编写单元测试，覆盖正常路径和边界情况",
            section_data={},
            inferred_deps=[s.suggested_name],
            expected_output_files=test_files,
            layer=3,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=test_files,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(test_files),
            acceptance_criteria=[{
                "id": f"AC-test-{_safe_file(s.suggested_name)}",
                "source_section": "tests",
                "source_item": s.suggested_name,
                "description": f"覆盖 {s.suggested_name} 的正常路径和边界情况",
                "verification_type": "unit_test",
                "expected": "所有测试通过",
            }],
            validation_commands=[{
                "name": f"运行 {test_name}",
                "command": f"pytest {' '.join(test_files)} -v" if test_files else f"pytest {test}/{safe_mod}/ -v",
                "timeout_seconds": 120,
            }],
        ))

    return stubs


# ═══════════════════════════════════════════════════════════════════════
# Database
# ═══════════════════════════════════════════════════════════════════════

def _database_rules(reg, conventions: dict) -> list[TaskStub]:
    stubs: list[TaskStub] = []
    mig_dir = conventions.get("migration_dir", "migrations")
    test = conventions.get("test_dir", "tests")
    safe_mod = _safe_module(reg.module)
    doc_id = reg.doc_id

    # tables
    table_entries = list(reg.iter_section("data_models"))
    for e in table_entries:
        if e.ownership != "canonical":
            continue
        ofiles = [f"{mig_dir}/V001__{_safe_file(e.item_name)}.sql"]
        stubs.append(TaskStub(
            suggested_name=f"创建 {e.item_name} 表",
            category="migration",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"编写 {e.item_name} 表的 migration 脚本, 字段: {', '.join(e.sub_items[:10])}",
            section_data={"table": e.item_data},
            expected_output_files=ofiles,
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=[mig_dir],
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-{e.item_name}",
                "source_section": "data_models",
                "source_item": e.item_name,
                "description": f"表 {e.item_name} 创建成功，所有字段类型正确",
                "verification_type": "database_state",
                "expected": f"表 {e.item_name} 存在，列定义与 LLD 一致",
            }],
            validation_commands=[{
                "name": f"验证 {e.item_name} 表",
                "command": f"pytest {test}/{safe_mod}/test_migrations.py -v -k {_safe_file(e.item_name)}",
                "timeout_seconds": 60,
            }],
        ))

    # indexes
    idx_entries = list(reg.iter_section("index_strategy"))
    for e in idx_entries:
        ofiles = [f"{mig_dir}/V002__{_safe_file(e.item_name)}_indexes.sql"]
        stubs.append(TaskStub(
            suggested_name=f"创建 {e.item_name} 索引",
            category="migration",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"为 {e.item_name} 创建索引: {', '.join(e.sub_items)}",
            section_data={"indexes": e.item_data},
            expected_output_files=ofiles,
            layer=1,
            inferred_deps=[f"创建 {e.item_name} 表"],
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=[mig_dir],
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-idx-{e.item_name}",
                "source_section": "index_strategy",
                "source_item": e.item_name,
                "description": f"索引创建成功: {', '.join(e.sub_items)}",
                "verification_type": "database_state",
                "expected": f"所有索引在 {e.item_name} 上可见",
            }],
            validation_commands=[{
                "name": f"验证 {e.item_name} 索引",
                "command": f"pytest {test}/{safe_mod}/test_indexes.py -v -k {_safe_file(e.item_name)}",
                "timeout_seconds": 60,
            }],
        ))

    # migration framework init
    for e in reg.iter_section("migration_strategy"):
        stubs.append(TaskStub(
            suggested_name="配置数据库迁移框架",
            category="config",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"配置 {e.item_data.get('tool','')} 迁移工具, 命名规范: {e.item_data.get('naming','')}",
            section_data={"migration_strategy": e.item_data},
            expected_output_files=[],
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            forbidden_paths=_default_forbidden_paths(),
            acceptance_criteria=[{
                "id": "AC-migration-framework",
                "source_section": "migration_strategy",
                "source_item": "migration_strategy",
                "description": "迁移框架配置完成，可执行迁移",
                "verification_type": "unit_test",
                "expected": "迁移命令可正常执行",
            }],
        ))

    # connection contracts
    for e in reg.iter_section("connection_contracts"):
        stubs.append(TaskStub(
            suggested_name="配置数据库连接和服务账号",
            category="config",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"配置连接池: {e.item_data.get('pool_size','')}, 超时: {e.item_data.get('timeout','')}",
            section_data={"connection_contracts": e.item_data},
            expected_output_files=[],
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            forbidden_paths=_default_forbidden_paths(),
            acceptance_criteria=[{
                "id": "AC-connection",
                "source_section": "connection_contracts",
                "source_item": "connection_contracts",
                "description": "数据库连接配置正确，连接池参数与 LLD 一致",
                "verification_type": "integration_test",
                "expected": "可以成功连接数据库",
            }],
        ))

    # capacity doc
    for e in reg.iter_section("capacity_estimation"):
        stubs.append(TaskStub(
            suggested_name="编写容量预估文档",
            category="doc",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"1年预估: {e.item_data.get('estimated_rows_1y','')}, 3年预估: {e.item_data.get('estimated_rows_3y','')}",
            section_data={"capacity": e.item_data},
            expected_output_files=[],
            layer=1,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            forbidden_paths=_default_forbidden_paths(),
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
            source={"lld_doc_id": doc_id, "lld_path": ""},
            forbidden_paths=_default_forbidden_paths(),
            acceptance_criteria=[{
                "id": f"AC-test-{_safe_file(s.suggested_name)}",
                "source_section": "tests",
                "source_item": s.suggested_name,
                "description": f"验证 {s.suggested_name}",
                "verification_type": "unit_test",
                "expected": "测试通过",
            }],
        ))

    return stubs


# ═══════════════════════════════════════════════════════════════════════
# Gateway
# ═══════════════════════════════════════════════════════════════════════

def _gateway_rules(reg, conventions: dict) -> list[TaskStub]:
    stubs: list[TaskStub] = []
    safe_mod = _safe_module(reg.module)
    src = conventions.get("src_dir", "src")
    test = conventions.get("test_dir", "tests")
    ext = conventions.get("file_ext", ".py")
    doc_id = reg.doc_id

    # routes
    route_entries = list(reg.iter_section("route_table"))
    if route_entries:
        ofiles = [f"{src}/{safe_mod}/routes{ext}"]
        stubs.append(TaskStub(
            suggested_name="配置网关路由表",
            category="service",
            lld_refs=[_mk_ref(e, reg) for e in route_entries],
            description_guide=f"配置 {len(route_entries)} 条路由规则",
            section_data={"route_table": [e.item_data for e in route_entries]},
            expected_output_files=ofiles,
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": "AC-gateway-routes",
                "source_section": "route_table",
                "source_item": "routes",
                "description": f"所有 {len(route_entries)} 条路由规则正确注册",
                "verification_type": "integration_test",
                "expected": "请求按路由规则正确转发",
            }],
            validation_commands=[{
                "name": "测试网关路由",
                "command": f"pytest {test}/{safe_mod}/test_routes{ext} -v",
                "timeout_seconds": 120,
            }],
        ))

    # middleware
    for e in reg.iter_section("middleware_chain"):
        ofiles = [f"{src}/{safe_mod}/middleware{ext}"]
        stubs.append(TaskStub(
            suggested_name="实现中间件链",
            category="service",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"实现中间件链: {e.item_data.get('chain', [])}",
            section_data={"middleware_chain": e.item_data},
            expected_output_files=ofiles,
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": "AC-middleware",
                "source_section": "middleware_chain",
                "source_item": "middleware_chain",
                "description": "中间件链按顺序正确执行",
                "verification_type": "integration_test",
                "expected": "请求按链顺序经过所有中间件",
            }],
            validation_commands=[{
                "name": "测试中间件",
                "command": f"pytest {test}/{safe_mod}/test_middleware{ext} -v",
                "timeout_seconds": 120,
            }],
        ))

    # auth
    for e in reg.iter_section("auth_policy"):
        ofiles = [f"{src}/{safe_mod}/auth{ext}"]
        stubs.append(TaskStub(
            suggested_name="实现认证授权策略",
            category="service",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"认证方式: {e.item_data.get('auth_method','')}, 公开端点: {e.sub_items}",
            section_data={"auth_policy": e.item_data},
            expected_output_files=ofiles,
            layer=1,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": "AC-auth",
                "source_section": "auth_policy",
                "source_item": "auth_policy",
                "description": "认证成功/失败/公开端点均正确处理",
                "verification_type": "integration_test",
                "expected": "受保护端点拒绝未认证请求，公开端点允许匿名访问",
            }],
            validation_commands=[{
                "name": "测试认证",
                "command": f"pytest {test}/{safe_mod}/test_auth{ext} -v",
                "timeout_seconds": 120,
            }],
        ))

    # rate limiting
    for e in reg.iter_section("rate_limiting"):
        ofiles = [f"{src}/{safe_mod}/rate_limiter{ext}"]
        stubs.append(TaskStub(
            suggested_name="实现限流策略",
            category="config",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"全局限流: {e.item_data.get('global','')}, 用户限流: {e.item_data.get('per_user','')}",
            section_data={"rate_limiting": e.item_data},
            expected_output_files=ofiles,
            layer=1,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": "AC-rate-limit",
                "source_section": "rate_limiting",
                "source_item": "rate_limiting",
                "description": f"超过阈值后返回 429，限流参数与 LLD 一致",
                "verification_type": "integration_test",
                "expected": "超限请求被拒绝，正常请求通过",
            }],
            validation_commands=[{
                "name": "测试限流",
                "command": f"pytest {test}/{safe_mod}/test_rate_limiter{ext} -v",
                "timeout_seconds": 120,
            }],
        ))

    # interfaces
    for e in reg.iter_section("interfaces"):
        ofiles = [f"{src}/{safe_mod}/handler/{_safe_file(e.item_name)}{ext}"]
        stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name}",
            category="endpoint",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"实现 {e.item_data.get('method','')} {e.item_data.get('endpoint','')}",
            section_data={"interface": e.item_data},
            expected_output_files=ofiles,
            layer=2,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-{e.item_name}",
                "source_section": "interfaces",
                "source_item": e.item_name,
                "description": f"{e.item_data.get('method','')} {e.item_data.get('endpoint','')} 返回预期响应",
                "verification_type": "integration_test",
                "expected": "状态码和响应体匹配 LLD 定义",
            }],
            validation_commands=[{
                "name": f"测试 {e.item_name}",
                "command": f"pytest {test}/{safe_mod}/test_{_safe_file(e.item_name)}{ext} -v",
                "timeout_seconds": 120,
            }],
        ))

    # tests
    impl_stubs = [s for s in stubs if s.category != "test"]
    for s in impl_stubs:
        test_files = _test_file_from(s.expected_output_files, conventions)
        stubs.append(TaskStub(
            suggested_name=f"测试 {s.suggested_name}",
            category="test",
            lld_refs=list(s.lld_refs),
            description_guide=f"验证 {s.suggested_name}",
            section_data={},
            inferred_deps=[s.suggested_name],
            expected_output_files=test_files,
            layer=3,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=test_files,
            forbidden_paths=_default_forbidden_paths(),
            file_locks=list(test_files),
            acceptance_criteria=[{
                "id": f"AC-test-{_safe_file(s.suggested_name)}",
                "source_section": "tests",
                "source_item": s.suggested_name,
                "description": f"覆盖 {s.suggested_name} 的网关集成测试",
                "verification_type": "integration_test",
                "expected": "所有测试通过",
            }],
        ))

    return stubs


# ═══════════════════════════════════════════════════════════════════════
# Frontend
# ═══════════════════════════════════════════════════════════════════════

def _frontend_rules(reg, conventions: dict) -> list[TaskStub]:
    stubs: list[TaskStub] = []
    safe_mod = _safe_module(reg.module)
    src = conventions.get("src_dir", "src")
    test = conventions.get("test_dir", "tests")
    doc_id = reg.doc_id
    fbd = _default_forbidden_paths()

    for e in reg.iter_section("component_tree"):
        ofiles = [f"{src}/{safe_mod}/components/{_safe_file(e.item_name)}.tsx"]
        stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name} 组件",
            category="service",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"实现 {e.item_name} 组件, props: {e.item_data.get('props', [])}",
            section_data={"component": e.item_data},
            expected_output_files=ofiles,
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=fbd,
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-{e.item_name}",
                "source_section": "component_tree",
                "source_item": e.item_name,
                "description": f"{e.item_name} 组件正确渲染，props 类型正确",
                "verification_type": "frontend_render",
                "expected": "组件渲染结果与设计一致",
            }],
        ))

    for e in reg.iter_section("state_design"):
        ofiles = [f"{src}/{safe_mod}/store.ts"]
        stubs.append(TaskStub(
            suggested_name="实现全局状态管理",
            category="service",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"实现状态管理, 缓存策略: {e.item_data.get('caching_strategy','')}",
            section_data={"state_design": e.item_data},
            expected_output_files=ofiles,
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=fbd,
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": "AC-state",
                "source_section": "state_design",
                "source_item": "state_design",
                "description": "状态管理初始化正确，响应式更新正常",
                "verification_type": "frontend_render",
                "expected": "状态变更驱动组件重渲染",
            }],
        ))

    for e in reg.iter_section("route_design"):
        ofiles = [f"{src}/{safe_mod}/routes.tsx"]
        stubs.append(TaskStub(
            suggested_name=f"配置路由 {e.item_name}",
            category="config",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"配置路由 {e.item_name}, 页面: {e.item_data.get('page','')}",
            section_data={"route": e.item_data},
            expected_output_files=ofiles,
            layer=1,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=fbd,
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-route-{e.item_name}",
                "source_section": "route_design",
                "source_item": e.item_name,
                "description": f"路由 {e.item_name} 正确导航到目标页面",
                "verification_type": "frontend_render",
                "expected": f"访问 {e.item_name} 渲染正确页面",
            }],
        ))

    for e in reg.iter_section("interaction_flows"):
        ofiles = [f"{src}/{safe_mod}/flows/{_safe_file(e.item_name)}.ts"]
        stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name} 交互流程",
            category="service",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"实现交互流程, 步骤: {e.item_data.get('steps', [])}",
            section_data={"interaction_flow": e.item_data},
            expected_output_files=ofiles,
            layer=1,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=fbd,
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-flow-{e.item_name}",
                "source_section": "interaction_flows",
                "source_item": e.item_name,
                "description": f"交互流程 {e.item_name} 各步骤正确执行",
                "verification_type": "frontend_render",
                "expected": "用户操作触发正确的流程步骤",
            }],
        ))

    for e in reg.iter_section("api_integration"):
        ofiles = [f"{src}/{safe_mod}/api/{_safe_file(e.item_name)}.ts"]
        stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name} API 集成",
            category="endpoint",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"集成 API: {e.item_data.get('endpoint','')}",
            section_data={"api_integration": e.item_data},
            expected_output_files=ofiles,
            layer=2,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=fbd,
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-api-{e.item_name}",
                "source_section": "api_integration",
                "source_item": e.item_name,
                "description": f"API 调用 {e.item_data.get('endpoint','')} 正确处理请求和响应",
                "verification_type": "integration_test",
                "expected": "请求发送和响应处理与后端契约一致",
            }],
        ))

    # tests
    impl_stubs = [s for s in stubs if s.category != "test"]
    for s in impl_stubs:
        test_files = _test_file_from(s.expected_output_files, conventions)
        stubs.append(TaskStub(
            suggested_name=f"测试 {s.suggested_name}",
            category="test",
            lld_refs=list(s.lld_refs),
            description_guide=f"验证 {s.suggested_name}",
            section_data={},
            inferred_deps=[s.suggested_name],
            expected_output_files=test_files,
            layer=3,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=test_files,
            forbidden_paths=fbd,
            file_locks=list(test_files),
            acceptance_criteria=[{
                "id": f"AC-test-{_safe_file(s.suggested_name)}",
                "source_section": "tests",
                "source_item": s.suggested_name,
                "description": f"覆盖 {s.suggested_name} 的前端功能测试",
                "verification_type": "frontend_render",
                "expected": "所有测试通过",
            }],
        ))

    return stubs


# ═══════════════════════════════════════════════════════════════════════
# Infrastructure
# ═══════════════════════════════════════════════════════════════════════

def _infra_rules(reg, conventions: dict) -> list[TaskStub]:
    stubs: list[TaskStub] = []
    safe_mod = _safe_module(reg.module)
    src = conventions.get("src_dir", "src")
    test = conventions.get("test_dir", "tests")
    ext = conventions.get("file_ext", ".py")
    doc_id = reg.doc_id
    fbd = _default_forbidden_paths()

    # topology
    for e in reg.iter_section("topology"):
        atype = e.artifact_type
        label = {"exchange": "Exchange", "queue": "Queue", "namespace": "Namespace", "bucket": "Bucket"}.get(atype, atype)
        ofiles = [f"infra/{safe_mod}/{atype}/{_safe_file(e.item_name)}.yaml"]
        stubs.append(TaskStub(
            suggested_name=f"定义 {label} {e.item_name}",
            category="config",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"定义 {label} {e.item_name}",
            section_data={"topology_item": e.item_data},
            expected_output_files=ofiles,
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=fbd,
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-topo-{e.item_name}",
                "source_section": "topology",
                "source_item": e.item_name,
                "description": f"{label} {e.item_name} 配置正确",
                "verification_type": "unit_test",
                "expected": f"{label} 可按配置正常创建和连接",
            }],
        ))

    # message contracts
    for e in reg.iter_section("message_contracts"):
        ofiles = [f"{src}/{safe_mod}/contracts/{_safe_file(e.item_name)}{ext}"]
        stubs.append(TaskStub(
            suggested_name=f"定义消息契约 {e.item_name}",
            category="service",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"定义消息 schema: {e.item_data.get('schema', {})}",
            section_data={"message_contract": e.item_data},
            expected_output_files=ofiles,
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=fbd,
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-msg-{e.item_name}",
                "source_section": "message_contracts",
                "source_item": e.item_name,
                "description": f"消息 {e.item_name} schema 定义与 LLD 一致",
                "verification_type": "unit_test",
                "expected": "消息序列化/反序列化正确",
            }],
        ))

    # reliability strategy
    for e in reg.iter_section("reliability_strategy"):
        ofiles = [f"{src}/{safe_mod}/reliability{ext}"]
        stubs.append(TaskStub(
            suggested_name="实现消息可靠性策略",
            category="service",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"ack模式: {e.item_data.get('ack_mode','')}, 重试: {e.item_data.get('retry',{})}",
            section_data={"reliability": e.item_data},
            expected_output_files=ofiles,
            layer=1,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=fbd,
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": "AC-reliability",
                "source_section": "reliability_strategy",
                "source_item": "reliability_strategy",
                "description": "重试和超时逻辑符合 LLD 定义",
                "verification_type": "integration_test",
                "expected": "消息失败后按策略重试，超时后正确降级",
            }],
        ))

    # data_models (config type)
    for e in reg.iter_section("data_models"):
        ofiles = [f"{src}/{safe_mod}/config/{_safe_file(e.item_name)}{ext}"]
        stubs.append(TaskStub(
            suggested_name=f"定义 {e.item_name} 配置",
            category="config",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"定义 {e.item_name} 配置结构",
            section_data={"data_model": e.item_data},
            expected_output_files=ofiles,
            layer=0,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=fbd,
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-cfg-{e.item_name}",
                "source_section": "data_models",
                "source_item": e.item_name,
                "description": f"{e.item_name} 配置结构体定义正确",
                "verification_type": "unit_test",
                "expected": "配置可正常加载和校验",
            }],
        ))

    # interfaces
    for e in reg.iter_section("interfaces"):
        ofiles = [f"{src}/{safe_mod}/api/{_safe_file(e.item_name)}{ext}"]
        stubs.append(TaskStub(
            suggested_name=f"实现 {e.item_name}",
            category="endpoint",
            lld_refs=[_mk_ref(e, reg)],
            description_guide=f"实现 {e.item_data.get('method','')} {e.item_data.get('endpoint','')}",
            section_data={"interface": e.item_data},
            expected_output_files=ofiles,
            layer=2,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=ofiles,
            forbidden_paths=fbd,
            file_locks=list(ofiles),
            acceptance_criteria=[{
                "id": f"AC-{e.item_name}",
                "source_section": "interfaces",
                "source_item": e.item_name,
                "description": f"{e.item_data.get('method','')} {e.item_data.get('endpoint','')} 返回预期响应",
                "verification_type": "integration_test",
                "expected": "状态码和响应体匹配 LLD 定义",
            }],
        ))

    # tests
    impl_stubs = [s for s in stubs if s.category != "test"]
    for s in impl_stubs:
        test_files = _test_file_from(s.expected_output_files, conventions)
        stubs.append(TaskStub(
            suggested_name=f"测试 {s.suggested_name}",
            category="test",
            lld_refs=list(s.lld_refs),
            description_guide=f"验证 {s.suggested_name}",
            section_data={},
            inferred_deps=[s.suggested_name],
            expected_output_files=test_files,
            layer=3,
            source={"lld_doc_id": doc_id, "lld_path": ""},
            allowed_paths=test_files,
            forbidden_paths=fbd,
            file_locks=list(test_files),
            acceptance_criteria=[{
                "id": f"AC-test-{_safe_file(s.suggested_name)}",
                "source_section": "tests",
                "source_item": s.suggested_name,
                "description": f"覆盖 {s.suggested_name} 的基础设施测试",
                "verification_type": "integration_test",
                "expected": "所有测试通过",
            }],
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


def _output_file(category: str, module: str, name: str, conventions: dict) -> list[str]:
    """Build expected_output_files path from category + conventions path templates."""
    safe_mod = _safe_module(module)
    safe_name = _safe_file(name)
    ext = conventions.get("file_ext", ".py")
    src = conventions.get("src_dir", "src")
    test = conventions.get("test_dir", "tests")

    templates = {
        "model":      f"{src}/{safe_mod}/models/{safe_name}{ext}",
        "service":    f"{src}/{safe_mod}/services/{safe_name}{ext}",
        "endpoint":   f"{src}/{safe_mod}/api/{safe_name}{ext}",
        "config":     f"{src}/{safe_mod}/config/{safe_name}{ext}",
        "migration":  f"{conventions.get('migration_dir', 'migrations')}/V___{safe_name}.sql",
        "doc":        [],
    }
    path = templates.get(category)
    if path is None:
        return []
    if isinstance(path, str):
        return [path]
    return path


def _test_file_from(output_files: list[str], conventions: dict) -> list[str]:
    """Derive test file paths from implementation file paths."""
    ext = conventions.get("file_ext", ".py")
    src = conventions.get("src_dir", "src")
    test = conventions.get("test_dir", "tests")
    results: list[str] = []
    for f in output_files:
        if f.startswith(f"{src}/"):
            rel = f[len(src) + 1:]  # strip "src/"
            parts = rel.split("/")
            stem = parts[-1].replace(ext, f"_test{ext}")
            results.append(f"{test}/{'/'.join(parts[:-1])}/{stem}")
        else:
            results.append(f)
    return results


def _svc_stub(reg, entry, methods, conventions, suffix="") -> TaskStub:
    """Build a service-contract TaskStub with full hard constraints."""
    names = [m.get("name", "?") for m in methods]
    safe_mod = _safe_module(reg.module)
    ext = conventions.get("file_ext", ".py")
    src = conventions.get("src_dir", "src")
    output_files = [f"{src}/{safe_mod}/services/{_safe_file(entry.item_name)}{ext}"]

    return TaskStub(
        suggested_name=f"实现 {entry.item_name}{suffix}",
        category="service",
        lld_refs=[_mk_ref(entry, reg)],
        description_guide=(
            f"实现 {entry.item_name} 服务方法: {', '.join(names)}\n"
            + "\n".join(
                f"  - {m.get('name','')}: {m.get('signature','')} "
                f"pre={m.get('precondition','')[:60]}"
                for m in methods
            )
        ),
        section_data={"service_contract": entry.item_data, "methods": methods},
        expected_output_files=output_files,
        layer=1,
        source={"lld_doc_id": reg.doc_id, "lld_path": ""},
        allowed_paths=[
            f"{src}/{safe_mod}/services/{_safe_file(entry.item_name)}{ext}",
        ],
        forbidden_paths=_default_forbidden_paths(),
        file_locks=list(output_files),
        acceptance_criteria=[
            {
                "id": f"AC-{names[0]}" if names else "AC-svc",
                "source_section": "service_contracts",
                "source_item": f"{entry.item_name}.{m.get('name','?')}",
                "description": f"{m.get('name','?')} 方法实现满足前置条件: {m.get('precondition','')}",
                "verification_type": "unit_test",
                "expected": f"返回值符合 {m.get('signature','')}",
            }
            for m in methods
        ],
        validation_commands=[
            {
                "name": f"测试 {entry.item_name}",
                "command": f"pytest {conventions.get('test_dir', 'tests')}/{safe_mod}/test_{_safe_file(entry.item_name)}{ext} -v",
                "timeout_seconds": 120,
            }
        ],
    )
