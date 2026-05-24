"""LLM Adapter - abstraction layer for LLM providers

This module provides an adapter interface that supports multiple LLM providers:
- Claude Code (claude_code)
- Codex CLI (open_code)
- Codex CLI (codex) - legacy alias for open_code

All agents use this interface to interact with LLMs, ensuring:
- Provider agnostic code
- Easy switching between providers
- Consistent interface
"""

from abc import ABC, abstractmethod
from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum


class LLMProvider(str, Enum):
    """Supported LLM providers"""
    CLAUDE_CODE = "claude_code"
    OPEN_CODE = "open_code"
    CODEX = "codex"  # Legacy alias, maps to open_code
    DEEPSEEK = "deepseek"


@dataclass
class LLMResponse:
    """Response from LLM"""
    content: str
    model: str
    provider: str
    usage: dict = None
    cost: float = 0.0
    timings: list = None  # [{"phase": "...", "duration_s": float}]


@dataclass
class LLMMessage:
    """Message for LLM"""
    role: str  # "user", "assistant", "system"
    content: str


class BaseLLMAdapter(ABC):
    """
    Base class for LLM adapters.

    All LLM implementations must implement this interface.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._setup()

    @abstractmethod
    def _setup(self) -> None:
        """Initialize the adapter"""
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        context: dict = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate response from LLM.

        Args:
            prompt: The prompt to send
            context: Additional context (optional)
            **kwargs: Provider-specific options

        Returns:
            LLMResponse with content and metadata
        """
        pass

    @abstractmethod
    def generate_messages(
        self,
        messages: list[LLMMessage],
        **kwargs
    ) -> LLMResponse:
        """
        Generate response using message history.

        Args:
            messages: List of conversation messages
            **kwargs: Provider-specific options

        Returns:
            LLMResponse with content and metadata
        """
        pass

    @abstractmethod
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
        """Agent mode with tool use — the LLM reads/writes files and runs commands.

        Args:
            prompt: The task prompt.
            role: Optional role name for system-prompt injection.
            tools: Optional list of tool definitions (adapter defaults if None).
            max_turns: Maximum tool-use round-trips.
            progress_callback: Optional callback(status: str) for progress display.
            **kwargs: Provider-specific options (model, max_tokens, etc.).

        Returns:
            LLMResponse with content and metadata.
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return provider name"""
        pass

    @property
    @abstractmethod
    def supported_models(self) -> list[str]:
        """Return list of supported models"""
        pass

    def generate_interactive(
        self,
        current_document: str,
        user_request: str,
        system_prompt: str = "",
        **kwargs,
    ) -> LLMResponse:
        """Single-turn document modification.

        Default implementation uses generate_messages.  Adapters may override
        for provider-specific behaviour (e.g. Claude Code uses --session-id).

        Args:
            current_document: The current document JSON text.
            user_request: The user's modification request.
            system_prompt: Optional system prompt for the modification.
            **kwargs: Provider-specific options.

        Returns:
            LLMResponse with the modified document content.
        """
        messages = []
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))
        messages.append(LLMMessage(
            role="user",
            content=(
                f"当前文档 JSON:\n{current_document}\n\n"
                f"用户修改要求: {user_request}\n\n"
                f"请根据用户要求修改文档，返回完整的修改后 JSON。\n"
                f"只返回纯 JSON，不要 markdown 代码块包裹，不要多余解释文字。"
            ),
        ))
        return self.generate_messages(messages, **kwargs)

    def generate_interactive_patch(
        self,
        current_document: str,
        user_request: str,
        system_prompt: str = "",
        turn_schema: dict | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Produce a structured turn result with patches instead of full replacement.

        Default implementation falls back to generate_interactive and wraps the
        result into a minimal turn structure.  Adapters with native two-step
        support (e.g. DeepSeekAdapter) should override this.

        Args:
            current_document: The current document JSON text.
            user_request: The user's modification request.
            system_prompt: Optional system prompt for the modification.
            turn_schema: The pm-turn-result JSON schema dict for structured output.
            **kwargs: Provider-specific options.

        Returns:
            LLMResponse whose content is the pm-turn-result JSON string.
        """
        import json as _json
        full_result = self.generate_interactive(
            current_document=current_document,
            user_request=user_request,
            system_prompt=system_prompt,
            **kwargs,
        )
        try:
            parsed = _json.loads(full_result.content)
            patches = [{"op": "replace", "path": "", "value": parsed}]
            turn_result = {
                "status": "updated",
                "operation": "modify",
                "doc_changed": "prd",
                "changed_file": "docs/prd.json",
                "affected_requirements": [],
                "conflicts": [],
                "message": "Document updated via fallback (full replace).",
                "open_questions": [],
                "patches": patches,
            }
            return LLMResponse(
                content=_json.dumps(turn_result, ensure_ascii=False),
                model=full_result.model,
                provider=full_result.provider,
                usage=full_result.usage,
            )
        except (_json.JSONDecodeError, Exception):
            return full_result


def create_llm_adapter(
    provider: LLMProvider,
    config: dict = None
) -> BaseLLMAdapter:
    """
    Factory function to create LLM adapter.

    Args:
        provider: The LLM provider to use
        config: Provider-specific configuration

    Returns:
        BaseLLMAdapter implementation
    """
    if provider == LLMProvider.CLAUDE_CODE:
        from cogniforge.llm.claude_code_adapter import ClaudeCodeAdapter
        return ClaudeCodeAdapter(config)
    elif provider == LLMProvider.OPEN_CODE:
        from cogniforge.llm.open_code_adapter import OpenCodeAdapter
        return OpenCodeAdapter(config)
    elif provider == LLMProvider.CODEX:
        # codex is a legacy provider name, map it to the Codex CLI adapter
        from cogniforge.llm.open_code_adapter import OpenCodeAdapter
        return OpenCodeAdapter(config)
    elif provider == LLMProvider.DEEPSEEK:
        from cogniforge.llm.deepseek_adapter import DeepSeekAdapter
        return DeepSeekAdapter(config)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
