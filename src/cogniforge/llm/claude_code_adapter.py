"""Claude Code adapter — text mode for NL→JSON, agent mode via Anthropic SDK."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from cogniforge.llm.base import BaseLLMAdapter, LLMResponse, LLMMessage

# ---------------------------------------------------------------------------
# Per-role system prompts (appended for agent mode)
# ---------------------------------------------------------------------------

ROLE_PROMPTS: dict[str, str] = {
    "pm": (
        "你是 CogniForge 系统的 PM (Product Manager) Agent。\n"
        "职责: 根据用户数据生成产品需求文档 (PRD)。\n"
        "要求: 先阅读 DESIGN.html 和已有 PRD 了解风格，生成 JSON，所有文字用中文。"
    ),
    "architect": (
        "你是 CogniForge 系统的 Architect Agent。\n"
        "职责: 根据 PRD 生成系统架构文档 (SAD) JSON。\n"
        "要求: 先阅读 PRD，包含组件设计/拓扑/数据流，使用中文。"
    ),
    "design": (
        "你是 CogniForge 系统的 Design (MDE) Agent。\n"
        "职责: 根据 PRD + SAD 生成详细设计文档 (LLD) JSON。\n"
        "要求: 先阅读 PRD 和 SAD，包含数据模型/接口定义/错误处理，使用中文。"
    ),
    "dev": (
        "你是 CogniForge 系统的 Dev Agent。\n"
        "职责: 根据 LLD 编写代码和测试，运行 pytest 验证。\n"
        "要求: 先阅读 LLD 和 CLAUDE.md，遵循简单优先原则，使用中文。"
    ),
    "reviewer": (
        "你是 CogniForge 系统的 Reviewer Agent。\n"
        "职责: 代码评审，生成 CR 报告 JSON。\n"
        "要求: 阅读 LLD 和代码，检查安全性/简洁性/合规性，使用中文。"
    ),
    "qa": (
        "你是 CogniForge 系统的 QA Agent。\n"
        "职责: 生成测试用例 JSON，执行测试，生成报告。\n"
        "要求: 阅读 LLD 和代码，覆盖正常/边界/错误路径，使用中文。"
    ),
    "techlead": (
        "你是 CogniForge 系统的 Tech Lead Agent。\n"
        "职责: 工作分解 (WBS)，质量评估。\n"
        "要求: 阅读全部上下文，按依赖排序，使用中文。"
    ),
    "devops": (
        "你是 CogniForge 系统的 DevOps Agent。\n"
        "职责: 生成部署配置 JSON。\n"
        "要求: 阅读 SAD 和 LLD，包含 Docker/环境变量/健康检查，使用中文。"
    ),
}

# ---------------------------------------------------------------------------
# Tool definitions (mirroring Claude Code core tools)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Use this to understand existing code, documentation, or context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read, relative to project root."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file. Creates parent directories if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to write to, relative to project root."},
                "content": {"type": "string", "description": "Full file content to write."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "List files in a directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path, relative to project root."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_bash",
        "description": "Run a shell command. Use for testing, building, or inspecting the project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute."},
            },
            "required": ["command"],
        },
    },
]

# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ClaudeCodeAdapter(BaseLLMAdapter):
    """Two-mode adapter:

    - **Text mode** (``generate``): ``claude -p`` without tools — fast, for
      NL→JSON extraction in the REPL.

    - **Agent mode** (``generate_agentic``): Anthropic SDK with tool use —
      Claude reads files, writes output, runs commands.  Full agent loop.
    """

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        # Model: from config, then env (Claude Code uses ANTHROPIC_MODEL)
        self.model = (
            self.config.get("model")
            or os.environ.get("ANTHROPIC_MODEL", "")
            or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "")
            or "claude-sonnet-4-20250514"
        )

        self.api_key = self.config.get("api_key", "")
        self.repo_path = Path(self.config.get("repo_path", Path.cwd())).resolve()
        self.claude_cli_path = self._resolve_claude_cli_path(
            self.config.get("claude_cli_path", "claude")
        )
        self.timeout = self.config.get("timeout", 600)

    # ------------------------------------------------------------------
    # Text mode — pure LLM via claude -p (NL→JSON, extraction, etc.)
    # ------------------------------------------------------------------

    def generate(
        self, prompt: str, context: dict = None, **kwargs
    ) -> LLMResponse:
        """Pure text generation via ``claude -p`` (no tools)."""
        full_prompt = self._build_prompt(prompt, context)
        model = kwargs.get("model", self.model)
        command = [self.claude_cli_path, "-p", full_prompt,
                    "--output-format", "json", "--model", model]
        return self._invoke_cli(command)

    def generate_messages(
        self, messages: list[LLMMessage], **kwargs
    ) -> LLMResponse:
        prompt = self._messages_to_prompt(messages)
        return self.generate(prompt=prompt, **kwargs)

    # ------------------------------------------------------------------
    # Agent mode — Anthropic SDK with tool use
    # ------------------------------------------------------------------

    def generate_agentic(
        self,
        prompt: str,
        *,
        role: str | None = None,
        tools: list[dict] | None = None,
        max_turns: int = 20,
        **kwargs,
    ) -> LLMResponse:
        """Run Claude as an agent with tool access via the Anthropic SDK.

        The agent can read files, write output, and run commands.  We handle
        the tool-use loop ourselves — no CLI permission issues.
        """
        client = self._get_anthropic_client()
        if client is None:
            return self._fallback_agentic(prompt, role=role, **kwargs)

        system_parts: list[str] = []
        if role and role in ROLE_PROMPTS:
            system_parts.append(ROLE_PROMPTS[role])
        system_parts.append(
            f"工作目录: {self.repo_path}\n"
            "你可以使用 read_file / write_file / list_dir / run_bash 工具完成任务。\n"
            "所有文件路径相对于项目根目录。完成后用中文回复。"
        )
        system = "\n\n".join(system_parts)

        messages: list[dict] = [{"role": "user", "content": prompt}]
        effective_tools = tools or TOOLS
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        for _ in range(max_turns):
            response = client.messages.create(
                model=kwargs.get("model", self.model),
                max_tokens=kwargs.get("max_tokens", 8192),
                system=system,
                messages=messages,
                tools=effective_tools,
            )

            # Tally usage
            u = response.usage
            usage["input_tokens"] += u.input_tokens
            usage["output_tokens"] += u.output_tokens
            usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]

            # Collect text + tool_use blocks
            text_parts: list[str] = []
            tool_uses: list[dict] = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            # If the model called tools, execute them and continue
            if tool_uses and response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results: list[dict] = []
                for tu in tool_uses:
                    result_text = self._execute_tool(tu["name"], tu["input"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": result_text,
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            # No more tool calls — finished
            return LLMResponse(
                content="\n".join(text_parts),
                model=kwargs.get("model", self.model),
                provider="claude_code",
                usage=usage,
            )

        return LLMResponse(
            content="(exceeded max turns)",
            model=kwargs.get("model", self.model),
            provider="claude_code",
            usage=usage,
        )

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool(self, name: str, inp: dict) -> str:
        """Execute a tool call and return the result text."""
        try:
            if name == "read_file":
                p = self.repo_path / inp["path"]
                if not p.exists():
                    return f"Error: file not found: {inp['path']}"
                content = p.read_text(encoding="utf-8")
                if len(content) > 8000:
                    content = content[:8000] + f"\n... (truncated, total {len(content)} chars)"
                return content

            elif name == "write_file":
                p = self.repo_path / inp["path"]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(inp["content"], encoding="utf-8")
                return f"Successfully wrote {len(inp['content'])} chars to {inp['path']}"

            elif name == "list_dir":
                p = self.repo_path / inp["path"]
                if not p.exists():
                    return f"Error: directory not found: {inp['path']}"
                items = sorted(os.listdir(p))
                return "\n".join(items[:50])

            elif name == "run_bash":
                result = subprocess.run(
                    inp["command"], shell=True, capture_output=True, text=True,
                    timeout=120, cwd=str(self.repo_path),
                )
                out = result.stdout
                if result.stderr:
                    out += f"\n[stderr]\n{result.stderr}"
                if len(out) > 4000:
                    out = out[:4000] + f"\n... (truncated)"
                return f"exit: {result.returncode}\n{out}"

            else:
                return f"Unknown tool: {name}"

        except Exception as e:
            return f"Tool error ({name}): {e}"

    # ------------------------------------------------------------------
    # Fallback — claude -p with tools (for environments where SDK can't auth)
    # ------------------------------------------------------------------

    def _fallback_agentic(self, prompt, *, role=None, **kwargs) -> LLMResponse:
        """Fallback: use ``claude -p`` with tools flags."""
        model = kwargs.get("model", self.model)
        cmd = [
            self.claude_cli_path, "-p", prompt,
            "--output-format", "json", "--model", model,
            "--tools", "Read,Write,Edit,Bash",
            "--permission-mode", "acceptEdits",
        ]
        if role and role in ROLE_PROMPTS:
            cmd.extend(["--append-system-prompt", ROLE_PROMPTS[role]])
        return self._invoke_cli(cmd)

    def _get_anthropic_client(self):
        """Create an Anthropic client.  Reads auth from env vars set by claude."""
        api_key = self.api_key
        base_url = None

        # Try env vars that Claude Code sets (supports DeepSeek, etc.)
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
        if not base_url:
            base_url = None  # use SDK default

        if not api_key:
            return None

        try:
            import anthropic
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            return anthropic.Anthropic(**kwargs)
        except ImportError:
            return None

    # ------------------------------------------------------------------
    # CLI invocation (shared by text mode and fallback)
    # ------------------------------------------------------------------

    def _invoke_cli(self, command: list[str]) -> LLMResponse:
        env = os.environ.copy()
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key

        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                cwd=str(self.repo_path), timeout=self.timeout,
                env=env, check=False,
            )
        except FileNotFoundError:
            raise RuntimeError("Claude Code CLI not found.")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Claude Code CLI timeout after {self.timeout}s")

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            if "error" in err.lower() and "tool" not in err.lower():
                raise RuntimeError(f"Claude CLI failed (exit {result.returncode}): {err}")

        content, usage = self._parse_output(result.stdout)
        if not content:
            content = result.stderr or result.stdout or ""
        if not content:
            raise RuntimeError("Claude Code CLI returned empty response")

        return LLMResponse(
            content=content, model=self.model, provider="claude_code", usage=usage,
        )

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, prompt: str, context: dict = None) -> str:
        if not context:
            return prompt
        parts = ["# Context"]
        for k, v in context.items():
            if isinstance(v, dict):
                parts.append(f"\n## {k}")
                for kv, vv in v.items():
                    parts.append(f"- {kv}: {vv}")
            elif isinstance(v, list):
                parts.append(f"\n## {k}")
                for item in v:
                    parts.append(f"- {item}")
            else:
                parts.append(f"- {k}: {v}")
        parts.append(f"\n# Prompt\n{prompt}")
        return "\n".join(parts)

    def _messages_to_prompt(self, messages: list[LLMMessage]) -> str:
        return "\n".join(f"{m.role.upper()}:\n{m.content}\n" for m in messages).strip()

    # ------------------------------------------------------------------
    # Output parsing (claude -p --output-format json)
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
        u = data.get("usage")
        if isinstance(u, dict):
            inp = u.get("input_tokens") or u.get("prompt_tokens") or 0
            out = u.get("output_tokens") or u.get("completion_tokens") or 0
            usage["input_tokens"] = inp
            usage["output_tokens"] = out
            usage["total_tokens"] = inp + out
        return content, usage

    # ------------------------------------------------------------------
    # CLI path / env
    # ------------------------------------------------------------------

    def _resolve_claude_cli_path(self, cli_path: str) -> str:
        if os.name != "nt":
            return cli_path
        for c in [cli_path, "claude.cmd", "claude.exe"]:
            r = shutil.which(c)
            if r:
                return r
        return cli_path

    # ------------------------------------------------------------------
    # Provider metadata
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "Claude Code"

    @property
    def supported_models(self) -> list[str]:
        return ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"]
