"""Dev Agent - Developer Agent for code implementation"""

from __future__ import annotations

from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.exceptions import AgentError


class DevAgent(BaseAgent):
    """Dev Agent — delegates to Claude Code agent to read LLD + context,
    write code, and run tests end-to-end."""

    def run(self, input_data: dict) -> dict:
        try:
            if self.agent is None:
                raise AgentError("DevAgent requires a Claude Code agent")

            task = input_data.get("task")
            module = input_data.get("module", task.module if task else "unknown")
            code = input_data.get("code", "")

            # If code is already provided, write it directly (operational)
            if code:
                return self._write_direct(module, task, code)

            return self._run_agentic(task, module)

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _run_agentic(self, task, module: str) -> dict:
        task_name = task.name if task else module
        task_desc = getattr(task, "description", "") if task else ""

        task_context = getattr(task, "context", None)
        acceptance_criteria = getattr(task, "acceptance_criteria", []) or []
        upstream_artifacts = []
        if task_context and hasattr(task_context, "upstream_artifacts"):
            upstream_artifacts = task_context.upstream_artifacts or []

        prompt = self._build_structured_prompt(
            task_name, task_desc, task_context, acceptance_criteria, upstream_artifacts, module
        )

        response = self.agent.generate_agentic(prompt, role="dev")

        code_dir = Path(self.config.repo_path) / "src" / module
        artifacts = [
            str(p.relative_to(self.config.repo_path))
            for p in code_dir.rglob("*.py")
        ] if code_dir.exists() else []

        return self.format_result(
            status="success",
            message=f"Code generated for {module}",
            artifacts=artifacts,
            reasoning=response.content,
        )

    def _build_structured_prompt(self, task_name: str, task_desc: str, ctx,
                                  criteria: list, upstream: list[dict],
                                  module: str) -> str:
        """Build a structured DEV prompt from TaskContext + upstream artifacts."""
        import json as _json
        sections: list[str] = []

        sections.append(f"## 任务\n{task_name}\n{task_desc}")

        if not ctx:
            sections.append(f"\n## 完整 LLD 参考\n.cogniforge/wiki/lld/{module}/")
            return (
                "实现以下开发任务。接口签名、数据模型字段和业务规则来自详细设计文档(LLD)，必须严格遵守。\n\n"
                + "\n".join(sections)
                + "\n\n要求：\n1. 先阅读 LLD 了解详细设计\n2. 编写代码并编写单元测试\n"
                "3. 完成后运行测试验证\n4. 完成后用中文回复确认"
            )

        # 2. Upstream artifacts
        if upstream:
            sections.append("## 上游已完成产物（可直接 import/调用）")
            for up in upstream:
                name = up.get("name", up.get("task_id", "?"))
                files = up.get("files", [])
                cat = up.get("category", "")
                sections.append(f"\n### {name} ({cat})")
                for f in files:
                    sections.append(f"  → {f}")

        # 3. API interfaces
        if ctx.scope.interfaces:
            sections.append("## API 接口（必须严格实现）")
            for iface in ctx.scope.interfaces:
                method = iface.get("method", "")
                endpoint = iface.get("endpoint", "")
                sections.append(f"\n### {iface.get('name','')}: {method} {endpoint}")
                sections.append(f"  {iface.get('description','')}")
                params = iface.get("parameters", [])
                if params:
                    sections.append(f"  parameters:")
                    for p in params:
                        sections.append(f"    - {p.get('name','')}: {p.get('type','')} — {p.get('description','')}")
                resp = iface.get("response", {})
                if resp:
                    sections.append(f"  response: HTTP {resp.get('status','')}")
                    body = resp.get("body", {})
                    if body:
                        sections.append(f"  response body: {_json.dumps(body, ensure_ascii=False)}")
                ecs = iface.get("error_codes", [])
                if ecs:
                    sections.append(f"  error_codes:")
                    for ec in ecs:
                        sections.append(f"    - {ec.get('code','')}: {ec.get('message','')}")

        # 4. Service contracts
        if ctx.scope.service_contracts:
            sections.append("\n## 服务契约（签名/前置/后置条件不可修改）")
            for sc in ctx.scope.service_contracts:
                for m in sc.get("methods", []):
                    sections.append(f"\n### {sc.get('name','')}.{m.get('name','')}")
                    sections.append(f"  signature: {m.get('signature','')}")
                    pre = m.get("precondition", "")
                    if pre:
                        sections.append(f"  precondition: {pre}")
                    post = m.get("postcondition", "")
                    if post:
                        sections.append(f"  postcondition: {post}")
                    for exc in m.get("exceptions", []):
                        sections.append(
                            f"  → {exc.get('http_status','')} {exc.get('name','')}: "
                            f"{exc.get('trigger','')}"
                        )

        # 5. Data models
        if ctx.scope.data_models:
            sections.append("\n## 数据模型（字段/类型不可修改）")
            for dm in ctx.scope.data_models:
                sections.append(f"\n### {dm.get('name','')} (ownership={dm.get('ownership','')})")
                sections.append(f"  {dm.get('description','')}")
                for f in dm.get("fields", []):
                    sections.append(
                        f"  - {f.get('name','')}: {f.get('type','')} "
                        f"required={f.get('required',False)}"
                    )
                idxs = dm.get("indexes", [])
                if idxs:
                    for idx in idxs:
                        cols = ", ".join(idx.get("columns", []))
                        sections.append(f"  INDEX {idx.get('name','')} ({cols}) unique={idx.get('unique',False)}")

        # 6. Domain objects
        if ctx.scope.domain_objects:
            sections.append("\n## 领域对象")
            for dobj in ctx.scope.domain_objects:
                ot = dobj.get("object_type", "")
                sections.append(f"\n### {dobj.get('name','')} ({ot})")
                sections.append(f"  {dobj.get('description','')}")
                if ot == "enum":
                    vals = dobj.get("values", [])
                    if vals:
                        sections.append(f"  values: {', '.join(vals)}")
                else:
                    for a in dobj.get("attributes", []):
                        sections.append(
                            f"  - {a.get('name','')}: {a.get('type','')} "
                            f"required={a.get('required',False)}"
                            f" | source={a.get('source','')}"
                        )

        # 7. Business rules
        br = ctx.scope.business_rules
        if br:
            sections.append("\n## 业务规则（必须实现）")
            for inv in br.get("invariants", []):
                sections.append(f"  - [invariant] {inv}")
            for sm in br.get("state_machines", []):
                sections.append(f"\n### 状态机: {sm.get('entity','')}")
                sections.append(f"  states: {sm.get('states', [])}")
                sections.append(f"  transitions:")
                for t in sm.get("transitions", []):
                    sections.append(f"    {t.get('from','')} → {t.get('to','')}: {t.get('trigger','')}")
                ir = sm.get("irreversible_rules", [])
                if ir:
                    sections.append(f"  irreversible_rules:")
                    for r in ir:
                        sections.append(f"    - {r}")
                concurrency = sm.get("concurrency", "")
                if concurrency:
                    sections.append(f"  concurrency: {concurrency}")
            for csr in br.get("cross_service_rules", []):
                sections.append(f"  - [cross_service] {csr}")

        # 8. Error handling
        eh = ctx.scope.error_handling
        if eh:
            sections.append("\n## 错误处理")
            if eh.get("strategy"):
                sections.append(f"  strategy: {eh['strategy']}")

        # 9. Acceptance criteria
        if criteria:
            sections.append("\n## 验收标准（每项必须满足）")
            for i, c in enumerate(criteria):
                desc = getattr(c, "description", "") if hasattr(c, "description") else c.get("description", str(c))
                vtype = getattr(c, "verification_type", "") if hasattr(c, "verification_type") else c.get("verification_type", "")
                sections.append(f"  {i + 1}. [{vtype}] {desc}")

        # 10. External contracts
        if ctx.external_contracts:
            sections.append("\n## 依赖的外部接口")
            for ec in ctx.external_contracts:
                sections.append(
                    f"  - {ec.get('module','')}: {ec.get('method','')} {ec.get('endpoint','')}"
                )

        # 11. Full LLD reference
        sections.append(f"\n## 完整 LLD 参考\n{ctx.lld_path}")

        return (
            "实现以下开发任务。接口签名、数据模型字段和业务规则来自详细设计文档(LLD)，必须严格遵守。\n\n"
            + "\n".join(sections)
            + "\n\n要求：\n"
            "1. 以上所有接口签名、字段定义、前置/后置条件必须精确实现\n"
            "2. 每个验收标准必须有对应代码实现来保障\n"
            "3. 所有错误码和异常场景必须实现\n"
            "4. 编写对应的单元测试\n"
            "5. 完成后运行测试验证\n"
            "6. 完成后用中文回复确认"
        )

    def _write_direct(self, module: str, task, code: str) -> dict:
        module_path = self.config.repo_path / "src" / module
        module_path.mkdir(parents=True, exist_ok=True)
        filename = f"{module}_{task.name.replace('-', '_').replace(' ', '_')}.py" if task else f"{module}.py"
        file_path = module_path / filename
        file_path.write_text(code, encoding="utf-8")
        rel = f"src/{module}/{filename}"
        self.wiki_system.git_storage.repo.index.add([rel])
        return self.format_result(
            status="success", message=f"Code written: {rel}",
            artifacts=[rel],
        )
