"""Open Code adapter - uses the official Codex CLI in non-interactive mode."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from cogniforge.llm.base import BaseLLMAdapter, LLMResponse, LLMMessage


class OpenCodeAdapter(BaseLLMAdapter):
    """
    Open Code LLM adapter.

    Uses the official Codex CLI as the LLM backend.
    This follows the documented `codex exec` non-interactive workflow.
    """

    def _setup(self) -> None:
        """Initialize Codex CLI adapter settings."""
        self.model = self.config.get("model", "gpt-5.4")
        self.api_key = self.config.get("api_key", "")
        self.repo_path = Path(self.config.get("repo_path", Path.cwd()))
        self.codex_cli_path = self._resolve_codex_cli_path(
            self.config.get("codex_cli_path", "codex")
        )
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.timeout = self.config.get("timeout", 60)
        self.approval_mode = self.config.get("approval_mode", "never")
        self.sandbox = self.config.get("sandbox", "read-only")
        self.full_auto = self.config.get("full_auto", False)

    def generate(
        self,
        prompt: str,
        context: dict = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate response using `codex exec`.

        Args:
            prompt: The prompt to send
            context: Additional context for the prompt
            **kwargs: Additional CLI-oriented options

        Returns:
            LLMResponse with generated content
        """
        full_prompt = self._build_prompt(prompt, context)
        content, usage = self._run_codex_exec(
            prompt=full_prompt,
            model=kwargs.get("model", self.model),
            approval_mode=kwargs.get("approval_mode", self.approval_mode),
            sandbox=kwargs.get("sandbox", self.sandbox),
            full_auto=kwargs.get("full_auto", self.full_auto),
        )

        return LLMResponse(
            content=content,
            model=kwargs.get("model", self.model),
            provider="open_code",
            usage=usage
        )

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
        """Agent mode via ``codex exec --full-auto``."""
        if progress_callback:
            progress_callback("通过 Codex CLI 执行中...")
        full_prompt = prompt
        if role:
            full_prompt = f"# Role: {role}\n\n{full_prompt}"
        full_prompt += f"\n\n工作目录: {self.repo_path}\n完成后用中文回复。"

        content, usage = self._run_codex_exec(
            prompt=full_prompt,
            model=kwargs.get("model", self.model),
            approval_mode="never",
            sandbox="read-only",
            full_auto=True,
        )
        return LLMResponse(
            content=content,
            model=kwargs.get("model", self.model),
            provider="open_code",
            usage=usage,
        )

    def generate_messages(
        self,
        messages: list[LLMMessage],
        **kwargs
    ) -> LLMResponse:
        """
        Generate response using message history.

        Args:
            messages: Conversation history
            **kwargs: Additional options

        Returns:
            LLMResponse with generated content
        """
        prompt = self._messages_to_prompt(messages)
        return self.generate(prompt=prompt, **kwargs)

    def _build_prompt(self, prompt: str, context: dict = None) -> str:
        """Build enhanced prompt with context"""
        if not context:
            return prompt

        context_lines = ["# Context\n"]

        for key, value in context.items():
            if isinstance(value, dict):
                context_lines.append(f"\n## {key}")
                for k, v in value.items():
                    context_lines.append(f"- {k}: {v}")
            elif isinstance(value, list):
                context_lines.append(f"\n## {key}")
                for item in value:
                    context_lines.append(f"- {item}")
            else:
                context_lines.append(f"- {key}: {value}")

        context_lines.append(f"\n# Prompt\n{prompt}")

        return "\n".join(context_lines)

    def _messages_to_prompt(self, messages: list[LLMMessage]) -> str:
        """Convert message history to a transcript-style prompt."""
        lines: list[str] = []
        for msg in messages:
            lines.append(f"{msg.role.upper()}:")
            lines.append(msg.content)
            lines.append("")
        return "\n".join(lines).strip()

    def _run_codex_exec(
        self,
        prompt: str,
        *,
        model: str,
        approval_mode: str,
        sandbox: str,
        full_auto: bool,
    ) -> tuple[str, dict]:
        """Run `codex exec` and return the last assistant message plus usage."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".txt",
            delete=False,
        ) as output_file:
            output_path = Path(output_file.name)

        command = self._build_command(
            prompt=prompt,
            output_path=output_path,
            model=model,
            approval_mode=approval_mode,
            sandbox=sandbox,
            full_auto=full_auto,
        )
        env = self._build_env()

        try:
            result = self._run_command(command, env)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Codex CLI not found. Install it first and make sure the `codex` command is on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Codex CLI timeout after {self.timeout}s") from exc

        if self._should_retry_without_approval_flag(result):
            command = self._build_command(
                prompt=prompt,
                output_path=output_path,
                model=model,
                approval_mode=None,
                sandbox=sandbox,
                full_auto=full_auto,
            )
            result = self._run_command(command, env)

        try:
            content = output_path.read_text(encoding="utf-8").strip()
        finally:
            output_path.unlink(missing_ok=True)

        if result.returncode != 0:
            error_message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"Codex CLI failed with exit code {result.returncode}: {error_message}")

        if not content:
            raise RuntimeError("Codex CLI returned no final assistant message")

        return content, self._extract_usage(result.stdout)

    def _build_command(
        self,
        *,
        prompt: str,
        output_path: Path,
        model: str,
        approval_mode: str | None,
        sandbox: str,
        full_auto: bool,
    ) -> list[str]:
        """Build a non-interactive `codex exec` command."""
        command = [self.codex_cli_path, "exec"]

        if full_auto:
            command.append("--full-auto")
        else:
            if approval_mode:
                command.extend(["--ask-for-approval", approval_mode])
            command.extend(["--sandbox", sandbox])

        if model:
            command.extend(["--model", model])

        command.extend([
            "--json",
            "--output-last-message",
            str(output_path),
            prompt,
        ])
        return command

    def _build_env(self) -> dict[str, str]:
        """Build the environment for Codex CLI execution."""
        env = os.environ.copy()
        api_key = self.api_key or env.get("CODEX_API_KEY") or env.get("OPENAI_API_KEY", "")
        if api_key:
            env["CODEX_API_KEY"] = api_key
            env.setdefault("OPENAI_API_KEY", api_key)
        return env

    def _run_command(self, command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        """Execute the Codex CLI command."""
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(self.repo_path),
            timeout=self.timeout,
            env=env,
            check=False,
        )

    def _should_retry_without_approval_flag(self, result: subprocess.CompletedProcess[str]) -> bool:
        """Detect older Codex exec versions that do not accept approval flags."""
        stderr = result.stderr or ""
        return result.returncode == 2 and "--ask-for-approval" in stderr and "unexpected argument" in stderr

    def _resolve_codex_cli_path(self, cli_path: str) -> str:
        """Resolve a Windows-safe Codex executable path when possible."""
        if os.name != "nt":
            return cli_path

        candidates = [cli_path]
        if cli_path == "codex":
            candidates = ["codex.cmd", "codex.exe", "codex"]

        for candidate in candidates:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

        return cli_path

    def _extract_usage(self, stdout: str) -> dict:
        """Extract usage metadata from Codex CLI JSONL output when available."""
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

        for line in stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_usage = event.get("usage")
            if not isinstance(event_usage, dict):
                continue

            usage["input_tokens"] = (
                event_usage.get("input_tokens")
                or event_usage.get("prompt_tokens")
                or usage["input_tokens"]
            )
            usage["output_tokens"] = (
                event_usage.get("output_tokens")
                or event_usage.get("completion_tokens")
                or usage["output_tokens"]
            )
            usage["total_tokens"] = (
                event_usage.get("total_tokens")
                or usage["input_tokens"] + usage["output_tokens"]
            )

        return usage

    @property
    def provider_name(self) -> str:
        return "Codex CLI"

    @property
    def supported_models(self) -> list[str]:
        return [
            "gpt-5.4",
            "gpt-5.3-codex",
            "gpt-5.4-mini",
        ]
