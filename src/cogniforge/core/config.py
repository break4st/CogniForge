"""Configuration management for CogniForge"""

import os
from pathlib import Path
from typing import Optional, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Default config template (written to .cogniforge/config.yaml on first run)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_YAML = """\
# ============================================================
# CogniForge 统一配置
# ============================================================

# ----- LLM 类 provider（API 直调） -----
llm:
  deepseek:
    api_key: ""                     # 填写你的 API key
    api_base: "https://api.deepseek.com/v1"
    model: "deepseek-v4-pro"
    max_tokens: 4096

# ----- AGENT 类 provider（CLI 工具） -----
agent:
  claude_code:
    model: "claude-sonnet-4-20250514"
    # cli_path: "claude"           # 可选，默认 "claude"

  # open_code:                     # 可选，按需启用
  #   model: "gpt-5.4"
  #   cli_path: "codex"

# ----- 角色 → provider 分配 -----
# 格式: 角色名: 类型.provider名
# 未列出的角色默认使用 agent.claude_code
roles:
  pm: llm.deepseek                # PM（PRD生成）
  architect: llm.deepseek         # Architect（系统架构）
  design: llm.deepseek            # Design（详细设计）
  techlead: llm.deepseek          # Tech Lead（WBS任务分解）
  # dev: agent.claude_code        # Dev（编码+测试，推荐 AGENT）
  # reviewer: agent.claude_code   # Reviewer（代码评审）
  # qa: agent.claude_code         # QA（测试用例+报告）
  # devops: agent.claude_code     # DevOps（部署，推荐 AGENT）
"""

# Roles that strongly prefer AGENT-type providers
AGENT_RECOMMENDED_ROLES = {"dev", "devops"}

# Default role → provider mapping (used when roles section is absent)
DEFAULT_ROLE_PROVIDERS = {
    "pm": "llm.deepseek",
    "architect": "llm.deepseek",
    "design": "llm.deepseek",
    "techlead": "llm.deepseek",
}


