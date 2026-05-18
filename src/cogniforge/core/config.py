"""Configuration management for CogniForge"""

import os
from pathlib import Path
from pydantic import BaseModel, Field


class Config(BaseModel):
    """CogniForge configuration"""

    # Repository paths
    repo_path: Path = Field(default_factory=Path.cwd)
    wiki_path: Path = Field(default=Path(".cogniforge/wiki"))
    src_path: Path = Field(default=Path("src"))

    # Context loading
    context_global_patterns: list[str] = Field(
        default=[
            ".cogniforge/wiki/prd/*.html",
            ".cogniforge/wiki/sad/*.md",
            ".cogniforge/wiki/decisions/*.md",
        ]
    )
    context_module_patterns: list[str] = Field(
        default=[
            ".cogniforge/wiki/lld/{module}/*.md",
            "src/{module}/*.py",
        ]
    )
    context_task_patterns: list[str] = Field(
        default=[
            ".cogniforge/wiki/tasks/{task_id}.md",
        ]
    )

    # Execution settings
    max_workers: int = Field(default=4)
    default_timeout: int = Field(default=300)

    # LLM settings
    llm_provider: str = Field(default="claude_code")
    llm_model: str = Field(default="claude-sonnet-4-20250514")
    llm_api_key: str = Field(default="")
    llm_api_base: str = Field(default="")
    claude_cli_path: str = Field(default="claude")
    codex_cli_path: str = Field(default="codex")
    codex_approval_mode: str = Field(default="never")
    codex_sandbox: str = Field(default="read-only")
    codex_full_auto: bool = Field(default=False)

    # Git settings
    git_auto_commit: bool = Field(default=True)
    git_commit_message_prefix: str = Field(default="docs")

    def __init__(self, **data):
        # Load from environment variables if not provided
        if not data.get("llm_api_key"):
            data["llm_api_key"] = os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        if not data.get("llm_api_base"):
            data["llm_api_base"] = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
        if not data.get("llm_provider"):
            data["llm_provider"] = os.environ.get("LLM_PROVIDER", "claude_code")
        if not data.get("llm_model"):
            data["llm_model"] = os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")
        if not data.get("claude_cli_path"):
            data["claude_cli_path"] = os.environ.get("CLAUDE_CLI_PATH", "claude")
        if not data.get("codex_cli_path"):
            data["codex_cli_path"] = os.environ.get("CODEX_CLI_PATH", "codex")
        if not data.get("codex_approval_mode"):
            data["codex_approval_mode"] = os.environ.get("CODEX_APPROVAL_MODE", "never")
        if not data.get("codex_sandbox"):
            data["codex_sandbox"] = os.environ.get("CODEX_SANDBOX", "read-only")
        if "codex_full_auto" not in data:
            data["codex_full_auto"] = os.environ.get("CODEX_FULL_AUTO", "").lower() in {
                "1", "true", "yes", "on"
            }

        super().__init__(**data)

    def resolve_wiki_path(self, *parts: str) -> Path:
        """Resolve wiki file path"""
        return self.repo_path / self.wiki_path / "/".join(parts)

    def resolve_src_path(self, *parts: str) -> Path:
        """Resolve source file path"""
        return self.repo_path / self.src_path / "/".join(parts)

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        """Load config from file"""
        import yaml

        if not path.exists():
            return cls()

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls(**data)

    def to_file(self, path: Path) -> None:
        """Save config to file"""
        import yaml

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)
