"""TaskContext builder — assemble structured context for DEV Agent consumption.

For each TaskStub, extract the relevant LLD data subset and build a
self-contained TaskContext so DEV doesn't need to re-read LLD.
"""

from __future__ import annotations

from cogniforge.wbs.decomposition_rules import TaskStub
from cogniforge.wbs.lld_artifact_registry import LLDArtifactRegistry
from cogniforge.models.task import TaskContext, TaskScope


def build_context(
    stub: TaskStub,
    registry: LLDArtifactRegistry,
    lld_data: dict,
    all_module_llds: dict[str, dict] | None = None,
) -> TaskContext:
    """Build a TaskContext for a single TaskStub.

    Args:
        stub: The task stub to build context for.
        registry: Parsed LLD artifact registry for this module.
        lld_data: Full LLD JSON dict.
        all_module_llds: Optional map of {module_name: lld_data} for cross-module
            contract resolution.

    Returns:
        TaskContext ready to attach to a Task.
    """
    all_module_llds = all_module_llds or {}

    # ── Scope: extract relevant LLD data from registry ──
    scope = TaskScope()

    for ref in stub.lld_refs:
        section = ref.get("section", "")
        item_name = ref.get("item_name", "")

        entry = registry.get_by_name(section, item_name)
        if not entry:
            continue
        data = entry.item_data

        if section == "data_models":
            scope.data_models.append(data)
        elif section == "domain_objects":
            scope.domain_objects.append(data)
        elif section == "interfaces":
            scope.interfaces.append(data)
        elif section == "service_contracts":
            scope.service_contracts.append(data)
        elif section == "business_rules":
            _merge_business_rules(scope, entry, data)
        elif section == "error_handling":
            scope.error_handling = data
        else:
            scope.extra_sections.setdefault(section, []).append(data)

    # ── Cross-module contracts ──
    external_contracts: list[dict] = []
    cross_module_deps: list[str] = []

    overview = lld_data.get("overview", {})
    declared_deps = overview.get("dependencies", [])

    for dep_module in declared_deps:
        if dep_module in all_module_llds:
            dep_lld = all_module_llds[dep_module]
            dep_ifaces = dep_lld.get("interfaces", [])
            for iface in dep_ifaces:
                external_contracts.append({
                    "module": dep_module,
                    "method": iface.get("method", ""),
                    "endpoint": iface.get("endpoint", ""),
                    "response": iface.get("response", {}),
                    "parameters": iface.get("parameters", []),
                })
            cross_module_deps.append(dep_module)

    # ── Tech stack ──
    tech_stack = overview.get("tech_stack", [])

    return TaskContext(
        module_type=registry.module_type,
        lld_path=f".cogniforge/wiki/lld/{registry.module}/{registry.doc_id}.json",
        module_overview=overview.get("description", ""),
        scope=scope,
        external_contracts=external_contracts,
        cross_module_deps=cross_module_deps,
        tech_stack=tech_stack if isinstance(tech_stack, list) else [],
    )


def _merge_business_rules(scope: TaskScope, entry, data: dict) -> None:
    """Merge a business_rules artifact into the scope."""
    br = scope.business_rules
    atype = entry.artifact_type

    if atype == "business_rule_invariant":
        br.setdefault("invariants", []).append(data.get("rule", str(data)))
    elif atype == "state_machine":
        br.setdefault("state_machines", []).append(data)
    elif atype == "cross_service_rule":
        br.setdefault("cross_service_rules", []).append(data.get("rule", str(data)))
    else:
        br.setdefault("other", []).append(data)
