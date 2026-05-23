"""DeepSeek API adapter — text mode via chat completions, agent mode via tool-calling loop."""

from __future__ import annotations

import json
import os
import re
import subprocess
import glob as _glob
from pathlib import Path

from openai import OpenAI

from cogniforge.llm.base import BaseLLMAdapter, LLMResponse, LLMMessage

# ---------------------------------------------------------------------------
# Per-role system prompts (mirrored from claude_code_adapter to avoid circular import)
# ---------------------------------------------------------------------------

ROLE_PROMPTS: dict[str, str] = {
    "pm": (
        "你是 CogniForge 系统的 PM (Product Manager) Agent。\n"
        "职责: 根据用户数据生成产品需求文档 (PRD)。"
    ),
    "architect": (
        "你是 CogniForge 系统的 Architect Agent。\n"
        "职责: 根据 PRD 生成系统架构文档 (SAD) JSON。"
    ),
    "design": (
        "你是 CogniForge 系统的 Design (MDE) Agent。\n"
        "职责: 根据 PRD + SAD 生成详细设计文档 (LLD) JSON。"
    ),
    "dev": (
        "你是 CogniForge 系统的 Dev Agent。\n"
        "职责: 根据 LLD 编写代码和测试，运行 pytest 验证。"
    ),
    "reviewer": (
        "你是 CogniForge 系统的 Reviewer Agent。\n"
        "职责: 代码评审，生成 CR 报告 JSON。"
    ),
    "qa": (
        "你是 CogniForge 系统的 QA Agent。\n"
        "职责: 生成测试用例 JSON，执行测试，生成报告。"
    ),
    "techlead": (
        "你是 CogniForge 系统的 Tech Lead Agent。\n"
        "职责: 工作分解 (WBS)，质量评估。"
    ),
    "devops": (
        "你是 CogniForge 系统的 DevOps Agent。\n"
        "职责: 生成部署配置 JSON。"
    ),
}

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "读取文件内容。用于查看已有文档、代码或配置文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对于项目根目录的文件路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "将内容写入文件。如果文件所在目录不存在会自动创建。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对于项目根目录的文件路径"},
                    "content": {"type": "string", "description": "要写入的完整内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "在文件中查找并替换文本。old_string 必须在文件中唯一或首次出现。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对于项目根目录的文件路径"},
                    "old_string": {"type": "string", "description": "要替换的原文本"},
                    "new_string": {"type": "string", "description": "替换后的新文本"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "执行 shell 命令。用于运行测试、查看 git 状态、安装依赖等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "按模式搜索文件。支持 ** 递归匹配。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "文件匹配模式，如 **/*.py"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "在文件中搜索文本模式。返回匹配的行及文件名和行号。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "要搜索的正则表达式或文本"},
                    "path": {"type": "string", "description": "搜索路径，默认为项目根目录"},
                },
                "required": ["pattern"],
            },
        },
    },
]

# User-friendly tool names for progress display
_TOOL_DISPLAY: dict[str, str] = {
    "Read": "读取文件",
    "Write": "写入文件",
    "Edit": "编辑文件",
    "Bash": "执行命令",
    "Glob": "搜索文件",
    "Grep": "搜索内容",
}

# Dangerous command patterns blocked by _tool_bash
_FORBIDDEN_PATTERNS = [
    r"rm\s+-rf\s+/", r":\s*\(\s*\)\s*\{", r">\s*/dev/sda",
    r"mkfs\.", r"dd\s+if=", r"sudo\s+rm", r"chmod\s+777\s+/",
]


