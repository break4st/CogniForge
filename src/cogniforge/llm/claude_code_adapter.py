"""Claude Code adapter — text mode for NL→JSON, agent mode for real work."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from cogniforge.llm.base import BaseLLMAdapter, LLMResponse, LLMMessage

# ---------------------------------------------------------------------------
# Per-role system prompt snippets appended to the default system prompt
# (CLAUDE.md is still loaded automatically — these add role-specific guidance)
# ---------------------------------------------------------------------------

ROLE_PROMPTS: dict[str, str] = {
    "pm": (
        "你是 CogniForge 系统的 PM (Product Manager) Agent。\n"
        "职责: 根据用户提供的数据生成产品需求文档 (PRD)。\n"
        "要求:\n"
        "- 先阅读 DESIGN.html 了解项目视觉风格\n"
        "- 先阅读 .cogniforge/wiki/prd/ 下已有 PRD 了解文档格式\n"
        "- 生成自包含的 HTML 文件，内嵌 CSS，暗色主题，与 DESIGN.html 风格一致\n"
        "- 所有标题和标签使用中文\n"
        "- 写入用户指定的路径，不要写入其他路径\n"
        "- 完成后用中文回复结果"
    ),
    "architect": (
        "你是 CogniForge 系统的 Architect Agent。\n"
        "职责: 根据 PRD 生成系统架构文档 (SAD)。\n"
        "要求:\n"
        "- 先阅读 .cogniforge/wiki/prd/ 下的 PRD 了解需求\n"
        "- 先阅读 DESIGN.html 了解架构设计规范\n"
        "- 生成架构文档，包含组件设计、拓扑结构、数据流、技术选型\n"
        "- 使用中文\n"
        "- 写入用户指定的路径"
    ),
    "design": (
        "你是 CogniForge 系统的 Design (MDE) Agent。\n"
        "职责: 根据 PRD 和 SAD 生成详细设计文档 (LLD)。\n"
        "要求:\n"
        "- 先阅读 PRD 和 SAD 了解上下文\n"
        "- 生成详细设计文档，包含数据模型、接口定义、错误处理策略\n"
        "- 使用中文\n"
        "- 写入用户指定的路径"
    ),
    "dev": (
        "你是 CogniForge 系统的 Dev Agent。\n"
        "职责: 根据 LLD 编写代码实现。\n"
        "要求:\n"
        "- 先阅读 LLD、SAD、PRD 了解完整上下文\n"
        "- 编写符合项目规范的代码\n"
        "- 遵循 CLAUDE.md 中的行为准则（简单优先、精准修改）\n"
        "- 写入 src/{module}/ 路径\n"
        "- 使用中文回复"
    ),
    "reviewer": (
        "你是 CogniForge 系统的 Reviewer Agent。\n"
        "职责: 对代码进行评审，生成 CR 报告。\n"
        "要求:\n"
        "- 阅读 LLD 和代码变更\n"
        "- 检查代码是否符合设计、是否安全、是否简洁\n"
        "- 生成 CR 报告写入 .cogniforge/wiki/reports/\n"
        "- 使用中文"
    ),
    "qa": (
        "你是 CogniForge 系统的 QA Agent。\n"
        "职责: 根据 LLD 生成测试用例并执行测试。\n"
        "要求:\n"
        "- 阅读 LLD 和代码\n"
        "- 生成测试用例写入 .cogniforge/wiki/qa/\n"
        "- 运行测试并生成报告写入 .cogniforge/wiki/reports/\n"
        "- 使用中文"
    ),
    "techlead": (
        "你是 CogniForge 系统的 Tech Lead Agent。\n"
        "职责: 工作分解 (WBS)、质量评估、流程控制。\n"
        "要求:\n"
        "- 阅读 PRD、SAD、LLD 了解完整上下文\n"
        "- 生成 WBS 任务分解\n"
        "- 评估质量门禁是否通过\n"
        "- 使用中文"
    ),
    "devops": (
        "你是 CogniForge 系统的 DevOps Agent。\n"
        "职责: 部署配置、上线运维。\n"
        "要求:\n"
        "- 阅读 SAD 和 LLD 了解部署需求\n"
        "- 生成部署配置文件\n"
        "- 使用中文"
    ),
}


class ClaudeCodeAdapter(BaseLLMAdapter):
    """Claude Code LLM adapter with two modes:

    - **Text mode** (generate):  ``claude -p`` without tools.  Fast, stateless.
      Used by the REPL for NL→JSON classification, field extraction, etc.

    - **Agent mode** (generate_agentic): ``claude -p`` with tools enabled.
      Claude Code can *read* context, *write* output files, and *run* shell
      commands — like a real agent.
    """

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        self.model = self.config.get("model", "claude-sonnet-4-20250514")
        self.api_key = self.config.get("api_key", "")
        self.repo_path = Path(self.config.get("repo_path", Path.cwd()))
        self.claude_cli_path = self._resolve_claude_cli_path(
            self.config.get("claude_cli_path", "claude")
        )
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.timeout = self.config.get("timeout", 600)

    # ------------------------------------------------------------------
    # Text mode — pure LLM, no tools (NL→JSON, extraction, etc.)
    # ------------------------------------------------------------------

    def generate(
        self, prompt: str, context: dict = None, **kwargs
    ) -> LLMResponse:
        """Pure text generation — no tool access."""
        full_prompt = self._build_prompt(prompt, context)
        command = self._build_text_command(prompt=full_prompt, **kwargs)
        return self._invoke(command)

    def generate_messages(
        self, messages: list[LLMMessage], **kwargs
    ) -> LLMResponse:
        prompt = self._messages_to_prompt(messages)
        return self.generate(prompt=prompt, **kwargs)

    # ------------------------------------------------------------------
    # Agent mode — Claude Code with tools (Read, Write, Edit, Bash)
    # ------------------------------------------------------------------

    def generate_agentic(
        self,
        prompt: str,
        *,
        role: str | None = None,
        tools: str = "Read,Write,Edit,Bash",
        permission_mode: str = "auto",
        **kwargs,
    ) -> LLMResponse:
        """Run Claude Code as an **agent** — it can read context, write
        output files, and execute shell commands.

        Parameters
        ----------
        prompt:
            The task description (what to do).
        role:
            Optional agent role key (``"pm"``, ``"dev"``, …).  If given,
            the corresponding role system prompt is appended so Claude Code
            understands its job.
        tools:
            Comma-separated tool list (default: ``"Read,Write,Edit,Bash"``).
        permission_mode:
            Permission mode.  ``"auto"`` allows safe writes without prompts.
        """
        command = self._build_agentic_command(
            prompt=prompt,
            role=role,
            tools=tools,
            permission_mode=permission_mode,
            **kwargs,
        )
        return self._invoke(command)

    # ------------------------------------------------------------------
    # Command builders
    # ------------------------------------------------------------------

    def _build_text_command(self, *, prompt: str, **kwargs) -> list[str]:
        """Minimal ``claude -p`` for text-only generation."""
        model = kwargs.get("model", self.model)
        cmd = [
            self.claude_cli_path,
            "-p", prompt,
            "--output-format", "json",
            "--model", model,
        ]
        return cmd

    def _build_agentic_command(
        self,
        *,
        prompt: str,
        role: str | None,
        tools: str,
        permission_mode: str,
        **kwargs,
    ) -> list[str]:
        """``claude -p`` with full agent capabilities."""
        model = kwargs.get("model", self.model)
        cmd = [
            self.claude_cli_path,
            "-p", prompt,
            "--output-format", "json",
            "--model", model,
            "--tools", tools,
            "--permission-mode", permission_mode,
        ]

        if role and role in ROLE_PROMPTS:
            cmd.extend(["--append-system-prompt", ROLE_PROMPTS[role]])

        return cmd

    # ------------------------------------------------------------------
    # Shared invocation
    # ------------------------------------------------------------------

    def _invoke(self, command: list[str]) -> LLMResponse:
        env = self._build_env()

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=str(self.repo_path),
                timeout=self.timeout,
                env=env,
                check=False,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Claude Code CLI not found. Install it first."
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Claude Code CLI timeout after {self.timeout}s"
            )

        if result.returncode != 0:
            error_message = (result.stderr or result.stdout or "").strip()
            # Don't raise on tool-use stderr noise
            if "error" in error_message.lower() and "tool" not in error_message.lower():
                raise RuntimeError(
                    f"Claude Code CLI failed (exit {result.returncode}): {error_message}"
                )

        content, usage = self._parse_output(result.stdout)
        if not content:
            raise RuntimeError("Claude Code CLI returned empty response")

        return LLMResponse(
            content=content,
            model=self.model,
            provider="claude_code",
            usage=usage,
        )

    # ------------------------------------------------------------------
    # Prompt helpers (text mode)
    # ------------------------------------------------------------------

    def _build_prompt(self, prompt: str, context: dict = None) -> str:
        if not context:
            return prompt
        parts = ["# Context\n"]
        for key, value in context.items():
            if isinstance(value, dict):
                parts.append(f"\n## {key}")
                for k, v in value.items():
                    parts.append(f"- {k}: {v}")
            elif isinstance(value, list):
                parts.append(f"\n## {key}")
                for item in value:
                    parts.append(f"- {item}")
            else:
                parts.append(f"- {key}: {value}")
        parts.append(f"\n# Prompt\n{prompt}")
        return "\n".join(parts)

    def _messages_to_prompt(self, messages: list[LLMMessage]) -> str:
        return "\n".join(
            f"{msg.role.upper()}:\n{msg.content}\n" for msg in messages
        ).strip()

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def _parse_output(self, stdout: str) -> tuple[str, dict]:
        usage: dict = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        stdout = stdout.strip()
        if not stdout:
            return "", usage
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return stdout, usage
        if not isinstance(data, dict):
            return stdout, usage

        content = data.get("result", "")
        raw_usage = data.get("usage")
        if isinstance(raw_usage, dict):
            inp = raw_usage.get("input_tokens") or raw_usage.get("prompt_tokens") or 0
            out = raw_usage.get("output_tokens") or raw_usage.get("completion_tokens") or 0
            usage["input_tokens"] = inp
            usage["output_tokens"] = out
            usage["total_tokens"] = inp + out

        return content, usage

    # ------------------------------------------------------------------
    # CLI path / env
    # ------------------------------------------------------------------

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        api_key = self.api_key or env.get("ANTHROPIC_API_KEY", "")
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
        return env

    def _resolve_claude_cli_path(self, cli_path: str) -> str:
        if os.name != "nt":
            return cli_path
        for candidate in [cli_path, "claude.cmd", "claude.exe"]:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        return cli_path

    # ------------------------------------------------------------------
    # Provider metadata
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "Claude Code"

    @property
    def supported_models(self) -> list[str]:
        return [
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
        ]
