"""Architect Agent — dual-JSON SAD creation and incremental architecture governance.

Long-term state: ``.cogniforge/wiki/sad/sad-{id}.json``
Per-turn output: ``schemas/se-turn-result-schema.json``
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole, DocumentType
from cogniforge.core.exceptions import AgentError
from cogniforge.wiki.wiki_renderer import repair_truncated_json


class ArchitectAgent(BaseAgent):
    """Architect Agent — initial SAD generation + patch-based incremental updates."""

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, input_data: dict) -> dict:
        try:
            if self.agent is None:
                raise AgentError("ArchitectAgent requires an LLM agent")

            cb = input_data.pop("_progress_callback", None)

            # ── Interactive modification mode ──
            pm_turn_result = input_data.get("pm_turn_result")
            if pm_turn_result:
                if cb:
                    cb("Architect 正在分析 PM 变更...")
                return self.modify_interactive(
                    pm_turn_result=pm_turn_result,
                    progress_callback=cb,
                )

            # ── Initial creation mode ──
            title = input_data.get("title", "System Architecture")
            system_overview = input_data.get("system_overview", "")
            architecture = input_data.get("architecture", "")
            components = input_data.get("components", [])
            data_flow = input_data.get("data_flow", "")

            return self._generate_initial(
                title, system_overview, architecture, components, data_flow,
                progress_callback=cb,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    # ------------------------------------------------------------------
    # Initial SAD generation
    # ------------------------------------------------------------------

    def _generate_initial(
        self, title: str, system_overview: str, architecture: str,
        components: list, data_flow: str,
        progress_callback: callable = None,
    ) -> dict:
        cb = progress_callback
        t0 = time.time()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        prd_context = self._load_latest_prd()
        prd_data = self._load_latest_prd_dict()

        # Determine doc_id and version
        existing_sad = self._load_current_sad()
        if existing_sad:
            doc_id = existing_sad.get("meta", {}).get("doc_id", "sad-001")
            version = existing_sad.get("meta", {}).get("version", 1) + 1
        else:
            existing = self.wiki_system.list_documents(DocumentType.SAD)
            seq = len(existing) + 1
            doc_id = f"sad-{seq:03d}"
            version = 1

        sad_path = self.wiki_system.agent_path(DocumentType.SAD, doc_id=doc_id)

        # Build source_prd from current PRD
        source_prd = {}
        if prd_data:
            source_prd = {
                "doc_id": prd_data.get("meta", {}).get("doc_id", "prd-current"),
                "version": prd_data.get("meta", {}).get("version", 1),
            }

        prompt = (
            f"根据以下数据创建一份系统架构文档 (SAD)，返回合法 JSON 对象:\n\n"
            f"JSON 结构如下:\n\n"
            f"{{\n"
            f"  \"meta\": {{\"doc_id\": \"{doc_id}\", \"type\": \"sad\",\n"
            f"    \"title\": \"{title}\", \"author\": \"architect_agent\",\n"
            f"    \"created\": \"{now}\", \"version\": {version}}},\n"
            f"  \"title\": \"{title}\",\n"
            f"  \"source_prd\": {json.dumps(source_prd, ensure_ascii=False)},\n"
            f"  \"system_overview\": {{\n"
            f"    \"description\": \"系统整体描述（string）\",\n"
            f"    \"roles\": [\n"
            f"      {{\"name\": \"角色名\",\n"
            f"        \"permissions\": [\"权限1\", \"权限2\", ...]}}\n"
            f"    ]\n"
            f"  }},\n"
            f"  \"architecture\": {{\n"
            f"    \"style\": \"架构风格（如 微服务架构）\",\n"
            f"    \"description\": \"架构设计描述（string）\",\n"
            f"    \"layers\": [\n"
            f"      {{\"name\": \"层名（如 接入层/网关层/服务层/数据层）\",\n"
            f"        \"components\": [\"该层包含的组件名称\", ...]}}\n"
            f"    ],\n"
            f"    \"connections\": [\n"
            f"      {{\"protocol\": \"层间通信协议（如 HTTPS / REST / SQL / AMQP）\",\n"
            f"        \"description\": \"通信说明\"}}\n"
            f"    ],\n"
            f"    \"features\": [\"架构特征1\", \"架构特征2\", ...]\n"
            f"  }},\n"
            f"  \"tech_stack\": {{\n"
            f"    \"backend\": {{\"language\": \"编程语言\", \"framework\": \"框架\"}},\n"
            f"    \"frontend\": {{\"framework\": \"前端框架\", \"ui_library\": \"UI组件库\"}},\n"
            f"    \"database\": \"数据库\",\n"
            f"    \"...\": \"按需增删字段\"\n"
            f"  }},\n"
            f"  \"components\": [\n"
            f"    {{\"id\": \"CMP-001\", \"name\": \"组件名\",\n"
            f"      \"type\": \"frontend|backend|gateway|service|database|infrastructure\",\n"
            f"      \"status\": \"active\", \"version\": 1,\n"
            f"      \"description\": \"组件描述\",\n"
            f"      \"responsibilities\": [\"职责1\", ...],\n"
            f"      \"source_requirements\": [\"REQ-001\"],\n"
            f"      \"contracts\": [\"CTR-001\"],\n"
            f"      \"depends_on_components\": [],\n"
            f"      \"change_history\": [{{\"version\": 1, \"change_type\": \"created\",\n"
            f"        \"summary\": \"初始创建\", \"reason\": \"首次生成 SAD\"}}]}}\n"
            f"  ],\n"
            f"  \"contracts\": [\n"
            f"    {{\"id\": \"CTR-001\", \"interface\": \"接口名称\",\n"
            f"      \"provider_component_id\": \"CMP-001\",\n"
            f"      \"provider\": \"提供者组件名\",\n"
            f"      \"consumers\": [\"消费者组件名\", ...],\n"
            f"      \"type\": \"REST|WebSocket|SSE|Event\",\n"
            f"      \"status\": \"active\", \"version\": 1,\n"
            f"      \"endpoint\": \"GET /api/...\",\n"
            f"      \"request\": {{\"path_params\": [], \"query_params\": [], \"body\": {{}}}},\n"
            f"      \"response\": {{\"status\": 200, \"body\": {{}}}},\n"
            f"      \"errors\": [{{\"status\": 404, \"code\": \"NOT_FOUND\",\n"
            f"        \"message\": \"资源不存在\"}}],\n"
            f"      \"description\": \"接口说明\",\n"
            f"      \"source_requirements\": [\"REQ-001\"],\n"
            f"      \"change_history\": [{{\"version\": 1, \"change_type\": \"created\",\n"
            f"        \"summary\": \"初始创建\", \"reason\": \"首次生成 SAD\"}}]}}\n"
            f"  ],\n"
            f"  \"data_flow\": [\n"
            f"    {{\"name\": \"数据流名称\",\n"
            f"      \"steps\": [\"步骤1\", \"步骤2\", ...]}},\n"
            f"    ...\n"
            f"  ],\n"
            f"  \"data_models\": [\n"
          f"    {{\"id\": \"DM-001\", \"name\": \"模型名\",\n"
          f"      \"description\": \"数据模型描述\",\n"
          f"      \"source_requirements\": [\"REQ-001\"],\n"
          f"      \"fields\": [\n"
          f"        {{\"name\": \"字段名\", \"type\": \"字段类型\",\n"
          f"          \"required\": false, \"description\": \"字段说明\"}}\n"
          f"      ]}}\n"
          f"  ],\n"
            f"  \"requirement_traceability\": [\n"
            f"    {{\"requirement_id\": \"REQ-001\", \"coverage\": \"full\",\n"
            f"      \"components\": [\"CMP-001\"], \"contracts\": [\"CTR-001\"],\n"
            f"      \"data_models\": [], \"notes\": \"\"}}\n"
            f"  ],\n"
            f"  \"architecture_decisions\": [],\n"
            f"  \"risks\": [],\n"
            f"  \"open_questions\": []\n"
            f"}}\n\n"
            f"重要说明:\n"
            f"- 每个 component 必须分配唯一 id（CMP-001, CMP-002...）\n"
            f"- 每个 contract 必须分配唯一 id（CTR-001, CTR-002...）\n"
            f"- system_overview.roles: 从 PRD 中提取用户角色及其权限\n"
            f"- architecture.layers: 按系统分层列出每层包含的组件\n"
            f"- architecture.connections: 相邻层之间的通信协议\n"
            f"- architecture.features: 列出架构的关键技术特征\n"
            f"- tech_stack: 根据架构设计明确定义技术选型\n"
            f"- components: 每个组件需要 status/version/source_requirements/change_history\n"
            f"- contracts: 每个契约需要 status/version/source_requirements/provider_component_id/errors/change_history\n"
          f"- data_models: 每个模型的 fields 必须是对象数组，每个 field 有 name/type/required/description\n"
            f"- requirement_traceability: 每个 PRD 需求必须有一条覆盖记录\n"
            f"- 所有文字使用中文\n\n"
            f"参考输入数据:\n"
            f"system_overview: {system_overview}\n"
            f"architecture: {architecture}\n"
            f"components: {json.dumps(components, ensure_ascii=False)}\n"
            f"data_flow: {data_flow}\n"
            f"已批准的 PRD 文档:\n{prd_context}\n"
        )

        max_retries = 2
        last_error = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                if cb:
                    cb(f"JSON 解析失败，正在重试 ({attempt}/{max_retries})...")
                prompt = (
                    f"你上一次输出的 JSON 有语法错误，无法解析：\n"
                    f"错误: {last_error}\n\n"
                    f"请重新生成。确保 JSON 格式正确，所有字符串内的双引号已转义，\n"
                    f"所有括号匹配，逗号位置正确。输出纯 JSON，不要包含 markdown 代码块。\n\n"
                    f"原始任务:\n{prompt}"
                )
            response = self.agent.generate_think_then_json(
                prompt, role="architect",
            )
            json_text = _extract_json(response.content)
            try:
                data, incomplete = repair_truncated_json(json_text)
                break
            except ValueError as e:
                last_error = str(e)
                if attempt == max_retries:
                    return self.format_result(
                        status="failed",
                        message=f"JSON 解析失败（已重试 {max_retries} 次）: {last_error}",
                        reasoning=response.content,
                    )
        if incomplete and cb:
            cb("警告: LLM 输出被截断，已自动修复 JSON 结构")

        data["components"] = self._assign_ids(data.get("components", []), "CMP")
        data["contracts"] = self._assign_ids(data.get("contracts", []), "CTR")
        data["data_models"] = self._assign_ids(data.get("data_models", []), "DM")
        json_text = json.dumps(data, ensure_ascii=False, indent=2)

        # Write JSON file
        sad_path.parent.mkdir(parents=True, exist_ok=True)
        sad_path.write_text(json_text, encoding="utf-8")

        # Validate written JSON
        json.loads(sad_path.read_text(encoding="utf-8"))

        return self._commit_and_result(
            sad_path, title, response.content,
            llm_timings=response.timings, t_total=time.time() - t0,
        )

    # ------------------------------------------------------------------
    # Interactive modification — patch-based iteration
    # ------------------------------------------------------------------

    def modify_interactive(
        self,
        pm_turn_result: dict,
        progress_callback: callable = None,
    ) -> dict:
        """Execute a single SE architecture modification turn.

        1. Read current PRD (full state)
        2. Read pm_turn_result (this round's PM delta)
        3. Read current SAD (current architecture state)
        4. Build SE input package, call LLM to get se-turn-result
        5. Validate se-turn-result against schema
        6. Apply patches to SAD
        7. Validate sad-schema + consistency checks
        8. Save, re-render, commit
        """
        try:
            t0 = time.time()
            current_sad = self._load_current_sad()
            if current_sad is None:
                return self.format_result(
                    status="failed",
                    message="SAD 不存在。请先生成 SAD。",
                )
            sad_doc_id = current_sad.get("meta", {}).get("doc_id", "sad-001")
            sad_path = self.wiki_system.agent_path(DocumentType.SAD, doc_id=sad_doc_id)

            sad_before_version = current_sad.get("meta", {}).get("version", 1)
            current_sad_json = json.dumps(current_sad, ensure_ascii=False, indent=2)

            # Load PRD
            prd_data = self._load_latest_prd_dict()
            if prd_data is None:
                return self.format_result(
                    status="failed",
                    message="PRD 不存在。请先创建 PRD。",
                )
            prd_json = json.dumps(prd_data, ensure_ascii=False, indent=2)

            # Load turn schema
            turn_schema_path = self.config.repo_path / "schemas" / "se-turn-result-schema.json"
            turn_schema = None
            if turn_schema_path.exists():
                turn_schema = json.loads(turn_schema_path.read_text(encoding="utf-8"))

            # System prompt for SE modification
            system_prompt = (
                "你是 CogniForge 系统的 SE (Architect) Agent。\n"
                "职责: 根据 PRD 变更维护系统架构文档 (SAD)。\n"
                "规则:\n"
                "1. 不要直接输出完整 SAD 文档，只输出包含 patches 数组的变更结果 JSON。\n"
                "2. 保留所有已有的 CMP-ID、CTR-ID、DM-ID 不变。\n"
                "3. 新增组件/契约/数据模型时分配新的 ID（下一个可用的编号）。\n"
                "4. 修改已有 component/contract 时，version +1 并追加 change_history。\n"
                "5. 优先判断现有组件是否能承载新需求，不要默认新增组件。\n"
                "6. 每个 active requirement 必须在 requirement_traceability 中有覆盖状态。\n"
                "7. SAD 有变化时 meta.version +1。\n"
                "8. 如果 PRD 需求无法被当前架构覆盖，返回 coverage=partial/blocked。\n"
                "9. 如果接口契约缺少 request/response/provider_component_id，必须补齐。\n"
                "10. 默认不删除，用 status=deprecated/removed 标记。\n"
                "11. patches 使用 RFC 6902 JSON Pointer 格式路径。\n"
                "12. 在 downstream_handoff 中给出 BE/FE/QA/DevOps agent 的任务提示。\n"
                "所有文字使用中文。"
            )

            # Build SE agent input
            pm_turn_json = json.dumps(pm_turn_result, ensure_ascii=False, indent=2)

            user_prompt = (
                f"## 当前 PRD 状态\n```json\n{prd_json}\n```\n\n"
                f"## PM 本轮变更 (pm-turn-result)\n```json\n{pm_turn_json}\n```\n\n"
                f"## 当前 SAD 状态\n```json\n{current_sad_json}\n```\n\n"
                f"请根据 PM 本轮变更，生成 se-turn-result JSON。\n"
                f"分析 PM 变更对架构的影响，判断已有组件是否能承载，\n"
                f"给出 patches 和 downstream_handoff。"
            )

            # Call LLM
            if progress_callback:
                progress_callback("Architect 正在分析架构影响...")

            if hasattr(self.agent, "generate_interactive_patch"):
                response = self.agent.generate_interactive_patch(
                    current_document=current_sad_json,
                    user_request=user_prompt,
                    system_prompt=system_prompt,
                    turn_schema=turn_schema,
                )
            else:
                response = self.agent.generate_interactive(
                    current_document=current_sad_json,
                    user_request=user_prompt,
                    system_prompt=system_prompt,
                )
            llm_timings = response.timings

            raw_content = response.content if hasattr(response, "content") else str(response)
            json_text = _extract_json(raw_content)

            try:
                turn_data = json.loads(json_text)
            except json.JSONDecodeError as e:
                return self.format_result(
                    status="failed",
                    message=f"LLM 输出的 JSON 无法解析: {e}",
                    reasoning=raw_content,
                )

            # Validate turn result against schema
            if turn_schema:
                turn_errors = self._validate_with_schema(turn_data, turn_schema_path)
                if turn_errors:
                    return self.format_result(
                        status="failed",
                        message=f"SE turn result schema error: {'; '.join(turn_errors[:3])}",
                        reasoning=raw_content,
                    )

            # Handle non-update statuses
            status = turn_data.get("status", "updated")
            if status == "no_change":
                return self.format_result(
                    status="success",
                    message=turn_data.get("message", "无需修改架构。"),
                    reasoning=raw_content,
                )
            if status == "need_clarification":
                return self.format_result(
                    status="success",
                    message=turn_data.get("message", "需要更多信息。"),
                    data={
                        "open_questions": turn_data.get("open_questions", []),
                    },
                    reasoning=raw_content,
                )
            if status == "rejected":
                return self.format_result(
                    status="failed",
                    message=turn_data.get("message", "架构变更请求被拒绝。"),
                    reasoning=raw_content,
                )

            # Apply patches
            t_apply_start = time.time()
            patches = turn_data.get("patches", [])
            if not patches:
                return self.format_result(
                    status="failed",
                    message="Turn returned 'updated' status but no patches.",
                    reasoning=raw_content,
                )

            updated_sad = self._apply_patches(current_sad, patches)

            # Validate updated SAD against sad-schema
            sad_schema_path = self.config.repo_path / "schemas" / "sad-schema.json"
            schema_errors = self._validate_with_schema(updated_sad, sad_schema_path)
            if schema_errors:
                return self.format_result(
                    status="failed",
                    message=f"Updated SAD schema error: {'; '.join(schema_errors[:3])}",
                    reasoning=raw_content,
                )

            # Consistency checks
            from cogniforge.consistency_checks import run_all
            cc_errors = run_all(prd_data, updated_sad, sad_before=current_sad)
            if cc_errors:
                return self.format_result(
                    status="failed",
                    message=f"Consistency check failed: {'; '.join(cc_errors[:3])}",
                    reasoning=raw_content,
                )

            # Write updated SAD
            sad_path.write_text(
                json.dumps(updated_sad, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # Validate written JSON
            json.loads(sad_path.read_text(encoding="utf-8"))

            rel_sad = sad_path.relative_to(self.config.repo_path).as_posix()

            # Render HTML
            from cogniforge.wiki.wiki_renderer import render_file
            html_path = render_file(sad_path)
            if not html_path:
                return self.format_result(
                    status="failed",
                    message="SAD HTML 渲染失败",
                )
            rel_html = html_path.relative_to(self.config.repo_path).as_posix()

            operation = turn_data.get("operation", "modify")
            with self.wiki_system.git_storage.atomic_write():
                self.wiki_system.git_storage.repo.index.add([rel_sad])
                self.wiki_system.git_storage.repo.index.add([rel_html])
                self.wiki_system.git_storage.commit(
                    f"docs: update SAD - {operation}",
                    "architect_agent",
                )

            artifacts = [rel_sad]
            if html_path:
                artifacts.append(
                    html_path.relative_to(self.config.repo_path).as_posix())

            t_apply = time.time() - t_apply_start
            t_total = time.time() - t0
            timings = []
            if llm_timings:
                timings.extend(llm_timings)
            timings.append({"phase": "应用变更", "duration_s": round(t_apply, 1)})
            timings.append({"phase": "总计", "duration_s": round(t_total, 1)})

            return self.format_result(
                status="success",
                message=turn_data.get("message", "SAD updated."),
                artifacts=artifacts,
                data={
                    "open_questions": turn_data.get("open_questions", []),
                    "affected_components": turn_data.get("affected_components", []),
                    "affected_contracts": turn_data.get("affected_contracts", []),
                    "downstream_handoff": turn_data.get("downstream_handoff", {}),
                    "new_version": updated_sad["meta"]["version"],
                    "timings": timings,
                },
                reasoning=raw_content,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    # ------------------------------------------------------------------
    # Canonical component type values
    # ------------------------------------------------------------------

    _COMPONENT_TYPE_CANONICAL: dict[str, str] = {
        "frontend": "frontend", "backend": "backend",
        "gateway": "gateway", "service": "service",
        "database": "database", "infrastructure": "infrastructure",
        "integration": "integration", "security": "security",
        # LLM common variants → canonical
        "db": "database", "DB": "database", "Database": "database",
        "cache": "infrastructure", "redis": "infrastructure",
        "mq": "infrastructure", "message_queue": "infrastructure",
        "file_storage": "infrastructure", "storage": "infrastructure",
        "api_gateway": "gateway", "web": "frontend", "ui": "frontend",
    }

    @classmethod
    def _normalize_component_type(cls, raw: str) -> str:
        return cls._COMPONENT_TYPE_CANONICAL.get(raw, "service")

    # ------------------------------------------------------------------
    # ID assignment
    # ------------------------------------------------------------------

    @staticmethod
    def _assign_ids(items: list[dict], prefix: str) -> list[dict]:
        """Assign stable serial IDs (CMP-001, CTR-001, DM-001) to items lacking them."""
        max_num = 0
        for item in items:
            item_id = item.get("id", "")
            if item_id.startswith(f"{prefix}-"):
                try:
                    num = int(item_id.split("-", 1)[1])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
        next_num = max_num + 1
        assigned = []
        for item in items:
            item_id = item.get("id", "")
            if not item_id or not item_id.startswith(f"{prefix}-"):
                item["id"] = f"{prefix}-{next_num:03d}"
                next_num += 1
            assigned.append(item)
        return assigned

    # ------------------------------------------------------------------
    # Document I/O
    # ------------------------------------------------------------------

    def _load_latest_prd(self) -> str:
        """Read the latest PRD JSON from the wiki path as string."""
        data = self._load_latest_prd_dict()
        if data:
            return json.dumps(data, ensure_ascii=False, indent=2)
        return "(无 PRD 文档)"

    def _load_latest_prd_dict(self) -> dict | None:
        """Read the latest PRD JSON as dict from the wiki path."""
        docs = self.wiki_system.list_documents(DocumentType.PRD)
        if not docs:
            return None
        latest = docs[-1]
        try:
            return json.loads((self.config.repo_path / latest.path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return None

    def _load_current_sad(self) -> dict | None:
        """Load the latest SAD JSON from the wiki path."""
        docs = self.wiki_system.list_documents(DocumentType.SAD)
        if not docs:
            return None
        latest = docs[-1]
        try:
            return json.loads((self.config.repo_path / latest.path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Patches & validation
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_patches(doc: dict, patches: list[dict]) -> dict:
        """Apply RFC 6902 JSON Patch operations to doc dict."""
        from jsonpatch import JsonPatch
        patch = JsonPatch(patches)
        return patch.apply(doc)

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

    # ------------------------------------------------------------------
    # Commit & result formatting
    # ------------------------------------------------------------------

    def _commit_and_result(self, sad_path: Path, title: str, reasoning: str = "",
                           llm_timings: list = None, t_total: float = 0) -> dict:
        t_write_start = time.time()

        if not sad_path.exists():
            return self.format_result(status="failed",
                                       message=f"LLM did not produce {sad_path}")

        # Normalize component types
        try:
            data = json.loads(sad_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return self.format_result(status="failed",
                                       message=f"SAD JSON 写入验证失败: {e}")

        components = data.get("components", [])
        fixed = 0
        for c in components:
            raw = c.get("type", "service")
            canonical = self._normalize_component_type(raw)
            if canonical != raw:
                c["type"] = canonical
                fixed += 1
        if fixed:
            sad_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")

        rel_sad = sad_path.relative_to(self.config.repo_path).as_posix()

        from cogniforge.wiki.wiki_renderer import render_file
        html_path = render_file(sad_path)
        if not html_path:
            return self.format_result(status="failed",
                                       message="SAD HTML 渲染失败，JSON 可能损坏")
        rel_html = html_path.relative_to(self.config.repo_path).as_posix()

        with self.wiki_system.git_storage.atomic_write():
            self.wiki_system.git_storage.repo.index.add([rel_sad])
            self.wiki_system.git_storage.repo.index.add([rel_html])
            self.wiki_system.git_storage.commit(f"feat: add SAD - {title}", "architect_agent")

        artifacts = [rel_sad]
        if rel_html:
            artifacts.append(rel_html)

        t_write = time.time() - t_write_start
        timings = []
        if llm_timings:
            timings.extend(llm_timings)
        timings.append({"phase": "创建文档", "duration_s": round(t_write, 1)})
        if t_total > 0:
            timings.append({"phase": "总计", "duration_s": round(t_total, 1)})

        return self.format_result(
            status="success",
            message=f"SAD created: {sad_path.stem}",
            artifacts=artifacts,
            reasoning=reasoning,
            data={"timings": timings},
        )


# ------------------------------------------------------------------
# JSON extraction
# ------------------------------------------------------------------

def _extract_json(text: str) -> str:
    """Strip markdown code fences, return bare JSON."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text
