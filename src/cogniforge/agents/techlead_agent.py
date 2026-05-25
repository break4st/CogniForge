"""Tech Lead Agent - Schedules tasks and governs execution"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import DocumentType, TaskPriority, TaskStatus
from cogniforge.core.exceptions import AgentError


def _load_wbs_task_schema(repo_path: Path) -> dict | None:
    """Load the WBS task JSON schema for validation. Returns None if missing."""
    schema_path = repo_path / "schemas" / "wbs-task-schema.json"
    if not schema_path.exists():
        return None
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _validate_task_against_schema(task_dict: dict, schema: dict) -> list[str]:
    """Validate a single task dict against wbs-task-schema.json.

    Returns a list of error messages (empty = valid).
    """
    try:
        import jsonschema
        validator = jsonschema.Draft7Validator(schema)
        errors = list(validator.iter_errors(task_dict))
        return [e.message for e in errors]
    except ImportError:
        return []
    except Exception as e:
        return [f"Schema 校验异常: {e}"]


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

            if action == "retro":
                return self._retro(input_data)

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
                source = t_dict.pop("source", None)
                boundary = t_dict.pop("implementation_boundary", None)
                validation = t_dict.pop("validation", None)
                dev_agent = t_dict.pop("dev_agent", None)
                file_locks = t_dict.pop("file_locks", [])
                acceptance_criteria = t_dict.pop("acceptance_criteria", [])

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
                task.file_locks = file_locks

                if lld_refs_data:
                    from cogniforge.models.task import LLDReference
                    task.lld_refs = [LLDReference(**r) for r in lld_refs_data]

                if source and isinstance(source, dict):
                    from cogniforge.models.task import TaskSource
                    task.source = TaskSource(**source)

                if boundary and isinstance(boundary, dict):
                    from cogniforge.models.task import ImplementationBoundary
                    task.implementation_boundary = ImplementationBoundary(**boundary)

                if validation and isinstance(validation, dict):
                    from cogniforge.models.task import TaskValidation
                    task.validation = TaskValidation(**validation)

                if dev_agent and isinstance(dev_agent, dict):
                    from cogniforge.models.task import DevAgentConfig
                    task.dev_agent = DevAgentConfig(**dev_agent)

                if acceptance_criteria:
                    from cogniforge.models.task import AcceptanceCriterion
                    task.acceptance_criteria = [
                        AcceptanceCriterion(**ac) for ac in acceptance_criteria
                        if isinstance(ac, dict)
                    ]

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

        # Build RepoConventions from config (optionally enriched by SAD)
        conventions = self.config.build_repo_conventions()

        from cogniforge.wbs.enriched_wbs_assembler import WBSAssembler
        assembler = WBSAssembler(self.wiki_system, self.task_engine,
                                 self.agent, conventions)
        result = assembler.assemble(module, lld_path)

        # Run four-dimensional validation
        quality_gates = assembler.validate_all(result.tasks)

        # Validate tasks against wbs-task-schema.json
        schema = _load_wbs_task_schema(self.config.repo_path)
        schema_errors: list[str] = []
        if schema:
            for t_dict in result.tasks:
                errs = _validate_task_against_schema(t_dict, schema)
                if errs:
                    schema_errors.append(f"{t_dict.get('name', '?')}: {'; '.join(errs)}")
        quality_gates["schema"] = {
            "passed": len(schema_errors) == 0,
            "errors": schema_errors,
        }

        # Check for upstream issues in LLD
        lld_data = json.loads(lld_path.read_text(encoding="utf-8"))
        upstream = self._detect_upstream_issues(lld_data, module)

        if upstream:
            from cogniforge.wbs.tl_turn_result import build_tl_result
            tl = build_tl_result(
                status="blocked",
                wbs_id="",
                task_ids=[],
                upstream_issues=upstream,
                message=f"LLD 存在不完整契约，WBS 暂不生成。{len(upstream)} 个问题。",
            )
            return {
                "status": "blocked",
                "message": tl.message,
                "data": {
                    "upstream_issues": upstream,
                    "task_count": 0,
                },
                "agent": self.role.value,
                "reasoning": "",
                "decisions": [],
                "artifacts": [],
            }

        # Register tasks
        count = self._register_wbs_tasks(result.tasks, module)

        # Build and write wbs index + tl result
        output = self._build_and_write_wbs_output(
            module, lld_docs[-1], result, quality_gates,
        )

        report = result.coverage
        coverage_msg = f", coverage={report.coverage_pct:.0f}%" if report else ""

        return self.format_result(
            status="success",
            message=f"WBS created: {count} tasks for {module}{coverage_msg}",
            data={
                "task_count": count,
                "coverage": report.coverage_pct if report else 0,
                "wbs_id": output.get("wbs_id", ""),
                "quality_gates": quality_gates,
            },
            artifacts=output.get("artifacts", []),
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

        # Validate generated JSON against schema
        json_abs = Path(self.config.repo_path) / json_path
        if json_abs.exists():
            try:
                data = json.loads(json_abs.read_text(encoding="utf-8"))
                schema_path = self.config.repo_path / "schemas" / "quality-report-schema.json"
                errors = self._validate_with_schema(data, schema_path)
                if errors:
                    return self.format_result(
                        status="failed",
                        message=f"Schema validation failed: {'; '.join(errors[:3])}",
                        reasoning=response.content,
                    )
            except json.JSONDecodeError as e:
                return self.format_result(
                    status="failed",
                    message=f"LLM 输出的 JSON 无法解析: {e}",
                    reasoning=response.content,
                )

        return self._commit_result(json_path, f"质量评估 - {module}", "techlead_agent",
                                   f"docs: quality evaluation for {module}", response.content)

    @staticmethod
    def _validate_with_schema(data: dict, schema_path: Path) -> list[str]:
        """Validate dict against JSON schema. Returns list of error messages."""
        if not schema_path.exists():
            return []
        try:
            import jsonschema
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            validator = jsonschema.Draft7Validator(schema)
            errors = list(validator.iter_errors(data))
            return [e.message for e in errors]
        except ImportError:
            return []
        except Exception as e:
            return [f"Schema validation error: {e}"]

    def _build_and_write_wbs_output(
        self, module: str, lld_doc, result,
        quality_gates: dict,
    ) -> dict:
        """Write wbs.json index and tl-turn-result, return output metadata."""
        from datetime import datetime
        from cogniforge.wbs.wbs_index import (
            WBSIndex, WBSMeta, WBSSource, TaskGraphNode, TaskGraphEdge,
            compute_execution_batches, write_wbs_index,
        )
        from cogniforge.wbs.tl_turn_result import build_tl_result

        repo_path = self.config.repo_path
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+09:00")
        wbs_id = f"wbs-{module}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Build WBS index
        nodes = []
        edges = []
        task_ids = []
        for i, t_dict in enumerate(result.tasks):
            tid = f"{module}-{i + 1:03d}"
            task_ids.append(tid)
            nodes.append(TaskGraphNode(
                task_id=tid,
                name=t_dict.get("name", ""),
                module=module,
                category=t_dict.get("category", ""),
                layer=t_dict.get("layer", 0),
                path=f".cogniforge/wiki/tasks/{tid}.json",
            ))
            for dep_name in t_dict.get("deps", []):
                edges.append(TaskGraphEdge(
                    from_task=dep_name,
                    to_task=tid,
                    reason=f"{t_dict.get('category', '')} depends on upstream",
                ))

        # Compute execution batches from assembled tasks (with task_ids)
        enriched_for_batch = []
        for i, t_dict in enumerate(result.tasks):
            bc = dict(t_dict)
            bc["task_id"] = f"{module}-{i + 1:03d}"
            enriched_for_batch.append(bc)
        batches = compute_execution_batches(enriched_for_batch)

        coverage_report = result.coverage
        cov_dict = {
            "total_artifacts": coverage_report.total_artifacts if coverage_report else 0,
            "covered": coverage_report.covered_artifacts if coverage_report else 0,
            "uncovered": len(coverage_report.uncovered) if coverage_report else 0,
            "coverage_pct": coverage_report.coverage_pct if coverage_report else 0.0,
            "passed": coverage_report.passed if coverage_report else False,
        }

        index = WBSIndex(
            meta=WBSMeta(
                wbs_id=wbs_id,
                created=now,
                project_id="",
                iteration_id="",
            ),
            source=WBSSource(
                llds=[{
                    "module": module,
                    "doc_id": lld_doc.doc_id,
                    "path": lld_doc.path,
                }],
            ),
            nodes=nodes,
            edges=edges,
            execution_batches=batches,
            coverage=cov_dict,
            quality_gates=quality_gates,
        )

        wbs_rel = write_wbs_index(repo_path, index)

        # Build tl-turn-result
        tl = build_tl_result(
            status="success",
            wbs_id=wbs_id,
            task_ids=task_ids,
            coverage=cov_dict,
            message=f"基于 {module} LLD 生成 {len(task_ids)} 个任务，{len(batches)} 个执行批次。",
        )
        tl_path = repo_path / ".cogniforge" / "turns" / "tl" / f"{wbs_id}.json"
        tl_path.parent.mkdir(parents=True, exist_ok=True)
        tl_path.write_text(
            json.dumps(tl.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "wbs_id": wbs_id,
            "artifacts": [str(wbs_rel), str(tl_path.relative_to(repo_path))],
        }

    def _detect_upstream_issues(self, lld_data: dict, module: str) -> list[dict]:
        """Detect incomplete LLD contracts that would block task generation."""
        issues: list[dict] = []

        # Check service_contracts for missing output schemas
        contracts = lld_data.get("service_contracts", [])
        if isinstance(contracts, list):
            for svc in contracts:
                if not isinstance(svc, dict):
                    continue
                methods = svc.get("methods", [])
                for m in methods:
                    if not isinstance(m, dict):
                        continue
                    if not m.get("output") or not m.get("signature"):
                        issues.append({
                            "target": "lld",
                            "issue_type": "incomplete_contract",
                            "artifact_id": f"{svc.get('name', '?')}.{m.get('name', '?')}",
                            "description": (
                                f"{svc.get('name', '?')}.{m.get('name', '?')} "
                                "缺少 output schema 或 signature，无法生成验收条件"
                            ),
                            "suggested_action": "回到 MDE 补齐 service_contract.methods[].output",
                        })

        # Check interfaces for missing response definitions
        interfaces = lld_data.get("interfaces", [])
        if isinstance(interfaces, list):
            for iface in interfaces:
                if not isinstance(iface, dict):
                    continue
                if not iface.get("response"):
                    issues.append({
                        "target": "lld",
                        "issue_type": "missing_response",
                        "artifact_id": iface.get("name", "?"),
                        "description": (
                            f"接口 {iface.get('name', '?')} 缺少 response 定义"
                        ),
                        "suggested_action": "回到 MDE 补齐 interfaces[].response",
                    })

        return issues

    def _retro(self, input_data: dict) -> dict:
        """RETRO: collect results from all phases and produce a retrospective report."""
        module = input_data.get("module", "unknown")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Collect task statistics
        all_tasks = self.task_engine.list_tasks()
        module_tasks = [t for t in all_tasks if t.module == module]

        done = sum(1 for t in module_tasks if t.status == TaskStatus.DONE)
        failed = sum(1 for t in module_tasks if t.status == TaskStatus.FAILED)
        blocked = sum(1 for t in module_tasks if t.status == TaskStatus.BLOCKED)
        total = len(module_tasks)

        estimated = sum(t.estimated_hours or 0 for t in module_tasks)
        actual = sum(t.actual_hours or 0 for t in module_tasks)

        # Build retro report
        retro_data = {
            "meta": {
                "doc_id": f"retro-{module}-001",
                "type": "report",
                "title": f"复盘总结 - {module}",
                "author": "techlead_agent",
                "created": now,
            },
            "content": {
                "module": module,
                "metrics": {
                    "tasks_total": total,
                    "tasks_done": done,
                    "tasks_failed": failed,
                    "tasks_blocked": blocked,
                    "completion_rate": f"{done / total * 100:.0f}%" if total > 0 else "N/A",
                    "estimated_total_hours": estimated,
                    "actual_total_hours": actual,
                    "estimation_accuracy": f"{actual / estimated * 100:.0f}%" if estimated > 0 else "N/A",
                },
                "process_improvements": [],
                "upstream_feedback": {
                    "pm": [],
                    "se": [],
                    "mde": [],
                    "wbs_rules": [],
                },
            },
        }

        # Write retro report
        retro_path = self.config.repo_path / ".cogniforge" / "wiki" / "reports" / f"retro-{module}-001.json"
        retro_path.parent.mkdir(parents=True, exist_ok=True)
        retro_path.write_text(
            json.dumps(retro_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return self.format_result(
            status="success",
            message=f"RETRO complete for {module}: {done}/{total} tasks done ({failed} failed, {blocked} blocked)",
            data=retro_data["content"]["metrics"],
            artifacts=[str(retro_path.relative_to(self.config.repo_path))],
        )

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
