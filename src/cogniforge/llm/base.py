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


@dataclass
class LLMResponse:
    """Response from LLM"""
    content: str
    model: str
    provider: str
    usage: dict = None
    cost: float = 0.0


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
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
