"""Claude Code adapter — text mode for NL→JSON, agent mode via CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from cogniforge.llm.base import BaseLLMAdapter, LLMResponse, LLMMessage

# ---------------------------------------------------------------------------
# Per-role system prompts (appended for agent mode)
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

class ClaudeCodeAdapter(BaseLLMAdapter):
    """Two-mode adapter:

    - **Text mode** (``generate``): ``claude -p`` without tools — fast, for
      NL→JSON extraction in the REPL.

    - **Agent mode** (``generate_agentic``): ``claude -p`` with ``--tools`` —
      Claude reads files, writes output, runs commands via CLI.
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
        """Pure text generation via ``claude -p`` (no tools).

        Always passes the prompt via stdin (``-p -``) to avoid
        command-line argument corruption on Windows, where multi-line
        prompts with embedded JSON quotes would be mangled by cmd.exe.
        """
        full_prompt = self._build_prompt(prompt, context)
        model = kwargs.get("model", self.model)
        command = [self.claude_cli_path, "-p", "-",
                    "--output-format", "json", "--model", model]
        return self._invoke_cli_stdin(command, full_prompt)

    def generate_messages(
        self, messages: list[LLMMessage], **kwargs
    ) -> LLMResponse:
        prompt = self._messages_to_prompt(messages)
        return self.generate(prompt=prompt, **kwargs)

    # ------------------------------------------------------------------
    # Agent mode — claude -p with --tools
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
        """Agent mode via ``claude -p`` with ``--tools``.

        Claude CLI handles the tool-use loop autonomously — we just pass the
        prompt, role, and tool configuration on the command line.  The final
        text response is parsed from the JSON output.
        """
        if progress_callback:
            progress_callback("通过 Claude CLI 执行中...")
        model = kwargs.get("model", self.model)

        cmd = [
            self.claude_cli_path, "-p", "-",
            "--output-format", "json",
            "--model", model,
            "--tools", "Read,Write,Edit,Bash,Glob,Grep",
            "--permission-mode", "acceptEdits",
            "--max-turns", str(max_turns),
        ]

        if role and role in ROLE_PROMPTS:
            cmd.extend(["--append-system-prompt", ROLE_PROMPTS[role]])

        # Build the full prompt: constraints (if any) + user prompt + workdir
        full_prompt = prompt
        constraint_loader = self.config.get("constraint_loader")
        if constraint_loader and role:
            constraints = constraint_loader.load(role)
            if constraints:
                full_prompt = f"# 约束\n{constraints}\n\n# 任务\n{prompt}"

        full_prompt += (
            f"\n\n工作目录: {self.repo_path}\n"
            "完成后用中文回复。"
        )

        return self._invoke_cli_stdin(cmd, full_prompt)

    def generate_agentic_stream(
        self,
        prompt: str,
        *,
        role: str | None = None,
        tools: list[dict] | None = None,
        max_turns: int = 20,
        progress_callback: callable = None,
        content_callback: callable = None,
        **kwargs,
    ) -> LLMResponse:
        """Streaming version of generate_agentic.

        Calls content_callback with each line of stdout as the CLI produces it.
        """
        if progress_callback:
            progress_callback("通过 Claude CLI 执行中...")
        model = kwargs.get("model", self.model)

        cmd = [
            self.claude_cli_path, "-p", "-",
            "--output-format", "json",
            "--model", model,
            "--tools", "Read,Write,Edit,Bash,Glob,Grep",
            "--permission-mode", "acceptEdits",
            "--max-turns", str(max_turns),
        ]

        if role and role in ROLE_PROMPTS:
            cmd.extend(["--append-system-prompt", ROLE_PROMPTS[role]])

        full_prompt = prompt
        constraint_loader = self.config.get("constraint_loader")
        if constraint_loader and role:
            constraints = constraint_loader.load(role)
            if constraints:
                full_prompt = f"# 约束\n{constraints}\n\n# 任务\n{prompt}"

        full_prompt += (
            f"\n\n工作目录: {self.repo_path}\n"
            "完成后用中文回复。"
        )

        return self._invoke_cli_stdin(cmd, full_prompt, content_callback=content_callback)

    # ------------------------------------------------------------------
    # Prompt helpers (shared by text mode and agent mode)
    # ------------------------------------------------------------------

    def _invoke_cli(self, command: list[str]) -> LLMResponse:
        env = os.environ.copy()
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key

        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                cwd=str(self.repo_path), timeout=self.timeout,
                env=env, check=False, encoding="utf-8",
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

    def _invoke_cli_stdin(
        self, command: list[str], stdin_text: str,
        content_callback: callable = None,
    ) -> LLMResponse:
        """Invoke CLI with prompt passed via stdin (avoids ARG_MAX limit).

        If content_callback is provided, it is called with each non-empty
        line of stdout as it arrives (streaming mode via Popen + thread).
        """
        if content_callback is None:
            return self._invoke_cli_stdin_blocking(command, stdin_text)
        return self._invoke_cli_stdin_stream(command, stdin_text, content_callback)

    def _invoke_cli_stdin_blocking(
        self, command: list[str], stdin_text: str,
    ) -> LLMResponse:
        """Original blocking subprocess.run() path."""
        env = os.environ.copy()
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key

        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                cwd=str(self.repo_path), timeout=self.timeout,
                env=env, check=False, input=stdin_text, encoding="utf-8",
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

    def _invoke_cli_stdin_stream(
        self, command: list[str], stdin_text: str,
        content_callback: callable,
    ) -> LLMResponse:
        """Streaming path using Popen + reader thread.

        content_callback is called with each line of stdout as it arrives.
        """
        import threading

        env = os.environ.copy()
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key

        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.repo_path),
                env=env,
                text=True,
                encoding="utf-8",
            )
        except FileNotFoundError:
            raise RuntimeError("Claude Code CLI not found.")

        accumulated_stdout = []
        read_error = None

        def _read_stdout():
            nonlocal read_error
            try:
                for line in proc.stdout:
                    line = line.rstrip("\n").rstrip("\r")
                    accumulated_stdout.append(line)
                    if line.strip():
                        content_callback(line)
            except Exception as e:
                read_error = e

        reader = threading.Thread(target=_read_stdout, daemon=True)
        reader.start()

        # Write stdin
        try:
            proc.stdin.write(stdin_text)
            proc.stdin.close()
        except Exception:
            pass

        # Wait with timeout
        try:
            proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise RuntimeError(f"Claude Code CLI timeout after {self.timeout}s")

        reader.join(timeout=5)

        if read_error:
            raise RuntimeError(f"Stream read error: {read_error}")

        stderr_text = proc.stderr.read() if proc.stderr else ""

        if proc.returncode != 0:
            err = stderr_text or "\n".join(accumulated_stdout)
            if "error" in err.lower() and "tool" not in err.lower():
                raise RuntimeError(f"Claude CLI failed (exit {proc.returncode}): {err}")

        full_output = "\n".join(accumulated_stdout)
        content, usage = self._parse_output(full_output)
        if not content:
            content = stderr_text or full_output
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

    # ------------------------------------------------------------------
    # Two-step generation: think first → format JSON
    # Step 1: free-form analysis, Step 2: structured JSON output
    # ------------------------------------------------------------------

    def generate_think_then_json(
        self,
        prompt: str,
        *,
        role: str | None = None,
        progress_callback: callable | None = None,
        **kwargs,
    ) -> LLMResponse:
        model = kwargs.pop("model", self.model)

        # Step 1: ask Claude to think deeply, produce free-form analysis
        if progress_callback:
            progress_callback("LLM 分析中")
        think_prompt = prompt + "\n\n请先深入分析思考，输出详细的设计方案。用自然语言描述，不要输出 JSON。"
        cmd1 = [self.claude_cli_path, "-p", "-",
                 "--output-format", "json", "--model", model]
        t1_start = time.time()
        resp1 = self._invoke_cli_stdin(cmd1, think_prompt)
        t1 = time.time() - t1_start
        content1 = resp1.content.strip()

        # Step 2: feed the analysis back + JSON formatting instruction
        if progress_callback:
            progress_callback("LLM 生成 JSON")
        json_prompt = (
            f"原始任务:\n{prompt}\n\n"
            f"分析结果:\n{content1}\n\n"
            f"请将上述分析结果整理为指定的 JSON 结构输出。\n"
            f"只返回纯 JSON 对象，不要 markdown 代码块包裹，不要任何解释文字。"
        )
        cmd2 = [self.claude_cli_path, "-p", "-",
                 "--output-format", "json", "--model", model]
        t2_start = time.time()
        result = self._invoke_cli_stdin(cmd2, json_prompt)
        t2 = time.time() - t2_start
        label = {"pm": "PM", "architect": "架构", "design": "设计"}.get(role, role.upper() if role else "LLM")
        result.timings = [
            {"phase": f"{label}分析", "duration_s": round(t1, 1)},
            {"phase": f"{label}生成", "duration_s": round(t2, 1)},
        ]
        return result

    # ------------------------------------------------------------------
    # Interactive modification (via claude -p --session-id)
    # ------------------------------------------------------------------

    def generate_interactive(
        self,
        current_document: str,
        user_request: str,
        system_prompt: str = "",
        *,
        session_id: str = "",
        schema_path: str = "",
        **kwargs,
    ) -> LLMResponse:
        """Single-turn document modification via claude -p --session-id.

        Uses --json-schema for format enforcement and --session-id for
        conversation continuity across turns.
        """
        import uuid

        sid = session_id or str(uuid.uuid4())
        model = kwargs.get("model", self.model)

        prompt_text = (
            f"当前文档 JSON:\n{current_document}\n\n"
            f"用户修改要求: {user_request}\n\n"
            f"请根据用户要求修改文档，返回完整的修改后 JSON。"
        )

        cmd = [
            self.claude_cli_path, "-p", "-",
            "--session-id", sid,
            "--output-format", "json",
            "--model", model,
        ]

        if system_prompt:
            cmd.extend(["--append-system-prompt", system_prompt])

        if schema_path:
            cmd.extend(["--json-schema", schema_path])

        env = os.environ.copy()
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key

        try:
            result = subprocess.run(
                cmd, cwd=str(self.repo_path), check=False,
                capture_output=True, text=True, timeout=self.timeout,
                input=prompt_text, encoding="utf-8", env=env,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude Code CLI timeout during interactive modification")
        except FileNotFoundError:
            raise RuntimeError("Claude Code CLI not found.")

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"Claude CLI failed (exit {result.returncode}): {err[:200]}")

        content, usage = self._parse_output(result.stdout)
        if not content:
            content = result.stderr or result.stdout or ""
        if not content:
            raise RuntimeError("Claude Code CLI returned empty response during modification")

        # Store session_id so callers can reuse it
        self._last_session_id = sid

        return LLMResponse(
            content=content, model=model, provider="claude_code", usage=usage,
        )
