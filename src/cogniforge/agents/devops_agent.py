"""DevOps Agent - Deployment and Infrastructure Agent"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import DocumentType
from cogniforge.core.exceptions import AgentError


class DevOpsAgent(BaseAgent):
    """DevOps Agent — delegates deploy config generation to Claude Code.
    Deploy / rollback are operational stubs."""

    def run(self, input_data: dict) -> dict:
        try:
            action = input_data.get("action", "prepare_deploy")

            if action == "deploy":
                return self._deploy(input_data)

            if action == "rollback":
                return self._rollback(input_data)

            if self.agent is None:
                raise AgentError("DevOpsAgent requires a Claude Code agent for this action")

            if action == "prepare_deploy":
                return self._agentic_prepare_deploy(input_data)
            else:
                return self.format_result(
                    status="failed", message=f"Unknown action: {action}"
                )

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

    def _agentic_prepare_deploy(self, input_data: dict) -> dict:
        module = input_data.get("module", "unknown")
        environment = input_data.get("environment", "dev")
        version = input_data.get("version", "latest")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        existing = self.wiki_system.list_documents(DocumentType.DEPLOY)
        dep_count = sum(1 for d in existing if d.doc_id.startswith(f"deploy-{module}-{environment}-"))
        seq = dep_count + 1
        doc_id = f"deploy-{module}-{environment}-{seq:03d}"
        json_path = self.wiki_system.agent_path(DocumentType.DEPLOY, doc_id=doc_id)

        prompt = (
            f"为以下模块准备部署配置，以 JSON 格式输出并写入:\n\n"
            f"输出路径: {json_path}\n"
            f"JSON 结构: {{\"meta\": {{\"doc_id\": \"{doc_id}\", \"type\": \"deploy\", "
            f"\"title\": \"部署配置 - {module}\", "
            f"\"author\": \"devops_agent\", \"created\": \"{now}\"}},\n"
            f" \"config\": {{\"module\": \"...\", \"environment\": \"...\", "
            f"\"docker\": {{}}, \"env_vars\": {{}}, \"network\": {{}}, \"health_check\": {{}}}}}}\n\n"
            f"输入数据:\n"
            f"module: {module}\n"
            f"environment: {environment}\n"
            f"version: {version}\n\n"
            f"要求:\n"
            f"1. 先阅读 .cogniforge/wiki/sad/ 了解系统架构\n"
            f"2. 先阅读 .cogniforge/wiki/lld/{module}/ 了解模块设计\n"
            f"3. 在 config 字段中包含: Docker 配置、环境变量、网络设置、健康检查\n"
            f"4. 使用中文、只写 JSON 不写 HTML、完成后回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="devops")

        # Validate generated JSON against schema
        json_abs = Path(self.config.repo_path) / json_path
        if json_abs.exists():
            try:
                data = json.loads(json_abs.read_text(encoding="utf-8"))
                schema_path = self.config.repo_path / "schemas" / "deploy-config-schema.json"
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

        return self._commit_result(json_path, f"部署配置 - {module}", response.content)

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

    def _deploy(self, input_data: dict) -> dict:
        module = input_data.get("module", "unknown")
        environment = input_data.get("environment", "dev")
        return self.format_result(
            status="success",
            message=f"Deploy {module} to {environment} (operational stub)",
            data={"module": module, "environment": environment},
        )

    def _rollback(self, input_data: dict) -> dict:
        module = input_data.get("module", "unknown")
        version = input_data.get("version", "previous")
        return self.format_result(
            status="success",
            message=f"Rollback {module} to {version} (operational stub)",
            data={"module": module, "version": version},
        )

    def _commit_result(self, json_path: Path, title: str, reasoning: str = "") -> dict:
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

        self.wiki_system.git_storage.commit(f"feat: deploy config for {title}", "devops_agent")

        return self.format_result(
            status="success",
            message=f"Deploy config created: {json_path.stem}",
            artifacts=artifacts,
            reasoning=reasoning,
        )
