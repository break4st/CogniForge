"""LLD JSON schema validator — mechanical rule checks, no LLM involved.

Validates LLD JSON completeness and correctness before commit.
Integrated into DesignAgent.run() as a pre-commit gate with retry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Per-module-type required sections
# ---------------------------------------------------------------------------

_REQUIRED_SECTIONS: dict[str, list[str]] = {
    "service": [
        "data_models",
        "domain_objects",
        "service_contracts",
        "business_rules",
        "interfaces",
        "error_handling",
    ],
    "frontend": [
        "data_models",
        "component_tree",
        "state_design",
        "route_design",
        "interaction_flows",
        "api_integration",
        "interfaces",
    ],
    "gateway": [
        "data_models",
        "route_table",
        "middleware_chain",
        "auth_policy",
        "rate_limiting",
        "interfaces",
        "error_handling",
    ],
    "database": [
        "data_models",
        "index_strategy",
        "migration_strategy",
        "capacity_estimation",
        "connection_contracts",
        "interfaces",
    ],
    "infrastructure": [
        "data_models",
        "topology",
        "interfaces",
    ],
}

# Infrastructure sub-type required sections
_INFRA_MQ_SECTIONS = ["message_contracts", "reliability_strategy"]


def validate_lld_json(json_path: Path) -> dict:
    """Validate a single LLD JSON file.

    Returns:
        {"passed": bool, "violations": list, "warnings": list, "meta": dict}
        Each violation/warning: {"section": str, "field": str, "detail": str}
    """
    violations: list[dict] = []
    warnings: list[dict] = []

    # Load JSON
    try:
        data = _load_json(json_path)
    except Exception as e:
        return {
            "passed": False,
            "violations": [{"section": "file", "field": "json", "detail": f"JSON 解析失败: {e}"}],
            "warnings": [],
            "meta": {},
        }

    meta = data.get("meta", {})
    module_type = meta.get("module_type", "service")
    module = meta.get("module", "unknown")

    base = {"meta": meta, "module": module, "module_type": module_type}

    # ── 1. Meta completeness ──
    _check_meta(meta, violations)

    # ── 2. Overview completeness ──
    overview = data.get("overview", {})
    if not isinstance(overview, dict):
        violations.append(_v("overview", "type", "overview 必须是一个 dict"))
    elif not overview.get("description"):
        violations.append(_v("overview", "description", "overview.description 不可为空"))

    # ── 3. Module-type-specific required sections ──
    # Section must exist (missing key = violation). Empty arrays/objects are OK at this level
    # — deeper checks handle content requirements.
    required = _REQUIRED_SECTIONS.get(module_type, [])
    for section in required:
        if section not in data:
            violations.append(_v(section, "existence", f"必需章节 '{section}' 缺失"))
        elif data[section] is None:
            violations.append(_v(section, "existence", f"必需章节 '{section}' 值为 null"))

    # ── 4. Deep field checks per section ──

    # 4a. data_models — ownership rules
    if module_type == "database":
        canonical_tables = [m for m in data.get("data_models", [])
                           if m.get("ownership") == "canonical" and m.get("type") == "table"]
        if not canonical_tables:
            violations.append(_v("data_models", "ownership",
                                 "database 模块必须至少有一个 ownership=canonical 的 table"))

    for dm in data.get("data_models", []):
        ownership = dm.get("ownership", "")
        if ownership == "derived":
            source = dm.get("source")
            if not source or not isinstance(source, dict):
                violations.append(_v("data_models", f"{dm.get('name','?')}.source",
                                     f"模型 '{dm.get('name','?')}' ownership=derived 但缺少 source"))
            elif not source.get("doc_id") or not source.get("model_name"):
                violations.append(_v("data_models", f"{dm.get('name','?')}.source",
                                     f"模型 '{dm.get('name','?')}' 的 source 缺少 doc_id 或 model_name"))

    # 4b. domain_objects (service only)
    for dobj in data.get("domain_objects", []):
        ot = dobj.get("object_type", "")
        if ot in ("entity", "value_object", "dto"):
            attrs = dobj.get("attributes", [])
            if not attrs:
                violations.append(_v("domain_objects", f"{dobj.get('name','?')}.attributes",
                                     f"领域对象 '{dobj.get('name','?')}' ({ot}) 缺少 attributes"))
            for a in attrs:
                if ot == "entity" and not a.get("source"):
                    warnings.append(_v("domain_objects", f"{dobj.get('name','?')}.{a.get('name','?')}.source",
                                       f"entity '{dobj.get('name','?')}' 的属性 '{a.get('name','?')}' 未标注 source"))
        elif ot == "enum":
            if not dobj.get("values"):
                violations.append(_v("domain_objects", f"{dobj.get('name','?')}.values",
                                     f"枚举 '{dobj.get('name','?')}' 缺少 values"))

    # 4c. service_contracts (service only)
    for svc in data.get("service_contracts", []):
        methods = svc.get("methods", [])
        if not methods:
            violations.append(_v("service_contracts", f"{svc.get('name','?')}.methods",
                                 f"服务 '{svc.get('name','?')}' 没有任何方法"))
        for m in methods:
            meth_name = m.get("name", "?")
            if not m.get("precondition"):
                warnings.append(_v("service_contracts", f"{svc.get('name','?')}.{meth_name}.precondition",
                                   f"方法 '{meth_name}' 缺少 precondition"))
            if not m.get("postcondition"):
                warnings.append(_v("service_contracts", f"{svc.get('name','?')}.{meth_name}.postcondition",
                                   f"方法 '{meth_name}' 缺少 postcondition"))
            if not m.get("signature"):
                violations.append(_v("service_contracts", f"{svc.get('name','?')}.{meth_name}.signature",
                                     f"方法 '{meth_name}' 缺少 signature"))

    # 4d. business_rules (service only)
    br = data.get("business_rules", {})
    if isinstance(br, dict):
        if not br.get("invariants"):
            warnings.append(_v("business_rules", "invariants", "business_rules 缺少 invariants"))

    # 4e. interfaces — method field required
    for iface in data.get("interfaces", []):
        if not iface.get("method"):
            violations.append(_v("interfaces", f"{iface.get('name','?')}.method",
                                 f"接口 '{iface.get('name','?')}' 缺少 method 字段"))
        if not iface.get("endpoint"):
            violations.append(_v("interfaces", f"{iface.get('name','?')}.endpoint",
                                 f"接口 '{iface.get('name','?')}' 缺少 endpoint"))
        resp_body = iface.get("response", {}).get("body", {})
        if isinstance(resp_body, dict) and not resp_body:
            if module_type != "frontend":  # frontend interfaces may not have response bodies
                warnings.append(_v("interfaces", f"{iface.get('name','?')}.response.body",
                                   f"接口 '{iface.get('name','?')}' 的 response.body 为空"))

    # 4f. component_tree (frontend only)
    for comp in data.get("component_tree", []):
        if not comp.get("props") and not comp.get("events") and not comp.get("state"):
            warnings.append(_v("component_tree", f"{comp.get('name','?')}",
                               f"组件 '{comp.get('name','?')}' 没有定义 props/events/state"))

    # 4g. route_table (gateway only)
    for rt in data.get("route_table", []):
        if not rt.get("path_pattern") or not rt.get("upstream"):
            violations.append(_v("route_table", f"{rt.get('path_pattern','?')}",
                                 f"路由条目缺少 path_pattern 或 upstream"))

    # 4h. auth_policy (gateway only)
    ap = data.get("auth_policy", {})
    if isinstance(ap, dict):
        if module_type == "gateway" and not ap.get("role_path_map"):
            violations.append(_v("auth_policy", "role_path_map", "auth_policy 缺少 role_path_map"))

    # 4i. topology (infrastructure only)
    if module_type == "infrastructure":
        topo = data.get("topology", {})
        if isinstance(topo, dict):
            has_exchanges = bool(topo.get("exchanges"))
            has_namespaces = bool(topo.get("namespaces"))
            has_buckets = bool(topo.get("buckets"))
            if not (has_exchanges or has_namespaces or has_buckets):
                violations.append(_v("topology", "structure",
                                     "topology 必须包含 exchanges/namespaces/buckets 之一"))
            # MQ sub-type requires extra sections
            if has_exchanges:
                for sec in _INFRA_MQ_SECTIONS:
                    if sec not in data or not data[sec]:
                        violations.append(_v(sec, "existence",
                                             f"消息队列类型基础设施缺少必需章节 '{sec}'"))

    # 4j. index_strategy (database only)
    for table in data.get("index_strategy", []):
        if not table.get("table") or not table.get("indexes"):
            violations.append(_v("index_strategy", "table",
                                 f"index_strategy 条目缺少 table 名或 indexes"))

    # 4k. error_handling
    eh = data.get("error_handling", {})
    if isinstance(eh, dict):
        if not eh.get("strategy"):
            warnings.append(_v("error_handling", "strategy", "error_handling 缺少 strategy"))

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "meta": base,
    }


def format_validation_report(result: dict) -> str:
    """Render a human-readable validation report for feeding back to the LLM."""
    lines = []
    meta = result.get("meta", {})
    module = meta.get("module", "?")
    module_type = meta.get("module_type", "?")

    if result["passed"]:
        lines.append(f"✓ LLD 校验通过 — {module} ({module_type})")
        if result.get("warnings"):
            lines.append(f"\n建议改进 ({len(result['warnings'])} 条):")
            for w in result["warnings"]:
                lines.append(f"  ⚠ [{w['section']}] {w['field']}: {w['detail']}")
        return "\n".join(lines)

    violations = result.get("violations", [])
    warnings = result.get("warnings", [])

    lines.append(f"✗ LLD 校验失败 — {module} ({module_type})")
    lines.append(f"  必须修复 {len(violations)} 个问题:\n")
    for i, v in enumerate(violations, 1):
        lines.append(f"  {i}. [{v['section']}] {v['field']}: {v['detail']}")

    if warnings:
        lines.append(f"\n建议改进 ({len(warnings)} 条):")
        for w in warnings:
            lines.append(f"  ⚠ [{w['section']}] {w['field']}: {w['detail']}")

    lines.append("\n请修正上述所有问题后重新输出完整的 JSON。")
    return "\n".join(lines)


def _v(section: str, field: str, detail: str) -> dict:
    return {"section": section, "field": field, "detail": detail}


def _check_meta(meta: dict, violations: list) -> None:
    """Check meta section completeness."""
    for field in ["doc_id", "type", "module_type", "module", "title"]:
        if not meta.get(field):
            violations.append(_v("meta", field, f"meta.{field} 不可为空"))


def _load_json(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Attempt repair
    from cogniforge.wiki.wiki_renderer import load_json_with_repair
    return load_json_with_repair(path)
