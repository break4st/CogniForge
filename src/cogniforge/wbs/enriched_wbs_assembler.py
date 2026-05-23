"""WBS Assembler — orchestrate mechanical decomposition + LLM enrichment + coverage."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from cogniforge.wbs.decomposition_rules import TaskStub
from cogniforge.wbs.lld_artifact_registry import LLDArtifactRegistry
from cogniforge.wbs.task_stub_generator import generate, generate_summary
from cogniforge.wbs.coverage_validator import validate_coverage, CoverageReport
from cogniforge.wbs.task_context_builder import build_context
from cogniforge.core.constants import TaskPriority

if TYPE_CHECKING:
    from cogniforge.llm.base import BaseLLMAdapter
    from cogniforge.wiki.wiki_system import WikiSystem


@dataclass
class WBSResult:
    tasks: list[dict] = field(default_factory=list)
    coverage: CoverageReport | None = None
    stubs_count: int = 0
    llm_rounds: int = 0
    mode: str = "structured"


class WBSAssembler:
    """Orchestrate structured WBS creation.

    Flow:
      1. Parse LLD → ArtifactRegistry
      2. Generate TaskStubs mechanically
      3. LLM enriches descriptions, estimates, priority, deps
      4. Validate coverage → retry if gaps (max 2 rounds)
      5. Build TaskContext for each task
    """

    def __init__(self, wiki_system: "WikiSystem", task_engine,
                 llm_adapter: "BaseLLMAdapter"):
        self.wiki = wiki_system
        self.task_engine = task_engine
        self.llm = llm_adapter

    def assemble(self, module: str, lld_path: Path,
                 max_llm_rounds: int = 2,
                 progress_callback: Callable[[str], None] | None = None) -> WBSResult:
        """Run the full structured WBS pipeline.

        Args:
            module: Module name.
            lld_path: Path to the LLD JSON file.
            max_llm_rounds: Max coverage-correction rounds.
            progress_callback: Optional callback(phase: str) for progress display.

        Returns:
            WBSResult with task dicts and coverage report.
        """
        # 1. Parse LLD
        if progress_callback:
            progress_callback("解析 LLD")
        registry = LLDArtifactRegistry.from_lld(lld_path)
        lld_data = _load_lld_json(lld_path)

        # 2. Mechanical stub generation
        if progress_callback:
            progress_callback("机械任务生成")
        stubs = generate(registry)
        summary = generate_summary(stubs)

        # 3. LLM enrichment
        enriched = stubs
        report = None
        for round_idx in range(max_llm_rounds + 1):
            if progress_callback:
                progress_callback(f"LLM 丰富第 {round_idx + 1} 轮")
            enriched = self._llm_enrich(module, enriched, lld_path, lld_data, round_idx,
                                         progress_callback=progress_callback)

            # 4. Coverage check
            if progress_callback:
                progress_callback("验证覆盖率")
            task_refs = [[ref for ref in s.lld_refs] for s in enriched if s.category != "test"]
            report = validate_coverage(lld_data, task_refs, registry.module_type)

            if report.passed:
                break

        # 5. Build TaskContext and assemble final task dicts
        if progress_callback:
            progress_callback("构建任务上下文")
        all_module_llds = _load_all_module_llds(self.wiki, module)
        tasks = self._build_task_dicts(enriched, registry, lld_data, all_module_llds, module)

        return WBSResult(
            tasks=tasks,
            coverage=report,
            stubs_count=summary["total"],
            llm_rounds=max_llm_rounds if not (report and report.passed) else 0,
            mode="structured",
        )

    def assemble_batch(self, module_specs: list[tuple[str, Path]]) -> list[WBSResult]:
        """Assemble WBS for multiple modules with a single batched LLM call.

        Args:
            module_specs: List of (module_name, lld_path) tuples.

        Returns:
            One WBSResult per module, in the same order.
        """
        # Phase 1: Mechanical stub generation for all modules
        per_module: list[dict] = []  # [{module, registry, lld_data, stubs}]
        all_stubs: list[dict] = []   # [{module, stubs}]

        for mod_name, lld_path in module_specs:
            registry = LLDArtifactRegistry.from_lld(lld_path)
            lld_data = _load_lld_json(lld_path)
            stubs = generate(registry)
            per_module.append({
                "module": mod_name, "registry": registry,
                "lld_data": lld_data, "stubs": stubs,
            })
            all_stubs.append({"module": mod_name, "stubs": stubs})

        # Phase 2: Single batched LLM enrichment
        enriched_map = self._llm_enrich_batch(all_stubs)

        # Phase 3: Coverage validation + task dicts per module
        all_llds = _load_all_module_llds(self.wiki, "")
        results: list[WBSResult] = []

        for pm in per_module:
            mod_name = pm["module"]
            registry = pm["registry"]
            lld_data = pm["lld_data"]
            stubs = enriched_map.get(mod_name, pm["stubs"])

            # Coverage check
            task_refs = [[ref for ref in s.lld_refs] for s in stubs if s.category != "test"]
            report = validate_coverage(lld_data, task_refs, registry.module_type)

            # Build task dicts
            tasks = self._build_task_dicts(stubs, registry, lld_data, all_llds, mod_name)

            results.append(WBSResult(
                tasks=tasks, coverage=report,
                stubs_count=len(stubs), llm_rounds=0,
                mode="structured",
            ))

        return results

    def _llm_enrich_batch(self, all_stubs: list[dict]) -> dict[str, list[TaskStub]]:
        """Single LLM call to enrich stubs for all modules.

        Returns {module_name: enriched_stubs}.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        total_stubs = sum(len(m["stubs"]) for m in all_stubs)

        # Build flat indexed stub list with module prefix
        flat_stubs: list[dict] = []
        idx = 0
        for m in all_stubs:
            for s in m["stubs"]:
                flat_stubs.append({
                    "index": idx,
                    "module": m["module"],
                    "suggested_name": s.suggested_name,
                    "category": s.category,
                    "layer": s.layer,
                    "description_guide": s.description_guide,
                    "lld_refs": s.lld_refs,
                    "expected_output_files": s.expected_output_files,
                })
                idx += 1

        modules_list = [m["module"] for m in all_stubs]
        prompt = (
            f"## 任务: 批量丰富 WBS 任务描述\n\n"
            f"模块列表 ({len(all_stubs)} 个): {', '.join(modules_list)}\n"
            f"时间: {now}\n\n"
            f"以下是从各模块 LLD 机械推导出的 {total_stubs} 个任务骨架（{len(all_stubs)} 个模块合计）。\n"
            f"请阅读各模块的 .cogniforge/wiki/lld/{{module}}/ 下的 LLD 文件，对每个任务执行:\n\n"
            f"1. 填写详细的 description（中文，2-8小时粒度，明确产出物）\n"
            f"2. 允许的微调: 合并 < 2h 小任务、拆分 > 8h 大任务（注明理由）\n"
            f"3. 设置 priority (0=阻塞 1=高 2=中 3=低)\n"
            f"4. 估算 estimated_hours (float)\n"
            f"5. 排序依赖关系 deps（模块内的依赖按 suggested_name 引用）\n"
            f"6. **禁止删除任何 lld_refs**\n"
            f"7. 跨模块依赖标注: 如果任务依赖其他模块的接口，在 inter_module_deps 字段中注明模块名\n\n"
            f"输入骨架:\n{json.dumps(flat_stubs, ensure_ascii=False, indent=2)}\n\n"
            f"输出格式 (严格 JSON 数组):\n"
            f'[{{"index": 0, "name": "...", "description": "...", '
            f'"deps": ["上游建议名"], "inter_module_deps": ["依赖的模块名"], '
            f'"priority": 1, "estimated_hours": 4.0, '
            f'"category": "model", "layer": 0, '
            f'"lld_refs": [...], "expected_output_files": [...], '
            f'"adjustments": [null]}}]\n\n'
            f"要求: 只输出 JSON 数组，不输出其他内容。"
        )

        response = self.llm.generate_agentic(prompt, role="techlead")
        enriched_dicts = _parse_llm_json_array(response.content)

        # Group back by module
        result: dict[str, list[TaskStub]] = {m["module"]: [] for m in all_stubs}
        if not enriched_dicts:
            # Parse failed — return originals
            for m in all_stubs:
                result[m["module"]] = list(m["stubs"])
            return result

        # Build index → stub + module map
        flat_stub_map: dict[int, tuple[str, TaskStub]] = {}
        idx = 0
        for m in all_stubs:
            for s in m["stubs"]:
                flat_stub_map[idx] = (m["module"], s)
                idx += 1

        # Merge enriched data back
        merged: dict[str, list[TaskStub]] = {m["module"]: [] for m in all_stubs}
        for ed in enriched_dicts:
            if not isinstance(ed, dict):
                continue
            eidx = ed.get("index", -1)
            if eidx in flat_stub_map:
                mod, stub = flat_stub_map[eidx]
                if ed.get("name"):
                    stub.suggested_name = ed["name"]
                stub.description_guide = ed.get("description", stub.description_guide)
                deps = ed.get("deps", [])
                if deps:
                    stub.inferred_deps = deps
                stub.confidence = "high"
                merged[mod].append(stub)
            else:
                # New stub from LLM split — put in its module
                mod = ed.get("module", modules_list[0] if modules_list else "unknown")
                new_stub = TaskStub(
                    suggested_name=ed.get("name", "new-task"),
                    category=ed.get("category", "service"),
                    lld_refs=ed.get("lld_refs", []),
                    description_guide=ed.get("description", ""),
                    inferred_deps=ed.get("deps", []),
                    expected_output_files=ed.get("expected_output_files", []),
                    layer=ed.get("layer", 1),
                    confidence="medium",
                )
                merged.setdefault(mod, []).append(new_stub)

        # Fill in any modules that didn't get results from LLM
        for m in all_stubs:
            if not merged[m["module"]]:
                merged[m["module"]] = list(m["stubs"])

        return merged

    def _llm_enrich(self, module: str, stubs: list[TaskStub],
                    lld_path: Path, lld_data: dict,
                    round_idx: int,
                    progress_callback: Callable[[str], None] | None = None) -> list[TaskStub]:
        """Send stubs to LLM for enrichment. Returns enriched stubs."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Build a compact JSON representation of stubs for the LLM
        stub_dicts = []
        for i, s in enumerate(stubs):
            stub_dicts.append({
                "index": i,
                "suggested_name": s.suggested_name,
                "category": s.category,
                "layer": s.layer,
                "description_guide": s.description_guide,
                "lld_refs": s.lld_refs,
                "expected_output_files": s.expected_output_files,
            })

        prompt = (
            f"## 任务: 丰富 WBS 任务描述\n\n"
            f"模块: {module}\n"
            f"LLD 路径: {lld_path}\n"
            f"时间: {now}\n\n"
            f"以下是从 LLD 机械推导出的 {len(stubs)} 个任务骨架。\n"
            f"请阅读 {lld_path} 中的完整 LLD，对每个任务执行:\n\n"
            f"1. 填写详细的 description（中文，2-8小时粒度，明确产出物）\n"
            f"2. 允许的微调 (allowed_adjustments):\n"
            f"   - 合并 < 2小时的小任务到相邻同层任务中（注明理由）\n"
            f"   - 拆分 > 8小时的复杂任务为子任务（注明理由）\n"
            f"3. 设置 priority (0=阻塞 1=高 2=中 3=低)\n"
            f"4. 估算 estimated_hours (float)\n"
            f"5. 排序依赖关系 deps (按 suggested_name 引用同批次内的任务)\n"
            f"6. **禁止删除任何 lld_refs** —— 机械推导出的引用必须全部保留\n\n"
            f"输入骨架:\n{json.dumps(stub_dicts, ensure_ascii=False, indent=2)}\n\n"
            f"输出格式 (严格 JSON 数组):\n"
            f'[{{"index": 0, "name": "...", "description": "...", '
            f'"deps": ["上游建议名"], "priority": 1, "estimated_hours": 4.0, '
            f'"category": "model", "layer": 0, '
            f'"lld_refs": [...], "expected_output_files": [...], '
            f'"adjustments": ["拆分理由" 或 null]}}]\n\n'
            f"要求: 只输出 JSON 数组，不输出其他内容。完成后不需要确认。"
        )

        response = self.llm.generate_agentic(prompt, role="techlead",
                                              progress_callback=progress_callback)

        # Try to parse LLM output
        enriched_dicts = _parse_llm_json_array(response.content)
        if not enriched_dicts:
            return stubs  # Parse failed, return originals

        # Filter out any non-dict entries (LLM may embed strings in arrays)
        enriched_dicts = [d for d in enriched_dicts if isinstance(d, dict)]

        # Merge LLM output back into stubs
        merged: list[TaskStub] = []
        index_map = {d.get("index", -1): d for d in enriched_dicts}

        for i, s in enumerate(stubs):
            ed = index_map.get(i)
            if ed and ed.get("name"):
                s.suggested_name = ed["name"]
                s.description_guide = ed.get("description", s.description_guide)
                s.confidence = "high"
            merged.append(s)

        # Handle newly-added stubs (LLM split a task)
        for d in enriched_dicts:
            idx = d.get("index", -1)
            if idx < 0 or idx >= len(stubs):
                new_stub = TaskStub(
                    suggested_name=d.get("name", "new-task"),
                    category=d.get("category", "service"),
                    lld_refs=d.get("lld_refs", []),
                    description_guide=d.get("description", ""),
                    inferred_deps=d.get("deps", []),
                    expected_output_files=d.get("expected_output_files", []),
                    layer=d.get("layer", 1),
                    confidence="medium",
                )
                merged.append(new_stub)

        return merged

    def _build_task_dicts(self, stubs: list[TaskStub], registry: LLDArtifactRegistry,
                          lld_data: dict, all_module_llds: dict[str, dict],
                          module: str) -> list[dict]:
        """Build final task dicts with TaskContext, ready for TaskEngine.create_task()."""
        tasks: list[dict] = []

        # Build name → index map for dep resolution
        name_to_idx: dict[str, int] = {}
        for i, s in enumerate(stubs):
            name_to_idx[s.suggested_name] = i

        for i, s in enumerate(stubs):
            # Resolve deps
            resolved_deps: list[str] = []
            for dep_name in s.inferred_deps:
                if dep_name in name_to_idx and name_to_idx[dep_name] < i:
                    resolved_deps.append(f"{module}-{name_to_idx[dep_name] + 1:03d}")

            priority_val = 2  # default medium
            # Use LLM-enriched description if available
            desc = getattr(s, "description_guide", "") or ""

            # Build context for implementation stubs (not tests)
            ctx = None
            if s.category != "test":
                ctx = build_context(s, registry, lld_data, all_module_llds)

            tasks.append({
                "name": s.suggested_name,
                "module": module,
                "description": desc,
                "deps": resolved_deps,
                "priority": priority_val,
                "assignee": "dev",
                "estimated_hours": _estimate_hours(s),
                "category": s.category,
                "lld_refs": s.lld_refs,
                "context": ctx,
                "expected_output_files": s.expected_output_files,
                "layer": s.layer,
            })

        return tasks


def _load_lld_json(path: Path) -> dict:
    import json
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        from cogniforge.wiki.wiki_renderer import load_json_with_repair
        return load_json_with_repair(path)


def _load_all_module_llds(wiki, exclude_module: str) -> dict[str, dict]:
    """Load LLD data for all modules except the current one."""
    from cogniforge.core.constants import DocumentType
    result: dict[str, dict] = {}
    try:
        all_llds = wiki.list_documents(DocumentType.LLD)
        for doc in all_llds:
            parts = doc.path.split("/")
            if len(parts) >= 4:
                mod_name = parts[3]
                if mod_name == exclude_module:
                    continue
                if mod_name not in result:
                    try:
                        abs_path = Path.cwd() / doc.path
                        result[mod_name] = _load_lld_json(abs_path)
                    except Exception:
                        pass
    except Exception:
        pass
    return result


def _parse_llm_json_array(text: str) -> list[dict]:
    """Try to extract a JSON array from LLM output."""
    text = text.strip()
    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    # Try extracting between [ and ]
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            result = json.loads(text[start:end + 1])
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
    return []


def _estimate_hours(stub: TaskStub) -> float:
    """Default hour estimation based on category and layer."""
    base = {
        "model": 2.0,
        "config": 1.0,
        "migration": 1.5,
        "service": 4.0,
        "endpoint": 3.0,
        "test": 2.0,
        "doc": 1.0,
        "fix": 2.0,
    }
    return base.get(stub.category, 2.0)
