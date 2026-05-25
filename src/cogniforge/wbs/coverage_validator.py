"""Coverage validator — four-dimensional task quality checks.

Pure data comparison.  No LLM involved.

Dimensions:
  1. Coverage    — every LLD artifact has at least one task
  2. Executability — every task has lld_refs, scope, boundary, acceptance_criteria
  3. File boundary — allowed_paths sensible, locks don't conflict
  4. DAG          — deps valid, no cycles, layer ordering
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cogniforge.wbs.lld_artifact_registry import LLDArtifactRegistry


# ═══════════════════════════════════════════════════════════════════════
# Dimension 1: Coverage
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class CoverageReport:
    total_artifacts: int = 0
    covered_artifacts: int = 0
    uncovered: list[tuple[str, str]] = field(default_factory=list)
    partially_covered: list[tuple[str, str, list[str]]] = field(default_factory=list)
    coverage_pct: float = 0.0
    passed: bool = False

    def format(self) -> str:
        lines = []
        status = "PASS" if self.passed else "FAIL"
        lines.append(f"Coverage: {status} ({self.coverage_pct:.0f}% — {self.covered_artifacts}/{self.total_artifacts})")
        if self.uncovered:
            lines.append(f"\nUncovered ({len(self.uncovered)}):")
            for section, name in self.uncovered:
                lines.append(f"  - [{section}] {name}")
        if self.partially_covered:
            lines.append(f"\nPartially covered ({len(self.partially_covered)}):")
            for section, name, missing in self.partially_covered:
                lines.append(f"  - [{section}] {name}: missing {missing}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Dimension 2: Executability
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ExecutabilityReport:
    passed: bool = True
    issues: list[str] = field(default_factory=list)

    def format(self) -> str:
        if self.passed:
            return "Executability: PASS"
        return "Executability: FAIL\n  " + "\n  ".join(self.issues)


def validate_executability(tasks: list[dict]) -> ExecutabilityReport:
    """Check every non-test task has the minimum required fields for DEV execution."""
    issues: list[str] = []

    for t in tasks:
        tid = t.get("task_id", t.get("name", "?"))
        cat = t.get("category", "")

        # Test / doc / config tasks have relaxed requirements
        if cat in ("test", "doc"):
            continue

        if not t.get("lld_refs"):
            issues.append(f"{tid}: 缺少 lld_refs")

        ctx = t.get("context", {})
        scope = ctx.get("scope", {}) if isinstance(ctx, dict) else None
        if scope is not None:
            has_scope = any(
                scope.get(k) for k in ("data_models", "domain_objects",
                                         "interfaces", "service_contracts",
                                         "business_rules")
            )
            if not has_scope:
                issues.append(f"{tid}: context.scope 为空，DEV Agent 缺少实现上下文")

        if not t.get("acceptance_criteria"):
            if cat != "config":
                issues.append(f"{tid}: 缺少 acceptance_criteria")

        boundary = t.get("implementation_boundary", {})
        allowed = boundary.get("allowed_paths", []) if isinstance(boundary, dict) else []
        if not allowed and cat not in ("config", "doc"):
            issues.append(f"{tid}: implementation_boundary.allowed_paths 为空")

    return ExecutabilityReport(
        passed=len(issues) == 0,
        issues=issues,
    )


# ═══════════════════════════════════════════════════════════════════════
# Dimension 3: File Boundary
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class FileBoundaryReport:
    passed: bool = True
    conflicts: list[str] = field(default_factory=list)

    def format(self) -> str:
        if self.passed:
            return "File Boundary: PASS"
        return "File Boundary: FAIL\n  " + "\n  ".join(self.conflicts)


def validate_file_boundary(tasks: list[dict]) -> FileBoundaryReport:
    """Check file boundaries are well-formed and locks don't conflict."""
    conflicts: list[str] = []
    locks_map: dict[str, list[str]] = {}

    for t in tasks:
        tid = t.get("task_id", t.get("name", "?"))
        boundary = t.get("implementation_boundary", {})
        if not isinstance(boundary, dict):
            continue

        allowed = boundary.get("allowed_paths", [])
        allowed_globs = boundary.get("allowed_path_globs", [])
        forbidden = boundary.get("forbidden_paths", [])
        expected = boundary.get("expected_output_files", [])

        # allowed_paths or allowed_path_globs must be non-empty (skip for doc tasks)
        cat = t.get("category", "")
        if not allowed and not allowed_globs and cat not in ("doc",):
            conflicts.append(f"{tid}: allowed_paths 和 allowed_path_globs 均为空")

        # forbidden_paths must include .cogniforge
        forbidden_str = " ".join(forbidden)
        if ".cogniforge" not in forbidden_str:
            conflicts.append(f"{tid}: forbidden_paths 未包含 .cogniforge")

        # expected_output_files must stay within allowed boundaries
        for f in expected:
            in_boundary = _path_in_boundary(f, allowed, allowed_globs)
            if not in_boundary:
                conflicts.append(
                    f"{tid}: expected_output_file '{f}' 不在 allowed_paths/globs 范围内"
                )

        # Collect file locks
        for f in t.get("file_locks", []):
            locks_map.setdefault(f, []).append(tid)

    # Check lock conflicts
    for f, owners in locks_map.items():
        if len(owners) > 1:
            conflicts.append(f"文件锁冲突: '{f}' 被 {owners} 同时锁定")

    return FileBoundaryReport(
        passed=len(conflicts) == 0,
        conflicts=conflicts,
    )


