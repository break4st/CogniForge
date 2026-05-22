"""Task stub generator — orchestrate decomposition rules over an LLD registry."""

from __future__ import annotations

from cogniforge.wbs.decomposition_rules import decompose, TaskStub
from cogniforge.wbs.lld_artifact_registry import LLDArtifactRegistry


def generate(registry: LLDArtifactRegistry) -> list[TaskStub]:
    """Generate task stubs from an LLD registry.

    Returns a flat list of TaskStub ordered by layer then suggested_name.
    """
    stubs = decompose(registry)
    # Sort: layer ascending, then by name
    stubs.sort(key=lambda s: (s.layer, s.suggested_name))
    return stubs


def generate_summary(stubs: list[TaskStub]) -> dict:
    """Return a summary dict for logging / display."""
    by_layer: dict[int, int] = {}
    by_category: dict[str, int] = {}
    for s in stubs:
        by_layer[s.layer] = by_layer.get(s.layer, 0) + 1
        by_category[s.category] = by_category.get(s.category, 0) + 1
    return {
        "total": len(stubs),
        "by_layer": by_layer,
        "by_category": by_category,
    }
