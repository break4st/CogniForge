"""Coverage validator — mechanically compare LLD artifacts against task lld_refs.

Pure data comparison.  No LLM involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cogniforge.wbs.lld_artifact_registry import LLDArtifactRegistry


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
