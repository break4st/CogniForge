"""Tech Lead Gate — post-DEV quality checks before CR.

Runs after DEV Agent completes a task. Checks:
  1. File boundary violations
  2. Acceptance criteria pass/fail
  3. Validation commands
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class GateCheck:
    name: str = ""
    passed: bool = False
    detail: str = ""


@dataclass
class GateResult:
    passed: bool = True
    checks: list[GateCheck] = field(default_factory=list)
    action: str = "advance_to_cr"  # "advance_to_cr" | "return_to_dev"


@dataclass
class CommandResult:
    command: str = ""
    return_code: int = -1
    stdout: str = ""
    stderr: str = ""
    passed: bool = False


class TechLeadGate:
    """Run post-DEV quality checks for a single task."""

    def __init__(self, repo_path: Path | None = None):
        self.repo_path = repo_path or Path.cwd()

    def run_checks(
        self,
        task: dict,
        dev_result: dict,
        changed_files: list[dict] | None = None,
    ) -> GateResult:
        """Run all gate checks. Returns GateResult with pass/fail and recommended action."""
        checks: list[GateCheck] = []

        # 1. File boundary check
        from cogniforge.execution.dev_runner import validate_changed_files

        if changed_files:
            fv = validate_changed_files(task, changed_files, self.repo_path)
            checks.append(GateCheck(
                name="文件越界检查",
                passed=fv.passed,
                detail="; ".join(fv.violations) if fv.violations else "所有文件在边界内",
            ))

        # 2. Acceptance criteria check
        acs = task.get("acceptance_criteria", [])
        ac_results = dev_result.get("acceptance_results", [])
        ac_map = {r.get("acceptance_id", ""): r for r in ac_results}

        for ac in acs:
            if not isinstance(ac, dict):
                continue
            aid = ac.get("id", "")
            result = ac_map.get(aid, {})
            ac_passed = result.get("status") == "passed"
            checks.append(GateCheck(
                name=f"验收: {ac.get('description', aid)[:60]}",
                passed=ac_passed,
                detail=result.get("evidence", "未找到验收结果") if not ac_passed else result.get("evidence", ""),
            ))

        # 3. Validation commands
        validation = task.get("validation", {})
        if isinstance(validation, dict):
            for cmd in validation.get("commands", []):
                if not isinstance(cmd, dict):
                    continue
                cr = self._run_command(cmd.get("command", ""))
                checks.append(GateCheck(
                    name=f"命令: {cmd.get('name', cmd.get('command', '?'))}",
                    passed=cr.passed,
                    detail=cr.stdout[:200] if cr.passed else cr.stderr[:200],
                ))

        passed = all(c.passed for c in checks)
        return GateResult(
            passed=passed,
            checks=checks,
            action="advance_to_cr" if passed else "return_to_dev",
        )

    def _run_command(self, command: str, timeout: int = 120) -> CommandResult:
        """Execute a shell command and capture result."""
        if not command:
            return CommandResult(passed=True)

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.repo_path),
            )
            return CommandResult(
                command=command,
                return_code=result.returncode,
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
                passed=result.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                command=command,
                return_code=-1,
                stderr=f"命令超时 ({timeout}s)",
                passed=False,
            )
        except Exception as e:
            return CommandResult(
                command=command,
                return_code=-1,
                stderr=str(e),
                passed=False,
            )