def _path_in_boundary(filepath: str, allowed: list[str],
                      globs: list[str]) -> bool:
    """Check if a file path falls within at least one allowed path or glob."""
    from fnmatch import fnmatch

    for prefix in allowed:
        if filepath.startswith(prefix):
            return True
    for pattern in globs:
        if fnmatch(filepath, pattern):
            return True
    return len(allowed) == 0 and len(globs) == 0  # no boundary set = accept


# ═══════════════════════════════════════════════════════════════════════
# Dimension 4: DAG
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class DAGValidationReport:
    passed: bool = True
    missing_deps: list[str] = field(default_factory=list)
    layer_violations: list[str] = field(default_factory=list)
    cycle_found: bool = False

    def format(self) -> str:
        if self.passed:
            return "DAG: PASS"
        parts = ["DAG: FAIL"]
        if self.missing_deps:
            parts.append(f"  缺失依赖: {', '.join(self.missing_deps)}")
        if self.layer_violations:
            parts.append(f"  层级违规: {', '.join(self.layer_violations)}")
        if self.cycle_found:
            parts.append("  检测到循环依赖")
        return "\n".join(parts)


def validate_dag(tasks: list[dict]) -> DAGValidationReport:
    """Validate the task dependency graph."""
    task_ids = {t.get("task_id", "") for t in tasks}
    id_to_task = {t.get("task_id", ""): t for t in tasks}
    missing_deps: list[str] = []
    layer_violations: list[str] = []

    for t in tasks:
        tid = t.get("task_id", "")
        layer = t.get("layer", 0)

        for dep_id in t.get("deps", []):
            # Dep must exist
            if dep_id not in task_ids:
                missing_deps.append(f"{tid} → {dep_id} (缺失)")
                continue

            # Dep must be at same or lower layer (test tasks can depend on any layer)
            cat = t.get("category", "")
            if cat != "test":
                dep_task = id_to_task.get(dep_id)
                if dep_task and dep_task.get("layer", 0) > layer:
                    layer_violations.append(
                        f"{tid} (layer={layer}) 依赖了更高层的 {dep_id} (layer={dep_task.get('layer', 0)})"
                    )

    # Cycle detection via DFS
    has_cycle = _has_cycle(task_ids, tasks)

    return DAGValidationReport(
        passed=len(missing_deps) == 0 and len(layer_violations) == 0 and not has_cycle,
        missing_deps=missing_deps,
        layer_violations=layer_violations,
        cycle_found=has_cycle,
    )


