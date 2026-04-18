"""Claude Code adapter - uses Claude Code as LLM backend"""

from typing import Optional

from cogniforge.llm.base import BaseLLMAdapter, LLMResponse, LLMMessage


class ClaudeCodeAdapter(BaseLLMAdapter):
    """
    Claude Code LLM adapter.

    Uses Claude Code (claude.ai/code) as the LLM backend.
    This adapter allows CogniForge to leverage Claude Code's capabilities.
    """

    def _setup(self) -> None:
        """Initialize Claude Code adapter"""
        self.model = self.config.get("model", "claude-sonnet-4-20250514")
        self.max_tokens = self.config.get("max_tokens", 4096)

    def generate(
        self,
        prompt: str,
        context: dict = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate response using Claude Code.

        Args:
            prompt: The prompt to send
            context: Additional context for the prompt
            **kwargs: Additional options

        Returns:
            LLMResponse with generated content
        """
        # Build enhanced prompt with context
        full_prompt = self._build_prompt(prompt, context)

        # Call Claude Code
        # Note: In actual implementation, this would use Claude Code's API
        # For now, this is a placeholder that simulates the response
        response_content = self._call_claude_code(full_prompt, **kwargs)

        return LLMResponse(
            content=response_content,
            model=self.model,
            provider="claude_code",
            usage={"input_tokens": len(full_prompt), "output_tokens": len(response_content)}
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
        # Convert messages to prompt format
        prompt = self._messages_to_prompt(messages)

        return self.generate(prompt, **kwargs)

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

    def _call_claude_code(self, prompt: str, **kwargs) -> str:
        """
        Call Claude Code API.

        Note: This is a placeholder. Actual implementation would
        use Claude Code's API or CLI interface.
        """
        # In real implementation:
        # 1. Use Claude Code API
        # 2. Or spawn claude CLI process
        # 3. Return response

        # Placeholder response
        return f"[Claude Code Response] Generated content for prompt: {prompt[:100]}..."

    def _messages_to_prompt(self, messages: list[LLMMessage]) -> str:
        """Convert message history to prompt string"""
        lines = []
        for msg in messages:
            lines.append(f"\n{msg.role.upper()}: {msg.content}\n")
        return "\n".join(lines)

    @property
    def provider_name(self) -> str:
        return "Claude Code"

    @property
    def supported_models(self) -> list[str]:
        return [
            "claude-opus-4-5",
            "claude-sonnet-4-20250514",
            "claude-haiku-4-5",
        ]
