"""PM Agent - Product Manager Agent for PRD creation and iterative management

Dual-JSON architecture:
- ``.cogniforge/wiki/prd/prd-current.json`` — long-term PRD state (stable IDs, versioning, change history)
- ``pm-turn-result.schema.json`` — per-turn structured change output (JSON Patch)
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


class PMAgent(BaseAgent):
    """PM Agent — two-step thinking→JSON for PRD creation, patch-based iteration."""

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, input_data: dict) -> dict:
        try:
            if self.agent is None:
                raise AgentError("PMAgent requires an LLM agent")

            cb = input_data.pop("_progress_callback", None)

            # ── Interactive modification mode ──
            modify_request = input_data.get("modify_request")
            if modify_request:
                if cb:
                    cb("PM 正在分析修改请求...")
                return self.modify_interactive(
                    user_request=modify_request,
                    progress_callback=cb,
                )

            # ── Initial creation mode ──
            raw_text = input_data.get("raw_text", "")
            if raw_text:
                if cb:
                    cb("PM 正在分析需求，提取项目信息...")
                return self._run_raw(raw_text)

            title = input_data.get("title", "未命名PRD")
            overview = input_data.get("overview", "")
            requirements = input_data.get("requirements", [])
            user_stories = input_data.get("user_stories", [])
            priorities = input_data.get("priorities", {})

            return self._run_structured(
                title, overview, requirements, user_stories, priorities,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    # ------------------------------------------------------------------
    # Initial creation — raw text
    # ------------------------------------------------------------------

    def _run_raw(self, raw_text: str) -> dict:
        t0 = time.time()
        prd_path = self.wiki_system.agent_path(DocumentType.PRD, doc_id="prd-current")

        prompt = (
            f"根据以下用户描述，创建一份完整的产品需求文档 (PRD)。\n"
            f"充分理解用户意图，提取项目名称、撰写详细概述、"
            f"梳理功能需求（含验收条件）、推导用户故事、标注优先级。\n\n"
            f"用户描述:\n{raw_text}\n\n"
            f"参考系统提示中的 EXAMPLE JSON OUTPUT 结构输出。"
        )

        response = self.agent.generate_think_then_json(
            prompt, role="pm",
        )

        result = self._write_prd(prd_path, response.content,
                                 llm_timings=response.timings, t_total=time.time() - t0)
        return result

    # ------------------------------------------------------------------
    # Initial creation — structured fields
    # ------------------------------------------------------------------

    def _run_structured(
        self, title, overview, requirements, user_stories, priorities,
    ) -> dict:
        t0 = time.time()
        prd_path = self.wiki_system.agent_path(DocumentType.PRD, doc_id="prd-current")

        prompt = (
            f"根据以下数据创建一份产品需求文档 (PRD)。\n\n"
            f"项目名称: {title}\n"
            f"项目概述: {overview}\n"
            f"功能需求: {json.dumps(requirements, ensure_ascii=False)}\n"
            f"用户故事: {json.dumps(user_stories, ensure_ascii=False)}\n"
            f"优先级: {json.dumps(priorities, ensure_ascii=False)}\n\n"
            f"参考系统提示中的 EXAMPLE JSON OUTPUT 结构输出。"
        )

        response = self.agent.generate_think_then_json(
            prompt, role="pm",
        )

        result = self._write_prd(prd_path, response.content,
                                 llm_timings=response.timings, t_total=time.time() - t0)
        return result

    # ------------------------------------------------------------------
    # Write PRD (creation)
    # ------------------------------------------------------------------

    def _write_prd(self, prd_path: Path, raw_content: str,
                   llm_timings: list = None, t_total: float = 0) -> dict:
        """Extract JSON, assign stable IDs, validate, write, render, commit."""
        t_write_start = time.time()
        json_text = _extract_json(raw_content)
        prd_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            return self.format_result(
                status="failed",
                message=f"LLM 输出的 JSON 无法解析: {e}",
                reasoning=raw_content,
            )

        # Replace <created_at> placeholder with actual timestamp
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        meta = data.get("meta", {})
        for field in ("created", "last_modified"):
            if meta.get(field) == "<created_at>":
                meta[field] = now
        data["meta"] = meta

        # Assign stable IDs if missing
        requirements = data.get("requirements", [])
        data["requirements"] = self._assign_ids(requirements, "REQ")
        user_stories = data.get("user_stories", [])
        data["user_stories"] = self._assign_ids(user_stories, "US")

        # Ensure change_history exists for each requirement
        for req in data["requirements"]:
            if not req.get("change_history"):
                req["change_history"] = [{
                    "version": req.get("version", 1),
                    "change_type": "created",
                    "summary": "初始创建",
                    "reason": "首次生成 PRD",
                }]

        # Link user_stories to requirements
        self._link_stories_to_reqs(data)

        # Validate against prd-schema
        schema_path = self.config.repo_path / "schemas" / "prd-schema.json"
        errors = self._validate_with_schema(data, schema_path)
        if errors:
            return self.format_result(
                status="failed",
                message=f"PRD schema validation failed: {'; '.join(errors[:3])}",
                reasoning=raw_content,
            )

        prd_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        rel_prd = prd_path.relative_to(self.config.repo_path).as_posix()
        self.wiki_system.git_storage.repo.index.add([rel_prd])

        # Render HTML
        from cogniforge.wiki.wiki_renderer import render_file
        html_path = render_file(prd_path)
        if html_path:
            rel_html = html_path.relative_to(self.config.repo_path).as_posix()
            self.wiki_system.git_storage.repo.index.add([rel_html])

        title = data.get("meta", {}).get("title", "未命名PRD")
        self.wiki_system.git_storage.commit(
            f"feat: add PRD - {title}", "pm_agent")

        artifacts = [rel_prd]
        if html_path:
            artifacts.append(
                html_path.relative_to(self.config.repo_path).as_posix())

        t_write = time.time() - t_write_start
        timings = []
        if llm_timings:
            timings.extend(llm_timings)
        timings.append({"phase": "创建文档", "duration_s": round(t_write, 1)})
        if t_total > 0:
            timings.append({"phase": "总计", "duration_s": round(t_total, 1)})

        return self.format_result(
            status="success",
            message=f"PRD created: {prd_path.stem}",
            artifacts=artifacts,
            reasoning=raw_content,
            data={"timings": timings},
        )

    # ------------------------------------------------------------------
    # Interactive modification — patch-based iteration
    # ------------------------------------------------------------------

    def modify_interactive(
        self,
        user_request: str,
        progress_callback: callable = None,
    ) -> dict:
        """Execute a single interactive modification turn using patch-based approach.

        1. Read current prd.json
        2. Call adapter to produce pm-turn-result with patches
        3. Validate turn result against pm-turn-result schema
        4. Apply patches to prd.json
        5. Validate updated prd.json against prd-schema
        6. Save, re-render, commit
        """
        try:
            t0 = time.time()
            current_prd = self._load_current_prd()
            if current_prd is None:
                return self.format_result(
                    status="failed",
                    message="PRD 不存在。请先创建 PRD。",
                )
            prd_doc_id = current_prd.get("meta", {}).get("doc_id", "prd-current")
            prd_path = self.wiki_system.agent_path(DocumentType.PRD, doc_id=prd_doc_id)

            current_json = json.dumps(current_prd, ensure_ascii=False, indent=2)

            # Load turn schema
            turn_schema_path = self.config.repo_path / "schemas" / "pm-turn-result-schema.json"
            turn_schema = None
            if turn_schema_path.exists():
                turn_schema = json.loads(turn_schema_path.read_text(encoding="utf-8"))

            # System prompt for PM modification
            system_prompt = (
                "你是 CogniForge 系统的 PM (Product Manager) Agent。\n"
                "职责: 根据用户要求修改产品需求文档 (PRD)。\n"
                "规则:\n"
                "1. 不要直接输出完整文档，只输出包含 patches 数组的变更结果 JSON。\n"
                "2. 保留所有已有的 REQ-ID 和 US-ID 不变。\n"
                "3. 新增需求时分配新的 ID（下一个可用的 REQ-NNN / US-NNN）。\n"
                "4. 直接修改需求内容（描述、验收条件、优先级等），不要更新 per-requirement 的 version 和 change_history。\n"
                "   change_history 只在需求首次创建时记录，修改轮次不追加变更历史。\n"
                "5. 在 priorities 中使用需求 ID（不是需求名称）。\n"
                "6. 如果检测到冲突，在 conflicts 数组中记录。\n"
                "7. patches 使用 RFC 6902 JSON Pointer 格式路径。\n"
                "所有文字使用中文。"
            )

            # Call LLM
            if progress_callback:
                progress_callback("PM 正在分析修改请求...")

            if hasattr(self.agent, "generate_interactive_patch"):
                response = self.agent.generate_interactive_patch(
                    current_document=current_json,
                    user_request=user_request,
                    system_prompt=system_prompt,
                    turn_schema=turn_schema,
                )
            else:
                response = self.agent.generate_interactive(
                    current_document=current_json,
                    user_request=user_request,
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
                        message=f"Turn result schema error: {'; '.join(turn_errors[:3])}",
                        reasoning=raw_content,
                    )

            # Handle non-update statuses
            status = turn_data.get("status", "updated")
            if status == "no_change":
                return self.format_result(
                    status="success",
                    message=turn_data.get("message", "无需修改。"),
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
                    message=turn_data.get("message", "修改请求被拒绝。"),
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

            updated_prd = self._apply_patches(current_prd, patches)

            # Update meta timestamp only — version stays put during editing rounds
            updated_prd.setdefault("meta", {})
            updated_prd["meta"]["last_modified"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            updated_prd["meta"]["last_author"] = "pm_agent"

            # Validate updated PRD against prd-schema
            prd_schema_path = self.config.repo_path / "schemas" / "prd-schema.json"
            schema_errors = self._validate_with_schema(updated_prd, prd_schema_path)
            if schema_errors:
                return self.format_result(
                    status="failed",
                    message=f"Updated PRD schema error: {'; '.join(schema_errors[:3])}",
                    reasoning=raw_content,
                )

            # Write updated PRD
            prd_path.write_text(
                json.dumps(updated_prd, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            rel_prd = prd_path.relative_to(self.config.repo_path).as_posix()
            self.wiki_system.git_storage.repo.index.add([rel_prd])

            # Render HTML
            from cogniforge.wiki.wiki_renderer import render_file
            html_path = render_file(prd_path)
            if html_path:
                rel_html = html_path.relative_to(self.config.repo_path).as_posix()
                self.wiki_system.git_storage.repo.index.add([rel_html])

            operation = turn_data.get("operation", "modify")
            self.wiki_system.git_storage.commit(
                f"docs: update PRD - {operation}",
                "pm_agent",
            )

            artifacts = [rel_prd]
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
                message=turn_data.get("message", "PRD updated."),
                artifacts=artifacts,
                data={
                    "open_questions": turn_data.get("open_questions", []),
                    "affected_requirements": turn_data.get("affected_requirements", []),
                    "new_version": updated_prd["meta"]["version"],
                    "timings": timings,
                },
                reasoning=raw_content,
            )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_current_prd(self) -> dict | None:
        """Load the latest PRD JSON from the wiki path."""
        docs = self.wiki_system.list_documents(DocumentType.PRD)
        if not docs:
            return None
        latest = docs[-1]
        try:
            return json.loads((self.config.repo_path / latest.path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _assign_ids(items: list[dict], prefix: str = "REQ") -> list[dict]:
        """Assign stable serial IDs (REQ-001, US-001, etc.) to items lacking them."""
        existing_nums: set[int] = set()
        max_num = 0
        for item in items:
            item_id = item.get("id", "")
            if item_id.startswith(f"{prefix}-"):
                try:
                    num = int(item_id.split("-", 1)[1])
                    existing_nums.add(num)
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
            else:
                try:
                    int(item_id.split("-", 1)[1])
                except ValueError:
                    item["id"] = f"{prefix}-{next_num:03d}"
                    next_num += 1
            assigned.append(item)
        return assigned

    @staticmethod
    def _apply_patches(prd: dict, patches: list[dict]) -> dict:
        """Apply RFC 6902 JSON Patch operations to prd dict."""
        from jsonpatch import JsonPatch
        patch = JsonPatch(patches)
        return patch.apply(prd)

    @staticmethod
    def _validate_with_schema(data: dict, schema_path: Path) -> list[str]:
        """Validate dict against JSON schema. Returns list of error messages (empty=valid)."""
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

    @staticmethod
    def _link_stories_to_reqs(data: dict) -> None:
        """Auto-link user stories to requirements when related_requirements is empty."""
        req_ids = [r.get("id") for r in data.get("requirements", []) if r.get("id")]
        for i, story in enumerate(data.get("user_stories", [])):
            if not story.get("related_requirements") and req_ids:
                # Link each story to the requirement at the same index, or the first
                idx = min(i, len(req_ids) - 1)
                story["related_requirements"] = [req_ids[idx]]


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
