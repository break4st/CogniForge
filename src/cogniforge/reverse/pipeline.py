"""逆向工程管线编排 — 6 阶段：扫描→模块发现→SAD→PRD→LLD→Workflow 引导。

持久化状态到 ``.cogniforge/reverse_engineer_state.json``，支持中断恢复。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

import click

from cogniforge.core.config import Config
from cogniforge.core.constants import AgentRole, DocumentType, ModuleType
from cogniforge.orchestration.workflow import Workflow
from cogniforge.task_engine.dag import DAGStep, DAGDefinition
from cogniforge.wiki.wiki_system import WikiSystem
from cogniforge.storage.git_storage import GitStorage
from cogniforge.reverse.scanner import scan_project

C_PURPLE = "\033[35m"
C_GREEN = "\033[32m"
C_DIM = "\033[2m"
C_RESET = "\033[0m"


# ---------------------------------------------------------------------------
# 状态持久化
# ---------------------------------------------------------------------------

@dataclass
class ReverseEngineerState:
    """逆向工程进度状态。"""
    version: str = "1.0"
    target_path: str = ""
    phase: str = "init"
    manifest_ready: bool = False
    module_map_confirmed: bool = False
    sad_generated: bool = False
    prd_generated: bool = False
    lld_completed_modules: list[str] = field(default_factory=list)
    lld_total_modules: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at


# ---------------------------------------------------------------------------
# 管线
# ---------------------------------------------------------------------------

class ReversePipeline:
    """逆向工程管线编排器。"""

    STATE_FILE = ".cogniforge/reverse_engineer_state.json"

    def __init__(
        self,
        target_path: Path,
        config: Config,
        agents: dict[str, object],
        auto_approve: bool = False,
    ):
        self.target_path = target_path.resolve()
        self.config = config
        self.agents = agents
        self.auto_approve = auto_approve
        self.state = ReverseEngineerState(target_path=str(self.target_path))
        self._manifest: dict | None = None
        self._module_map: list[dict] | None = None
        self._sad: dict | None = None
        self._prd: dict | None = None

        # 为目标路径初始化 wiki system
        self._target_git = GitStorage(self.target_path)
        self._target_wiki = WikiSystem(
            Config(repo_path=self.target_path),
            self._target_git,
        )

    # ------------------------------------------------------------------
    # 主编排
    # ------------------------------------------------------------------

    def run(self, resume: bool = False) -> None:
        """执行全部 6 个 phase。"""
        if resume:
            self._load_state()

        click.echo(f"\n{C_PURPLE}{'=' * 60}{C_RESET}")
        click.echo(f"  {C_PURPLE}CogniForge 逆向工程{C_RESET}")
        click.echo(f"  目标: {self.target_path}")
        click.echo(f"{C_PURPLE}{'=' * 60}{C_RESET}\n")

        phases = [
            ("Phase 1: 代码扫描", "scanning", self._phase1_scan),
            ("Phase 2: 模块发现", "module_discovery", self._phase2_discover_modules),
            ("Phase 3: SAD 生成", "sad", self._phase3_generate_sad),
            ("Phase 4: PRD 生成", "prd", self._phase4_generate_prd),
            ("Phase 5: LLD 生成", "lld", self._phase5_generate_llds),
            ("Phase 6: Workflow 引导", "registry", self._phase6_bootstrap_workflow),
        ]

        for label, phase_key, handler in phases:
            if resume and self.state.phase == phase_key:
                # Skip already completed
                if self._is_phase_done(phase_key):
                    click.echo(f"  {C_DIM}{label}... (已完成，跳过){C_RESET}")
                    continue
                resume = False

            click.echo(f"  {label}...", nl=False)
            try:
                handler()
                self.state.phase = phase_key
                self._save_state()
                click.echo(f" {C_GREEN}✓{C_RESET}")
            except Exception as e:
                click.echo(f" {click.style('✗', fg='red')}")
                click.echo(f"    错误: {e}")
                self.state.errors.append({
                    "phase": phase_key,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                })
                self._save_state()
                click.echo(f"\n  中断于 {label}，可运行 --resume 从中断处继续。")
                return

        click.echo(f"\n{C_GREEN}✓ 逆向工程完成！{C_RESET}")
        click.echo(f"  生成的文档位于: {self.target_path / '.cogniforge' / 'wiki'}")
        click.echo(f"  使用 'cd {self.target_path} && cogniforge start' 开始正向工作流")

    def _is_phase_done(self, phase_key: str) -> bool:
        checks = {
            "scanning": self.state.manifest_ready,
            "module_discovery": self.state.module_map_confirmed,
            "sad": self.state.sad_generated,
            "prd": self.state.prd_generated,
            "lld": bool(self.state.lld_total_modules and
                        len(self.state.lld_completed_modules) == len(self.state.lld_total_modules)),
            "registry": self._workflow_bootstrapped(),
        }
        return checks.get(phase_key, False)

    # ------------------------------------------------------------------
    # Phase 1: 代码扫描
    # ------------------------------------------------------------------

    def _phase1_scan(self) -> None:
        self._manifest = scan_project(self.target_path)
        manifest_path = self.target_path / ".cogniforge" / "reverse_engineer" / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(self._manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.state.manifest_ready = True
        click.echo(f"  ({self._manifest['file_count']} 文件, "
                   f"~{self._manifest['total_tokens_est']} tokens)")

    # ------------------------------------------------------------------
    # Phase 2: 模块发现
    # ------------------------------------------------------------------

    def _phase2_discover_modules(self) -> None:
        self._manifest = self._manifest or _load_manifest(self.target_path)
        self._module_map = _discover_modules(self._manifest)
        self._confirm_module_map()
        # 持久化 module_map 供后续 phases 使用
        map_path = self.target_path / ".cogniforge" / "reverse_engineer" / "module_map.json"
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(json.dumps(self._module_map, ensure_ascii=False, indent=2), encoding="utf-8")
        self.state.module_map_confirmed = True

    def _confirm_module_map(self) -> None:
        click.echo(f"\n    发现 {len(self._module_map)} 个模块:")
        for m in self._module_map:
            click.echo(f"      [{m['module_type']}] {m['module']}: "
                       f"{len(m['source_paths'])} 文件 — {m['description']}")

        if self.auto_approve:
            click.echo("     --yes 模式: 自动确认模块划分")
            return

        if not click.confirm("     确认模块划分? (y/n)", default=True):
            click.echo("     已取消。可使用 --yes 跳过人工确认。")
            raise SystemExit(0)

    # ------------------------------------------------------------------
    # Phase 3: SAD 生成
    # ------------------------------------------------------------------

    def _phase3_generate_sad(self) -> None:
        self._manifest = self._manifest or _load_manifest(self.target_path)
        self._module_map = self._module_map or _load_module_map(self.target_path)

        arch_agent = self.agents.get(AgentRole.ARCHITECT.value)
        if arch_agent is None:
            raise RuntimeError("ArchitectAgent 未初始化")

        # 临时切换 wiki_system 为目标路径的
        saved_ws = arch_agent.wiki_system
        saved_config = arch_agent.config
        arch_agent.wiki_system = self._target_wiki
        arch_agent.config = Config(repo_path=self.target_path)

        try:
            result = arch_agent._run_reverse(
                manifest=self._manifest,
                module_map=self._module_map,
                progress_callback=lambda msg: None,
            )
            if result["status"] != "success":
                raise RuntimeError(result.get("message", "SAD 生成失败"))
        finally:
            arch_agent.wiki_system = saved_ws
            arch_agent.config = saved_config

        self._sad = _load_latest_wiki_json(self.target_path, "sad")
        self.state.sad_generated = True

    # ------------------------------------------------------------------
    # Phase 4: PRD 生成
    # ------------------------------------------------------------------

    def _phase4_generate_prd(self) -> None:
        self._manifest = self._manifest or _load_manifest(self.target_path)
        self._sad = self._sad or _load_latest_wiki_json(self.target_path, "sad")
        if self._sad is None:
            raise RuntimeError("SAD 不存在，无法生成 PRD")

        pm_agent = self.agents.get(AgentRole.PM.value)
        if pm_agent is None:
            raise RuntimeError("PMAgent 未初始化")

        saved_ws = pm_agent.wiki_system
        saved_config = pm_agent.config
        pm_agent.wiki_system = self._target_wiki
        pm_agent.config = Config(repo_path=self.target_path)

        try:
            result = pm_agent._run_reverse(
                manifest=self._manifest,
                sad=self._sad,
                progress_callback=lambda msg: None,
            )
            if result["status"] != "success":
                raise RuntimeError(result.get("message", "PRD 生成失败"))
        finally:
            pm_agent.wiki_system = saved_ws
            pm_agent.config = saved_config

        self._prd = _load_latest_wiki_json(self.target_path, "prd")
        self.state.prd_generated = True

    # ------------------------------------------------------------------
    # Phase 5: LLD 生成 (per-module 并行)
    # ------------------------------------------------------------------

    def _phase5_generate_llds(self) -> None:
        self._sad = self._sad or _load_latest_wiki_json(self.target_path, "sad")
        self._prd = self._prd or _load_latest_wiki_json(self.target_path, "prd")
        self._module_map = self._module_map or _load_module_map(self.target_path)
        if not self._sad or not self._prd:
            raise RuntimeError("SAD/PRD 不完整，无法生成 LLD")

        design_agent = self.agents.get(AgentRole.DESIGN.value)
        if design_agent is None:
            raise RuntimeError("DesignAgent 未初始化")

        self.state.lld_total_modules = [m["module"] for m in self._module_map]

        for mod in self._module_map:
            module_name = mod["module"]
            if module_name in self.state.lld_completed_modules:
                click.echo(f"      {module_name} (已完成，跳过)")
                continue

            click.echo(f"      {module_name}...", nl=False)

            # 读取模块源码
            source_texts: dict[str, str] = {}
            for sp in mod.get("source_paths", []):
                fpath = self.target_path / sp
                if fpath.exists():
                    source_texts[sp] = fpath.read_text(encoding="utf-8")

            # 切片 PRD/SAD
            prd_slice = _slice_prd_for_module(self._prd, self._sad, mod)
            sad_slice = _slice_sad_for_module(self._sad, mod)

            saved_ws = design_agent.wiki_system
            saved_config = design_agent.config
            design_agent.wiki_system = self._target_wiki
            design_agent.config = Config(repo_path=self.target_path)

            try:
                result = design_agent._run_reverse(
                    module=module_name,
                    module_type=mod["module_type"],
                    source_texts=source_texts,
                    prd_slice=prd_slice,
                    sad_slice=sad_slice,
                    progress_callback=lambda msg: None,
                )
                if result["status"] != "success":
                    click.echo(f" 失败: {result.get('message', '')}")
                    continue
            finally:
                design_agent.wiki_system = saved_ws
                design_agent.config = saved_config

            self.state.lld_completed_modules.append(module_name)
            self._save_state()
            click.echo(f" {C_GREEN}✓{C_RESET}")

    # ------------------------------------------------------------------
    # Phase 6: Workflow 引导
    # ------------------------------------------------------------------

    def _phase6_bootstrap_workflow(self) -> None:
        workflow = Workflow(DAGDefinition(), repo_path=self.target_path)
        workflow.start()

        for step in DAGStep:
            if step == DAGStep.PRD:
                workflow.go_to_step(step, require_approval=False)
                workflow.approve(step, comment="逆向生成基线", approver="reverse_engineer")
                continue
            workflow.go_to_step(step, require_approval=False)
            workflow.approve(step, comment="逆向生成基线", approver="reverse_engineer")
            workflow._state.step_results[step.value] = {
                "step": step.value,
                "status": "success",
                "artifacts": [],
                "timestamp": datetime.now().isoformat(),
            }

        # Mark complete
        workflow._state.current_step = None
        workflow._save_state()
        click.echo(f"    workflow_state.json 已生成")

    def _workflow_bootstrapped(self) -> bool:
        state_path = self.target_path / ".cogniforge" / "workflow_state.json"
        return state_path.exists()

    # ------------------------------------------------------------------
    # 状态持久化
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        path = self.target_path / self.STATE_FILE
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.state = ReverseEngineerState(**data)
            click.echo(f"  从中断处恢复 (phase={self.state.phase})")

    def _save_state(self) -> None:
        self.state.updated_at = datetime.now().isoformat()
        path = self.target_path / self.STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self.state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# 模块发现 (NetworkX Louvain 社区检测)
# ---------------------------------------------------------------------------

def _discover_modules(manifest: dict) -> list[dict]:
    """基于依赖图的社区检测 + 关键词推断模块类型。"""
    try:
        import networkx as nx
    except ImportError:
        return _fallback_module_discovery(manifest)

    graph = manifest.get("dependency_graph", {})
    g = nx.DiGraph()
    for src, targets in graph.items():
        for tgt in targets:
            g.add_edge(src, tgt)

    if len(g) == 0:
        return _fallback_module_discovery(manifest)

    try:
        from networkx.algorithms.community import louvain_communities
        communities = louvain_communities(g.to_undirected())
    except Exception:
        return _fallback_module_discovery(manifest)

    symbols = manifest.get("symbols", {})
    modules: list[dict] = []

    for i, community in enumerate(communities):
        files = sorted(community)
        if len(files) < 3:
            continue
        module_type = _infer_module_type(files, symbols)
        module_name = _infer_module_name(files)
        modules.append({
            "module": module_name,
            "module_type": module_type,
            "source_paths": files,
            "description": _summarize_module(files, symbols),
        })

    if not modules:
        return _fallback_module_discovery(manifest)
    return modules


def _fallback_module_discovery(manifest: dict) -> list[dict]:
    """降级：按目录分组。"""
    groups: dict[str, list[str]] = {}
    for fpath in manifest.get("dependency_graph", {}):
        parts = fpath.split("/")
        if len(parts) >= 3 and parts[0] == "src":
            key = "/".join(parts[:3])
        elif len(parts) >= 2:
            key = parts[0]
        else:
            key = "root"
        groups.setdefault(key, []).append(fpath)

    symbols = manifest.get("symbols", {})
    modules: list[dict] = []
    for key, files in sorted(groups.items()):
        if len(files) < 2:
            continue
        mt = _infer_module_type(files, symbols)
        modules.append({
            "module": _infer_module_name(files),
            "module_type": mt,
            "source_paths": sorted(files),
            "description": _summarize_module(files, symbols),
        })
    return modules


def _infer_module_type(files: list[str], symbols: dict) -> str:
    """基于文件路径和模块内符号推断模块类型。"""
    full_text = " ".join(files).lower()
    file_set = set(files)
    module_classes = [
        c["name"].lower()
        for c in symbols.get("classes", [])
        if c.get("file", "") in file_set
    ]
    all_text = full_text + " " + " ".join(module_classes)

    keywords = {
        "database": ["model", "schema", "db", "migration", "table", "orm", "sqlalchemy", "entity"],
        "frontend": ["component", "template", "html", "jsx", "css", "react", "vue", "svelte"],
        "gateway": ["router", "route", "middleware", "gateway", "proxy", "nginx", "cors"],
        "infrastructure": ["broker", "queue", "cache", "redis", "mq", "kafka", "rabbitmq", "minio", "s3"],
    }

    scores: dict[str, int] = {}
    for mt, kws in keywords.items():
        scores[mt] = sum(1 for kw in kws if kw in all_text)

    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best
    return "service"


def _infer_module_name(files: list[str]) -> str:
    """从文件列表提取模块名：取最深公共目录的最后一个有意义目录名。"""
    if not files:
        return "Unknown"
    # 找最长公共前缀（目录部分）
    common = files[0].split("/")[:-1]  # 排除文件名
    for f in files[1:]:
        fp = f.split("/")[:-1]
        j = 0
        while j < len(common) and j < len(fp) and common[j] == fp[j]:
            j += 1
        common = common[:j]
    # 跳过通用前缀 (src, cogniforge 等)
    skip = {"src", "cogniforge"}
    for name in reversed(common):
        clean = name.replace("_", " ").title().replace(" ", "")
        if name.lower() not in skip:
            return clean
    # fallback: 最后一个非跳过的
    for name in reversed(common):
        return name.replace("_", " ").title().replace(" ", "")
    return "Root"


def _summarize_module(files: list[str], symbols: dict) -> str:
    file_set = set(files)
    classes_in_module = [
        c["name"] for c in symbols.get("classes", [])
        if c.get("file", "") in file_set
    ]
    if classes_in_module:
        top = classes_in_module[:3]
        return f"core classes: {', '.join(top)}"
    return f"{len(files)} files"


# ---------------------------------------------------------------------------
# PRD/SAD slice helpers
# ---------------------------------------------------------------------------

def _slice_prd_for_module(prd: dict, sad: dict, mod: dict) -> dict:
    """提取与模块相关的 PRD 切片。"""
    owned_comps = mod.get("owned_components", [])
    if sad and not owned_comps:
        for comp in sad.get("components", []):
            if comp.get("name") == mod["module"]:
                owned_comps.append(comp.get("id", ""))
    req_ids: set[str] = set()
    for comp in sad.get("components", []):
        if comp.get("id") in owned_comps:
            for rid in comp.get("source_requirements", []):
                req_ids.add(rid)

    if not req_ids:
        return {"requirements": prd.get("requirements", []),
                "user_stories": prd.get("user_stories", []),
                "priorities": prd.get("priorities", {})}

    relevant_reqs = [r for r in prd.get("requirements", []) if r.get("id") in req_ids]
    relevant_story_ids: set[str] = set()
    for r in relevant_reqs:
        for us_id in r.get("related_user_stories", []):
            relevant_story_ids.add(us_id)
    relevant_stories = [s for s in prd.get("user_stories", []) if s.get("id") in relevant_story_ids]
    relevant_priorities = {rid: prd.get("priorities", {}).get(rid, "中") for rid in req_ids}

    return {
        "requirements": relevant_reqs,
        "user_stories": relevant_stories,
        "priorities": relevant_priorities,
    }


def _slice_sad_for_module(sad: dict, mod: dict) -> dict:
    """提取与模块相关的 SAD 切片。"""
    mod_name = mod["module"]
    owned_comps: list[str] = []
    owned_ctrs: list[str] = []
    consumed_ctrs: list[str] = []

    for comp in sad.get("components", []):
        if comp.get("name") == mod_name:
            owned_comps.append(comp.get("id", ""))
            owned_ctrs.extend(comp.get("contracts", []))

    for ctr in sad.get("contracts", []):
        if ctr.get("provider") == mod_name:
            owned_ctrs.append(ctr.get("id", ""))
        if mod_name in ctr.get("consumers", []):
            consumed_ctrs.append(ctr.get("id", ""))

    all_ctr_ids = set(owned_ctrs) | set(consumed_ctrs)
    comp_set = set(owned_comps)

    return {
        "components": [c for c in sad.get("components", []) if c.get("id") in comp_set],
        "contracts": [c for c in sad.get("contracts", []) if c.get("id") in all_ctr_ids],
        "data_models": sad.get("data_models", []),
        "architecture_decisions": sad.get("architecture_decisions", []),
        "risks": sad.get("risks", []),
        "requirement_traceability": [
            t for t in sad.get("requirement_traceability", [])
            if set(t.get("components", [])) & comp_set or set(t.get("contracts", [])) & all_ctr_ids
        ],
    }


# ---------------------------------------------------------------------------
# 文件加载
# ---------------------------------------------------------------------------

def _load_manifest(target_path: Path) -> dict:
    path = target_path / ".cogniforge" / "reverse_engineer" / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"manifest 不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_module_map(target_path: Path) -> list[dict]:
    path = target_path / ".cogniforge" / "reverse_engineer" / "module_map.json"
    if not path.exists():
        raise FileNotFoundError(f"module_map 不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_latest_wiki_json(target_path: Path, doc_type: str) -> dict | None:
    import glob
    pattern = str(target_path / ".cogniforge" / "wiki" / doc_type / "*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    try:
        return json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None
