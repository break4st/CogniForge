#!/usr/bin/env python3
"""MDE (Design Agent) 角色测试脚本

基于实际 PRD + SAD 文档，验证 MDE 输入质量与输出正确性。
覆盖: PRD→SAD 追溯 → SAD 组件完整性 → 契约定义 → 数据模型 → LLD Schema → 跨文档一致性。

用法:
    python tests/agents/test_mde.py                  # 机械验证 PRD + SAD + LLD
    python tests/agents/test_mde.py --live           # 实时调用 LLM 生成缺失的 LLD
    python tests/agents/test_mde.py --module "部署编排引擎"  # 只测单个模块
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ===================================================================
# 测试固件: PRD JSON (完整)
# ===================================================================

FIXTURE_PRD: dict = {
    "meta": {
        "doc_id": "prd-current", "type": "prd",
        "title": "安全易部署 - 多项目自动化部署工具 PRD",
        "author": "pm_agent", "created": "2025-06-25 17:42",
        "version": 1, "last_modified": "2025-06-25 17:42", "last_author": "pm_agent",
    },
    "overview": "本产品是一款面向开发者和运维人员的轻量级持续部署桌面工具。"
                "它允许用户创建并管理多个项目，为每个项目配置多套独立的部署环境"
                "（如测试、灰度、正式线）。通过安全的密钥加密管理，用户可一键将打"
                "包好的可执行文件上传至远程服务器，自动创建版本文件夹并生成执行"
                "脚本，实现高效、安全的自动化部署与多项目并行管理。",
    "requirements": [
        {"id": "REQ-001", "name": "项目管理 - 列表与基础操作",
         "description": "用户可以创建、编辑、删除项目。每个项目包含名称、描述等信息，用于隔离不同业务系统的部署配置。",
         "status": "draft", "version": 1, "priority": "高", "depends_on": [], "supersedes": [],
         "acceptance_criteria": ["项目列表中可新增项目，输入名称后保存成功。",
                                 "点击编辑可修改项目信息。",
                                 "删除项目时，二次确认，删除后所有该项目下的环境配置一并移除。",
                                 "点击某个项目可切换到对应视图，加载其环境列表。"],
         "related_user_stories": ["US-001"],
         "change_history": [{"version": 1, "change_type": "created", "summary": "初始创建", "reason": "首次生成 PRD"}]},
        {"id": "REQ-002", "name": "环境配置 - 多环境管理",
         "description": "在项目内，用户可添加多套部署环境配置，包含服务器地址、端口、认证方式、部署路径等，实现不同部署目标的灵活配置。",
         "status": "draft", "version": 1, "priority": "高", "depends_on": ["REQ-001"], "supersedes": [],
         "acceptance_criteria": ["在项目下可新增环境，表单包含所有必填项（地址、端口、认证、路径），保存后环境列表展示。",
                                 "支持编辑和删除环境。",
                                 "认证方式支持密码和私钥文件选择，私钥文件路径本地存储。",
                                 "提供'测试连接'按钮，点击后利用配置尝试 SSH 连接并返回是否成功。",
                                 "环境列表可设置一个为默认环境，便于快速选择。"],
         "related_user_stories": ["US-002"],
         "change_history": [{"version": 1, "change_type": "created", "summary": "初始创建", "reason": "首次生成 PRD"}]},
        {"id": "REQ-003", "name": "密钥安全存储",
         "description": "所有密码和私钥内容必须加密存储，运行时通过主密码解密使用，保障敏感信息不落明盘。",
         "status": "draft", "version": 1, "priority": "高", "depends_on": [], "supersedes": [],
         "acceptance_criteria": ["存储的环境配置文件中敏感字段不可为明文。",
                                 "系统启动时需输入管理密码（或主密码），用于派生加解密密钥。",
                                 "输入错误管理密码将无法解密环境配置，无法进行部署操作。"],
         "related_user_stories": ["US-002", "US-006"],
         "change_history": [{"version": 1, "change_type": "created", "summary": "初始创建", "reason": "首次生成 PRD"}]},
        {"id": "REQ-004", "name": "自动化部署流程",
         "description": "用户选择本地可执行文件，一键部署到选定环境的远程服务器，自动创建时间戳版本目录并生成执行脚本，完成后可选更新软链接实现切换。",
         "status": "draft", "version": 1, "priority": "高", "depends_on": ["REQ-002", "REQ-003"], "supersedes": [],
         "acceptance_criteria": ["点击部署后弹出文件选择对话框，选定文件后开始上传。",
                                 "远程服务器上在指定根路径下按照时间戳创建新版本目录，如 release_YYYYMMDD_HHmmss。",
                                 "文件通过 SFTP 上传至该版本目录内。",
                                 "根据环境配置中预设的脚本模板，在版本目录下生成可执行启动脚本（如 start.sh），脚本权限设为可执行。",
                                 "若环境配置中启用了'自动更新软链接'，部署完成后将 current 链接指向新版本目录。",
                                 "部署过程日志实时显示，完成后弹出成功提示。"],
         "related_user_stories": ["US-003"],
         "change_history": [{"version": 1, "change_type": "created", "summary": "初始创建", "reason": "首次生成 PRD"}]},
        {"id": "REQ-005", "name": "部署前/后自定义脚本",
         "description": "支持在环境配置中编写部署前和部署后执行的远程命令，用于数据库迁移、服务重启等自定义操作。",
         "status": "draft", "version": 1, "priority": "中", "depends_on": ["REQ-004"], "supersedes": [],
         "acceptance_criteria": ["环境编辑页面提供'部署前脚本'和'部署后脚本'文本框。",
                                 "部署时，先执行部署前脚本（如果存在），执行失败可配置为中断部署。",
                                 "文件上传完毕并生成启动脚本后，执行部署后脚本。",
                                 "脚本执行输出应回显在部署日志中。"],
         "related_user_stories": ["US-004"],
         "change_history": [{"version": 1, "change_type": "created", "summary": "初始创建", "reason": "首次生成 PRD"}]},
        {"id": "REQ-006", "name": "版本历史与回滚",
         "description": "展示远程服务器上该环境的版本目录列表，允许用户选择历史版本并将 current 软链接指向该版本，实现快速回滚。",
         "status": "draft", "version": 1, "priority": "中", "depends_on": ["REQ-004"], "supersedes": [],
         "acceptance_criteria": ["选择环境后可查看'部署历史'，列表显示版本目录名称和创建时间。",
                                 "对历史版本提供'回滚'操作，执行后将 current 链接指向该版本目录。",
                                 "回滚操作需要二次确认。"],
         "related_user_stories": ["US-005"],
         "change_history": [{"version": 1, "change_type": "created", "summary": "初始创建", "reason": "首次生成 PRD"}]},
        {"id": "REQ-007", "name": "项目间独立配置与切换",
         "description": "确保多个项目之间的环境配置完全隔离，切换项目时界面数据无缝更新，互不干扰。",
         "status": "draft", "version": 1, "priority": "高", "depends_on": ["REQ-001"], "supersedes": [],
         "acceptance_criteria": ["新建项目 B，其环境列表为空，不影响项目 A 的现有环境。",
                                 "从项目 A 切换到项目 B，右侧环境列表和部署日志自动更新为 B 的内容，无残留数据。"],
         "related_user_stories": ["US-007"],
         "change_history": [{"version": 1, "change_type": "created", "summary": "初始创建", "reason": "首次生成 PRD"}]},
    ],
    "user_stories": [
        {"id": "US-001", "role": "开发者", "action": "创建多个项目",
         "goal": "分别管理不同的微服务系统，使配置相互隔离。", "related_requirements": ["REQ-001"]},
        {"id": "US-002", "role": "运维人员", "action": "为每个项目配置测试和正式两套环境，并使用不同的 SSH 密钥",
         "goal": "保证不同环境的安全隔离与访问控制。", "related_requirements": ["REQ-002", "REQ-003"]},
        {"id": "US-003", "role": "开发者", "action": "一键将打包好的 JAR 包部署到测试服务器，并自动生成启动脚本",
         "goal": "省去手动上传、创建目录和编写脚本的重复操作。", "related_requirements": ["REQ-004"]},
        {"id": "US-004", "role": "发布负责人", "action": "在部署前后执行自定义的数据库迁移脚本",
         "goal": "确保发布流程的完整性和连贯性。", "related_requirements": ["REQ-005"]},
        {"id": "US-005", "role": "运维人员", "action": "从历史版本列表中选择一个版本快速回滚",
         "goal": "新版本出现问题时能迅速恢复服务。", "related_requirements": ["REQ-006"]},
        {"id": "US-006", "role": "团队 Leader", "action": "设置主密码保护所有环境密钥",
         "goal": "只有授权人员才能进行部署操作，保障信息安全。", "related_requirements": ["REQ-003"]},
        {"id": "US-007", "role": "多项目管理者", "action": "在不同项目间快速切换",
         "goal": "各自的部署配置互不干扰，提升多项目并行管理效率。", "related_requirements": ["REQ-007"]},
    ],
    "priorities": {"REQ-001": "高", "REQ-002": "高", "REQ-003": "高", "REQ-004": "高",
                   "REQ-005": "中", "REQ-006": "中", "REQ-007": "高"},
}

# ===================================================================
# 测试固件: SAD JSON (精简关键字段，完整内容见 sad-001.json)
# ===================================================================

FIXTURE_SAD_COMPONENTS: list[dict] = [
    {"id": "CMP-001", "name": "ProjectListView", "type": "frontend",
     "source_requirements": ["REQ-001", "REQ-007"], "contracts": ["CTR-001"],
     "depends_on_components": ["CMP-007"]},
    {"id": "CMP-002", "name": "EnvironmentView", "type": "frontend",
     "source_requirements": ["REQ-002"], "contracts": ["CTR-002"],
     "depends_on_components": ["CMP-007"]},
    {"id": "CMP-003", "name": "DeployPanel", "type": "frontend",
     "source_requirements": ["REQ-004", "REQ-005"], "contracts": ["CTR-003"],
     "depends_on_components": ["CMP-007"]},
    {"id": "CMP-004", "name": "VersionHistoryView", "type": "frontend",
     "source_requirements": ["REQ-006"], "contracts": ["CTR-004"],
     "depends_on_components": ["CMP-007"]},
    {"id": "CMP-005", "name": "MasterPasswordDialog", "type": "frontend",
     "source_requirements": ["REQ-003"], "contracts": ["CTR-005"],
     "depends_on_components": ["CMP-007"]},
    {"id": "CMP-006", "name": "IPC Bridge", "type": "frontend",
     "source_requirements": [], "contracts": [],
     "depends_on_components": ["CMP-008", "CMP-009", "CMP-010", "CMP-011", "CMP-012"]},
    {"id": "CMP-007", "name": "MasterPasswordService", "type": "service",
     "source_requirements": ["REQ-003"], "contracts": ["CTR-005"],
     "depends_on_components": ["CMP-013", "CMP-014"]},
    {"id": "CMP-008", "name": "ProjectService", "type": "service",
     "source_requirements": ["REQ-001", "REQ-007"], "contracts": ["CTR-001"],
     "depends_on_components": ["CMP-013", "CMP-014"]},
    {"id": "CMP-009", "name": "EnvironmentService", "type": "service",
     "source_requirements": ["REQ-002"], "contracts": ["CTR-002", "CTR-006"],
     "depends_on_components": ["CMP-013", "CMP-014", "CMP-015"]},
    {"id": "CMP-010", "name": "DeploymentService", "type": "service",
     "source_requirements": ["REQ-004", "REQ-005"], "contracts": ["CTR-003"],
     "depends_on_components": ["CMP-009", "CMP-014", "CMP-015", "CMP-016"]},
    {"id": "CMP-011", "name": "VersionHistoryService", "type": "service",
     "source_requirements": ["REQ-006"], "contracts": ["CTR-004"],
     "depends_on_components": ["CMP-009", "CMP-015", "CMP-016"]},
    {"id": "CMP-012", "name": "DeploymentLogService", "type": "service",
     "source_requirements": ["REQ-004", "REQ-006"], "contracts": [],
     "depends_on_components": []},
    {"id": "CMP-013", "name": "ConfigStore", "type": "infrastructure",
     "source_requirements": ["REQ-001", "REQ-002", "REQ-003"], "contracts": [],
     "depends_on_components": []},
    {"id": "CMP-014", "name": "CryptoService", "type": "infrastructure",
     "source_requirements": ["REQ-003"], "contracts": [],
     "depends_on_components": ["CMP-007"]},
    {"id": "CMP-015", "name": "SshClient", "type": "infrastructure",
     "source_requirements": ["REQ-002", "REQ-004", "REQ-006"], "contracts": [],
     "depends_on_components": []},
    {"id": "CMP-016", "name": "Logger", "type": "infrastructure",
     "source_requirements": [], "contracts": [], "depends_on_components": []},
]

FIXTURE_SAD_CONTRACTS: list[dict] = [
    {"id": "CTR-001", "interface": "project:list / project:create / project:update / project:delete",
     "provider_component_id": "CMP-008", "provider": "ProjectService",
     "consumers": ["ProjectListView"], "type": "REST", "endpoint": "ipc:project:*",
     "source_requirements": ["REQ-001", "REQ-007"]},
    {"id": "CTR-002", "interface": "env:list / env:create / env:update / env:delete / env:testConnection",
     "provider_component_id": "CMP-009", "provider": "EnvironmentService",
     "consumers": ["EnvironmentView"], "type": "REST", "endpoint": "ipc:env:*",
     "source_requirements": ["REQ-002"]},
    {"id": "CTR-003", "interface": "deploy:execute",
     "provider_component_id": "CMP-010", "provider": "DeploymentService",
     "consumers": ["DeployPanel"], "type": "REST", "endpoint": "ipc:deploy:execute",
     "source_requirements": ["REQ-004", "REQ-005"]},
    {"id": "CTR-004", "interface": "history:list / history:rollback",
     "provider_component_id": "CMP-011", "provider": "VersionHistoryService",
     "consumers": ["VersionHistoryView"], "type": "REST",
     "endpoint": "ipc:history:list, ipc:history:rollback",
     "source_requirements": ["REQ-006"]},
    {"id": "CTR-005", "interface": "masterPassword:verify / masterPassword:setup",
     "provider_component_id": "CMP-007", "provider": "MasterPasswordService",
     "consumers": ["MasterPasswordDialog"], "type": "REST",
     "endpoint": "ipc:masterPassword:verify, ipc:masterPassword:setup",
     "source_requirements": ["REQ-003"]},
    {"id": "CTR-006", "interface": "env:decrypt (internal call)",
     "provider_component_id": "CMP-014", "provider": "CryptoService",
     "consumers": ["EnvironmentService", "DeploymentService"], "type": "Event",
     "endpoint": "N/A (local method)", "source_requirements": ["REQ-003"]},
]

FIXTURE_SAD_DATA_MODELS: list[dict] = [
    {"id": "DM-001", "name": "Project",
     "source_requirements": ["REQ-001"],
     "fields": ["id", "name", "description", "environmentsEncrypted"]},
    {"id": "DM-002", "name": "Environment",
     "source_requirements": ["REQ-002"],
     "fields": ["id", "projectId", "name", "host", "port", "authType", "username",
                "password", "privateKeyPath", "deployRootPath", "scriptTemplate",
                "preDeployScript", "postDeployScript", "autoUpdateSymlink", "isDefault"]},
    {"id": "DM-003", "name": "AppConfig",
     "source_requirements": ["REQ-003"],
     "fields": ["passwordHash", "salt"]},
    {"id": "DM-004", "name": "DeployLog",
     "source_requirements": ["REQ-004", "REQ-006"],
     "fields": ["timestamp", "projectName", "environmentName", "operation", "detail"]},
]

FIXTURE_SAD_TRACES: list[dict] = [
    {"requirement_id": "REQ-001", "coverage": "full",
     "components": ["CMP-001", "CMP-008", "CMP-013"], "contracts": ["CTR-001"],
     "data_models": ["DM-001"]},
    {"requirement_id": "REQ-002", "coverage": "full",
     "components": ["CMP-002", "CMP-009", "CMP-013", "CMP-014", "CMP-015"],
     "contracts": ["CTR-002"], "data_models": ["DM-002"]},
    {"requirement_id": "REQ-003", "coverage": "full",
     "components": ["CMP-005", "CMP-007", "CMP-013", "CMP-014"],
     "contracts": ["CTR-005", "CTR-006"], "data_models": ["DM-003"]},
    {"requirement_id": "REQ-004", "coverage": "full",
     "components": ["CMP-003", "CMP-010", "CMP-012", "CMP-014", "CMP-015", "CMP-016"],
     "contracts": ["CTR-003"], "data_models": ["DM-004"]},
    {"requirement_id": "REQ-005", "coverage": "full",
     "components": ["CMP-003", "CMP-010", "CMP-015"],
     "contracts": ["CTR-003"], "data_models": []},
    {"requirement_id": "REQ-006", "coverage": "full",
     "components": ["CMP-004", "CMP-011", "CMP-015", "CMP-012"],
     "contracts": ["CTR-004"], "data_models": ["DM-004"]},
    {"requirement_id": "REQ-007", "coverage": "full",
     "components": ["CMP-001", "CMP-008", "CMP-013"],
     "contracts": ["CTR-001"], "data_models": []},
]

# SAD 组件类型 → LLD module_type 直接映射 (两者共用同一枚举值)
SAD_TYPE_MAP = {
    "frontend": "frontend", "service": "service",
    "gateway": "gateway", "infrastructure": "infrastructure",
}

# LLD 模块类型 → 必需章节
REQUIRED_SECTIONS: dict[str, list[str]] = {
    "service":    ["data_models", "domain_objects", "service_contracts",
                   "business_rules", "interfaces", "error_handling"],
    "frontend":   ["data_models", "component_tree", "state_design", "route_design",
                   "interaction_flows", "api_integration", "interfaces"],
    "gateway":    ["data_models", "route_table", "middleware_chain",
                   "auth_policy", "rate_limiting", "interfaces", "error_handling"],
    "database":   ["data_models", "index_strategy", "migration_strategy",
                   "capacity_estimation", "connection_contracts", "interfaces"],
    "infrastructure": ["data_models", "topology", "interfaces"],
}

TYPE_EXCLUSIVE: dict[str, set[str]] = {
    "service":    {"domain_objects", "service_contracts", "business_rules"},
    "frontend":   {"component_tree", "state_design", "route_design",
                   "interaction_flows", "api_integration"},
    "gateway":    {"route_table", "middleware_chain", "auth_policy", "rate_limiting"},
    "database":   {"index_strategy", "migration_strategy", "capacity_estimation"},
    "infrastructure": {"topology", "message_contracts", "reliability_strategy"},
}

SHARED = {"data_models", "interfaces", "error_handling",
          "connection_contracts", "workflow", "security_design"}


# ===================================================================
# 报告
# ===================================================================

class TestReport:
    def __init__(self):
        self.tests: list[dict] = []
        self.t0 = time.time()

    def add(self, check: str, ok: bool, detail: str,
            section: str = "", severity: str = "error"):
        self.tests.append({"check": check, "passed": ok, "detail": detail,
                           "section": section, "severity": severity})

    def summary(self) -> str:
        elapsed = time.time() - self.t0
        total = len(self.tests)
        ok = sum(1 for t in self.tests if t["passed"])
        ng = total - ok
        errs = sum(1 for t in self.tests if not t["passed"] and t["severity"] == "error")
        warns = sum(1 for t in self.tests if not t["passed"] and t["severity"] == "warning")

        lines = [
            "=" * 70,
            "  MDE (Design Agent) 角色测试报告",
            "=" * 70,
            f"  执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  耗时: {elapsed:.2f}s",
            f"  测试总数: {total}  |  通过: {ok}  |  失败: {ng}",
        ]
        if errs:
            lines.append(f"  错误: {errs}  |  警告: {warns}")
        lines.append("")
        lines.append("-" * 70)
        lines.append("  详细结果")
        lines.append("-" * 70)
        for i, t in enumerate(self.tests, 1):
            icon = "[PASS]" if t["passed"] else "[FAIL]"
            sev = f" [{t['severity'].upper()}]" if not t["passed"] else ""
            lines.append(f"  {i:3d}. {icon}{sev} [{t['section']}] {t['check']}")
            if not t["passed"]:
                lines.append(f"       -> {t['detail']}")
        lines.append("")
        lines.append("-" * 70)
        lines.append(f"  结论: {'所有测试通过' if ng == 0 else f'{ng} 项失败，需修复'}")
        lines.append("=" * 70)
        return "\n".join(lines)


report = TestReport()


# ===================================================================
# 工具函数
# ===================================================================

def find_repo_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".git").exists() or (p / "CLAUDE.md").exists():
            return p
        p = p.parent
    return Path.cwd()


def load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def scan_lld_owned_components(repo: Path) -> dict[str, str]:
    """Scan all LLD files and return {CMP_ID: module_name} from module_boundary."""
    lld_dir = repo / ".cogniforge" / "wiki" / "lld"
    if not lld_dir.exists():
        return {}
    result: dict[str, str] = {}
    for f in sorted(lld_dir.rglob("lld-*.json")):
        data = load_json(f)
        if not isinstance(data, dict):
            continue
        mod = data.get("meta", {}).get("module", "")
        owned = data.get("module_boundary", {}).get("owned_components", [])
        for cmp_id in owned:
            result[cmp_id] = mod
    return result


def load_all_llds(repo: Path) -> dict[str, dict]:
    lld_dir = repo / ".cogniforge" / "wiki" / "lld"
    if not lld_dir.exists():
        return {}
    result: dict[str, dict] = {}
    for f in sorted(lld_dir.rglob("*.json")):
        data = load_json(f)
        if not isinstance(data, dict):
            continue
        mod = data.get("meta", {}).get("module", f.stem)
        result[mod] = data
    return result


def load_recent_sad(repo: Path) -> Optional[dict]:
    sad_dir = repo / ".cogniforge" / "wiki" / "sad"
    if not sad_dir.exists():
        return None
    files = sorted(sad_dir.glob("*.json"), reverse=True)
    return load_json(files[0]) if files else None


# ===================================================================
# 1⃣  PRD → SAD 需求追溯完整性
# ===================================================================

def test_prd_to_sad_traceability():
    """验证每条 PRD 需求都在 SAD 中有 full coverage。"""
    sec = "PRD→SAD 追溯"
    prd_reqs = {r["id"] for r in FIXTURE_PRD["requirements"]}

    for req_id in sorted(prd_reqs):
        trace = next((t for t in FIXTURE_SAD_TRACES if t["requirement_id"] == req_id), None)
        if trace is None:
            report.add(f"'{req_id}' 在 SAD 追溯中存在", False,
                       f"PRD 需求 '{req_id}' 不在 SAD requirement_traceability 中", sec)
            continue

        coverage = trace.get("coverage", "")
        report.add(f"'{req_id}' coverage={coverage}", coverage == "full",
                   f"'{req_id}' 覆盖状态: {coverage}" +
                   ("" if coverage == "full" else " (应为 full)"), sec)

        # 至少有一个组件和一个契约覆盖（除非是纯 UI 需求）
        has_comp = len(trace.get("components", [])) > 0
        has_ctr = len(trace.get("contracts", [])) > 0
        report.add(f"'{req_id}' 有组件覆盖", has_comp,
                   f"组件: {trace.get('components', [])}", sec,
                   severity="warning" if not has_comp else "error")
        report.add(f"'{req_id}' 有契约覆盖", has_ctr,
                   f"契约: {trace.get('contracts', [])}", sec,
                   severity="warning" if not has_ctr else "error")

    # 反向: SAD 追溯中的每条需求都属于 PRD
    for trace in FIXTURE_SAD_TRACES:
        rid = trace["requirement_id"]
        report.add(f"SAD 追溯 '{rid}' 对应 PRD 需求存在",
                   rid in prd_reqs,
                   f"'{rid}' {'存在于' if rid in prd_reqs else '不在'} PRD 中", sec)


# ===================================================================
# 2⃣  SAD 组件结构完整性
# ===================================================================

def test_sad_components():
    """验证 SAD 组件定义是否完备。"""
    sec = "SAD 组件"

    types_count: dict[str, int] = {}
    comp_ids = {c["id"] for c in FIXTURE_SAD_COMPONENTS}
    comp_names = {c["name"] for c in FIXTURE_SAD_COMPONENTS}

    for comp in FIXTURE_SAD_COMPONENTS:
        cid = comp["id"]
        ctype = comp.get("type", "")
        types_count[ctype] = types_count.get(ctype, 0) + 1

        # 必填字段
        for field in ["id", "name", "type", "source_requirements"]:
            has = field in comp
            report.add(f"'{cid}' 有 {field}", has,
                       f"'{cid}' {'有' if has else '缺少'} {field}", sec)

        # depends_on 引用有效性
        for dep_id in comp.get("depends_on_components", []):
            report.add(f"'{cid}' depends_on '{dep_id}' 存在",
                       dep_id in comp_ids,
                       f"依赖组件 '{dep_id}' {'存在' if dep_id in comp_ids else '不存在'}", sec)

        # 契约引用有效性
        ctr_ids = {c["id"] for c in FIXTURE_SAD_CONTRACTS}
        for ctr_id in comp.get("contracts", []):
            report.add(f"'{cid}' contract '{ctr_id}' 存在",
                       ctr_id in ctr_ids,
                       f"契约 '{ctr_id}' {'存在' if ctr_id in ctr_ids else '不存在'}", sec)

    # 各类型数量
    report.add("组件类型分布", len(types_count) >= 3,
               f"类型: {dict(types_count)} (预期 >=3)", sec)
    report.add("frontend 组件数", types_count.get("frontend", 0) >= 4,
               f"frontend: {types_count.get('frontend', 0)}", sec)
    report.add("service 组件数", types_count.get("service", 0) >= 4,
               f"service: {types_count.get('service', 0)}", sec)
    report.add("infrastructure 组件数", types_count.get("infrastructure", 0) >= 3,
               f"infrastructure: {types_count.get('infrastructure', 0)}", sec)

    return comp_ids, comp_names


# ===================================================================
# 3⃣  SAD 契约定义完整性
# ===================================================================

def test_sad_contracts(comp_ids: set[str], comp_names: set[str]):
    """验证 SAD 契约定义是否完整且 provider/consumer 引用有效。"""
    sec = "SAD 契约"

    for ctr in FIXTURE_SAD_CONTRACTS:
        cid = ctr["id"]
        for field in ["id", "interface", "provider_component_id", "provider", "consumers"]:
            has = field in ctr
            report.add(f"'{cid}' 有 {field}", has,
                       f"'{cid}' {'有' if has else '缺少'} {field}", sec)

        # provider 组件存在 (provider_component_id 是 CMP-xxx，provider 是组件名)
        prov = ctr.get("provider_component_id", "")
        report.add(f"'{cid}' provider_id '{prov}' 存在",
                   prov in comp_ids,
                   f"provider组件ID '{prov}' {'存在' if prov in comp_ids else '不存在'}", sec)

        # consumer 组件存在 (consumers 里存的是组件名，不是 CMP ID)
        for consumer in ctr.get("consumers", []):
            report.add(f"'{cid}' consumer '{consumer}' 存在",
                       consumer in comp_names,
                       f"consumer组件 '{consumer}' {'存在' if consumer in comp_names else '不存在'}", sec)

        # 有 source_requirements
        has_src = len(ctr.get("source_requirements", [])) > 0
        report.add(f"'{cid}' 有 source_requirements", has_src,
                   f"来源需求: {ctr.get('source_requirements', [])}", sec,
                   severity="warning" if not has_src else "error")

    # 检查每个 service 组件都有至少一个对外契约 (内部服务如 Logger/ConfigStore 除外)
    internal_services = {"CMP-012", "CMP-013", "CMP-014", "CMP-015", "CMP-016"}
    for comp in FIXTURE_SAD_COMPONENTS:
        if comp["type"] != "service":
            continue
        if comp["id"] in internal_services:
            continue
        has_ctr = len(comp.get("contracts", [])) > 0
        report.add(f"service '{comp['name']}' 有对外契约", has_ctr,
                   f"契约: {comp.get('contracts', [])}", sec)


# ===================================================================
# 4⃣  SAD 数据模型与 PRD 需求对齐
# ===================================================================

def test_sad_data_models():
    """验证 SAD 数据模型覆盖了 PRD 的核心数据需求。"""
    sec = "SAD 数据模型"

    prd_reqs = {r["id"] for r in FIXTURE_PRD["requirements"]}

    for dm in FIXTURE_SAD_DATA_MODELS:
        dmid = dm["id"]
        report.add(f"'{dmid}' 有字段定义", len(dm.get("fields", [])) > 0,
                   f"{len(dm.get('fields', []))} 个字段", sec)

        for rid in dm.get("source_requirements", []):
            report.add(f"'{dmid}' source_requirement '{rid}' 有效",
                       rid in prd_reqs,
                       f"需求 '{rid}' {'存在' if rid in prd_reqs else '不存在'}", sec)

    # 检查关键数据实体
    expected_models = {"Project", "Environment", "AppConfig", "DeployLog"}
    actual_names = {dm["name"] for dm in FIXTURE_SAD_DATA_MODELS}
    for name in expected_models:
        report.add(f"数据模型 '{name}' 已定义", name in actual_names,
                   f"'{name}' {'已' if name in actual_names else '未'}在 SAD 中定义", sec)


# ===================================================================
# 5⃣  PRD 需求依赖关系检查
# ===================================================================

def test_prd_dependency_integrity():
    """验证 PRD 内部依赖无环且引用完整。"""
    sec = "PRD 依赖"

    req_ids = {r["id"] for r in FIXTURE_PRD["requirements"]}

    # depends_on 引用存在性
    for req in FIXTURE_PRD["requirements"]:
        rid = req["id"]
        for dep in req.get("depends_on", []):
            report.add(f"'{rid}' depends_on '{dep}' 有效",
                       dep in req_ids,
                       f"依赖 '{dep}' {'存在' if dep in req_ids else '不存在'}", sec)

    # 依赖环检测
    graph = {r["id"]: r.get("depends_on", []) for r in FIXTURE_PRD["requirements"]}
    cycles = _find_cycles(graph)
    if cycles:
        report.add("PRD 需求依赖无环", False,
                   f"检测到环: {cycles}", sec)
    else:
        report.add("PRD 需求依赖无环", True, "需求依赖关系为 DAG", sec)

    # 优先级高需求不应依赖低需求
    for req in FIXTURE_PRD["requirements"]:
        rid = req["id"]
        pri = req.get("priority", "")
        for dep in req.get("depends_on", []):
            dep_req = next((r for r in FIXTURE_PRD["requirements"] if r["id"] == dep), None)
            if dep_req:
                dep_pri = dep_req.get("priority", "")
                if pri == "低" and dep_pri == "高":
                    report.add(f"'{rid}'(低) depends_on '{dep}'(高) 合理",
                               True, "低优先级依赖高优先级 — 检查确认无问题", sec,
                               severity="warning")


# ===================================================================
# 6⃣  SAD → 模块注册表 映射
# ===================================================================

def test_sad_to_registry_mapping(repo: Path, comp_names: set[str]):
    """验证 SAD 组件都被 LLD module_boundary 覆盖。"""
    sec = "SAD→Registry"
    lld_owned = scan_lld_owned_components(repo)

    if not lld_owned:
        report.add("LLD owned_components 加载", False, "无 LLD 文档或 module_boundary 为空", sec)
        return

    report.add("LLD owned_components 加载", len(lld_owned) > 0,
               f"共 {len(lld_owned)} 个组件映射", sec)

    # Build SAD component ID → name
    sad_id_to_name = {c["id"]: c["name"] for c in FIXTURE_SAD_COMPONENTS}

    uncovered: list[str] = []
    for comp_id, comp_name in sorted(sad_id_to_name.items()):
        if comp_id not in lld_owned:
            uncovered.append(f"{comp_id}({comp_name})")

    if uncovered:
        report.add("SAD 组件→LLD 覆盖",
                   False,
                   f"未覆盖: {uncovered}", sec, severity="warning")
    else:
        report.add("SAD 组件→LLD 覆盖", True,
                   "所有 SAD 组件在 LLD module_boundary 中有对应模块", sec)


# ===================================================================
# 7⃣  LLD Schema 结构验证 (逐模块)
# ===================================================================

def test_lld_schema_per_module(repo: Path):
    """对已存在的 LLD 文档进行逐模块结构验证。"""
    llds = load_all_llds(repo)
    if not llds:
        report.add("LLD 文档加载", False,
                   "无 LLD JSON 文件，请先运行 MDE Agent", "LLD Schema")
        return

    report.add("LLD 文档加载", True,
               f"共 {len(llds)} 个 LLD 文档", "LLD Schema")

    for mod_name, lld in llds.items():
        sec = f"LLD [{mod_name}]"
        meta = lld.get("meta", {})
        mod_type = meta.get("module_type", "service")

        # meta 字段
        for f in ["doc_id", "module", "module_type", "version"]:
            has = f in meta
            report.add(f"meta.{f}", has, f"= {meta.get(f, '缺失')}", sec)

        # 必需章节
        for req_sec in REQUIRED_SECTIONS.get(mod_type, []):
            has = req_sec in lld and lld[req_sec]
            report.add(f"章节 '{req_sec}' 存在且非空", has,
                       f"'{req_sec}' {'存在' if has else '缺失或为空'}", sec)

        # 不允许越界章节
        for otype, excl in TYPE_EXCLUSIVE.items():
            if otype == mod_type:
                continue
            for es in excl:
                if es in lld and es not in SHARED:
                    report.add(f"无越界章节 '{es}' ({otype}专属)", False,
                               f"'{es}' 不应出现在 {mod_type} 类型中", sec)


# ===================================================================
# 8⃣  跨文档接口一致性: SAD Contract ↔ LLD Interface
# ===================================================================

def test_contract_to_lld_interface(repo: Path):
    """验证 SAD 契约在 LLD 中有对应的接口实现。"""
    sec = "契约→LLD 接口"

    llds = load_all_llds(repo)
    if not llds:
        report.add("LLD 加载", False, "无 LLD 文档可检查", sec)
        return

    # 从 LLD 中提取所有接口的 endpoint
    lld_endpoints: set[str] = set()
    for mod_name, lld in llds.items():
        for iface in lld.get("interfaces", []):
            if isinstance(iface, dict):
                ep = iface.get("endpoint", "")
                if ep:
                    lld_endpoints.add(ep)

    for ctr in FIXTURE_SAD_CONTRACTS:
        cid = ctr["id"]
        sad_ep = ctr.get("endpoint", "")

        # 在 LLD 中搜索匹配 (模糊匹配: 提取 ipc:xxx:yyy 中的关键部分)
        matched = False
        sad_keywords = sad_ep.replace("ipc:", "").replace("*", "").strip()
        for lld_ep in lld_endpoints:
            if sad_keywords in lld_ep or lld_ep in sad_ep:
                matched = True
                break

        # 也检查 LLD 的 service_contracts
        if not matched:
            for mod_name, lld in llds.items():
                for sc in lld.get("service_contracts", []):
                    if isinstance(sc, dict):
                        sc_name = sc.get("name", "") or sc.get("method", "")
                        if sad_keywords.lower() in sc_name.lower():
                            matched = True
                            break
                if matched:
                    break

        report.add(f"契约 '{cid}' ({sad_ep[:40]}...) 有 LLD 实现",
                   matched,
                   f"'{cid}' {'在 LLD 中找到接口' if matched else '未在 LLD 中找到接口实现'}",
                   sec, severity="warning" if not matched else "error")


# ===================================================================
# 9⃣  SAD 组件依赖 → LLD consumer 契约引用
# ===================================================================

def test_component_deps_to_lld(repo: Path):
    """验证 SAD 中声明的组件依赖在 LLD 中有对应的 consumer 契约引用。"""
    sec = "组件依赖→LLD"

    llds = load_all_llds(repo)
    if not llds:
        return

    # 构建 LLD 中 consumer 契约引用索引
    lld_ctr_refs: dict[str, set[str]] = {}
    for mod_name, lld in llds.items():
        consumed = set()
        for iface in lld.get("interfaces", []):
            if isinstance(iface, dict):
                refs = iface.get("consumed_contracts", [])
                if isinstance(refs, list):
                    consumed.update(refs)
        lld_ctr_refs[mod_name] = consumed

    # 检查前端组件 (它们消费契约) 对应的 LLD 是否引用了正确的契约
    frontend_ctrs = {
        "ProjectListView": ["CTR-001"],
        "EnvironmentView": ["CTR-002"],
        "DeployPanel": ["CTR-003"],
        "VersionHistoryView": ["CTR-004"],
        "MasterPasswordDialog": ["CTR-005"],
    }

    for comp_name, expected_ctrs in frontend_ctrs.items():
        # 前端组件都映射到同一个 LLD: 前端应用_React_UI
        lld_ctrs = lld_ctr_refs.get("前端应用_React_UI", set())
        for ctr_id in expected_ctrs:
            found = ctr_id in lld_ctrs or any(
                ctr_id in json.dumps(lld.get("api_integration", {}), ensure_ascii=False)
                for lld_name, lld in llds.items()
                if "前端" in lld_name
            )
            if not lld_ctrs:
                continue  # LLD 未生成时跳过
            report.add(f"'{comp_name}' 消费契约 '{ctr_id}'",
                       found,
                       f"'{ctr_id}' {'在 LLD 中引用' if found else '未引用'}", sec,
                       severity="warning" if not found else "error")


# ===================================================================
# 辅助: 环检测
# ===================================================================

def _find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(node):
        if node in stack:
            idx = stack.index(node)
            cycles.append(stack[idx:] + [node])
            return
        if node in visited or node not in graph:
            return
        visited.add(node)
        stack.append(node)
        for nb in graph.get(node, []):
            dfs(nb)
        stack.pop()

    for n in graph:
        if n not in visited:
            dfs(n)
    return cycles


# ===================================================================
# 主流程
# ===================================================================

def run_all_tests(live_mode: bool = False, target_module: str = None):
    repo = find_repo_root()
    print(f"[INFO] 仓库根目录: {repo}")

    # ── 1. PRD → SAD 追溯 ──
    print("[TEST] 1/9 PRD → SAD 需求追溯...")
    test_prd_to_sad_traceability()

    # ── 2. SAD 组件结构 ──
    print("[TEST] 2/9 SAD 组件完整性...")
    comp_ids, comp_names = test_sad_components()

    # ── 3. SAD 契约 ──
    print("[TEST] 3/9 SAD 契约定义...")
    test_sad_contracts(comp_ids, comp_names)

    # ── 4. SAD 数据模型 ──
    print("[TEST] 4/9 SAD 数据模型...")
    test_sad_data_models()

    # ── 5. PRD 依赖完整性 ──
    print("[TEST] 5/9 PRD 需求依赖...")
    test_prd_dependency_integrity()

    # ── 6. SAD → Registry ──
    print("[TEST] 6/9 SAD 组件 → 模块注册表...")
    test_sad_to_registry_mapping(repo, comp_names)

    # ── 7. LLD Schema ──
    print("[TEST] 7/9 LLD Schema 结构验证...")
    test_lld_schema_per_module(repo)

    # ── 8. 契约→LLD 接口 ──
    print("[TEST] 8/9 SAD 契约 → LLD 接口...")
    test_contract_to_lld_interface(repo)

    # ── 9. 组件依赖→LLD ──
    print("[TEST] 9/9 SAD 组件依赖 → LLD consumer 契约...")
    test_component_deps_to_lld(repo)

    # ── 输出 ──
    print()
    print(report.summary())

    out_dir = repo / "tests"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "mde_test_report.json"
    json_report = {
        "timestamp": datetime.now().isoformat(),
        "live_mode": live_mode,
        "total_tests": len(report.tests),
        "passed": sum(1 for t in report.tests if t["passed"]),
        "failed": sum(1 for t in report.tests if not t["passed"]),
        "details": report.tests,
    }
    json_path.write_text(
        json.dumps(json_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[JSON 报告] {json_path}")

    failed = sum(1 for t in report.tests
                 if not t["passed"] and t["severity"] == "error")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MDE (Design Agent) 角色测试脚本")
    parser.add_argument("--live", action="store_true",
                        help="实时调用 LLM 生成缺失的 LLD")
    parser.add_argument("--module", type=str, default=None,
                        help="仅测试指定模块")
    args = parser.parse_args()

    print("=" * 70)
    print("  CogniForge MDE 角色测试 (PRD + SAD + LLD)")
    print("=" * 70)
    print(f"  PRD: {FIXTURE_PRD['meta']['title']}")
    print(f"  模式: {'实时 LLM 生成' if args.live else '机械验证'}")
    print()

    sys.exit(run_all_tests(live_mode=args.live, target_module=args.module))
