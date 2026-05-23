"""Tech Lead Agent - Schedules tasks and governs execution"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import DocumentType, TaskPriority
from cogniforge.core.exceptions import AgentError


class TechLeadAgent(BaseAgent):
    """Tech Lead Agent — delegates WBS creation and quality evaluation to
    Claude Code agent.  Flow control decisions stay operational."""

    def run(self, input_data: dict) -> dict:
        try:
            action = input_data.get("action", "create_wbs")

            if action == "decide_next":
                return self._decide_next(input_data)

            if action == "control_flow":
                return self._control_flow(input_data)

            if self.agent is None:
                raise AgentError("TechLeadAgent requires a Claude Code agent for this action")

            if action == "create_wbs":
                return self._structured_create_wbs(input_data)
            elif action == "evaluate_quality":
                return self._agentic_evaluate_quality(input_data)
            else:
                return self.format_result(
                    status="failed", message=f"Unknown action: {action}"
                )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _register_wbs_tasks(self, tasks: list[dict], module: str) -> int:
        """Register pre-built WBS task dicts with TaskEngine. Returns count created."""
        count = 0
        for t_dict in tasks:
            try:
                ctx = t_dict.pop("context", None)
                lld_refs_data = t_dict.pop("lld_refs", [])
                exp_files = t_dict.pop("expected_output_files", [])
                layer_val = t_dict.pop("layer", 0)

                task = self.task_engine.create_task(
                    name=t_dict["name"],
                    module=t_dict["module"],
                    description=t_dict.get("description", ""),
                    deps=t_dict.get("deps", []),
                    priority=TaskPriority(t_dict.get("priority", 2)),
                    assignee=t_dict.get("assignee"),
                    estimated_hours=t_dict.get("estimated_hours"),
                    category=t_dict.get("category"),
                )
                if ctx:
                    from cogniforge.models.task import TaskContext
                    if isinstance(ctx, dict):
                        task.context = TaskContext(**ctx)
                    else:
                        task.context = ctx
                task.expected_output_files = exp_files
                task.layer = layer_val
                if lld_refs_data:
                    from cogniforge.models.task import LLDReference
                    task.lld_refs = [LLDReference(**r) for r in lld_refs_data]
                self._save_task(task, "feat: create WBS task")
                count += 1
            except Exception:
                pass
        return count

    def _structured_create_wbs(self, input_data: dict) -> dict:
        """Structured WBS creation: mechanical decomposition + LLM enrichment."""
        module = input_data.get("module", "unknown")

        lld_docs = self.wiki_system.list_documents(DocumentType.LLD, module=module)
        if not lld_docs:
            raise AgentError(f"No LLD found for module {module} — cannot create WBS")

        lld_path = Path(self.config.repo_path) / lld_docs[-1].path
        if not lld_path.exists():
            raise AgentError(f"LLD file not found: {lld_path}")

        from cogniforge.wbs.enriched_wbs_assembler import WBSAssembler
        assembler = WBSAssembler(self.wiki_system, self.task_engine, self.agent)
        result = assembler.assemble(module, lld_path)

        count = self._register_wbs_tasks(result.tasks, module)

        report = result.coverage
        coverage_msg = f", coverage={report.coverage_pct:.0f}%" if report else ""

        return self.format_result(
            status="success",
            message=f"WBS created: {count} tasks for {module}{coverage_msg}",
            data={"task_count": count, "coverage": report.coverage_pct if report else 0},
            decisions=[f"stubs={result.stubs_count}"],
        )

    def _save_task(self, task, commit_message: str) -> None:
        try:
            task_path = Path(f".cogniforge/wiki/tasks/{task.task_id}.json")
            full_path = self.config.repo_path / task_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(
                json.dumps(task.to_json(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.wiki_system.git_storage.repo.index.add([str(task_path)])
        except Exception:
            pass

    def _agentic_evaluate_quality(self, input_data: dict) -> dict:
        module = input_data.get("module", "unknown")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        existing = self.wiki_system.list_documents(DocumentType.REPORT)
        ql_count = sum(1 for d in existing if d.doc_id.startswith(f"quality-{module}-"))
        seq = ql_count + 1
        doc_id = f"quality-{module}-{seq:03d}"
        json_path = self.wiki_system.agent_path(DocumentType.REPORT, doc_id=doc_id)

        prompt = (
            f"评估以下模块的质量门禁，以 JSON 格式输出并写入:\n\n"
            f"输出路径: {json_path}\n"
            f"JSON 结构: {{\"meta\": {{\"doc_id\": \"{doc_id}\", \"type\": \"report\", "
            f"\"title\": \"质量评估 - {module}\", "
            f"\"author\": \"techlead_agent\", \"created\": \"{now}\"}},\n"
            f" \"content\": \"... (包含 PASS/FAIL 结论及各检查项结果)\"}}\n\n"
            f"输入数据:\n"
            f"module: {module}\n\n"
            f"要求:\n"
            f"1. 阅读该模块的 LLD、代码、CR 报告、测试报告\n"
            f"2. 检查：CR 是否通过、测试是否通过、代码是否符合设计\n"
            f"3. 在 content 字段中明确给出 PASS/FAIL 结论\n"
            f"4. 使用中文、只写 JSON 不写 HTML、完成后回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="techlead")
        return self._commit_result(json_path, f"质量评估 - {module}", "techlead_agent",
                                   f"docs: quality evaluation for {module}", response.content)

    def _decide_next(self, input_data: dict) -> dict:
        return self.format_result(
            status="success",
            message="Decision deferred to Tech Lead",
            data={"next_action": "advance"},
        )

    def _control_flow(self, input_data: dict) -> dict:
        return self.format_result(
            status="success",
            message="Flow control active",
            data={"status": "ok"},
        )

    def _commit_result(self, json_path: Path, title: str, author: str,
                       commit_msg: str, reasoning: str = "") -> dict:
        json_abs = Path(self.config.repo_path) / json_path
        if not json_abs.exists():
            return self.format_result(status="failed",
                                       message=f"Claude Code did not produce {json_path}")

        rel_json = json_path.relative_to(self.config.repo_path).as_posix()
        self.wiki_system.git_storage.repo.index.add([rel_json])

        from cogniforge.wiki.wiki_renderer import render_file
        html_path = render_file(json_abs)
        rel_html = html_path.relative_to(self.config.repo_path).as_posix() if html_path else ""
        if rel_html:
            self.wiki_system.git_storage.repo.index.add([rel_html])

        artifacts = [rel_json]
        if rel_html:
            artifacts.append(rel_html)

        self.wiki_system.git_storage.commit(commit_msg, author)

        return self.format_result(
            status="success",
            message=f"Document created: {json_path.stem}",
            artifacts=artifacts,
            reasoning=reasoning,
        )
