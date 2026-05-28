"""CogniForge Service Layer.

Shared by CLI and RPC server. Each service wraps one domain and returns
JSON-safe dicts. No terminal I/O, no Click dependency.
"""

from __future__ import annotations

from pathlib import Path

from cogniforge.core.config import Config
from cogniforge.core.constants import AgentRole
from cogniforge.storage.git_storage import GitStorage
from cogniforge.context.context_loader import ContextLoader
from cogniforge.wiki.wiki_system import WikiSystem
from cogniforge.task_engine.task_engine import TaskEngine
from cogniforge.task_engine.dag import DAGDefinition
from cogniforge.orchestration.workflow import Workflow
from cogniforge.agents.pm_agent import PMAgent
from cogniforge.agents.architect_agent import ArchitectAgent
from cogniforge.agents.design_agent import DesignAgent
from cogniforge.agents.techlead_agent import TechLeadAgent
from cogniforge.agents.dev_agent import DevAgent
from cogniforge.agents.review_agent import ReviewAgent
from cogniforge.agents.qa_agent import QAAgent
from cogniforge.agents.devops_agent import DevOpsAgent
from cogniforge.constraints import ConstraintLoader

from cogniforge.services.agent_service import AgentService
from cogniforge.services.workflow_service import WorkflowService
from cogniforge.services.project_service import ProjectService
from cogniforge.services.wiki_service import WikiService


def _build_providers(config: Config) -> dict[str, object]:
    """Create provider adapter instances from config.

    Returns a dict keyed by 'llm.<name>' and 'agent.<name>'.
    """
    from cogniforge.llm.base import LLMProvider, create_llm_adapter

    constraint_loader = ConstraintLoader(config.repo_path)
    providers: dict[str, object] = {}

    # LLM providers (API direct call)
    for name, cfg in config.llm.items():
        if not isinstance(cfg, dict):
            continue
        adapter = create_llm_adapter(
            LLMProvider.DEEPSEEK,
            config={
                "api_key": cfg.get("api_key", ""),
                "api_base": cfg.get("api_base", "https://api.deepseek.com/beta"),
                "model": cfg.get("model", "deepseek-v4-pro"),
                "max_tokens": cfg.get("max_tokens", 4096),
                "repo_path": str(config.repo_path),
                "constraint_loader": constraint_loader,
            },
        )
        providers[f"llm.{name}"] = adapter

    # AGENT providers (CLI-based)
    for name, cfg in config.agent.items():
        if not isinstance(cfg, dict):
            continue
        try:
            provider_enum = LLMProvider(name)
        except ValueError:
            provider_enum = LLMProvider.CLAUDE_CODE

        adapter_config: dict = {
            "model": cfg.get("model", "claude-sonnet-4-20250514"),
            "repo_path": str(config.repo_path),
            "constraint_loader": constraint_loader,
        }
        if name == "claude_code":
            adapter_config["claude_cli_path"] = cfg.get("cli_path", "claude")
        elif name == "open_code":
            adapter_config["codex_cli_path"] = cfg.get("cli_path", "codex")

        adapter = create_llm_adapter(provider_enum, config=adapter_config)
        providers[f"agent.{name}"] = adapter

    return providers


def _resolve_provider(role: str, config: Config, providers: dict) -> object:
    """Resolve the adapter for a given agent role."""
    default_ref = "agent.claude_code"
    ref = config.roles.get(role, default_ref)
    if ref in providers:
        return providers[ref]
    if default_ref in providers:
        return providers[default_ref]
    return next(iter(providers.values()))


def _ensure_githooks(repo_path: Path) -> None:
    """Activate project githooks silently."""
    hooks_path = repo_path / ".githooks"
    if not hooks_path.is_dir():
        return
    try:
        import subprocess
        result = subprocess.run(
            ["git", "config", "--local", "core.hooksPath"],
            cwd=str(repo_path), capture_output=True, text=True,
        )
        if result.stdout.strip() != ".githooks":
            subprocess.run(
                ["git", "config", "--local", "core.hooksPath", ".githooks"],
                cwd=str(repo_path), capture_output=True,
            )
    except Exception:
        pass


def build_services(repo_path: Path) -> dict:
    """Initialize the full CogniForge context and return a dict of objects.

    Returns:
        {"config": Config, "git_storage": GitStorage,
         "wiki_system": WikiSystem, "context_loader": ContextLoader,
         "task_engine": TaskEngine, "workflow": Workflow,
         "agents": dict[str, BaseAgent], "_providers": dict}
    """
    config = Config.from_cogniforge_config(repo_path)
    _ensure_githooks(config.repo_path)

    git_storage = GitStorage(config.repo_path)
    wiki_system = WikiSystem(config, git_storage)
    context_loader = ContextLoader(config)
    task_engine = TaskEngine(config, git_storage)
    workflow = Workflow(DAGDefinition(), repo_path=config.repo_path)

    providers = _build_providers(config)

    agents = {
        AgentRole.PM.value: PMAgent(
            AgentRole.PM, wiki_system, context_loader, config,
            agent=_resolve_provider("pm", config, providers),
        ),
        AgentRole.ARCHITECT.value: ArchitectAgent(
            AgentRole.ARCHITECT, wiki_system, context_loader, config,
            agent=_resolve_provider("architect", config, providers),
        ),
        AgentRole.DESIGN.value: DesignAgent(
            AgentRole.DESIGN, wiki_system, context_loader, config,
            agent=_resolve_provider("design", config, providers),
        ),
        AgentRole.TECHLEAD.value: TechLeadAgent(
            AgentRole.TECHLEAD, wiki_system, context_loader, config,
            task_engine=task_engine,
            agent=_resolve_provider("techlead", config, providers),
        ),
        AgentRole.DEV.value: DevAgent(
            AgentRole.DEV, wiki_system, context_loader, config,
            agent=_resolve_provider("dev", config, providers),
        ),
        AgentRole.REVIEWER.value: ReviewAgent(
            AgentRole.REVIEWER, wiki_system, context_loader, config,
            agent=_resolve_provider("reviewer", config, providers),
        ),
        AgentRole.QA.value: QAAgent(
            AgentRole.QA, wiki_system, context_loader, config,
            agent=_resolve_provider("qa", config, providers),
        ),
        AgentRole.DEVOPS.value: DevOpsAgent(
            AgentRole.DEVOPS, wiki_system, context_loader, config,
            agent=_resolve_provider("devops", config, providers),
        ),
    }

    return {
        "config": config,
        "git_storage": git_storage,
        "wiki_system": wiki_system,
        "context_loader": context_loader,
        "task_engine": task_engine,
        "workflow": workflow,
        "agents": agents,
        "_providers": providers,
    }
