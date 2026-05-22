"""WBS (Work Breakdown Structure) — MDE→DEV structured translation layer.

Transforms structured LLD JSON into traceable, verifiable Task units
that DEV Agents can consume without re-reading the full LLD.
"""

from cogniforge.wbs.lld_artifact_registry import LLDArtifactRegistry, ArtifactEntry

__all__ = ["LLDArtifactRegistry", "ArtifactEntry"]
