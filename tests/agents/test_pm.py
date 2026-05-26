#!/usr/bin/env python3
"""PM (Product Manager) 角色测试脚本

针对"多项目自动化部署"功能的 PM 流水线全面测试。
覆盖: 输入解析 → PRD Schema 合规 → 需求完整性 → 用户故事规范 → ID 分配 → 优先级一致性 → 依赖关系 → 变更历史。

用法:
    python tests/agents/test_pm.py                         # 机械验证（无需 LLM）
    python tests/agents/test_pm.py --live                  # 实时调用 LLM 生成 PRD
    python tests/agents/test_pm.py --report-only           # 仅输出已有 PRD 的检查报告
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 特征描述 (输入)
# ---------------------------------------------------------------------------

FEATURE_DESCRIPTION = (
    "实现将打包好的可执行文件自动化部署到指定远程服务器的功能。"
    "系统支持用户自定义多套部署环境（如测试线、灰度线、正式线等），"
    "每套环境可通过密钥配置安全连接，部署时自动在远程服务器上创建版本文件夹并生成执行脚本，"
    "实现一键式自动化部署。同时支持用户创建和管理多个项目，"
    "每个项目拥有独立的部署环境配置，支持在项目间灵活切换，满足多项目并行管理的需求。"
)

# ---------------------------------------------------------------------------
# PRD Schema 常量 (与 prd-schema.json 对齐)
# ---------------------------------------------------------------------------

META_REQUIRED = ["doc_id", "type", "title", "author", "created", "version", "last_modified", "last_author"]

REQUIREMENT_REQUIRED = ["id", "name", "description", "status", "version"]

REQUIREMENT_OPTIONAL = [
    "acceptance_criteria", "priority", "depends_on", "supersedes",
    "related_user_stories", "change_history",
]

REQUIREMENT_STATUSES = {"draft", "active", "changed", "deprecated", "removed"}

REQUIREMENT_PRIORITIES = {"高", "中", "低"}

REQUIREMENT_CHANGE_TYPES = {
    "created", "modified", "deprecated", "removed", "merged", "split",
    "superseded", "reprioritized",
}

USER_STORY_REQUIRED = ["id", "role", "action", "goal"]

USER_STORY_OPTIONAL = ["related_requirements"]

ID_PATTERN_REQ = re.compile(r"^REQ-\d{3,}$")
ID_PATTERN_US = re.compile(r"^US-\d{3,}$")

DOC_REQUIRED_TOP = ["meta", "overview", "requirements", "user_stories", "priorities"]


# ---------------------------------------------------------------------------
# 测试结果收集
# ---------------------------------------------------------------------------

class TestReport:
    def __init__(self):
        self.tests: list[dict] = []
        self.start_time = time.time()

    def add(self, check_name: str, passed: bool, detail: str,
            section: str = "", severity: str = "error"):
        self.tests.append({
            "check": check_name, "passed": passed, "detail": detail,
            "section": section, "severity": severity,
        })

    def summary(self) -> str:
        elapsed = time.time() - self.start_time
        total = len(self.tests)
        passed = sum(1 for t in self.tests if t["passed"])
        failed = total - passed
        errors = sum(1 for t in self.tests
                     if not t["passed"] and t["severity"] == "error")
        warnings = sum(1 for t in self.tests
                       if not t["passed"] and t["severity"] == "warning")

        lines = []
        lines.append("=" * 70)
        lines.append("  PM (Product Manager) 角色测试报告")
        lines.append("=" * 70)
        lines.append(f"  执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  耗时: {elapsed:.2f}s")
        lines.append(f"  测试总数: {total}  |  通过: {passed}  |  失败: {failed}")
        if errors:
            lines.append(f"  错误: {errors}  |  警告: {warnings}")
        lines.append("")

        lines.append("-" * 70)
        lines.append("  详细测试结果")
        lines.append("-" * 70)
        for i, t in enumerate(self.tests, 1):
            icon = "[PASS]" if t["passed"] else "[FAIL]"
            sev = f" [{t['severity'].upper()}]" if not t["passed"] else ""
            lines.append(f"  {i:3d}. {icon}{sev} [{t['section']}] {t['check']}")
            if not t["passed"]:
                lines.append(f"       -> {t['detail']}")

        lines.append("")
        lines.append("-" * 70)
        if failed == 0:
            lines.append("  结论: 所有测试通过")
        else:
            lines.append(f"  结论: {failed} 项测试失败，需要修复")
        lines.append("=" * 70)
        return "\n".join(lines)


report = TestReport()


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def find_repo_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".git").exists() or (p / "CLAUDE.md").exists():
            return p
        p = p.parent
    return Path.cwd()


def tests_dir(repo: Path) -> Path:
    return repo / "tests"


def load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError, ValueError):
        return None


def load_prd(repo: Path) -> Optional[dict]:
    prd_dir = repo / ".cogniforge" / "wiki" / "prd"
    if not prd_dir.exists():
        return None
    for f in sorted(prd_dir.glob("*.json"), reverse=True):
        data = load_json(f)
        if data and data.get("meta", {}).get("type") == "prd":
            return data
    return None


# ---------------------------------------------------------------------------
# 测试 1: 输入特征描述语义覆盖
# ---------------------------------------------------------------------------

def test_feature_semantics(feature_desc: str):
    section = "输入验证"
    concepts = [
        ("部署", "自动化部署", "error"),
        ("环境", "多套部署环境(测试/灰度/正式)", "error"),
        ("密钥/认证", "安全连接与密钥管理", "error"),
        ("远程服务器", "远程服务器连接", "error"),
        ("版本/文件夹", "版本目录管理", "warning"),
        ("脚本/启动", "执行脚本生成", "error"),
        ("项目", "多项目管理与切换", "error"),
    ]
    for kw, label, severity in concepts:
        found = any(k in feature_desc for k in kw.split("/"))
        report.add(
            f"包含 '{label}' 概念", found,
            f"{'已' if found else '缺'}含 '{label}'",
            section=section, severity=severity if not found else "error",
        )

    # 检查整体信息密度
    report.add("特征描述长度充足", len(feature_desc) >= 80,
               f"共 {len(feature_desc)} 字符", section=section)


# ---------------------------------------------------------------------------
# 测试 2: PRD 文档存在性
# ---------------------------------------------------------------------------

def test_prd_existence(repo: Path) -> Optional[dict]:
    section = "PRD 加载"
    prd = load_prd(repo)
    if prd is None:
        report.add("PRD 文档存在", False,
                   "prd-current.json 不存在，请先运行 PM Agent 生成", section=section)
        return None
    report.add("PRD 文档存在", True,
               f"已加载: {prd.get('meta', {}).get('doc_id', '?')}", section=section)
    return prd


# ---------------------------------------------------------------------------
# 测试 3: 顶层结构 & Meta 字段
# ---------------------------------------------------------------------------

def test_top_level_structure(prd: dict):
    section = "顶层结构"

    for field in DOC_REQUIRED_TOP:
        has = field in prd
        report.add(f"顶层字段 '{field}' 存在", has,
                   f"'{field}' {'已存在' if has else '缺失'}", section=section)

    meta = prd.get("meta", {})
    if not meta:
        report.add("meta 对象", False, "meta 字段缺失", section=section)
        return

    for field in META_REQUIRED:
        has = field in meta
        val = meta.get(field, "缺失")
        report.add(f"meta.{field}", has,
                   f"meta.{field} = {val}", section=section)

    # 类型检查
    report.add("meta.type == 'prd'", meta.get("type") == "prd",
               f"type = {meta.get('type', '?')}", section=section)
    report.add("meta.version >= 1", meta.get("version", 0) >= 1,
               f"version = {meta.get('version')}", section=section)
    report.add("meta.doc_id 不为空", bool(meta.get("doc_id")),
               f"doc_id = {meta.get('doc_id')}", section=section)


# ---------------------------------------------------------------------------
# 测试 4: 需求完整性
# ---------------------------------------------------------------------------

def test_requirements(prd: dict):
    section = "需求列表"
    requirements = prd.get("requirements", [])
    if not isinstance(requirements, list):
        report.add("requirements 是数组", False,
                   f"类型为 {type(requirements).__name__}", section=section)
        return

    count = len(requirements)
    report.add("需求数量合理", count >= 3,
               f"共 {count} 条需求 (预期 >=3)", section=section,
               severity="warning" if count < 3 else "error")

    req_ids: set[str] = set()
    seen_ids: set[str] = set()

    for i, req in enumerate(requirements):
        if not isinstance(req, dict):
            report.add(f"REQ[{i}] 是对象", False,
                       f"REQ[{i}] 类型为 {type(req).__name__}", section=section)
            continue

        req_id = req.get("id", f"缺失[{i}]")

        # 必填字段
        for field in REQUIREMENT_REQUIRED:
            has = field in req
            if not has:
                report.add(f"'{req_id}' 缺少 '{field}'", False,
                           f"需求 '{req_id}' 缺少必填字段 '{field}'", section=section)

        # ID 格式
        if req_id not in ("", "缺失"):
            if ID_PATTERN_REQ.match(req_id):
                if req_id in seen_ids:
                    report.add(f"'{req_id}' ID 重复", False,
                               f"需求 ID '{req_id}' 出现多次", section=section)
                seen_ids.add(req_id)
                req_ids.add(req_id)
            else:
                report.add(f"'{req_id}' ID 格式", False,
                           f"ID '{req_id}' 不匹配 REQ-NNN 格式", section=section)

        # 状态枚举
        status = req.get("status", "")
        if status and status not in REQUIREMENT_STATUSES:
            report.add(f"'{req_id}' status 合法", False,
                       f"status='{status}' 不在 {REQUIREMENT_STATUSES} 中",
                       section=section)

        # 优先级枚举
        priority = req.get("priority", "")
        if priority and priority not in REQUIREMENT_PRIORITIES:
            report.add(f"'{req_id}' priority 合法", False,
                       f"priority='{priority}' 不在 {REQUIREMENT_PRIORITIES} 中",
                       section=section)

        # 验收条件
        ac = req.get("acceptance_criteria", [])
        if isinstance(ac, list):
            report.add(f"'{req_id}' 有验收条件", len(ac) > 0,
                       f"{len(ac)} 条验收条件" if ac else "无验收条件",
                       section=section, severity="warning" if not ac else "error")

        # depends_on 引用的 ID 是否存在
        deps = req.get("depends_on", [])
        if isinstance(deps, list):
            for dep_id in deps:
                # 延迟检查，先收集
                pass

        # supersedes 引用的 ID 格式
        supers = req.get("supersedes", [])
        if isinstance(supers, list):
            for sid in supers:
                if not ID_PATTERN_REQ.match(sid):
                    report.add(f"'{req_id}' supersedes '{sid}' 格式", False,
                               f"supersedes 引用 '{sid}' 格式错误", section=section)

        # change_history
        history = req.get("change_history", [])
        if isinstance(history, list):
            report.add(f"'{req_id}' 有变更历史", len(history) > 0,
                       f"{len(history)} 条记录" if history else "无变更历史",
                       section=section,
                       severity="warning" if not history else "error")
            for ci, entry in enumerate(history):
                if isinstance(entry, dict):
                    for hf in ["version", "change_type", "summary", "reason"]:
                        if hf not in entry:
                            report.add(
                                f"'{req_id}' change_history[{ci}].{hf}",
                                False,
                                f"变更记录 #{ci} 缺少 '{hf}'",
                                section=section)
                    ct = entry.get("change_type", "")
                    if ct and ct not in REQUIREMENT_CHANGE_TYPES:
                        report.add(
                            f"'{req_id}' change_history[{ci}] change_type 合法",
                            False,
                            f"change_type='{ct}' 不在允许值中",
                            section=section)

    report.add("所有 REQ-ID 唯一", len(seen_ids) == count,
               f"{len(seen_ids)} 个唯一 ID / {count} 条需求", section=section)

    # 延迟检查 depends_on 引用
    for req in requirements:
        if not isinstance(req, dict):
            continue
        req_id = req.get("id", "?")
        deps = req.get("depends_on", [])
        if not isinstance(deps, list):
            continue
        for dep_id in deps:
            exists = dep_id in req_ids
            report.add(f"'{req_id}' depends_on '{dep_id}' 存在",
                       exists,
                       f"依赖 '{dep_id}' {'存在' if exists else '不存在'}于需求列表中",
                       section="需求依赖",
                       severity="error" if not exists else "error")

    return req_ids


# ---------------------------------------------------------------------------
# 测试 5: 用户故事质量
# ---------------------------------------------------------------------------

def test_user_stories(prd: dict, req_ids: set[str]):
    section = "用户故事"
    stories = prd.get("user_stories", [])
    if not isinstance(stories, list):
        report.add("user_stories 是数组", False,
                   f"类型为 {type(stories).__name__}", section=section)
        return

    count = len(stories)
    report.add("用户故事数量合理", count >= 2,
               f"共 {count} 个用户故事 (预期 >=2)", section=section,
               severity="warning" if count < 2 else "error")

    seen_ids: set[str] = set()

    for i, story in enumerate(stories):
        if not isinstance(story, dict):
            report.add(f"US[{i}] 是对象", False,
                       f"US[{i}] 类型为 {type(story).__name__}", section=section)
            continue

        us_id = story.get("id", f"缺失[{i}]")

        for field in USER_STORY_REQUIRED:
            has = field in story
            if not has:
                report.add(f"'{us_id}' 缺少 '{field}'", False,
                           f"用户故事 '{us_id}' 缺少必填字段 '{field}'",
                           section=section)

        # ID 格式
        if us_id != "缺失":
            if ID_PATTERN_US.match(us_id):
                if us_id in seen_ids:
                    report.add(f"'{us_id}' ID 重复", False,
                               f"ID '{us_id}' 出现多次", section=section)
                seen_ids.add(us_id)
            else:
                report.add(f"'{us_id}' ID 格式", False,
                           f"ID '{us_id}' 不匹配 US-NNN 格式", section=section)

        # role/action/goal 非空
        for field in ["role", "action", "goal"]:
            val = story.get(field, "")
            report.add(f"'{us_id}' {field} 非空", bool(val),
                       f"{field}='{val[:40]}...'" if len(val) > 40 else f"{field}='{val}'",
                       section=section)

        # related_requirements 引用有效性
        rel_reqs = story.get("related_requirements", [])
        if isinstance(rel_reqs, list):
            for rid in rel_reqs:
                exists = rid in req_ids
                report.add(f"'{us_id}' related_requirements '{rid}' 有效",
                           exists,
                           f"引用的需求 '{rid}' {'存在' if exists else '不存在'}",
                           section=section,
                           severity="warning" if not exists else "error")

    report.add("所有 US-ID 唯一", len(seen_ids) == count,
               f"{len(seen_ids)} 个唯一 ID / {count} 个故事", section=section)


# ---------------------------------------------------------------------------
# 测试 6: 优先级一致性
# ---------------------------------------------------------------------------

def test_priorities(prd: dict, req_ids: set[str]):
    section = "优先级"
    priorities = prd.get("priorities", {})
    if not isinstance(priorities, dict):
        report.add("priorities 是对象", False,
                   f"类型为 {type(priorities).__name__}", section=section)
        return

    # 检查 priorities 中的 key 是否都对应实际需求
    for rid, pri in priorities.items():
        valid_id = ID_PATTERN_REQ.match(rid)
        report.add(f"priorities key '{rid}' 格式正确", bool(valid_id),
                   f"'{rid}' {'格式正确' if valid_id else '格式错误'}",
                   section=section)

        valid_pri = pri in REQUIREMENT_PRIORITIES
        report.add(f"priorities['{rid}'] 值合法", valid_pri,
                   f"'{pri}' {'合法' if valid_pri else f'不在{REQUIREMENT_PRIORITIES}中'}",
                   section=section)

        if rid not in req_ids:
            report.add(f"priorities['{rid}'] 对应需求存在", False,
                       f"优先级映射引用了不存在的需求 '{rid}'",
                       section=section,
                       severity="warning" if rid.startswith("REQ-") else "error")

    # 反向检查: 每个需求都有优先级
    for rid in req_ids:
        has_pri = rid in priorities
        report.add(f"需求 '{rid}' 有优先级", has_pri,
                   f"'{rid}' {'有' if has_pri else '无'}优先级映射",
                   section=section,
                   severity="warning" if not has_pri else "error")

    # 高优先级数量统计
    high_count = sum(1 for v in priorities.values() if v == "高")
    report.add("高优先级需求数量", high_count > 0,
               f"{high_count} 个高优先级需求", section=section)


# ---------------------------------------------------------------------------
# 测试 7: overview 质量
# ---------------------------------------------------------------------------

def test_overview(prd: dict):
    section = "项目概述"
    overview = prd.get("overview", "")
    if not overview:
        report.add("overview 字段", False, "overview 为空", section=section)
        return

    report.add("overview 长度合理", len(overview) >= 30,
               f"overview 共 {len(overview)} 字符", section=section)

    # 关键要素覆盖
    elements = ["部署", "项目", "环境"]
    for elem in elements:
        has = elem in overview
        report.add(f"overview 含 '{elem}'", has,
                   f"overview {'包含' if has else '缺少'}'{elem}'",
                   section=section,
                   severity="warning" if not has else "error")


# ---------------------------------------------------------------------------
# 测试 8: 需求间逻辑关系
# ---------------------------------------------------------------------------

def test_requirement_relations(prd: dict, req_ids: set[str]):
    section = "需求关系"

    requirements = prd.get("requirements", [])
    if not requirements:
        return

    # 8.1 检测依赖环 (简单 BFS)
    deps_graph: dict[str, list[str]] = {}
    for req in requirements:
        if not isinstance(req, dict):
            continue
        rid = req.get("id", "")
        if rid:
            deps_graph[rid] = req.get("depends_on", [])

    cycles = _find_cycles(deps_graph)
    if cycles:
        report.add("无依赖环", False,
                   f"检测到依赖环: {cycles}", section=section)
    else:
        report.add("无依赖环", True,
                   "需求依赖关系中无环", section=section)

    # 8.2 supersedes 反向引用 (确保被替代的需求已经 deprecated)
    for req in requirements:
        if not isinstance(req, dict):
            continue
        supers = req.get("supersedes", [])
        if not supers:
            continue
        rid = req.get("id", "?")
        for sid in supers:
            deprecated = False
            for other in requirements:
                if other.get("id") == sid:
                    deprecated = other.get("status") in ("deprecated", "removed")
                    break
            report.add(f"'{rid}' supersedes '{sid}' 状态一致",
                       deprecated,
                       f"被替代的 '{sid}' 状态为"
                       f"{'deprecated/removed' if deprecated else '非deprecated'}",
                       section=section,
                       severity="warning" if not deprecated else "error")


def _find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """简单 DFS 检测有向图中的环。"""
    cycles: list[list[str]] = []
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(node: str):
        if node in stack:
            idx = stack.index(node)
            cycles.append(stack[idx:] + [node])
            return
        if node in visited or node not in graph:
            return
        visited.add(node)
        stack.append(node)
        for neighbor in graph.get(node, []):
            dfs(neighbor)
        stack.pop()

    for n in graph:
        if n not in visited:
            dfs(n)
    return cycles


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_all_tests(feature_desc: str, live_mode: bool = False):
    repo = find_repo_root()
    print(f"[INFO] 仓库根目录: {repo}")

    # ── 测试 1: 输入验证 ──
    print("[TEST] 1/8 输入特征描述语义覆盖...")
    test_feature_semantics(feature_desc)

    # ── 测试 2: PRD 文档存在性 ──
    print("[TEST] 2/8 PRD 文档加载...")
    prd = test_prd_existence(repo)
    if prd is None:
        if live_mode:
            print("[INFO] PRD 不存在，尝试实时生成...")
            prd = _generate_prd_live(repo, feature_desc)
        if prd is None:
            print("[FAIL] 无法加载或生成 PRD，后继测试全部跳过")
            print(report.summary())
            return 1

    # ── 测试 3: 顶层结构 ──
    print("[TEST] 3/8 顶层结构与 Meta 字段...")
    test_top_level_structure(prd)

    # ── 测试 4: 需求完整性 ──
    print("[TEST] 4/8 需求完整性验证...")
    req_ids = test_requirements(prd)

    # ── 测试 5: 用户故事 ──
    print("[TEST] 5/8 用户故事质量...")
    test_user_stories(prd, req_ids)

    # ── 测试 6: 优先级一致性 ──
    print("[TEST] 6/8 优先级一致性...")
    test_priorities(prd, req_ids)

    # ── 测试 7: overview ──
    print("[TEST] 7/8 项目概述质量...")
    test_overview(prd)

    # ── 测试 8: 需求关系 ──
    print("[TEST] 8/8 需求间逻辑关系...")
    test_requirement_relations(prd, req_ids)

    # ── 输出报告 ──
    print()
    print(report.summary())

    out_dir = tests_dir(repo)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "pm_test_report.json"
    json_report = {
        "timestamp": datetime.now().isoformat(),
        "feature": feature_desc,
        "live_mode": live_mode,
        "prd_title": prd.get("meta", {}).get("title", "?") if prd else "N/A",
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


def _generate_prd_live(repo: Path, feature_desc: str) -> Optional[dict]:
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, "-m", "cogniforge", "agent", "pm",
             "--raw", feature_desc],
            cwd=str(repo), capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"  [WARN] PMAgent 调用失败: {result.stderr[:200]}")
            return None
        return load_prd(repo)
    except FileNotFoundError:
        print("  [WARN] cogniforge CLI 不可用，跳过实时生成")
        return None
    except subprocess.TimeoutExpired:
        print("  [WARN] PMAgent 调用超时")
        return None


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PM (Product Manager) 角色测试脚本")
    parser.add_argument("--live", action="store_true",
                        help="实时调用 LLM 生成缺失的 PRD 文档")
    parser.add_argument("--report-only", action="store_true",
                        help="仅输出已有 PRD 的检查报告")
    parser.add_argument("--feature", type=str, default=None,
                        help="自定义特征描述文件路径")
    args = parser.parse_args()

    feature = FEATURE_DESCRIPTION
    if args.feature:
        fp = Path(args.feature)
        if fp.exists():
            feature = fp.read_text(encoding="utf-8")
        else:
            print(f"[ERROR] 文件不存在: {args.feature}")
            sys.exit(1)

    print("=" * 70)
    print("  CogniForge PM 角色测试")
    print("=" * 70)
    print(f"  模式: {'实时 LLM 生成' if args.live else '机械验证'}")
    print(f"  特征: {feature[:80]}...")
    print()

    exit_code = run_all_tests(feature, live_mode=args.live)
    sys.exit(exit_code)
