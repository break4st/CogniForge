"""Review Agent - Code Review Agent"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import DocumentType
from cogniforge.core.exceptions import AgentError


class ReviewAgent(BaseAgent):
    """Review Agent — delegates to Claude Code agent to review code
    and generate CR reports."""

    def run(self, input_data: dict) -> dict:
        try:
            if self.agent is None:
                raise AgentError("ReviewAgent requires a Claude Code agent")

            module = input_data.get("module", "unknown")
            files = input_data.get("files", [])

            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            existing = self.wiki_system.list_documents(DocumentType.REPORT)
            cr_count = sum(1 for d in existing if d.doc_id.startswith(f"cr-{module}-"))
            seq = cr_count + 1
            doc_id = f"cr-{module}-{seq:03d}"
            json_path = self.wiki_system.agent_path(DocumentType.REPORT, doc_id=doc_id)

            prompt = (
                f"对以下模块进行代码评审，以 JSON 格式输出并写入:\n\n"
                f"输出路径: {json_path}\n"
                f"JSON 结构: {{\"meta\": {{\"doc_id\": \"{doc_id}\", \"type\": \"report\", "
                f"\"title\": \"CR 报告 - {module}\", "
                f"\"author\": \"review_agent\", \"created\": \"{now}\"}},\n"
                f" \"content\": \"... (使用 PASS/FAIL 标注每项检查，包含改进建议)\"}}\n\n"
                f"输入数据:\n"
                f"module: {module}\n"
                f"files: {', '.join(files) if files else '所有变更文件'}\n\n"
                f"要求:\n"
                f"1. 先阅读 .cogniforge/wiki/lld/{module}/ 了解设计意图\n"
                f"2. 阅读相关代码文件\n"
                f"3. 在 content 字段中使用 PASS/FAIL 标注每项检查\n"
                f"4. 使用中文、只写 JSON 不写 HTML、完成后回复确认"
            )

            response = self.agent.generate_agentic(prompt, role="reviewer")

            # Validate generated JSON against schema
            json_abs = Path(self.config.repo_path) / json_path
            if json_abs.exists():
                try:
                    data = json.loads(json_abs.read_text(encoding="utf-8"))
                    schema_path = self.config.repo_path / "schemas" / "cr-report-schema.json"
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

            return self._commit_result(json_path, f"CR 报告 - {module}", response.content)

        except Exception as e:
            return self.format_result(status="failed", message=str(e))

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

        self.wiki_system.git_storage.commit(f"feat: code review for {title}", "review_agent")

        return self.format_result(
            status="success",
            message=f"CR completed: {json_path.stem}",
            artifacts=artifacts,
            reasoning=reasoning,
        )
