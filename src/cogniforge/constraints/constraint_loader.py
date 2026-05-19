"""Constraint loader — reads per-role .md files, falls back to built-in defaults."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Built-in default constraints for each role
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, str] = {
    "pm": (
        "# PM Agent 约束\n\n"
        "## 输出格式\n"
        "- 生成 JSON 格式的 PRD 文档\n"
        "- 不要写入 HTML 文件（HTML 由系统自动渲染）\n\n"
        "## 风格\n"
        "- 先阅读已有 PRD 了解文档风格\n\n"
        "## 语言\n"
        "- 所有文字使用中文\n"
    ),
    "architect": (
        "# Architect Agent 约束\n\n"
        "## 输出要求\n"
        "- 先阅读 PRD 了解产品需求\n"
        "- 包含组件设计、拓扑结构、数据流描述\n"
        "- 生成 JSON 格式\n\n"
        "## 语言\n"
        "- 使用中文\n"
    ),
    "design": (
        "# Design Agent 约束\n\n"
        "## 输出要求\n"
        "- 先阅读 PRD 和 SAD 了解上下文\n"
        "- 包含数据模型、接口定义、错误处理\n"
        "- 生成 JSON 格式\n\n"
        "## 语言\n"
        "- 使用中文\n"
    ),
    "dev": (
        "# Dev Agent 约束\n\n"
        "## 编码原则\n"
        "- 简单优先：用最少代码解决问题，不加不必要的抽象或配置项\n"
        "- 精准修改：只改必须改的，不重构没坏的东西，匹配现有代码风格\n"
        "- 目标驱动：每个实现都要有明确的验证标准\n"
        "- 不推测：不确定时先确认，不要静默选择\n\n"
        "## 技术要求\n"
        "- 遵循 Python 最佳实践，使用 type hints\n"
        "- 代码写完后运行 pytest 验证\n\n"
        "## 语言\n"
        "- 使用中文\n"
    ),
    "reviewer": (
        "# Reviewer Agent 约束\n\n"
        "## 审查要点\n"
        "- 代码是否符合 LLD 设计意图\n"
        "- 是否存在安全漏洞\n"
        "- 代码是否简洁（不过度抽象）\n"
        "- 开发约束是否被遵守（简单优先/精准修改/目标驱动/不推测）\n\n"
        "## 输出格式\n"
        "- 生成 CR 报告，使用 PASS/FAIL 标注每项检查\n\n"
        "## 语言\n"
        "- 使用中文\n"
    ),
    "qa": (
        "# QA Agent 约束\n\n"
        "## 测试覆盖\n"
        "- 正常路径\n"
        "- 边界条件\n"
        "- 错误路径\n\n"
        "## 输出\n"
        "- 生成测试用例 JSON\n"
        "- 执行测试并生成报告\n\n"
        "## 语言\n"
        "- 使用中文\n"
    ),
    "techlead": (
        "# Tech Lead Agent 约束\n\n"
        "## 工作分解\n"
        "- 阅读全部上下文（PRD、SAD、LLD）\n"
        "- 按依赖关系排序任务\n"
        "- 评估每项工作的复杂度\n\n"
        "## 语言\n"
        "- 使用中文\n"
    ),
    "devops": (
        "# DevOps Agent 约束\n\n"
        "## 部署配置\n"
        "- 阅读 SAD 和 LLD 了解架构\n"
        "- 包含 Docker 配置\n"
        "- 包含环境变量\n"
        "- 包含健康检查\n\n"
        "## 语言\n"
        "- 使用中文\n"
    ),
}

# ---------------------------------------------------------------------------
# ConstraintLoader
# ---------------------------------------------------------------------------


class ConstraintLoader:
    """Load per-role behavioral constraints.

    Reads from .cogniforge/constraints/{role}.md, falling back to built-in defaults
    when the file doesn't exist.
    """

    def __init__(self, repo_path: str | Path) -> None:
        self.repo_path = Path(repo_path)
        self._cache: dict[str, str] = {}

    @property
    def constraints_dir(self) -> Path:
        return self.repo_path / ".cogniforge" / "constraints"

    def load(self, role: str) -> str:
        """Load constraints for a role. File first, default as fallback."""
        if role in self._cache:
            return self._cache[role]

        file_path = self.constraints_dir / f"{role}.md"
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8").strip()
        else:
            content = DEFAULTS.get(role, "").strip()

        self._cache[role] = content
        return content

    def init_all(self) -> list[Path]:
        """Generate default constraint files for all roles.

        Only creates files that don't already exist (won't overwrite user edits).
        Returns list of created file paths.
        """
        self.constraints_dir.mkdir(parents=True, exist_ok=True)
        created: list[Path] = []

        for role, content in DEFAULTS.items():
            file_path = self.constraints_dir / f"{role}.md"
            if not file_path.exists():
                file_path.write_text(content, encoding="utf-8")
                created.append(file_path)

        # Clear cache so next load picks up the new files
        self._cache.clear()
        return created