class Config(BaseModel):
    """CogniForge configuration.

    On first load, if .cogniforge/config.yaml doesn't exist, a template is
    generated automatically.  All settings live in one file.
    """

    # Repository paths
    repo_path: Path = Field(default_factory=Path.cwd)
    wiki_path: Path = Field(default=Path(".cogniforge/wiki"))
    src_path: Path = Field(default=Path("src"))

    # Context loading
    context_global_patterns: list[str] = Field(
        default=[
            ".cogniforge/wiki/prd/*.json",
            ".cogniforge/wiki/sad/*.json",
            ".cogniforge/wiki/decisions/*.json",
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
    max_workers: int = Field(default=10)
    default_timeout: int = Field(default=300)

    # ── LLM providers (API direct call) ──
    llm: dict[str, dict] = Field(
        default_factory=lambda: {
            "deepseek": {
                "api_key": "",
                "api_base": "https://api.deepseek.com/v1",
                "model": "deepseek-v4-pro",
                "max_tokens": 4096,
            }
        }
    )

    # ── AGENT providers (CLI-based) ──
    agent: dict[str, dict] = Field(
        default_factory=lambda: {
            "claude_code": {
                "model": "claude-sonnet-4-20250514",
                "cli_path": "claude",
            }
        }
    )

    # ── Role → provider mapping ──
    roles: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_ROLE_PROVIDERS)
    )

    # ── Legacy fields (kept for backward compatibility) ──
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, **data):
        self._apply_env_fallbacks(data)
        super().__init__(**data)

    @staticmethod
    def _apply_env_fallbacks(data: dict) -> None:
        """Apply environment variable fallbacks for legacy single-provider fields."""
        if not data.get("llm_api_key"):
            data["llm_api_key"] = (
                os.environ.get("DEEPSEEK_API_KEY")
                or os.environ.get("CODEX_API_KEY")
                or os.environ.get("OPENAI_API_KEY", "")
            )
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

    # ------------------------------------------------------------------
    # Factory: load from .cogniforge/config.yaml (auto-generate if missing)
    # ------------------------------------------------------------------

    @classmethod
    def from_cogniforge_config(cls, repo_path: Path) -> "Config":
        """Load config from .cogniforge/config.yaml, auto-generating on first run.

        Returns a Config instance.  Validation warnings/errors are printed to
        stderr; errors raise SystemExit(1).
        """
        config_path = repo_path / ".cogniforge" / "config.yaml"

        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
            import click
            click.echo(
                f"  [config] 已生成默认配置文件: {config_path.relative_to(repo_path)}\n"
                f"           请编辑此文件填写 API key 等必要信息后重新运行。"
            )

        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # Merge env var fallbacks for LLM provider api_keys
        for name, cfg in raw.get("llm", {}).items():
            if isinstance(cfg, dict) and not cfg.get("api_key"):
                env_key = os.environ.get("DEEPSEEK_API_KEY", "")
                if env_key:
                    cfg["api_key"] = env_key

        # Build legacy fields from new config for backward compat
        legacy = cls._derive_legacy_fields(raw, repo_path)

        instance = cls(repo_path=repo_path, **raw, **legacy)
        cls._validate_and_warn(instance, raw)
        return instance

    @staticmethod
    def _derive_legacy_fields(raw: dict, repo_path: Path) -> dict:
        """Derive legacy single-provider fields from new config structure."""
        legacy: dict[str, Any] = {}

        # Default role is the first one listed, or pm → llm.deepseek
        roles = raw.get("roles", DEFAULT_ROLE_PROVIDERS)
        default_role_key = list(roles.keys())[0] if roles else "pm"
        default_provider_ref = roles.get(default_role_key, "agent.claude_code")

        # llm_provider: if first role uses an LLM, set that
        if default_provider_ref.startswith("agent."):
            legacy["llm_provider"] = default_provider_ref.replace("agent.", "")
        else:
            legacy["llm_provider"] = default_provider_ref.split(".", 1)[1] if "." in default_provider_ref else default_provider_ref

        return legacy

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_and_warn(config: "Config", raw: dict) -> None:
        """Validate config and print errors/warnings.  Raises SystemExit on errors."""
        import click

        errors: list[str] = []
        warnings: list[str] = []

        # --- Check LLM providers ---
        for name, cfg in config.llm.items():
            api_key = cfg.get("api_key", "") if isinstance(cfg, dict) else ""
            if not api_key:
                env_key = os.environ.get("DEEPSEEK_API_KEY", "")
                if env_key:
                    if isinstance(cfg, dict):
                        cfg["api_key"] = env_key
                # Only error if a role actually references this provider
                ref = f"llm.{name}"
                if any(r == ref for r in config.roles.values()):
                    errors.append(
                        f"LLM provider '{name}' 缺少 api_key，"
                        f"但角色已配置使用它。\n"
                        f"    请在 .cogniforge/config.yaml 的 llm.{name}.api_key 中填写，"
                        f"或设置环境变量 DEEPSEEK_API_KEY"
                    )
                else:
                    if not api_key:
                        warnings.append(
                            f"LLM provider '{name}' 缺少 api_key（无角色使用，已忽略）"
                        )

        # --- Check AGENT providers ---
        for name, cfg in config.agent.items():
            cli_path = (cfg.get("cli_path", name) if isinstance(cfg, dict) else name)
            if name == "claude_code":
                cli_path = cfg.get("cli_path", "claude") if isinstance(cfg, dict) else "claude"
                import shutil
                if not shutil.which(cli_path):
                    ref = f"agent.{name}"
                    if any(r == ref for r in config.roles.values()):
                        errors.append(
                            f"AGENT provider '{name}' 需要 Claude Code CLI，"
                            f"但未在 PATH 中找到 '{cli_path}'。\n"
                            f"    安装: npm i -g @anthropic-ai/claude-code"
                        )
                    else:
                        warnings.append(
                            f"AGENT provider '{name}' 的 CLI 未找到（无角色使用，已忽略）"
                        )

        # --- Check role → provider references exist ---
        for role_name, ref in config.roles.items():
            type_name, _, provider_name = ref.partition(".")
            if type_name == "llm":
                if provider_name not in config.llm:
                    errors.append(
                        f"角色 '{role_name}' 引用了不存在的 LLM provider "
                        f"'{provider_name}'。\n"
                        f"    请在 .cogniforge/config.yaml 的 llm 段中定义它"
                    )
            elif type_name == "agent":
                if provider_name not in config.agent:
                    errors.append(
                        f"角色 '{role_name}' 引用了不存在的 AGENT provider "
                        f"'{provider_name}'。\n"
                        f"    请在 .cogniforge/config.yaml 的 agent 段中定义它"
                    )
            else:
                errors.append(
                    f"角色 '{role_name}' 的 provider 引用格式无效: '{ref}'。\n"
                    f"    格式应为: llm.<name> 或 agent.<name>"
                )

        # --- Role-type compatibility warnings ---
        for role_name in AGENT_RECOMMENDED_ROLES:
            ref = config.roles.get(role_name, "")
            if ref.startswith("llm."):
                warnings.append(
                    f"角色 '{role_name}' 配置为 {ref}，但该角色涉及大量命令行操作"
                    f"（pytest/git），建议使用 agent 类 provider。将继续运行，但可能不稳定。"
                )

        # --- LLM available? ---
        has_llm = any(
            (cfg.get("api_key", "") if isinstance(cfg, dict) else False)
            for cfg in config.llm.values()
        )
        if not has_llm and config.llm:
            warnings.append(
                "未检测到任何 LLM provider 的有效 api_key，NL→JSON 解析将回退到 AGENT provider。"
            )

        # --- Print warnings ---
        for w in warnings:
            click.echo(f"  [WARN] {w}")

        # --- Print errors and abort ---
        if errors:
            for e in errors:
                click.echo(f"  [ERROR] {e}")
            raise SystemExit(1)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def resolve_wiki_path(self, *parts: str) -> Path:
        """Resolve wiki file path"""
        return self.repo_path / self.wiki_path / "/".join(parts)

    def resolve_src_path(self, *parts: str) -> Path:
        """Resolve source file path"""
        return self.repo_path / self.src_path / "/".join(parts)

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        """Load config from an arbitrary YAML file (legacy path)."""
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