class DeepSeekAdapter(BaseLLMAdapter):
    """Two-mode adapter via DeepSeek HTTP API.

    - **Text mode** (``generate``): chat completions + response_format json_object.
    - **Agent mode** (``generate_agentic``): self-implemented tool-calling loop
      supporting Read / Write / Edit / Bash / Glob / Grep tools.
    """

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        self.model = (
            self.config.get("model")
            or os.environ.get("DEEPSEEK_MODEL", "")
            or "deepseek-v4-pro"
        )
        self.api_key = (
            self.config.get("api_key")
            or os.environ.get("DEEPSEEK_API_KEY", "")
        )
        self.api_base = (
            self.config.get("api_base")
            or os.environ.get("DEEPSEEK_API_BASE", "")
            or "https://api.deepseek.com/v1"
        )
        self.repo_path = Path(self.config.get("repo_path", Path.cwd())).resolve()
        self.max_tokens = int(self.config.get("max_tokens", 4096))
        self.timeout = int(self.config.get("timeout", 600))

        self._client = OpenAI(api_key=self.api_key, base_url=self.api_base)

    # ------------------------------------------------------------------
    # Text mode
    # ------------------------------------------------------------------

    def generate(
        self, prompt: str, context: dict = None, **kwargs
    ) -> LLMResponse:
        full_prompt = self._build_prompt(prompt, context)
        model = kwargs.get("model", self.model)
        response = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": full_prompt}],
            response_format={"type": "json_object"},
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            timeout=self.timeout,
        )
        return self._to_llm_response(response)

    def generate_messages(
        self, messages: list[LLMMessage], **kwargs
    ) -> LLMResponse:
        api_messages = [{"role": m.role, "content": m.content} for m in messages]
        model = kwargs.get("model", self.model)
        response = self._client.chat.completions.create(
            model=model,
            messages=api_messages,
            response_format={"type": "json_object"},
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            timeout=self.timeout,
        )
        return self._to_llm_response(response)

    # ------------------------------------------------------------------
    # Agent mode — tool-calling loop
    # ------------------------------------------------------------------

    def generate_agentic(
        self,
        prompt: str,
        *,
        role: str | None = None,
        tools: list[dict] | None = None,
        max_turns: int = 20,
        progress_callback: callable = None,
        **kwargs,
    ) -> LLMResponse:
        messages = self._build_agentic_messages(prompt, role)
        tool_defs = tools or TOOL_DEFINITIONS
        model = kwargs.get("model", self.model)
        cb = progress_callback

        for _turn in range(max_turns):
            if cb and _turn == 0:
                cb("正在分析需求...")
            response = self._client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tool_defs,
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                timeout=self.timeout,
            )
            choice = response.choices[0]
            msg = choice.message

            # No tool calls → final response
            if not msg.tool_calls:
                if cb:
                    cb("正在生成最终回复...")
                return LLMResponse(
                    content=msg.content or "",
                    model=self.model,
                    provider="deepseek",
                    usage=self._extract_usage(response),
                )

            # Append assistant message with tool_calls, preserving any
            # extra fields (e.g. reasoning_content for DeepSeek thinking mode)
            assistant_msg: dict = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
            for field in ("reasoning_content",):
                val = getattr(msg, field, None)
                if val:
                    assistant_msg[field] = val
            messages.append(assistant_msg)

            # Execute each tool call
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                file_hint = args.get("path", args.get("pattern",
                             args.get("command", "")))
                display = _TOOL_DISPLAY.get(name, name)
                if file_hint:
                    # Truncate long command/pattern strings
                    short = file_hint if len(file_hint) <= 60 else file_hint[:57] + "..."
                    display = f"{display}: {short}"
                if cb:
                    cb(display)
                try:
                    result = self._execute_tool(name, tc.function.arguments)
                    result_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                except Exception as exc:
                    result_str = f"Error: {exc}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        # Reached max_turns
        return LLMResponse(
            content="(reached max turns without final response)",
            model=self.model,
            provider="deepseek",
            usage={},
        )

    def _build_agentic_messages(self, prompt: str, role: str | None) -> list[dict]:
        messages: list[dict] = []
        system_parts: list[str] = []

        if role and role in ROLE_PROMPTS:
            system_parts.append(ROLE_PROMPTS[role])

        constraint_loader = self.config.get("constraint_loader")
        if constraint_loader and role:
            constraints = constraint_loader.load(role)
            if constraints:
                system_parts.append(f"# 约束\n{constraints}")

        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})

        full_prompt = prompt + f"\n\n工作目录: {self.repo_path}\n完成后用中文回复。"
        messages.append({"role": "user", "content": full_prompt})
        return messages

    # ------------------------------------------------------------------
    # Interactive modification
    # ------------------------------------------------------------------

    def generate_interactive(
        self,
        current_document: str,
        user_request: str,
        system_prompt: str = "",
        **kwargs,
    ) -> LLMResponse:
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({
            "role": "user",
            "content": (
                f"当前文档 JSON:\n{current_document}\n\n"
                f"用户修改要求: {user_request}\n\n"
                f"请根据用户要求修改文档，返回完整的修改后 JSON。\n"
                f"只返回纯 JSON，不要 markdown 代码块包裹，不要多余解释文字。"
            ),
        })
        model = kwargs.get("model", self.model)
        response = self._client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            timeout=self.timeout,
        )
        return self._to_llm_response(response)

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _execute_tool(self, name: str, args_json: str) -> str:
        args = json.loads(args_json)
        tool_map = {
            "Read": self._tool_read,
            "Write": self._tool_write,
            "Edit": self._tool_edit,
            "Bash": self._tool_bash,
            "Glob": self._tool_glob,
            "Grep": self._tool_grep,
        }
        fn = tool_map.get(name)
        if fn is None:
            return f"Unknown tool: {name}"
        return fn(**args)

    def _resolve_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.repo_path / p
        p = p.resolve()
        if not str(p).startswith(str(self.repo_path)):
            raise PermissionError(f"路径超出项目范围: {path}")
        return p

    def _tool_read(self, path: str) -> str:
        full = self._resolve_path(path)
        if not full.exists():
            return f"Error: 文件不存在: {path}"
        return full.read_text(encoding="utf-8")

    def _tool_write(self, path: str, content: str) -> str:
        full = self._resolve_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return f"已写入: {path}"

    def _tool_edit(self, path: str, old_string: str, new_string: str) -> str:
        full = self._resolve_path(path)
        if not full.exists():
            return f"Error: 文件不存在: {path}"
        content = full.read_text(encoding="utf-8")
        if old_string not in content:
            return f"Error: 在 {path} 中未找到指定文本"
        content = content.replace(old_string, new_string, 1)
        full.write_text(content, encoding="utf-8")
        return f"已编辑: {path}"

    def _tool_bash(self, command: str) -> str:
        for pat in _FORBIDDEN_PATTERNS:
            if re.search(pat, command):
                return f"Error: 命令被安全策略拦截: {command[:80]}"
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["cmd", "/c", command],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(self.repo_path),
                )
            else:
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True,
                    timeout=30, cwd=str(self.repo_path),
                )
        except subprocess.TimeoutExpired:
            return "Error: 命令执行超时 (30s)"
        output = (result.stdout or "") + (result.stderr or "")
        if len(output) > 10000:
            output = output[:10000] + "\n... (输出已截断)"
        return output or "(无输出)"

    def _tool_glob(self, pattern: str) -> str:
        matches = _glob.glob(pattern, root_dir=str(self.repo_path), recursive=True)
        if not matches:
            return "(无匹配文件)"
        return json.dumps(sorted(matches), ensure_ascii=False, indent=2)

    def _tool_grep(self, pattern: str, path: str = ".") -> str:
        search_path = self._resolve_path(path)
        try:
            result = subprocess.run(
                ["grep", "-rn", pattern, str(search_path)],
                capture_output=True, text=True, timeout=10,
            )
        except FileNotFoundError:
            # Fallback: Python implementation for Windows
            return self._grep_python(pattern, search_path)
        except subprocess.TimeoutExpired:
            return "Error: 搜索超时 (10s)"
        output = result.stdout
        if len(output) > 10000:
            output = output[:10000] + "\n... (输出已截断)"
        return output or "(无匹配)"

    @staticmethod
    def _grep_python(pattern: str, search_path: Path) -> str:
        lines: list[str] = []
        try:
            regex = re.compile(pattern)
        except re.error:
            regex = re.compile(re.escape(pattern))
        for f in search_path.rglob("*"):
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel = f.relative_to(search_path)
                    lines.append(f"{rel}:{lineno}:{line.rstrip()}")
        if len(lines) > 200:
            lines = lines[:200]
            lines.append("... (结果已截断)")
        return "\n".join(lines) if lines else "(无匹配)"

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

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    def _to_llm_response(self, response) -> LLMResponse:
        choice = response.choices[0]
        content = choice.message.content or ""
        return LLMResponse(
            content=content,
            model=self.model,
            provider="deepseek",
            usage=self._extract_usage(response),
        )

    @staticmethod
    def _extract_usage(response) -> dict:
        if response.usage is None:
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        return {
            "input_tokens": response.usage.prompt_tokens or 0,
            "output_tokens": response.usage.completion_tokens or 0,
            "total_tokens": (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0),
        }

    # ------------------------------------------------------------------
    # Provider metadata
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "deepseek"

    @property
    def supported_models(self) -> list[str]:
        return ["deepseek-v4-pro", "deepseek-v4", "deepseek-chat", "deepseek-reasoner"]