def _has_cycle(task_ids: set[str], tasks: list[dict]) -> bool:
    """DFS-based cycle detection."""
    adj: dict[str, list[str]] = {tid: [] for tid in task_ids}
    for t in tasks:
        tid = t.get("task_id", "")
        for dep_id in t.get("deps", []):
            if dep_id in adj:
                adj[dep_id].append(tid)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {tid: WHITE for tid in task_ids}

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for neighbor in adj.get(node, []):
            if color.get(neighbor) == GRAY:
                return True
            if color.get(neighbor) == WHITE:
                if dfs(neighbor):
                    return True
        color[node] = BLACK
        return False

    for tid in task_ids:
        if color.get(tid) == WHITE:
            if dfs(tid):
                return True
    return False


def validate_coverage(lld_path: Path | dict, task_refs: list[list[dict]],
                      module_type: str = "service") -> CoverageReport:
    """Compare LLD artifacts against task lld_refs.

    Args:
        lld_path: Path to LLD JSON or already-loaded dict.
        task_refs: List of per-task lld_refs lists.
        module_type: Module type for section-aware checking.

    Returns CoverageReport with pass/fail and gap details.
    """
    registry = LLDArtifactRegistry.from_lld(lld_path)
    all_entries = list(registry.iter_all())

    # Build a flat set of (section, item_name) from all task refs
    covered: set[tuple[str, str]] = set()
    covered_svc_methods: dict[str, set[str]] = {}  # service_name → {method_names}
    covered_sm_transitions: dict[str, set[str]] = {}  # entity → {transition_labels}

    for ref_list in task_refs:
        for ref in ref_list:
            section = ref.get("section", "")
            item_name = ref.get("item_name", "")
            sub = ref.get("sub_item")
            covered.add((section, item_name))

            # Track sub-item coverage for service_contracts
            if section == "service_contracts" and sub:
                covered_svc_methods.setdefault(item_name, set()).add(sub)

            # Track sub-item coverage for state_machines
            if section == "business_rules" and sub:
                covered_sm_transitions.setdefault(item_name, set()).add(sub)

    # Mandatory-coverage sections (must be 100%)
    mandatory_sections = {
        "service":        ["data_models", "service_contracts", "interfaces"],
        "database":       ["data_models", "index_strategy"],
        "gateway":        ["route_table", "interfaces"],
        "frontend":       ["component_tree", "interfaces"],
        "infrastructure": ["topology", "interfaces"],
    }
    mandatory = mandatory_sections.get(module_type, ["interfaces"])

    uncovered: list[tuple[str, str]] = []
    partially_covered: list[tuple[str, str, list[str]]] = []
    covered_count = 0

    for entry in all_entries:
        key = (entry.section, entry.item_name)
        is_covered = key in covered
        is_mandatory = entry.section in mandatory

        if is_covered:
            covered_count += 1
        elif is_mandatory:
            uncovered.append(key)
        # Non-mandatory uncovered → not counted as violation but still tracked

        # Check sub_item coverage for service_contracts
        if entry.section == "service_contracts" and is_covered and entry.sub_items:
            covered_methods = covered_svc_methods.get(entry.item_name, set())
            missing = [m for m in entry.sub_items if m not in covered_methods]
            if missing:
                partially_covered.append((entry.section, entry.item_name, missing))

        # Check sub_item coverage for state_machines
        if (entry.section == "business_rules"
                and entry.artifact_type == "state_machine"
                and is_covered
                and entry.sub_items):
            covered_trans = covered_sm_transitions.get(entry.item_name, set())
            missing = [t for t in entry.sub_items if t not in covered_trans]
            if missing:
                partially_covered.append((entry.section, entry.item_name, missing))

    # Count only mandatory-section entries for coverage ratio
    mandatory_entries = [e for e in all_entries if e.section in mandatory]
    total = len(mandatory_entries) if mandatory_entries else len(all_entries)

    # covered_count should only count mandatory entries that are covered
    covered_mandatory = sum(
        1 for e in mandatory_entries if (e.section, e.item_name) in covered
    ) if mandatory_entries else covered_count

    coverage_pct = (covered_mandatory / total * 100) if total > 0 else 0.0

    # Partially-covered is advisory — doesn't block pass on its own
    has_uncovered = len(uncovered) > 0
    passed = not has_uncovered

    return CoverageReport(
        total_artifacts=total,
        covered_artifacts=covered_count,
        uncovered=uncovered,
        partially_covered=partially_covered,
        coverage_pct=coverage_pct,
        passed=passed,
    )
