"""DEV Runner — invoke the DEV Agent (Claude Code) for a single task.

Prepares a task-specific prompt with boundaries, context, acceptance criteria,
and output format.  Collects and validates the dev-run-result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from fnmatch import fnmatch


@dataclass
class FileValidationResult:
    passed: bool = True
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def prepare_dev_prompt(task: dict) -> str:
    """Build the DEV Agent system prompt from a task dict.

    The task dict should include: task_id, name, description, module,
    implementation_boundary, context, acceptance_criteria, validation.
    """
    tid = task.get("task_id", task.get("name", "?"))
    name = task.get("name", "")
    desc = task.get("description", "")
    module = task.get("module", "")

    boundary = task.get("implementation_boundary", {})
    if not isinstance(boundary, dict):
        boundary = {}

    allowed = boundary.get("allowed_paths", [])
    allowed_globs = boundary.get("allowed_path_globs", [])
    forbidden = boundary.get("forbidden_paths", [])
    expected = boundary.get("expected_output_files", [])
    max_files = boundary.get("max_files_changed", 6)

    acs = task.get("acceptance_criteria", [])
    val_cmds = task.get("validation", {}).get("commands", []) if isinstance(
        task.get("validation"), dict
    ) else []

    prompt = f"""你是 DEV Agent，负责实现一个且仅一个 task.json 中定义的工程任务。

## 任务信息
- task_id: {tid}
- 名称: {name}
- 模块: {module}
- 描述: {desc}

## 实现边界
你只能修改以下路径内的文件:
"""
    for p in allowed:
        prompt += f"  - {p}\n"
    for g in allowed_globs:
        prompt += f"  - {g} (glob)\n"

    prompt += f"""
绝对禁止修改以下路径:
"""
    for p in forbidden:
        prompt += f"  - {p}\n"

    prompt += f"""
期望产出文件:
"""
    for f in expected:
        prompt += f"  - {f}\n"

    prompt += f"""
最多修改 {max_files} 个文件。

## 验收标准
"""
    for i, ac in enumerate(acs):
        if isinstance(ac, dict):
            prompt += f"{i + 1}. [{ac.get('id', '?')}] {ac.get('description', '')} — 期望: {ac.get('expected', '')}\n"

    prompt += """
## 规则
1. 只实现当前 task_id 对应的任务，不扩大范围。
2. 只能修改 implementation_boundary 内的文件。
3. 禁止修改 forbidden_paths 中的任何文件。
4. 禁止修改 PRD、SAD、LLD、WBS、task JSON 本身。
5. 必须依据 lld_refs 和 context.scope 实现。
6. 如果发现 LLD 信息不足，返回 status=blocked + blocked_reason，不要猜测。
7. 完成后必须输出符合 dev-run-result-schema.json 的结构化 JSON。

## 输出格式
返回一个 JSON 对象:
```json
{
  "task_id": "{tid}",
  "status": "implemented",
  "summary": "...",
  "changed_files": [{"path": "...", "change_type": "created|modified|deleted"}],
  "commands_run": [{"command": "...", "exit_code": 0, "summary": "..."}],
  "acceptance_results": [{"acceptance_id": "...", "status": "passed|failed|skipped", "evidence": "..."}],
  "blocked_reason": "",
  "upstream_issues": [],
  "follow_up_tasks": [],
  "notes_for_reviewer": []
}
```
"""
    return prompt


def validate_changed_files(
    task: dict,
    changed_files: list[dict],
    repo_path: Path | None = None,
) -> FileValidationResult:
    """Check that all changed files respect the task's implementation boundary."""
    boundary = task.get("implementation_boundary", {})
    if not isinstance(boundary, dict):
        return FileValidationResult(passed=False,
                                     violations=["implementation_boundary 缺失"])

    allowed = boundary.get("allowed_paths", [])
    allowed_globs = boundary.get("allowed_path_globs", [])
    forbidden = boundary.get("forbidden_paths", [])
    max_files = boundary.get("max_files_changed", 6)

    violations: list[str] = []
    warnings: list[str] = []

    # Check file count
    if len(changed_files) > max_files:
        violations.append(
            f"修改了 {len(changed_files)} 个文件，超过上限 {max_files}"
        )

    for cf in changed_files:
        fpath = cf.get("path", "") if isinstance(cf, dict) else str(cf)

        # Forbidden check
        for fb in forbidden:
            if fpath.startswith(fb) or fnmatch(fpath, fb):
                violations.append(f"禁止修改的文件被修改: {fpath} (forbidden: {fb})")
                break

        # Allowed check
        in_allowed = False
        for prefix in allowed:
            if fpath.startswith(prefix):
                in_allowed = True
                break
        for pattern in allowed_globs:
            if fnmatch(fpath, pattern):
                in_allowed = True
                break
        if not in_allowed and allowed:
            violations.append(f"文件不在允许范围内: {fpath}")

    # Check expected_output_files
    expected = boundary.get("expected_output_files", [])
    actual_paths = {
        cf.get("path", "") if isinstance(cf, dict) else str(cf)
        for cf in changed_files
    }
    for exp_f in expected:
        if exp_f not in actual_paths:
            warnings.append(f"期望产出文件未创建/修改: {exp_f}")

    return FileValidationResult(
        passed=len(violations) == 0,
        violations=violations,
        warnings=warnings,
    )


def extract_dev_run_result(raw_output: str, schema_path: Path | None = None) -> dict:
    """Extract and parse a dev-run-result JSON from Claude Code output.

    Handles markdown code fences and leading/trailing text.
    Returns the parsed dict, or an error dict with status='parse_error'.
    """
    text = raw_output.strip()

    # Try extracting from ```json fence
    start = text.find("```json")
    if start >= 0:
        start = text.find("\n", start) + 1
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()

    # Try extracting from ``` fence
    elif text.startswith("```"):
        end = text.find("```", 3)
        if end > 3:
            text = text[3:end].strip()

    # Try direct JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Last resort: find JSON object
    obj_start = text.find("{")
    obj_end = text.rfind("}")
    if obj_start >= 0 and obj_end > obj_start:
        try:
            return json.loads(text[obj_start:obj_end + 1])
        except json.JSONDecodeError:
            pass

    return {
        "task_id": "",
        "status": "parse_error",
        "summary": "无法解析 DEV Agent 输出",
        "changed_files": [],
    }
