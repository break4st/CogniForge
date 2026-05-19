"""DevOps Agent - Deployment and Infrastructure Agent"""

from __future__ import annotations

import json
from pathlib import Path

from cogniforge.agents.base import BaseAgent
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
        output_path = f".cogniforge/wiki/ops/deploy.md"

        prompt = (
            f"为以下模块准备部署配置:\n\n"
            f"模块: {module}\n"
            f"环境: {environment}\n"
            f"版本: {version}\n\n"
            f"要求：\n"
            f"1. 先阅读 .cogniforge/wiki/sad/ 了解系统架构\n"
            f"2. 先阅读 .cogniforge/wiki/lld/{module}/ 了解模块设计\n"
            f"3. 生成部署配置写入: {output_path}\n"
            f"4. 包含: Docker 配置、环境变量、网络设置、健康检查\n"
            f"5. 使用中文\n"
            f"6. 完成后用中文回复确认"
        )

        response = self.agent.generate_agentic(prompt, role="devops")

        output_abs = Path(self.config.repo_path) / output_path
        if output_abs.exists():
            self.wiki_system.git_storage.repo.index.add([output_path])
            self.wiki_system.git_storage.commit(
                f"feat: deploy config for {module}", "devops_agent"
            )
            return self.format_result(
                status="success",
                message=f"Deploy config prepared for {module}",
                artifacts=[output_path],
                reasoning=response.content,
            )
        return self.format_result(
            status="failed", message=f"Deploy config not produced for {module}"
        )

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
