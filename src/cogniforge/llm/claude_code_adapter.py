"""Claude Code adapter - uses the Claude Code CLI in non-interactive mode."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from cogniforge.llm.base import BaseLLMAdapter, LLMResponse, LLMMessage


class ClaudeCodeAdapter(BaseLLMAdapter):
    """
    Claude Code LLM adapter.

    Uses the Claude Code CLI (`claude`) as the LLM backend.
    Invokes `claude -p` (print mode) for non-interactive generation.
    """

    def _setup(self) -> None:
        """Initialize Claude Code adapter settings."""
        self.model = self.config.get("model", "claude-sonnet-4-20250514")
        self.api_key = self.config.get("api_key", "")
        self.repo_path = Path(self.config.get("repo_path", Path.cwd()))
        self.claude_cli_path = self._resolve_claude_cli_path(
            self.config.get("claude_cli_path", "claude")
        )
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.timeout = self.config.get("timeout", 300)

    def generate(
        self,
        prompt: str,
        context: dict = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate response using `claude -p`.

        Args:
            prompt: The prompt to send
            context: Additional context for the prompt
            **kwargs: Additional CLI-oriented options

        Returns:
            LLMResponse with generated content
        """
        full_prompt = self._build_prompt(prompt, context)
        content, usage = self._call_claude_code(
            prompt=full_prompt,
            model=kwargs.get("model", self.model),
        )

        return LLMResponse(
            content=content,
            model=kwargs.get("model", self.model),
            provider="claude_code",
            usage=usage
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

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, prompt: str, context: dict = None) -> str:
        """Build enhanced prompt with context."""
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

    # ------------------------------------------------------------------
    # Claude CLI execution
    # ------------------------------------------------------------------

    def _call_claude_code(
        self,
        prompt: str,
        *,
        model: str,
    ) -> tuple[str, dict]:
        """Run `claude -p` and return the response text plus usage."""
        command = self._build_command(prompt=prompt, model=model)
        env = self._build_env()

        try:
            result = self._run_command(command, env)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Claude Code CLI not found. Install it first and make sure the "
                "`claude` command is on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Claude Code CLI timeout after {self.timeout}s"
            ) from exc

        if result.returncode != 0:
            error_message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"Claude Code CLI failed with exit code {result.returncode}: "
                f"{error_message}"
            )

        content, usage = self._parse_output(result.stdout)
        if not content:
            raise RuntimeError("Claude Code CLI returned empty response")

        return content, usage

    def _build_command(
        self,
        *,
        prompt: str,
        model: str,
    ) -> list[str]:
        """Build a non-interactive `claude -p` command."""
        command = [
            self.claude_cli_path,
            "-p", prompt,
            "--output-format", "json",
        ]

        if model:
            command.extend(["--model", model])

        return command

    def _build_env(self) -> dict[str, str]:
        """Build the environment for Claude Code CLI execution."""
        env = os.environ.copy()
        api_key = self.api_key or env.get("ANTHROPIC_API_KEY", "")
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
        return env

    def _run_command(
        self, command: list[str], env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        """Execute the Claude Code CLI command."""
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(self.repo_path),
            timeout=self.timeout,
            env=env,
            check=False,
        )

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def _parse_output(self, stdout: str) -> tuple[str, dict]:
        """
        Parse Claude Code JSON output.

        With --output-format json, stdout is a JSON object:
            {"result": "...", "usage": {"input_tokens": N, "output_tokens": N}}

        Falls back to treating stdout as plain text if JSON parsing fails.
        """
        usage: dict = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

        stdout = stdout.strip()
        if not stdout:
            return "", usage

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            # Not JSON — treat the whole stdout as the response text
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
    # CLI path resolution
    # ------------------------------------------------------------------

    def _resolve_claude_cli_path(self, cli_path: str) -> str:
        """Resolve a Windows-safe Claude CLI executable path when possible."""
        if os.name != "nt":
            return cli_path

        candidates = [cli_path]
        if cli_path == "claude":
            candidates = ["claude.cmd", "claude.exe", "claude"]

        for candidate in candidates:
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
