"""TL Turn Result — Tech Lead Agent per-turn output.

Follows the same pattern as:
  - pm-turn-result (PM Agent)
  - se-turn-result (SE/Architect Agent)
  - mde-turn-result (MDE/Design Agent)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CoverageSummary(BaseModel):
    """Coverage statistics from WBS validation."""
    total_artifacts: int = 0
    covered: int = 0
    uncovered: int = 0
    coverage_pct: float = 0.0
    passed: bool = False


class UpstreamIssue(BaseModel):
    """An issue discovered in an upstream design document."""
    target: str = ""          # "prd" | "sad" | "lld" | "mde" | "se"
    issue_type: str = ""      # e.g., "incomplete_contract", "missing_section"
    artifact_id: str = ""     # e.g., "CTR-007", "SC-003"
    description: str = ""
    suggested_action: str = ""


class TLTurnResult(BaseModel):
    """Tech Lead per-turn structured output.

    Analogous to pm-turn-result / se-turn-result / mde-turn-result.
    """

    status: str = "success"          # "success" | "blocked" | "failed" | "no_change"
    operation: str = "create_wbs"    # "create_wbs" | "retro" | "evaluate_quality" | "schedule"
    wbs_id: str = ""
    created_tasks: list[str] = Field(default_factory=list)
    updated_tasks: list[str] = Field(default_factory=list)
    blocked_tasks: list[str] = Field(default_factory=list)
    coverage_summary: CoverageSummary = Field(default_factory=CoverageSummary)
    upstream_issues: list[UpstreamIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    message: str = ""

    def to_json(self) -> dict:
        data = self.model_dump(mode="json")
        return data

    @classmethod
    def from_json_dict(cls, data: dict) -> "TLTurnResult":
        return cls.model_validate(data)


def build_tl_result(
    status: str,
    wbs_id: str,
    task_ids: list[str],
    coverage: dict | None = None,
    upstream_issues: list[dict] | None = None,
    message: str = "",
) -> TLTurnResult:
    """Convenience factory for building a TLTurnResult."""
    cov = CoverageSummary()
    if coverage:
        cov = CoverageSummary(
            total_artifacts=coverage.get("total_artifacts", 0),
            covered=coverage.get("covered", 0),
            uncovered=coverage.get("uncovered", 0),
            coverage_pct=coverage.get("coverage_pct", 0.0),
            passed=coverage.get("passed", False),
        )

    issues = []
    if upstream_issues:
        for ui in upstream_issues:
            issues.append(UpstreamIssue(
                target=ui.get("target", ""),
                issue_type=ui.get("issue_type", ""),
                artifact_id=ui.get("artifact_id", ""),
                description=ui.get("description", ""),
                suggested_action=ui.get("suggested_action", ""),
            ))

    return TLTurnResult(
        status=status,
        operation="create_wbs",
        wbs_id=wbs_id,
        created_tasks=task_ids,
        coverage_summary=cov,
        upstream_issues=issues,
        message=message,
    )
